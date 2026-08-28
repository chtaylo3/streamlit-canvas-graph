import { describe, expect, it } from "vitest";
import type { Edge, Node } from "@xyflow/react";
import { layoutNodes, removeLayerOverlaps } from "./layout";

describe("vertical dependency layout", () => {
  it("centers a parent above its child tier", async () => {
    const nodes: Node[] = [
      { id: "account", position: { x: 0, y: 0 }, data: {} },
      ...Array.from({ length: 10 }, (_, index) => ({
        id: `repo-${index}`,
        position: { x: 0, y: 0 },
        data: {},
      })),
    ];
    const edges: Edge[] = Array.from({ length: 10 }, (_, index) => ({
      id: `edge-${index}`,
      source: "account",
      target: `repo-${index}`,
    }));

    const laidOut = await layoutNodes(nodes, edges);
    const account = laidOut.find((node) => node.id === "account")!;
    const repositories = laidOut.filter((node) => node.id.startsWith("repo-"));
    const left = Math.min(...repositories.map((node) => node.position.x));
    const right = Math.max(...repositories.map((node) => node.position.x + 180));

    expect(account.position.x + 90).toBeCloseTo((left + right) / 2);
    expect(repositories.every((node) => node.position.y > account.position.y)).toBe(true);
  });

  it("removes collisions without shifting the center of a tier", () => {
    const nodes: Node[] = [
      { id: "left", position: { x: 0, y: 100 }, data: {} },
      { id: "middle", position: { x: 50, y: 100 }, data: {} },
      { id: "right", position: { x: 100, y: 100 }, data: {} },
    ];
    const originalCenter = (0 + 100 + 180) / 2;

    const spread = removeLayerOverlaps(nodes, 40);
    const ordered = [...spread].sort((left, right) => left.position.x - right.position.x);
    const spreadCenter = (ordered[0].position.x + ordered.at(-1)!.position.x + 180) / 2;

    expect(ordered[1].position.x - ordered[0].position.x).toBeGreaterThanOrEqual(220);
    expect(ordered[2].position.x - ordered[1].position.x).toBeGreaterThanOrEqual(220);
    expect(spreadCenter).toBeCloseTo(originalCenter);
  });
});
