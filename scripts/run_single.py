"""Produce ONE owner-asked post with PaCo and stop at the gate.

The owner asks for a specific post; this entry point runs the normal
pipeline for exactly that post (brief, draft, humanise, visual,
check, judge) and prepares nothing else. It NEVER approves, rejects
or schedules: the prepared post waits at the owner's gate like any
other.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/run_single.py --ask-file PATH
    PYTHONPATH=src .venv/bin/python scripts/run_single.py "the ask"

The data directory comes from PAGEOPS_DATA_DIR, as with run_cycle.py.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pageops.config import get_settings  # noqa: E402
from pageops.model_client import get_client, get_image_client, get_judge_client  # noqa: E402
from pageops.pipeline import process_single  # noqa: E402
from pageops.store import open_store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one owner-asked PaCo post")
    parser.add_argument("ask", nargs="?", help="The owner's ask for this one post")
    parser.add_argument("--ask-file", help="Read the ask from a file instead")
    parser.add_argument("--topic", default="", help="Plan topic (default: the ask)")
    parser.add_argument("--angle", default="", help="Plan angle line")
    parser.add_argument("--platform", default="facebook")
    parser.add_argument("--visual-style", default="", help="scene, concept, ...")
    args = parser.parse_args(argv)

    ask = ""
    if args.ask_file:
        ask = Path(args.ask_file).read_text(encoding="utf-8").strip()
    elif args.ask:
        ask = args.ask.strip()
    if not ask:
        print("No ask given; nothing was produced.")
        return 1

    settings = get_settings()
    store = open_store(settings.data_dir)
    client = get_client(settings)
    judge = get_judge_client(settings)
    image_client = get_image_client(settings)
    row = process_single(
        store,
        client,
        ask,
        topic=args.topic,
        angle=args.angle,
        platform=args.platform,
        visual_style=args.visual_style,
        judge=judge,
        image_client=image_client,
    )
    print(f"Prepared one post: id {row.get('id')} - status {row.get('status')}")
    print("It waits at the owner's approval gate; nothing was published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
