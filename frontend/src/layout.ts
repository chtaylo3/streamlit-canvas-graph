import type { Edge, Node } from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";

const elk = new ELK();
const NODE_WIDTH = 180;
const NODE_HEIGHT = 92;

export function removeLayerOverlaps<T extends Node>(nodes: T[], gap: number): T[] {
  const layers = new Map<number, T[]>();
  for (const node of nodes) {
    const layer = Math.round(node.position.y);
    layers.set(layer, [...(layers.get(layer) ?? []), node]);
  }
  const positions = new Map<string, { x: number; y: number }>();
  for (const layer of layers.values()) {
    const ordered = [...layer].sort((left, right) => left.position.x - right.position.x);
    const originalLeft = ordered[0].position.x;
    const originalRight = ordered.at(-1)!.position.x + NODE_WIDTH;
    let cursor = originalLeft;
    for (const node of ordered) {
      const x = Math.max(node.position.x, cursor);
      positions.set(node.id, { x, y: node.position.y });
      cursor = x + NODE_WIDTH + gap;
    }
    const adjustedLeft = positions.get(ordered[0].id)!.x;
    const adjustedRight = positions.get(ordered.at(-1)!.id)!.x + NODE_WIDTH;
    const centerShift = (originalLeft + originalRight - adjustedLeft - adjustedRight) / 2;
    for (const node of ordered) {
      const position = positions.get(node.id)!;
      positions.set(node.id, { ...position, x: position.x + centerShift });
    }
  }
  return nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) ?? node.position,
  }));
}

export async function layoutNodes<T extends Node>(nodes: T[], edges: Edge[]): Promise<T[]> {
  const nodeGap = Math.min(90, 42 + Math.sqrt(nodes.length) * 3);
  const layerGap = Math.min(170, 90 + Math.sqrt(nodes.length) * 4);
  const result = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": String(nodeGap),
      "elk.layered.spacing.nodeNodeBetweenLayers": String(layerGap),
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      "elk.layered.nodePlacement.bk.fixedAlignment": "BALANCED",
      "elk.layered.nodePlacement.favorStraightEdges": "true",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.crossingMinimization.semiInteractive": "true",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: nodes.map((node) => ({
      id: node.id,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
  });
  const positions = new Map(
    result.children?.map((child) => [
      child.id,
      { x: child.x ?? 0, y: child.y ?? 0 },
    ]),
  );
  const laidOut = nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) ?? node.position,
  }));
  return removeLayerOverlaps(laidOut, nodeGap);
}
