import logging
import os
import subprocess
import time

import pyperclip

from .config import InjectionConfig

logger = logging.getLogger(__name__)

_IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"


def _simulate_paste():
    """Simulate Ctrl+V using the best available method."""
    if _IS_WAYLAND:
        # ydotool works at kernel level — works on GNOME Wayland
        try:
            subprocess.run(
                ["ydotool", "key", "--delay", "150", "ctrl+v"],
                timeout=5,
            )
            return
        except FileNotFoundError:
            logger.warning("ydotool not found — text is on clipboard, paste manually with Ctrl+V")
    else:
        # X11 — xdotool
        try:
            subprocess.run(["xdotool", "key", "ctrl+v"], timeout=5)
            return
        except FileNotFoundError:
            pass
        # pynput fallback for X11
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.ctrl)
        kb.press("v")
        kb.release("v")
        kb.release(Key.ctrl)


class TextInjector:
    def __init__(self, config: InjectionConfig):
        self._config = config

    def inject(self, text: str) -> bool:
        if not text:
            logger.warning("Empty text, nothing to inject")
            return False
        return self._inject_clipboard(text)

    def _inject_clipboard(self, text: str) -> bool:
        try:
            pyperclip.copy(text)
            time.sleep(0.2)

            _simulate_paste()

            time.sleep(0.3)

            logger.info("Injected %d chars via clipboard", len(text))
            return True
        except Exception:
            logger.exception("Clipboard injection failed")
            return False
