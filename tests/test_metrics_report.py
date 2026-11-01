from pageops.metrics import compute_metrics
from pageops.report import build_report
from pageops.store import Store

ROWS = [
    {"date": "2026-10-27", "platform": "facebook", "post_id": "p1",
     "reach": "1000", "engagement": "120", "clicks": "30", "notes": ""},
    {"date": "2026-10-29", "platform": "facebook", "post_id": "p2",
     "reach": "2500", "engagement": "300", "clicks": "45", "notes": ""},
]


def test_compute_metrics_totals_and_best():
    stats = compute_metrics(ROWS)
    assert stats["totals"] == {"posts": 2, "reach": 3500, "engagement": 420, "clicks": 75}
    assert stats["best_post"]["post_id"] == "p2"


def test_report_cites_only_computed_numbers(tmp_path):
    store = Store(tmp_path)
    for row in ROWS:
        store.append_row("metrics", row)
    report = build_report(store)
    assert "3500" in report["narrative"]
    assert "420" in report["narrative"]
    assert "p2" in report["narrative"]


def test_report_with_no_metrics(tmp_path):
    report = build_report(Store(tmp_path))
    assert "No metrics recorded yet" in report["narrative"]
