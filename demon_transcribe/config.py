from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ModelConfig:
    name: str = "small.en"
    backend: str = "whisper-cpp"  # "whisper-cpp" (Vulkan GPU) or "faster-whisper" (CPU)
    device: str = "auto"  # "auto", "cpu", or "cuda" (faster-whisper only)
    compute_type: str = "int8"
    model_path: Optional[str] = None
    beam_size: int = 1
    cpu_threads: int = 0  # 0 = auto (os.cpu_count())
    num_workers: int = 1
    prewarm: bool = True


@dataclass
class HotkeyConfig:
    combination: str = "ctrl+shift+space"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    device: Optional[int] = None
    dtype: str = "int16"


@dataclass
class InjectionConfig:
    method: str = "clipboard"  # clipboard, keystroke, auto
    restore_clipboard: bool = True
    paste_delay_ms: int = 50


@dataclass
class FeedbackConfig:
    beep_on_start: bool = True
    beep_on_stop: bool = True
    beep_frequency: int = 440
    beep_duration_ms: int = 100


@dataclass
class TranscriptionConfig:
    language: Optional[str] = None
    vad_filter: bool = True
    no_repeat_ngram_size: int = 3
    word_timestamps: bool = False
    temperature: float = 0.0


@dataclass
class DashboardConfig:
    width: int = 1000
    height: int = 680
    show_on_startup: bool = False


@dataclass
class OverlayConfig:
    position: str = "bottom"  # "top" or "bottom"
    dot_size: int = 8
    pill_width: int = 150   # unused, kept for config compat
    pill_height: int = 26   # unused, kept for config compat
    screen_margin: int = 40


@dataclass
class LLMConfig:
    enabled: bool = False
    api_url: str = "http://localhost:1234/v1/chat/completions"
    model: str = ""  # empty = use whatever model is loaded in LM Studio
    timeout_ms: int = 3000  # give up after this and use raw transcription
    system_prompt: str = (
        "You are a dictation formatter. You receive raw speech-to-text output and the name of the "
        "active application. Your job:\n"
        "1. Fix punctuation, capitalization, and spacing\n"
        "2. Expand spoken commands: 'new line' → newline, 'period' → '.', 'comma' → ',', "
        "'question mark' → '?', 'exclamation point' → '!', 'open paren' → '(', 'close paren' → ')'\n"
        "3. If the active app is a code editor (VS Code, terminal, etc.), format code-like dictation "
        "appropriately (e.g., 'def foo of x' → 'def foo(x):')\n"
        "4. Never add information that wasn't dictated. Never explain. Output ONLY the formatted text."
    )


@dataclass
class AppConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


def _merge_dataclass(cls, data: dict):
    if data is None:
        return cls()
    valid = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in valid}
    return cls(**filtered)


def load_config(path: str) -> AppConfig:
    p = Path(path)
    if not p.exists():
        save_default_config(path)

    with open(p, "r") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(
        model=_merge_dataclass(ModelConfig, raw.get("model")),
        hotkey=_merge_dataclass(HotkeyConfig, raw.get("hotkey")),
        audio=_merge_dataclass(AudioConfig, raw.get("audio")),
        injection=_merge_dataclass(InjectionConfig, raw.get("injection")),
        feedback=_merge_dataclass(FeedbackConfig, raw.get("feedback")),
        transcription=_merge_dataclass(TranscriptionConfig, raw.get("transcription")),
        dashboard=_merge_dataclass(DashboardConfig, raw.get("dashboard")),
        overlay=_merge_dataclass(OverlayConfig, raw.get("overlay")),
        llm=_merge_dataclass(LLMConfig, raw.get("llm")),
    )


def save_config(path: str, config: AppConfig):
    data = asdict(config)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def save_default_config(path: str):
    save_config(path, AppConfig())
