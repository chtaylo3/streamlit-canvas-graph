export type CanvasEventKind = "node_select" | "thumbnail_select";

export function canvasEvent(kind: CanvasEventKind, nodeId: string, nonce = Date.now()) {
  return { kind, nodeId, nonce };
}
