import networkx as nx

from streamlit_canvas_graph.graph import (
    bounded_neighborhood,
    breadcrumb_path,
    emphasized_context_edges,
    repository_scope,
    scoped_explore_paths,
)


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


def test_repository_scoped_paths_and_breadcrumbs() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from(
        [
            ("account", "repo-a"),
            ("account", "repo-b"),
            ("repo-a", "manifest-a"),
            ("repo-b", "manifest-b"),
            ("manifest-a", "direct-a"),
            ("direct-a", "shared"),
            ("manifest-b", "direct-b"),
            ("direct-b", "shared"),
        ]
    )
    types = {
        "account": "account",
        "repo-a": "repository",
        "repo-b": "repository",
        "manifest-a": "manifest",
        "manifest-b": "manifest",
        "direct-a": "dependency",
        "direct-b": "dependency",
        "shared": "dependency",
    }
    for node, node_type in types.items():
        graph.nodes[node].update(name=node, node_type=node_type)

    assert repository_scope(graph, "shared", "repo-a") == "repo-a"
    assert scoped_explore_paths(graph, "manifest", "repo-a") == {
        "manifest-a": ("manifest-a",)
    }
    assert scoped_explore_paths(graph, "dependency", "repo-a")["shared"] == (
        "manifest-a",
        "direct-a",
        "shared",
    )
    assert breadcrumb_path(graph, "shared", "repo-a") == (
        "account",
        "repo-a",
        "manifest-a",
        "direct-a",
        "shared",
    )
    assert emphasized_context_edges(
        graph,
        "direct-a",
        ("account", "repo-a", "manifest-a", "direct-a"),
        {"repo-a", "manifest-a", "direct-a", "shared"},
    ) == {
        ("repo-a", "manifest-a"),
        ("manifest-a", "direct-a"),
        ("direct-a", "shared"),
    }
