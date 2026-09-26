import type { AgentBlueprintDto, PaletteResource, ResourceDescriptorDto, RunEventDto, TemplateDto } from "./types";

export const rooms = [
  { id: "plaza", label: "Foundry plaza", detail: "Templates and projects", glyph: "P" },
  { id: "core", label: "Core workshop", detail: "Prompt and model", glyph: "C" },
  { id: "gear", label: "Gear shop", detail: "Tools and skills", glyph: "G" },
  { id: "memory", label: "Memory tower", detail: "Context and recall", glyph: "M" },
  { id: "safety", label: "Safety gate", detail: "Permissions", glyph: "S" },
  { id: "arena", label: "Training arena", detail: "Run and inspect", glyph: "T" },
] as const;

export const templates: TemplateDto[] = [
  {
    id: "researcher",
    name: "Research scout",
    description: "Primary-source research with clear uncertainty.",
    icon: "compass",
    tools: ["web_search", "fetch_url"],
    prompt: "Research carefully. Prefer primary sources, cite important claims, and state uncertainty when evidence is incomplete.",
  },
  {
    id: "support",
    name: "Support guide",
    description: "Clear customer answers with escalation boundaries.",
    icon: "speech",
    tools: ["current_time"],
    prompt: "Help the customer clearly. Ask for missing context, never invent policy, and explain when a human needs to take over.",
  },
  {
    id: "document-organizer",
    name: "Document organizer",
    description: "Turn local documents into structured findings.",
    icon: "folder",
    tools: ["list_files", "read_file", "search_document"],
    prompt: "Organize document contents into clear sections. Preserve source wording for important facts and identify missing information.",
  },
];

export const defaultResources: ResourceDescriptorDto[] = [
  { id: "openai:gpt-4.1-mini", kind: "model", name: "GPT-4.1 mini", description: "Fast tool-capable general model.", risk_level: "low", requires_approval: false, available: true },
  { id: "web_search", kind: "tool", name: "Web search", description: "Search public web sources.", risk_level: "medium", requires_approval: false, available: true },
  { id: "fetch_url", kind: "tool", name: "Fetch URL", description: "Read a URL returned by a search.", risk_level: "medium", requires_approval: false, available: true },
  { id: "current_time", kind: "tool", name: "Current time", description: "Read the local runtime clock.", risk_level: "low", requires_approval: false, available: true },
  { id: "read_file", kind: "tool", name: "Read file", description: "Read an approved workspace file.", risk_level: "high", requires_approval: true, available: true },
  { id: "search_document", kind: "skill", name: "Search document", description: "Find relevant passages in local documents.", risk_level: "medium", requires_approval: true, available: true },
];

export const paletteResources: PaletteResource[] = [
  { id: "openai:gpt-4.1-mini", kind: "model", name: "GPT-4.1 mini", description: "Fast tool-capable general model.", detail: "tool calling / streaming", risk_level: "low", requires_approval: false, available: true, configFields: ["provider", "model", "temperature"] },
  { id: "anthropic:claude-sonnet", kind: "model", name: "Claude Sonnet", description: "Reasoning-focused model provider.", detail: "reasoning / tool calling", risk_level: "low", requires_approval: false, available: true, configFields: ["provider", "model", "temperature"] },
  { id: "web_search", kind: "tool", name: "Web Search", description: "Search public web sources.", detail: "network / approval: no", risk_level: "medium", requires_approval: false, available: true, configFields: ["query", "limit", "network policy"] },
  { id: "fetch_url", kind: "tool", name: "Fetch URL", description: "Read a URL returned by a search.", detail: "network / allowlist", risk_level: "medium", requires_approval: false, available: true, configFields: ["url", "allowed domains"] },
  { id: "read_file", kind: "tool", name: "Read File", description: "Read an approved workspace file.", detail: "filesystem / approval: yes", risk_level: "high", requires_approval: true, available: true, configFields: ["workspace root", "approval"] },
  { id: "research-skill", kind: "skill", name: "Research Skill", description: "Research with source-aware instructions.", detail: "load on demand", risk_level: "low", requires_approval: false, available: true, configFields: ["load mode", "required tools"] },
  { id: "citation-skill", kind: "skill", name: "Citation Skill", description: "Keep claims connected to evidence.", detail: "load on demand", risk_level: "low", requires_approval: false, available: true, configFields: ["load mode"] },
  { id: "research-and-cite", kind: "workflow", name: "Research & Cite", description: "Search, inspect, and compose a sourced answer.", detail: "optional behavior module", risk_level: "medium", requires_approval: false, available: true, configFields: ["trigger", "steps", "output contract"] },
  { id: "human-review", kind: "workflow", name: "Human Review", description: "Pause an Agent run for a person to approve.", detail: "approval checkpoint", risk_level: "high", requires_approval: true, available: true, configFields: ["reviewer", "expiry", "approval policy"] },
  { id: "approval-policy", kind: "policy", name: "Side-effect Shield", description: "Require approval before side effects.", detail: "policy / gate", risk_level: "high", requires_approval: true, available: true, configFields: ["categories", "approvers"] },
];

export function blueprintFromTemplate(template: TemplateDto): AgentBlueprintDto {
  return {
    id: `local-${crypto.randomUUID()}`,
    slug: `${template.id}-agent`,
    display_name: template.name,
    icon: template.icon,
    pixel_theme: "foundry",
    template_id: template.id,
    system_prompt: template.prompt,
    model_ref: "openai:gpt-4.1-mini",
    tool_refs: [...template.tools],
    skill_refs: [],
    memory_policy: { short_term: true, long_term: false, namespace: `${template.id}-memory` },
    security_policy: { network: "allowlist", filesystem: "none", approvals: "side_effects" },
    status: "draft",
    version: 0,
    changelog: ["Created from template"],
  };
}

export function simulatedEvents(input: string, blueprint: AgentBlueprintDto): RunEventDto[] {
  const now = new Date().toISOString();
  return [
    { id: "event-1", type: "run_started", label: "Run started", detail: `Input received (${input.length} chars)`, timestamp: now },
    { id: "event-2", type: "model_output", label: "Model planned", detail: `${blueprint.model_ref} selected the next action`, timestamp: now },
    ...blueprint.tool_refs.slice(0, 1).map((tool, index) => ({
      id: `event-${index + 3}`,
      type: "tool_call" as const,
      label: "Tool call",
      detail: `${tool} called with mock-safe arguments`,
      timestamp: now,
    })),
    { id: "event-4", type: "run_completed", label: "Run completed", detail: "Mock adapter returned a deterministic response", timestamp: now },
  ];
}
