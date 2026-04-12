"""
Floating overlay dot at bottom-right corner of screen.
Just a small colored dot:
  - Green: idle/ready
  - Red (pulsing): recording
  - Yellow: transcribing
  - Blue: loading
  - Gray: error
"""
import logging
import tkinter as tk
from typing import Optional

from .config import OverlayConfig
from .constants import DaemonState

logger = logging.getLogger(__name__)

DOT_COLORS = {
    DaemonState.IDLE: "#22c55e",
    DaemonState.RECORDING: "#ef4444",
    DaemonState.TRANSCRIBING: "#eab308",
    DaemonState.ERROR: "#6b7280",
}


class Overlay:
    def __init__(self, root: tk.Tk, config: OverlayConfig):
        self._root = root
        self._config = config
        self._state = DaemonState.IDLE
        self._float_win: Optional[tk.Toplevel] = None
        self._canvas: Optional[tk.Canvas] = None
        self._dot_id = None
        self._pulse_job = None
        self._size = config.dot_size

    def initialize(self):
        self._float_win = tk.Toplevel(self._root)
        self._float_win.overrideredirect(True)
        self._float_win.attributes("-topmost", True)
        self._float_win.attributes("-alpha", 0.85)

        # Position at absolute bottom-right corner
        self._root.update_idletasks()
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        pad = 10  # tiny gap from screen edge
        x = screen_w - self._size - pad
        y = screen_h - self._size - pad

        self._float_win.geometry(f"{self._size}x{self._size}+{x}+{y}")
        self._float_win.configure(bg="#010101")

        try:
            self._float_win.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass

        self._canvas = tk.Canvas(
            self._float_win, width=self._size, height=self._size,
            highlightthickness=0, bd=0, bg="#010101",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._dot_id = self._canvas.create_oval(0, 0, self._size, self._size, fill="#22c55e", outline="")

    def update_state(self, state: DaemonState, extended: bool = False):
        self._state = state
        if self._root:
            self._root.after(0, self._apply_state)

    def show_loading(self):
        if self._root:
            self._root.after(0, lambda: self._set_color("#3b82f6"))

    def _apply_state(self):
        self._stop_pulse()
        color = DOT_COLORS.get(self._state, "#6b7280")
        self._set_color(color)

        if self._state == DaemonState.RECORDING:
            self._root.after(200, self._start_pulse)

    def _set_color(self, color: str):
        if self._dot_id and self._canvas:
            self._canvas.itemconfig(self._dot_id, fill=color)

    def _start_pulse(self):
        self._do_pulse(True)

    def _do_pulse(self, bright):
        if self._state != DaemonState.RECORDING:
            return
        color = "#ef4444" if bright else "#b91c1c"
        self._set_color(color)
        self._pulse_job = self._root.after(400, self._do_pulse, not bright)

    def _stop_pulse(self):
        if self._pulse_job:
            self._root.after_cancel(self._pulse_job)
            self._pulse_job = None
