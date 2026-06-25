# Blackboard Contract

The parent workflow owns blackboard mutations.

Child skills and tools may return state patches, assumptions, artifacts, and
failure records. The parent workflow decides whether and how to apply them.

Required operations:

- initialize workflow state;
- read workflow state;
- apply state patches;
- mark phases complete;
- record assumptions;
- record artifacts;
- record failures;
- snapshot workflow state.

