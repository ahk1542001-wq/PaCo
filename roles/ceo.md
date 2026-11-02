# CEO — Control Layer

The control layer above both departments. The human owner sits
above the CEO and holds the approval gate personally.

## Owns

- The assignment: brief intake, restatement and missing-field flags.
- Routing: every handoff between roles goes through the store,
  never role to role directly.
- The gate surface: checked work is presented to the owner on the
  dashboard, as one approved content package or not at all.
- Consolidation: the final report is assembled and signed off here.

## Stops

- Cannot approve in the owner's place, ever. Approval is a human
  action with a state precondition, enforced in code.
- Creates no content and publishes nothing itself.

## Self-check

- Every stage's output is present in the store before the gate.
- The consolidated report traces to numbers in the metrics store.

## Skills

None. The CEO layer is deterministic code (the pipeline) plus the
dashboard surface.

## Tools

Pipeline, shared store, dashboard.

## Model

Routing is executed deterministically in code. The verdict the
routing acts on comes from the Brand Checker.
