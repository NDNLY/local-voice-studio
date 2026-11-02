"""Local Voice Studio: voice cloning, text-to-speech and downloadable audio."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx
from send2trash import send2trash

from engine_client import SpeechEngine

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("VOICE_STUDIO_DATA", ROOT / "data")).resolve()
VOICES = DATA / "voices"
AUDIO = DATA / "audio"
TEMP = DATA / "tmp"
TRASH = DATA / "trash"
DRAFTS = DATA / "previews"
EXTRACTED = DATA / "extracted"
for directory in (VOICES, AUDIO, TEMP, TRASH, DRAFTS, EXTRACTED):
    directory.mkdir(parents=True, exist_ok=True)
os.environ["GRADIO_TEMP_DIR"] = str(TEMP / "gradio")
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
SETTINGS = DATA / "settings.json"
HISTORY = DATA / "history.json"
DEFAULT_PREVIEW = "你好，这是我的声音。欢迎来到本地语音工作室。"
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_UPLOAD = 32 * 1024 * 1024
MAX_VIDEO = 512 * 1024 * 1024
_disk_lock = threading.RLock()
_asr_lock = threading.Lock()
_asr_model = None
_synthesis_lock = asyncio.Lock()
_audio_lock = asyncio.Lock()
engine = SpeechEngine(os.environ.get("VOICE_STUDIO_ENGINE", "http://127.0.0.1:9877"))


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data):
    with _disk_lock:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def settings():
    return read_json(SETTINGS, {"voice_id": "mandarin-female", "preview_text": DEFAULT_PREVIEW})


def checked_id(value):
    if not ID_RE.fullmatch(value):
        raise HTTPException(400, "音色或音频编号无效。")
    return value


def get_voice(voice_id):
    folder = VOICES / checked_id(voice_id)
    if (folder / "design.json").is_file():
        params = read_json(folder / "design.json", {})
        return {"id": voice_id, "name": params.pop("label", voice_id), "kind": "design", "params": params}
    audio_path = folder / "ref_audio.wav"
    if audio_path.is_file() and (folder / "ref_text.txt").is_file():
        label_path = folder / "label.txt"
        return {"id": voice_id, "name": label_path.read_text(encoding="utf-8").strip() if label_path.exists() else voice_id,
                "kind": "clone", "audio_path": audio_path,
                "reference_text": (folder / "ref_text.txt").read_text(encoding="utf-8").strip()}
    raise HTTPException(404, "这个音色不存在，请刷新音色库。")


def voice_list():
    result = []
    for folder in sorted(VOICES.iterdir()):
        if not folder.is_dir() or not ID_RE.fullmatch(folder.name):
            continue
        try:
            voice = get_voice(folder.name)
            item = {key: voice[key] for key in ("id", "name", "kind")}
            if voice["kind"] == "clone":
                item["reference_text"] = voice["reference_text"]
                with wave.open(str(voice["audio_path"])) as audio:
                    item["reference_seconds"] = round(audio.getnframes() / audio.getframerate(), 2)
            result.append(item)
        except (HTTPException, OSError, wave.Error):
            continue
    return result


def ffmpeg():
    local = ROOT / ".tools" / "ffmpeg.exe"
    if local.exists():
        return str(local)
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def normalize_reference(source, destination, start, seconds):
    if not math.isfinite(start) or not math.isfinite(seconds) or start < 0 or not 3 <= seconds <= 15:
        raise HTTPException(400, "请选择3到15秒的参考片段，起点不能小于0。")
    process = subprocess.run([ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-ss", str(start),
                              "-i", str(source), "-t", str(seconds), "-vn", "-ac", "1", "-ar", "16000",
                              "-c:a", "pcm_s16le", str(destination)], capture_output=True, timeout=30)
    if process.returncode:
        raise HTTPException(400, "无法读取这个音频，请使用 WAV、MP3、M4A、FLAC 或 OGG 文件。")
    try:
        with wave.open(str(destination)) as audio:
            duration = audio.getnframes() / audio.getframerate()
            import numpy as np
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32)
        if duration < 2.5:
            raise HTTPException(400, "所选片段不足3秒，请调整起点或时长。")
        if float(np.sqrt(np.mean(samples * samples))) < 40:
            raise HTTPException(400, "这段音频几乎没有声音，请选择清晰的人声片段。")
        return round(duration, 2)
    except (wave.Error, EOFError) as exc:
        raise HTTPException(400, "参考音频格式不正确。") from exc


def recognize_reference(path):
    global _asr_model
    import numpy as np
    with wave.open(str(path)) as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
    with _asr_lock:
        if _asr_model is None:
            from faster_whisper import WhisperModel
            _asr_model = WhisperModel(str(ROOT / "models" / "faster-whisper-small"), device="cpu",
                                       compute_type="int8", cpu_threads=4, local_files_only=True)
        segments, _ = _asr_model.transcribe(samples, language="zh", beam_size=5, vad_filter=True,
                                            condition_on_previous_text=False)
        return "".join(segment.text.strip() for segment in segments).strip()


async def read_upload(file):
    content = await file.read(MAX_UPLOAD + 1)
    if not content:
        raise HTTPException(400, "请先选择一段参考音频。")
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "参考文件超过32MB，请先截取一段较短的录音。")
    return content


def store_generation(content, voice, text, speed, steps, title=None):
    with wave.open(io.BytesIO(content)) as audio:
        duration = audio.getnframes() / audio.getframerate()
    audio_id = uuid.uuid4().hex
    (DRAFTS / (audio_id + ".wav")).write_bytes(content)
    item = {"id": audio_id, "title": title or text[:24], "voice_id": voice["id"], "voice_name": voice["name"], "text": text,
            "duration": round(duration, 2), "speed": speed, "steps": steps,
            "created_at": datetime.now(timezone.utc).isoformat(), "url": f"/api/audio/{audio_id}.wav", "saved": False}
    with _disk_lock:
        write_json(DRAFTS / (audio_id + ".json"), item)
    return item


def require_idle():
    if _synthesis_lock.locked():
        raise HTTPException(409, "正在生成声音，请完成后再编辑或删除。")


def checked_audio_id(audio_id):
    if not re.fullmatch(r"[a-f0-9]{32}", audio_id):
        raise HTTPException(400, "作品编号无效。")
    return audio_id


def discard_preview(audio_id):
    """Only remove disposable preview files; saved audio is in a different folder."""
    checked_audio_id(audio_id)
    if DRAFTS.resolve().parent != DATA.resolve():
        raise RuntimeError("Preview cache is outside the application data directory.")
    with _disk_lock:
        paths = [DRAFTS / (audio_id + suffix) for suffix in (".wav", ".mp3", ".json", ".json.tmp")]
        existed = any(path.exists() for path in paths)
        try:
            for path in paths:
                path.unlink(missing_ok=True)
        except OSError:
            # A download can briefly hold an audio file open on Windows.
            return False
        return existed


def cleanup_previews(max_age=None):
    now = time.time()
    with _disk_lock:
        ids = {path.name.split(".")[0] for path in DRAFTS.iterdir()
               if path.is_file() and re.fullmatch(r"[a-f0-9]{32}\.(?:wav|mp3|json|json\.tmp)", path.name)}
        removed = 0
        for audio_id in ids:
            paths = list(DRAFTS.glob(audio_id + ".*"))
            if max_age is not None and any(now - path.stat().st_mtime < max_age for path in paths):
                continue
            removed += bool(discard_preview(audio_id))
        return removed


def archive_item(kind, original_id, name, item, files, commit=None, rollback=None):
    """Bundle related files and send the bundle to the actual system recycle bin."""
    trash_id = uuid.uuid4().hex
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:40] or kind
    folder = TRASH / (safe_name + "--" + trash_id)
    folder.mkdir()
    moved = []
    committed = False
    try:
        for source, target_name in files:
            if source.exists():
                target = folder / target_name
                source.rename(target)
                moved.append((source, target))
        write_json(folder / "manifest.json", {"id": trash_id, "kind": kind, "original_id": original_id,
            "name": name, "item": item, "deleted_at": datetime.now(timezone.utc).isoformat()})
        if commit:
            commit()
            committed = True
        send2trash(str(folder))
    except Exception:
        if committed and rollback:
            rollback()
        for source, target in reversed(moved):
            target.rename(source)
        for temporary in (folder / "manifest.json", folder / "manifest.json.tmp"):
            temporary.unlink(missing_ok=True)
        folder.rmdir()
        raise
    return trash_id


def recover_restored_items():
    """Windows Restore returns a bundle here; merge it back into the library."""
    with _disk_lock:
        for folder in list(TRASH.iterdir()):
            if not folder.is_dir():
                continue
            record = read_json(folder / "manifest.json", {})
            if record.get("kind") not in ("voice", "work"):
                continue
            # Old versions kept deleted bundles locally under a bare UUID.
            # Preserve that deletion intent by migrating them to Windows Trash.
            if re.fullmatch(r"[a-f0-9]{32}", folder.name):
                send2trash(str(folder))
                continue
            original_id = record.get("original_id", "")
            if record["kind"] == "voice":
                target = VOICES / checked_id(original_id)
                if target.exists() or not (folder / "voice").is_dir():
                    continue
                (folder / "voice").rename(target)
                if not settings().get("voice_id"):
                    write_json(SETTINGS, {**settings(), "voice_id": original_id})
            else:
                checked_audio_id(original_id)
                items = read_json(HISTORY, [])
                if any(item["id"] == original_id for item in items) or not (folder / "audio.wav").is_file():
                    continue
                if any((AUDIO / (original_id + "." + ext)).exists() for ext in ("wav", "mp3")):
                    continue
                for ext in ("wav", "mp3"):
                    source = folder / ("audio." + ext)
                    if source.exists():
                        source.rename(AUDIO / (original_id + "." + ext))
                items.append({**record["item"], "saved": True})
                items.sort(key=lambda item: item["created_at"], reverse=True)
                write_json(HISTORY, items)
            (folder / "manifest.json").unlink()
            folder.rmdir()


def desktop_directory():
    override = os.environ.get("VOICE_STUDIO_DESKTOP")
    if override:
        return Path(override).resolve()
    if os.name == "nt":
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
            return Path(buffer.value)
    return Path.home() / "Desktop"


@asynccontextmanager
async def lifespan(application):
    cleanup_previews()
    async def maintain_cache():
        while True:
            await asyncio.sleep(60)
            async with _audio_lock:
                cleanup_previews(24 * 3600)
    maintenance = asyncio.create_task(maintain_cache())
    try:
        yield
    finally:
        maintenance.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance
        cleanup_previews()


app = FastAPI(title="Local Voice Studio", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        from urllib.parse import urlparse
        if urlparse(origin).netloc != request.headers.get("host"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "请从本机语音工作室页面操作。"}, status_code=403)
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
async def health():
    ready = False
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(engine.url + "/config")
            ready = response.status_code == 200 and response.json().get("title") == "OmniVoice Demo"
    except (httpx.HTTPError, ValueError):
        pass
    return {"ok": True, "app": "voice-studio", "engine_ready": ready, "local_only": True,
            "voice_count": len(voice_list()), "asr_available": (ROOT / "models/faster-whisper-small/model.bin").is_file()}


@app.get("/api/voices")
async def voices():
    recover_restored_items()
    return {"voices": voice_list(), "settings": settings()}


class SettingsBody(BaseModel):
    voice_id: str | None = None
    preview_text: str | None = Field(default=None, max_length=300)


@app.post("/api/settings")
async def save_settings(body: SettingsBody):
    with _disk_lock:
        current = settings()
        if body.voice_id is not None:
            get_voice(body.voice_id)
            current["voice_id"] = body.voice_id
        if body.preview_text is not None:
            current["preview_text"] = body.preview_text.strip() or DEFAULT_PREVIEW
        write_json(SETTINGS, current)
    return current


class GenerateBody(BaseModel):
    voice_id: str
    text: str = Field(min_length=1, max_length=2000)
    speed: float = Field(default=1, ge=0.7, le=1.3)
    steps: int = 16
    title: str | None = Field(default=None, max_length=80)


@app.post("/api/generate")
async def generate(body: GenerateBody):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "请先输入要生成的文字。")
    if body.steps not in (16, 32):
        raise HTTPException(400, "请选择快速或精细模式。")
    voice = get_voice(body.voice_id)
    if _synthesis_lock.locked():
        raise HTTPException(409, "正在生成上一段语音，请完成后再试。")
    async with _synthesis_lock:
        try:
            content = await asyncio.to_thread(engine.synthesize, text, voice, body.speed, body.steps)
            return store_generation(content, voice, text, body.speed, body.steps, (body.title or "").strip() or None)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(502, "语音生成失败，请确认本机语音引擎已启动。" + str(exc)[:180]) from exc


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), start: float = Form(0), seconds: float = Form(8)):
    try:
        content = await read_upload(file)
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            source, reference = Path(folder) / "source.audio", Path(folder) / "reference.wav"
            source.write_bytes(content)
            duration = await asyncio.to_thread(normalize_reference, source, reference, start, seconds)
            text = await asyncio.to_thread(recognize_reference, reference)
            if not text:
                raise HTTPException(400, "没有识别出清晰的人声，请调整片段或手动填写文字。")
            return {"text": text, "duration": duration}
    finally:
        await file.close()


@app.post("/api/voices/clone")
async def clone_voice(file: UploadFile = File(...), name: str = Form(...), text: str = Form(""),
                      start: float = Form(0), seconds: float = Form(8)):
    try:
        name = name.strip()
        if not 1 <= len(name) <= 40:
            raise HTTPException(400, "请给音色取一个1到40字的名字。")
        if len(text) > 2000:
            raise HTTPException(400, "参考文字太长，请只填写所选片段中说的话。")
        content = await read_upload(file)
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            source, reference = Path(folder) / "source.audio", Path(folder) / "reference.wav"
            source.write_bytes(content)
            duration = await asyncio.to_thread(normalize_reference, source, reference, start, seconds)
            reference_text = text.strip() or await asyncio.to_thread(recognize_reference, reference)
            if not reference_text:
                raise HTTPException(400, "没有识别出参考文字，请手动填写。")
            voice_id = "clone-" + uuid.uuid4().hex[:12]
            destination = VOICES / voice_id
            destination.mkdir()
            shutil.copy2(reference, destination / "ref_audio.wav")
            (destination / "ref_text.txt").write_text(reference_text, encoding="utf-8")
            (destination / "label.txt").write_text(name, encoding="utf-8")
            (destination / "omnivoice.txt").write_text("OmniVoice clone", encoding="utf-8")
            write_json(destination / "reference.json", {"duration": duration, "start": start,
                                                         "created_at": datetime.now(timezone.utc).isoformat()})
            current = settings()
            current["voice_id"] = voice_id
            write_json(SETTINGS, current)
            return {"id": voice_id, "name": name, "kind": "clone", "reference_text": reference_text,
                    "reference_seconds": duration}
    finally:
        await file.close()


@app.get("/api/history")
async def history():
    recover_restored_items()
    return [{**item, "saved": True} for item in read_json(HISTORY, [])]


class SaveWorkBody(BaseModel):
    audio_id: str
    title: str = Field(min_length=1, max_length=80)


@app.post("/api/previews/{audio_id}/discard")
async def discard_unsaved_preview(audio_id: str):
    checked_audio_id(audio_id)
    async with _audio_lock:
        return {"ok": True, "discarded": discard_preview(audio_id)}


@app.websocket("/api/previews/{audio_id}/session")
async def preview_session(websocket: WebSocket, audio_id: str):
    from urllib.parse import urlparse
    origin = websocket.headers.get("origin")
    if (not re.fullmatch(r"[a-f0-9]{32}", audio_id) or
            (origin and urlparse(origin).netloc != websocket.headers.get("host")) or
            not (DRAFTS / (audio_id + ".json")).is_file()):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    finally:
        async with _audio_lock:
            discard_preview(audio_id)


@app.post("/api/history")
async def save_work(body: SaveWorkBody):
    audio_id = checked_audio_id(body.audio_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "作品名称不能为空。")
    async with _audio_lock:
        with _disk_lock:
            items = read_json(HISTORY, [])
            existing = next((item for item in items if item["id"] == audio_id), None)
            if existing:
                return {**existing, "saved": True}
            item = read_json(DRAFTS / (audio_id + ".json"), None)
            if item is None or not (DRAFTS / (audio_id + ".wav")).is_file():
                raise HTTPException(404, "这段试听不存在，请重新生成。")
            item.update(title=title, saved=True)
            moved = []
            try:
                for ext in ("wav", "mp3"):
                    source, target = DRAFTS / (audio_id + "." + ext), AUDIO / (audio_id + "." + ext)
                    if source.exists():
                        source.rename(target)
                        moved.append((source, target))
                items.insert(0, item)
                write_json(HISTORY, items)
            except Exception:
                for source, target in reversed(moved):
                    target.rename(source)
                raise
            (DRAFTS / (audio_id + ".json")).unlink()
            return item


class VoiceEditBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    reference_text: str | None = Field(default=None, max_length=2000)


@app.patch("/api/voices/{voice_id}")
async def edit_voice(voice_id: str, body: VoiceEditBody):
    require_idle()
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "音色名称不能为空。")
    with _disk_lock:
        voice = get_voice(voice_id)
        folder = VOICES / voice_id
        if voice["kind"] == "clone":
            if body.reference_text is not None:
                if not body.reference_text.strip():
                    raise HTTPException(400, "参考文字不能为空，请填写录音里的原话。")
                (folder / "ref_text.txt").write_text(body.reference_text.strip(), encoding="utf-8")
            (folder / "label.txt").write_text(name, encoding="utf-8")
        else:
            write_json(folder / "design.json", {**voice["params"], "label": name})
    return next(item for item in voice_list() if item["id"] == voice_id)


@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    require_idle()
    with _disk_lock:
        voice = get_voice(voice_id)
        current = settings()
        previous = dict(current)
        def update_selection():
            if current.get("voice_id") == voice_id:
                remaining = voice_list()
                current["voice_id"] = remaining[0]["id"] if remaining else None
                write_json(SETTINGS, current)
        trash_id = archive_item("voice", voice_id, voice["name"], None,
                                [(VOICES / voice_id, "voice")], update_selection,
                                lambda: write_json(SETTINGS, previous))
    return {"ok": True, "trash_id": trash_id, "system_recycle_bin": True}


class WorkEditBody(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@app.patch("/api/history/{audio_id}")
async def edit_work(audio_id: str, body: WorkEditBody):
    checked_audio_id(audio_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "作品名称不能为空。")
    with _disk_lock:
        items = read_json(HISTORY, [])
        item = next((item for item in items if item["id"] == audio_id), None)
        if item is None:
            raise HTTPException(404, "这段作品不存在，请刷新列表。")
        item["title"] = title
        write_json(HISTORY, items)
        return item


@app.delete("/api/history/{audio_id}")
async def delete_work(audio_id: str):
    checked_audio_id(audio_id)
    require_idle()
    async with _audio_lock:
        with _disk_lock:
            items = read_json(HISTORY, [])
            item = next((item for item in items if item["id"] == audio_id), None)
            if item is None:
                raise HTTPException(404, "这段作品不存在，请刷新列表。")
            trash_id = archive_item("work", audio_id, item.get("title") or item["text"][:24], item,
                [(AUDIO / (audio_id + "." + ext), "audio." + ext) for ext in ("wav", "mp3")],
                lambda: write_json(HISTORY, [other for other in items if other["id"] != audio_id]),
                lambda: write_json(HISTORY, items))
    return {"ok": True, "trash_id": trash_id, "system_recycle_bin": True}


def focus_recycle_bin_window():
    """Activate the Explorer window requested by the application's button."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    titles = ("回收站 - 文件资源管理器", "回收站", "Recycle Bin - File Explorer", "Recycle Bin")
    for _ in range(30):
        handle = next((handle for title in titles if (handle := user32.FindWindowW(None, title))), None)
        if handle:
            foreground = user32.GetForegroundWindow()
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
            attached = False
            try:
                if foreground_thread and current_thread != foreground_thread:
                    attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
                user32.ShowWindow(handle, 9)  # SW_RESTORE, including an existing minimized window.
                user32.BringWindowToTop(handle)
                user32.SetForegroundWindow(handle)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            return user32.GetForegroundWindow() == handle
        time.sleep(0.1)
    return False


@app.post("/api/system-recycle-bin/open")
async def open_system_recycle_bin():
    if os.name != "nt":
        raise HTTPException(400, "当前系统不是 Windows。")
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1  # SW_SHOWNORMAL; do not inherit the server's hidden startup.
    try:
        subprocess.Popen([str(explorer), "shell:::{645FF040-5081-101B-9F08-00AA002F954E}"],
                         startupinfo=startup, close_fds=True)
    except OSError as exc:
        raise HTTPException(503, "无法启动 Windows 回收站，请从桌面打开。") from exc
    return {"ok": True, "foreground": await asyncio.to_thread(focus_recycle_bin_window)}


@app.post("/api/extract-audio")
async def extract_audio(file: UploadFile = File(...)):
    try:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".mpeg", ".mpg", ".ts"):
            raise HTTPException(400, "请选择 MP4、MOV、MKV、AVI 或 WebM 等视频文件。")
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            source, output = Path(directory) / ("source" + suffix), Path(directory) / "audio.mp3"
            size = 0
            with source.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_VIDEO:
                        raise HTTPException(413, "视频超过512MB，请先截取需要的部分。")
                    destination.write(chunk)
            if size == 0:
                raise HTTPException(400, "视频文件是空的。")
            try:
                result = await asyncio.to_thread(subprocess.run,
                    [ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-i", str(source),
                     "-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(output)],
                    capture_output=True, timeout=300)
            except subprocess.TimeoutExpired:
                raise HTTPException(400, "提取时间过长，请换一个较短的视频。")
            if result.returncode or not output.is_file() or output.stat().st_size < 100:
                raise HTTPException(400, "没有提取到音轨，请确认视频有声音且文件没有损坏。")
            desktop = desktop_directory()
            if not desktop.is_dir():
                raise HTTPException(500, "找不到桌面文件夹，无法保存音频。")
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(file.filename).stem).strip(" .")[:70] or "视频"
            stem = "视频-" + stem if stem.upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"} else stem
            for number in range(10000):
                name = stem + "-音频" + (f" ({number + 1})" if number else "") + ".mp3"
                destination = desktop / name
                try:
                    handle = destination.open("xb")
                except FileExistsError:
                    continue
                try:
                    with handle, output.open("rb") as audio:
                        shutil.copyfileobj(audio, handle)
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
                break
            else:
                raise HTTPException(409, "桌面同名文件过多，请重命名视频后重试。")
            extract_id = uuid.uuid4().hex
            write_json(EXTRACTED / (extract_id + ".json"), {"name": name, "path": str(destination)})
            return {"id": extract_id, "name": name, "path": str(destination), "size": destination.stat().st_size,
                    "url": "/api/extracted/" + extract_id}
    finally:
        await file.close()


@app.get("/api/extracted/{extract_id}")
async def extracted_audio(extract_id: str):
    checked_audio_id(extract_id)
    record = read_json(EXTRACTED / (extract_id + ".json"), {})
    path = Path(record.get("path", "")).resolve()
    if path.parent != desktop_directory().resolve() or not path.is_file():
        raise HTTPException(404, "桌面上的音频已移动或删除。")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/api/audio/{filename}")
async def audio_file(filename: str, download: bool = False):
    match = re.fullmatch(r"([a-f0-9]{32})\.(wav|mp3)", filename)
    if not match:
        raise HTTPException(404, "音频不存在。")
    audio_id, extension = match.groups()
    base = AUDIO if (AUDIO / (audio_id + ".wav")).is_file() else DRAFTS
    wav = base / (audio_id + ".wav")
    if not wav.is_file():
        raise HTTPException(404, "音频不存在。")
    path = base / filename
    if extension == "mp3":
        async with _audio_lock:
            if not wav.is_file():
                raise HTTPException(404, "音频不存在。")
            if not path.exists():
                result = await asyncio.to_thread(subprocess.run, [ffmpeg(), "-nostdin", "-y", "-loglevel", "error",
                            "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k", str(path)], capture_output=True, timeout=60)
                if result.returncode:
                    raise HTTPException(500, "MP3 转换失败，请先下载 WAV。")
    item = next((item for item in read_json(HISTORY, []) if item["id"] == audio_id), {})
    item = item or read_json(DRAFTS / (audio_id + ".json"), {})
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", item.get("title", "")).strip(" .")[:60]
    return FileResponse(path, media_type="audio/wav" if extension == "wav" else "audio/mpeg",
                        filename=((title or "voice-" + audio_id[:8]) + "." + extension) if download else None)


@app.get("/api/voices/{voice_id}/reference")
async def reference_audio(voice_id: str):
    voice = get_voice(voice_id)
    if voice["kind"] != "clone":
        raise HTTPException(404, "这个音色没有参考录音。")
    return FileResponse(voice["audio_path"], media_type="audio/wav")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
