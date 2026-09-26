import { defaultResources, simulatedEvents, templates } from "./data";
import type { AgentBlueprintDto, ApiClient, PreviewRequestDto, PreviewResultDto, ReleaseManifestDto, ResourceDescriptorDto, TemplateDto, ValidationResultDto } from "./types";

const jsonHeaders = { "content-type": "application/json" };

export function createLiveApiClient(baseUrl: string, fetchImpl: typeof fetch = fetch): ApiClient {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: { ...jsonHeaders, ...(init?.headers ?? {}) },
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json() as Promise<T>;
  }
  return {
    async listTemplates() { return (await request<{ items: Record<string, unknown>[] }>("/templates")).items.map(normalizeTemplate); },
    async listResources() { return (await request<{ items: Record<string, unknown>[] }>("/resources")).items.map(normalizeResource); },
    async listBlueprints() { return (await request<{ items: Record<string, unknown>[] }>("/blueprints")).items.map(normalizeBlueprint); },
    async createBlueprint(blueprint) { return normalizeBlueprint(await request<Record<string, unknown>>("/blueprints", { method: "POST", body: JSON.stringify(blueprint) })); },
    async updateBlueprint(blueprint) { return normalizeBlueprint(await request<Record<string, unknown>>(`/blueprints/${blueprint.id}`, { method: "PATCH", body: JSON.stringify(blueprint) })); },
    validateBlueprint(blueprint) { return request<ValidationResultDto>(`/blueprints/${blueprint.id}/validate`, { method: "POST", body: "{}" }); },
    async previewBlueprint(blueprint, requestDto) {
      const result = await request<Record<string, unknown>>(`/blueprints/${blueprint.id}/preview`, { method: "POST", body: JSON.stringify(requestDto) });
      return {
        run_id: String(result.run_id ?? ""),
        output_text: String(result.output_text ?? ""),
        events: [],
        duration_ms: Number(result.duration_ms ?? 0),
      };
    },
    async publishBlueprint(blueprint) {
      const release = await request<Record<string, unknown>>(`/blueprints/${blueprint.id}/publish`, { method: "POST", body: "{}" });
      const version = Number(release.version ?? blueprint.version + 1);
      return {
        blueprint: normalizeBlueprint({ ...blueprint, status: "published", version }),
        release: normalizeRelease(release, blueprint),
      };
    },
  };
}

function normalizeTemplate(value: Record<string, unknown>): TemplateDto {
  return {
    id: String(value.id ?? ""),
    name: String(value.name ?? value.display_name ?? value.id ?? "Template"),
    description: String(value.description ?? ""),
    icon: String(value.icon ?? "agent"),
    tools: asStringArray(value.tools ?? value.tool_refs),
    prompt: String(value.prompt ?? value.system_prompt ?? ""),
  };
}

function normalizeResource(value: Record<string, unknown>): ResourceDescriptorDto {
  return {
    id: String(value.id ?? ""),
    kind: (value.kind as ResourceDescriptorDto["kind"]) ?? "tool",
    name: String(value.name ?? value.id ?? "Resource"),
    description: String(value.description ?? ""),
    risk_level: (value.risk_level as ResourceDescriptorDto["risk_level"]) ?? "low",
    requires_approval: Boolean(value.requires_approval),
    available: Boolean(value.available ?? value.supported ?? true),
  };
}

function normalizeBlueprint(value: Record<string, unknown>): AgentBlueprintDto {
  const memory = (value.memory_policy ?? {}) as Record<string, unknown>;
  const security = (value.security_policy ?? {}) as Record<string, unknown>;
  return {
    id: String(value.id ?? `local-${Date.now()}`),
    slug: String(value.slug ?? "agent"),
    display_name: String(value.display_name ?? "Agent"),
    icon: String(value.icon ?? "agent"),
    pixel_theme: String(value.pixel_theme ?? "foundry"),
    template_id: String(value.template_id ?? "blank"),
    system_prompt: String(value.system_prompt ?? ""),
    model_ref: typeof value.model_ref === "string" ? value.model_ref : "openai:gpt-4.1-mini",
    tool_refs: asStringArray(value.tool_refs),
    skill_refs: asStringArray(value.skill_refs),
    memory_policy: {
      short_term: Boolean(memory.short_term ?? true),
      long_term: Boolean(memory.long_term ?? memory.write ?? false),
      namespace: String(memory.namespace ?? value.slug ?? "agent-memory"),
    },
    security_policy: {
      network: security.network === "allowlist" ? "allowlist" : "none",
      filesystem: security.filesystem === "workspace" ? "workspace" : "none",
      approvals: security.approvals === "never" ? "never" : "side_effects",
    },
    status: value.status === "published" ? "published" : "draft",
    version: Number(value.version ?? 0),
    changelog: Array.isArray(value.changelog) ? value.changelog.map(String) : value.changelog ? [String(value.changelog)] : [],
  };
}

function normalizeRelease(value: Record<string, unknown>, blueprint: AgentBlueprintDto): ReleaseManifestDto {
  return {
    agent_name: String(value.agent_name ?? value.slug ?? blueprint.slug),
    version: Number(value.version ?? blueprint.version + 1),
    blueprint_id: String(value.blueprint_id ?? blueprint.id),
    fingerprint: String(value.fingerprint ?? ""),
    status: "published",
    api_path: String(value.api_path ?? `/agents/${value.slug ?? blueprint.slug}`),
  };
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

export function createMockApiClient(): ApiClient {
  let blueprints: AgentBlueprintDto[] = [];
  return {
    async listTemplates() { return templates; },
    async listResources() { return defaultResources; },
    async listBlueprints() { return blueprints; },
    async createBlueprint(blueprint) {
      blueprints = [...blueprints.filter((item) => item.id !== blueprint.id), { ...blueprint }];
      return { ...blueprint };
    },
    async updateBlueprint(blueprint) {
      blueprints = blueprints.map((item) => item.id === blueprint.id ? { ...blueprint } : item);
      return { ...blueprint };
    },
    async validateBlueprint(blueprint) {
      const errors: string[] = [];
      if (!blueprint.display_name.trim()) errors.push("Display name is required.");
      if (!blueprint.system_prompt.trim()) errors.push("System prompt is required.");
      if (!blueprint.model_ref.trim()) errors.push("A model is required.");
      if (blueprint.tool_refs.includes("read_file") && blueprint.security_policy.filesystem === "none") errors.push("Read file requires workspace filesystem access.");
      return {
        ok: errors.length === 0,
        errors,
        warnings: blueprint.tool_refs.length === 0 ? ["This agent has no tools equipped."] : [],
        checks: [
          { id: "identity", label: "Identity", ok: Boolean(blueprint.display_name.trim()), detail: "Name is present" },
          { id: "prompt", label: "Prompt", ok: Boolean(blueprint.system_prompt.trim()), detail: "System prompt is present" },
          { id: "model", label: "Model", ok: Boolean(blueprint.model_ref.trim()), detail: "Model selected" },
        ],
      };
    },
    async previewBlueprint(blueprint, request: PreviewRequestDto) {
      return {
        run_id: `mock-run-${Date.now()}`,
        output_text: `mock run\n\ninput: ${request.input}\n\nagent: ${blueprint.display_name}\nstatus: simulated response`,
        events: simulatedEvents(request.input, blueprint),
        duration_ms: 184,
      };
    },
    async publishBlueprint(blueprint) {
      const published = { ...blueprint, status: "published" as const, version: Math.max(1, blueprint.version + 1), changelog: [...blueprint.changelog, "Published from Studio"] };
      blueprints = blueprints.map((item) => item.id === blueprint.id ? published : item);
      return {
        blueprint: published,
        release: { agent_name: published.slug, version: published.version, blueprint_id: published.id, fingerprint: `mock-${published.id}-${published.version}`, status: "published", api_path: `/agents/${published.slug}` },
      };
    },
  };
}
