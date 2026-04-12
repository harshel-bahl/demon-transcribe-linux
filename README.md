# demon-transcribe (Linux)

Local, offline voice transcription with Vulkan GPU acceleration for Linux. A privacy-first alternative to Wispr Flow — runs entirely on your machine with no cloud dependency. All processing happens locally using whisper.cpp with GPU acceleration.

Ported from the [Windows version](https://github.com/harshel-bahl/demon-transcribe).

## Features

- **Vulkan GPU acceleration**: Uses whisper.cpp with Vulkan for fast transcription on AMD/Intel/NVIDIA GPUs
- **Push-to-talk**: Hold `Ctrl+Shift+Space` to dictate, release to transcribe and paste
- **Extended mode**: Double-tap the hotkey to keep listening, tap again to stop
- **Works everywhere**: Copies transcribed text to clipboard and pastes into the focused app
- **Wayland native**: Uses evdev for hotkeys and ydotool for text injection — works on GNOME Wayland
- **Dashboard**: Dark-themed UI with GPU status, stats, history, and model picker
- **Floating overlay**: Green dot in the bottom-right corner shows recording state
- **Model swapping**: Switch between Whisper models live from the dashboard
- **Single instance**: Only one process runs at a time

## Requirements

- Linux (tested on Ubuntu 24.04 with GNOME/Wayland)
- Python 3.11+
- Vulkan-capable GPU (AMD, Intel, or NVIDIA) with drivers installed
- Microphone

## Setup

### 1. Install system dependencies

```bash
sudo apt install -y \
    xdotool xclip cmake build-essential \
    vulkan-tools libvulkan-dev glslang-tools glslc \
    libsdl2-dev portaudio19-dev \
    python3-tk python3-venv python3-dev \
    ydotool
```

For Python 3.12 specifically (Ubuntu 24.04):
```bash
sudo apt install -y python3.12-venv python3.12-dev
```

### 2. Add yourself to the input group (required for global hotkeys on Wayland)

```bash
sudo usermod -aG input $USER
```

**You must reboot after this for the group to take effect.**

### 3. Build whisper.cpp with Vulkan

```bash
cd /tmp
git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

Then copy the binary and libraries into the project:

```bash
cd /path/to/demon-transcribe
mkdir -p bin/whisper-vulkan

# Copy binary
cp /tmp/whisper.cpp/build/bin/whisper-cli bin/whisper-vulkan/

# Copy shared libraries
for lib in /tmp/whisper.cpp/build/src/libwhisper.so.* \
           /tmp/whisper.cpp/build/ggml/src/libggml-cpu.so.* \
           /tmp/whisper.cpp/build/ggml/src/ggml-vulkan/libggml-vulkan.so.* \
           /tmp/whisper.cpp/build/ggml/src/libggml.so.* \
           /tmp/whisper.cpp/build/ggml/src/libggml-base.so.*; do
    cp "$lib" bin/whisper-vulkan/
    base=$(basename "$lib")
    # Create version symlinks
    cd bin/whisper-vulkan
    short="${base%.*.*}"
    shorter="${short%.*}"
    ln -sf "$base" "$short" 2>/dev/null
    ln -sf "$base" "$shorter" 2>/dev/null
    ln -sf "$base" "${shorter%.*}" 2>/dev/null
    cd ../..
done
```

### 4. Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Run

```bash
./venv/bin/python3 run.py
```

The default model (`large-v3-turbo-q5`, ~547MB) will download automatically on first run.

### Desktop app (optional)

To add to your GNOME app launcher, create `~/.local/share/applications/demon-transcribe.desktop`:

```ini
[Desktop Entry]
Name=Demon Transcribe
Comment=Local offline speech-to-text with Vulkan GPU acceleration
Exec=/path/to/demon-transcribe/launch.sh
Path=/path/to/demon-transcribe
Type=Application
Terminal=false
Categories=AudioVideo;Audio;Utility;
StartupNotify=true
SingleMainWindow=true
```

### Shell alias (optional)

Add to your `~/.bashrc`:

```bash
dt() {
    pkill -f "python3 run.py" 2>/dev/null
    rm -f /tmp/demon_transcribe.lock
    sleep 0.5
    cd ~/path/to/demon-transcribe
    if grep -q "input.*$USER" /etc/group 2>/dev/null && ! groups | grep -qw input; then
        sg input -c "exec ./venv/bin/python3 run.py"
    else
        ./venv/bin/python3 run.py
    fi
}
```

## Usage

| Action | How |
|---|---|
| **Dictate** | Hold `Ctrl+Shift+Space`, speak, release |
| **Extended dictate** | Double-tap `Ctrl+Shift+Space`, speak, tap again to stop |
| **Open dashboard** | Click the app window or find it in your taskbar |
| **Change model** | Dashboard → Model dropdown → Apply |
| **Copy a snippet** | Click any history entry in the dashboard |
| **Toggle GPU** | Dashboard → GPU ON/OFF button |
| **Quit** | Dashboard → Quit button |

## Models (whisper.cpp / Vulkan GPU)

| Model | Size | Speed | Quality |
|---|---|---|---|
| `tiny.en` | ~75 MB | Instant | Basic |
| `base.en` | ~142 MB | Instant | Good |
| `small.en` | ~466 MB | Fastest | Great |
| **`large-v3-turbo-q5`** | **~547 MB** | **Fast** | **Excellent (default)** |
| `large-v3-turbo-q8` | ~865 MB | Fast | Excellent+ |
| `medium.en` | ~1.5 GB | Very fast | Excellent |
| `large-v3-turbo` | ~1.6 GB | Moderate | Excellent (f16) |

Models download automatically when selected. Managed from the dashboard.

## Configuration

Edit `config.yaml` and restart the app. Key settings:

```yaml
model:
  name: "large-v3-turbo-q5"  # See model table above
  backend: "whisper-cpp"       # "whisper-cpp" (Vulkan GPU) or "faster-whisper" (CPU/CUDA)
  device: "auto"               # "auto", "cpu"
  beam_size: 1                 # 1=fast greedy, 5=slower but better

hotkey:
  combination: "ctrl+shift+space"

feedback:
  beep_on_start: false         # Beep when recording starts
  beep_on_stop: false          # Beep when recording stops

transcription:
  language: null               # null=auto-detect, or "en", "es", "fr", etc.
  vad_filter: true             # Skip silence

overlay:
  dot_size: 8                  # Overlay dot size in pixels
```

## Architecture

```
demon_transcribe/
├── main.py          # Orchestrator — lifecycle and state machine
├── dashboard.py     # Dark-themed tkinter dashboard
├── overlay.py       # Floating dot indicator (bottom-right)
├── transcriber.py   # Unified backend: whisper.cpp or faster-whisper
├── whisper_cpp.py   # whisper.cpp subprocess wrapper with Vulkan
├── audio.py         # Microphone capture via sounddevice
├── hotkey.py        # Global hotkey via evdev (Wayland) with pynput fallback (X11)
├── injector.py      # Clipboard + paste injection (ydotool/xdotool)
├── formatter.py     # Optional LLM post-processing
├── history.py       # JSON-backed snippet history
├── stats.py         # Session and all-time usage statistics
├── config.py        # YAML config with typed dataclasses
└── constants.py     # App name, version, enums
```

## Troubleshooting

**Hotkey doesn't work**: Make sure you're in the `input` group (`groups` should show `input`). If not, run `sudo usermod -aG input $USER` and **reboot**.

**"pynput fallback" in logs**: The `input` group isn't active in your session. Reboot, or use `sg input -c "./venv/bin/python3 run.py"` to activate it.

**No Vulkan GPU detected**: Check `vulkaninfo --summary` to verify your GPU supports Vulkan. Make sure you have the right drivers (`mesa-vulkan-drivers` for AMD/Intel, NVIDIA's proprietary drivers for NVIDIA).

**Text doesn't auto-paste**: On GNOME Wayland, auto-paste may not work in all apps. The text is always copied to your clipboard — just press `Ctrl+V` manually.

**Terminal paste**: Terminals use `Ctrl+Shift+V` for paste, not `Ctrl+V`. After dictating, press `Ctrl+Shift+V` in your terminal.

**Multiple instances**: The app uses a lock file at `/tmp/demon_transcribe.lock`. If it gets stuck, run `pkill -f "python3 run.py"; rm -f /tmp/demon_transcribe.lock`.

## Linux-specific notes

This is a Linux port of the [Windows version](https://github.com/harshel-bahl/demon-transcribe). Key differences:

- **Hotkeys**: Uses `evdev` (kernel-level input) instead of Win32 API — works on Wayland
- **Text injection**: Uses `ydotool` + clipboard instead of `pydirectinput`
- **GPU acceleration**: Vulkan via whisper.cpp instead of the Windows Vulkan build
- **System info**: Reads from `/proc/cpuinfo`, `lspci`, `os.sysconf` instead of PowerShell/Win32
- **Single instance**: Uses `fcntl` file locking instead of Windows Mutex
- **UI**: Uses DejaVu Sans font, Linux-compatible mousewheel events, X11/Wayland overlay

## License

MIT
