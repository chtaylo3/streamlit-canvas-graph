"""GitHub-backed dependency graph explorer."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent


def main() -> None:
    """Launch the Streamlit application."""
    from streamlit.web import cli as stcli

    app = PACKAGE_ROOT / "app.py"
    sys.argv = ["streamlit", "run", str(app), *sys.argv[1:]]
    raise SystemExit(stcli.main())
