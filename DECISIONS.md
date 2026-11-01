# PageOps Agent — Decisions

One page. Produced by the M1 alignment pass (Pocock `grill-with-docs`) over the build package spec (00–02), 2026-11-02. Anything not decided here is listed under Open, never silently resolved.

## Decided

- **Product:** PageOps Agent, a digital marketing and content creation agent. One web dashboard is the only interface. No Telegram, no chat UI, no native Facebook/Instagram publishing APIs.
- **Demo brand:** FYF AI. Brand voice seed comes from the 2026-10-26 FYF AI service-page plan until the owner's official brand files replace it.
- **Company shape:** CEO control layer → two departments (Content Creation & Branding; Digital Marketing) → six roles → stages. The main orchestrator is the CEO layer's execution arm. The approval gate sits on the department boundary; Department 1 output crosses into Department 2 only as the approved content package, after the owner's click.
- **Models:** Muse Wonder is the main LLM (plan, drafts, report narrative, verdicts). Dev iterations may run on Muse Spark via `PAGEOPS_MAIN_MODEL`; verdicts always run on Wonder. Tests always mock the model.
- **HTTP client:** plain `httpx` against the OpenAI-compatible Meta Model API, not a vendor SDK — the endpoint is OpenAI-compatible, the calls are simple chat completions, and an SDK would add a dependency without adding capability.
- **Checker:** deterministic code first (quoted evidence), model verdict second. The checker always runs on the full post text (draft + hashtags).
- **Store:** local CSV mirroring the Google Sheets schema (Brand Voice / Plan / Metrics), one-way push to Sheets. The dashboard reads the store; no separate state.
- **Scheduler gate:** `scheduler.py` refuses, in code, anything not in `approved` status. Buffer runs dry-run until a live key exists; dry-run queue IDs are labelled as such everywhere.
- **Cost policy:** usage is logged per run; flag at ~50% and ~80% of the $150 Meta credit. No paid step beyond the credit without the owner's say.
- **Gate enforcement:** every change lands as a branch + pull request; GitHub Actions runs the full test suite on each PR; branch protection on `main` requires green checks; CodeRabbit reviews each PR on two axes (standards, then spec). Merge = the change's FINAL.

## Open (not silently resolved)

- **Buffer live vs Postiz fallback:** needs the owner's Buffer account + API key (Nov 3 step). Until then, dry-run stands and is labelled as such.
- **CodeRabbit app installation:** the config file ships with the repo; if the GitHub App is not installed on the repo, the first PR will show no review — that gap gets reported, not papered over.
- **Graphic Designer role:** the owner's design session sketched one in Department 1; the pipeline has no visual-production stage today. Adding it means a new stage + minitask. Owner's call.
