from streamlit.testing.v1 import AppTest

from streamlit_canvas_graph import PACKAGE_ROOT


def test_streamlit_app_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCG_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(PACKAGE_ROOT / "app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    assert app.title[0].value == "GitHub Dependency Explorer"
    assert len(app.metric) == 4
