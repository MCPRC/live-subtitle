# live-subtitle

Windows 本地实时英语转简体中文字幕工具的源码快照。

基于 [TokamakCC/live-subtitle](https://github.com/TokamakCC/whisper-real-time-subtitles-translation-pyqt6-ctranslate2-windows) 的本地修改版。上游来源提交为 `d0c8b03`，保留原 MIT 许可与版权声明。

## 功能

- WASAPI 回环采集系统播放音频，Faster-Whisper small INT8 识别、Opus-MT EN→ZH INT8 本地翻译。
- PyQt6 双语悬浮字幕、侧边历史、自动跟随、拖动、点击穿透、独立背景/文字透明度。
- CPU / NVIDIA CUDA 选择与失败回退。
- 独立环境补齐界面：固定依赖与模型清单、仅补齐缺项、模型导入、SHA-256 校验、可取消续传与本地推理自检。目前只验证英语→简体中文。

## 仓库内容与边界

保留当前 `source/src`、补齐/启动/诊断/模型准备工具、模型元数据清单、依赖锁、两项补齐测试以及许可证。模型权重、Python 运行时、虚拟环境、缓存、日志、截图、本机配置、EXE 和 DLL 均不上传。这里是源码备份，不是下载即用的二进制发行包。

字幕推理不调用在线翻译 API，也不上传音频。补齐过程需要访问 Hugging Face、PyPI 和 PyTorch 官方 CPU 包索引。模型及相关暂存限制为 4 GB，运行组件不计入该模型限制。

## 开发与构建说明

目标环境为 Windows x64、Python 3.11。`requirements.lock.txt` 记录现有环境的精确版本，其中 `torch` CPU 包来自 `https://download.pytorch.org/whl/cpu`，NVIDIA 包为可选 GPU 加速组件，不应将全部锁文件不加区分地当成 CPU 最小依赖。补齐工具使用 `tools/environment-manifest.json` 中的 CPU 基线依赖和模型版本。

源码入口：`tools/environment_gui.py`（补齐界面）、`tools/launcher.py`（字幕启动器）。已有项目环境下的构建脚本为 `tools/build_environment.ps1`，PyInstaller 配置为 `tools/environment.spec` 和 `tools/启动字幕.spec`。环境补齐 EXE 必须与其 `environment_internal` 目录一起分发。

当前构建不是全新机器的一键自举：脚本依赖项目已有 venv、构建依赖、目录和旧启动器备份条件；字幕启动器 spec 仍保留原部署目录的绝对路径。换目录后需要先调整该 spec，准备运行时与构建目录。此次上传未修改产品源码，也未声称完成干净克隆重建测试。请不要直接在正在使用的部署目录盲目执行构建覆盖。

补齐界面打包后可不依赖项目 venv 打开，但实际推理/转换仍需要项目 `venv` 或 `runtime/tools` 中的 Python 3.11；两者均不存在时会明确报错。暂不自动安装 GPU 驱动或 CUDA 组件。

## 测试范围

`tests/environment_tests.py` 使用隔离夹具与本地 HTTP 服务器测试补齐逻辑；`tests/environment_full_repair_test.py` 需要已有源权重和运行环境，验证离线转换恢复，不能视作全新电脑安装测试。此前开发阶段记录了本机 EXE 启动/检查/退出、现有模型导入及完整环境复用测试；本次 GitHub 上传只核查源码和文件范围，未重新运行程序或测试。

## 许可

原项目源码 MIT 许可见 LICENSE。本仓库不包含第三方模型权重或运行库。依赖与模型分别遵循自身许可；特别是 PyQt6 使用 GPLv3 或商业许可，不能把原项目 MIT 许可当作打包第三方组件的许可。发布二进制前需独立审查对应许可与分发义务。
