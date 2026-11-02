"""OmniVoice's official Gradio API, with no video-platform dependency."""
from __future__ import annotations

from pathlib import Path
import threading


class SpeechEngine:
    def __init__(self, url="http://127.0.0.1:9877"):
        self.url = url
        self._client = None
        self._lock = threading.Lock()

    def synthesize(self, text: str, voice: dict, speed: float, steps: int) -> bytes:
        from gradio_client import Client, handle_file
        with self._lock:
            if self._client is None:
                self._client = Client(self.url, verbose=False)
            p = voice.get("params", {})
            common = [int(steps), float(p.get("gs", 2)), True, float(speed), None, True, True]
            if voice["kind"] == "clone":
                args = [text, "Chinese", handle_file(str(voice["audio_path"])), voice["reference_text"], "", *common]
                endpoint = "/_clone_fn"
            else:
                args = [text, "Chinese", *common, *[p.get(key, "Auto") for key in
                        ("gender", "age", "pitch", "style", "accent", "dialect")]]
                endpoint = "/_design_fn"
            try:
                result = self._client.predict(*args, api_name=endpoint)
                if not result or not result[0]:
                    raise RuntimeError(str(result[1] if result and len(result) > 1 else "没有生成音频"))
                path = Path(result[0])
                content = path.read_bytes()
                if content[:4] != b"RIFF":
                    raise RuntimeError("语音引擎没有返回有效的 WAV 音频。")
                # This is the downloaded client result, not the saved voice reference.
                if path.resolve() != Path(voice.get("audio_path", ".")).resolve():
                    path.unlink(missing_ok=True)
                return content
            except Exception:
                self._client = None
                raise
