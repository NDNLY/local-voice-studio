# 声匣 · 本地语音工作室

<img src="assets/shengxia.png" alt="声匣" width="128">

基于 OmniVoice 的 Windows 桌面语音工具，支持声音克隆和文字转语音，合成与识别均在本机运行。

## 功能

- 文字转语音，内置四种音色，支持语速与精度调整。
- 参考录音克隆，支持片段截取和本地文字识别。
- 音色与作品的编辑、删除和回收站还原。
- 音频试听、手动保存、WAV / MP3 导出。
- 视频转 MP3，保存到桌面。

## 环境

- Windows 10 / 11（64 位）、WebView2 Runtime。
- Python 3.12、Python 3.11 和 Windows `py` 启动器。
- NVIDIA 显卡及支持 PyTorch CUDA 13.0 的驱动。

## 安装

```powershell
git clone https://github.com/NDNLY/local-voice-studio.git
cd local-voice-studio
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

安装脚本自动创建环境、安装依赖并下载模型。完成后，双击 `声匣.exe` 或 `启动语音工作室.cmd`。

详细操作见 [使用说明](使用说明.md)。音色、作品和设置保存在 `data/`。

## 开发

从源码启动：

```powershell
.\.venv\Scripts\pythonw.exe .\desktop.py
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

打包桌面程序，输出到 `dist/声匣.exe`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

## 主要组件

[OmniVoice](https://github.com/k2-fsa/OmniVoice) · [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [pywebview](https://github.com/r0x0r/pywebview) · [FastAPI](https://github.com/fastapi/fastapi) · [FFmpeg](https://ffmpeg.org/)
