from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .github_client import GitHubClient, GitHubError, matching_paths

ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-3-Clause", "Artistic-2.0"}


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    source: str
    ecosystem: str
    patterns: tuple[str, ...]
    license: str
    complexity: str
    note: str
    default_selected: bool

    @property
    def full_name(self) -> str:
        path = urlparse(self.source).path.strip("/").removesuffix(".git")
        if path.count("/") != 1:
            raise ValueError(f"Invalid GitHub repository URL: {self.source}")
        return path


@dataclass(frozen=True, slots=True)
class Preflight:
    entry: CatalogEntry
    available: bool
    default_branch: str | None
    head_sha: str | None
    size_kb: int | None
    detected_license: str | None
    matching_manifests: tuple[str, ...]
    reason: str | None = None


def load_catalog(path: Path) -> list[CatalogEntry]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("Unsupported repository catalog version")
    entries = []
    for row in payload.get("repositories", []):
        entry = CatalogEntry(
            row["source"],
            row["ecosystem"],
            tuple(row["patterns"]),
            row["license"],
            row["complexity"],
            row["note"],
            bool(row["default_selected"]),
        )
        if entry.license not in ALLOWED_LICENSES:
            raise ValueError(f"Catalog license is not allowlisted: {entry.license}")
        entries.append(entry)
    if len(entries) != 12:
        raise ValueError(f"Expected 12 curated repositories, found {len(entries)}")
    return entries


def preflight(client: GitHubClient, entry: CatalogEntry) -> Preflight:
    try:
        repository = client.repository(entry.full_name)
        if repository.get("private"):
            return Preflight(
                entry,
                False,
                None,
                None,
                repository.get("size"),
                None,
                (),
                "source is not public",
            )
        branch = repository["default_branch"]
        tree = client.tree(entry.full_name, branch)
        manifests = tuple(matching_paths(tree, entry.patterns))
        license_payload = client.license(entry.full_name)
        detected_license = license_payload.get("license", {}).get("spdx_id")
        sha = client.get(f"/repos/{entry.full_name}/commits/{branch}")["sha"]
        if detected_license not in ALLOWED_LICENSES:
            return Preflight(
                entry,
                False,
                branch,
                sha,
                repository.get("size"),
                detected_license,
                manifests,
                "detected license is not allowlisted",
            )
        if not manifests:
            return Preflight(
                entry,
                False,
                branch,
                sha,
                repository.get("size"),
                detected_license,
                (),
                "no expected manifest or lockfile found",
            )
        return Preflight(
            entry,
            True,
            branch,
            sha,
            repository.get("size"),
            detected_license,
            manifests,
        )
    except (GitHubError, KeyError, ValueError) as exc:
        return Preflight(entry, False, None, None, None, None, (), str(exc))


def destination_name(prefix: str, entry: CatalogEntry) -> str:
    clean_prefix = re.sub(r"[^a-z0-9-]+", "-", prefix.casefold()).strip("-")
    source_name = re.sub(
        r"[^a-z0-9-]+", "-", entry.full_name.split("/")[-1].casefold()
    ).strip("-")
    if not clean_prefix:
        raise ValueError("Prefix must contain at least one letter or digit")
    return f"{clean_prefix}-{entry.ecosystem.casefold()}-{source_name}"[:100].rstrip(
        "-"
    )


def provision(
    client: GitHubClient,
    token: str,
    owner: str,
    check: Preflight,
    prefix: str,
    manifest_path: Path,
) -> dict[str, Any]:
    if not check.available or not check.default_branch or not check.head_sha:
        raise ValueError(
            f"Cannot provision unavailable source: {check.entry.full_name}"
        )
    name = destination_name(prefix, check.entry)
    try:
        client.repository(f"{owner}/{name}")
    except GitHubError:
        pass
    else:
        raise ValueError(f"Destination already exists: {owner}/{name}")
    created = client.create_private_repository(
        name, f"Private dependency-explorer test copy of {check.entry.source}"
    )
    try:
        _copy_default_branch(
            check.entry.source, check.default_branch, created["clone_url"], token
        )
    except Exception:
        try:
            client.delete_repository(created["full_name"])
        except GitHubError:
            pass
        raise
    record = {
        "source": check.entry.source,
        "source_sha": check.head_sha,
        "destination_id": created["id"],
        "destination_full_name": created["full_name"],
        "destination_url": created["html_url"],
        "license": check.detected_license,
        "ecosystem": check.entry.ecosystem,
        "created_at": datetime.now(UTC).isoformat(),
        "removed_at": None,
    }
    _append_manifest(manifest_path, record)
    return record


def cleanup(
    client: GitHubClient, manifest_path: Path, full_names: set[str]
) -> list[str]:
    payload = _read_manifest(manifest_path)
    allowed = {
        row["destination_full_name"]
        for row in payload["repositories"]
        if not row.get("removed_at")
    }
    if not full_names <= allowed:
        raise ValueError(
            "Cleanup requested a repository not present as active in the local provisioning manifest"
        )
    removed_at = datetime.now(UTC).isoformat()
    for full_name in sorted(full_names):
        client.delete_repository(full_name)
        for row in payload["repositories"]:
            if row["destination_full_name"] == full_name and not row.get("removed_at"):
                row["removed_at"] = removed_at
    _write_manifest(manifest_path, payload)
    return sorted(full_names)


def active_provisioned(manifest_path: Path) -> list[dict[str, Any]]:
    return [
        row
        for row in _read_manifest(manifest_path)["repositories"]
        if not row.get("removed_at")
    ]


def _copy_default_branch(
    source: str, branch: str, destination: str, token: str
) -> None:
    with tempfile.TemporaryDirectory(prefix="scg-provision-") as temporary:
        root = Path(temporary)
        checkout = root / "source"
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                branch,
                source,
                str(checkout),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        shutil.rmtree(checkout / ".git")
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=checkout,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "config", "user.name", "Dependency Explorer Provisioner"],
            cwd=checkout,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "noreply@localhost"],
            cwd=checkout,
            check=True,
        )
        subprocess.run(["git", "add", "--all"], cwd=checkout, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Create private dependency-explorer test copy"],
            cwd=checkout,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", destination], cwd=checkout, check=True
        )
        askpass = root / "askpass.sh"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in *Username*) printf "%s" "x-access-token";; *) printf "%s" "$SCG_GIT_TOKEN";; esac\n',
            encoding="utf-8",
        )
        askpass.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_ASKPASS": str(askpass),
                "GIT_TERMINAL_PROMPT": "0",
                "SCG_GIT_TOKEN": token,
            }
        )
        subprocess.run(
            ["git", "push", "--set-upstream", "origin", "main"],
            cwd=checkout,
            check=True,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "repositories": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("repositories"), list):
        raise ValueError("Invalid provisioning manifest")
    return payload


def _append_manifest(path: Path, record: dict[str, Any]) -> None:
    payload = _read_manifest(path)
    payload["repositories"].append(record)
    _write_manifest(path, payload)


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
