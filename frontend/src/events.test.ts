import { describe, expect, it } from "vitest";
import { canvasEvent } from "./events";

describe("canvasEvent", () => {
  it("keeps node and thumbnail selections distinct", () => {
    expect(canvasEvent("node_select", "node-1", 10)).toEqual({ kind: "node_select", nodeId: "node-1", nonce: 10 });
    expect(canvasEvent("thumbnail_select", "node-1", 11)).toEqual({ kind: "thumbnail_select", nodeId: "node-1", nonce: 11 });
  });
});
