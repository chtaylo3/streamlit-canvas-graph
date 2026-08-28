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
import { Streamlit, type Theme } from "streamlit-component-lib";
import "./style.css";
import { canvasEvent, type CanvasEventKind } from "./events";
import { layoutNodes } from "./layout";

type InputNode = {
  id: string;
  name: string;
  nodeType: string;
  ecosystem?: string;
  version?: string;
  thumbnail?: string;
  focused: boolean;
  dimmed: boolean;
};

type CanvasNodeData = InputNode & { onThumbnail: (id: string) => void };
type CanvasNode = Node<CanvasNodeData, "dependencyNode">;

const DependencyNode = memo(({ data, selected }: NodeProps<CanvasNode>) => (
  <div className={`graph-node type-${data.nodeType} ${data.focused ? "focused" : ""} ${data.dimmed ? "dimmed" : ""} ${selected ? "selected" : ""}`} role="button" aria-label={`${data.nodeType} ${data.name}`} tabIndex={0}>
    <Handle type="target" position={Position.Top} />
    <div className="node-type">{data.nodeType}</div>
    <div className="node-name">{data.name}</div>
    {(data.ecosystem || data.version) && <div className="node-subtitle">{[data.ecosystem, data.version].filter(Boolean).join(" · ")}</div>}
    {data.thumbnail && <button className="ring-button" title="Open ring details" aria-label={`Open risk ring for ${data.name}`} onClick={(event) => { event.stopPropagation(); data.onThumbnail(data.id); }}><img src={data.thumbnail} alt="" /></button>}
    <Handle type="source" position={Position.Bottom} />
  </div>
));

const nodeTypes = { dependencyNode: DependencyNode };

type CanvasProps = {
  args: { nodes?: InputNode[]; edges?: Array<{ source: string; target: string; type: string; dimmed: boolean; emphasized: boolean }> };
  disabled: boolean;
  theme?: Theme;
};

function Canvas({ args, disabled, theme }: CanvasProps) {
  const inputNodes = (args.nodes ?? []) as InputNode[];
  const inputEdges = (args.edges ?? []) as Array<{ source: string; target: string; type: string; dimmed: boolean; emphasized: boolean }>;
  const emit = useCallback((kind: CanvasEventKind, nodeId: string) => Streamlit.setComponentValue(canvasEvent(kind, nodeId)), []);
  const baseNodes = useMemo<CanvasNode[]>(() => inputNodes.map((node) => ({ id: node.id, type: "dependencyNode", position: { x: 0, y: 0 }, data: { ...node, onThumbnail: (id) => emit("thumbnail_select", id) } })), [args.nodes, emit]);
  const edges = useMemo<Edge[]>(() => inputEdges.map((edge, index) => ({ id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, type: "smoothstep", pathOptions: { borderRadius: 12, offset: 24 }, label: edge.type === "depends_on" ? undefined : edge.type, animated: false, style: { opacity: edge.dimmed ? 0.22 : 1, strokeWidth: edge.emphasized ? 3 : 1.5 } })), [args.edges]);
  const [nodes, setNodes] = useState<CanvasNode[] | null>(null);
  useEffect(() => {
    let active = true;
    setNodes(null);
    layoutNodes(baseNodes, edges).then((laidOut) => {
      if (active) setNodes(laidOut);
    });
    return () => { active = false; };
  }, [baseNodes, edges]);
  useEffect(() => Streamlit.setFrameHeight(620), []);
  return <div className={`canvas ${theme?.base ?? "light"}`}>
    {nodes === null ? <div className="canvas-loading">Laying out dependency graph…</div> : <ReactFlowProvider><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} elementsSelectable={!disabled} fitView fitViewOptions={{ padding: 0.18, duration: 300 }} minZoom={0.08} maxZoom={2.5} onInit={(instance) => requestAnimationFrame(() => instance.fitView({ padding: 0.18, duration: 300 }))} onNodeClick={(_, node) => emit("node_select", node.id)} colorMode={theme?.base === "dark" ? "dark" : "light"}>
      <Background gap={22} size={1} /><Controls /><MiniMap pannable zoomable nodeColor={(node) => ({ account: "#0f172a", repository: "#2563eb", manifest: "#7c3aed", dependency: "#0891b2" }[(node.data as CanvasNodeData).nodeType] ?? "#64748b")} />
    </ReactFlow></ReactFlowProvider>}
  </div>;
}

type RenderData = { args: CanvasProps["args"]; disabled: boolean; theme?: Theme };

function ConnectedCanvas() {
  const [renderData, setRenderData] = useState<RenderData | null>(null);
  useEffect(() => {
    const onRender = (event: Event) => setRenderData((event as CustomEvent<RenderData>).detail);
    Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
    Streamlit.setComponentReady();
    return () => Streamlit.events.removeEventListener(Streamlit.RENDER_EVENT, onRender);
  }, []);
  return renderData ? <Canvas {...renderData} /> : <div className="canvas-loading">Connecting to Streamlit…</div>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><ConnectedCanvas /></React.StrictMode>);
