import { describe, expect, it } from "vitest";
import { blueprintFromTemplate, templates } from "./data";
import {
  addAgentToCanvas,
  attachResourceToAgent,
  createCanvasBundle,
  loadCanvasBundle,
  saveCanvasBundle,
} from "./canvas-model";

describe("Canvas Document model", () => {
  it("keeps canvas layout separate from the Agent blueprint", () => {
    const bundle = addAgentToCanvas(
      createCanvasBundle("Research canvas"),
      blueprintFromTemplate(templates[0]),
      { x: 24, y: 18 },
    );

    expect(bundle.canvas.schema_version).toBe("mosaic.canvas/v1");
    const agentNode = bundle.canvas.nodes.find((node) => node.kind === "agent");
    expect(agentNode).toMatchObject({ kind: "agent", position: { x: 24, y: 18 } });
    expect(agentNode && bundle.blueprints[agentNode.blueprint_id].system_prompt).toContain("Research");
    expect(agentNode).not.toHaveProperty("system_prompt");
  });

  it("creates a ResourceInstance and typed owns edge when equipping a Tool", () => {
    const initial = addAgentToCanvas(
      createCanvasBundle(),
      blueprintFromTemplate(templates[1]),
      { x: 20, y: 20 },
    );

    const equipped = attachResourceToAgent(initial, "support-agent", {
      resource_id: "web_search",
      kind: "tool",
      display_name: "Research search",
      config: { max_results: 5 },
    });

    expect(Object.values(equipped.resource_instances)).toHaveLength(1);
    expect(equipped.canvas.edges[0]).toMatchObject({
      type: "owns",
      source_port: "tools",
      target_port: "tools",
    });
    expect(equipped.canvas.nodes.some((node) => node.kind === "resource")).toBe(true);
  });

  it("persists and restores a bundle through the local-first storage boundary", () => {
    const storage = new Map<string, string>();
    const fakeStorage = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    };
    const bundle = addAgentToCanvas(createCanvasBundle(), blueprintFromTemplate(templates[1]), { x: 10, y: 12 });

    saveCanvasBundle(fakeStorage, bundle);
    const restored = loadCanvasBundle(fakeStorage);

    expect(restored.canvas.id).toBe(bundle.canvas.id);
    expect(restored.canvas.nodes).toEqual(bundle.canvas.nodes);
    expect(restored.blueprints).toEqual(bundle.blueprints);
  });
});
