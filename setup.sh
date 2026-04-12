#!/bin/bash
set -e

echo "=== demon-transcribe Linux setup ==="

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "Python 3 is required. Install with: sudo apt install python3"
    exit 1
fi

# Create venv
if [ ! -d venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# Check whisper-cli binary
if [ ! -f bin/whisper-vulkan/whisper-cli ]; then
    echo "WARNING: whisper-cli binary not found in bin/whisper-vulkan/"
    echo "Build it with: cmake -B build -DGGML_VULKAN=ON && cmake --build build"
fi

# Download default model
echo "Pre-downloading default model (large-v3-turbo-q5)..."
python -c "
from demon_transcribe.whisper_cpp import get_model_path
get_model_path('large-v3-turbo-q5')
print('Model ready!')
"

echo ""
echo "=== Setup complete! ==="
echo "Run with: source venv/bin/activate && python run.py"
