import sys
import os
import fcntl
import signal

# Single-instance lock using /tmp so it's always cleaned up on reboot
_lock_path = "/tmp/demon_transcribe.lock"
_lock_file = open(_lock_path, "w")
try:
    fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    # Another instance holds the lock — read its PID and report
    try:
        with open(_lock_path) as f:
            old_pid = f.read().strip()
        print(f"demon-transcribe is already running (PID {old_pid}).")
    except Exception:
        print("demon-transcribe is already running.")
    sys.exit(0)

# Write our PID so others can find us
_lock_file.truncate(0)
_lock_file.seek(0)
_lock_file.write(str(os.getpid()))
_lock_file.flush()

from demon_transcribe.main import DemonTranscribe

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    app = DemonTranscribe(config_path=config_path)
    app.run()
