# CLAUDE.md

Guidance for Claude when working in the BEM-AI / AUTOMA-AI repository. Read
this together with `AGENTS.md` — that file is the source of truth for current
patterns, A2A 1.0 rules, the multi-agent migration checklist, and learning
mode. This file adds Claude-specific working principles on top of it.

## Core working principles

### 1. KISS — keep it simple and stupid

When asked to implement a feature, fix a bug, or address review comments,
always plan the simplest, most straightforward approach first.

- Prefer the smallest change that solves the problem. Fewer files, fewer
  abstractions, fewer moving parts.
- Reuse existing patterns in the repo (YAML agent specs, `AgentFactory`,
  `SubAgentSpec`, registry/config patterns) instead of inventing new ones.
- Do not introduce a new layer of indirection, plugin system, or framework
  unless the problem genuinely needs it. If two approaches both work, pick the
  one a senior engineer can read top-to-bottom in one sitting.
- Push back politely on requests that would add complexity without a clear
  payoff, and propose the simpler alternative.
- Avoid speculative generality: do not build hooks, registries, or extension
  points for "future" use cases that aren't in the current task.
- Before writing code, briefly state the plan in plain English (one short
  paragraph or a few bullets) so the user can redirect early if it's heavier
  than needed.

### 2. Comment helpers and non-obvious code

Code is read more than it's written. Add comments wherever a senior engineer
would have to pause and reason about *why*.

- Every helper function gets a short docstring saying what it does and, when
  relevant, why it exists separately from its caller.
- Any line or block that is not immediately obvious — non-trivial control
  flow, a workaround for an external library, a subtle ordering requirement,
  a thread-safety concern, a deliberate fallback — gets an inline comment
  that explains the *reason*, not just a restatement of the code.
- Prefer comments that capture intent and constraints ("must run before
  recorder is closed because…", "kept as `is` comparison so wrapped factories
  re-register cleanly") over comments that narrate syntax.
- Do not over-comment trivially obvious code. The bar is: would a senior
  engineer reading this cold pause here? If yes, comment.
- When fixing a bug, leave a brief comment near the fix referencing the
  failure mode it prevents, so the fix isn't accidentally undone later.

## Repo-specific reminders

- Follow the patterns in `AGENTS.md` for new agents and migrations: YAML
  specs first, `GenericAgentType.LANGGRAPHCHAT`, `SubAgentSpec` for
  multi-agent, A2A 1.0 card shape with `supportedInterfaces`.
- Avoid the legacy paths listed in `AGENTS.md` (`ORCHESTRATOR`,
  `agentic_network`, `chat_network`, workflow-graph orchestration, etc.).
- For telemetry work, the contract is: facade emits one stable AUTOMA record
  shape; core ships only `noop` and `jsonl`; OTEL/AgentCore live behind the
  recorder registry as opt-in plugins. Do not pull OpenTelemetry deps into
  core.
- After changes, use the smallest relevant verification (`py_compile`, a
  narrow import smoke check, the nearest targeted test). Do not expand scope
  on sandbox/socket failures — state the limitation and stop.

## Working style

- Plan briefly, implement minimally, comment where it helps a future reader.
- When addressing review comments, fix exactly what was asked. If a related
  issue is worth raising, mention it separately rather than bundling it into
  the same change.
- When in doubt between two designs, choose the one with less code and
  fewer concepts.
- Honor learning mode (see `AGENTS.md`) when the user says they are
  onboarding: explain before writing, verify understanding after.
