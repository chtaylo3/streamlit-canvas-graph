from streamlit_canvas_graph.database import create_demo_dataset


def test_demo_dataset_is_idempotent(tmp_path) -> None:
    first = create_demo_dataset(tmp_path)
    second = create_demo_dataset(tmp_path)
    assert first == second
    assert first.exists()
    assert len(list((tmp_path / "thumbnails").glob("*.png"))) >= 10
    assert len(list((tmp_path / "parquet").glob("*/*.parquet"))) == 14
