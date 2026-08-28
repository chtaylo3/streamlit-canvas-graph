from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import networkx as nx
import streamlit.components.v1 as components

_DIST = Path(__file__).resolve().parent / "frontend"
_component = (
    components.declare_component("dependency_canvas", path=str(_DIST))
    if _DIST.exists()
    else None
)


def dependency_canvas(
    graph: nx.DiGraph,
    focus_id: str,
    data_root: Path,
    *,
    dimmed_ids: set[str] | None = None,
    emphasized_edges: set[tuple[str, str]] | None = None,
    key: str,
) -> dict[str, Any] | None:
    if _component is None:
        return None
    nodes = []
    for node_id, data in graph.nodes(data=True):
        thumbnail = data_root / "thumbnails" / f"{node_id}.png"
        encoded = None
        if thumbnail.exists():
            encoded = "data:image/png;base64," + base64.b64encode(
                thumbnail.read_bytes()
            ).decode("ascii")
        nodes.append(
            {
                "id": node_id,
                "name": data["name"],
                "nodeType": data["node_type"],
                "ecosystem": data.get("ecosystem"),
                "version": data.get("version"),
                "thumbnail": encoded,
                "focused": node_id == focus_id,
                "dimmed": node_id in (dimmed_ids or set()),
            }
        )
    edges = [
        {
            "source": source,
            "target": target,
            "type": data.get("edge_type", "depends_on"),
            "dimmed": source in (dimmed_ids or set())
            or target in (dimmed_ids or set()),
            "emphasized": (source, target) in (emphasized_edges or set()),
        }
        for source, target, data in graph.edges(data=True)
    ]
    return _component(nodes=nodes, edges=edges, key=key, default=None)


def canvas_available() -> bool:
    return _component is not None
