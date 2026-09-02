from __future__ import annotations

from functools import lru_cache

import networkx as nx
from streamlit_graph_canvas import (
    BadgeBinding,
    CanvasResult,
    Edge,
    EdgeStyle,
    EdgeType,
    FitView,
    GraphData,
    GraphSchema,
    Node,
    NodeStyle,
    NodeType,
    PaletteTone,
    Region,
    RendererRegistry,
    enable_renderers,
    graph_canvas,
)

_CONTRIB_DISTRIBUTION = "streamlit-graph-canvas-contrib"
_COUNT_CHIP = "streamlit-graph-canvas/contrib/count-chip"
CANVAS_ELEMENT_BUDGET = 500

_COUNT_BADGE = BadgeBinding(
    name="connections",
    kind=_COUNT_CHIP,
    region=Region.at(164, 10, 34, 22),
)

DEPENDENCY_SCHEMA = GraphSchema(
    node_types={
        "account": NodeType(
            "account",
            NodeStyle(
                width=210,
                height=96,
                fill="account",
                stroke="account_border",
                text="account_text",
            ),
            badges=(_COUNT_BADGE,),
        ),
        "repository": NodeType(
            "repository",
            NodeStyle(
                width=210,
                height=96,
                fill="repository",
                stroke="repository_border",
            ),
            badges=(_COUNT_BADGE,),
        ),
        "manifest": NodeType(
            "manifest",
            NodeStyle(width=210, height=96, fill="manifest", stroke="manifest_border"),
            badges=(_COUNT_BADGE,),
        ),
        "dependency": NodeType(
            "dependency",
            NodeStyle(
                width=210,
                height=96,
                fill="dependency",
                stroke="dependency_border",
            ),
            badges=(_COUNT_BADGE,),
        ),
    },
    edge_types={
        "depends_on": EdgeType("depends_on"),
        "emphasized": EdgeType(
            "emphasized", style=EdgeStyle(stroke="accent", width=2.5)
        ),
    },
    palette={
        "account": PaletteTone("#0f172a", "#1e293b"),
        "account_border": PaletteTone("#334155", "#64748b"),
        "account_text": PaletteTone("#ffffff"),
        "repository": PaletteTone("#dbeafe", "#1e3a8a"),
        "repository_border": PaletteTone("#2563eb", "#60a5fa"),
        "manifest": PaletteTone("#ede9fe", "#4c1d95"),
        "manifest_border": PaletteTone("#7c3aed", "#a78bfa"),
        "dependency": PaletteTone("#cffafe", "#164e63"),
        "dependency_border": PaletteTone("#0891b2", "#22d3ee"),
        "accent": PaletteTone("#2563eb", "#60a5fa"),
        "on_accent": PaletteTone("#ffffff", "#0f172a"),
    },
)


@lru_cache(maxsize=1)
def _renderer_registry() -> RendererRegistry:
    """Enable the explicitly pinned stock renderer distribution."""

    return enable_renderers([_CONTRIB_DISTRIBUTION])


def build_canvas_graph(
    graph: nx.DiGraph,
    *,
    dimmed_ids: set[str] | None = None,
    emphasized_edges: set[tuple[str, str]] | None = None,
) -> GraphData:
    """Translate the explorer graph into the public graph-canvas contract."""

    dimmed = dimmed_ids or set()
    emphasized = emphasized_edges or set()
    nodes = tuple(
        Node(
            id=str(node_id),
            type=str(data["node_type"]),
            label=str(data["name"]),
            data={
                "ecosystem": data.get("ecosystem"),
                "version": data.get("version"),
            },
            badges={"connections": int(graph.degree(node_id))},
            dimmed=node_id in dimmed,
        )
        for node_id, data in graph.nodes(data=True)
    )
    edges = tuple(
        Edge(
            id=f"edge-{index}",
            source=str(source),
            target=str(target),
            type="emphasized" if (source, target) in emphasized else "depends_on",
            data={"relationship": data.get("edge_type", "depends_on")},
            dimmed=source in dimmed or target in dimmed,
        )
        for index, (source, target, data) in enumerate(graph.edges(data=True))
    )
    return GraphData(nodes=nodes, edges=edges)


def dependency_canvas(
    graph: nx.DiGraph,
    *,
    dimmed_ids: set[str] | None = None,
    emphasized_edges: set[tuple[str, str]] | None = None,
    key: str,
) -> CanvasResult:
    """Render a dependency graph through the installed graph-canvas packages."""

    return graph_canvas(
        build_canvas_graph(
            graph,
            dimmed_ids=dimmed_ids,
            emphasized_edges=emphasized_edges,
        ),
        DEPENDENCY_SCHEMA,
        key=key,
        fit_view=FitView.TOPOLOGY_CHANGE,
        max_elements=CANVAS_ELEMENT_BUDGET,
        renderer_registry=_renderer_registry(),
        height=590,
    )
