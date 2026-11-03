"""Tests for the weekly heartbeat entry point (scripts/run_cycle.py).

The heartbeat prepares a week and stops at the human gate. These
tests pin its three safety properties: no brief means no run, a
waiting gate means no new cycle, and it contains no approval,
rejection or scheduling calls.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from pageops.store import Store

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_cycle.py"
BRIEF = "Promote the chatbot offer to SME page owners this week"


def _load_cycle():
    spec = importlib.util.spec_from_file_location("run_cycle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mock_env(monkeypatch, data_dir: Path) -> None:
    monkeypatch.setenv("PAGEOPS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("PAGEOPS_BRIEF_FILE", raising=False)


def test_missing_brief_file_runs_nothing(tmp_path, monkeypatch, capsys):
    cycle = _load_cycle()
    data_dir = tmp_path / "data"
    _mock_env(monkeypatch, data_dir)

    code = cycle.main(["--brief-file", str(tmp_path / "no-brief.txt")])

    assert code != 0
    assert "missing or empty" in capsys.readouterr().err
    assert not data_dir.exists()  # no store was created, nothing ran


def test_empty_brief_file_runs_nothing(tmp_path, monkeypatch, capsys):
    cycle = _load_cycle()
    data_dir = tmp_path / "data"
    brief_file = tmp_path / "brief.txt"
    brief_file.write_text("  \n\n", encoding="utf-8")
    _mock_env(monkeypatch, data_dir)

    code = cycle.main(["--brief-file", str(brief_file)])

    assert code != 0
    assert "missing or empty" in capsys.readouterr().err
    assert not data_dir.exists()


def test_waiting_gate_starts_no_new_cycle(tmp_path, monkeypatch, capsys):
    cycle = _load_cycle()
    data_dir = tmp_path / "data"
    store = Store(data_dir)
    store.add_plan_row({"status": "awaiting_approval", "topic": "Earlier post"})
    (data_dir / "standing-brief.txt").write_text(BRIEF + "\n", encoding="utf-8")
    before = store.read_dataset("plan")
    _mock_env(monkeypatch, data_dir)

    code = cycle.main([])

    assert code == 0
    out = capsys.readouterr().out
    assert "The gate is still waiting" in out
    assert "Items awaiting approval: 1" in out
    assert Store(data_dir).read_dataset("plan") == before


def test_clean_store_runs_full_cycle_to_the_gate(tmp_path, monkeypatch, capsys):
    cycle = _load_cycle()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "standing-brief.txt").write_text(
        BRIEF + "\nA second line that is not part of the summary brief.\n",
        encoding="utf-8",
    )
    _mock_env(monkeypatch, data_dir)

    code = cycle.main([])

    assert code == 0
    out = capsys.readouterr().out
    rows = Store(data_dir).read_dataset("plan")
    content = [r for r in rows if r.get("status") != "brief_received"]
    assert len(content) == 7
    assert all(r["status"] == "awaiting_approval" for r in content)
    summary_file = data_dir / "notes" / "last_cycle.txt"
    assert summary_file.exists()
    summary = summary_file.read_text(encoding="utf-8")
    assert summary in out
    assert f"Brief: {BRIEF}" in summary
    assert "- awaiting_approval: 7" in summary
    assert "Items awaiting approval: 7" in summary


def test_cycle_source_has_no_gate_crossing_calls():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called |= {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "approve_item" not in called
    assert "reject_item" not in called
    assert "schedule_approved" not in called
