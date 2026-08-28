from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from packaging.version import InvalidVersion, Version

from .database import (
    connect,
    export_snapshot_parquet,
    initialize_database,
    insert_node,
    metric_map,
    populate_metrics,
    stable_id,
)
from .github_client import GitHubClient, Repository, matching_paths
from .model import EdgeType, NodeType
from .parsers import Package, ParsedManifest, parse_manifest
from .thumbnails import write_ring_thumbnail

SUPPORTED_PATTERNS = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "poetry.lock",
    "requirements*.txt",
    "packages.lock.json",
    "Directory.Packages.props",
    "*.csproj",
    "*.fsproj",
    "*.vbproj",
)


def ingest_repositories(
    client: GitHubClient,
    account: dict[str, Any],
    repositories: Iterable[Repository],
    output_root: Path,
) -> tuple[Path, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    db_path = output_root / "dependency-explorer.duckdb"
    connection = connect(db_path)
    initialize_database(connection)
    captured_at = datetime.now(UTC).replace(microsecond=0)
    snapshot_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
        [
            snapshot_id,
            captured_at,
            "github",
            json.dumps({"collector": "scg-ingest", "schema_version": 1}),
        ],
    )
    account_id = stable_id("github-account", str(account["id"]))
    insert_node(
        connection,
        snapshot_id,
        account_id,
        NodeType.ACCOUNT,
        account.get("name") or account["login"],
        metadata={
            "login": account["login"],
            "account_subtype": account.get("type", "User").lower(),
        },
    )
    for repository in repositories:
        _ingest_repository(connection, client, snapshot_id, account_id, repository)
    _enrich(connection, snapshot_id)
    populate_metrics(connection, snapshot_id)
    thumbnail_root = output_root / "thumbnails"
    for (node_id,) in connection.execute(
        "SELECT node_id FROM nodes WHERE snapshot_id = ?", [snapshot_id]
    ).fetchall():
        write_ring_thumbnail(
            thumbnail_root / f"{node_id}.png",
            metric_map(connection, snapshot_id, node_id),
        )
    export_snapshot_parquet(
        connection, snapshot_id, output_root / "parquet" / snapshot_id
    )
    connection.close()
    return db_path, snapshot_id


def _ingest_repository(
    connection: Any,
    client: GitHubClient,
    snapshot_id: str,
    account_id: str,
    repository: Repository,
) -> None:
    repo_id = stable_id("github-repository", str(repository.repo_id))
    insert_node(
        connection,
        snapshot_id,
        repo_id,
        NodeType.REPOSITORY,
        repository.name,
        metadata={
            "full_name": repository.full_name,
            "visibility": "private" if repository.private else "public",
            "default_branch": repository.default_branch,
            "url": repository.html_url,
        },
    )
    connection.execute(
        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
        [snapshot_id, account_id, repo_id, EdgeType.OWNS, False, "{}"],
    )
    try:
        tree = client.tree(repository.full_name, repository.default_branch)
        paths = matching_paths(tree, SUPPORTED_PATTERNS)
    except Exception as exc:  # noqa: BLE001 - isolate one inaccessible repository
        _issue(connection, snapshot_id, repo_id, None, "tree_unavailable", str(exc))
        paths = []
    for path in paths:
        try:
            parsed = parse_manifest(
                path,
                client.content(repository.full_name, path, repository.default_branch),
            )
            _store_manifest(connection, snapshot_id, repo_id, repository, parsed)
        except Exception as exc:  # noqa: BLE001 - record malformed third-party input
            _issue(
                connection,
                snapshot_id,
                repo_id,
                path,
                "manifest_parse_failed",
                str(exc),
            )
    try:
        sbom = client.sbom(repository.full_name)
        _store_sbom(connection, snapshot_id, repo_id, repository, sbom)
    except Exception as exc:  # noqa: BLE001 - SBOM support varies by repository
        _issue(
            connection,
            snapshot_id,
            repo_id,
            None,
            "sbom_unavailable",
            str(exc),
            severity="warning",
        )


def _store_manifest(
    connection: Any,
    snapshot_id: str,
    repo_id: str,
    repository: Repository,
    parsed: ParsedManifest,
) -> None:
    manifest_id = stable_id("manifest", str(repository.repo_id), parsed.path)
    connection.execute(
        "INSERT OR IGNORE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            manifest_id,
            NodeType.MANIFEST,
            parsed.path.rsplit("/", 1)[-1],
            parsed.ecosystem,
            None,
            json.dumps(
                {
                    "path": parsed.path,
                    "parser": parsed.parser,
                    "complete": parsed.complete,
                }
            ),
        ],
    )
    connection.execute(
        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
        [snapshot_id, repo_id, manifest_id, EdgeType.CONTAINS, False, "{}"],
    )
    by_name: dict[str, str] = {}
    for package in parsed.packages:
        dependency_id = _store_package(connection, snapshot_id, package)
        by_name[package.name.casefold()] = dependency_id
        if package.direct:
            connection.execute(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                [
                    snapshot_id,
                    manifest_id,
                    dependency_id,
                    EdgeType.DEPENDS_ON,
                    True,
                    json.dumps({"source": parsed.parser}),
                ],
            )
    for package in parsed.packages:
        source = by_name.get(package.name.casefold())
        if not source:
            continue
        for child_name, _ in package.dependencies:
            target = by_name.get(child_name.casefold())
            if target and source != target:
                connection.execute(
                    "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        snapshot_id,
                        source,
                        target,
                        EdgeType.DEPENDS_ON,
                        False,
                        json.dumps({"source": parsed.parser}),
                    ],
                )
    for warning in parsed.warnings:
        _issue(
            connection,
            snapshot_id,
            repo_id,
            parsed.path,
            "partial_resolution",
            warning,
            severity="warning",
        )


def _store_package(connection: Any, snapshot_id: str, package: Package) -> str:
    dependency_id = stable_id(
        "dependency",
        package.ecosystem.casefold(),
        package.name.casefold(),
        package.version,
    )
    purl_type = {"PyPI": "pypi", "NuGet": "nuget"}.get(package.ecosystem, "npm")
    connection.execute(
        "INSERT OR IGNORE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            dependency_id,
            NodeType.DEPENDENCY,
            package.name,
            package.ecosystem,
            package.version,
            json.dumps({"purl": f"pkg:{purl_type}/{package.name}@{package.version}"}),
        ],
    )
    return dependency_id


def _store_sbom(
    connection: Any,
    snapshot_id: str,
    repo_id: str,
    repository: Repository,
    sbom: dict[str, Any],
) -> None:
    packages = sbom.get("packages", [])
    if not packages:
        return
    manifest_id = stable_id(
        "manifest", str(repository.repo_id), "github-sbom.spdx.json"
    )
    connection.execute(
        "INSERT OR IGNORE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            manifest_id,
            NodeType.MANIFEST,
            "GitHub dependency graph",
            "SPDX",
            None,
            json.dumps(
                {
                    "path": "github-sbom.spdx.json",
                    "parser": "github-spdx",
                    "complete": True,
                }
            ),
        ],
    )
    connection.execute(
        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
        [snapshot_id, repo_id, manifest_id, EdgeType.CONTAINS, False, "{}"],
    )
    refs: dict[str, str] = {}
    for record in packages:
        name, version = record.get("name"), record.get("versionInfo")
        purl = _external_purl(record)
        if not name or not version or not purl:
            continue
        ecosystem = _ecosystem_from_purl(purl)
        dependency_id = _store_package(
            connection, snapshot_id, Package(name, version, ecosystem)
        )
        refs[record.get("SPDXID", "")] = dependency_id
    described_ids = {
        relationship.get("relatedSpdxElement")
        for relationship in sbom.get("relationships", [])
        if relationship.get("relationshipType") == "DESCRIBES"
    }
    for relationship in sbom.get("relationships", []):
        source_ref, target_ref = (
            relationship.get("spdxElementId"),
            relationship.get("relatedSpdxElement"),
        )
        if relationship.get("relationshipType") != "DEPENDS_ON":
            continue
        target = refs.get(target_ref)
        if not target:
            continue
        source = refs.get(source_ref)
        if source and source != target:
            connection.execute(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                [
                    snapshot_id,
                    source,
                    target,
                    EdgeType.DEPENDS_ON,
                    False,
                    json.dumps({"source": "github-spdx"}),
                ],
            )
        if source_ref in described_ids:
            connection.execute(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                [
                    snapshot_id,
                    manifest_id,
                    target,
                    EdgeType.DEPENDS_ON,
                    True,
                    json.dumps({"source": "github-spdx"}),
                ],
            )


def _external_purl(record: dict[str, Any]) -> str | None:
    for reference in record.get("externalRefs", []):
        locator = reference.get("referenceLocator", "")
        if locator.startswith("pkg:"):
            return locator
    return None


def _ecosystem_from_purl(purl: str) -> str:
    kind = purl.removeprefix("pkg:").split("/", 1)[0].casefold()
    return {"pypi": "PyPI", "nuget": "NuGet", "npm": "npm"}.get(kind, kind)


def _enrich(connection: Any, snapshot_id: str) -> None:
    rows = connection.execute(
        "SELECT node_id, name, ecosystem, version FROM nodes WHERE snapshot_id = ? AND node_type = 'dependency'",
        [snapshot_id],
    ).fetchall()
    with httpx.Client(
        timeout=20, headers={"User-Agent": "streamlit-canvas-graph"}
    ) as client:
        with ThreadPoolExecutor(max_workers=16) as executor:
            latest_versions = list(
                executor.map(lambda row: _latest_version(client, row[2], row[1]), rows)
            )
        for (node_id, _name, _ecosystem, version), latest in zip(
            rows, latest_versions, strict=True
        ):
            update_kind = classify_update(version, latest) if latest else None
            connection.execute(
                "INSERT OR REPLACE INTO package_versions VALUES (?, ?, ?, ?, ?, ?)",
                [snapshot_id, node_id, version, latest, update_kind, "registry"],
            )
        for offset in range(0, len(rows), 1000):
            batch = rows[offset : offset + 1000]
            try:
                response = client.post(
                    "https://api.osv.dev/v1/querybatch",
                    json={
                        "queries": [
                            {
                                "version": version,
                                "package": {"name": name, "ecosystem": ecosystem},
                            }
                            for _node_id, name, ecosystem, version in batch
                        ]
                    },
                )
                response.raise_for_status()
                results = response.json().get("results", [])
            except httpx.HTTPError:
                continue
            for (node_id, _name, _ecosystem, _version), result in zip(
                batch, results, strict=False
            ):
                for vulnerability in result.get("vulns", []):
                    severity, cvss = _osv_severity(vulnerability)
                    connection.execute(
                        "INSERT OR IGNORE INTO vulnerabilities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            snapshot_id,
                            node_id,
                            vulnerability["id"],
                            severity,
                            cvss,
                            vulnerability.get("summary") or vulnerability["id"],
                            None,
                            _fixed_version(vulnerability),
                            f"https://osv.dev/vulnerability/{vulnerability['id']}",
                            json.dumps({"aliases": vulnerability.get("aliases", [])}),
                        ],
                    )


def _latest_version(client: httpx.Client, ecosystem: str, name: str) -> str | None:
    try:
        if ecosystem == "npm":
            data = client.get(
                f"https://registry.npmjs.org/{quote(name, safe='@')}/latest"
            ).json()
            return data.get("version")
        if ecosystem == "PyPI":
            return (
                client.get(f"https://pypi.org/pypi/{quote(name)}/json")
                .json()
                .get("info", {})
                .get("version")
            )
        if ecosystem == "NuGet":
            versions = (
                client.get(
                    f"https://api.nuget.org/v3-flatcontainer/{quote(name.casefold())}/index.json"
                )
                .json()
                .get("versions", [])
            )
            stable = [value for value in versions if "-" not in value]
            return stable[-1] if stable else None
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return None


def classify_update(current: str, latest: str | None) -> str | None:
    if not latest:
        return None
    try:
        current_version, latest_version = Version(current), Version(latest)
    except InvalidVersion:
        return None
    if latest_version <= current_version:
        return None
    if latest_version.major != current_version.major:
        return "major"
    if latest_version.minor != current_version.minor:
        return "minor"
    return "patch"


def _osv_severity(vulnerability: dict[str, Any]) -> tuple[str, float | None]:
    scores = vulnerability.get("severity", [])
    cvss: float | None = None
    for score in scores:
        match = re.search(r"CVSS:[^ ]+", score.get("score", ""))
        if match:
            metrics = match.group(0).split("/")
            # OSV often supplies vectors rather than base scores; preserve unknown score.
            cvss = next(
                (
                    float(item)
                    for item in metrics
                    if re.fullmatch(r"\d+(?:\.\d+)?", item)
                ),
                None,
            )
    severity = (
        "critical"
        if cvss and cvss >= 9
        else "high"
        if cvss and cvss >= 7
        else "medium"
        if cvss and cvss >= 4
        else "low"
    )
    return severity, cvss


def _fixed_version(vulnerability: dict[str, Any]) -> str | None:
    fixed = [
        event["fixed"]
        for affected in vulnerability.get("affected", [])
        for range_ in affected.get("ranges", [])
        for event in range_.get("events", [])
        if "fixed" in event
    ]
    return min(fixed) if fixed else None


def _issue(
    connection: Any,
    snapshot_id: str,
    repo_id: str | None,
    path: str | None,
    code: str,
    message: str,
    *,
    severity: str = "error",
) -> None:
    sanitized = redact_secrets(message)
    connection.execute(
        "INSERT INTO ingestion_issues VALUES (?, ?, ?, ?, ?, ?)",
        [snapshot_id, repo_id, path, severity, code, sanitized[:2000]],
    )


def redact_secrets(message: str) -> str:
    """Redact credential shapes before text reaches logs or snapshot data."""
    patterns = (
        (r"(?i)(token|authorization|bearer)\s*[:=]?\s*\S+", r"\1=[REDACTED]"),
        (r"github_pat_[A-Za-z0-9_]+", "github_pat_[REDACTED]"),
        (r"gh[oprsu]_[A-Za-z0-9]+", "ghx_[REDACTED]"),
        (r"https?://[^/@\s:]+:[^/@\s]+@", "https://[REDACTED]@"),
        (r"AKIA[0-9A-Z]{16}", "AKIA[REDACTED]"),
    )
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message)
    return message
