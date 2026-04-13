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
import subprocess
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
        self._last_geom = ""
        self._rendered_size = 0

    @staticmethod
    def _get_display_scale() -> float:
        """Detect display scale factor from Xft.dpi (set by GNOME from text-scaling-factor)."""
        try:
            out = subprocess.check_output(
                ["xrdb", "-query"], text=True, stderr=subprocess.DEVNULL, timeout=2
            )
            for line in out.splitlines():
                if line.startswith("Xft.dpi:"):
                    dpi = float(line.split(":")[1].strip())
                    return dpi / 96.0
        except Exception:
            pass
        return 1.0

    def initialize(self):
        self._float_win = tk.Toplevel(self._root)
        self._float_win.overrideredirect(True)
        self._float_win.attributes("-topmost", True)
        self._float_win.attributes("-alpha", 0.85)
        self._float_win.configure(bg="#010101")

        try:
            self._float_win.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass

        self._reposition()
        self._start_reposition_loop()

    def _start_reposition_loop(self):
        """Periodically recheck screen geometry so the dot stays at the corner
        when monitors are added/removed or scaling changes."""
        self._root.after(30000, self._reposition_tick)

    def _reposition_tick(self):
        self._reposition()
        self._root.after(30000, self._reposition_tick)

    def _reposition(self):
        if not self._float_win:
            return
        self._float_win.update_idletasks()
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        scale = self._get_display_scale()
        pad = round(10 * scale)
        size = round(self._size * scale)
        x = screen_w - size - pad
        y = screen_h - size - pad

        geom = f"{size}x{size}+{x}+{y}"
        if geom == self._last_geom:
            return
        self._last_geom = geom
        self._float_win.geometry(geom)

        # Rebuild the canvas when the scaled dot size changes
        if size != self._rendered_size:
            self._rendered_size = size
            if self._canvas:
                self._canvas.destroy()
            self._canvas = tk.Canvas(
                self._float_win, width=size, height=size,
                highlightthickness=0, bd=0, bg="#010101",
            )
            self._canvas.pack(fill=tk.BOTH, expand=True)
            color = DOT_COLORS.get(self._state, "#22c55e")
            self._dot_id = self._canvas.create_oval(0, 0, size, size, fill=color, outline="")

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
