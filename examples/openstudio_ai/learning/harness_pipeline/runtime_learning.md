# Runtime Learning

Runtime learning in exported Claude/Codex harnesses is candidate-only.

Allowed runtime outputs:

- candidate reusable recipes;
- candidate measures;
- session lessons;
- notes for future evals.

Runtime agents must not directly edit trusted `knowledge/`, `skills/`,
`measures/approved/`, or MCP tools.

Use `learning/candidates/` for proposed assets and validate against the schemas
in `learning/schemas/`.

