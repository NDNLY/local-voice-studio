"""Tests use a temporary data directory and never touch the user's voice library."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
import uuid
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
storage = tempfile.TemporaryDirectory()
os.environ["VOICE_STUDIO_DATA"] = storage.name
import app as studio
from fastapi.testclient import TestClient


def wav_fixture():
    import math
    audio = io.BytesIO()
    samples = b"".join(int(9000 * math.sin(i * math.tau * 330 / 16000)).to_bytes(2, "little", signed=True)
                       for i in range(16000 * 4))
    with wave.open(audio, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(samples)
    return audio.getvalue()


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(studio.app)
        folder = studio.VOICES / "test-design"
        folder.mkdir()
        (folder / "design.json").write_text(json.dumps({"label": "测试音色"}), encoding="utf-8")
        cls.wav = wav_fixture()
        cls.bin = Path(storage.name) / "fake-system-bin"
        cls.bin.mkdir()
        cls.desktop = Path(storage.name) / "desktop"
        cls.desktop.mkdir()
        os.environ["VOICE_STUDIO_DESKTOP"] = str(cls.desktop)
        def recycle(path):
            source = Path(path)
            source.rename(cls.bin / source.name)
        cls.recycle_patch = patch.object(studio, "send2trash", side_effect=recycle)
        cls.recycle_patch.start()
        cls.addClassCleanup(cls.recycle_patch.stop)
        wav_path = Path(storage.name) / "fixture.wav"
        wav_path.write_bytes(cls.wav)
        cls.video = Path(storage.name) / "fixture.mp4"
        subprocess.run([studio.ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=5", "-i", str(wav_path), "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(cls.video)], check=True)

    def restore_from_system_bin(self, trash_id):
        folder = next(self.bin.glob("*--" + trash_id))
        folder.rename(studio.TRASH / folder.name)
        self.client.get("/api/voices")
        self.client.get("/api/history")

    def test_preview_text_persists(self):
        response = self.client.post("/api/settings", json={"preview_text": "自定义试听，已保存。", "voice_id": "test-design"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/voices").json()["settings"]["preview_text"], "自定义试听，已保存。")

    def test_empty_text_is_rejected(self):
        self.assertEqual(self.client.post("/api/generate", json={"voice_id": "test-design", "text": "  "}).status_code, 400)

    def test_voice_path_is_bounded(self):
        self.assertEqual(self.client.post("/api/generate", json={"voice_id": "../settings", "text": "你好"}).status_code, 400)

    def test_external_page_cannot_modify_local_settings(self):
        response = self.client.post("/api/settings", json={"preview_text": "外部页面"}, headers={"Origin": "https://external.example"})
        self.assertEqual(response.status_code, 403)

    def test_invalid_reference_range_is_rejected(self):
        response = self.client.post("/api/voices/clone", files={"file": ("ref.wav", self.wav, "audio/wav")},
                                    data={"name": "测试", "start": "-1", "seconds": "4"})
        self.assertEqual(response.status_code, 400)

    def test_clone_saves_reference_and_can_be_selected(self):
        response = self.client.post("/api/voices/clone", files={"file": ("ref.wav", self.wav, "audio/wav")},
                                    data={"name": "克隆测试音色", "text": "这是参考录音的对应文字。", "seconds": "4"})
        self.assertEqual(response.status_code, 200, response.text)
        voice_id = response.json()["id"]
        self.assertEqual(studio.settings()["voice_id"], voice_id)
        reference = self.client.get(f"/api/voices/{voice_id}/reference")
        self.assertEqual(reference.status_code, 200)
        self.assertTrue(reference.content.startswith(b"RIFF"))

    def test_generation_history_and_both_download_formats(self):
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            response = self.client.post("/api/generate", json={"voice_id": "test-design", "text": "下载格式验证"})
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()
        self.assertNotIn(item["id"], [work["id"] for work in self.client.get("/api/history").json()])
        saved = self.client.post("/api/history", json={"audio_id": item["id"], "title": "手动保存的作品"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()["saved"])
        self.assertEqual(self.client.get("/api/history").json()[0]["id"], item["id"])
        wav = self.client.get(item["url"] + "?download=true")
        self.assertTrue(wav.content.startswith(b"RIFF"))
        self.assertIn("attachment", wav.headers["content-disposition"])
        mp3 = self.client.get("/api/audio/" + item["id"] + ".mp3?download=true")
        self.assertEqual(mp3.status_code, 200)
        self.assertEqual(mp3.headers["content-type"], "audio/mpeg")
        self.assertGreater(len(mp3.content), 1000)

    def make_clone(self):
        voice_id = "test-" + uuid.uuid4().hex[:12]
        folder = studio.VOICES / voice_id
        folder.mkdir()
        (folder / "ref_audio.wav").write_bytes(self.wav)
        (folder / "ref_text.txt").write_text("参考原文", encoding="utf-8")
        (folder / "label.txt").write_text("待编辑音色", encoding="utf-8")
        return voice_id, folder

    def make_work(self, voice_id="test-design", title="测试作品"):
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            response = self.client.post("/api/generate", json={"voice_id": voice_id, "text": "作品测试原文", "title": title})
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.post("/api/history", json={"audio_id": response.json()["id"], "title": title})
        self.assertEqual(saved.status_code, 200, saved.text)
        return saved.json()

    def test_edit_clone_preserves_recording_and_updates_reference(self):
        voice_id, folder = self.make_clone()
        response = self.client.patch(f"/api/voices/{voice_id}", json={"name": "新的声音名称", "reference_text": "校正后的参考原文"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "新的声音名称")
        self.assertEqual(response.json()["reference_text"], "校正后的参考原文")
        self.assertEqual((folder / "ref_audio.wav").read_bytes(), self.wav)
        invalid = self.client.patch(f"/api/voices/{voice_id}", json={"name": "合法名字", "reference_text": " "})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(studio.get_voice(voice_id)["name"], "新的声音名称")

    def test_design_rename_preserves_synthesis_parameters(self):
        folder = studio.VOICES / ("design-" + uuid.uuid4().hex[:10])
        folder.mkdir()
        studio.write_json(folder / "design.json", {"label": "旧名", "pitch": "Low", "gender": "Female", "gs": 2.5})
        response = self.client.patch(f"/api/voices/{folder.name}", json={"name": "新名"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(studio.get_voice(folder.name)["params"], {"pitch": "Low", "gender": "Female", "gs": 2.5})

    def test_deleted_voice_can_restore_without_removing_its_works(self):
        voice_id, folder = self.make_clone()
        item = self.make_work(voice_id)
        self.client.post("/api/settings", json={"voice_id": voice_id})
        response = self.client.delete(f"/api/voices/{voice_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(folder.exists())
        self.assertNotEqual(studio.settings()["voice_id"], voice_id)
        self.assertEqual(self.client.get(item["url"]).content, self.wav)
        trash_id = response.json()["trash_id"]
        self.assertTrue(next(self.bin.glob("*--" + trash_id)).is_dir())
        self.assertFalse(any(studio.TRASH.glob("*--" + trash_id)))
        self.restore_from_system_bin(trash_id)
        self.assertEqual((folder / "ref_audio.wav").read_bytes(), self.wav)
        self.assertEqual(studio.get_voice(voice_id)["reference_text"], "参考原文")

    def test_work_rename_delete_and_restore_both_formats(self):
        item = self.make_work()
        audio_id = item["id"]
        response = self.client.patch(f"/api/history/{audio_id}", json={"title": "新的作品名"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], item["text"])
        wav = self.client.get(item["url"] + "?download=true")
        self.assertIn("filename*=utf-8", wav.headers["content-disposition"])
        mp3_url = f"/api/audio/{audio_id}.mp3"
        mp3 = self.client.get(mp3_url)
        self.assertEqual(mp3.status_code, 200)
        removed = self.client.delete(f"/api/history/{audio_id}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.client.get(item["url"]).status_code, 404)
        self.assertEqual(self.client.get(mp3_url).status_code, 404)
        self.assertNotIn(audio_id, [work["id"] for work in self.client.get("/api/history").json()])
        self.restore_from_system_bin(removed.json()["trash_id"])
        self.assertEqual(self.client.get(item["url"]).content, self.wav)
        self.assertEqual(self.client.get(mp3_url).content, mp3.content)
        work = next(work for work in self.client.get("/api/history").json() if work["id"] == audio_id)
        self.assertEqual(work["title"], "新的作品名")

    def test_rewrite_creates_a_separate_work(self):
        original = self.make_work()
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            edited = self.client.post("/api/generate", json={"voice_id": original["voice_id"], "text": "新的原文", "title": "测试作品（修改版）"}).json()
        self.assertNotEqual(original["id"], edited["id"])
        self.assertEqual(edited["text"], "新的原文")
        self.assertEqual(edited["title"], "测试作品（修改版）")
        self.assertIn(original["id"], [item["id"] for item in self.client.get("/api/history").json()])

    def test_edit_validation_busy_guard_and_cross_origin(self):
        voice_id, _ = self.make_clone()
        self.assertEqual(self.client.patch(f"/api/voices/{voice_id}", json={"name": " "}).status_code, 400)
        self.assertEqual(self.client.patch("/api/history/invalid-id", json={"title": "test"}).status_code, 400)
        with patch.object(studio._synthesis_lock, "locked", return_value=True):
            self.assertEqual(self.client.delete(f"/api/voices/{voice_id}").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/voices/{voice_id}", headers={"Origin": "https://external.example"}).status_code, 403)
        self.assertTrue((studio.VOICES / voice_id).is_dir())

    def test_restore_cannot_overwrite_existing_voice(self):
        voice_id, folder = self.make_clone()
        deleted = self.client.delete(f"/api/voices/{voice_id}").json()
        folder.mkdir()
        (folder / "keep.txt").write_text("keep", encoding="utf-8")
        self.restore_from_system_bin(deleted["trash_id"])
        self.assertEqual((folder / "keep.txt").read_text(), "keep")

    def test_delete_rolls_back_files_when_history_cannot_save(self):
        item = self.make_work()
        original_write = studio.write_json
        def fail_history(path, data):
            if path == studio.HISTORY:
                raise OSError("simulated disk failure")
            return original_write(path, data)
        trash_before = sorted(path.name for path in self.bin.iterdir())
        with patch.object(studio, "write_json", side_effect=fail_history):
            with self.assertRaises(OSError):
                self.client.delete("/api/history/" + item["id"])
        self.assertEqual(self.client.get(item["url"]).content, self.wav)
        self.assertIn(item["id"], [work["id"] for work in self.client.get("/api/history").json()])
        self.assertEqual(sorted(path.name for path in self.bin.iterdir()), trash_before)

    def test_preview_is_unsaved_until_explicit_save_and_save_is_idempotent(self):
        before = self.client.get("/api/history").json()
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            item = self.client.post("/api/generate", json={"voice_id": "test-design", "text": "仅供试听"}).json()
        self.assertFalse(item["saved"])
        self.assertEqual(self.client.get("/api/history").json(), before)
        self.assertTrue((studio.DRAFTS / (item["id"] + ".wav")).is_file())
        self.assertEqual(self.client.get(item["url"]).content, self.wav)
        self.assertEqual(self.client.get("/api/audio/" + item["id"] + ".mp3").status_code, 200)
        for _ in range(2):
            saved = self.client.post("/api/history", json={"audio_id": item["id"], "title": "选中的作品"})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()["saved"])
        self.assertEqual(len(self.client.get("/api/history").json()), len(before) + 1)
        self.assertTrue((studio.AUDIO / (item["id"] + ".mp3")).is_file())
        self.assertFalse((studio.DRAFTS / (item["id"] + ".json")).exists())

    def test_video_audio_is_saved_to_desktop_without_overwriting(self):
        results = []
        for _ in range(2):
            response = self.client.post("/api/extract-audio", files={"file": ("示例视频.mp4", self.video.read_bytes(), "video/mp4")})
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()
            path = Path(item["path"])
            self.assertEqual(path.parent, self.desktop)
            self.assertGreater(path.stat().st_size, 1000)
            self.assertEqual(self.client.get(item["url"]).content, path.read_bytes())
            results.append(path)
        self.assertNotEqual(*results)

    def test_invalid_video_does_not_create_desktop_audio(self):
        before = sorted(path.name for path in self.desktop.iterdir())
        response = self.client.post("/api/extract-audio", files={"file": ("bad.mp4", b"broken", "video/mp4")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(sorted(path.name for path in self.desktop.iterdir()), before)

    def test_failed_system_recycle_restores_original_files_and_metadata(self):
        item = self.make_work()
        with patch.object(studio, "send2trash", side_effect=OSError("recycle unavailable")):
            with self.assertRaises(OSError):
                self.client.delete("/api/history/" + item["id"])
        self.assertEqual(self.client.get(item["url"]).content, self.wav)
        self.assertIn(item["id"], [work["id"] for work in self.client.get("/api/history").json()])

    def test_legacy_local_deleted_voice_is_migrated_not_restored(self):
        legacy = studio.TRASH / uuid.uuid4().hex
        legacy.mkdir()
        (legacy / "voice").mkdir()
        voice_id = "legacy-" + uuid.uuid4().hex[:10]
        studio.write_json(legacy / "manifest.json", {"kind": "voice", "original_id": voice_id})
        self.client.get("/api/voices")
        self.assertFalse((studio.VOICES / voice_id).exists())
        self.assertFalse(legacy.exists())
        self.assertTrue((self.bin / legacy.name).is_dir())

    def test_discard_preview_removes_cache_and_preserves_saved_work(self):
        saved = self.make_work()
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            preview = self.client.post("/api/generate", json={"voice_id": "test-design", "text": "清理验证"}).json()
        self.client.get("/api/audio/" + preview["id"] + ".mp3")
        response = self.client.post("/api/previews/" + preview["id"] + "/discard")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["discarded"])
        self.assertFalse(any(studio.DRAFTS.glob(preview["id"] + ".*")))
        self.assertEqual(self.client.get(preview["url"]).status_code, 404)
        self.client.post("/api/previews/" + saved["id"] + "/discard")
        self.assertEqual(self.client.get(saved["url"]).content, self.wav)

    def test_cache_expiry_preserves_new_previews_and_saved_audio(self):
        import time
        saved = self.make_work()
        stale_id, new_id = uuid.uuid4().hex, uuid.uuid4().hex
        for audio_id in (stale_id, new_id):
            (studio.DRAFTS / (audio_id + ".wav")).write_bytes(self.wav)
        stale = studio.DRAFTS / (stale_id + ".wav")
        os.utime(stale, (time.time() - 90000, time.time() - 90000))
        studio.cleanup_previews(86400)
        self.assertFalse(stale.exists())
        self.assertTrue((studio.DRAFTS / (new_id + ".wav")).exists())
        self.assertEqual(self.client.get(saved["url"]).content, self.wav)

    def test_startup_and_shutdown_clear_previews_only(self):
        saved = self.make_work()
        old_id = uuid.uuid4().hex
        (studio.DRAFTS / (old_id + ".wav")).write_bytes(self.wav)
        with TestClient(studio.app) as client:
            self.assertFalse((studio.DRAFTS / (old_id + ".wav")).exists())
            with patch.object(studio.engine, "synthesize", return_value=self.wav):
                preview = client.post("/api/generate", json={"voice_id": "test-design", "text": "会话试听"}).json()
            self.assertTrue((studio.DRAFTS / (preview["id"] + ".wav")).exists())
        self.assertFalse((studio.DRAFTS / (preview["id"] + ".wav")).exists())
        self.assertEqual(self.client.get(saved["url"]).content, self.wav)

    def test_recycle_button_launches_visible_explorer_and_reports_failures(self):
        with patch.object(studio.subprocess, "Popen") as popen, patch.object(studio, "focus_recycle_bin_window", return_value=True):
            response = self.client.post("/api/system-recycle-bin/open")
            self.assertEqual(response.status_code, 200, response.text)
            args, kwargs = popen.call_args
            self.assertTrue(args[0][0].endswith("explorer.exe"))
            self.assertEqual(args[0][1], "shell:::{645FF040-5081-101B-9F08-00AA002F954E}")
            self.assertEqual(kwargs["startupinfo"].wShowWindow, 1)
        with patch.object(studio.subprocess, "Popen", side_effect=OSError("cannot start")):
            self.assertEqual(self.client.post("/api/system-recycle-bin/open").status_code, 503)

    def test_preview_session_disconnect_deletes_unsaved_audio(self):
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            preview = self.client.post("/api/generate", json={"voice_id": "test-design", "text": "连接清理验证"}).json()
        with self.client.websocket_connect("/api/previews/" + preview["id"] + "/session"):
            self.assertTrue((studio.DRAFTS / (preview["id"] + ".wav")).exists())
        self.assertFalse(any(studio.DRAFTS.glob(preview["id"] + ".*")))

    def test_preview_session_cannot_be_opened_from_external_origin(self):
        from starlette.websockets import WebSocketDisconnect
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            preview = self.client.post("/api/generate", json={"voice_id": "test-design", "text": "外部来源验证"}).json()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/previews/" + preview["id"] + "/session", headers={"Origin": "https://external.example"}):
                pass
        self.assertTrue((studio.DRAFTS / (preview["id"] + ".wav")).exists())

    def test_saving_while_preview_connected_survives_disconnect(self):
        with patch.object(studio.engine, "synthesize", return_value=self.wav):
            preview = self.client.post("/api/generate", json={"voice_id": "test-design", "text": "保存后保留"}).json()
        with self.client.websocket_connect("/api/previews/" + preview["id"] + "/session"):
            saved = self.client.post("/api/history", json={"audio_id": preview["id"], "title": "需要保留的作品"})
            self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get(preview["url"]).content, self.wav)
        self.assertIn(preview["id"], [item["id"] for item in self.client.get("/api/history").json()])


if __name__ == "__main__":
    unittest.main()
