import type {
  AgentBlueprintDto,
  CanvasAgentNode,
  CanvasBundle,
  CanvasDocument,
  CanvasEdge,
  CanvasNode,
  CanvasPosition,
  CanvasResourceNode,
  CanvasWorkflowNode,
  PaletteResource,
  ResourceInstance,
  WorkflowDefinition,
} from "./types";

export const CANVAS_STORAGE_KEY = "mosaic.canvas.bundle.v1";

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function id(prefix: string): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

export function createCanvasBundle(name = "Untitled Canvas"): CanvasBundle {
  const canvas: CanvasDocument = {
    schema_version: "mosaic.canvas/v1",
    id: id("canvas"),
    name,
    description: "",
    revision: 0,
    status: "draft",
    nodes: [],
    edges: [],
    groups: [],
    viewport: { x: 0, y: 0, zoom: 1 },
  };
  return { canvas, blueprints: {}, resource_instances: {}, workflows: {} };
}

export function addAgentToCanvas(
  bundle: CanvasBundle,
  blueprint: AgentBlueprintDto,
  position: CanvasPosition,
): CanvasBundle {
  const node: CanvasAgentNode = {
    id: blueprint.slug,
    kind: "agent",
    blueprint_id: blueprint.id,
    blueprint_revision: blueprint.version,
    behavior_mode: "agentic",
    position,
    size: { width: 330, height: 250 },
    z_index: bundle.canvas.nodes.length,
  };
  return {
    ...bundle,
    canvas: { ...bundle.canvas, revision: bundle.canvas.revision + 1, nodes: [...bundle.canvas.nodes, node] },
    blueprints: { ...bundle.blueprints, [blueprint.id]: blueprint },
  };
}

export function attachResourceToAgent(
  bundle: CanvasBundle,
  agentNodeId: string,
  input: {
    resource_id: string;
    kind: PaletteResource["kind"];
    display_name: string;
    config: Record<string, unknown>;
  },
): CanvasBundle {
  const agent = bundle.canvas.nodes.find((node): node is CanvasAgentNode => node.id === agentNodeId && node.kind === "agent");
  if (!agent) throw new Error(`agent node '${agentNodeId}' not found`);

  if (input.kind === "workflow") {
    const workflowId = id(`workflow-${input.resource_id}`);
    const workflow: WorkflowDefinition = {
      id: workflowId,
      name: input.display_name,
      version: 1,
      input_schema: {},
      output_schema: {},
      nodes: [],
      edges: [],
    };
    const workflowNode: CanvasWorkflowNode = {
      id: id("workflow-node"),
      kind: "workflow",
      workflow_id: workflowId,
      workflow_version: 1,
      position: { x: agent.position.x + 35, y: agent.position.y + 28 },
      size: { width: 280, height: 190 },
      z_index: bundle.canvas.nodes.length,
    };
    const edge: CanvasEdge = {
      id: id("edge"),
      type: "invokes",
      source_node_id: agent.id,
      source_port: "workflows",
      target_node_id: workflowNode.id,
      target_port: "input",
      enabled: true,
    };
    return {
      ...bundle,
      canvas: { ...bundle.canvas, revision: bundle.canvas.revision + 1, nodes: [...bundle.canvas.nodes, workflowNode], edges: [...bundle.canvas.edges, edge] },
      workflows: { ...bundle.workflows, [workflow.id]: workflow },
    };
  }

  const instance: ResourceInstance = {
    id: id("resource"),
    resource_id: input.resource_id,
    kind: input.kind === "policy" ? "policy" : input.kind,
    display_name: input.display_name,
    config: input.config,
    policy: {
      approval: input.kind === "policy" ? "side_effects" : "never",
      credential_ref: null,
      timeout_seconds: 30,
      max_retries: 0,
    },
    validation: { status: "valid", errors: [], warnings: [], validated_at: new Date().toISOString() },
  };
  const resourceNode: CanvasResourceNode = {
    id: id("resource-node"),
    kind: "resource",
    resource_instance_id: instance.id,
    position: { x: agent.position.x + 28, y: agent.position.y + 32 },
    size: { width: 180, height: 72 },
    z_index: bundle.canvas.nodes.length,
  };
  const port = input.kind === "model" ? "model" : input.kind === "skill" ? "skills" : "tools";
  const edge: CanvasEdge = {
    id: id("edge"),
    type: input.kind === "model" ? "binds" : "owns",
    source_node_id: agent.id,
    source_port: port,
    target_node_id: resourceNode.id,
    target_port: port,
    enabled: true,
  };
  return {
    ...bundle,
    canvas: { ...bundle.canvas, revision: bundle.canvas.revision + 1, nodes: [...bundle.canvas.nodes, resourceNode], edges: [...bundle.canvas.edges, edge] },
    resource_instances: { ...bundle.resource_instances, [instance.id]: instance },
  };
}

export function saveCanvasBundle(storage: StorageLike, bundle: CanvasBundle): void {
  storage.setItem(CANVAS_STORAGE_KEY, JSON.stringify(bundle));
}

export function loadCanvasBundle(storage: StorageLike): CanvasBundle {
  const raw = storage.getItem(CANVAS_STORAGE_KEY);
  if (!raw) return createCanvasBundle();
  try {
    const parsed = JSON.parse(raw) as CanvasBundle;
    if (parsed?.canvas?.schema_version !== "mosaic.canvas/v1" || !Array.isArray(parsed.canvas.nodes)) {
      return createCanvasBundle();
    }
    return parsed;
  } catch {
    return createCanvasBundle();
  }
}

export function getBrowserStorage(): StorageLike | null {
  if (typeof window === "undefined" || !window.localStorage || typeof window.localStorage.getItem !== "function") return null;
  return window.localStorage;
}

export function canvasNodesForAgent(bundle: CanvasBundle, agentId: string): CanvasNode[] {
  const agent = bundle.canvas.nodes.find((node) => node.id === agentId);
  if (!agent) return [];
  return bundle.canvas.edges
    .filter((edge) => edge.source_node_id === agentId)
    .map((edge) => bundle.canvas.nodes.find((node) => node.id === edge.target_node_id))
    .filter((node): node is CanvasNode => Boolean(node));
}
