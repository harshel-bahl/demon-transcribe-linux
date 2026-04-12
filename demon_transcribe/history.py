import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from .constants import HISTORY_FILE, MAX_HISTORY_ITEMS

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    text: str
    timestamp: str
    duration_sec: float
    model: str
    word_count: int


class HistoryManager:
    def __init__(self, filepath: str = HISTORY_FILE, max_items: int = MAX_HISTORY_ITEMS):
        self._filepath = filepath
        self._max_items = max_items
        self._entries: list[HistoryEntry] = []
        self._lock = threading.Lock()
        self._load()

    def add(self, text: str, duration_sec: float, model: str) -> HistoryEntry:
        entry = HistoryEntry(
            text=text,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_sec=round(duration_sec, 2),
            model=model,
            word_count=len(text.split()),
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_items:
                self._entries = self._entries[-self._max_items:]
            self._save()
        return entry

    def get_all(self) -> list[HistoryEntry]:
        with self._lock:
            return list(reversed(self._entries))  # newest first

    def get_latest(self) -> Optional[HistoryEntry]:
        with self._lock:
            return self._entries[-1] if self._entries else None

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._save()

    def total_words(self) -> int:
        with self._lock:
            return sum(e.word_count for e in self._entries)

    def total_snippets(self) -> int:
        with self._lock:
            return len(self._entries)

    def total_audio_seconds(self) -> float:
        with self._lock:
            return sum(e.duration_sec for e in self._entries)

    def _load(self):
        if not os.path.exists(self._filepath):
            return
        try:
            with open(self._filepath, "r") as f:
                data = json.load(f)
            entries_raw = data.get("entries", [])
            self._entries = [HistoryEntry(**e) for e in entries_raw]
            logger.info("Loaded %d history entries", len(self._entries))
        except Exception:
            logger.exception("Failed to load history, starting fresh")
            self._entries = []

    def _save(self):
        data = {"version": 1, "entries": [asdict(e) for e in self._entries]}
        try:
            dir_name = os.path.dirname(self._filepath) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._filepath)
        except Exception:
            logger.exception("Failed to save history")
