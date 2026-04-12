"""
Global push-to-talk hotkey with two modes:
1. Hold:       Hold hotkey → record → release → transcribe
2. Double-tap: Tap hotkey twice quickly → stays listening until you tap again
"""
import logging
import threading
import time
from typing import Callable, Optional, Set

from pynput import keyboard

logger = logging.getLogger(__name__)

_MODIFIER_MAP = {
    "ctrl": {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "shift": {keyboard.Key.shift_l, keyboard.Key.shift_r},
    "alt": {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "cmd": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
}

_KEY_TO_CANONICAL = {}
for name, keys in _MODIFIER_MAP.items():
    for k in keys:
        _KEY_TO_CANONICAL[k] = name

_SPECIAL_KEYS = {
    "space": keyboard.Key.space,
    "enter": keyboard.Key.enter,
    "tab": keyboard.Key.tab,
    "esc": keyboard.Key.esc,
    "backspace": keyboard.Key.backspace,
    "delete": keyboard.Key.delete,
    "up": keyboard.Key.up,
    "down": keyboard.Key.down,
    "left": keyboard.Key.left,
    "right": keyboard.Key.right,
}

DOUBLE_TAP_WINDOW = 0.4  # seconds between taps to count as double-tap
HOLD_THRESHOLD = 0.25    # seconds — shorter than this counts as a "tap"


class PushToTalkHotkey:
    def __init__(
        self,
        combination: str,
        on_activate: Callable[[], None],
        on_deactivate: Callable[[], None],
        on_activate_extended: Callable[[], None],
        on_deactivate_extended: Callable[[], None],
        on_cancel: Callable[[], None] = None,
    ):
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._on_activate_extended = on_activate_extended
        self._on_deactivate_extended = on_deactivate_extended
        self._on_cancel = on_cancel

        self._target_keys = self._parse_combination(combination)
        self._pressed_keys: Set[str] = set()
        self._lock = threading.Lock()
        self._listener: Optional[keyboard.Listener] = None

        # State machine
        self._is_held = False           # hotkey is physically held down right now
        self._hold_start: float = 0     # when the current hold began
        self._last_tap_time: float = 0  # when the last short tap ended
        self._extended_active = False   # currently in extended listening mode
        self._hold_activated = False    # did we fire on_activate for this hold?

        logger.info("Hotkey configured: %s -> %s", combination, self._target_keys)

    def _parse_combination(self, combo_str: str) -> Set[str]:
        parts = [p.strip().lower() for p in combo_str.split("+")]
        target = set()
        for part in parts:
            if part in _MODIFIER_MAP:
                target.add(part)
            elif part in _SPECIAL_KEYS:
                target.add(part)
            elif len(part) == 1:
                target.add(part)
            else:
                logger.warning("Unknown key in combination: %s", part)
                target.add(part)
        return target

    def _normalize_key(self, key) -> Optional[str]:
        if key in _KEY_TO_CANONICAL:
            return _KEY_TO_CANONICAL[key]
        for name, k in _SPECIAL_KEYS.items():
            if key == k:
                return name
        if hasattr(key, "char") and key.char is not None:
            return key.char.lower()
        if hasattr(key, "vk") and key.vk is not None:
            char = chr(key.vk).lower() if 32 <= key.vk <= 126 else None
            if char:
                return char
        return None

    # ── Keyboard events ──

    def _on_press(self, key):
        normalized = self._normalize_key(key)
        if normalized is None:
            return

        with self._lock:
            self._pressed_keys.add(normalized)

            if not self._is_held and self._target_keys.issubset(self._pressed_keys):
                self._is_held = True
                self._hold_start = time.monotonic()
                self._hold_activated = False

                if self._extended_active:
                    # Already in extended mode — this tap will end it (on release)
                    pass
                else:
                    # Start recording immediately so no audio is lost.
                    # If this turns out to be a short tap, we'll discard in on_release.
                    self._hold_activated = True
                    threading.Thread(target=self._safe_activate, daemon=True).start()

    def _on_release(self, key):
        normalized = self._normalize_key(key)
        if normalized is None:
            return

        with self._lock:
            if self._is_held and normalized in self._target_keys:
                self._is_held = False
                hold_duration = time.monotonic() - self._hold_start

                if self._extended_active:
                    # Tap to end extended mode
                    self._extended_active = False
                    threading.Thread(target=self._safe_deactivate_extended, daemon=True).start()

                elif hold_duration < HOLD_THRESHOLD:
                    # Short tap — check for double-tap before deciding what to do
                    now = time.monotonic()
                    if (now - self._last_tap_time) < DOUBLE_TAP_WINDOW:
                        # Double tap! Recording is already running from the second
                        # tap's on_press — just transition to extended mode.
                        # Do NOT cancel — let it keep recording.
                        self._extended_active = True
                        self._last_tap_time = 0
                        # The first tap already started+cancelled a recording,
                        # the second tap started a new one via on_press.
                        # We just need to tell main.py we're in extended mode now.
                        threading.Thread(target=self._safe_activate_extended, daemon=True).start()
                    else:
                        # Single short tap — cancel the recording we started
                        threading.Thread(target=self._safe_cancel, daemon=True).start()
                        self._last_tap_time = now

                elif self._hold_activated:
                    # Normal hold-to-talk release
                    threading.Thread(target=self._safe_deactivate, daemon=True).start()

            self._pressed_keys.discard(normalized)

    # ── Safe callback wrappers ──

    def _safe_activate(self):
        try:
            self._on_activate()
        except Exception:
            logger.exception("Error in activate callback")

    def _safe_deactivate(self):
        try:
            self._on_deactivate()
        except Exception:
            logger.exception("Error in deactivate callback")

    def _safe_activate_extended(self):
        try:
            self._on_activate_extended()
        except Exception:
            logger.exception("Error in activate_extended callback")

    def _safe_deactivate_extended(self):
        try:
            self._on_deactivate_extended()
        except Exception:
            logger.exception("Error in deactivate_extended callback")

    def _safe_cancel(self):
        try:
            if self._on_cancel:
                self._on_cancel()
        except Exception:
            logger.exception("Error in cancel callback")

    # ── Lifecycle ──

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Hotkey listener started")

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("Hotkey listener stopped")
