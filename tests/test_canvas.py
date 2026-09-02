import networkx as nx
from streamlit_graph_canvas import enable_renderers, serialize_graph

from streamlit_canvas_graph.canvas import DEPENDENCY_SCHEMA, build_canvas_graph


def test_build_canvas_graph_preserves_explorer_semantics() -> None:
    graph = nx.DiGraph()
    graph.add_node(
        "repo",
        node_type="repository",
        name="example/repository",
        ecosystem=None,
        version=None,
    )
    graph.add_node(
        "package",
        node_type="dependency",
        name="example-package",
        ecosystem="PyPI",
        version="1.2.3",
    )
    graph.add_edge("repo", "package", edge_type="depends_on")

    canvas = build_canvas_graph(
        graph,
        dimmed_ids={"repo"},
        emphasized_edges={("repo", "package")},
    )

    nodes = {node.id: node for node in canvas.nodes}
    assert nodes["repo"].type == "repository"
    assert nodes["repo"].dimmed is True
    assert nodes["repo"].badges["connections"] == 1
    assert nodes["package"].data == {
        "ecosystem": "PyPI",
        "version": "1.2.3",
    }
    assert nodes["package"].dimmed is False
    assert canvas.edges[0].type == "emphasized"
    assert canvas.edges[0].dimmed is True
    assert canvas.edges[0].data["relationship"] == "depends_on"

    serialized = serialize_graph(
        DEPENDENCY_SCHEMA,
        canvas,
        renderer_registry=enable_renderers(["streamlit-graph-canvas-contrib"]),
    )
    presentation = serialized.envelope["presentation"]
    serialized_nodes = {node["id"]: node for node in presentation["nodes"]}
    assert serialized_nodes["repo"]["dimmed"] is True
    assert serialized_nodes["package"]["dimmed"] is False
    assert serialized_nodes["repo"]["badges"][0]["primitives"]
    assert presentation["edges"][0]["dimmed"] is True


def test_dependency_schema_uses_the_contrib_count_chip() -> None:
    for node_type in DEPENDENCY_SCHEMA.node_types.values():
        assert node_type.badges[0].kind == ("streamlit-graph-canvas/contrib/count-chip")
        assert node_type.badges[0].name == "connections"
