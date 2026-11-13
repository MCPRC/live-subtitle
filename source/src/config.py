"""实时电影字幕：配置。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Config:
    # 音频
    device: str | None = None          # 回环设备名（模糊匹配），None=默认扬声器
    samplerate: int = 16000
    block_s: float = 0.1               # 每次读取的音频块长度（秒）

    # VAD
    frame_ms: int = 30
    vad_start_ratio: float = 2.6       # 语音阈值 = 噪声底 * ratio
    vad_min_rms: float = 0.004         # 绝对最小阈值，防静音误触发
    vad_hangover_s: float = 0.45       # 连续静音多久算一句话结束
    vad_min_speech_s: float = 0.8      # 太短的片段丢弃
    vad_max_segment_s: float = 8.0     # 单段最长，超过强制切分

    # ASR
    model_size: str = "small"          # tiny/base/small/medium
    asr_device: str = "cpu"            # cpu / cuda
    compute_type: str = "int8"         # int8 / float32 / float16
    language: str | None = None        # None=自动检测；如 "en"、"ja"
    model_dir: str = "models"

    # 翻译
    translator: str = "auto"           # auto / opus / nllb / none
    target_lang: str = "zh"            # 目标语言（google 用 zh-CN；nllb 用 zho_Hans）
    nllb_model_dir: str = "models/nllb-200-distilled-600M-ct2-int8"
    nllb_src_lang: str = "eng_Latn"
    opus_model_dir: str = "models/opus-mt-en-zh-ct2"
    m2m_model_dir: str = "models/m2m100-418m-ct2-int8"

    # 字幕窗
    overlay: bool = True
    font_size: int = 26
    max_lines: int = 3
    opacity: float = 0.78
    clear_after: float = 6.0           # 秒；0=永不自动清空

    # 其他
    show_source: bool = True           # 字幕窗同时显示原文
    verbose: bool = True
