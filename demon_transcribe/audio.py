import logging
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from .config import AudioConfig, FeedbackConfig

logger = logging.getLogger(__name__)


class AudioRecorder:
    def __init__(self, config: AudioConfig):
        self._config = config
        self._buffer: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: Optional[sd.InputStream] = None
        self._recording = False

    def start_recording(self):
        if self._recording:
            logger.warning("Already recording")
            return

        with self._lock:
            self._buffer.clear()

        try:
            self._stream = sd.InputStream(
                samplerate=self._config.sample_rate,
                channels=self._config.channels,
                dtype=self._config.dtype,
                device=self._config.device,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._recording = True
            logger.info("Recording started")
        except Exception:
            logger.exception("Failed to start recording")
            self._recording = False
            raise

    def stop_recording(self) -> Optional[np.ndarray]:
        """Stop recording and return raw audio as numpy array, or None if empty."""
        if not self._recording:
            logger.warning("Not recording")
            return None

        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("Error stopping stream")
            self._stream = None

        with self._lock:
            if not self._buffer:
                logger.warning("Empty audio buffer")
                return None
            audio_data = np.concatenate(self._buffer)
            self._buffer.clear()

        logger.info("Captured %d frames (%.1fs)", len(audio_data), len(audio_data) / self._config.sample_rate)
        return audio_data

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio callback status: %s", status)
        with self._lock:
            self._buffer.append(indata.copy())

    def cleanup(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._recording = False


def play_beep(config: FeedbackConfig, start: bool = True):
    if start and not config.beep_on_start:
        return
    if not start and not config.beep_on_stop:
        return

    try:
        freq = config.beep_frequency if start else config.beep_frequency * 1.5
        duration = config.beep_duration_ms / 1000.0
        sample_rate = 44100
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        tone = (np.sin(2 * np.pi * freq * t) * 0.3).astype(np.float32)
        sd.play(tone, samplerate=sample_rate)
    except Exception:
        logger.exception("Failed to play beep")
