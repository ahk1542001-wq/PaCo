"""End-to-end verification for PageOps Agent (M19).

Runs the full pipeline in mock mode inside a throwaway data dir and
checks the whole chain the demo depends on: brief -> plan -> draft
-> visual -> check -> approval gate -> scheduling -> report, plus
the context architecture (write log, private notes, history loop).
Then attempts one real-mode smoke call if a model client is
configured; without a key it reports SKIPPED, never a failure.

Usage: PYTHONPATH=src python3 scripts/verify_e2e.py
Exit code 0 only when every non-skipped check passes.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pageops.context import latest_analyst_summary, load_trend_notes  # noqa: E402
from pageops.model_client import MockClient, get_client  # noqa: E402
from pageops.metrics import import_metrics  # noqa: E402
from pageops.pipeline import fetch_trends, process_week, report_week  # noqa: E402
from pageops.scheduler import BufferClient, schedule_item  # noqa: E402
from pageops.store import Store  # noqa: E402

BRIEF = "Promote the chatbot offer to SME page owners this week"


def run_checks(data_dir: Path) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, evidence: str) -> None:
        results.append((name, ok, evidence))

    store = Store(data_dir)
    rows = process_week(store, MockClient(), BRIEF)
    check("pipeline rows produced", len(rows) == 7, f"{len(rows)} rows")
    check(
        "all rows awaiting approval",
        all(r["status"] == "awaiting_approval" for r in rows),
        ", ".join(sorted({r["status"] for r in rows})),
    )
    check(
        "drafts carry check evidence",
        all("[PASS] banned_phrases" in r["check_status"] for r in rows),
        "checker summaries stored on rows",
    )
    check(
        "visuals produced + stored",
        all(r.get("visual") and (data_dir / r["visual"]).exists() for r in rows),
        "; ".join(r.get("visual", "") for r in rows),
    )

    # The gate: an unapproved item must be refused by the scheduler.
    try:
        schedule_item(store, rows[0]["id"], BufferClient())
        check("scheduler refuses unapproved", False, "no error raised")
    except PermissionError as exc:
        check("scheduler refuses unapproved", True, str(exc)[:80])

    store.update_row("plan", rows[0]["id"], {"status": "approved"})
    scheduled = schedule_item(store, rows[0]["id"], BufferClient())
    check(
        "approved item schedules (dry-run)",
        scheduled.get("buffer_id", "").startswith("dry-run-"),
        f"buffer_id={scheduled.get('buffer_id')}",
    )

    fetch_trends(store=store, fetcher=lambda f=None: [{"title": "T", "link": "https://x"}])
    check("trend notes snapshotted", len(load_trend_notes(store)) == 1, "private layer")

    import_metrics(
        store,
        [{"date": "2026-08-20", "platform": "facebook", "post_id": "p1",
          "reach": "36", "engagement": "5", "clicks": "0", "notes": ""}],
    )
    report = report_week(store, client=MockClient())
    check(
        "report built from store numbers",
        "reach 36" in report["narrative"],
        report["narrative"].splitlines()[-1][:80],
    )
    check(
        "history loop closed",
        "36" in latest_analyst_summary(store),
        latest_analyst_summary(store),
    )
    log = data_dir / "writes.log"
    check(
        "write log records the run",
        log.exists() and "dataset=plan" in log.read_text(encoding="utf-8"),
        f"{len(log.read_text(encoding='utf-8').splitlines())} log lines" if log.exists() else "missing",
    )
    return results


def real_smoke() -> tuple[str, bool | None, str]:
    try:
        client = get_client()
    except Exception as exc:  # no key configured in this environment
        return ("real-mode smoke call", None, f"skipped: {exc}")
    if not hasattr(client, "chat"):
        return ("real-mode smoke call", None, "skipped: mock client configured")
    reply = client.chat(
        [{"role": "user", "content": "Reply with exactly: PageOps smoke OK"}],
        model="muse-wonder-1.0",
    )
    text = reply["choices"][0]["message"]["content"]
    return ("real-mode smoke call", "OK" in text, text[:80])


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        results = run_checks(Path(tmp))
    results.append(real_smoke())
    failed = 0
    for name, ok, evidence in results:
        mark = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            failed += 1
        print(f"[{mark}] {name} — {evidence}")
    print(f"\n{len(results) - failed - sum(1 for _, o, _ in results if o is None)}/"
          f"{len(results)} checks passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
