# 声匣 · 本地语音工作室

Windows 桌面语音工具，使用 OmniVoice 在本机完成声音克隆和文字转语音。不需要 Vidu、DeepSeek、API Key 或平台积分。

<img src="assets/shengxia-rabbit.png" alt="声匣小兔图标" width="160">

## 功能

- 中文文字转语音，内置四种设计音色，可调整语速与生成精度。
- 上传参考录音，截取 3–15 秒片段克隆声音；推荐使用清晰、单人、无背景音乐的 3–10 秒录音。
- 在本机识别参考片段原话，也可以手动填写、校正。
- 编辑音色名称、参考文字；编辑作品名称，载入作品文字重新生成。
- WAV、MP3 试听和下载；试听满意后手动保存作品。
- 提取视频完整音轨为 MP3，直接保存到 Windows 桌面，同名不覆盖。
- 删除音色、作品时移到 Windows 系统回收站；还原文件夹后可重新恢复列表。
- pywebview / WebView2 独立窗口；未保存试听在替换、关闭时自动清理。

## 仓库内容

本仓库包含完整应用源码、现有 Windows 桌面启动程序 `声匣.exe`、兔子图标、四种工厂音色参数、依赖清单、模型版本与校验值、安装及重新打包脚本和自动化测试。

模型约 3.7 GB，安装脚本从模型发布方下载，不存入 Git。Python 环境、缓存、日志、个人克隆录音和已生成作品也不提交。`声匣.exe` 是桌面入口，仍需要相邻源码、环境和模型；不能只复制这个 EXE 使用。

## 环境要求

- Windows 10 / 11（64 位），Microsoft Edge WebView2 Runtime。
- Python **3.12**（界面、后端）、Python **3.11**（模型）及 Windows `py` 启动器。
- 支持当前 PyTorch CUDA 13.0 构建的 NVIDIA 显卡与驱动。当前启动脚本固定使用 CUDA；其他硬件尚未验证。
- 首次安装需要联网下载 Python 依赖与模型，预留足够磁盘空间；完成后合成、识别在本机运行。

当前依赖版本与 CUDA 组合来自原运行环境。显存、速度和兼容性取决于具体硬件；仓库测试不会代替真实 GPU 合成验证。

## 安装与启动

在 PowerShell 中执行：

```powershell
git clone https://github.com/NDNLY/local-voice-studio.git
cd local-voice-studio
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

安装脚本会创建两个独立虚拟环境，安装依赖，初始化工厂音色，然后下载固定版本的 OmniVoice（含音频 tokenizer）和 faster-whisper-small，并核验大权重 SHA-256。已有同名音色和设置不会被覆盖。

完成后双击 `启动语音工作室.cmd` 或 `声匣.exe`。也可从源码打开窗口：

```powershell
.\.venv\Scripts\pythonw.exe .\desktop.py
```

仅调试页面时运行：

```powershell
.\.venv\Scripts\python.exe .\launcher.py
```

默认本机端口：工作室 `8788`，OmniVoice `9877`。桌面启动器会复用已运行且匹配的服务；关闭窗口只结束本次启动器新建的服务。

模型下载失败可以重新运行：

```powershell
.\.tts-venv\Scripts\python.exe .\scripts\prepare_install.py --models-only
```

已经手动备好模型时，可执行 `setup.ps1 -SkipModels`，随后将模型放到下述目录；运行引擎使用离线模式，文件必须齐全。

```text
models/
  OmniVoice/
    config.json
    model.safetensors
    tokenizer.json
    tokenizer_config.json
    chat_template.jinja
    audio_tokenizer/       # 完整 tokenizer 文件目录
  faster-whisper-small/
    config.json
    model.bin
    tokenizer.json
    vocabulary.txt
```

音频转换默认使用 `imageio-ffmpeg` 自带的 FFmpeg；如果存在 `.tools/ffmpeg.exe`，优先使用该文件。

## 使用与数据

详见 [使用说明](使用说明.md)。

| 路径 | 内容 |
| --- | --- |
| `app.py` | FastAPI 后端、音色与作品管理、转码、回收站、临时缓存 |
| `engine_client.py` | OmniVoice Gradio API 适配 |
| `launcher.py` / `desktop.py` | 服务管理 / 原生窗口入口 |
| `run_engine.py` | 本地 CUDA 模型服务 |
| `static/` | 工作室界面 |
| `presets/voices/` | 四种非个人工厂音色参数 |
| `scripts/` | 安装、模型下载、桌面打包 |
| `models.lock.json` | 模型仓库、固定版本与权重校验值 |
| `tests/` | 使用临时目录和模拟合成的测试 |
| `data/voices/` | 本机个人音色与参考录音（不上传） |
| `data/audio/` | 手动保存的作品（不上传） |
| `data/previews/` | 未保存试听缓存（不上传） |
| `models/` / `logs/` | 模型 / 本机日志（不上传） |

从 GitHub 重新克隆会得到初始工厂音色；个人音色与作品需要另外备份 `data/`。当前电脑的原始数据不受上传影响。

## 测试

安装应用依赖后运行，不需要 GPU 或下载模型：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时音频、视频和模拟回收站，不操作真实作品；覆盖保存与撤销、编辑删除与还原、失败回退、音频导出、试听缓存连接和安装预设。模型合成在测试中模拟。

## 重新打包桌面程序

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-desktop.ps1
```

生成 `dist/声匣.exe`，使用仓库内的兔子图标。关闭原应用后，将新 EXE 复制到项目根目录使用。相邻目录与环境仍必须保留；此操作不会生成包含模型的单文件安装包。

## 表达能力与第三方组件

OmniVoice 支持部分笑声、叹气等标签，例如 `[laughter]`、`[sigh]`，效果随文字和音色变化。当前界面没有精确的开心、悲伤或生气强度控制。

- [OmniVoice](https://github.com/k2-fsa/OmniVoice) / [模型](https://huggingface.co/k2-fsa/OmniVoice)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [small 模型](https://huggingface.co/Systran/faster-whisper-small)
- [pywebview](https://github.com/r0x0r/pywebview)
- [FastAPI](https://github.com/fastapi/fastapi)、[FFmpeg](https://ffmpeg.org/)、[Send2Trash](https://github.com/arsenetar/send2trash)

第三方软件和模型各自适用其发布方许可证，本仓库不重新授权第三方权重。仓库尚未为自有应用源码指定开源许可证。
