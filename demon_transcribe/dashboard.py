"""
Dark-themed dashboard window with system info, model picker, stats, history.
Owns the tk.Tk root; overlay creates a Toplevel on it.
"""
import logging
import os
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Callable, Optional

import pyperclip

from .constants import APP_NAME, APP_VERSION, DaemonState
from .config import AppConfig
from .history import HistoryManager
from .stats import StatsTracker
from .transcriber import Transcriber

logger = logging.getLogger(__name__)

# ── Theme colors ──
BG        = "#111111"
BG_CARD   = "#1a1a1a"
BG_FIELD  = "#222222"
BG_HOVER  = "#2a2a2a"
FG        = "#e8e8e8"
FG_DIM    = "#777777"
FG_ACCENT = "#999999"
BORDER    = "#2a2a2a"
GREEN     = "#22c55e"
RED       = "#ef4444"
YELLOW    = "#eab308"
BLUE      = "#3b82f6"
GRAY      = "#6b7280"
CYAN      = "#06b6d4"
PURPLE    = "#a855f7"

# Platform-aware font
_FONT = "DejaVu Sans" if sys.platform != "win32" else "Segoe UI"

STATE_COLORS = {
    DaemonState.IDLE: GREEN,
    DaemonState.RECORDING: RED,
    DaemonState.TRANSCRIBING: YELLOW,
    DaemonState.ERROR: GRAY,
}
STATE_LABELS = {
    DaemonState.IDLE: "Ready",
    DaemonState.RECORDING: "Recording",
    DaemonState.TRANSCRIBING: "Transcribing",
    DaemonState.ERROR: "Error",
}


def _get_hardware_info() -> dict:
    """Detect CPU, GPU, RAM info using Linux system tools."""
    info = {"cpu": "Unknown", "gpu": "Unknown", "ram_gb": 0}

    # RAM via os.sysconf
    try:
        mem_bytes = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        info["ram_gb"] = round(mem_bytes / (1024 ** 3))
    except Exception:
        pass

    # CPU
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        info["cpu"] = platform.processor() or "Unknown"

    # GPU
    try:
        out = subprocess.check_output(["lspci"], text=True, timeout=5)
        for line in out.split("\n"):
            if "VGA" in line or "3D" in line or "Display" in line:
                # Format: "c4:00.0 Display controller: AMD/ATI Device 150e"
                info["gpu"] = line.split(":", 2)[-1].strip() if ":" in line else line.strip()
                break
    except Exception:
        pass

    return info


class Dashboard:
    def __init__(
        self,
        on_quit: Callable,
        on_restart: Callable,
        on_model_change: Callable,
        on_paste_snippet: Callable[[str], None],
        on_llm_toggle: Callable[[bool], None],
        on_gpu_toggle: Callable[[bool], None],
        history: HistoryManager,
        stats: StatsTracker,
        config: AppConfig,
    ):
        self._on_quit = on_quit
        self._on_restart = on_restart
        self._on_model_change = on_model_change
        self._on_paste_snippet = on_paste_snippet
        self._on_llm_toggle = on_llm_toggle
        self._on_gpu_toggle = on_gpu_toggle
        self._history = history
        self._stats = stats
        self._config = config
        self._root: Optional[tk.Tk] = None
        self._state = DaemonState.IDLE
        self._hw_info = {}

    def get_root(self) -> tk.Tk:
        return self._root

    def run(self, setup_callback: Callable):
        self._root = tk.Tk()
        self._root.title(f"{APP_NAME} v{APP_VERSION}")
        w, h = self._config.dashboard.width, self._config.dashboard.height
        self._root.geometry(f"{w}x{h}")
        self._root.minsize(w, h)
        self._root.configure(bg=BG)
        self._root.protocol("WM_DELETE_WINDOW", self._minimize)

        # Icon — try .png first (Linux), fall back to .ico (Windows)
        try:
            icon_dir = os.path.dirname(os.path.dirname(__file__))
            png_path = os.path.join(icon_dir, "demon_transcribe.png")
            ico_path = os.path.join(icon_dir, "demon_transcribe.ico")
            if os.path.exists(png_path):
                img = tk.PhotoImage(file=png_path)
                self._root.iconphoto(False, img)
            elif os.path.exists(ico_path) and sys.platform == "win32":
                self._root.iconbitmap(ico_path)
        except Exception:
            pass

        self._apply_theme()
        self._hw_info = _get_hardware_info()
        self._build_ui()

        if not self._config.dashboard.show_on_startup:
            self._root.iconify()


        import threading
        threading.Thread(target=setup_callback, daemon=True).start()

        self._root.mainloop()

    # ── Theme ──

    def _apply_theme(self):
        style = ttk.Style(self._root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, fieldbackground=BG_FIELD, bordercolor=BORDER)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=BG, foreground=FG_DIM, borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=BG, foreground=FG_DIM, font=(_FONT, 8))
        style.configure("TButton", background=BG_FIELD, foreground=FG, padding=(8, 3), font=(_FONT, 8))
        style.map("TButton", background=[("active", BG_HOVER)])
        style.configure("Accent.TButton", background=BLUE, foreground="white", font=(_FONT, 8, "bold"))
        style.map("Accent.TButton", background=[("active", "#2563eb")])
        style.configure("Danger.TButton", background="#7f1d1d", foreground="#fca5a5", font=(_FONT, 8))
        style.map("Danger.TButton", background=[("active", RED)])
        style.configure("TCombobox", fieldbackground=BG_FIELD, foreground=FG, selectbackground=BG_HOVER)
        style.configure("Dim.TLabel", foreground=FG_DIM, font=(_FONT, 8))
        style.configure("Accent.TLabel", foreground=FG_ACCENT, font=(_FONT, 9))
        style.configure("Header.TLabel", font=(_FONT, 14, "bold"))
        style.configure("Version.TLabel", foreground=FG_DIM, font=(_FONT, 8))
        style.configure("StatNum.TLabel", font=(_FONT, 18, "bold"), foreground=FG)
        style.configure("StatLabel.TLabel", foreground=FG_DIM, font=(_FONT, 8))
        style.configure("SysKey.TLabel", foreground=FG_DIM, font=(_FONT, 8))
        style.configure("SysVal.TLabel", foreground=FG, font=(_FONT, 8))
        style.configure("Speed.TLabel", foreground=CYAN, font=(_FONT, 9, "bold"))
        style.configure("LLM.TLabel", foreground=FG_DIM, font=(_FONT, 8))
        style.configure("CardFrame.TFrame", background=BG_CARD)

    # ── UI Construction ──

    def _build_ui(self):
        container = ttk.Frame(self._root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self._build_header(container)
        self._build_pipeline_section(container)
        self._build_model_section(container)
        self._build_stats_section(container)
        self._build_history_section(container)
        self._build_footer(container)

    def _build_header(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, 8))

        left = ttk.Frame(frame)
        left.pack(side=tk.LEFT)
        ttk.Label(left, text=APP_NAME, style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(left, text=f"v{APP_VERSION}", style="Version.TLabel").pack(side=tk.LEFT, padx=(6, 0), pady=(4, 0))

        right = ttk.Frame(frame)
        right.pack(side=tk.RIGHT)
        self._status_canvas = tk.Canvas(right, width=10, height=10, bg=BG, highlightthickness=0)
        self._status_canvas.pack(side=tk.LEFT, padx=(0, 5))
        self._status_dot = self._status_canvas.create_oval(1, 1, 9, 9, fill=GREEN, outline="")
        self._status_label = ttk.Label(right, text="Starting...", style="Accent.TLabel")
        self._status_label.pack(side=tk.LEFT)

    def _build_pipeline_section(self, parent):
        """System info: hardware + pipeline status in a compact card."""
        card = tk.Frame(parent, bg=BG_CARD, padx=10, pady=8)
        card.pack(fill=tk.X, pady=(0, 6))

        # Row 0: CPU + RAM
        r0 = tk.Frame(card, bg=BG_CARD)
        r0.pack(fill=tk.X, pady=(0, 2))

        cpu = self._hw_info.get("cpu", "Unknown")
        if len(cpu) > 42:
            cpu = cpu[:42] + "..."
        ram = self._hw_info.get("ram_gb", "?")
        tk.Label(r0, text=f"{cpu}  |  {ram} GB RAM", fg=FG_DIM, bg=BG_CARD, font=(_FONT, 8)).pack(side=tk.LEFT)

        # Row 1: GPU + Device badge + GPU toggle
        r1 = tk.Frame(card, bg=BG_CARD)
        r1.pack(fill=tk.X, pady=(0, 2))

        gpu = self._hw_info.get("gpu", "Unknown")
        if len(gpu) > 35:
            gpu = gpu[:35] + "..."
        self._gpu_label = tk.Label(r1, text=gpu, fg=FG, bg=BG_CARD, font=(_FONT, 8, "bold"))
        self._gpu_label.pack(side=tk.LEFT)

        self._device_badge = tk.Label(r1, text="  detecting...  ", fg=FG_DIM, bg="#1f1f1f",
                                       font=(_FONT, 7), padx=4, pady=1)
        self._device_badge.pack(side=tk.LEFT, padx=(8, 0))

        # GPU on/off toggle
        self._gpu_is_on = (self._config.model.device != "cpu")
        self._gpu_toggle_btn = ttk.Button(r1, text="GPU ON" if self._gpu_is_on else "GPU OFF",
                                           width=7, command=self._toggle_gpu)
        self._gpu_toggle_btn.pack(side=tk.RIGHT)

        # Row 2: Speed + LLM
        r2 = tk.Frame(card, bg=BG_CARD)
        r2.pack(fill=tk.X)

        self._speed_label = tk.Label(r2, text="Speed: --", fg=CYAN, bg=BG_CARD, font=(_FONT, 8, "bold"))
        self._speed_label.pack(side=tk.LEFT)

        # LLM toggle
        llm_frame = tk.Frame(r2, bg=BG_CARD)
        llm_frame.pack(side=tk.RIGHT)
        self._llm_status = tk.Label(llm_frame, text="checking...", fg=FG_DIM, bg=BG_CARD, font=(_FONT, 8))
        self._llm_status.pack(side=tk.LEFT)
        self._llm_toggle_btn = ttk.Button(llm_frame, text="ON", width=3, command=self._toggle_llm)
        self._llm_toggle_btn.pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(llm_frame, text="LLM", fg=FG_DIM, bg=BG_CARD, font=(_FONT, 7)).pack(side=tk.LEFT, padx=(4, 0))

        self._llm_is_on = self._config.llm.enabled
        self._update_llm_toggle_btn()

    def _build_model_section(self, parent):
        lf = ttk.LabelFrame(parent, text=" Model ", padding=6)
        lf.pack(fill=tk.X, pady=(0, 6))

        self._all_models = Transcriber.list_available_models()

        # Active model with status badge
        active_row = ttk.Frame(lf)
        active_row.pack(fill=tk.X, pady=(0, 4))
        self._active_model_label = tk.Label(
            active_row, text=self._config.model.name, fg=FG, bg=BG,
            font=(_FONT, 11, "bold"), anchor=tk.W
        )
        self._active_model_label.pack(side=tk.LEFT)
        self._model_status_badge = tk.Label(
            active_row, text=" LOADING ", fg="#fde047", bg="#422006",
            font=(_FONT, 7, "bold"), padx=3, pady=1
        )
        self._model_status_badge.pack(side=tk.LEFT, padx=(6, 0))
        self._active_model_detail = tk.Label(active_row, text="", fg=FG_DIM, bg=BG, font=(_FONT, 8))
        self._active_model_detail.pack(side=tk.LEFT, padx=(6, 0))
        self._update_active_model_detail()

        # Model picker row
        pick_row = ttk.Frame(lf)
        pick_row.pack(fill=tk.X, pady=(0, 4))

        display_names = self._build_model_display_names()
        self._model_var = tk.StringVar(value="")
        self._model_combo = ttk.Combobox(pick_row, textvariable=self._model_var,
                                          values=display_names, state="readonly", width=34)
        self._model_combo.pack(side=tk.LEFT, padx=(0, 6))
        self._model_combo.bind("<<ComboboxSelected>>", lambda e: self._update_swap_info())

        ttk.Button(pick_row, text="Apply", command=self._apply_model, style="Accent.TButton", width=7).pack(side=tk.LEFT)

        self._model_info = ttk.Label(pick_row, text="", style="Dim.TLabel")
        self._model_info.pack(side=tk.LEFT, padx=(8, 0))

        # Delete button row
        del_row = ttk.Frame(lf)
        del_row.pack(fill=tk.X)
        ttk.Button(del_row, text="Delete Selected Model", command=self._delete_model,
                   style="Danger.TButton").pack(side=tk.LEFT)
        self._disk_usage_label = ttk.Label(del_row, text="", style="Dim.TLabel")
        self._disk_usage_label.pack(side=tk.RIGHT)
        self._update_disk_usage()

    def _build_model_display_names(self) -> list[str]:
        """Build display names showing download status."""
        names = []
        for m in self._all_models:
            downloaded = self._is_model_downloaded(m)
            status = "\u2713" if downloaded else "\u2193"  # checkmark or download arrow
            names.append(f"{status} {m['name']}  [{m['backend']}]")
        return names

    def _is_model_downloaded(self, model: dict) -> bool:
        """Check if a model's files exist on disk."""
        if model["backend"] == "whisper-cpp":
            from .whisper_cpp import GGML_MODELS, MODELS_DIR
            info = GGML_MODELS.get(model["name"])
            if info:
                return os.path.exists(os.path.join(MODELS_DIR, info["file"]))
            return False
        else:
            # faster-whisper models are cached in HuggingFace cache
            try:
                from huggingface_hub import try_to_load_from_cache
                _MODEL_ID_MAP = {"distil-large-v3": "Systran/faster-distil-whisper-large-v3"}
                model_id = _MODEL_ID_MAP.get(model["name"], model["name"])
                result = try_to_load_from_cache(f"Systran/faster-whisper-{model_id}", "config.json")
                return result is not None
            except Exception:
                return False

    def _build_stats_section(self, parent):
        lf = ttk.LabelFrame(parent, text=" Stats ", padding=6)
        lf.pack(fill=tk.X, pady=(0, 6))

        row = ttk.Frame(lf)
        row.pack(fill=tk.X)

        self._stat_words = self._make_stat(row, "0", "words")
        self._stat_snippets = self._make_stat(row, "0", "snippets")
        self._stat_duration = self._make_stat(row, "0m 0s", "session")

        self._alltime_label = ttk.Label(lf, text="", style="Dim.TLabel")
        self._alltime_label.pack(anchor=tk.W, pady=(4, 0))

        self.refresh_stats()

    def _make_stat(self, parent, value, label):
        frame = ttk.Frame(parent)
        frame.pack(side=tk.LEFT, expand=True)
        num = ttk.Label(frame, text=value, style="StatNum.TLabel")
        num.pack()
        ttk.Label(frame, text=label, style="StatLabel.TLabel").pack()
        return num

    def _build_history_section(self, parent):
        lf = ttk.LabelFrame(parent, text=" History ", padding=4)
        lf.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        btn_row = ttk.Frame(lf)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn_row, text="Copy Last", command=self._copy_last, width=9).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Clear", command=self._clear_history, width=6).pack(side=tk.LEFT)

        scroll_frame = ttk.Frame(lf)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        self._history_canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient=tk.VERTICAL, command=self._history_canvas.yview)
        self._history_inner = tk.Frame(self._history_canvas, bg=BG)

        self._history_inner.bind("<Configure>",
            lambda e: self._history_canvas.configure(scrollregion=self._history_canvas.bbox("all")))
        self._history_canvas.create_window((0, 0), window=self._history_inner, anchor=tk.NW)
        self._history_canvas.configure(yscrollcommand=scrollbar.set)

        self._history_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Linux uses Button-4/Button-5 for scroll, Windows uses MouseWheel
        if sys.platform == "win32":
            self._history_canvas.bind("<Enter>",
                lambda e: self._history_canvas.bind_all("<MouseWheel>", self._on_mousewheel))
            self._history_canvas.bind("<Leave>",
                lambda e: self._history_canvas.unbind_all("<MouseWheel>"))
        else:
            self._history_canvas.bind("<Enter>", self._bind_linux_scroll)
            self._history_canvas.bind("<Leave>", self._unbind_linux_scroll)

        self.refresh_history()

    def _bind_linux_scroll(self, event):
        self._history_canvas.bind_all("<Button-4>", self._on_scroll_up)
        self._history_canvas.bind_all("<Button-5>", self._on_scroll_down)

    def _unbind_linux_scroll(self, event):
        self._history_canvas.unbind_all("<Button-4>")
        self._history_canvas.unbind_all("<Button-5>")

    def _on_scroll_up(self, event):
        self._history_canvas.yview_scroll(-3, "units")

    def _on_scroll_down(self, event):
        self._history_canvas.yview_scroll(3, "units")

    def _build_footer(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, 0))

        ttk.Label(frame, text="Ctrl+Shift+Space: hold or double-tap", style="Dim.TLabel").pack(side=tk.LEFT)
        ttk.Button(frame, text="Quit", command=self._on_quit, width=5).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(frame, text="Restart", command=self._on_restart, width=7).pack(side=tk.RIGHT, padx=(4, 0))

    # ── Public update methods (thread-safe via root.after) ──

    def update_state(self, state: DaemonState):
        self._state = state
        if self._root:
            self._root.after(0, self._apply_state, state)

    def show_loading(self, msg: str = "Loading model..."):
        if self._root:
            self._root.after(0, self._apply_loading, msg)

    def refresh_stats(self):
        if self._root:
            self._root.after(0, self._do_refresh_stats)

    def refresh_history(self):
        if self._root:
            self._root.after(0, self._do_refresh_history)

    def batch_post_transcription(self, speed, elapsed):
        """Batch all post-transcription dashboard updates into a single Tk callback."""
        if self._root:
            self._root.after(0, lambda: self._do_batch_update(speed, elapsed))

    def _do_batch_update(self, speed, elapsed):
        self._do_update_speed(speed, elapsed)
        self._do_refresh_stats()
        self._do_refresh_history()

    def update_system_info(self, device: str, compute: str, llm_enabled: bool,
                          llm_connected: bool = False, llm_model: str = None):
        if self._root:
            self._root.after(0, self._do_update_system_info, device, compute,
                             llm_enabled, llm_connected, llm_model)

    def set_model_loaded(self, loaded: bool):
        """Update the model status badge to show LOADED or LOADING."""
        if self._root:
            self._root.after(0, self._do_set_model_loaded, loaded)

    def _do_set_model_loaded(self, loaded: bool):
        if loaded:
            self._model_status_badge.config(text=" LOADED ", fg="#86efac", bg="#14532d")
        else:
            self._model_status_badge.config(text=" LOADING ", fg="#fde047", bg="#422006")

    def update_speed(self, speed_ratio: float, elapsed: float):
        if self._root:
            self._root.after(0, self._do_update_speed, speed_ratio, elapsed)

    # ── Internal UI updates ──

    def _apply_state(self, state):
        color = STATE_COLORS.get(state, GRAY)
        label = STATE_LABELS.get(state, "Unknown")
        self._status_canvas.itemconfig(self._status_dot, fill=color)
        self._status_label.config(text=label)

    def _apply_loading(self, msg):
        self._status_canvas.itemconfig(self._status_dot, fill=BLUE)
        self._status_label.config(text=msg)

    def _do_update_system_info(self, device, compute, llm_enabled, llm_connected=False, llm_model=None):
        # Device badge
        device_text = f" {device.upper()} ({compute}) "
        if device in ("vulkan", "cuda"):
            self._device_badge.config(text=device_text, fg="#86efac", bg="#14532d")
        else:
            self._device_badge.config(text=device_text, fg=FG_DIM, bg="#1f1f1f")

        # LLM status
        if not llm_enabled:
            self._llm_status.config(text="off", fg=FG_DIM)
        elif llm_connected and llm_model:
            name = llm_model if len(llm_model) <= 24 else llm_model[:24] + "..."
            self._llm_status.config(text=name, fg=GREEN)
        elif llm_connected:
            self._llm_status.config(text="no model", fg=YELLOW)
        else:
            self._llm_status.config(text="disconnected", fg=RED)

    def _do_update_speed(self, speed_ratio, elapsed):
        if speed_ratio >= 5:
            color = GREEN
        elif speed_ratio >= 1:
            color = CYAN
        else:
            color = YELLOW
        self._speed_label.config(text=f"Speed: {speed_ratio:.1f}x realtime ({elapsed:.1f}s)", fg=color)

    def _do_refresh_stats(self):
        ss = self._stats.get_session_stats()
        at = self._stats.get_all_time_stats()
        self._stat_words.config(text=f"{ss['words']:,}")
        self._stat_snippets.config(text=str(ss['snippets']))
        self._stat_duration.config(text=ss['duration'])
        self._alltime_label.config(
            text=f"All-time: {at['words']:,} words across {at['snippets']} snippets"
        )

    def _do_refresh_history(self):
        for w in self._history_inner.winfo_children():
            w.destroy()

        entries = self._history.get_all()
        if not entries:
            tk.Label(self._history_inner, text="No transcriptions yet", fg=FG_DIM, bg=BG,
                     font=(_FONT, 9)).pack(pady=20)
            return

        for entry in entries:
            self._make_history_row(entry)

    def _make_history_row(self, entry):
        frame = tk.Frame(self._history_inner, bg=BG_CARD, padx=8, pady=5, cursor="hand2")
        frame.pack(fill=tk.X, pady=1)

        try:
            dt = datetime.fromisoformat(entry.timestamp)
            ts_text = f"{dt.strftime('%b %d')}, {dt.strftime('%I:%M %p').lstrip('0')}"
        except Exception:
            ts_text = entry.timestamp[:16]

        header = tk.Frame(frame, bg=BG_CARD)
        header.pack(fill=tk.X)
        tk.Label(header, text=ts_text, fg=FG_DIM, bg=BG_CARD, font=(_FONT, 7)).pack(side=tk.LEFT)
        tk.Label(header, text=f"{entry.word_count}w | {entry.duration_sec:.0f}s | {entry.model}",
                 fg=FG_DIM, bg=BG_CARD, font=(_FONT, 7)).pack(side=tk.RIGHT)

        preview = entry.text[:100] + ("..." if len(entry.text) > 100 else "")
        tk.Label(frame, text=preview, fg=FG, bg=BG_CARD, font=(_FONT, 9),
                 anchor=tk.W, wraplength=940).pack(fill=tk.X, pady=(1, 0))

        text = entry.text
        for widget in [frame] + frame.winfo_children():
            widget.bind("<Button-1>", lambda e, t=text, f=frame: self._copy_entry(t, f))
            if hasattr(widget, 'winfo_children'):
                for child in widget.winfo_children():
                    child.bind("<Button-1>", lambda e, t=text, f=frame: self._copy_entry(t, f))

        def on_enter(e, f=frame):
            f.configure(bg=BG_HOVER)
            for c in f.winfo_children():
                c.configure(bg=BG_HOVER)
                for cc in getattr(c, 'winfo_children', lambda: [])():
                    cc.configure(bg=BG_HOVER)

        def on_leave(e, f=frame):
            f.configure(bg=BG_CARD)
            for c in f.winfo_children():
                c.configure(bg=BG_CARD)
                for cc in getattr(c, 'winfo_children', lambda: [])():
                    cc.configure(bg=BG_CARD)

        frame.bind("<Enter>", on_enter)
        frame.bind("<Leave>", on_leave)

    def _copy_entry(self, text, frame):
        pyperclip.copy(text)
        frame.configure(bg="#1a3a1a")
        self._root.after(250, lambda: frame.configure(bg=BG_CARD))

    def _copy_last(self):
        entry = self._history.get_latest()
        if entry:
            pyperclip.copy(entry.text)

    def _clear_history(self):
        if messagebox.askyesno("Clear History", "Delete all transcription history?", parent=self._root):
            self._history.clear()
            self.refresh_history()

    # ── GPU toggle ──

    def _toggle_gpu(self):
        self._gpu_is_on = not self._gpu_is_on
        if self._gpu_is_on:
            self._gpu_toggle_btn.config(text="GPU ON")
        else:
            self._gpu_toggle_btn.config(text="GPU OFF")
            self._device_badge.config(text=" CPU (forced) ", fg=FG_DIM, bg="#1f1f1f")
        self._on_gpu_toggle(self._gpu_is_on)

    # ── LLM toggle ──

    def _toggle_llm(self):
        self._llm_is_on = not self._llm_is_on
        self._update_llm_toggle_btn()
        self._on_llm_toggle(self._llm_is_on)

    def _update_llm_toggle_btn(self):
        if self._llm_is_on:
            self._llm_toggle_btn.config(text="ON")
        else:
            self._llm_toggle_btn.config(text="OFF")
            self._llm_status.config(text="off", fg=FG_DIM)

    # ── Model management ──

    def _get_selected_model(self) -> Optional[dict]:
        sel = self._model_var.get()
        for m in self._all_models:
            downloaded = self._is_model_downloaded(m)
            status = "\u2713" if downloaded else "\u2193"
            display = f"{status} {m['name']}  [{m['backend']}]"
            if display == sel:
                return m
        return None

    def _apply_model(self):
        m = self._get_selected_model()
        if m and (m["name"] != self._config.model.name or m["backend"] != self._config.model.backend):
            self._on_model_change(m["name"], m["backend"])
            self._active_model_label.config(text=m["name"])
            self._config.model.name = m["name"]
            self._config.model.backend = m["backend"]
            self._update_active_model_detail()

    def _update_active_model_detail(self):
        name = self._config.model.name
        backend = self._config.model.backend
        for m in self._all_models:
            if m["name"] == name and m["backend"] == backend:
                self._active_model_detail.config(
                    text=f"{m['backend']}  |  {m['size']}  |  {m['speed']}"
                )
                return
        self._active_model_detail.config(text=f"{backend}")

    def _update_swap_info(self):
        m = self._get_selected_model()
        if m:
            downloaded = self._is_model_downloaded(m)
            status = "downloaded" if downloaded else "will download"
            self._model_info.config(text=f"{m['size']}  |  {m['quality']}  |  {status}")
        else:
            self._model_info.config(text="")

    def _delete_model(self):
        m = self._get_selected_model()
        if not m:
            messagebox.showinfo("Delete Model", "Select a model from the dropdown first.", parent=self._root)
            return
        if not self._is_model_downloaded(m):
            messagebox.showinfo("Delete Model", f"{m['name']} is not downloaded.", parent=self._root)
            return
        if m["name"] == self._config.model.name and m["backend"] == self._config.model.backend:
            messagebox.showwarning("Delete Model", "Cannot delete the currently active model.", parent=self._root)
            return

        if m["backend"] == "whisper-cpp":
            from .whisper_cpp import GGML_MODELS, MODELS_DIR
            info = GGML_MODELS.get(m["name"])
            if info:
                path = os.path.join(MODELS_DIR, info["file"])
                size_mb = os.path.getsize(path) / (1024 * 1024) if os.path.exists(path) else 0
                if messagebox.askyesno("Delete Model",
                    f"Delete {m['name']}?\n{size_mb:.0f} MB will be freed.",
                    parent=self._root):
                    os.remove(path)
                    logger.info("Deleted model: %s (%s)", m["name"], path)
        else:
            messagebox.showinfo("Delete Model",
                "faster-whisper models are managed by HuggingFace cache.\n"
                "Clear cache with: huggingface-cli delete-cache",
                parent=self._root)

        # Refresh the combo display names
        self._model_combo.config(values=self._build_model_display_names())
        self._update_disk_usage()

    def _update_disk_usage(self):
        """Show total disk usage of downloaded models."""
        from .whisper_cpp import MODELS_DIR
        total = 0
        if os.path.isdir(MODELS_DIR):
            for f in os.listdir(MODELS_DIR):
                fp = os.path.join(MODELS_DIR, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        if total > 0:
            gb = total / (1024 ** 3)
            self._disk_usage_label.config(text=f"Models on disk: {gb:.1f} GB")
        else:
            self._disk_usage_label.config(text="")

    # ── Misc ──

    def _on_mousewheel(self, event):
        self._history_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _minimize(self):
        self._root.iconify()

    def stop(self):
        if self._root:
            self._root.after(0, self._root.destroy)
