"""Native Windows entry point. Model and user data stay beside the executable."""
from __future__ import annotations

import html
import logging
import os
import subprocess
import sys
import threading

import webview

from launcher import ROOT, ensure_services

LOADING = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<style>body{margin:0;background:#f5f5ef;color:#203b30;font:16px 'Microsoft YaHei',sans-serif;
display:grid;place-items:center;height:100vh}.box{max-width:520px;padding:48px;text-align:center}
h1{font-size:42px;letter-spacing:6px;margin:0 0 20px}p{color:#6b786d;line-height:1.9}
.bar{width:120px;height:4px;background:#dce2d6;margin:32px auto;overflow:hidden;border-radius:4px}
.bar:after{content:'';display:block;height:100%;width:45%;background:#2c5d46;animation:slide 1.4s infinite}
@keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(330%)}}</style>
<div class="box"><h1>声匣</h1><p>本地语音工作室</p><div class="bar"></div>
<p>正在准备你的声音工作室…<br>首次加载模型需要稍等片刻。</p></div></html>"""


def main():
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    # A windowed executable has no terminal streams.
    stream = (logs / "desktop.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    stopped = threading.Event()
    owned = []
    lock = threading.Lock()

    def stop_process(process):
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process.terminate()

    def remember(process):
        with lock:
            owned.append(process)
            if stopped.is_set():
                stop_process(process)

    def cleanup():
        stopped.set()
        with lock:
            for process in reversed(owned):
                stop_process(process)
            owned.clear()

    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window("声匣 · 本地语音工作室", html=LOADING,
                                   width=1380, height=920, min_size=(960, 680),
                                   background_color="#f5f5ef", text_select=True)
    window.events.closed += cleanup

    def prepare():
        try:
            url = ensure_services(remember, stopped)
            if not stopped.is_set():
                window.load_url(url)
        except Exception as error:
            logging.exception("Desktop startup failed")
            if not stopped.is_set():
                message = html.escape(str(error))
                window.load_html(LOADING.split('<div class="box">')[0] +
                    '<div class="box"><h1>暂时没能启动</h1><p>请关闭窗口后重试。' +
                    '<br>详细信息保存在本目录 logs/desktop.log。</p><p>' + message + '</p></div></html>')
                cleanup()

    try:
        webview.start(prepare, gui="edgechromium", debug=False,
                      private_mode=False, storage_path=str(ROOT / "data" / "desktop-cache"))
    finally:
        cleanup()


if __name__ == "__main__":
    main()
