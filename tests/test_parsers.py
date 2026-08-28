import json

from streamlit_canvas_graph.ingestion import classify_update
from streamlit_canvas_graph.parsers import parse_manifest


def test_package_lock_parses_direct_and_transitive_packages() -> None:
    payload = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"alpha": "^1"}},
            "node_modules/alpha": {
                "name": "alpha",
                "version": "1.2.0",
                "dependencies": {"beta": "^2"},
            },
            "node_modules/beta": {"name": "beta", "version": "2.0.1"},
        },
    }
    parsed = parse_manifest("package-lock.json", json.dumps(payload))
    assert [(package.name, package.direct) for package in parsed.packages] == [
        ("alpha", True),
        ("beta", False),
    ]
    assert parsed.packages[0].dependencies == [("beta", "^2")]


def test_uv_lock_parses_parent_relationships() -> None:
    parsed = parse_manifest(
        "uv.lock",
        '[[package]]\nname="project"\nversion="0.1.0"\nsource={editable="."}\ndependencies=[{name="alpha"}]\n[[package]]\nname="alpha"\nversion="1.0.0"\ndependencies=[{name="beta"}]\n[[package]]\nname="beta"\nversion="2.0.0"\n',
    )
    assert len(parsed.packages) == 2
    assert parsed.packages[0].direct
    assert parsed.packages[0].dependencies == [("beta", "")]


def test_nuget_lock_parses_frameworks() -> None:
    payload = {
        "dependencies": {
            "net8.0": {
                "Direct.Package": {
                    "type": "Direct",
                    "resolved": "1.2.3",
                    "dependencies": {"Child.Package": "2.0.0"},
                },
                "Child.Package": {"type": "Transitive", "resolved": "2.0.0"},
            }
        }
    }
    parsed = parse_manifest("src/packages.lock.json", json.dumps(payload))
    assert {package.name for package in parsed.packages} == {
        "Direct.Package",
        "Child.Package",
    }
    assert next(
        package for package in parsed.packages if package.name == "Direct.Package"
    ).direct


def test_update_classification() -> None:
    assert classify_update("1.2.3", "2.0.0") == "major"
    assert classify_update("1.2.3", "1.3.0") == "minor"
    assert classify_update("1.2.3", "1.2.4") == "patch"
    assert classify_update("1.2.3", "1.2.3") is None
