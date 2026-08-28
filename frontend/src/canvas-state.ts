import type { Node } from "@xyflow/react";

export function mergeNodes<T extends Node>(current: T[], incoming: T[]): T[] {
  const positions = new Map(current.map((node) => [node.id, node.position]));
  return incoming.map((node) => ({
    ...node,
    position: positions.get(node.id) ?? node.position,
  }));
}

export function focusNode<T extends Node>(nodes: T[], nodeId: string): T[] {
  return nodes.map((node) => ({
    ...node,
    data: { ...node.data, focused: node.id === nodeId },
  }));
}
