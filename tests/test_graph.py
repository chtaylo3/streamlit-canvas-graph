import networkx as nx

from streamlit_canvas_graph.graph import bounded_neighborhood


def test_bounded_neighborhood_two_up_one_down_and_cycle_safe() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from(
        [
            ("account", "repo"),
            ("repo", "manifest"),
            ("manifest", "direct"),
            ("direct", "transitive"),
            ("transitive", "direct"),
        ]
    )
    for node in graph:
        graph.nodes[node].update(name=node, node_type="dependency")
    visible, hidden = bounded_neighborhood(graph, "direct")
    assert set(visible) == {"repo", "manifest", "direct", "transitive"}
    assert hidden == 0


def test_bounded_neighborhood_reports_truncation() -> None:
    graph = nx.DiGraph()
    graph.add_node("root", name="root", node_type="account")
    for index in range(10):
        graph.add_node(str(index), name=str(index), node_type="repository")
        graph.add_edge("root", str(index))
    visible, hidden = bounded_neighborhood(graph, "root", limit=4)
    assert "root" in visible
    assert len(visible) == 4
    assert hidden == 7
