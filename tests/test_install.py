"""Verify that a clean checkout gets usable presets without touching user data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prepare_install", PROJECT / "scripts" / "prepare_install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_factory_voices_install_without_overwriting_personal_edits(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(PROJECT / "presets", root / "presets")
            installer.install_presets(root)
            voices = root / "data" / "voices"
            self.assertEqual(len(list(voices.glob("*/design.json"))), 4)
            settings = root / "data" / "settings.json"
            selected = json.loads(settings.read_text(encoding="utf-8"))["voice_id"]
            self.assertTrue((voices / selected / "design.json").is_file())
            edited = voices / selected / "design.json"
            edited.write_text('{"label":"my edit"}', encoding="utf-8")
            settings.write_text('{"voice_id":"my-clone"}', encoding="utf-8")
            installer.install_presets(root)
            self.assertEqual(json.loads(edited.read_text(encoding="utf-8"))["label"], "my edit")
            self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["voice_id"], "my-clone")

    def test_model_manifest_pins_all_required_weights(self):
        models = json.loads((PROJECT / "models.lock.json").read_text(encoding="utf-8"))["models"]
        self.assertEqual({model["directory"] for model in models}, {"OmniVoice", "faster-whisper-small"})
        for model in models:
            self.assertRegex(model["revision"], r"^[a-f0-9]{40}$")
            for digest in model["sha256"].values():
                self.assertRegex(digest, r"^[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
