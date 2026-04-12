#!/bin/bash
# Kill ALL existing instances — by lock file and by process name
if [ -f /tmp/demon_transcribe.lock ]; then
    pid=$(cat /tmp/demon_transcribe.lock 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
    fi
    rm -f /tmp/demon_transcribe.lock
fi
pkill -f "python3 run.py" 2>/dev/null
sleep 0.5

cd /home/harshel-bahl/Documents/demon-transcribe
exec ./venv/bin/python3 run.py
