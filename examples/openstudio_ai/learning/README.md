# OpenStudio AI Learning Pipelines

OpenStudio AI uses two separate learning pipelines.

Developer pipeline:

- captures raw usage, failures, warnings, and corrections;
- distills them into candidate lessons or assets;
- sends candidates through review;
- validates with evals;
- promotes approved assets into trusted knowledge, skills, SDK index notes, or
  MCP measures.

Harness pipeline:

- runs inside a distributable harness;
- captures local repeated scripts, recipes, and session lessons;
- proposes candidate measures or reusable recipes;
- stores candidates locally for review;
- never directly edits trusted assets.

This separation keeps "AI learns" defensible: runtime observations can create
candidates, but trusted assets require review and validation.

