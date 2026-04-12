import sys
import os
import fcntl

# Single-instance lock
_lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".demon_transcribe.lock")
_lock_file = open(_lock_path, "w")
try:
    fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print("demon-transcribe is already running.")
    sys.exit(0)

from demon_transcribe.main import DemonTranscribe

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    app = DemonTranscribe(config_path=config_path)
    app.run()
