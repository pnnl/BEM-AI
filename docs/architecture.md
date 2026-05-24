# AUTOMA-AI Architecture Principles

*A north-star guide for building integration-first, stateful, and interoperable agent systems.*

AUTOMA-AI is designed to support production-oriented agent systems that must survive beyond a notebook, demo, or one-off prompt chain. It provides composable agent infrastructure for applications that need persistent state, human checkpoints, external tools, distributed agents, traceable artifacts, and replaceable infrastructure.

This document describes the architectural principles that should guide AUTOMA-AI development. It is not an API reference. Instead, it defines what the framework is optimizing for and how future contributors should evaluate new features.

## 1. Purpose of AUTOMA-AI

AUTOMA-AI exists to help teams build agent systems that can be integrated into real applications. These systems often need to coordinate multiple agents, call external tools, persist workflow state, retrieve domain knowledge, support human review, and run across local and cloud environments.

AUTOMA-AI is not trying to be the simplest possible agent demo framework. It is designed for cases where integration, state management, extensibility, and deployment flexibility matter.

The core purpose is:

> AUTOMA-AI provides integration-first composable agent infrastructure for stateful, production-oriented workflows.

This means the framework should help users assemble agent systems from interchangeable components rather than require them to adopt a monolithic stack.

## 2. Architectural Philosophy

AUTOMA-AI is guided by five architectural principles.

### Protocol-first

Where possible, AUTOMA-AI should use open protocols for integration boundaries. Agent collaboration can use Google A2A. Tool and context integration can use MCP. Protocols make agents and tools more reusable across frameworks, services, and deployment environments.

### Interface-first

AUTOMA-AI should provide stable contracts before assuming one implementation. Tools, memory stores, retrievers, blackboards, checkpointers, and model providers should be replaceable when they satisfy the expected interface.

### State-aware

Production workflows need more than chat history. AUTOMA-AI should treat workflow state, intermediate artifacts, checkpoints, and human decisions as first-class concerns.

### Production-oriented

The framework should support real application needs such as persistence, validation gates, distributed deployment, service integration, observability, and cloud-ready infrastructure patterns. Production-oriented does not mean every interface is fully mature today; it means these requirements shape the architecture.

### Framework-composable

AUTOMA-AI should integrate with existing ecosystems such as LangChain, LangGraph, A2A, MCP, cloud services, local tools, and application backends. It should not assume every useful component must be implemented inside AUTOMA-AI.

## 3. System Model

At a high level, an AUTOMA-AI application can be viewed as layered execution infrastructure:

```text
User / Application
        ↓
Orchestrator / Agent
        ↓
Skills / Workflow Instructions
        ↓
Tools / MCP / Retrieval / Memory / Blackboard
        ↓
External Systems and Data
```

For multi-agent workflows, agents may collaborate through local delegation, remote A2A services, or shared state:

```text
Agent A ── local delegation or A2A ── Agent B
   │                                     │
   └────────── Shared Blackboard ────────┘
```

AUTOMA-AI systems commonly use several coordination channels:

- **Conversation history** for dialogue context.
- **Blackboard/shared state** for structured workflow artifacts.
- **Tools and MCP servers** for external executable capabilities.
- **Retrievers** for grounding agents in domain knowledge.
- **Memory stores** for session and longer-term context.
- **A2A or local delegation** for agent-to-agent collaboration.
- **Checkpointers** for resumable execution.

This model is intentionally broader than agents simply sending messages to each other. AUTOMA-AI is a structured execution environment for stateful workflows.

## 4. Agents: Local Components and Remote Services

An AUTOMA-AI agent is a reasoning and execution unit configured with instructions, model provider, tools, memory, retrieval, skills, and optional collaboration mechanisms.

Agents can be used in two primary forms:

1. **Local agents** running in the same Python process.
2. **Remote agents** exposed as A2A-compatible services.

Local agents are useful for simple applications, testing, and tightly coupled workflows. Remote A2A agents are useful when agents need to be independently deployed, discovered, reused, scaled, or owned by different teams.

A2A is an important integration option, but it should not be mandatory for every use case. AUTOMA-AI should support direct local composition first and allow protocol-based deployment when distributed ownership, scaling, isolation, or reuse becomes important.

## 5. Protocol-First Collaboration

AUTOMA-AI uses protocol-first design to reduce lock-in and improve reuse. An agent or tool should be useful even when called from another framework, service, or application.

Two protocols are especially important:

- **Google A2A** for agent-to-agent communication and distributed agent collaboration.
- **Model Context Protocol (MCP)** for exposing tools and contextual capabilities to agents.

Protocol-first design does not mean protocol-only design. For simple local workflows, protocol overhead may not be necessary. AUTOMA-AI should support local composition where it is simpler, and protocol-based boundaries where reuse, deployment independence, scaling, or organizational ownership matter.

The guiding principle is:

> Use local composition for simplicity. Use protocol boundaries for interoperability, distribution, and reuse.

## 6. Interface-First / Plugin-and-Play Design

AUTOMA-AI should provide interfaces rather than force a single fixed implementation. Defaults are important for onboarding, but defaults should not become architectural assumptions.

Major extension points include:

| Interface | Purpose | Example implementations |
| --- | --- | --- |
| Tool interface | Expose executable capabilities | Local Python functions, REST APIs, MCP tools |
| Memory store | Persist conversation or long-term context | In-memory, SQLite, Chroma, DynamoDB, custom stores |
| Blackboard | Store structured workflow artifacts | In-memory, Redis, database-backed store, cloud store |
| Checkpointer | Persist workflow execution state | In-memory, Redis, AWS-backed checkpointer |
| Retriever | Ground agents in external knowledge | Chroma, OpenSearch, custom vector database |
| Model provider | Swap LLM hosts | OpenAI, Azure OpenAI, Bedrock, Google GenAI, Ollama |
| Agent collaboration | Connect agents locally or remotely | Local delegation, A2A services |

This plugin-and-play interface design allows teams to change infrastructure without rewriting the entire agent workflow. A prototype may use in-memory state and local tools. A production system may use Redis checkpointing, DynamoDB memory, MCP tool servers, and cloud-hosted model providers.

The framework should prefer:

- Interface before implementation.
- Configuration before hard-coded behavior.
- Replaceable components before fixed dependencies.
- Application-specific implementations outside the core framework when possible.

## 7. Blackboard and Shared State

The shared blackboard is one of the most important concepts in AUTOMA-AI. It is a structured state layer where agents and workflows can write intermediate artifacts, decisions, user-approved content, retrieved evidence, and task outputs.

A chat-history-only workflow often works like this:

```text
Agent A says something → Agent B reads text → Agent C infers state
```

A blackboard-based workflow works more like this:

```text
Agent A writes artifact → Agent B reads artifact → Agent C updates artifact
```

The blackboard should be treated as the source of truth for intermediate workflow artifacts. Conversation history may explain how the system got there, but the blackboard records what the workflow currently believes to be true.

Benefits include:

- **Traceability**: Intermediate decisions and artifacts are inspectable.
- **Token efficiency**: Agents can reference stored artifacts instead of replaying full context.
- **Determinism**: Workflows can read and write known state keys.
- **Human checkpoints**: Users can approve or revise structured artifacts before the next step.
- **Pause/resume**: Workflows can continue from stored state rather than reconstructing everything from chat history.

The blackboard is not just memory. It is workflow state and artifact management.

## 8. Skills vs Tools

AUTOMA-AI separates skills from tools because they serve different purposes.

**Tools** are executable capabilities. Examples include:

- Searching the web.
- Running Python.
- Querying a database.
- Calling an EnergyPlus or OpenStudio workflow.
- Fetching a weather file.
- Retrieving an object schema.

**Skills** are reusable reasoning and task instructions. Examples include:

- Drafting a project description.
- Recommending a categorical exclusion.
- Validating an EnergyPlus object.
- Summarizing an environmental screening result.
- Performing compliance reasoning.

A skill should encode task strategy, expected process, constraints, and output contract. A tool should expose an action the agent can invoke.

Keeping these concepts separate makes workflows easier to test, reuse, and govern. Tools do things. Skills guide how agents should think through and complete tasks.

## 9. Orchestration and Workflow Control

AUTOMA-AI supports multi-agent collaboration, but production workflows often need explicit orchestration rather than uncontrolled agent chatter.

An orchestrator may be responsible for:

- Selecting the next workflow step.
- Calling specialized agents.
- Managing blackboard state.
- Enforcing validation gates.
- Pausing for human confirmation.
- Preventing speculative advancement.
- Summarizing progress.
- Resuming interrupted workflows.

AUTOMA-AI should favor explicit workflow transitions over implicit message passing. In production settings, the system should know what step it is in, what artifact is being produced, what validation is required, and when human confirmation is needed.

This does not prevent decentralized agent collaboration. It means production workflows should have clear control points so errors do not silently propagate across the system.

## 10. Memory, Retrieval, and Context Engineering

AUTOMA-AI should treat context as an engineered system rather than a single prompt window.

Different context types should have different roles:

| Context type | Role |
| --- | --- |
| System instructions | Define agent identity, constraints, and global behavior |
| Skill instructions | Define task-specific strategy and output contract |
| Conversation history | Preserve dialogue continuity |
| Blackboard artifacts | Store current workflow state and intermediate outputs |
| Retrieval results | Ground reasoning in external knowledge |
| Memory store | Preserve session or long-term context |
| Tool schemas | Describe available actions |

The framework should help decide what belongs in conversation history, what belongs in the blackboard, what should be retrieved on demand, and what should remain in durable memory.

This is especially important for long workflows where dumping everything into the prompt increases token cost, reduces clarity, and makes state harder to verify.

## 11. Checkpointing, Persistence, and Resumability

Long-running workflows should assume interruption. A user may pause for review, an application server may restart, a model call may fail, or a workflow may need to resume after external data is collected.

AUTOMA-AI should make it possible to resume from known workflow state rather than restart from conversation replay.

Checkpointing supports:

- Durable execution state.
- Pause/resume workflows.
- Human review between steps.
- Recovery from service interruption.
- More reliable deployment in cloud environments.

In-memory checkpointing is useful for development. Redis or cloud-backed checkpointing is more appropriate for deployed applications. The checkpointer interface should allow these backends to be swapped without changing the workflow logic.

## 12. Model Provider Abstraction

AUTOMA-AI supports multiple model providers because model choice should be an infrastructure decision, not an application rewrite.

Applications may need to choose model providers based on:

- Cost.
- Latency.
- Reasoning quality.
- Security requirements.
- Data governance.
- Availability.
- Cloud deployment constraints.
- Local/offline requirements.

The framework should isolate provider-specific details behind configuration and provider abstractions. This allows teams to use OpenAI, Azure OpenAI, AWS Bedrock, Google GenAI, Ollama, or other endpoints without rewriting orchestration logic.

## 13. Production Integration Boundaries

AUTOMA-AI should integrate with production applications rather than replace them.

The surrounding application remains responsible for:

- User experience.
- Authentication and authorization.
- Domain data ownership.
- Business rules.
- Deployment policy.
- Compliance requirements.
- Monitoring and operations.
- User-facing APIs.

AUTOMA-AI provides the agent execution and integration layer. It should expose clear boundaries so application teams can connect agents to their existing services, databases, user interfaces, and cloud infrastructure.

This boundary is important: AUTOMA-AI is not a complete end-to-end application platform. It is the composable infrastructure layer for building agent-enabled applications.

## 14. Maturity and Stability Principles

AUTOMA-AI is production-oriented in architecture but still maturing as an open-source package. Users should expect active development, evolving APIs, and improving documentation.

The maturity goal is not to freeze the framework too early. The goal is to stabilize the right contracts over time.

Priorities include:

1. Stabilize public interfaces for agents, tools, memory, blackboards, checkpointers, and retrievers.
2. Improve examples that show realistic integration patterns.
3. Add tests for interface contracts and core execution paths.
4. Document extension patterns for custom providers and backends.
5. Strengthen deployment guidance for cloud and enterprise environments.
6. Improve observability and debugging for long-running workflows.

Adopters should use AUTOMA-AI when its integration-first architecture is valuable, while understanding that the package and documentation are actively evolving.

## 15. Design Rules for Future Development

Future AUTOMA-AI development should follow these rules:

1. **Interface before implementation.** New infrastructure capabilities should sit behind clear contracts.
2. **Configuration before hard-coded behavior.** Users should be able to select providers and backends without editing core logic.
3. **Structured artifacts before raw text handoff.** Important workflow state should be represented explicitly.
4. **Local composition before distributed complexity.** Keep simple use cases simple.
5. **Protocol boundary when reuse or deployment independence matters.** Use A2A, MCP, or other standards when components need to be reusable across systems.
6. **Clear state transition before autonomous continuation.** Long-running workflows should know when they are allowed to proceed.
7. **Application-specific logic outside the core framework when possible.** Domain workflows should live in examples, applications, or extensions unless they generalize across use cases.
8. **Human checkpoints as first-class workflow events.** User confirmation, revision, and approval should be modeled explicitly.
9. **Observability as part of production readiness.** Agents should expose enough state and metadata for debugging, review, and evaluation.
10. **Compatibility with existing ecosystems.** AUTOMA-AI should build on standards and proven frameworks rather than duplicate them unnecessarily.

Examples:

- A DynamoDB memory store should be implemented behind the memory interface.
- A Redis checkpointer should be implemented behind the checkpointer interface.
- A PermitCE-specific workflow should live as an application or example, not as core framework behavior.
- An EnergyPlus MCP server should be integrated through MCP rather than special-cased into agent internals.
- A new model provider should be exposed through the model provider abstraction, not hard-coded into one agent class.

These rules help keep AUTOMA-AI from becoming a collection of application-specific utilities.

## 16. Roadmap Direction

Future development should strengthen AUTOMA-AI's role as production-oriented integration infrastructure.

Roadmap themes include:

- More stable public interface contracts.
- Better blackboard persistence backends.
- Cloud-native memory and checkpointing options.
- Stronger A2A agent discovery and collaboration patterns.
- More MCP examples and tool integration patterns.
- Improved workflow validation and human-in-the-loop APIs.
- Better observability, metrics, and debugging support.
- Testing harnesses for agents, tools, skills, and workflows.
- More examples showing local-to-production migration paths.

The roadmap should continue to optimize for interoperability, extensibility, state management, and production integration rather than building a closed ecosystem.

## 17. Relationship to BEM-AI and PNNL Applications

BEM-AI began as a building energy modeling multi-agent system. AUTOMA-AI is the generalized framework layer extracted from that work.

BEM-AI remains an important reference application, but AUTOMA-AI should not be limited to building energy modeling. It should support BEM, permitting, scientific workflows, engineering workflows, and other PNNL applications while keeping domain-specific logic outside the core framework when possible.

This separation matters:

- **AUTOMA-AI** is the reusable framework and integration layer.
- **BEM-AI** is a reference application and example domain workflow.
- **PermitCE and other applications** can use AUTOMA-AI as a foundation for stateful, human-in-the-loop, production-oriented agent workflows.

The framework should continue to learn from real applications, but reusable infrastructure should remain separate from domain-specific business logic.

## Summary

AUTOMA-AI should be understood as:

> Integration-first composable agent infrastructure for stateful, production-oriented workflows.

The project should continue to prioritize:

- Protocol-driven interoperability.
- Plugin-and-play interfaces.
- Shared blackboard state.
- Explicit workflow control.
- Persistent and resumable execution.
- Model and infrastructure flexibility.
- Clear production integration boundaries.

These principles should guide README messaging, documentation, examples, roadmap decisions, and future code contributions.
