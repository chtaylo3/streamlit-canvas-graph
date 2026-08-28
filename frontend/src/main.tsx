import React, { memo, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Streamlit, withStreamlitConnection, type ComponentProps } from "streamlit-component-lib";
import ELK from "elkjs/lib/elk.bundled.js";
import "./style.css";
import { canvasEvent, type CanvasEventKind } from "./events";

type InputNode = {
  id: string;
  name: string;
  nodeType: string;
  ecosystem?: string;
  version?: string;
  thumbnail?: string;
  focused: boolean;
};

type CanvasNodeData = InputNode & { onThumbnail: (id: string) => void };
type CanvasNode = Node<CanvasNodeData, "dependencyNode">;

const DependencyNode = memo(({ data, selected }: NodeProps<CanvasNode>) => (
  <div className={`graph-node type-${data.nodeType} ${data.focused ? "focused" : ""} ${selected ? "selected" : ""}`} role="button" aria-label={`${data.nodeType} ${data.name}`} tabIndex={0}>
    <Handle type="target" position={Position.Left} />
    <div className="node-type">{data.nodeType}</div>
    <div className="node-name">{data.name}</div>
    {(data.ecosystem || data.version) && <div className="node-subtitle">{[data.ecosystem, data.version].filter(Boolean).join(" · ")}</div>}
    {data.thumbnail && <button className="ring-button" title="Open ring details" aria-label={`Open risk ring for ${data.name}`} onClick={(event) => { event.stopPropagation(); data.onThumbnail(data.id); }}><img src={data.thumbnail} alt="" /></button>}
    <Handle type="source" position={Position.Right} />
  </div>
));

const nodeTypes = { dependencyNode: DependencyNode };
const elk = new ELK();

async function layout(nodes: CanvasNode[], edges: Edge[]): Promise<CanvasNode[]> {
  const result = await elk.layout({
    id: "root",
    layoutOptions: { "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.spacing.nodeNode": "45", "elk.layered.spacing.nodeNodeBetweenLayers": "90" },
    children: nodes.map((node) => ({ id: node.id, width: 180, height: 92 })),
    edges: edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  });
  const positions = new Map(result.children?.map((child) => [child.id, { x: child.x ?? 0, y: child.y ?? 0 }]));
  return nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position }));
}

function Canvas({ args, disabled, theme }: ComponentProps) {
  const inputNodes = (args.nodes ?? []) as InputNode[];
  const inputEdges = (args.edges ?? []) as Array<{ source: string; target: string; type: string }>;
  const emit = useCallback((kind: CanvasEventKind, nodeId: string) => Streamlit.setComponentValue(canvasEvent(kind, nodeId)), []);
  const baseNodes = useMemo<CanvasNode[]>(() => inputNodes.map((node) => ({ id: node.id, type: "dependencyNode", position: { x: 0, y: 0 }, data: { ...node, onThumbnail: (id) => emit("thumbnail_select", id) } })), [args.nodes, emit]);
  const edges = useMemo<Edge[]>(() => inputEdges.map((edge, index) => ({ id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, label: edge.type === "depends_on" ? undefined : edge.type, animated: false })), [args.edges]);
  const [nodes, setNodes] = useState(baseNodes);
  useEffect(() => { layout(baseNodes, edges).then(setNodes); }, [baseNodes, edges]);
  useEffect(() => Streamlit.setFrameHeight(620), []);
  return <div className={`canvas ${theme?.base ?? "light"}`}>
    <ReactFlowProvider><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} elementsSelectable={!disabled} fitView minZoom={0.15} maxZoom={2.5} onNodeClick={(_, node) => emit("node_select", node.id)} colorMode={theme?.base === "dark" ? "dark" : "light"}>
      <Background gap={22} size={1} /><Controls /><MiniMap pannable zoomable nodeColor={(node) => ({ account: "#0f172a", repository: "#2563eb", manifest: "#7c3aed", dependency: "#0891b2" }[(node.data as CanvasNodeData).nodeType] ?? "#64748b")} />
    </ReactFlow></ReactFlowProvider>
  </div>;
}

const ConnectedCanvas = withStreamlitConnection(Canvas);
createRoot(document.getElementById("root")!).render(<React.StrictMode><ConnectedCanvas /></React.StrictMode>);
