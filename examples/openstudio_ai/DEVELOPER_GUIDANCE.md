# OpenStudio AI Developer Guidance

This guide explains how the OpenStudio AI folder is organized, which modules
are for developers, which assets are exported into agent hosts, and what the
near-term deployment roadmap should prioritize.

The main rule is simple:

> Developers maintain the workbench. Claude Code, Codex, and other host agents
> consume the trusted runtime harness.

## Product Boundary

OpenStudio AI has two audiences.

1. Harness developers
   Build, test, review, validate, and promote OpenStudio AI assets.
2. End users through host agents
   Use OpenStudio AI through Claude Code, Codex, or another agent shell.

Not every folder is exported to a host agent. Some folders are source,
governance, review, or build machinery.

## Completed Baseline

The current implementation should be treated as the development baseline. These
pieces are in place:

- `openstudio_mcp/` is the stable MCP package name. It intentionally avoids the
  top-level name `mcp` so it does not shadow the Anthropic MCP Python package.
- Claude Code plugin export creates a local marketplace, plugin manifest,
  `.mcp.json`, commands, skills, knowledge, instructions, blackboard schemas,
  and runtime learning folders.
- Codex plugin export creates a local marketplace, plugin manifest, `.mcp.json`,
  skills, knowledge, instructions, blackboard schemas, and runtime learning
  folders.
- Runtime skills are exported as folder-per-skill packages. Skills and
  knowledge are not flattened into one large `CLAUDE.md`.
- HVAC child skills are generated from one YAML spec per skill plus a shared
  Jinja template.
- Developer-only skill management docs are excluded from runtime skill exports.
- Runtime learning exports include schemas and a local candidate area for
  session lessons, reusable recipes, and candidate measures.
- Developer learning has a deterministic pipeline runner that reads local logs
  and writes candidate lessons into a review queue.
- A developer learning agent contract exists for the future agent-assisted
  reflection loop.
- Focused tests cover Claude export, Codex export, learning pipeline behavior,
  SDK docs, and MCP smoke behavior.

## Current Deployment Limits

These are active engineering limits, not product vision gaps:

- Exported plugin `.mcp.json` files still point to the local BEM-AI checkout and
  current Python environment. A deployable release should provide an installed
  package entrypoint or vendored runtime.
- Learning promotion is intentionally gated. Runtime agents can propose
  candidates, but trusted assets still require review, validation, and explicit
  promotion.
- The blackboard is currently an AUTOMA-AI workflow management layer. It is
  exported as schema/context only for host agents, not as a host-native shared
  state service.
- The developer learning agent is specified, but the active runner is
  deterministic. Agent-assisted reflection should be added after review and
  eval gates are stable.

## Exported Runtime Harness

These are the assets a host adapter packages for Claude Code, Codex, or another
agent host.

- `openstudio_mcp/`
  The OpenStudio MCP server. This is the primary runtime tool surface for model
  operations, simulation, result queries, SDK doc lookup, and approved measures.

- `skills/*.md`
  Runtime skill files loaded by the host agent. These include parent workflow
  skills and generated child skills.

- `prompts/`
  System and project instruction contracts. Important files include
  `harness_system_prompt.md`, `blackboard_contract.md`,
  `learning_contract.md`, `promotion_rules.md`, and `openstudio_agent.md`.

- `knowledge/`
  Trusted, reviewed knowledge-base content. Only reviewed/promoted knowledge
  should be treated as exportable.

- `measures/approved/`
  Reviewed deterministic measures that are safe to expose through MCP.

- `blackboard/schemas/`
  Shared state schemas for long-running workflows.

- `learning/harness_pipeline/schemas/`
  Runtime candidate schemas for session lessons, reusable recipes, and candidate
  measures.

Host agents should consume these trusted runtime assets. They should not edit
developer source specs, templates, review queues, or candidate assets directly.

## Developer-Only Workbench

These folders are for maintaining and improving OpenStudio AI. They are not the
normal user-facing plugin payload.

- `skills/specs/`
  YAML source specs for generated child skills. Developers edit these, then run
  the generator to update runtime `.md` skills.

- `skills/templates/`
  Jinja templates for generated skills. Change these only when the shared child
  skill contract should change.

- `scripts/`
  Build, generation, and index scripts.

- `learning/`
  Developer and runtime learning pipeline code. This captures, distills,
  reviews, validates, and promotes lessons/assets.

- `evals/`
  Agent-behavior evals. Use these to validate promoted lessons, skills,
  measures, and SDK notes.

- `sdk_index/`
  Developer boundary for the future structured SDK index and knowledge graph.
  Only query capabilities should be exposed through MCP or adapters.

- `policy/`
  Governance, promotion, review, retention, allowlist, and runtime gate policy.

- `measures/candidates/`
  Draft measures generated by developers or runtime learning. These require
  review before publication.

- `state/`
  Local sessions, snapshots, candidate assets, and workflow-run state. This is
  runtime working storage, not trusted product content.

## Bridge Modules

These modules connect the developer workbench to the exported harness.

- `harness/`
  Defines the host-agnostic package boundary: prompts, skills, MCP entrypoint,
  blackboard schema, learning log, knowledge roots, and SDK index roots.

- `adapters/`
  Host-specific install/export logic. These modules translate the harness into
  Codex, Claude Code, or another host's configuration format.

The adapters should not contain product logic. Product logic belongs in MCP
tools, skills, blackboard operations, learning pipelines, and trusted assets.

## Mental Model

```text
Developer Workbench
  skills/specs
  skills/templates
  scripts
  learning
  evals
  sdk_index
  policy
  measures/candidates
        |
        v
Trusted Runtime Assets
  openstudio_mcp
  prompts
  skills/*.md
  knowledge
  measures/approved
  blackboard/schemas
  learning/harness_pipeline/schemas
        |
        v
Harness Export
  harness
  adapters/codex_adapter.py
  adapters/claude_code_adapter.py
        |
        v
Codex / Claude Code / Other Agent Hosts
```

## Developer Workstreams

### Developer 1: Runtime Harness And Host Adapters

Primary folders:

- `openstudio_mcp/`
- `blackboard/`
- `harness/`
- `adapters/`
- `prompts/`

Responsibilities:

1. Keep `harness/package_manifest.yaml` the authoritative package manifest.
2. Maintain Claude Code and Codex plugin exports from the same harness registry.
3. Keep MCP imports and package paths stable under
   `examples.openstudio_ai.openstudio_mcp`.
4. Replace local-checkout MCP launch config with a deployable runtime entrypoint.
5. Add validation that exported packages include MCP config, prompts, skills,
   knowledge, schemas, runtime learning assets, and approved measures.
6. Keep blackboard scope explicit: AUTOMA-AI-native now, MCP-backed later.

Current Claude Code export command:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin
```

The export command creates a local marketplace with `.claude-plugin/marketplace.json`
and an `openstudio-ai/` plugin folder containing `.claude-plugin/plugin.json`,
`.mcp.json`, `commands/`, `skills/`, `knowledge/`, `instructions/`,
`learning/`, and `blackboard/schemas/`.

Claude Code install flow:

```text
/plugin marketplace add /tmp/openstudio-ai-plugin
/plugin install openstudio-ai@openstudio-ai-local
/reload-plugins
```

Current Codex export command:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.codex_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-codex-plugin
```

The export command creates a repo-local Codex marketplace at
`.agents/plugins/marketplace.json` and a plugin folder at
`plugins/openstudio-ai/` containing `.codex-plugin/plugin.json`, `.mcp.json`,
`skills/`, `knowledge/`, `instructions/`, `learning/`, and
`blackboard/schemas/`.

Local project install remains available for Claude Code development:

```bash
.venv/bin/python -m examples.openstudio_ai.adapters.claude_code_adapter install \
  --target-dir /path/to/claude/project \
  --dry-run
```

The non-dry-run install command writes `.mcp.json` and `.claude/CLAUDE.md` into
the target project. Use plugin export as the preferred distributable path.

### Developer 2: Learning, Skill Quality, And Promotion

Primary folders:

- `learning/`
- `evals/`
- `skills/specs/`
- `skills/templates/`
- `knowledge/`
- `measures/candidates/`
- `measures/approved/`

Responsibilities:

1. Implement learning event capture for failures, user corrections, simulation
   warnings, review notes, and successful repeated workflows.
2. Distill raw events into candidate lessons, candidate skills, candidate
   measures, and eval cases.
3. Maintain a review queue format for candidate assets.
4. Require eval linkage before promotion.
5. Promote reviewed assets into `knowledge/`, `skills/*.md`,
   `measures/approved/`, or SDK index artifacts.
6. Keep generated child skills concise and synchronized with their YAML specs.

Current developer learning command:

```bash
.venv/bin/python -m examples.openstudio_ai.learning.developer_pipeline.run_pipeline
```

This writes candidate lessons to `learning/review_queue/`. Candidates are not
trusted assets until reviewed, validated, and promoted.

Runtime learning export:

- Claude/Codex exports include `learning/schemas/` and `learning/candidates/`.
- Claude exports include `/openstudio-ai:propose-measure`.
- Runtime candidates remain untrusted until reviewed and validated.

## Learning Pipeline Boundary

OpenStudio AI has two learning pipelines.

Developer learning pipeline:

- captures raw events from development and review;
- distills candidate assets;
- requires human/modeler review;
- validates through evals;
- promotes trusted assets.

Harness runtime learning pipeline:

- captures local repeated scripts, session lessons, and candidate recipes;
- may propose candidate measures;
- writes candidates to local/candidate storage;
- does not directly update trusted assets.

Runtime learning can suggest. Developer learning can promote.

## Promotion Rules

An asset should not move into trusted runtime content unless it has:

- source event lineage;
- reviewer approval;
- at least one linked eval case;
- a clear promotion target.

Allowed promotion targets:

- `knowledge/`
- `skills/*.md`
- `sdk_index/`
- `openstudio_mcp/`
- `measures/approved/`
- `evals/`

Do not promote directly from `state/`, `logs/`, or `measures/candidates/`
without review and validation.

## Skill Development Rules

Parent workflow skills are generally hand-authored.

Child workflow skills should be generated when they share a common structure.
For HVAC child skills:

- edit `skills/specs/hvac/*.yaml`;
- edit `skills/templates/hvac_child_skill.md.j2` only for shared structure;
- regenerate with `scripts/generate_hvac_child_skills.py`;
- run the generator check and focused tests.

Runtime hosts consume `skills/*.md`, not `skills/specs/*.yaml`.

## Adapter Development Rules

Adapters should make normal user setup simple.

Target user flow:

1. User installs OpenStudio AI or installs a packaged OpenStudio AI release.
2. User runs a host-specific setup or plugin marketplace command.
3. Adapter writes or previews host configuration.
4. Host agent loads prompts, skills, MCP server config, blackboard schema,
   runtime learning schemas, and trusted knowledge.
5. User works in Claude Code, Codex, or another host normally.

Adapters should provide:

- `--dry-run` before writing config;
- clear list of files they will create or modify;
- no direct modification of trusted assets;
- no hidden learning promotion.

## What Not To Export

Do not export these as normal host-agent runtime content:

- `skills/specs/`
- `skills/templates/`
- `scripts/`
- `learning/developer_pipeline/`
- `learning/developer_agent/`
- `evals/`
- `measures/candidates/`
- review queues;
- raw logs;
- local `state/` snapshots;
- development-only policy drafts.

These may be included in a developer distribution, but not in the normal
Claude/Codex runtime package.

## Near-Term Roadmap

### 1. Package The Runtime For Deployment

Replace local-checkout MCP references with a release entrypoint. The goal is an
exported plugin that can start `openstudio_ai` without relying on a developer's
repo path or active virtual environment.

Definition of done:

- installable Python package or vendored runtime path exists;
- exported `.mcp.json` uses the package entrypoint;
- adapter validation fails when required runtime dependencies are missing;
- Claude Code and Codex exports pass their validators after packaging.

### 2. Harden Adapter Validation

The adapters are now real product boundaries. Treat them like release tooling.

Definition of done:

- one command validates the harness manifest and both host exports;
- tests assert exported command metadata, skill folder layout, learning assets,
  and blackboard schemas;
- adapter docs show normal install, validation, and troubleshooting flows;
- generated packages contain no developer-only specs, templates, review queues,
  or raw logs.

### 3. Make Learning Promotion Operational

The learning architecture is present. The next step is to make the review and
promotion process executable end to end.

Definition of done:

- raw event examples cover script failures, simulation warnings, user
  corrections, review notes, and repeated successful workflows;
- candidate lesson, candidate measure, and candidate eval examples exist;
- review records capture approval, rejection, reviewer, rationale, and linked
  evidence;
- promotion scripts move approved assets into trusted targets only after eval
  linkage;
- promoted knowledge and measures include lineage metadata.

### 4. Add Agent-Assisted Developer Reflection

Use the `learning/developer_agent/` contract to add an agent loop that reflects
on telemetry and proposes candidates, while preserving deterministic gates.

Definition of done:

- the agent can read reviewable telemetry batches;
- it writes candidate assets in the same schemas as the deterministic runner;
- it cannot directly modify trusted assets;
- evals compare agent proposals against expected candidate structure and
  required evidence.

### 5. Prove The Augment Layer With VAV Workflow Evals

The parent/child VAV skill hierarchy should be validated as a planning system,
not only as markdown assets.

Definition of done:

- an eval checks that the parent skill initializes state and loads only the
  needed child skill for the current phase;
- child skill contracts include required fields, outputs, validation checks,
  and failure behavior;
- the eval confirms no full-system child context is loaded when one phase is
  enough;
- one golden VAV workflow trace is stored as a reference artifact.

### 6. Integrate SDK Index And Knowledge Retrieval

The SDK index should become a precise context retrieval layer rather than a
large static context dump.

Definition of done:

- MCP exposes SDK index lookup with class, method, and return-unit metadata;
- lessons learned can link to SDK symbols;
- exported instructions tell host agents when to query SDK index instead of
  loading broad docs;
- evals cover known traps such as radians-versus-degrees behavior.

### 7. Revisit Blackboard As A Shared Runtime Service

Keep the blackboard as AUTOMA-AI-native for now. Revisit MCP-backed state only
after adapter packaging, learning promotion, and VAV evals are stable.

Definition of done:

- clear decision on whether host agents need blackboard tools or only schemas;
- if needed, MCP operations cover initialize, patch, get phase state, mark step
  complete, and snapshot;
- parent workflow skills remain the owner of state mutation semantics.

## Direction For The Team

Developer 1 should focus on runtime packaging, adapter validation, host install
flows, and MCP stability.

Developer 2 should focus on learning pipeline operations, promotion gates,
workflow evals, skill quality, and knowledge/measure governance.

Both developers should keep the exported runtime harness small, reviewed, and
portable. The developer workbench can be larger because it is where experience
is captured, reviewed, validated, and promoted into the product.
