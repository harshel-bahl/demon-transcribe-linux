"""Launcher for demon-transcribe (no console window when run with pythonw.exe)."""
import os
import sys
import logging
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Single-instance lock ──
import ctypes
_MUTEX_NAME = "DemonTranscribe_SingleInstance_Mutex"
_kernel32 = ctypes.windll.kernel32
_mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
if _kernel32.GetLastError() == 183:
    sys.exit(0)

# ── Logging to file ──
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demon_transcribe.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_file, mode="w")],
)
sys.stdout = open(log_file, "a")
sys.stderr = sys.stdout

try:
    from demon_transcribe.main import DemonTranscribe
    app = DemonTranscribe(config_path="config.yaml")
    app.run()
except Exception:
    traceback.print_exc()
finally:
    if _mutex:
        _kernel32.ReleaseMutex(_mutex)
        _kernel32.CloseHandle(_mutex)
