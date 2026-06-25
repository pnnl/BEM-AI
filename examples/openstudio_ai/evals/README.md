# OpenStudio AI Evals

Evals measure agent behavior, not just Python code correctness.

Initial eval categories:

- `planning/`: checks that the parent workflow selects only the needed child
  skill and maintains blackboard assumptions.
- `measures/`: checks candidate/promoted measure behavior.
- `regression/`: preserves known lessons learned and failure fixes.
- `cases/`: JSON eval case definitions.
- `datasets/`: small local inputs used by evals.

Every promoted lesson, skill, SDK note, or measure should link to at least one
eval case.

