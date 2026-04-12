import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .history import HistoryManager


class StatsTracker:
    def __init__(self, history: "HistoryManager"):
        self._history = history
        self._session_start = time.monotonic()
        self._session_words = 0
        self._session_chars = 0
        self._session_snippets = 0
        self._session_audio_sec = 0.0

    def record(self, text: str, duration_sec: float):
        self._session_words += len(text.split())
        self._session_chars += len(text)
        self._session_snippets += 1
        self._session_audio_sec += duration_sec

    def get_session_stats(self) -> dict:
        elapsed = time.monotonic() - self._session_start
        return {
            "words": self._session_words,
            "chars": self._session_chars,
            "snippets": self._session_snippets,
            "audio_seconds": round(self._session_audio_sec, 1),
            "duration": self._format_duration(elapsed),
        }

    def get_all_time_stats(self) -> dict:
        return {
            "words": self._history.total_words(),
            "snippets": self._history.total_snippets(),
            "audio_seconds": round(self._history.total_audio_seconds(), 1),
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m {s}s"
