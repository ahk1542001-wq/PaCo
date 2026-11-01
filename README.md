# PageOps Agent

**PageOps Agent is a digital marketing and content creation agent.** It
runs a social-media business page's weekly content
operation end to end — brief, trend research, content plan, on-brand
drafts with rule checks, human approval, scheduling, performance
report — from a single web dashboard. A human approves every post
before anything can be scheduled. The demo brand is **FYF AI**, an
AI-automation services page for Myanmar and Thai SME owners.

Built during the **Meta Global AI Developer Hackathon (November
2026)** on the Meta Model API: **Muse Wonder** is the main LLM (plan,
drafts, verdicts), with Muse Spark available for light utility calls.
An optional open-weights route serves **Muse Spark Open** through
Baseten (`BASETEN_API_KEY`), so the same pipeline can run on Meta's
open weights when wanted.

## Pipeline

1. **Brief** — a short form on the dashboard (goal, offer, dates).
2. **Trend research** — curated RSS/news feeds plus the brand's own
   past performance; every trend item keeps its source link.
3. **Content plan** — a 7-day plan written against the brand-voice
   profile, shown as cards on a kanban board.
4. **Drafts with brand-rule checks** — every draft is checked by a
   deterministic rule checker (banned phrases, CTA present, platform
   length caps, required hashtags). Each verdict quotes the draft's
   own lines as evidence; nothing rests on the model's word alone.
   A failing draft is revised once, then flagged for the human.
5. **Approval** — Approve / Reject buttons on the board. The
   scheduling layer itself refuses anything that is not approved;
   that gate is proven by an automated test.
6. **Scheduling** — approved posts go to the Buffer queue (dry-run
   mode until the live key is wired); queue IDs show on the cards.
7. **Performance report** — metrics maths in code, and a report in
   goal, strategy, execution, result shape that cites only numbers
   present in the metrics store.

## Architecture

```
src/pageops/
  config.py        environment settings (MODEL_MODE defaults to "mock")
  model_client.py  MetaModelClient (api.meta.ai, usage-logged) + MockClient
  store.py         CSV store mirroring the Google Sheets schema:
                   brand_voice / plan / metrics
  checker.py       deterministic brand-rule checker, pure code, no model
  rss.py           feedparser-based trend fetcher (feeds in data/feeds.txt)
  pipeline.py      brief -> plan -> draft -> check (revise once, then flag)
  dashboard.py     the web dashboard: brief form, kanban board, approval
                   actions, metrics + report panels
  scheduler.py     approval gate + Buffer scheduling (dry-run capable)
  metrics.py       deterministic performance maths (code, never the model)
  report.py        goal/strategy/execution/result report from real metrics
  sheets_sync.py   one-way push of the store to the Google Sheets mirror
scripts/
  smoke_test.py    one minimal Meta Model API call; run before real work
data/
  feeds.txt        RSS feed list (5 feeds)
  *.csv            datasets (brand voice ships seeded with FYF AI)
tests/             pytest suite (32 tests)
```

State lives in CSV files with the same schema as the Google Sheets
tabs (Brand Voice / Plan / Metrics); `sheets_sync` pushes the store
to Sheets so both views agree.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # MODEL_API_KEY for meta mode; BUFFER_API_KEY later
./run_dashboard.sh     # http://127.0.0.1:8765
```

Launchers set `PYTHONPATH=src` and unset `NO_PROXY`/`no_proxy` (on
some VMs those values crash httpx URL parsing).

## Mock mode and the smoke test

With `MODEL_MODE=mock` (the default) the model client returns canned
structured plans, drafts and verdicts, so the full pipeline and the
test suite run offline with no key and no spend.

Before any real-model work, run the smoke test once:

```bash
PYTHONPATH=src .venv/bin/python scripts/smoke_test.py
```

With `MODEL_MODE=meta` and a `MODEL_API_KEY` from dev.meta.ai it makes
one minimal Muse Wonder call and prints the reply and token usage.
Every real call is counted in `data/usage_log.jsonl`.

## Tests

```bash
.venv/bin/python -m pytest -q
```
