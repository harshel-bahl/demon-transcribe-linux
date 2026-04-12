import logging
import os
import shutil
import sys
from typing import Optional

import numpy as np

from .config import ModelConfig, TranscriptionConfig

logger = logging.getLogger(__name__)


def _patch_hf_symlinks():
    """Patch huggingface_hub to fall back to file copies when symlinks fail on Windows."""
    if sys.platform != "win32":
        return
    try:
        import huggingface_hub.file_download as hf_dl
        _original = hf_dl._create_symlink

        def _safe_symlink(src: str, dst: str, new_blob: bool = False):
            try:
                _original(src, dst, new_blob=new_blob)
            except OSError:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.copy2(src, dst)
                logger.debug("Symlink failed, copied %s -> %s", src, dst)

        hf_dl._create_symlink = _safe_symlink
        logger.info("Patched huggingface_hub symlink fallback for Windows")
    except Exception:
        logger.warning("Could not patch huggingface_hub symlinks (non-fatal)")


_patch_hf_symlinks()

# Models available for the faster-whisper backend
_FASTER_WHISPER_MODELS = [
    {"name": "tiny.en", "size": "~75 MB", "speed": "Fastest", "quality": "Basic", "backend": "faster-whisper"},
    {"name": "base.en", "size": "~145 MB", "speed": "Very fast", "quality": "Good", "backend": "faster-whisper"},
    {"name": "small.en", "size": "~483 MB", "speed": "Fast", "quality": "Great", "backend": "faster-whisper"},
    {"name": "medium.en", "size": "~1.5 GB", "speed": "Moderate", "quality": "Excellent", "backend": "faster-whisper"},
    {"name": "distil-large-v3", "size": "~1.5 GB", "speed": "Fast", "quality": "Excellent (distilled)", "backend": "faster-whisper"},
    {"name": "large-v3-turbo", "size": "~800 MB", "speed": "Moderate", "quality": "Excellent", "backend": "faster-whisper"},
    {"name": "large-v3", "size": "~3 GB", "speed": "Slow", "quality": "Best", "backend": "faster-whisper"},
]

# Models available for the whisper.cpp backend (Vulkan GPU)
_WHISPER_CPP_MODELS = [
    {"name": "large-v3-turbo-q5", "size": "~547 MB", "speed": "Fast (GPU)", "quality": "Excellent", "backend": "whisper-cpp"},
    {"name": "large-v3-turbo-q8", "size": "~865 MB", "speed": "Fast (GPU)", "quality": "Excellent+", "backend": "whisper-cpp"},
    {"name": "medium.en", "size": "~1.5 GB", "speed": "Very fast (GPU)", "quality": "Excellent", "backend": "whisper-cpp"},
    {"name": "small.en", "size": "~466 MB", "speed": "Fastest (GPU)", "quality": "Great", "backend": "whisper-cpp"},
    {"name": "base.en", "size": "~142 MB", "speed": "Instant (GPU)", "quality": "Good", "backend": "whisper-cpp"},
    {"name": "tiny.en", "size": "~75 MB", "speed": "Instant (GPU)", "quality": "Basic", "backend": "whisper-cpp"},
    {"name": "large-v3-turbo", "size": "~1.6 GB", "speed": "Moderate (GPU)", "quality": "Excellent (f16)", "backend": "whisper-cpp"},
]


class Transcriber:
    """Unified transcriber that delegates to either whisper.cpp or faster-whisper."""

    def __init__(self, model_config: ModelConfig, transcription_config: TranscriptionConfig):
        self._model_config = model_config
        self._transcription_config = transcription_config
        self._backend = None  # The actual backend instance
        self._backend_name = model_config.backend
        self._device_used: str = "cpu"
        self._compute_used: str = model_config.compute_type
        self._last_speed: float = 0.0
        self._last_elapsed: float = 0.0

    def load_model(self):
        if self._backend_name == "whisper-cpp":
            self._load_whisper_cpp()
        else:
            self._load_faster_whisper()

    def _load_whisper_cpp(self):
        from .whisper_cpp import WhisperCppTranscriber

        self._backend = WhisperCppTranscriber(
            model_name=self._model_config.name,
            language=self._transcription_config.language or "en",
            beam_size=self._model_config.beam_size,
            use_gpu=(self._model_config.device != "cpu"),
            threads=self._model_config.cpu_threads,
        )
        self._backend.load_model()
        self._device_used = self._backend.device_used
        self._compute_used = self._backend.compute_used
        logger.info("whisper.cpp backend loaded (device=%s)", self._device_used)

    def _load_faster_whisper(self):
        from faster_whisper import WhisperModel

        _MODEL_ID_MAP = {
            "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
        }

        name = self._model_config.model_path or self._model_config.name
        model_id = _MODEL_ID_MAP.get(name, name)
        cpu_threads = self._model_config.cpu_threads or os.cpu_count() or 4

        self._device_used, self._compute_used = self._detect_best_device(
            self._model_config.device, self._model_config.compute_type
        )

        logger.info(
            "Loading faster-whisper model '%s' (device=%s, compute=%s, threads=%d)",
            model_id, self._device_used, self._compute_used, cpu_threads,
        )
        self._backend = WhisperModel(
            model_id,
            device=self._device_used,
            compute_type=self._compute_used,
            cpu_threads=cpu_threads,
            num_workers=self._model_config.num_workers,
        )
        logger.info("faster-whisper model loaded successfully")

        if self._model_config.prewarm:
            self._prewarm()

    @staticmethod
    def _detect_best_device(config_device: str, config_compute: str) -> tuple[str, str]:
        if config_device == "cuda":
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    return "cuda", config_compute if config_compute != "int8" else "float16"
            except Exception:
                pass
            logger.warning("CUDA requested but not available, falling back to CPU")
            return "cpu", config_compute
        if config_device == "auto":
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    return "cuda", "float16"
            except Exception:
                pass
            return "cpu", config_compute
        return config_device, config_compute

    def _prewarm(self):
        try:
            silent = np.zeros(8000, dtype=np.float32)
            segments, _ = self._backend.transcribe(silent, beam_size=1, vad_filter=False, language="en")
            for _ in segments:
                pass
            logger.info("Model pre-warmed")
        except Exception:
            logger.warning("Model pre-warm failed (non-fatal)")

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        if self._backend is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        if self._backend_name == "whisper-cpp":
            return self._transcribe_whisper_cpp(audio_data, sample_rate)
        else:
            return self._transcribe_faster_whisper(audio_data, sample_rate)

    def _transcribe_whisper_cpp(self, audio_data: np.ndarray, sample_rate: int) -> str:
        result = self._backend.transcribe(audio_data, sample_rate)
        self._last_speed = self._backend.last_speed
        self._last_elapsed = self._backend.last_elapsed
        self._device_used = self._backend.device_used
        return result

    def _transcribe_faster_whisper(self, audio_data: np.ndarray, sample_rate: int) -> str:
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        if audio_data.ndim > 1:
            audio_data = audio_data[:, 0]

        duration = len(audio_data) / sample_rate

        kwargs = {
            "beam_size": self._model_config.beam_size,
            "best_of": 1,
            "temperature": self._transcription_config.temperature,
            "vad_filter": self._transcription_config.vad_filter,
            "condition_on_previous_text": False,
            "no_repeat_ngram_size": self._transcription_config.no_repeat_ngram_size,
            "word_timestamps": self._transcription_config.word_timestamps,
        }
        if self._transcription_config.language:
            kwargs["language"] = self._transcription_config.language

        import time
        t0 = time.perf_counter()
        logger.info("Transcribing %.1fs of audio via faster-whisper", duration)

        segments, info = self._backend.transcribe(audio_data, **kwargs)
        text_parts = [seg.text for seg in segments]

        elapsed = time.perf_counter() - t0
        result = "".join(text_parts).strip()
        self._last_elapsed = elapsed
        self._last_speed = duration / elapsed if elapsed > 0 else 0
        logger.info(
            "faster-whisper (%s, %.1fs audio in %.1fs = %.1fx realtime): %s",
            info.language, info.duration, elapsed, self._last_speed, result[:100],
        )
        return result

    def unload_model(self):
        if self._backend is not None:
            if self._backend_name == "whisper-cpp":
                self._backend.unload_model()
            else:
                del self._backend
            self._backend = None
            logger.info("Model unloaded")

    @property
    def is_loaded(self) -> bool:
        if self._backend_name == "whisper-cpp":
            return self._backend is not None and self._backend.is_loaded
        return self._backend is not None

    @property
    def device_used(self) -> str:
        return self._device_used

    @property
    def compute_used(self) -> str:
        return self._compute_used

    @property
    def last_speed(self) -> float:
        return self._last_speed

    @property
    def last_elapsed(self) -> float:
        return self._last_elapsed

    @staticmethod
    def list_available_models(backend: str = None) -> list[dict]:
        if backend == "faster-whisper":
            return _FASTER_WHISPER_MODELS
        if backend == "whisper-cpp":
            return _WHISPER_CPP_MODELS
        # Return all, whisper-cpp first
        return _WHISPER_CPP_MODELS + _FASTER_WHISPER_MODELS
