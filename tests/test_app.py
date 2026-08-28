from streamlit.testing.v1 import AppTest

from streamlit_canvas_graph import PACKAGE_ROOT


def test_streamlit_app_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SCG_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(PACKAGE_ROOT / "app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    assert app.title[0].value == "GitHub Dependency Explorer"
    assert len(app.metric) == 4
    explore = next(widget for widget in app.selectbox if widget.label == "Explore")
    jump = next(widget for widget in app.selectbox if widget.label == "Jump to node")
    assert explore.value == "repository"
    assert all(
        option == "Search repositories…" or option.endswith(" · repository")
        for option in jump.options
    )

    jump.select("payments-api · repository").run()
    assert not app.exception
    explore = next(widget for widget in app.selectbox if widget.label == "Explore")
    jump = next(widget for widget in app.selectbox if widget.label == "Jump to node")
    assert explore.value == "manifest"
    assert all(
        option == "Search manifests…" or option.endswith(" · manifest")
        for option in jump.options
    )
