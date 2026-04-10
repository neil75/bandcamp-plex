"""Persistent record of Bandcamp items we've already synced."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.downloaded: set[str] = set()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self.downloaded = set(data.get("downloaded", []))
                log.info("Loaded state with %d known item(s)", len(self.downloaded))
            except Exception:
                log.exception("Failed to read state %s; starting fresh", path)

    def has(self, key: str) -> bool:
        return key in self.downloaded

    def mark(self, key: str) -> None:
        if key in self.downloaded:
            return
        self.downloaded.add(key)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"downloaded": sorted(self.downloaded)}, indent=2))
        tmp.replace(self.path)
