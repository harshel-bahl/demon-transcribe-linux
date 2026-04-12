import logging
import subprocess
import time

import pyperclip
from pynput.keyboard import Controller, Key

from .config import InjectionConfig

logger = logging.getLogger(__name__)

_keyboard = Controller()


class TextInjector:
    def __init__(self, config: InjectionConfig):
        self._config = config

    def inject(self, text: str) -> bool:
        if not text:
            logger.warning("Empty text, nothing to inject")
            return False

        method = self._config.method
        if method == "clipboard":
            return self._inject_clipboard(text)
        elif method == "keystroke":
            return self._inject_keystroke(text)
        elif method == "auto":
            if self._inject_clipboard(text):
                return True
            logger.info("Clipboard injection failed, falling back to keystroke")
            return self._inject_keystroke(text)
        else:
            logger.error("Unknown injection method: %s", method)
            return False

    def _inject_clipboard(self, text: str) -> bool:
        try:
            original = None
            if self._config.restore_clipboard:
                try:
                    original = pyperclip.paste()
                except Exception:
                    original = None

            pyperclip.copy(text)
            time.sleep(self._config.paste_delay_ms / 1000.0)

            _keyboard.press(Key.ctrl)
            _keyboard.press("v")
            _keyboard.release("v")
            _keyboard.release(Key.ctrl)

            # Give the target app time to process the paste
            time.sleep(0.15)

            if self._config.restore_clipboard and original is not None:
                time.sleep(0.05)
                pyperclip.copy(original)

            logger.info("Injected %d chars via clipboard", len(text))
            return True
        except Exception:
            logger.exception("Clipboard injection failed")
            return False

    def _inject_keystroke(self, text: str) -> bool:
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--", text],
                timeout=10,
            )
            logger.info("Injected %d chars via xdotool keystroke", len(text))
            return True
        except FileNotFoundError:
            logger.error("xdotool not found — install with: sudo apt install xdotool")
            return False
        except Exception:
            logger.exception("Keystroke injection failed")
            return False
