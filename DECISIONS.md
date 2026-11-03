# PageOps Agent — Decisions

One page. Produced by the M1 alignment pass (Pocock `grill-with-docs`) over the build package spec (00–02), 2026-11-02. Anything not decided here is listed under Open, never silently resolved.

## Decided

- **Product:** PageOps Agent, a digital marketing and content creation agent. One web dashboard is the only interface. No Telegram, no chat UI, no native Facebook/Instagram publishing APIs.
- **Demo brand:** FYF AI. Brand voice seed comes from the 2026-10-26 FYF AI service-page plan until the owner's official brand files replace it.
- **Company shape:** CEO control layer → two departments (Content Creation & Branding; Digital Marketing) → six roles → stages. The main orchestrator is the CEO layer's execution arm. The approval gate sits on the department boundary; Department 1 output crosses into Department 2 only as the approved content package, after the owner's click.
- **Models:** Muse Wonder is the main LLM (plan, drafts, report narrative) on the Meta Model API. **Verdicts and routing decisions run on Muse Spark Open via Baseten: a second model judging, never its own output** (owner's designation, 2026-11-02; see the plan's Model map). Dev iterations may run on Muse Spark via `PAGEOPS_MAIN_MODEL`. Tests always mock the model.
- **HTTP client:** plain `httpx` against the OpenAI-compatible Meta Model API, not a vendor SDK — the endpoint is OpenAI-compatible, the calls are simple chat completions, and an SDK would add a dependency without adding capability.
- **Checker:** deterministic code first (quoted evidence), model verdict second. The checker always runs on the full post text (draft + hashtags).
- **Store:** local CSV mirroring the Google Sheets schema (Brand Voice / Plan / Metrics), one-way push to Sheets. The dashboard reads the store; no separate state.
- **Scheduler gate:** `scheduler.py` refuses, in code, anything not in `approved` status. Buffer runs dry-run until a live key exists; dry-run queue IDs are labelled as such everywhere.
- **Cost policy:** usage is logged per run; flag at ~50% and ~80% of the $150 Meta credit. No paid step beyond the credit without the owner's say.
- **Gate enforcement:** every change lands as a branch + pull request; GitHub Actions runs the full test suite on each PR; branch protection on `main` requires green checks. The lane then runs its own two-axis review (standards, then spec, the Matt Pocock way, fresh-context reviewers) on the change, fixes every finding on the spot, retests, and merges. **A step is FINAL only after green checks + a passed two-axis review + merge.** CodeRabbit is configured as an additional automated reviewer once its app is installed.
- **Judge change (2026-11-03):** the owner moved every big-decision role to Muse Wonder, Brand Checker verdicts included. Verdicts now run on Muse Wonder in a dedicated judge pass (its own client instance and verdict prompt) on the Meta Model API. This supersedes the 2026-11-02 designation in the Models entry above, which named Muse Spark Open via Baseten as the judge. The deterministic checker in code remains the independent, model-free layer under the verdict. Muse Spark Open via Baseten stays in the code as an optional alternate route; it is not the configured judge.
- **Concept mode (2026-11-03):** still visuals gain directed, generated-scene production in two planner-chosen styles (the plan's `visual_style` field). Scene style: a rich generated scene with the full headline treatment composited in code. Concept style: one visual metaphor per post, a sectioned conceptual-ad prompt whose Constraints include an explicit No exceptions clause in the metaphor's own terms (every instance of the metaphor element handled, none outside the protective action, the protected subject fully inside the safe zone); the manifest's concept record carries that line, and an image that would contradict the one-line claim is the wrong image (regenerate or fall back). Muse Wonder art-directs (concept line + prompt), Muse Image generates one plate, the Designer composites all typography in code, and the brand templates remain the recorded fallback for any direction or generation failure. The owner's design bar: professional output in every role, not flat templates.

## Open (not silently resolved)

- **Buffer live vs Postiz fallback:** needs the owner's Buffer account + API key (Nov 3 step). Until then, dry-run stands and is labelled as such.
- **CodeRabbit app installation:** the config file ships with the repo; if the GitHub App is not installed on the repo, the first PR will show no review — that gap gets reported, not papered over.
- **Graphic Designer role:** the owner's design session sketched one in Department 1; the pipeline has no visual-production stage today. Adding it means a new stage + minitask. Owner's call.

<!-- gate proof: throwaway PR for M1, 2026-11-02 -->

## Video format vocabulary (2026-11-03)

The Concept acceptance run exposed a vocabulary trap: Muse Wonder labelled two plan rows "video" instead of "Short video", and every video trigger matched the exact phrase "short video", so those rows silently received poster visuals only. The planner's format names are not constrained, so the triggers now match any format containing "video" (pipeline review tail, the Meta draft instruction, and the mock client). A regression test pins a plain "video" row producing a video.

## Scene scrim legibility (2026-11-03)

The same acceptance run showed the scene treatment's subline running off its scrim onto the bare photograph, unreadable over busy areas: the scrim was a fixed 55 percent fade while the text block it carries can extend past it. The treatment now measures the headline and angle first and sizes the scrim to the text block, with a slower fade, so every line it carries stays on the brand colour. A regression test renders a long topic and angle over a white plate and checks the scrim is still visibly present deep in the text zone.
