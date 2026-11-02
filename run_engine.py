"""Start the local OmniVoice engine from this independent application folder."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "engine-cache"
CACHE.mkdir(parents=True, exist_ok=True)
os.environ.update(HF_HUB_OFFLINE="1", GRADIO_ANALYTICS_ENABLED="False",
                  GRADIO_TEMP_DIR=str(CACHE / "gradio"), HF_HUB_DISABLE_SYMLINKS_WARNING="1")
os.environ["PATH"] = str(ROOT / ".tools") + os.pathsep + os.environ.get("PATH", "")

if __name__ == "__main__":
    from omnivoice.cli.demo import main
    raise SystemExit(main(["--model", str(ROOT / "models" / "OmniVoice"), "--device", "cuda",
                           "--ip", "127.0.0.1", "--port", "9877", "--no-asr"]))
