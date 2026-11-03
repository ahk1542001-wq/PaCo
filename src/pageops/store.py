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
        "id", "date", "platform", "topic", "angle", "format", "status", "brief", "brief_check",
        "draft", "check_status", "visual", "reject_reason", "post_id", "buffer_id", "character",
        "video", "visual_style",
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
    "banned_phrases": (
        "guaranteed income; guarantee income; get rich; get-rich; "
        "100% profit; make money fast; risk-free income"
    ),
    "cta_markers": (
        "message us; send us a message; dm us; contact us; get started; "
        "book a; book your; learn more; sign up; call us; chat with us"
    ),
    "character_name": "PaCo",
    "character_image": "assets/paco-character.png",
    "character_rules": (
        "PaCo appears as a circular badge composited from the reference "
        "image only; never redrawn or restyled; used on announcement "
        "and engagement posts."
    ),
    "character_sheet": "assets/paco-character-sheet.png",
    # Brand foundation values (brand-foundation-fyf-ai.md, assembled
    # 2026-11-03 from the designer tokens, the service page plan and
    # the case study baseline). Recorded as data so the brand record
    # lives outside code; the owner's supplied brand files replace
    # them in one swap when they land.
    "brand_colors": (
        "Primary #123B8F; Accent #F5B301; Background #F7F5F0; Ink #14213D"
    ),
    "brand_fonts": (
        "Padauk, a single font family for all text (Bold, then Regular); "
        "wordmark 64 px; headline 72 px stepping down to a 28 px minimum; "
        "angle subline 44 px; footer line 40 px; the Pillow default bitmap "
        "font only if Padauk is missing"
    ),
    "logo_usage": (
        "Text wordmark only: the words FYF AI in white Padauk on the "
        "primary #123B8F top band; no logo files or artwork exist; "
        "artwork rules (clear space, minimum size, approved colourways) "
        "are to confirm with the supplied brand files"
    ),
    "template_sizes": (
        "poster 1080x1350; thumb 1080x1080; banner 1640x924; "
        "carousel slide 1080x1080; video frame 1080x1920"
    ),
    "proof_baseline": (
        "FYF AI page starting baseline (Facebook, 90 days to "
        "31 October 2026): 15 followers; 970 views; 131 unique viewers; "
        "44 engagements including clicks; the three posts in the "
        "metrics store total 170 views, 13 engagements and 1 click; "
        "a starting baseline only, not a results claim"
    ),
}

# Brand keys added after the first seed shipped. A store whose
# brand_voice predates any of them gets ONLY the missing keys
# backfilled from the seed: without them, get_brand_voice returns ""
# for the key forever (a character-marked draft would hard-fail
# against an empty reference). Owner-edited values are never
# overwritten: a key that is present, even blank, is left as it is.
BACKFILL_KEYS: tuple[str, ...] = (
    "character_name",
    "character_image",
    "character_rules",
    "character_sheet",
    "brand_colors",
    "brand_fonts",
    "logo_usage",
    "template_sizes",
    "proof_baseline",
)


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
            else:
                # Migrate an older file whose header predates a new
                # field: rewrite it on the current schema, keeping rows.
                with path.open(newline="", encoding="utf-8") as fh:
                    header = next(csv.reader(fh), [])
                if header != fields:
                    self.write_dataset(name, self.read_dataset(name))
        # Seed the brand voice once, only if it is still empty.
        if not self.read_dataset("brand_voice"):
            for key, value in BRAND_VOICE_SEED.items():
                self.append_row("brand_voice", {"key": key, "value": value})
        # Backfill ONLY the keys in BACKFILL_KEYS on a store whose
        # brand_voice predates them (see the note on BACKFILL_KEYS).
        existing_keys = {row["key"] for row in self.read_dataset("brand_voice")}
        for key in BACKFILL_KEYS:
            if key not in existing_keys:
                self.append_row(
                    "brand_voice", {"key": key, "value": BRAND_VOICE_SEED[key]}
                )

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

    def _log_write(self, dataset: str, row_id: str, fields: list[str]) -> None:
        """Append one line to the store write log (the audit trail)."""
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{stamp} dataset={dataset} id={row_id} fields={','.join(fields)}\n"
        with (self.data_dir / "writes.log").open("a", encoding="utf-8") as fh:
            fh.write(line)

    def append_row(self, dataset: str, row: dict[str, str]) -> dict[str, str]:
        fields = DATASETS[dataset]
        clean = {f: str(row.get(f, "")) for f in fields}
        with self._path(dataset).open("a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=fields).writerow(clean)
        self._log_write(dataset, clean.get("id", "-"), [f for f in fields if clean.get(f)])
        return clean

    def update_row(self, dataset: str, row_id: str, updates: dict[str, str]) -> dict[str, str]:
        """Update one row by id and persist the whole dataset."""
        rows = self.read_dataset(dataset)
        for row in rows:
            if row.get("id") == str(row_id):
                row.update({k: str(v) for k, v in updates.items()})
                self.write_dataset(dataset, rows)
                self._log_write(dataset, str(row_id), sorted(updates))
                return row
        raise KeyError(f"No row with id {row_id} in {dataset}")

    # -- Convenience helpers -------------------------------------------------

    def set_brand_value(self, key: str, value: str) -> None:
        """Set one brand voice key (the brand-assets layer is data)."""
        rows = self.read_dataset("brand_voice")
        for row in rows:
            if row.get("key") == key:
                row["value"] = value
                self.write_dataset("brand_voice", rows)
                return
        rows.append({"key": key, "value": value})
        self.write_dataset("brand_voice", rows)

    def get_brand_voice(self) -> dict:
        """Brand voice as a structured dict (lists split on ';').

        The rule lists (banned_phrases, cta_markers) are included
        only when the stored value is non-blank: a store that
        predates those keys gets the checker's fallback defaults,
        so protection can never be blanked away by accident.
        """
        raw = {row["key"]: row["value"] for row in self.read_dataset("brand_voice")}
        voice = {
            "brand_name": raw.get("brand_name", ""),
            "services": [s.strip() for s in raw.get("services", "").split(";") if s.strip()],
            "audience": raw.get("audience", ""),
            "tone": raw.get("tone", ""),
            "rules": [r.strip() for r in raw.get("rules", "").split(";") if r.strip()],
            "required_hashtags": [
                h.strip() for h in raw.get("required_hashtags", "").split(";") if h.strip()
            ],
            "character_name": raw.get("character_name", ""),
            "character_image": raw.get("character_image", ""),
            "character_rules": raw.get("character_rules", ""),
            "character_sheet": raw.get("character_sheet", ""),
            "brand_colors": raw.get("brand_colors", ""),
            "brand_fonts": raw.get("brand_fonts", ""),
            "logo_usage": raw.get("logo_usage", ""),
            "template_sizes": raw.get("template_sizes", ""),
            "proof_baseline": raw.get("proof_baseline", ""),
        }
        for key in ("banned_phrases", "cta_markers"):
            if raw.get(key, "").strip():
                voice[key] = [p.strip() for p in raw[key].split(";") if p.strip()]
        return voice

    def add_plan_row(self, row: dict[str, str]) -> dict[str, str]:
        """Append a plan row, assigning a simple incrementing id if absent."""
        if not row.get("id"):
            existing = self.read_dataset("plan")
            row = {**row, "id": str(len(existing) + 1)}
        return self.append_row("plan", row)
