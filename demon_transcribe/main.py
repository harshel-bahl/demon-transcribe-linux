import gc
import logging
import os
import sys
import threading

import numpy as np

from .audio import AudioRecorder, play_beep
from .config import AppConfig, load_config, save_config
from .constants import DaemonState
from .dashboard import Dashboard
from .formatter import LLMFormatter
from .history import HistoryManager
from .hotkey import PushToTalkHotkey
from .injector import TextInjector
from .overlay import Overlay
from .stats import StatsTracker
from .transcriber import Transcriber

logger = logging.getLogger(__name__)


class DemonTranscribe:
    def __init__(self, config_path: str = "config.yaml"):
        self._config_path = config_path
        self._config: AppConfig | None = None
        self._recorder: AudioRecorder | None = None
        self._transcriber: Transcriber | None = None
        self._injector: TextInjector | None = None
        self._hotkey: PushToTalkHotkey | None = None
        self._overlay: Overlay | None = None
        self._dashboard: Dashboard | None = None
        self._history: HistoryManager | None = None
        self._stats: StatsTracker | None = None
        self._formatter: LLMFormatter | None = None
        self._state = DaemonState.IDLE
        self._state_lock = threading.Lock()

    def run(self):
        self._setup_logging()
        logger.info("Starting demon-transcribe")

        self._config = load_config(self._config_path)
        logger.info("Config loaded from %s", self._config_path)

        # History & stats (need config path for history file location)
        history_path = os.path.join(os.path.dirname(self._config_path) or ".", "history.json")
        self._history = HistoryManager(filepath=history_path)
        self._stats = StatsTracker(self._history)

        # Dashboard owns the Tk root and mainloop
        self._dashboard = Dashboard(
            on_quit=self._quit,
            on_restart=self._restart,
            on_model_change=self._on_model_change,
            on_paste_snippet=self._on_paste_snippet,
            on_llm_toggle=self._on_llm_toggle,
            on_gpu_toggle=self._on_gpu_toggle,
            history=self._history,
            stats=self._stats,
            config=self._config,
        )
        # This blocks on the main thread
        self._dashboard.run(setup_callback=self._initialize)

    def _setup_logging(self):
        if not logging.root.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                handlers=[logging.StreamHandler(sys.stdout)],
            )
        # Quiet noisy loggers
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("faster_whisper").setLevel(logging.WARNING)

    def _initialize(self):
        try:
            root = self._dashboard.get_root()

            # Create overlay on the main thread
            self._overlay = Overlay(root, self._config.overlay)
            root.after(0, self._overlay.initialize)

            self._dashboard.show_loading("Loading model...")
            self._dashboard.set_model_loaded(False)
            self._overlay.show_loading()

            self._transcriber = Transcriber(self._config.model, self._config.transcription)
            self._transcriber.load_model()

            self._recorder = AudioRecorder(self._config.audio)
            self._injector = TextInjector(self._config.injection)
            self._formatter = LLMFormatter(self._config.llm)
            if self._formatter.enabled:
                logger.info("LLM formatting enabled (%s)", self._config.llm.api_url)

            self._hotkey = PushToTalkHotkey(
                combination=self._config.hotkey.combination,
                on_activate=self._on_hotkey_press,
                on_deactivate=self._on_hotkey_release,
                on_activate_extended=self._on_extended_start,
                on_deactivate_extended=self._on_extended_stop,
                on_cancel=self._on_hotkey_cancel,
            )
            self._hotkey.start()

            self._set_state(DaemonState.IDLE)
            self._dashboard.set_model_loaded(True)

            # Check LM Studio connection
            llm_info = self._formatter.check_connection() if self._formatter else {}
            self._dashboard.update_system_info(
                self._transcriber.device_used,
                self._transcriber.compute_used,
                self._formatter.enabled if self._formatter else False,
                llm_connected=llm_info.get("connected", False),
                llm_model=llm_info.get("model"),
            )
            self._dashboard.refresh_stats()
            self._dashboard.refresh_history()
            logger.info("demon-transcribe ready! Hold %s to record.", self._config.hotkey.combination)
        except Exception:
            logger.exception("Initialization failed")
            self._set_state(DaemonState.ERROR)

    def _set_state(self, state: DaemonState, extended: bool = False):
        with self._state_lock:
            self._state = state
        if self._overlay:
            self._overlay.update_state(state, extended=extended)
        if self._dashboard:
            self._dashboard.update_state(state)

    # ── Normal hold-to-talk ──

    def _on_hotkey_press(self):
        with self._state_lock:
            if self._state != DaemonState.IDLE:
                return

        self._set_state(DaemonState.RECORDING)
        if self._config:
            play_beep(self._config.feedback, start=True)

        try:
            self._recorder.start_recording()
        except Exception:
            logger.exception("Failed to start recording")
            self._set_state(DaemonState.IDLE)

    def _on_hotkey_release(self):
        with self._state_lock:
            if self._state != DaemonState.RECORDING:
                return
        self._finish_recording()

    def _on_hotkey_cancel(self):
        """Called on short tap (not a hold) — discard any audio captured."""
        with self._state_lock:
            if self._state != DaemonState.RECORDING:
                return
        if self._recorder:
            self._recorder.stop_recording()  # discard
        self._set_state(DaemonState.IDLE)

    # ── Extended listening ──

    def _on_extended_start(self):
        with self._state_lock:
            if self._state == DaemonState.RECORDING:
                # Already recording from the second tap — just switch to extended mode
                pass
            elif self._state == DaemonState.IDLE:
                # Fresh extended start (shouldn't happen with current hotkey logic, but safe)
                try:
                    self._recorder.start_recording()
                except Exception:
                    logger.exception("Failed to start extended recording")
                    self._set_state(DaemonState.IDLE)
                    return
            else:
                return

        self._set_state(DaemonState.RECORDING, extended=True)
        if self._config:
            play_beep(self._config.feedback, start=True)
        logger.info("Extended listening started")

    def _on_extended_stop(self):
        with self._state_lock:
            if self._state != DaemonState.RECORDING:
                return
        logger.info("Extended listening ended")
        self._finish_recording()

    # ── Shared pipeline ──

    def _finish_recording(self):
        try:
            audio_data = self._recorder.stop_recording()
            if self._config:
                play_beep(self._config.feedback, start=False)

            if audio_data is None:
                logger.warning("No audio captured")
                self._set_state(DaemonState.IDLE)
                return

            self._set_state(DaemonState.TRANSCRIBING)

            duration_sec = len(audio_data) / self._config.audio.sample_rate
            text = self._transcriber.transcribe(audio_data, sample_rate=self._config.audio.sample_rate)

            if text:
                # LLM post-processing (formatting, commands, context)
                if self._formatter and self._formatter.enabled:
                    text = self._formatter.format(text)

                # Record in history and stats
                self._history.add(text, duration_sec, self._config.model.name)
                self._stats.record(text, duration_sec)

                # Copy to clipboard first, then batch dashboard updates
                self._injector.inject(text)

                speed = self._transcriber.last_speed
                elapsed = self._transcriber.last_elapsed
                self._dashboard.batch_post_transcription(speed, elapsed)
            else:
                logger.info("Empty transcription, nothing to inject")

        except Exception:
            logger.exception("Error during transcription pipeline")
        finally:
            self._set_state(DaemonState.IDLE)

    # ── Model change from dashboard ──

    def _on_model_change(self, model_name: str, backend: str = None):
        def _do_change():
            try:
                # Show loading state (not TRANSCRIBING — that's for actual transcription)
                self._dashboard.show_loading(f"Loading {model_name}...")
                self._dashboard.set_model_loaded(False)
                self._overlay.show_loading()

                # Free old model explicitly before loading new one
                if self._transcriber is not None:
                    self._transcriber.unload_model()
                    self._transcriber = None
                gc.collect()

                # Update config and load new model
                self._config.model.name = model_name
                if backend:
                    self._config.model.backend = backend
                self._transcriber = Transcriber(self._config.model, self._config.transcription)
                self._transcriber.load_model()

                save_config(self._config_path, self._config)
                logger.info("Model changed to %s", model_name)

                self._dashboard.set_model_loaded(True)
                llm_info = self._formatter.check_connection() if self._formatter else {}
                self._dashboard.update_system_info(
                    self._transcriber.device_used,
                    self._transcriber.compute_used,
                    self._formatter.enabled if self._formatter else False,
                    llm_connected=llm_info.get("connected", False),
                    llm_model=llm_info.get("model"),
                )
                self._set_state(DaemonState.IDLE)
            except Exception:
                logger.exception("Failed to change model")
                self._set_state(DaemonState.ERROR)

        threading.Thread(target=_do_change, daemon=True).start()

    def _on_gpu_toggle(self, use_gpu: bool):
        """Toggle GPU acceleration — reloads the model with the new device setting."""
        new_device = "auto" if use_gpu else "cpu"
        if self._config.model.device == new_device:
            return
        self._config.model.device = new_device
        save_config(self._config_path, self._config)
        logger.info("GPU %s — reloading model", "enabled" if use_gpu else "disabled")
        # Reload model with new device setting
        self._on_model_change(self._config.model.name, self._config.model.backend)

    def _on_llm_toggle(self, enabled: bool):
        self._config.llm.enabled = enabled
        if self._formatter:
            self._formatter._config.enabled = enabled
        save_config(self._config_path, self._config)

        if enabled:
            llm_info = self._formatter.check_connection() if self._formatter else {}
            self._dashboard.update_system_info(
                self._transcriber.device_used,
                self._transcriber.compute_used,
                True,
                llm_connected=llm_info.get("connected", False),
                llm_model=llm_info.get("model"),
            )
        logger.info("LLM formatting %s", "enabled" if enabled else "disabled")

    def _on_paste_snippet(self, text: str):
        threading.Thread(target=lambda: self._injector.inject(text), daemon=True).start()

    # ── Lifecycle ──

    def _shutdown(self):
        logger.info("Shutting down components")
        if self._hotkey:
            self._hotkey.stop()
            self._hotkey = None
        if self._recorder:
            self._recorder.cleanup()
            self._recorder = None
        if self._transcriber:
            self._transcriber.unload_model()
            self._transcriber = None
        self._injector = None
        gc.collect()

    def _restart(self):
        logger.info("Restarting daemon")
        self._shutdown()
        self._config = load_config(self._config_path)
        threading.Thread(target=self._initialize, daemon=True).start()

    def _quit(self):
        logger.info("Quitting demon-transcribe")
        self._shutdown()
        if self._dashboard:
            self._dashboard.stop()
