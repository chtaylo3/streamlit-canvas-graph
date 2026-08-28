from dataclasses import replace
from pathlib import Path

import pytest

from streamlit_canvas_graph.settings import (
    PROJECT_ROOT,
    _warn_insecure_secret_permissions,
    reload_config,
)


def test_settings_use_tracked_defaults(monkeypatch) -> None:
    monkeypatch.delenv("SCG_DATA_DIR", raising=False)
    config = reload_config()
    assert config.data_dir == PROJECT_ROOT / "data/demo"
    assert config.repository_catalog == PROJECT_ROOT / "config/test-repositories.toml"


def test_settings_support_environment_and_secret_overrides(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SCG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCG_GITHUB_READ_TOKEN", "test-token")
    config = reload_config()
    assert config.data_dir == Path(tmp_path)
    assert config.database == Path(tmp_path) / "dependency-explorer.duckdb"
    assert config.require_secret("github_read_token") == "test-token"
    assert "test-token" not in repr(config)


def test_missing_secret_has_safe_error(monkeypatch) -> None:
    config = replace(reload_config(), github_provision_token=None)
    with pytest.raises(RuntimeError, match="SCG_GITHUB_PROVISION_TOKEN") as error:
        config.require_secret("github_provision_token")
    assert "github_pat" not in str(error.value)


def test_insecure_secret_permissions_warn(tmp_path) -> None:
    secrets = tmp_path / ".secrets.toml"
    secrets.write_text('github_read_token = "test"')
    secrets.chmod(0o644)

    with pytest.warns(UserWarning, match="chmod 600"):
        _warn_insecure_secret_permissions(secrets)
