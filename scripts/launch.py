"""Start the app, wait until it responds, then open the user's browser."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = f"http://127.0.0.1:{int(os.environ.get('PORT', '8050'))}"


def ready():
    try:
        with urllib.request.urlopen(URL + "/api/catalog", timeout=0.5) as response:
            return isinstance(json.load(response).get("sessions"), list)
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return False


def main():
    if ready():
        print(f"F1 Telemetry Lab is already running: {URL}")
        webbrowser.open(URL)
        return 0
    process = subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=ROOT)
    try:
        for _ in range(60):
            if process.poll() is not None:
                return process.returncode
            if ready():
                webbrowser.open(URL)
                print("Keep this window open. Press Ctrl+C to stop the dashboard.")
                return process.wait()
            time.sleep(0.25)
        print("The server is taking longer than expected. Check its messages above.")
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
