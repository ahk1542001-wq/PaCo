"""CSV-backed data store for PageOps Agent.

Mirrors the Google Sheets schema we will sync to later: three datasets,
one CSV per dataset, in the data/ directory.

  brand_voice : key/value rows describing the brand (services, audience,
                tone, rules, required hashtags)
  plan        : one row per planned post or received brief
  metrics     : one row per published post's performance snapshot
"""

from __future__ import annotations

import csv
from pathlib import Path

DATASETS: dict[str, list[str]] = {
    "brand_voice": ["key", "value"],
    "plan": [
        "id", "date", "platform", "topic", "angle", "format", "status", "brief",
        "draft", "check_status", "buffer_id",
    ],
    "metrics": ["date", "platform", "post_id", "reach", "engagement", "clicks", "notes"],
}

# Seed brand voice for the demo brand, FYF AI: an AI-automation services
# page for Myanmar and Thai SME owners.
BRAND_VOICE_SEED: dict[str, str] = {
    "brand_name": "FYF AI",
    "services": (
        "Page/WhatsApp chatbot from $150; CRM & Lead Follow-Up Pack from $200; "
        "E-Commerce Pack from $200; Content Pipeline from $150; Monthly Care"
    ),
    "audience": "Myanmar and Thai SME owners who sell through social media pages",
    "tone": "Professional and friendly, plain language, no hype",
    "rules": (
        "Every post needs a clear CTA; "
        "No income-guarantee or get-rich claims; "
        "No real person's name anywhere"
    ),
    "required_hashtags": "#FYFAI; #AIAutomation; #SME",
}


class Store:
    """Tiny CSV store. One instance points at one data directory."""

    def __init__(self, data_dir: Path | str | None = None):
        if data_dir is None:
            from .config import DEFAULT_DATA_DIR

            data_dir = DEFAULT_DATA_DIR
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def _path(self, dataset: str) -> Path:
        if dataset not in DATASETS:
            raise KeyError(f"Unknown dataset: {dataset}")
        return self.data_dir / f"{dataset}.csv"

    def _ensure_files(self) -> None:
        for name, fields in DATASETS.items():
            path = self._path(name)
            if not path.exists():
                with path.open("w", newline="", encoding="utf-8") as fh:
                    csv.DictWriter(fh, fieldnames=fields).writeheader()
        # Seed the brand voice once, only if it is still empty.
        if not self.read_dataset("brand_voice"):
            for key, value in BRAND_VOICE_SEED.items():
                self.append_row("brand_voice", {"key": key, "value": value})

    def read_dataset(self, dataset: str) -> list[dict[str, str]]:
        with self._path(dataset).open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def write_dataset(self, dataset: str, rows: list[dict[str, str]]) -> None:
        fields = DATASETS[dataset]
        with self._path(dataset).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({f: row.get(f, "") for f in fields})

    def append_row(self, dataset: str, row: dict[str, str]) -> dict[str, str]:
        fields = DATASETS[dataset]
        clean = {f: str(row.get(f, "")) for f in fields}
        with self._path(dataset).open("a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=fields).writerow(clean)
        return clean

    def update_row(self, dataset: str, row_id: str, updates: dict[str, str]) -> dict[str, str]:
        """Update one row by id and persist the whole dataset."""
        rows = self.read_dataset(dataset)
        for row in rows:
            if row.get("id") == str(row_id):
                row.update({k: str(v) for k, v in updates.items()})
                self.write_dataset(dataset, rows)
                return row
        raise KeyError(f"No row with id {row_id} in {dataset}")

    # -- Convenience helpers -------------------------------------------------

    def get_brand_voice(self) -> dict:
        """Brand voice as a structured dict (lists split on ';')."""
        raw = {row["key"]: row["value"] for row in self.read_dataset("brand_voice")}
        return {
            "brand_name": raw.get("brand_name", ""),
            "services": [s.strip() for s in raw.get("services", "").split(";") if s.strip()],
            "audience": raw.get("audience", ""),
            "tone": raw.get("tone", ""),
            "rules": [r.strip() for r in raw.get("rules", "").split(";") if r.strip()],
            "required_hashtags": [
                h.strip() for h in raw.get("required_hashtags", "").split(";") if h.strip()
            ],
        }

    def add_plan_row(self, row: dict[str, str]) -> dict[str, str]:
        """Append a plan row, assigning a simple incrementing id if absent."""
        if not row.get("id"):
            existing = self.read_dataset("plan")
            row = {**row, "id": str(len(existing) + 1)}
        return self.append_row("plan", row)
