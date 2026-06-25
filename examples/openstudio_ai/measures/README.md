# OpenStudio AI Measures

Measures are deterministic automation artifacts that can be exposed through MCP.

Folders:

- `approved/`: reviewed and validated measures safe for MCP publication.
- `candidates/`: generated or proposed measures that still require review.
- `templates/`: scaffolds used by the learning pipeline to draft measures.

Runtime learning may write candidates. Only the developer learning pipeline can
promote a candidate into `approved/`.

