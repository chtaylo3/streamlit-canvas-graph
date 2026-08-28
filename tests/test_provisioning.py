import json
from base64 import b64encode
from pathlib import Path

import pytest

from streamlit_canvas_graph.github_client import GitHubError
from streamlit_canvas_graph.provisioning import (
    CatalogEntry,
    Preflight,
    cleanup,
    destination_name,
    load_catalog,
    provision,
    verified_license,
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


def test_ambiguous_github_license_is_verified_from_content() -> None:
    encoded = b64encode(b"The Artistic License 2.0\nTerms follow").decode()
    payload = {
        "license": {"spdx_id": "NOASSERTION"},
        "encoding": "base64",
        "content": f"{encoded[:20]}\n{encoded[20:]}",
    }

    assert verified_license(payload, "Artistic-2.0") == "Artistic-2.0"


def test_ambiguous_github_license_does_not_trust_catalog_alone() -> None:
    payload = {
        "license": {"spdx_id": "NOASSERTION"},
        "encoding": "base64",
        "content": b64encode(b"An unrelated license").decode(),
    }

    assert verified_license(payload, "Artistic-2.0") == "NOASSERTION"


def test_provision_disables_actions_before_copy_and_rolls_back_interrupt(
    tmp_path, monkeypatch
) -> None:
    events: list[str] = []

    class ProvisionClient:
        def repository(self, _full_name: str) -> None:
            raise GitHubError("not found")

        def create_private_repository(self, _name: str, _description: str) -> dict:
            events.append("create")
            return {
                "id": 42,
                "full_name": "me/scg-test-pypi-complex-repo",
                "clone_url": "https://github.com/me/scg-test-pypi-complex-repo.git",
                "html_url": "https://github.com/me/scg-test-pypi-complex-repo",
            }

        def disable_actions(self, _full_name: str) -> None:
            events.append("disable_actions")

        def delete_repository(self, _full_name: str) -> None:
            events.append("delete")

    entry = CatalogEntry(
        "https://github.com/example/Complex.Repo",
        "PyPI",
        ("uv.lock",),
        "MIT",
        "high",
        "test",
        True,
    )
    check = Preflight(entry, True, "main", "abc123", 1, "MIT", ("uv.lock",))

    def interrupted_copy(*_args: object) -> None:
        events.append("copy")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "streamlit_canvas_graph.provisioning._copy_default_branch", interrupted_copy
    )
    with pytest.raises(KeyboardInterrupt):
        provision(
            ProvisionClient(),
            "token",
            "me",
            check,
            "scg-test",
            tmp_path / "manifest.json",
        )

    assert events == ["create", "disable_actions", "copy", "delete"]
    assert not (tmp_path / "manifest.json").exists()
