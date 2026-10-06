# Mosaic Canvas Data Model

This document explains the model behind
[`contracts/canvas-document.schema.json`](../../contracts/canvas-document.schema.json).
The JSON Schema is authoritative; this file explains how the objects relate and
how they cross the Studio/control-plane/runtime boundary.

## 1. Four Object Families

```text
CanvasDocument       presentation + composition
AgentBlueprint       executable Agent intent
ResourceInstance     configured capability instance
WorkflowDefinition   reusable behavior module
```

### CanvasDocument

```ts
interface CanvasDocument {
  schema_version: "mosaic.canvas/v1";
  id: string;
  name: string;
  revision: number;
  status: "draft" | "published";
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  groups: CanvasGroup[];
  viewport: Viewport;
}
```

### CanvasNode

```ts
type CanvasNode = AgentCanvasNode | WorkflowCanvasNode | ResourceCanvasNode;

interface NodeLayout {
  id: string;
  position: { x: number; y: number };
  size: { width: number; height: number };
  z_index: number;
  collapsed?: boolean;
  locked?: boolean;
}

interface AgentCanvasNode extends NodeLayout {
  kind: "agent";
  blueprint_id: string;
  blueprint_revision?: number;
  behavior_mode: "agentic" | "workflow_assisted" | "workflow_first";
}

interface WorkflowCanvasNode extends NodeLayout {
  kind: "workflow";
  workflow_id: string;
  workflow_version?: number;
}

interface ResourceCanvasNode extends NodeLayout {
  kind: "resource";
  resource_instance_id: string;
}
```

The Studio may maintain a richer local view model around these objects, but the
persisted form must stay contract-valid and portable.

## 2. ResourceInstance

`ResourceDescriptor` describes what exists in the catalog. `ResourceInstance`
describes how one Agent uses it.

```ts
interface ResourceInstance {
  id: string;
  resource_id: string;
  kind: "model" | "tool" | "skill" | "memory" | "policy" | "connector";
  display_name: string;
  config: Record<string, unknown>;
  policy: {
    approval: "never" | "side_effects" | "always";
    credential_ref: string | null;
    timeout_seconds: number;
    max_retries: number;
  };
  validation: {
    status: "unknown" | "valid" | "invalid" | "stale";
    errors: string[];
    warnings: string[];
    validated_at: string | null;
  };
}
```

Raw credentials are forbidden. Only `env:` and `keychain:` references cross the
contract boundary.

## 3. WorkflowDefinition

Workflow is reusable and versioned. It is not required for Agentic mode.

```ts
interface WorkflowDefinition {
  id: string;
  name: string;
  version: number;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  nodes: WorkflowStep[];
  edges: WorkflowEdge[];
}

interface WorkflowStep {
  id: string;
  type: "trigger" | "agent" | "tool" | "condition" | "approval" | "output";
  object_ref?: string | null;
  config: Record<string, unknown>;
}

interface WorkflowEdge {
  id: string;
  source_step_id: string;
  target_step_id: string;
  condition?: string | null;
}
```

The separation matters:

```text
CanvasEdge       = relationship between top-level canvas objects
WorkflowEdge     = execution order inside one reusable workflow
```

## 4. Edge Semantics

```ts
type CanvasEdgeType = "owns" | "binds" | "invokes" | "handoff" | "feeds";

interface CanvasEdge {
  id: string;
  type: CanvasEdgeType;
  source_node_id: string;
  source_port: string;
  target_node_id: string;
  target_port: string;
  enabled: boolean;
  priority?: number;
  condition?: string | null;
}
```

Port compatibility is validated by the control plane. Studio should show a
highlight only for compatible targets, but the provider must validate again.

## 5. Runtime Projection

```text
CanvasDocument
  -> resolve AgentCanvasNode.blueprint_id
  -> resolve ResourceInstance configs and policies
  -> resolve WorkflowDefinition versions
  -> validate typed edges
  -> compile AgentBlueprint
  -> Mosaic Harness AgentSpec + ToolExecutionPolicy + runtime graph
```

The projection is one-way for execution. Runtime events can be linked to a
canvas node through `agent_name`, `resource_instance_id`, `workflow_id`, and
`run_id`, but runtime internals do not mutate the CanvasDocument.

## 6. Draft And Release Identity

| Object | Identity | Mutable? |
|---|---|---:|
| CanvasDocument | `id + revision` | Draft only |
| AgentBlueprint | `id + revision` | Draft only |
| ResourceInstance | `id` | Draft only |
| WorkflowDefinition | `id + version` | New version |
| ReleaseManifest | `release_id + version` | No |

Changing a runtime-relevant field makes validation `stale`. Changing only node
position or viewport does not require model/provider validation.

## 7. Migration Notes

The current Studio prototype has an `AgentCanvasNode` with embedded
`AgentBlueprintDto`, `attachedResourceIds`, and `attachedWorkflowIds`. The v1
migration should:

1. generate a stable `blueprint_id` for the embedded blueprint;
2. move layout into `CanvasDocument.nodes[]`;
3. convert each configured attachment to a `ResourceInstance`;
4. convert workflow attachments to `WorkflowCanvasNode` references;
5. preserve `behaviorMode` as `behavior_mode`;
6. write `revision: 0` and `status: "draft"`;
7. validate before autosaving.

