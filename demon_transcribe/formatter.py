"""
LLM-based post-processor for dictated text.
Calls a local LM Studio (or any OpenAI-compatible) API to format raw transcription
with context awareness — punctuation, commands, code formatting, etc.
Falls back gracefully to raw text if the LLM is unavailable.
"""
import json
import logging
import subprocess
import time
import urllib.request
import urllib.error

from .config import LLMConfig

logger = logging.getLogger(__name__)


def _get_active_window_title() -> str:
    """Get the title of the currently focused window via xdotool (Linux/X11)."""
    try:
        hwnd = subprocess.check_output(
            ["xdotool", "getactivewindow"], text=True, timeout=2
        ).strip()
        title = subprocess.check_output(
            ["xdotool", "getwindowname", hwnd], text=True, timeout=2
        ).strip()
        return title
    except Exception:
        return ""


class LLMFormatter:
    def __init__(self, config: LLMConfig):
        self._config = config
        self._available = None  # None = unknown, True/False after first call

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def check_connection(self) -> dict:
        """Check if LM Studio is running and what model is loaded.
        Returns {"connected": bool, "model": str or None}."""
        if not self._config.enabled:
            return {"connected": False, "model": None}

        # Derive base URL from the chat completions URL
        base = self._config.api_url.rsplit("/chat/completions", 1)[0]
        models_url = base + "/models"

        try:
            req = urllib.request.Request(models_url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            models = result.get("data", [])
            if models:
                model_id = models[0].get("id", "unknown")
                self._available = True
                return {"connected": True, "model": model_id}
            return {"connected": True, "model": None}
        except Exception:
            self._available = False
            return {"connected": False, "model": None}

    def format(self, raw_text: str) -> str:
        """Format raw transcription via LLM. Returns raw_text on any failure."""
        if not self._config.enabled or not raw_text.strip():
            return raw_text

        active_window = _get_active_window_title()
        user_msg = f"[Active app: {active_window}]\n{raw_text}" if active_window else raw_text

        body = {
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.0,
            "max_tokens": len(raw_text) * 3,  # generous but bounded
            "stream": False,
        }
        if self._config.model:
            body["model"] = self._config.model

        timeout_sec = self._config.timeout_ms / 1000.0

        try:
            t0 = time.perf_counter()
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                self._config.api_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            formatted = result["choices"][0]["message"]["content"].strip()
            elapsed = time.perf_counter() - t0

            if not formatted:
                logger.warning("LLM returned empty text, using raw")
                return raw_text

            self._available = True
            logger.info("LLM formatted in %.0fms: %r -> %r", elapsed * 1000, raw_text[:60], formatted[:60])
            return formatted

        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            if self._available is not False:
                logger.info("LLM not available (LM Studio not running?), using raw transcription")
                self._available = False
            return raw_text
        except Exception:
            logger.exception("LLM formatting failed, using raw transcription")
            return raw_text
