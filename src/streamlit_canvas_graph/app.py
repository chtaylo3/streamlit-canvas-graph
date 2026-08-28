from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from streamlit_canvas_graph.canvas import canvas_available, dependency_canvas
from streamlit_canvas_graph.database import create_demo_dataset, snapshot_rows
from streamlit_canvas_graph.graph import (
    bounded_neighborhood,
    load_graph,
    node_metrics,
    thumbnail_path,
    vulnerabilities_for_node,
)
from streamlit_canvas_graph.settings import get_config
from streamlit_canvas_graph.thumbnails import COLORS

st.set_page_config(page_title="Dependency Explorer", page_icon="◉", layout="wide")

TYPE_COLORS = {
    "account": "#0f172a",
    "repository": "#2563eb",
    "manifest": "#7c3aed",
    "dependency": "#0891b2",
}


@st.cache_resource
def open_database(path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=True)


@st.cache_data
def graph_for_snapshot(path: str, snapshot_id: str) -> nx.DiGraph:
    con = duckdb.connect(path, read_only=True)
    try:
        return load_graph(con, snapshot_id)
    finally:
        con.close()


def graph_figure(graph: nx.DiGraph, focus_id: str | None) -> go.Figure:
    if not graph:
        return go.Figure()
    generations = (
        list(nx.topological_generations(graph))
        if nx.is_directed_acyclic_graph(graph)
        else []
    )
    if generations:
        positions: dict[str, tuple[float, float]] = {}
        for column, generation in enumerate(generations):
            for row, node_id in enumerate(generation):
                positions[node_id] = (column * 2.5, -row * 1.6 + len(generation) * 0.8)
    else:
        positions = nx.spring_layout(graph, seed=7)
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for source, target in graph.edges:
        edge_x.extend((positions[source][0], positions[target][0], None))
        edge_y.extend((positions[source][1], positions[target][1], None))
    edges = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line={"color": "#cbd5e1", "width": 1.5},
        hoverinfo="skip",
    )
    nodes = list(graph.nodes)
    node_trace = go.Scatter(
        x=[positions[node][0] for node in nodes],
        y=[positions[node][1] for node in nodes],
        mode="markers+text",
        customdata=nodes,
        text=[graph.nodes[node]["name"] for node in nodes],
        textposition="bottom center",
        hovertemplate="<b>%{text}</b><br>%{meta}<extra></extra>",
        meta=[graph.nodes[node]["node_type"] for node in nodes],
        marker={
            "size": [34 if node == focus_id else 25 for node in nodes],
            "color": [
                TYPE_COLORS.get(graph.nodes[node]["node_type"], "#64748b")
                for node in nodes
            ],
            "line": {"color": "#f8fafc", "width": 3},
        },
    )
    figure = go.Figure([edges, node_trace])
    figure.update_layout(
        height=590,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        paper_bgcolor="#f8fafc",
        plot_bgcolor="#f8fafc",
        showlegend=False,
        dragmode="pan",
        xaxis={"visible": False},
        yaxis={"visible": False, "scaleanchor": "x", "scaleratio": 1},
    )
    return figure


def ring_figure(metrics: dict[str, dict[str, int]]) -> go.Figure:
    figure = go.Figure()
    specs = (("vulnerabilities", 0.35), ("updates", 0.58), ("scope", 0.78))
    for dimension, hole in specs:
        values = metrics.get(dimension, {})
        labels = list(values) or ["none"]
        counts = list(values.values()) or [1]
        figure.add_trace(
            go.Pie(
                labels=labels,
                values=counts,
                hole=hole,
                sort=False,
                marker={"colors": [COLORS.get(label, "#e2e8f0") for label in labels]},
                textinfo="none",
                hovertemplate="%{label}: %{value}<extra></extra>",
                domain={"x": [0, 1], "y": [0, 1]},
            )
        )
    figure.update_layout(
        height=330,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        showlegend=True,
        legend={"orientation": "h"},
    )
    return figure


def select_node(node_id: str, *, panel: str = "metadata") -> None:
    st.session_state.focus_id = node_id
    st.session_state.selected_id = node_id
    st.session_state.panel = panel


def render_details(
    connection: duckdb.DuckDBPyConnection,
    snapshot_id: str,
    graph: nx.DiGraph,
    data_root: Path,
    node_id: str,
) -> None:
    data = graph.nodes[node_id]
    st.subheader(data["name"])
    st.caption(f"{data['node_type'].title()} · {data.get('ecosystem') or 'GitHub'}")
    image = thumbnail_path(data_root, node_id)
    if image.exists():
        if st.button(
            "Open ring details", key=f"ring-{node_id}", use_container_width=True
        ):
            st.session_state.panel = "ring"
        st.image(str(image), width=105)
    if st.session_state.get("panel") == "ring":
        st.plotly_chart(
            ring_figure(node_metrics(connection, snapshot_id, node_id)),
            use_container_width=True,
            config={"displayModeBar": False},
        )
        if st.button("Back to metadata", use_container_width=True):
            st.session_state.panel = "metadata"
    else:
        fields: dict[str, Any] = {
            "Node ID": node_id,
            "Type": data["node_type"],
            "Ecosystem": data.get("ecosystem"),
            "Version": data.get("version"),
        }
        fields.update(data.get("metadata", {}))
        for key, value in fields.items():
            if value is not None:
                st.markdown(f"**{key.replace('_', ' ').title()}**  \n{value}")


def main() -> None:
    config = get_config()
    data_root = config.data_dir
    db_path = config.database
    if not db_path.exists():
        create_demo_dataset(data_root)
    connection = open_database(str(db_path))
    snapshots = snapshot_rows(connection)
    st.title("GitHub Dependency Explorer")
    st.caption(
        "Browse accounts, repositories, manifests, and direct or transitive dependencies without losing context."
    )
    if not snapshots:
        st.warning("This database contains no snapshots.")
        return
    controls = st.columns([2, 3, 1])
    labels = {
        row["snapshot_id"]: f"{row['captured_at']:%Y-%m-%d %H:%M} · {row['source']}"
        for row in snapshots
    }
    snapshot_id = controls[0].selectbox(
        "Snapshot", list(labels), format_func=labels.get
    )
    graph = graph_for_snapshot(str(db_path), snapshot_id)
    search_options = sorted(graph, key=lambda node: graph.nodes[node]["name"].lower())
    search = controls[1].selectbox(
        "Jump to node",
        [None, *search_options],
        format_func=lambda node: (
            "Search all nodes…"
            if node is None
            else f"{graph.nodes[node]['name']} · {graph.nodes[node]['node_type']}"
        ),
    )
    if search and search != st.session_state.get("selected_id"):
        select_node(search)
    if controls[2].button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    focus_id = st.session_state.get("focus_id")
    if focus_id not in graph:
        focus_id = next(
            (node for node in graph if graph.nodes[node]["node_type"] == "account"),
            next(iter(graph)),
        )
        select_node(focus_id)
    visible, hidden = bounded_neighborhood(graph, focus_id)
    canvas, details = st.columns([3, 1], gap="large")
    with canvas:
        if hidden:
            st.info(
                f"Showing the highest-priority 500 nodes; {hidden} additional nodes are hidden. Use search or filters to refocus."
            )
        if canvas_available():
            event = dependency_canvas(
                visible,
                focus_id,
                data_root,
                key=f"graph-{snapshot_id}-{focus_id}",
            )
            if event and event.get("nonce") != st.session_state.get("canvas_nonce"):
                st.session_state.canvas_nonce = event["nonce"]
                clicked = event.get("nodeId")
                if clicked in graph:
                    select_node(
                        clicked,
                        panel="ring"
                        if event.get("kind") == "thumbnail_select"
                        else "metadata",
                    )
                    st.rerun()
        else:
            event = st.plotly_chart(
                graph_figure(visible, focus_id),
                use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False},
                on_select="rerun",
                selection_mode="points",
                key=f"graph-{snapshot_id}",
            )
            points = event.selection.points if event and event.selection else []
            if points and points[0].get("customdata") in graph:
                clicked = points[0]["customdata"]
                if clicked != st.session_state.get("selected_id"):
                    select_node(clicked)
                    st.rerun()
        st.caption(
            "Click a node to refocus. The canvas shows two levels toward ancestors and one toward descendants."
        )
    with details:
        render_details(
            connection, snapshot_id, graph, data_root, st.session_state.selected_id
        )
    st.divider()
    st.subheader("Vulnerability posture")
    findings = vulnerabilities_for_node(
        connection, snapshot_id, st.session_state.selected_id
    )
    counts = {
        severity: sum(row["severity"] == severity for row in findings)
        for severity in ("critical", "high", "medium", "low")
    }
    cards = st.columns(4)
    for card, severity in zip(cards, counts, strict=True):
        card.metric(severity.title(), counts[severity])
    if findings:
        severities = st.multiselect("Severity", list(counts), default=list(counts))
        frame = pd.DataFrame([row for row in findings if row["severity"] in severities])
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
            column_config={"advisory_url": st.column_config.LinkColumn("Advisory")},
        )
    else:
        st.success(
            "No vulnerabilities are associated with this node in the selected snapshot."
        )


main()
