"""
whisper.cpp backend — calls the whisper-cli binary via subprocess.
Supports Vulkan GPU acceleration on AMD/Intel/NVIDIA.
"""
import json
import logging
import os
import subprocess
import tempfile
import time
import wave

import numpy as np

logger = logging.getLogger(__name__)

# Where we store the whisper.cpp binary and GGML models
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(_PROJECT_ROOT, "bin", "whisper-vulkan")
MODELS_DIR = os.path.join(_PROJECT_ROOT, "models")

# Map friendly names to GGML model filenames and download URLs
GGML_MODELS = {
    "large-v3-turbo-q5": {
        "file": "ggml-large-v3-turbo-q5_0.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
        "size": "~547 MB",
        "speed": "Fast (GPU)",
        "quality": "Excellent",
    },
    "large-v3-turbo-q8": {
        "file": "ggml-large-v3-turbo-q8_0.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin",
        "size": "~865 MB",
        "speed": "Fast (GPU)",
        "quality": "Excellent+",
    },
    "medium.en": {
        "file": "ggml-medium.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin",
        "size": "~1.5 GB",
        "speed": "Very fast (GPU)",
        "quality": "Excellent",
    },
    "small.en": {
        "file": "ggml-small.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin",
        "size": "~466 MB",
        "speed": "Fastest (GPU)",
        "quality": "Great",
    },
    "base.en": {
        "file": "ggml-base.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
        "size": "~142 MB",
        "speed": "Instant (GPU)",
        "quality": "Good",
    },
    "tiny.en": {
        "file": "ggml-tiny.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin",
        "size": "~75 MB",
        "speed": "Instant (GPU)",
        "quality": "Basic",
    },
    "large-v3-turbo": {
        "file": "ggml-large-v3-turbo.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        "size": "~1.6 GB",
        "speed": "Moderate (GPU)",
        "quality": "Excellent (f16)",
    },
}


def _get_env() -> dict:
    """Return env dict with LD_LIBRARY_PATH set to find bundled shared libs."""
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = BIN_DIR + ":" + env.get("LD_LIBRARY_PATH", "")
    return env


def get_cli_path() -> str:
    """Return the path to whisper-cli binary."""
    # Prefer Vulkan build
    vulkan_path = os.path.join(BIN_DIR, "whisper-cli")
    if os.path.exists(vulkan_path):
        return vulkan_path
    # Fallback to official build
    official_path = os.path.join(_PROJECT_ROOT, "bin", "whisper-cpp", "Release", "whisper-cli")
    if os.path.exists(official_path):
        return official_path
    raise FileNotFoundError("whisper-cli not found. Run setup to download/build it.")


def get_model_path(model_name: str) -> str:
    """Return the path to a GGML model file, downloading if needed."""
    info = GGML_MODELS.get(model_name)
    if info is None:
        # Try as a direct filename
        direct = os.path.join(MODELS_DIR, model_name)
        if os.path.exists(direct):
            return direct
        # Try with ggml- prefix
        prefixed = os.path.join(MODELS_DIR, f"ggml-{model_name}.bin")
        if os.path.exists(prefixed):
            return prefixed
        raise FileNotFoundError(f"Unknown model: {model_name}")

    model_path = os.path.join(MODELS_DIR, info["file"])
    if os.path.exists(model_path):
        return model_path

    # Download the model
    logger.info("Downloading model %s (%s)...", model_name, info["size"])
    os.makedirs(MODELS_DIR, exist_ok=True)
    _download_model(info["url"], model_path)
    return model_path


def _download_model(url: str, dest: str):
    """Download a model file with progress logging."""
    import urllib.request
    tmp = dest + ".downloading"
    try:
        def _report(block_num, block_size, total_size):
            if total_size > 0 and block_num % 500 == 0:
                pct = min(100, block_num * block_size * 100 // total_size)
                logger.info("Download progress: %d%%", pct)

        urllib.request.urlretrieve(url, tmp, reporthook=_report)
        os.replace(tmp, dest)
        logger.info("Download complete: %s", os.path.basename(dest))
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def check_vulkan_support() -> dict:
    """Quick check if whisper.cpp detects Vulkan GPU. Returns {gpu_found, gpu_name}."""
    try:
        cli = get_cli_path()
        result = subprocess.run(
            [cli, "--help"],
            capture_output=True, text=True, timeout=5,
            env=_get_env(),
        )
        stderr = result.stderr or ""
        for line in stderr.split("\n"):
            if "ggml_vulkan:" in line and "=" in line:
                # e.g. "ggml_vulkan: 0 = AMD Radeon(TM) 890M Graphics ..."
                parts = line.split("=", 1)
                if len(parts) > 1:
                    gpu_name = parts[1].split("(")[0].strip()
                    return {"gpu_found": True, "gpu_name": gpu_name}
        return {"gpu_found": False, "gpu_name": None}
    except Exception:
        return {"gpu_found": False, "gpu_name": None}


class WhisperCppTranscriber:
    """Transcriber using whisper.cpp subprocess with Vulkan GPU acceleration."""

    def __init__(self, model_name: str, language: str = "en",
                 beam_size: int = 1, use_gpu: bool = True, threads: int = 0):
        self._model_name = model_name
        self._model_path: str = None
        self._cli_path: str = None
        self._language = language or "en"
        self._beam_size = beam_size
        self._use_gpu = use_gpu
        self._threads = threads or (os.cpu_count() or 4)
        self._device_used = "vulkan" if use_gpu else "cpu"
        self._compute_used = "q5" if "q5" in model_name else "q8" if "q8" in model_name else "f16"
        self._last_speed: float = 0.0
        self._last_elapsed: float = 0.0
        # Reuse a single temp file path to avoid tmpfile churn
        self._tmp_wav = os.path.join(tempfile.gettempdir(), "demon_transcribe_audio.wav")

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

    def load_model(self):
        """Locate the CLI binary and ensure the model file exists (download if needed)."""
        self._cli_path = get_cli_path()
        logger.info("Using whisper.cpp at: %s", self._cli_path)

        self._model_path = get_model_path(self._model_name)
        logger.info("Using model: %s", self._model_path)

        # Check Vulkan on first load
        if self._use_gpu:
            info = check_vulkan_support()
            if info["gpu_found"]:
                self._device_used = "vulkan"
                logger.info("Vulkan GPU detected: %s", info["gpu_name"])
            else:
                self._device_used = "cpu"
                logger.warning("No Vulkan GPU found, running on CPU")

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio numpy array via whisper.cpp subprocess."""
        if self._cli_path is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # Convert to int16 if float32
        if audio_data.dtype == np.float32:
            audio_data = (audio_data * 32768).clip(-32768, 32767).astype(np.int16)
        if audio_data.ndim > 1:
            audio_data = audio_data[:, 0]

        duration = len(audio_data) / sample_rate

        # Write audio to reusable temp WAV file (avoids tmpfile allocation per call)
        tmp_path = self._tmp_wav
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())

        try:
            t0 = time.perf_counter()

            cmd = [
                self._cli_path,
                "-m", self._model_path,
                "-f", tmp_path,
                "-t", str(self._threads),
                "-bs", str(self._beam_size),
                "--no-prints",
                "-l", self._language,
            ]
            if not self._use_gpu:
                cmd.append("--no-gpu")

            logger.info("Transcribing %.1fs audio via whisper.cpp (%s)", duration, self._device_used)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(30, duration * 10),  # generous timeout
                env=_get_env(),
            )

            elapsed = time.perf_counter() - t0
            self._last_elapsed = elapsed
            self._last_speed = duration / elapsed if elapsed > 0 else 0

            if result.returncode != 0:
                logger.error("whisper.cpp failed (rc=%d): %s", result.returncode, result.stderr[:500])
                return ""

            # Parse output — whisper-cli with --no-prints outputs just the text
            text = result.stdout.strip()
            # Remove timestamp lines if present: [00:00:00.000 --> 00:00:05.000]   text
            lines = []
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("[") and "-->" in line and "]" in line:
                    # Extract text after the timestamp bracket
                    bracket_end = line.index("]") + 1
                    lines.append(line[bracket_end:].strip())
                elif line:
                    lines.append(line)

            result_text = " ".join(lines).strip()
            logger.info(
                "whisper.cpp (%s, %.1fs audio in %.1fs = %.1fx realtime): %s",
                self._device_used, duration, elapsed, self._last_speed, result_text[:100],
            )
            return result_text

        except Exception:
            logger.exception("whisper.cpp transcription error")
            return ""

    def unload_model(self):
        """No persistent state to free for subprocess backend."""
        self._cli_path = None
        self._model_path = None
        # Clean up temp file
        try:
            if os.path.exists(self._tmp_wav):
                os.unlink(self._tmp_wav)
        except OSError:
            pass

    @property
    def is_loaded(self) -> bool:
        return self._cli_path is not None and self._model_path is not None
