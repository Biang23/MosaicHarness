# Mosaic Canvas Interaction State v1

The diagram describes user-visible states and the transitions that are allowed
to mutate the Canvas draft. It deliberately separates transient interaction
state from persisted state.

## 1. End-to-End Interaction State

```mermaid
stateDiagram-v2
    [*] --> Loading
    Loading --> EmptyCanvas: no draft found
    Loading --> CanvasReady: draft loaded
    Loading --> LoadError: fetch failed
    LoadError --> Loading: retry

    EmptyCanvas --> TemplatePicker: choose template
    TemplatePicker --> CanvasReady: place Agent
    CanvasReady --> CanvasReady: pan / zoom / select / move node
    CanvasReady --> DraggingResource: drag palette resource
    CanvasReady --> ConnectingPorts: start edge from port
    CanvasReady --> InspectorOpen: click Agent / Workflow / Resource
    CanvasReady --> DirtyDraft: layout or graph mutation

    DraggingResource --> ResourceHover: pointer over canvas
    ResourceHover --> ConfigureResource: release on Agent port
    ResourceHover --> CreateResourceNode: release on empty canvas
    ResourceHover --> CanvasReady: cancel drag
    CreateResourceNode --> ConfigureResource: resource instance created
    ConfigureResource --> ValidatingResource: submit configuration
    ConfigureResource --> CanvasReady: cancel
    ValidatingResource --> EquippedResource: validation passed
    ValidatingResource --> ConfigurationError: validation failed
    ConfigurationError --> ConfigureResource: edit fields
    EquippedResource --> DirtyDraft: attach to Agent / Canvas

    ConnectingPorts --> EdgePreview: pointer over compatible port
    EdgePreview --> ConfigureEdge: release on port
    EdgePreview --> CanvasReady: invalid target / cancel
    ConfigureEdge --> DirtyDraft: save typed edge
    ConfigureEdge --> CanvasReady: cancel

    InspectorOpen --> InspectorOpen: edit prompt / mode / binding
    InspectorOpen --> DirtyDraft: field changed
    DirtyDraft --> SavingDraft: debounce autosave
    SavingDraft --> SavedDraft: revision accepted
    SavingDraft --> Conflict: revision is stale
    SavingDraft --> SaveError: network / storage failure
    Conflict --> MergeRequired: show remote revision
    MergeRequired --> SavingDraft: resolve and retry
    SaveError --> SavingDraft: retry

    CanvasReady --> PreviewPreflight: run test
    DirtyDraft --> PreviewPreflight: run test with current draft
    PreviewPreflight --> PreviewStreaming: validation passed
    PreviewPreflight --> ConfigurationError: validation failed
    PreviewStreaming --> ApprovalPending: side effect requires approval
    ApprovalPending --> PreviewStreaming: approved
    ApprovalPending --> PreviewFailed: denied / expired
    PreviewStreaming --> PreviewCompleted: run finished
    PreviewStreaming --> PreviewFailed: runtime error
    PreviewCompleted --> CanvasReady: inspect trace
    PreviewFailed --> CanvasReady: inspect error

    InspectorOpen --> PublishPreflight: publish
    PublishPreflight --> EvaluationPending: schema and graph valid
    PublishPreflight --> ConfigurationError: blocking issue
    EvaluationPending --> ReleaseReady: required evaluation passes
    EvaluationPending --> PublishBlocked: missing / failed gate
    ReleaseReady --> Published: create immutable release
    Published --> CanvasReady: continue editing as new draft
    PublishBlocked --> InspectorOpen: fix and retry
```

## 2. Resource Drop State

```mermaid
sequenceDiagram
    participant U as User
    participant P as Resource Palette
    participant C as Canvas
    participant M as Config Modal
    participant V as Validator
    participant D as Draft Store

    U->>P: begin drag Tool / Skill / Model / Workflow
    P->>C: drag payload {resource_id, kind}
    C-->>U: highlight compatible Agent ports
    U->>C: release on Agent port
    C->>M: open schema-driven configuration
    U->>M: fill config, permissions, approval
    M->>V: submit ResourceInstance
    alt valid
        V-->>M: valid + warnings
        M->>D: attach instance to draft
        D-->>C: new revision + equipped tile
        C-->>U: show loadout status
    else invalid
        V-->>M: field / capability / policy errors
        M-->>U: keep modal open with errors
    end
```

## 3. Agent Inspector State

```mermaid
stateDiagram-v2
    [*] --> Overview
    Overview --> Overview: edit display name / system prompt
    Overview --> Bindings: open Bindings tab
    Bindings --> Bindings: add or remove ResourceInstance
    Bindings --> ConfigureResource: click Add capability
    Overview --> Workflows: open Workflows tab
    Workflows --> Workflows: attach / detach WorkflowDefinition
    Workflows --> ConfigureWorkflow: configure workflow reference
    Overview --> Test: open Test tab
    Test --> PreviewPreflight: run Agent
    Overview --> Release: open Release tab
    Release --> Validate: validate Agent and Canvas
    Validate --> Release: display doctor / graph / security checks
    Release --> PublishPreflight: publish version
```

## 4. Persisted Versus Ephemeral State

| State | Persisted? | Reason |
|---|---:|---|
| Agent node position | yes | Reopen the workspace where the user left it. |
| Canvas viewport | yes | Preserve workspace orientation. |
| Agent blueprint reference | yes | Runtime compilation input. |
| Resource instance config | yes | Executable behavior and policy. |
| Workflow attachment | yes | Executable capability relationship. |
| Typed Canvas edge | yes | Agent/Workflow composition semantics. |
| Selected node | no | UI-only preference. |
| Open modal | no | Transient interaction. |
| Drag preview line | no | Transient interaction. |
| Loading spinner | no | Request state. |
| Run event trace | no in CanvasDocument | Stored by run journal and referenced by run ID. |

## 5. Failure And Recovery Rules

- A failed resource configuration never creates an equipped instance.
- A stale autosave returns a conflict; it never overwrites the newer revision.
- A rejected edge is removed from the preview and never enters the document.
- Preview can run against a draft snapshot, but it cannot publish or mutate the
  production runtime registry.
- A denied approval ends the affected run with an explicit event; it is not a
  generic tool failure.
- A failed evaluation gate leaves the draft editable and does not create a
  release.
- Browser refresh restores the latest saved document, not unsent transient UI
  state.

