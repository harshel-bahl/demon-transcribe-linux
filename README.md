# demon-transcribe

Local, offline voice transcription that works in any app. A privacy-first alternative to Wispr Flow — runs entirely on your machine with no cloud dependency.

## Features

- **Push-to-talk**: Hold `Ctrl+Shift+Space` to dictate, release to paste
- **Extended mode**: Double-tap the hotkey to keep listening, tap again to stop
- **Works everywhere**: Pastes transcribed text into whatever app has focus
- **Model swapping**: Switch between Whisper models from the dashboard
- **Dashboard**: Dark-themed UI with stats, history, and model picker
- **Floating overlay**: Small dot at bottom of screen shows recording state
- **Single instance**: Only one process runs, no matter how many times you click
- **Fast**: Greedy decoding + model pre-warming + in-memory audio pipeline

## Quick Start

### Option 1: Automated setup (recommended)

```
git clone https://github.com/YOUR_USERNAME/demon-transcribe.git
cd demon-transcribe
setup.bat
```

Double-click the "Demon Transcribe" shortcut on your desktop.

### Option 2: Manual setup

```
git clone https://github.com/YOUR_USERNAME/demon-transcribe.git
cd demon-transcribe
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
venv\Scripts\pythonw.exe launch.pyw
```

### Option 3: Without venv

```
pip install -r requirements.txt
python run.py
```

## Requirements

- Windows 10/11
- Python 3.11+
- ~500MB disk (for small.en model)
- ~400MB RAM while running
- Microphone

## Usage

| Action | How |
|---|---|
| **Dictate** | Hold `Ctrl+Shift+Space`, speak, release |
| **Extended dictate** | Double-tap `Ctrl+Shift+Space`, speak, tap again to stop |
| **Open dashboard** | Click "Demon Transcribe" in taskbar |
| **Change model** | Dashboard → Model dropdown → Apply |
| **Copy past snippet** | Dashboard → click any history entry |
| **Quit** | Dashboard → Quit button |

## Models

| Model | Size | Speed | Quality | Best for |
|---|---|---|---|---|
| `tiny.en` | ~75 MB | Fastest | Basic | Quick notes, low-end hardware |
| `base.en` | ~145 MB | Very fast | Good | Casual use |
| **`small.en`** | **~483 MB** | **Fast** | **Great** | **Default — best balance** |
| `medium.en` | ~1.5 GB | Moderate | Excellent | When accuracy matters most |
| `large-v3-turbo` | ~800 MB | Fast | Excellent | Best quality-to-speed ratio |
| `large-v3` | ~3 GB | Slow | Best | Maximum accuracy |

Multilingual variants (`tiny`, `base`, `small`, `medium`) available for non-English languages.

## Configuration

Edit `config.yaml` to customize. Changes take effect after clicking "Restart" in the dashboard.

### Key settings

```yaml
model:
  name: "small.en"       # Model name (see table above)
  device: "cpu"           # "cpu" or "cuda" (NVIDIA GPU)
  compute_type: "int8"    # "int8", "float16", "float32"
  beam_size: 1            # 1=fast greedy, 5=slower but slightly better

hotkey:
  combination: "ctrl+shift+space"

transcription:
  language: null          # null=auto-detect, or "en", "es", "fr", etc.
  vad_filter: true        # Skip silence (recommended)

overlay:
  position: "bottom"      # "top" or "bottom"
  dot_size: 10            # Idle dot size in pixels
  screen_margin: 40       # Distance from screen edge
```

## Architecture

```
demon_transcribe/
├── main.py          # Orchestrator — owns lifecycle and state machine
├── dashboard.py     # Dark-themed tkinter dashboard (Tk root owner)
├── overlay.py       # Floating dot/pill indicator (Toplevel)
├── transcriber.py   # Faster-Whisper wrapper with speed optimizations
├── audio.py         # Microphone capture via sounddevice
├── hotkey.py        # Global push-to-talk with double-tap detection
├── injector.py      # Clipboard paste + keystroke fallback
├── history.py       # JSON-backed snippet history (last 100)
├── stats.py         # Session and all-time usage statistics
├── config.py        # YAML config with typed dataclasses
└── constants.py     # App name, version, enums
```

## Troubleshooting

**App doesn't start**: Check `demon_transcribe.log` in the project folder for errors.

**No audio captured**: Verify your microphone is the default input device in Windows Sound settings.

**Slow transcription**: Try `beam_size: 1` in config.yaml (default). Upgrade to `medium.en` or `large-v3-turbo` for better quality without much speed loss.

**Hotkey doesn't work in some apps**: Some apps running as administrator block global hotkeys. Try running demon-transcribe as administrator.

## License

MIT
