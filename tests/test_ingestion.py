import hashlib
import json
from datetime import UTC, datetime

import pytest

from streamlit_canvas_graph.database import (
    connect,
    initialize_database,
    insert_node,
)
from streamlit_canvas_graph.github_client import Repository
from streamlit_canvas_graph.ingestion import (
    _ingest_repository,
    _store_manifest,
    _validate_dependency_provenance,
    ingest_repositories,
    redact_secrets,
)
from streamlit_canvas_graph.model import NodeType
from streamlit_canvas_graph.parsers import Package, ParsedManifest, parse_manifest


def test_manifest_edges_include_only_direct_dependencies(tmp_path) -> None:
    connection = connect(tmp_path / "test.duckdb")
    initialize_database(connection)
    snapshot_id = "snapshot"
    repository_id = "repository"
    connection.execute(
        "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
        [snapshot_id, datetime.now(UTC), "test", "{}"],
    )
    insert_node(
        connection,
        snapshot_id,
        repository_id,
        NodeType.REPOSITORY,
        "example",
    )
    repository = Repository(
        1,
        "example/repository",
        "repository",
        "example",
        True,
        False,
        "main",
        1,
        "https://github.com/example/repository",
    )
    parsed = ParsedManifest(
        "package-lock.json",
        "npm",
        "package-lock",
        [
            Package("direct", "1.0.0", "npm", True, [("transitive", "^2")]),
            Package("transitive", "2.0.0", "npm", False),
        ],
    )

    _store_manifest(
        connection,
        snapshot_id,
        repository_id,
        repository,
        parsed,
    )
    edges = connection.execute(
        """
        SELECT source.name, target.name, edges.is_direct
        FROM edges
        JOIN nodes source ON source.snapshot_id = edges.snapshot_id
                         AND source.node_id = edges.source_id
        JOIN nodes target ON target.snapshot_id = edges.snapshot_id
                         AND target.node_id = edges.target_id
        WHERE edges.snapshot_id = ? AND edges.edge_type = 'depends_on'
        ORDER BY source.name, target.name
        """,
        [snapshot_id],
    ).fetchall()
    connection.close()

    assert edges == [
        ("direct", "transitive", False),
        ("package-lock.json", "direct", True),
    ]


def test_manifest_provenance_anchors_every_dependency_component(tmp_path) -> None:
    connection = connect(tmp_path / "test.duckdb")
    initialize_database(connection)
    snapshot_id = "snapshot"
    repository_id = "repository"
    connection.execute(
        "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
        [snapshot_id, datetime.now(UTC), "test", "{}"],
    )
    insert_node(
        connection,
        snapshot_id,
        repository_id,
        NodeType.REPOSITORY,
        "example",
    )
    repository = Repository(
        1,
        "example/repository",
        "repository",
        "example",
        True,
        False,
        "main",
        1,
        "https://github.com/example/repository",
    )
    parsed = parse_manifest(
        "uv.lock",
        """
        [[package]]
        name = "project"
        version = "0.1.0"
        source = { editable = "." }
        dependencies = [{ name = "direct" }]

        [[package]]
        name = "direct"
        version = "1.0.0"
        dependencies = [{ name = "direct-child" }]

        [[package]]
        name = "direct-child"
        version = "2.0.0"

        [[package]]
        name = "orphan-root"
        version = "1.0.0"
        dependencies = [{ name = "orphan-child" }]

        [[package]]
        name = "orphan-child"
        version = "2.0.0"

        [[package]]
        name = "standalone"
        version = "1.0.0"

        [[package]]
        name = "cycle-a"
        version = "1.0.0"
        dependencies = [{ name = "cycle-b" }]

        [[package]]
        name = "cycle-b"
        version = "1.0.0"
        dependencies = [{ name = "cycle-a" }]
        """,
    )

    _store_manifest(
        connection,
        snapshot_id,
        repository_id,
        repository,
        parsed,
        content_sha256="abc123",
    )

    resolved_names = {
        row[0]
        for row in connection.execute(
            """
            SELECT target.name
            FROM edges
            JOIN nodes target ON target.snapshot_id = edges.snapshot_id
                             AND target.node_id = edges.target_id
            WHERE edges.snapshot_id = ? AND edges.edge_type = 'resolves'
            """,
            [snapshot_id],
        ).fetchall()
    }
    direct_names = {
        row[0]
        for row in connection.execute(
            """
            SELECT target.name
            FROM edges
            JOIN nodes target ON target.snapshot_id = edges.snapshot_id
                             AND target.node_id = edges.target_id
            WHERE edges.snapshot_id = ?
              AND edges.edge_type = 'depends_on'
              AND edges.is_direct
            """,
            [snapshot_id],
        ).fetchall()
    }
    manifest_metadata = json.loads(
        connection.execute(
            "SELECT metadata FROM nodes WHERE snapshot_id = ? AND node_type = 'manifest'",
            [snapshot_id],
        ).fetchone()[0]
    )

    _validate_dependency_provenance(connection, snapshot_id)
    connection.close()

    assert "orphan-root" in resolved_names
    assert "standalone" in resolved_names
    assert len(resolved_names & {"cycle-a", "cycle-b"}) == 1
    assert direct_names == {"direct"}
    assert manifest_metadata["content_sha256"] == "abc123"


def test_provenance_validation_rejects_unreachable_dependency(tmp_path) -> None:
    connection = connect(tmp_path / "test.duckdb")
    initialize_database(connection)
    snapshot_id = "snapshot"
    connection.execute(
        "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
        [snapshot_id, datetime.now(UTC), "test", "{}"],
    )
    insert_node(
        connection,
        snapshot_id,
        "manifest",
        NodeType.MANIFEST,
        "uv.lock",
    )
    insert_node(
        connection,
        snapshot_id,
        "orphan",
        NodeType.DEPENDENCY,
        "orphan",
        "PyPI",
        "1.0.0",
    )

    with pytest.raises(RuntimeError, match="orphan@1.0.0"):
        _validate_dependency_provenance(connection, snapshot_id)

    connection.close()


def test_repository_ingestion_is_pinned_to_commit_and_hashes_manifest(
    tmp_path,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.refs: list[str] = []

        def commit_sha(self, full_name: str, ref: str) -> str:
            assert full_name == "example/repository"
            assert ref == "main"
            return "commit-sha"

        def tree(self, full_name: str, ref: str) -> list[dict[str, str]]:
            self.refs.append(ref)
            return [{"path": "requirements.txt", "type": "blob"}]

        def content(self, full_name: str, path: str, ref: str) -> str:
            self.refs.append(ref)
            return "requests==2.0.0\n"

        def sbom(self, full_name: str) -> dict[str, object]:
            return {}

    connection = connect(tmp_path / "test.duckdb")
    initialize_database(connection)
    snapshot_id = "snapshot"
    account_id = "account"
    connection.execute(
        "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
        [snapshot_id, datetime.now(UTC), "test", "{}"],
    )
    insert_node(connection, snapshot_id, account_id, NodeType.ACCOUNT, "example")
    repository = Repository(
        1,
        "example/repository",
        "repository",
        "example",
        True,
        False,
        "main",
        1,
        "https://github.com/example/repository",
    )
    client = Client()

    _ingest_repository(
        connection,
        client,  # type: ignore[arg-type]
        snapshot_id,
        account_id,
        repository,
    )

    repository_metadata = json.loads(
        connection.execute(
            "SELECT metadata FROM nodes WHERE snapshot_id = ? AND node_type = 'repository'",
            [snapshot_id],
        ).fetchone()[0]
    )
    manifest_metadata = json.loads(
        connection.execute(
            "SELECT metadata FROM nodes WHERE snapshot_id = ? AND node_type = 'manifest'",
            [snapshot_id],
        ).fetchone()[0]
    )
    connection.close()

    assert client.refs == ["commit-sha", "commit-sha"]
    assert repository_metadata["commit_sha"] == "commit-sha"
    assert (
        manifest_metadata["content_sha256"]
        == hashlib.sha256(b"requests==2.0.0\n").hexdigest()
    )


def test_failed_provenance_gate_rolls_back_snapshot(tmp_path, monkeypatch) -> None:
    def fail_validation(connection, snapshot_id: str) -> None:
        raise RuntimeError(f"invalid snapshot {snapshot_id}")

    monkeypatch.setattr(
        "streamlit_canvas_graph.ingestion._validate_dependency_provenance",
        fail_validation,
    )

    with pytest.raises(RuntimeError, match="invalid snapshot"):
        ingest_repositories(
            object(),  # type: ignore[arg-type]
            {"id": 1, "login": "example", "type": "User"},
            [],
            tmp_path,
        )

    connection = connect(tmp_path / "dependency-explorer.duckdb")
    assert connection.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 0
    connection.close()


def test_redact_secrets_covers_common_credential_shapes() -> None:
    aws_key = "AKIA" + "1234567890ABCDEF"
    message = (
        "token=plain-secret github_pat_1234567890 ghp_1234567890 "
        f"https://user:password@example.test {aws_key}"
    )

    redacted = redact_secrets(message)

    assert "plain-secret" not in redacted
    assert "1234567890" not in redacted
    assert "password" not in redacted
    assert aws_key not in redacted
