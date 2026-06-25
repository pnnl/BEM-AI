# OpenStudio AI Blackboard

The blackboard is the persistent workflow state store used by long-running
OpenStudio AI workflows.

The parent workflow owns all state mutations. Child skills and runtime tools
return state patches, but they do not directly rewrite shared assumptions,
phase status, or promoted artifacts.

Core operations:

- `initialize_workflow`
- `read_state`
- `apply_state_patch`
- `mark_phase_complete`
- `record_assumption`
- `record_artifact`
- `record_failure`
- `snapshot_workflow`

