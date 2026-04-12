"""
Global push-to-talk hotkey with two modes:
1. Hold:       Hold hotkey → record → release → transcribe
2. Double-tap: Tap hotkey twice quickly → stays listening until you tap again

Uses evdev on Linux (works on both X11 and Wayland) with pynput fallback.
"""
import logging
import os
import sys
import threading
import time
from typing import Callable, Optional, Set

logger = logging.getLogger(__name__)

DOUBLE_TAP_WINDOW = 0.4  # seconds between taps to count as double-tap
HOLD_THRESHOLD = 0.25    # seconds — shorter than this counts as a "tap"

# evdev key name mapping
_EVDEV_MODIFIER_NAMES = {
    "ctrl": {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"},
    "shift": {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"},
    "alt": {"KEY_LEFTALT", "KEY_RIGHTALT"},
    "cmd": {"KEY_LEFTMETA", "KEY_RIGHTMETA"},
}

_EVDEV_SPECIAL_NAMES = {
    "space": "KEY_SPACE",
    "enter": "KEY_ENTER",
    "tab": "KEY_TAB",
    "esc": "KEY_ESC",
    "backspace": "KEY_BACKSPACE",
    "delete": "KEY_DELETE",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
}


def _can_use_evdev() -> bool:
    """Check if evdev is available and we have permission to read input devices."""
    try:
        import evdev
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        # Check we can find at least one keyboard
        for dev in devices:
            caps = dev.capabilities(verbose=True)
            for (etype, _), events in caps.items():
                if etype == "EV_KEY":
                    return True
        return False
    except Exception:
        return False


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
        self._combination_str = combination

        # State machine
        self._pressed_keys: Set[str] = set()
        self._lock = threading.Lock()
        self._is_held = False
        self._hold_start: float = 0
        self._last_tap_time: float = 0
        self._extended_active = False
        self._hold_activated = False

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._use_evdev = _can_use_evdev()

        if self._use_evdev:
            self._target_keys = self._parse_combination_evdev(combination)
            logger.info("Hotkey configured (evdev): %s -> %s", combination, self._target_keys)
        else:
            self._target_keys = self._parse_combination_pynput(combination)
            logger.info("Hotkey configured (pynput fallback): %s -> %s", combination, self._target_keys)

    # ── evdev parsing ──

    def _parse_combination_evdev(self, combo_str: str) -> Set[str]:
        parts = [p.strip().lower() for p in combo_str.split("+")]
        target = set()
        for part in parts:
            if part in _EVDEV_MODIFIER_NAMES:
                target.add(part)
            elif part in _EVDEV_SPECIAL_NAMES:
                target.add(part)
            elif len(part) == 1:
                target.add(part)
            else:
                logger.warning("Unknown key in combination: %s", part)
                target.add(part)
        return target

    def _normalize_evdev_key(self, key_name: str) -> Optional[str]:
        """Normalize an evdev key name like KEY_LEFTCTRL to 'ctrl'."""
        for name, variants in _EVDEV_MODIFIER_NAMES.items():
            if key_name in variants:
                return name
        for name, evdev_name in _EVDEV_SPECIAL_NAMES.items():
            if key_name == evdev_name:
                return name
        # Single character keys: KEY_A -> 'a'
        if key_name.startswith("KEY_") and len(key_name) == 5:
            return key_name[4:].lower()
        return None

    # ── pynput parsing (fallback) ──

    def _parse_combination_pynput(self, combo_str: str) -> Set[str]:
        from pynput import keyboard
        _MODIFIER_MAP = {
            "ctrl": {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
            "shift": {keyboard.Key.shift_l, keyboard.Key.shift_r},
            "alt": {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
            "cmd": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
        }
        parts = [p.strip().lower() for p in combo_str.split("+")]
        target = set()
        for part in parts:
            if part in _MODIFIER_MAP:
                target.add(part)
            else:
                target.add(part)
        return target

    # ── Shared state machine ──

    def _handle_press(self, key_name: str):
        with self._lock:
            self._pressed_keys.add(key_name)

            if not self._is_held and self._target_keys.issubset(self._pressed_keys):
                self._is_held = True
                self._hold_start = time.monotonic()
                self._hold_activated = False

                if self._extended_active:
                    pass
                else:
                    self._hold_activated = True
                    threading.Thread(target=self._safe_activate, daemon=True).start()

    def _handle_release(self, key_name: str):
        with self._lock:
            if self._is_held and key_name in self._target_keys:
                self._is_held = False
                hold_duration = time.monotonic() - self._hold_start

                if self._extended_active:
                    self._extended_active = False
                    threading.Thread(target=self._safe_deactivate_extended, daemon=True).start()

                elif hold_duration < HOLD_THRESHOLD:
                    now = time.monotonic()
                    if (now - self._last_tap_time) < DOUBLE_TAP_WINDOW:
                        self._extended_active = True
                        self._last_tap_time = 0
                        threading.Thread(target=self._safe_activate_extended, daemon=True).start()
                    else:
                        threading.Thread(target=self._safe_cancel, daemon=True).start()
                        self._last_tap_time = now

                elif self._hold_activated:
                    threading.Thread(target=self._safe_deactivate, daemon=True).start()

            self._pressed_keys.discard(key_name)

    # ── evdev listener ──

    def _evdev_loop(self):
        import evdev
        import select

        devices = []
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            # EV_KEY = 1
            if 1 in caps:
                devices.append(dev)

        if not devices:
            logger.error("No keyboard devices found for evdev")
            return

        logger.info("Monitoring %d input devices via evdev", len(devices))

        while self._running:
            r, _, _ = select.select(devices, [], [], 0.5)
            for dev in r:
                try:
                    for event in dev.read():
                        if event.type != 1:  # EV_KEY
                            continue
                        key_name = evdev.ecodes.KEY.get(event.code, f"KEY_{event.code}")
                        if isinstance(key_name, list):
                            key_name = key_name[0]
                        normalized = self._normalize_evdev_key(key_name)
                        if normalized is None:
                            continue

                        if event.value == 1:  # key down
                            self._handle_press(normalized)
                        elif event.value == 0:  # key up
                            self._handle_release(normalized)
                except OSError:
                    # Device disconnected
                    continue

    # ── pynput listener (fallback) ──

    def _start_pynput(self):
        from pynput import keyboard

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
            "space": keyboard.Key.space, "enter": keyboard.Key.enter,
            "tab": keyboard.Key.tab, "esc": keyboard.Key.esc,
        }

        def normalize(key):
            if key in _KEY_TO_CANONICAL:
                return _KEY_TO_CANONICAL[key]
            for name, k in _SPECIAL_KEYS.items():
                if key == k:
                    return name
            if hasattr(key, "char") and key.char:
                return key.char.lower()
            return None

        def on_press(key):
            n = normalize(key)
            if n:
                self._handle_press(n)

        def on_release(key):
            n = normalize(key)
            if n:
                self._handle_release(n)

        self._pynput_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._pynput_listener.daemon = True
        self._pynput_listener.start()

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
        self._running = True
        if self._use_evdev:
            self._thread = threading.Thread(target=self._evdev_loop, daemon=True)
            self._thread.start()
            logger.info("Hotkey listener started (evdev)")
        else:
            self._start_pynput()
            logger.info("Hotkey listener started (pynput)")

    def stop(self):
        self._running = False
        if hasattr(self, '_pynput_listener') and self._pynput_listener:
            self._pynput_listener.stop()
            self._pynput_listener = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Hotkey listener stopped")
