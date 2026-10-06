import { useCallback, useEffect, useMemo, useState } from "react";
import { createLiveApiClient, createMockApiClient } from "./api";
import { blueprintFromTemplate, defaultResources, paletteResources, templates } from "./data";
import {
  addAgentToCanvas,
  attachResourceToAgent,
  createCanvasBundle,
  getBrowserStorage,
  loadCanvasBundle,
  saveCanvasBundle,
} from "./canvas-model";
import type {
  AgentBehaviorMode,
  AgentBlueprintDto,
  AgentCanvasNode,
  ApiClient,
  PaletteResource,
  PreviewResultDto,
  ResourceDescriptorDto,
  RuntimeMode,
  TemplateDto,
  ValidationResultDto,
} from "./types";

type InspectorTab = "overview" | "bindings" | "workflows" | "test" | "release";

function useApiClient(mode: RuntimeMode): ApiClient {
  return useMemo(
    () => mode === "live"
      ? createLiveApiClient(import.meta.env.VITE_MOSAIC_API_BASE || "http://127.0.0.1:8787")
      : createMockApiClient(),
    [mode],
  );
}

function initialNode(template: TemplateDto, index: number): AgentCanvasNode {
  const blueprint = blueprintFromTemplate(template);
  return {
    id: blueprint.slug,
    blueprint,
    x: 18 + (index % 2) * 43,
    y: 20 + Math.floor(index / 2) * 32,
    behaviorMode: "agentic",
    attachedResourceIds: [...template.tools],
    attachedWorkflowIds: [],
  };
}

function viewNodesFromBundle(bundle: ReturnType<typeof createCanvasBundle>): AgentCanvasNode[] {
  return bundle.canvas.nodes.flatMap((canvasNode) => {
    if (canvasNode.kind !== "agent") return [];
    const blueprint = bundle.blueprints[canvasNode.blueprint_id];
    if (!blueprint) return [];
    const outgoing = bundle.canvas.edges.filter((edge) => edge.source_node_id === canvasNode.id);
    return [{
      id: canvasNode.id,
      blueprint,
      x: canvasNode.position.x,
      y: canvasNode.position.y,
      behaviorMode: canvasNode.behavior_mode,
      attachedResourceIds: outgoing.map((edge) => bundle.canvas.nodes.find((node) => node.id === edge.target_node_id)).filter((node): node is Extract<typeof node, { kind: "resource" }> => Boolean(node && node.kind === "resource")).map((node) => bundle.resource_instances[node.resource_instance_id]?.resource_id).filter(Boolean),
      attachedWorkflowIds: outgoing.map((edge) => bundle.canvas.nodes.find((node) => node.id === edge.target_node_id)).filter((node): node is Extract<typeof node, { kind: "workflow" }> => Boolean(node && node.kind === "workflow")).map((node) => bundle.workflows[node.workflow_id]?.id).filter(Boolean),
    }];
  });
}

export function FoundryApp() {
  const initialMode: RuntimeMode = import.meta.env.VITE_MOSAIC_MODE === "live" ? "live" : "mock";
  const [mode, setMode] = useState<RuntimeMode>(initialMode);
  const api = useApiClient(mode);
  const [canvasBundle, setCanvasBundle] = useState(() => {
    const storage = getBrowserStorage();
    return storage ? loadCanvasBundle(storage) : createCanvasBundle();
  });
  const [nodes, setNodes] = useState<AgentCanvasNode[]>(() => viewNodesFromBundle(canvasBundle));
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [resources, setResources] = useState<ResourceDescriptorDto[]>(defaultResources);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [tab, setTab] = useState<InspectorTab>("overview");
  const [config, setConfig] = useState<{ resource: PaletteResource; agentId: string } | null>(null);
  const [validation, setValidation] = useState<ValidationResultDto | null>(null);
  const [preview, setPreview] = useState<PreviewResultDto | null>(null);
  const [status, setStatus] = useState("Choose a template or drag a resource onto the canvas.");
  const [online, setOnline] = useState(mode === "mock");
  const [loading, setLoading] = useState(false);

  const selectedNode = nodes.find((node) => node.id === selectedAgentId) ?? null;

  const persistBundle = (nextBundle: typeof canvasBundle) => {
    setCanvasBundle(nextBundle);
    const storage = getBrowserStorage();
    if (storage) saveCanvasBundle(storage, nextBundle);
  };

  const syncBundleFromNodes = (nextNodes: AgentCanvasNode[], baseBundle = canvasBundle) => {
    const nextCanvasNodes = baseBundle.canvas.nodes.map((canvasNode) => {
      const viewNode = nextNodes.find((node) => node.id === canvasNode.id);
      if (!viewNode || canvasNode.kind !== "agent") return canvasNode;
      return {
        ...canvasNode,
        position: { x: viewNode.x, y: viewNode.y },
        behavior_mode: viewNode.behaviorMode,
        blueprint_revision: viewNode.blueprint.version,
      };
    });
    const nextBlueprints = nextNodes.reduce<Record<string, AgentBlueprintDto>>((all, node) => {
      all[node.blueprint.id] = node.blueprint;
      return all;
    }, { ...baseBundle.blueprints });
    persistBundle({
      ...baseBundle,
      canvas: { ...baseBundle.canvas, revision: baseBundle.canvas.revision + 1, nodes: nextCanvasNodes },
      blueprints: nextBlueprints,
    });
  };

  const refresh = useCallback(async () => {
    try {
      const nextResources = await api.listResources();
      setResources(nextResources);
      setOnline(true);
      setStatus(mode === "mock" ? "Mock canvas ready." : "Connected to local control plane.");
    } catch (error) {
      setOnline(false);
      setStatus(`Control plane unavailable: ${error instanceof Error ? error.message : "request failed"}`);
    }
  }, [api, mode]);

  useEffect(() => { void refresh(); }, [refresh]);

  const createFromTemplate = (template: TemplateDto) => {
    const node = initialNode(template, nodes.length);
    const nextNodes = [...nodes, node];
    const nextBundle = addAgentToCanvas(canvasBundle, node.blueprint, { x: node.x, y: node.y });
    persistBundle(nextBundle);
    setNodes(nextNodes);
    setSelectedAgentId(node.id);
    setTab("overview");
    setStatus(`${template.name} placed on the Mosaic Canvas.`);
  };

  const updateNode = (agentId: string, patch: Partial<AgentCanvasNode>) => {
    const nextNodes = nodes.map((node) => node.id === agentId ? { ...node, ...patch } : node);
    setNodes(nextNodes);
    syncBundleFromNodes(nextNodes);
  };

  const updateBlueprint = (patch: Partial<AgentBlueprintDto>) => {
    if (!selectedAgentId) return;
    const nextNodes = nodes.map((node) => node.id === selectedAgentId
      ? { ...node, blueprint: { ...node.blueprint, ...patch } }
      : node);
    setNodes(nextNodes);
    syncBundleFromNodes(nextNodes);
  };

  const resourceById = (id: string) => paletteResources.find((item) => item.id === id);

  const openResourceConfig = (resourceId: string, agentId = selectedAgentId) => {
    const resource = resourceById(resourceId);
    if (!resource || !agentId) {
      setStatus("Select an Agent before equipping a resource.");
      return;
    }
    setConfig({ resource, agentId });
  };

  const handleDrop = (event: React.DragEvent, agentId: string) => {
    event.preventDefault();
    const resourceId = event.dataTransfer.getData("text/plain") || event.dataTransfer.getData("text");
    if (resourceId) openResourceConfig(resourceId, agentId);
  };

  const handleCanvasDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const payload = event.dataTransfer.getData("text/plain");
    if (!payload.startsWith("canvas-agent:")) return;
    const agentId = payload.slice("canvas-agent:".length);
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(4, Math.min(78, ((event.clientX - rect.left) / rect.width) * 100));
    const y = Math.max(4, Math.min(78, ((event.clientY - rect.top) / rect.height) * 100));
    updateNode(agentId, { x, y });
    setStatus("Agent node position saved to the Canvas Document.");
  };

  const equipResource = (resourceConfig: Record<string, unknown>) => {
    if (!config) return;
    const node = nodes.find((item) => item.id === config.agentId);
    if (!node) return;
    const resource = config.resource;
    const resourceIds = Array.from(new Set([...node.attachedResourceIds, resource.id]));
    const blueprintPatch: Partial<AgentBlueprintDto> = {};
    if (resource.kind === "model") blueprintPatch.model_ref = resource.id;
    if (resource.kind === "tool") blueprintPatch.tool_refs = Array.from(new Set([...node.blueprint.tool_refs, resource.id]));
    if (resource.kind === "skill") blueprintPatch.skill_refs = Array.from(new Set([...node.blueprint.skill_refs, resource.id]));
    if (resource.kind === "policy") blueprintPatch.security_policy = { ...node.blueprint.security_policy, approvals: "side_effects" };
    const nextViewNodes = nodes.map((item) => item.id === config.agentId ? {
      ...item,
      attachedResourceIds: resourceIds,
      attachedWorkflowIds: resource.kind === "workflow"
        ? Array.from(new Set([...item.attachedWorkflowIds, resource.id]))
        : item.attachedWorkflowIds,
      blueprint: { ...item.blueprint, ...blueprintPatch },
    } : item);
    const configuredBundle = attachResourceToAgent(canvasBundle, config.agentId, {
      resource_id: resource.id,
      kind: resource.kind,
      display_name: resource.name,
      config: resourceConfig,
    });
    setNodes(nextViewNodes);
    syncBundleFromNodes(nextViewNodes, configuredBundle);
    setConfig(null);
    setStatus(`${resource.name} equipped on ${node.blueprint.display_name}.`);
  };

  const saveDraft = async () => {
    if (!selectedNode) return;
    setLoading(true);
    try {
      const saved = selectedNode.blueprint.id.startsWith("local-")
        ? await api.createBlueprint(selectedNode.blueprint)
        : await api.updateBlueprint(selectedNode.blueprint);
      updateBlueprint(saved);
      setStatus(mode === "mock" ? "Draft saved in mock workspace." : "Draft saved to local control plane.");
    } catch (error) {
      setStatus(`Draft save failed: ${error instanceof Error ? error.message : "request failed"}`);
    } finally {
      setLoading(false);
    }
  };

  const validate = async () => {
    if (!selectedNode) return;
    const result = await api.validateBlueprint(selectedNode.blueprint);
    setValidation(result);
    setStatus(result.ok ? "Agent blueprint passed validation." : "Agent blueprint needs attention.");
  };

  const publish = async () => {
    if (!selectedNode) return;
    setLoading(true);
    try {
      const result = await api.publishBlueprint(selectedNode.blueprint);
      updateBlueprint(result.blueprint);
      setStatus(`Release v${result.release.version} published.`);
    } catch (error) {
      setStatus(`Publish blocked: ${error instanceof Error ? error.message : "request failed"}`);
    } finally {
      setLoading(false);
    }
  };

  const runPreview = async (input: string) => {
    if (!selectedNode || !input.trim()) {
      setStatus("Enter a test input first.");
      return;
    }
    setLoading(true);
    try {
      const result = await api.previewBlueprint(selectedNode.blueprint, {
        input,
        user_id: "studio",
        session_id: "studio",
        thread_id: "studio",
      });
      setPreview(result);
      setStatus(`${mode === "mock" ? "Mock" : "Live"} run completed.`);
    } catch (error) {
      setStatus(`Run failed: ${error instanceof Error ? error.message : "request failed"}`);
    } finally {
      setLoading(false);
    }
  };

  const filteredResources = paletteResources.filter((resource) =>
    `${resource.name} ${resource.kind} ${resource.description}`.toLowerCase().includes(paletteQuery.toLowerCase()),
  );

  return (
    <div className="app-shell canvas-app">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div><p className="eyebrow">MOSAIC / FOUNDRY</p><h1>Agent Assembly Canvas</h1></div>
        </div>
        <div className="runtime-controls">
          <span className={`runtime-chip ${online ? "online" : "offline"}`}><span className="pulse" /> {mode === "mock" ? "MOCK CANVAS" : online ? "CONTROL PLANE" : "OFFLINE"}</span>
          <select aria-label="Runtime mode" value={mode} onChange={(event) => setMode(event.target.value as RuntimeMode)}><option value="mock">Mock mode</option><option value="live">Live control plane</option></select>
          <button className="icon-button" aria-label="Refresh resources" title="Refresh resources" onClick={() => void refresh()} disabled={loading}>↻</button>
        </div>
      </header>

      <main className="canvas-workspace">
        <ResourcePalette query={paletteQuery} onQueryChange={setPaletteQuery} resources={filteredResources} onDragStart={(event, resource) => event.dataTransfer.setData("text/plain", resource.id)} onPick={(resource) => openResourceConfig(resource.id)} />
        <section className="canvas-stage" aria-label="Mosaic Agent Canvas">
          <div className="canvas-toolbar"><div><p className="eyebrow">SYSTEM MAP</p><h2>Build Agents as playable systems</h2></div><div className="canvas-toolbar-meta"><span>{nodes.length} agents</span><span>{resources.length} resources</span><span>zoom 100%</span></div></div>
          <div className="canvas-board" data-testid="agent-canvas" onDragOver={(event) => event.preventDefault()} onDrop={handleCanvasDrop}>
            {nodes.length === 0 ? <TemplatePicker onCreate={createFromTemplate} /> : nodes.map((node) => <AgentNodeCard key={node.id} node={node} onSelect={() => { setSelectedAgentId(node.id); setTab("overview"); }} onDrop={(event) => handleDrop(event, node.id)} onDragOver={(event) => event.preventDefault()} onDragStart={(event) => event.dataTransfer.setData("text/plain", `canvas-agent:${node.id}`)} />)}
          </div>
          <div className="canvas-status"><span className="pixel-dot" />{status}</div>
        </section>
        <Inspector node={selectedNode} tab={tab} setTab={setTab} onBlueprintChange={updateBlueprint} onModeChange={(value) => selectedNode && updateNode(selectedNode.id, { behaviorMode: value })} onPickResource={(resource) => selectedNode && openResourceConfig(resource.id, selectedNode.id)} onSave={() => void saveDraft()} onValidate={() => void validate()} onPublish={() => void publish()} onPreview={(input) => void runPreview(input)} validation={validation} preview={preview} loading={loading} />
      </main>

      {config && <ResourceConfigModal resource={config.resource} onCancel={() => setConfig(null)} onEquip={equipResource} />}
      <footer className="statusbar"><span>Canvas document is independent from Mosaic Harness runtime.</span><span>schema v2 / local-first</span></footer>
    </div>
  );
}

function ResourcePalette({ query, onQueryChange, resources, onDragStart, onPick }: { query: string; onQueryChange: (value: string) => void; resources: PaletteResource[]; onDragStart: (event: React.DragEvent, resource: PaletteResource) => void; onPick: (resource: PaletteResource) => void }) {
  const groups = ["model", "tool", "skill", "workflow", "policy"] as const;
  return <aside className="resource-palette" aria-label="Resource palette"><div className="palette-heading"><div><p className="eyebrow">RESOURCE PALETTE</p><h2>Equip your Agent</h2></div><span className="palette-count">{resources.length}</span></div><p className="palette-help">Drag a resource onto an Agent, or click to configure.</p><input className="palette-search" aria-label="Search resources" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search tools, skills, models..." />{groups.map((kind) => { const items = resources.filter((resource) => resource.kind === kind); if (!items.length) return null; return <div className="palette-group" key={kind}><div className="palette-group-title">{kind === "model" ? "MODELS" : `${kind.toUpperCase()}S`}</div>{items.map((resource) => <button className={`palette-card palette-${resource.kind}`} data-testid={`palette-${resource.id}`} draggable onDragStart={(event) => onDragStart(event, resource)} onClick={() => onPick(resource)} key={resource.id} type="button"><span className="resource-swatch" /><span className="palette-card-copy"><strong>{resource.name}</strong><small>{resource.detail}</small></span><span className="resource-kind">{resource.kind}</span></button>)}</div>; })}</aside>;
}

function TemplatePicker({ onCreate }: { onCreate: (template: TemplateDto) => void }) {
  return <div className="template-picker"><div className="pixel-compass">+</div><p className="eyebrow">PLACE YOUR FIRST AGENT</p><h2>Choose a starting loadout</h2><p>Templates are launch pads. Every Agent stays editable after it lands on the canvas.</p><div className="template-grid">{templates.map((template) => <button className="template-card" data-testid={`template-${template.id}`} key={template.id} onClick={() => onCreate(template)} type="button"><span className="template-icon">{template.icon.slice(0, 1).toUpperCase()}</span><strong>{template.name}</strong><small>{template.description}</small><em>{template.tools.length} starter tools</em></button>)}</div></div>;
}

function AgentNodeCard({ node, onSelect, onDrop, onDragOver, onDragStart }: { node: AgentCanvasNode; onSelect: () => void; onDrop: (event: React.DragEvent) => void; onDragOver: (event: React.DragEvent) => void; onDragStart: (event: React.DragEvent) => void }) {
  const tools = node.blueprint.tool_refs.map((id) => paletteResources.find((resource) => resource.id === id)).filter(Boolean) as PaletteResource[];
  return <article className="agent-node" data-testid={`agent-node-${node.id}`} style={{ left: `${node.x}%`, top: `${node.y}%` }} onClick={onSelect} draggable onDragStart={onDragStart}><header className="agent-node-header"><span className="agent-avatar">A</span><div><strong>{node.blueprint.display_name}</strong><small>{node.behaviorMode}</small></div><span className="node-status">{node.blueprint.status}</span></header><div className="agent-model">◈ {node.blueprint.model_ref}</div><div className="agent-slot-label">DROP TO EQUIP</div><div className="agent-dropzone" data-testid={`agent-dropzone-${node.id}`} onDragOver={onDragOver} onDrop={onDrop}><span className="drop-plus">+</span><span>Tool / Skill / Workflow</span></div><div className="agent-loadout">{tools.map((tool) => <span className="loadout-chip" key={tool.id}>{tool.name}</span>)}{node.attachedWorkflowIds.map((id) => <span className="loadout-chip workflow-chip" key={id}>{paletteResources.find((resource) => resource.id === id)?.name ?? id}</span>)}</div><footer className="agent-node-footer"><span>{node.blueprint.tool_refs.length} tools</span><span>{node.blueprint.skill_refs.length} skills</span><span>{node.attachedWorkflowIds.length} workflows</span></footer></article>;
}

function Inspector({ node, tab, setTab, onBlueprintChange, onModeChange, onPickResource, onSave, onValidate, onPublish, onPreview, validation, preview, loading }: { node: AgentCanvasNode | null; tab: InspectorTab; setTab: (tab: InspectorTab) => void; onBlueprintChange: (patch: Partial<AgentBlueprintDto>) => void; onModeChange: (mode: AgentBehaviorMode) => void; onPickResource: (resource: PaletteResource) => void; onSave: () => void; onValidate: () => void; onPublish: () => void; onPreview: (input: string) => void; validation: ValidationResultDto | null; preview: PreviewResultDto | null; loading: boolean }) {
  const [input, setInput] = useState("");
  if (!node) return <aside className="agent-inspector empty-inspector"><span className="inspector-orb">M</span><p className="eyebrow">NO AGENT SELECTED</p><h2>Drop a template on the canvas</h2><p>Every Agent is an independent, movable object. Select it to edit its system prompt, model bindings, capabilities, and optional workflows.</p></aside>;
  const workflowNames = node.attachedWorkflowIds.map((id) => paletteResources.find((resource) => resource.id === id)?.name ?? id);
  return <aside className="agent-inspector" aria-label="Agent inspector"><div className="inspector-title"><span className="agent-avatar large">A</span><div><p className="eyebrow">SELECTED AGENT</p><h2>{node.blueprint.display_name}</h2><span className="mode-badge">{node.behaviorMode}</span></div><span className="node-status">{node.blueprint.status}</span></div><div className="inspector-tabs" role="tablist">{(["overview", "bindings", "workflows", "test", "release"] as InspectorTab[]).map((item) => <button role="tab" aria-selected={tab === item} className={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item} type="button">{item[0].toUpperCase() + item.slice(1)}</button>)}</div>{tab === "overview" && <div className="inspector-content"><label className="field"><span>Display name</span><input value={node.blueprint.display_name} onChange={(event) => onBlueprintChange({ display_name: event.target.value })} /></label><label className="field"><span>Behavior mode</span><select aria-label="Behavior mode" value={node.behaviorMode} onChange={(event) => onModeChange(event.target.value as AgentBehaviorMode)}><option value="agentic">Agentic loop</option><option value="workflow-assisted">Workflow assisted</option><option value="workflow-first">Workflow first</option></select></label><label className="field"><span>System prompt</span><textarea aria-label="System prompt" value={node.blueprint.system_prompt} onChange={(event) => onBlueprintChange({ system_prompt: event.target.value })} /></label><button className="primary-button wide" onClick={onSave} type="button">Save blueprint</button></div>}{tab === "bindings" && <div className="inspector-content"><div className="binding-section"><span className="section-kicker">MODEL</span><button className="binding-row" onClick={() => onPickResource(paletteResources.find((resource) => resource.kind === "model" && resource.id === node.blueprint.model_ref) ?? paletteResources[0])} type="button"><span className="binding-icon model-icon">◈</span><span><strong>{node.blueprint.model_ref}</strong><small>Primary reasoning engine</small></span></button></div><div className="binding-section"><span className="section-kicker">EQUIPPED CAPABILITIES</span><div className="equipped-list">{[...node.blueprint.tool_refs, ...node.blueprint.skill_refs].map((id) => <span className="equipped-chip" key={id}>{paletteResources.find((resource) => resource.id === id)?.name ?? id}</span>)}</div><button className="secondary-button" onClick={() => onPickResource(paletteResources.find((resource) => resource.kind === "tool") ?? paletteResources[0])} type="button">+ Add capability</button></div></div>}{tab === "workflows" && <div className="inspector-content"><div className="workflow-hero"><span className="workflow-glyph">W</span><div><strong>Optional behavior modules</strong><small>Attach workflows without changing the Agentic default.</small></div></div>{workflowNames.length ? workflowNames.map((name) => <div className="workflow-row" key={name}><span className="workflow-glyph">W</span><span><strong>{name}</strong><small>Optional behavior module</small></span><button className="icon-button" aria-label={`Edit ${name}`}>↗</button></div>) : <div className="empty-panel">No workflows attached yet.<br />Drag one from the Resource Palette onto this Agent.</div>}</div>}{tab === "test" && <div className="inspector-content"><label className="field"><span>Test input</span><textarea aria-label="Test input" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask this Agent to do something..." /></label><button className="primary-button wide" disabled={loading} onClick={() => onPreview(input)} type="button">{loading ? "Running..." : "Run Agent"}</button>{preview && <div className="run-panel"><pre>{preview.output_text}</pre><span>{preview.run_id}</span></div>}</div>}{tab === "release" && <div className="inspector-content"><div className="release-check"><strong>Release gate</strong><span className={validation?.ok ? "check-ok" : "check-pending"}>{validation?.ok ? "READY" : "PENDING VALIDATION"}</span></div><button className="secondary-button wide" onClick={onValidate} type="button">Validate Agent</button><button className="primary-button wide" disabled={loading || node.blueprint.status === "published"} onClick={onPublish} type="button">Publish version</button>{validation && <div className="validation-panel">{validation.errors.length ? validation.errors.join(" ") : "No blocking issues."}</div>}</div>}</aside>;
}

function ResourceConfigModal({ resource, onCancel, onEquip }: { resource: PaletteResource; onCancel: () => void; onEquip: (config: Record<string, unknown>) => void }) {
  const [values, setValues] = useState<Record<string, unknown>>(() => Object.fromEntries(resource.configFields.map((field) => [field, field === "load mode" ? "on demand" : ""])));
  return <div className="modal-backdrop" role="presentation"><div className="resource-modal" role="dialog" aria-modal="true" aria-labelledby="resource-modal-title"><header><span className={`resource-modal-swatch ${resource.kind}`} /> <div><p className="eyebrow">EQUIP RESOURCE / {resource.kind.toUpperCase()}</p><h2 id="resource-modal-title">Configure {resource.name}</h2></div><button className="modal-close" aria-label="Close configuration" onClick={onCancel} type="button">×</button></header><p className="modal-description">{resource.description}</p><div className="modal-fields">{resource.configFields.map((field) => <label className="field" key={field}><span>{field}</span><input value={String(values[field] ?? "")} onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))} placeholder={`Define ${field}`} /></label>)}</div><div className="modal-risk"><span className={`risk-dot ${resource.risk_level}`} /> <strong>{resource.risk_level} risk</strong><span>{resource.requires_approval ? "Approval required before side effects." : "No approval required."}</span></div><footer><button className="secondary-button" onClick={onCancel} type="button">Cancel</button><button className="primary-button" onClick={() => onEquip(values)} type="button">Equip resource</button></footer></div></div>;
}
