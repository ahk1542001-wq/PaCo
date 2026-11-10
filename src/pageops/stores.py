"""Multi-page store registry for the dashboard.

Until now one dashboard process served exactly one store, chosen
at launch. A product the owner runs for several client pages
needs one dashboard that can move between page stores: this
registry discovers the stores, holds the active one, and is the
only thing the dashboard handler talks to.

Discovery: directories under the launch store's parent (the repo
root in production) whose name matches the data-* convention and
that actually contain store datasets (brand_voice.csv + plan.csv,
or a paco.db). The launch store is always first and always
included, even when its own name does not match the convention.

The active selection is persisted server-side in a small state
file next to the stores (.paco-dashboard-state.json). Server-side
was chosen over a cookie: the owner reaches the same dashboard
from desktop and phone, and a cookie would let the two browsers
disagree about which page is live; the state file also survives
browser restarts and is directly testable. It is only written
in multi-store mode (when a data-* store exists beside the
launch store), so single-store use stays exactly as before.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import threading
from pathlib import Path

from .store import Store, SqliteStore

STATE_FILE = ".paco-dashboard-state.json"


def _is_store_dir(path: Path) -> bool:
    return (path / "paco.db").exists() or (
        (path / "brand_voice.csv").exists() and (path / "plan.csv").exists()
    )


def _read_brand_name(path: Path) -> str:
    """A store dir's brand_name without opening (or mutating) it."""
    try:
        db = path / "paco.db"
        if db.exists():
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT data FROM store_rows WHERE dataset = 'brand_voice'"
                ).fetchall()
            finally:
                conn.close()
            for (raw,) in rows:
                row = json.loads(raw)
                if row.get("key") == "brand_name":
                    return str(row.get("value") or "")
            return ""
        with open(path / "brand_voice.csv", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("key") == "brand_name":
                    return str(row.get("value") or "")
    except (OSError, sqlite3.Error, json.JSONDecodeError, csv.Error):
        return ""
    return ""


def _open_dir(path: Path) -> Store:
    """Open a discovered store on the backend its content uses."""
    if (path / "paco.db").exists():
        return SqliteStore(path)
    return Store(path)


class StoreRegistry:
    """The page stores one dashboard process can serve."""

    def __init__(self, launch_store: Store):
        self._launch = launch_store
        self._launch_name = launch_store.data_dir.name
        self.root = launch_store.data_dir.parent
        self._cache: dict[str, Store] = {self._launch_name: launch_store}
        self._lock = threading.Lock()
        self._multi = self._launch_name.startswith("data-") or any(
            name != self._launch_name for name in self._discovered()
        )
        self._active = self._launch_name
        if self._multi:
            saved = self._read_state()
            if saved and saved in self.discover():
                self._active = saved

    # -- discovery -------------------------------------------------
    def _discovered(self) -> list[str]:
        try:
            children = sorted(self.root.iterdir())
        except OSError:
            return []
        return [
            child.name
            for child in children
            if child.is_dir()
            and child.name.startswith("data-")
            and _is_store_dir(child)
        ]

    def discover(self) -> list[str]:
        """Store dir names: the launch store first, then the rest."""
        found = self._discovered()
        return [self._launch_name] + [n for n in found if n != self._launch_name]

    def pages(self) -> list[dict]:
        """Switcher entries: dir name, display label, active flag."""
        out = []
        for name in self.discover():
            cached = self._cache.get(name)
            if cached is not None:
                label = cached.get_brand_voice().get("brand_name", "")
            else:
                label = _read_brand_name(self.root / name)
            out.append(
                {
                    "name": name,
                    "label": label or name,
                    "active": name == self._active,
                }
            )
        return out

    # -- the active store -------------------------------------------
    def active(self) -> Store:
        name = self._active
        if name not in self._cache:
            self._cache[name] = _open_dir(self.root / name)
        return self._cache[name]

    def active_name(self) -> str:
        return self._active

    def switch(self, name: str) -> Store:
        with self._lock:
            if name not in self.discover():
                raise ValueError(f"Unknown page store: {name}")
            self._active = name
            self._write_state()
            return self.active()

    def create_page(self, name: str) -> Store:
        """Seed a fresh store for a new page and switch to it."""
        display = (name or "").strip()
        slug = re.sub(r"[^a-z0-9]+", "-", display.lower()).strip("-")
        if not slug:
            raise ValueError("A page name needs at least one letter or digit")
        dirname = f"data-{slug}"
        target = self.root / dirname
        with self._lock:
            if target.exists():
                raise ValueError(f"A page store already exists: {dirname}")
            store = Store(target, blank=True)
            store.set_brand_value("brand_name", display)
            self._cache[dirname] = store
            self._active = dirname
            self._multi = True
            self._write_state()
            return store

    # -- persisted selection -----------------------------------------
    def _state_path(self) -> Path:
        return self.root / STATE_FILE

    def _read_state(self) -> str:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
            return str(data.get("active") or "")
        except (OSError, json.JSONDecodeError, AttributeError):
            return ""

    def _write_state(self) -> None:
        if not self._multi:
            return
        try:
            self._state_path().write_text(
                json.dumps({"active": self._active}), encoding="utf-8"
            )
        except OSError:
            pass
