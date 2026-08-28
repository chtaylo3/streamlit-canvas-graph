import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import { focusNode, mergeNodes } from "./canvas-state";

describe("in-place canvas updates", () => {
  it("preserves positions for nodes that remain visible", () => {
    const current: Node[] = [
      { id: "repo", position: { x: 120, y: 80 }, data: { focused: true } },
    ];
    const incoming: Node[] = [
      { id: "repo", position: { x: 0, y: 0 }, data: { focused: false } },
      { id: "manifest", position: { x: 0, y: 0 }, data: { focused: true } },
    ];

    const merged = mergeNodes(current, incoming);

    expect(merged[0].position).toEqual({ x: 120, y: 80 });
    expect(merged[0].data.focused).toBe(false);
    expect(merged[1].position).toEqual({ x: 0, y: 0 });
  });

  it("optimistically moves focus to the clicked node", () => {
    const nodes: Node[] = [
      { id: "repo", position: { x: 0, y: 0 }, data: { focused: true } },
      { id: "manifest", position: { x: 0, y: 100 }, data: { focused: false } },
    ];

    const focused = focusNode(nodes, "manifest");

    expect(focused.map((node) => node.data.focused)).toEqual([false, true]);
  });
});
