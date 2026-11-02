"""Install non-personal presets and download the pinned public model weights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def install_presets(root: Path = ROOT):
    """Seed missing factory voices without overwriting user edits or settings."""
    voices = root / "data" / "voices"
    voices.mkdir(parents=True, exist_ok=True)
    for source in sorted((root / "presets" / "voices").glob("*/design.json")):
        destination = voices / source.parent.name / "design.json"
        # A matching clone folder must also be preserved.
        if destination.parent.exists():
            continue
        content = source.read_text(encoding="utf-8")
        json.loads(content)
        destination.parent.mkdir()
        destination.write_text(content, encoding="utf-8")
    settings = root / "data" / "settings.json"
    if not settings.exists():
        with settings.open("x", encoding="utf-8") as output:
            json.dump({"voice_id": "mandarin-female",
                       "preview_text": "你好，这是我的声音。欢迎来到本地语音工作室。"},
                      output, ensure_ascii=False, indent=2)


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_models(root: Path = ROOT):
    from huggingface_hub import snapshot_download

    manifest = json.loads((root / "models.lock.json").read_text(encoding="utf-8"))
    for model in manifest["models"]:
        directory = root / "models" / model["directory"]
        print(f"Downloading {model['repository']} at {model['revision']}...", flush=True)
        snapshot_download(repo_id=model["repository"], revision=model["revision"],
                          local_dir=str(directory), allow_patterns=model["allow_patterns"])
        for filename, expected in model["sha256"].items():
            path = directory / filename
            if not path.is_file() or sha256(path) != expected:
                raise RuntimeError(f"Model checksum mismatch: {path}")
        print(f"Verified {model['directory']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--presets-only", action="store_true")
    mode.add_argument("--models-only", action="store_true")
    args = parser.parse_args()
    if not args.models_only:
        install_presets()
    if not args.presets_only:
        download_models()


if __name__ == "__main__":
    main()
