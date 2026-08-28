from datetime import UTC, datetime

from streamlit_canvas_graph.database import connect, initialize_database, insert_node
from streamlit_canvas_graph.github_client import Repository
from streamlit_canvas_graph.ingestion import _store_manifest, redact_secrets
from streamlit_canvas_graph.model import NodeType
from streamlit_canvas_graph.parsers import Package, ParsedManifest


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
