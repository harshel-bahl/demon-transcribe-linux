from enum import Enum

APP_NAME = "demon-transcribe"
APP_VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = "config.yaml"
HISTORY_FILE = "history.json"
MAX_HISTORY_ITEMS = 100


class DaemonState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    ERROR = "error"
