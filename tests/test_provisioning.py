import json
from pathlib import Path

import pytest

from streamlit_canvas_graph.provisioning import (
    CatalogEntry,
    cleanup,
    destination_name,
    load_catalog,
)


class FakeClient:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_repository(self, full_name: str) -> None:
        self.deleted.append(full_name)


def test_catalog_has_four_defaults_per_ecosystem() -> None:
    entries = load_catalog(Path("config/test-repositories.toml"))
    assert len(entries) == 12
    assert all(entry.default_selected for entry in entries)
    assert {
        ecosystem: sum(entry.ecosystem == ecosystem for entry in entries)
        for ecosystem in {entry.ecosystem for entry in entries}
    } == {"npm": 4, "PyPI": 4, "NuGet": 4}


def test_destination_name_contains_no_owner() -> None:
    entry = CatalogEntry(
        "https://github.com/example/Complex.Repo",
        "PyPI",
        ("uv.lock",),
        "MIT",
        "high",
        "test",
        True,
    )
    assert destination_name("Security Test", entry) == "security-test-pypi-complex-repo"


def test_cleanup_is_allowlisted_by_local_manifest(tmp_path) -> None:
    path = tmp_path / "repositories.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "repositories": [
                    {"destination_full_name": "me/allowed", "removed_at": None}
                ],
            }
        )
    )
    client = FakeClient()
    assert cleanup(client, path, {"me/allowed"}) == ["me/allowed"]
    assert client.deleted == ["me/allowed"]
    with pytest.raises(ValueError):
        cleanup(client, path, {"me/not-allowed"})
