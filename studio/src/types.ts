export type RoomId = "plaza" | "core" | "gear" | "memory" | "safety" | "arena";
export type BlueprintStatus = "draft" | "published";
export type RuntimeMode = "mock" | "live";
export type ResourceKind = "model" | "tool" | "skill" | "workflow" | "policy";
export type AgentBehaviorMode = "agentic" | "workflow-assisted" | "workflow-first";

export interface PaletteResource {
  id: string;
  kind: ResourceKind;
  name: string;
  description: string;
  detail: string;
  risk_level: "low" | "medium" | "high";
  requires_approval: boolean;
  available: boolean;
  configFields: string[];
}

export interface AgentCanvasNode {
  id: string;
  blueprint: AgentBlueprintDto;
  x: number;
  y: number;
  behaviorMode: AgentBehaviorMode;
  attachedResourceIds: string[];
  attachedWorkflowIds: string[];
}

export interface TemplateDto {
  id: string;
  name: string;
  description: string;
  icon: string;
  tools: string[];
  prompt: string;
}

export interface ResourceDescriptorDto {
  id: string;
  kind: "model" | "tool" | "skill" | "capability" | "connector";
  name: string;
  description: string;
  risk_level: "low" | "medium" | "high";
  requires_approval: boolean;
  available: boolean;
}

export interface MemoryPolicyDto {
  short_term: boolean;
  long_term: boolean;
  namespace: string;
}

export interface SecurityPolicyDto {
  network: "none" | "allowlist";
  filesystem: "none" | "workspace";
  approvals: "never" | "side_effects";
}

export interface AgentBlueprintDto {
  id: string;
  slug: string;
  display_name: string;
  icon: string;
  pixel_theme: string;
  template_id: string;
  system_prompt: string;
  model_ref: string;
  tool_refs: string[];
  skill_refs: string[];
  memory_policy: MemoryPolicyDto;
  security_policy: SecurityPolicyDto;
  status: BlueprintStatus;
  version: number;
  changelog: string[];
}

export interface ValidationResultDto {
  ok: boolean;
  errors: string[];
  warnings?: string[];
  checks?: Array<{ id: string; label: string; ok: boolean; detail: string }>;
}

export interface PreviewRequestDto {
  input: string;
  user_id: string;
  session_id: string;
  thread_id: string;
}

export interface RunEventDto {
  id: string;
  type: "run_started" | "model_output" | "tool_call" | "tool_result" | "run_completed" | "run_failed";
  label: string;
  detail: string;
  timestamp: string;
}

export interface PreviewResultDto {
  run_id: string;
  output_text: string;
  events: RunEventDto[];
  duration_ms: number;
}

export interface ReleaseManifestDto {
  agent_name: string;
  version: number;
  blueprint_id: string;
  fingerprint: string;
  status: "published";
  api_path: string;
}

export interface ApiClient {
  listTemplates(): Promise<TemplateDto[]>;
  listResources(): Promise<ResourceDescriptorDto[]>;
  listBlueprints(): Promise<AgentBlueprintDto[]>;
  createBlueprint(blueprint: AgentBlueprintDto): Promise<AgentBlueprintDto>;
  updateBlueprint(blueprint: AgentBlueprintDto): Promise<AgentBlueprintDto>;
  validateBlueprint(blueprint: AgentBlueprintDto): Promise<ValidationResultDto>;
  previewBlueprint(blueprint: AgentBlueprintDto, request: PreviewRequestDto): Promise<PreviewResultDto>;
  publishBlueprint(blueprint: AgentBlueprintDto): Promise<{ blueprint: AgentBlueprintDto; release: ReleaseManifestDto }>;
}
