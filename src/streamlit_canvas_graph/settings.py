from __future__ import annotations

import os
import stat
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dynaconf import Dynaconf

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class AppConfig:
    data_dir: Path
    database: Path
    github_output_dir: Path
    repository_catalog: Path
    provisioning_manifest: Path
    provisioning_prefix: str
    github_read_token: str | None = field(repr=False)
    github_provision_token: str | None = field(repr=False)

    def require_secret(self, name: str) -> str:
        value = getattr(self, name, None)
        if not value:
            env_name = f"SCG_{name.upper()}"
            raise RuntimeError(
                f"Configure {name} in .secrets.toml or set {env_name} in the environment"
            )
        return value


def _absolute(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load tracked defaults, ignored secrets, and SCG_* environment overrides."""
    secrets_path = PROJECT_ROOT / ".secrets.toml"
    _warn_insecure_secret_permissions(secrets_path)
    settings = Dynaconf(
        envvar_prefix="SCG",
        settings_files=[
            str(PROJECT_ROOT / "settings.toml"),
            str(secrets_path),
        ],
        environments=False,
        load_dotenv=True,
        merge_enabled=True,
    )
    data_dir = _absolute(settings.get("data_dir", "data/demo"))
    database_value = settings.get("database")
    database = (
        _absolute(database_value)
        if database_value
        else data_dir / "dependency-explorer.duckdb"
    )
    return AppConfig(
        data_dir=data_dir,
        database=database,
        github_output_dir=_absolute(settings.get("github_output_dir", "data/github")),
        repository_catalog=_absolute(
            settings.get("repository_catalog", "config/test-repositories.toml")
        ),
        provisioning_manifest=_absolute(
            settings.get("provisioning_manifest", "data/provisioning/repositories.json")
        ),
        provisioning_prefix=str(settings.get("provisioning_prefix", "scg-test")),
        github_read_token=_secret(
            settings, "github_read_token", legacy_env="GITHUB_READ_TOKEN"
        ),
        github_provision_token=_secret(
            settings,
            "github_provision_token",
            legacy_env="GITHUB_PROVISION_TOKEN",
        ),
    )


def _secret(settings: Dynaconf, key: str, *, legacy_env: str) -> str | None:
    """Return a secret without ever including its value in an error or representation."""
    value = settings.get(key) or os.environ.get(legacy_env)
    if not value or str(value).endswith("replace_me") or "replace_me_" in str(value):
        return None
    return str(value)


def _warn_insecure_secret_permissions(path: Path) -> None:
    """Warn when another local user could read or replace the secrets file."""
    if os.name != "posix" or not path.exists():
        return
    if stat.S_IMODE(path.stat().st_mode) & (stat.S_IRWXG | stat.S_IRWXO):
        warnings.warn(
            f"{path} is accessible by group or other users; run chmod 600 {path}",
            UserWarning,
            stacklevel=2,
        )


def reload_config() -> AppConfig:
    """Clear the cached settings, primarily for tests and long-running tools."""
    get_config.cache_clear()
    return get_config()
