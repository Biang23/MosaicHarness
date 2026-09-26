import { describe, expect, it } from "vitest";
import { blueprintFromTemplate, templates } from "./data";
import { createLiveApiClient, createMockApiClient } from "./api";

describe("mock Studio API", () => {
  it("creates, validates, previews, and publishes a template blueprint", async () => {
    const api = createMockApiClient();
    const blueprint = blueprintFromTemplate(templates[1]);

    await api.createBlueprint(blueprint);
    const validation = await api.validateBlueprint(blueprint);
    const preview = await api.previewBlueprint(blueprint, {
      input: "hello",
      user_id: "studio",
      session_id: "session",
      thread_id: "thread",
    });
    const published = await api.publishBlueprint(blueprint);

    expect(validation.ok).toBe(true);
    expect(preview.run_id).toMatch(/^mock-run-/);
    expect(preview.events.at(-1)?.type).toBe("run_completed");
    expect(published.blueprint.status).toBe("published");
    expect(published.release.version).toBe(1);
  });

  it("reports invalid prompt and model fields", async () => {
    const api = createMockApiClient();
    const blueprint = { ...blueprintFromTemplate(templates[0]), display_name: "", system_prompt: "", model_ref: "" };

    const validation = await api.validateBlueprint(blueprint);

    expect(validation.ok).toBe(false);
    expect(validation.errors).toEqual(expect.arrayContaining([
      "Display name is required.",
      "System prompt is required.",
      "A model is required.",
    ]));
  });

  it("normalizes platform API DTOs for live mode", async () => {
    const fetchImpl: typeof fetch = async (input) => {
      const path = String(input);
      const payload = path.endsWith("/templates")
        ? { items: [{ id: "support", display_name: "Support", description: "Help", system_prompt: "Answer.", tool_refs: ["current_time"] }] }
        : path.endsWith("/resources")
          ? { items: [{ id: "current_time", kind: "tool", name: "Current time", supported: true, requires_approval: false }] }
          : path.endsWith("/blueprints")
            ? { items: [] }
            : {};
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    };
    const api = createLiveApiClient("http://local", fetchImpl);

    const liveTemplates = await api.listTemplates();
    const liveResources = await api.listResources();

    expect(liveTemplates[0].name).toBe("Support");
    expect(liveTemplates[0].prompt).toBe("Answer.");
    expect(liveResources[0].available).toBe(true);
  });
});
