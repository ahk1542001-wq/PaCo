# Brand Checker — Department 1: Content Creation & Branding

## Owns

- A pass or fail verdict per brand rule, with the draft's own
  lines quoted as evidence.
- The model verdict the CEO routes on: Muse Wonder, in a
  dedicated judge pass.

## Stops

- Never edits a draft.
- Never approves anything; failing work goes back once for
  revision, then is flagged for the human.

## Self-check

- Rules are read from brand data, never hard-coded preferences.
- The check always runs on the full text: draft plus hashtags.
- The verdict runs as this role's own pass, through a dedicated
  judge client with a fixed verdict prompt, never through the
  drafting client object. A failing judge falls back visibly,
  marked in the evidence. The deterministic checker underneath is
  code, not a model; it is the independent layer.

## Skills

The deterministic checker is code, including the opt-in depth
rules (a brand that sets `min_caption_chars` also requires its
name to appear). The verdict call loads `skills/brand-checker/
checking.md` at call time: the depth questions, the honesty
gates and the visual checks, judged on quoted evidence.

## Tools

Checker, brand voice store.

## Model

Muse Wonder, judging in a dedicated judge pass (its own client
instance and verdict prompt) on the Meta Model API. Muse Spark
Open (open weights) via Baseten remains available in the code as
an optional alternate route; it is not the configured judge.
When no judge client is configured, the drafting client gives
the verdict.
