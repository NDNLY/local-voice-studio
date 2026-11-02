"""Launch Voice Studio and its local model without accounts or API keys."""
from __future__ import annotations

import argparse
from http.client import HTTPConnection, HTTPException
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import webbrowser

ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def get_json(url):
    address = urlsplit(url)
    connection = HTTPConnection(address.hostname, address.port, timeout=5)
    try:
        # These are loopback services; system proxy settings must not intercept them.
        connection.request("GET", address.path)
        response = connection.getresponse()
        if response.status != 200:
            return None
        return json.load(response)
    except (HTTPException, OSError, ValueError) as error:
        logging.info("Local service check failed for %s: %s", url, error)
        return None
    finally:
        connection.close()


def launch(python, args, log_name):
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    cache = ROOT / "data" / "tmp"
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", TEMP=str(cache), TMP=str(cache),
               GRADIO_ANALYTICS_ENABLED="False")
    env["PATH"] = str(ROOT / ".tools") + os.pathsep + env.get("PATH", "")
    # The standalone service does not need credentials inherited from other tools.
    for key in ("VIDU_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "VIDU_CONF"):
        env.pop(key, None)
    # Child services use their own Python environments, outside the frozen GUI.
    for key in list(env):
        if key.startswith("_PYI_"):
            env.pop(key)
    with (logs / log_name).open("ab") as output:
        frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
        if frozen_windows:
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            process = subprocess.Popen([str(python), *args], cwd=ROOT, env=env, stdout=output, stderr=output,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        finally:
            if frozen_windows:
                ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
    (logs / (log_name + ".pid")).write_text(str(process.pid), encoding="ascii")
    return process


def wait(url, process, seconds, label, stop_event=None):
    started = time.monotonic()
    last = -20
    while time.monotonic() - started < seconds:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("Startup cancelled.")
        data = get_json(url)
        if data is not None:
            return data
        if process.poll() is not None:
            raise RuntimeError(label + " exited. Check the logs folder.")
        elapsed = int(time.monotonic() - started)
        if elapsed - last >= 15:
            print(f"Loading {label}... {elapsed}s", flush=True)
            last = elapsed
        time.sleep(1)
    raise RuntimeError(label + " is still loading. Check the logs folder before retrying.")


def ensure_services(on_started=None, stop_event=None):
    def start(python, args, log_name):
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("Startup cancelled.")
        process = launch(python, args, log_name)
        if on_started:
            on_started(process)
        return process

    speech = get_json("http://127.0.0.1:9877/config")
    if speech is None:
        for model in ("models/OmniVoice/model.safetensors", "models/OmniVoice/audio_tokenizer/model.safetensors"):
            if not (ROOT / model).is_file():
                raise RuntimeError("Missing local speech model: " + model)
        process = start(ROOT / ".tts-venv/Scripts/python.exe", [str(ROOT / "run_engine.py")], "engine.log")
        speech = wait("http://127.0.0.1:9877/config", process, 240, "speech model", stop_event)
    if speech.get("title") != "OmniVoice Demo":
        raise RuntimeError("Port 9877 is occupied by another application.")
    url = "http://127.0.0.1:8788"
    app = get_json(url + "/api/health")
    if app is None:
        process = start(ROOT / ".venv/Scripts/python.exe",
                         ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8788"], "studio.log")
        app = wait(url + "/api/health", process, 45, "Voice Studio", stop_event)
    if app.get("app") != "voice-studio":
        raise RuntimeError("Port 8788 is occupied by another application.")
    print("Voice Studio ready: " + url, flush=True)
    print("Local speech generation. No login, API keys or platform credits required.", flush=True)
    return url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = ensure_services()
    if not args.no_browser:
        webbrowser.open(url)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Startup failed: " + str(error), flush=True)
        raise SystemExit(1)
