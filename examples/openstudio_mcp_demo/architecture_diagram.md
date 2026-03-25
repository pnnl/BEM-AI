# OpenStudio MCP Server Diagram (Sponsor View)

This diagram shows how a user request flows through the OpenStudio MCP demo.

## 1) Big Picture

```mermaid
flowchart LR
    U[Engineer / Sponsor User] --> UI[Chat UI]
    UI --> AG[OpenStudio Agent]
    AG --> MCP[OpenStudio MCP Server]

    subgraph MCP[OpenStudio MCP Server]
      T1[Model Tools: load / clone / apply_measure / validate]
      T2[Simulation Tools: run / status / artifacts]
      T3[Results Tools: query / summarize]
      POL[Policy Files: allowlist + measure registry]
      MEAS[Measure Scripts: add_daylighting]
      JOB[Job Manager: tracks RUNNING/SUCCEEDED/FAILED]
      ART[Artifact Store: model/sql/log/report IDs]
      WS[Workspace Folders: per-job files]
      OS[OpenStudio Engine]

      T1 --> POL
      T1 --> MEAS
      T1 --> WS
      T2 --> JOB
      T2 --> OS
      T2 --> WS
      T2 --> ART
      T3 --> ART
    end

    MCP --> AG
    AG --> UI
```

## 2) Typical Sizing Workflow

```mermaid
sequenceDiagram
    participant User
    participant Agent
    participant MCP
    participant OS as OpenStudio Engine

    User->>Agent: "Run sizing on sample.osm"
    Agent->>MCP: model.load(model_uri)
    MCP-->>Agent: model_id

    Agent->>MCP: model.apply_measure(model_id, add_daylighting)
    MCP->>OS: execute_python_script add_daylighting.py
    OS-->>MCP: out.osm + logs
    MCP-->>Agent: new model_id + changes

    Agent->>MCP: sim.run(model_id)
    MCP->>OS: openstudio run -w in.osw
    MCP-->>Agent: job_id (immediate)

    loop poll
      Agent->>MCP: sim.status(job_id)
      MCP-->>Agent: RUNNING / SUCCEEDED / FAILED
    end

    Agent->>MCP: sim.artifacts(job_id)
    MCP-->>Agent: sql_id, logs_id, report_id

    Agent->>MCP: results.query(sql_id, sizing_summary)
    MCP-->>Agent: real SQL-based metrics
    Agent-->>User: sponsor-friendly summary
```

## 3) Plain-English Summary

- The **agent** is the coordinator.
- The **MCP server** is the toolbox.
- The **OpenStudio engine** does heavy simulation work.
- **Job manager** tracks progress.
- **Artifact store** keeps references to outputs.
- **Policy files** control what tools/measures are allowed.
