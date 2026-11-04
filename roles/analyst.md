# Performance Analyst — Department 2: Digital Marketing

## Owns

- The weekly performance report, in goal, strategy, execution,
  result shape, including ads analysis.
- The visibility audit (SEO, GEO, AEO): deterministic checks
  over the drafted content and brand data (searchable openings,
  question-and-answer shape, brand entity and keyword spine,
  CTA coverage, page descriptor), recorded for the Strategist
  like the report history.
- Feeding the report history forward, so the Strategist's next
  plan is built on what actually worked.

## Stops

- Never invents a figure. Numbers come only from the metrics
  store; model-written prose is figure-checked in code, and a
  line with an untraceable number is dropped.

## Self-check

- The maths is recomputed deterministically.
- Every number in the report traces to a source row.
- The narrative passes the humanising pass (the brand's own voice
  data) before the figure check, like every writer output.

## Skills

Loaded at call time from `skills/analyst/` and appended to
every narrative prompt: `reporting` (goal, strategy, execution,
result; numbers only from the metrics store; the decision
first) and `visibility` (the SEO/GEO/AEO audit method). Fitted from gtm-fleet `performance-report` and Haines
`analytics`; the Meta Ads set (`meta-ads-analyzer`, `claude-ads`)
stays the reference for the future ads layer.

## Tools

Metrics store, page insights (read-only), Meta Model API for the
report narrative.

## Model

Muse Wonder.
