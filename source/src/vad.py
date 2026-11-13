"""极简能量 VAD：把连续音频切成语义片段。

不依赖任何模型，先用噪声底自适应阈值做初步断句；
以后可替换成 Silero VAD（onnxruntime），接口保持不变。
"""
from __future__ import annotations

from collections import deque

import numpy as np


class EnergyVAD:
    def __init__(
        self,
        samplerate: int = 16000,
        frame_ms: int = 30,
        start_ratio: float = 2.6,
        min_rms: float = 0.004,
        hangover_s: float = 0.45,
        min_speech_s: float = 0.8,
        max_segment_s: float = 8.0,
        preroll_s: float = 0.3,
    ):
        self.samplerate = samplerate
        self.frame_len = max(1, int(samplerate * frame_ms / 1000))
        self.start_ratio = start_ratio
        self.min_rms = min_rms
        self.hangover_frames = max(1, int(hangover_s * 1000 / frame_ms))
        self.min_speech_frames = max(1, int(min_speech_s * 1000 / frame_ms))
        self.max_segment_frames = max(1, int(max_segment_s * 1000 / frame_ms))
        self.preroll = deque(maxlen=max(1, int(preroll_s * 1000 / frame_ms)))

        self._buf = np.empty(0, dtype=np.float32)
        self._noise = 0.002
        self._in_speech = False
        self._frames: list[np.ndarray] = []
        self._silence = 0

    # ------------------------------------------------------------------
    def push(self, chunk: np.ndarray) -> list[np.ndarray]:
        """输入任意长度音频块，返回已完成的语音片段列表。"""
        if chunk.size:
            self._buf = np.concatenate([self._buf, chunk.astype(np.float32, copy=False)])

        finished: list[np.ndarray] = []
        while self._buf.size >= self.frame_len:
            frame = self._buf[: self.frame_len]
            self._buf = self._buf[self.frame_len:]
            rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
            threshold = max(self.min_rms, self._noise * self.start_ratio)
            speech = rms > threshold

            if not self._in_speech:
                if speech:
                    self._in_speech = True
                    self._frames = list(self.preroll)
                    self.preroll.clear()
                    self._frames.append(frame)
                    self._silence = 0
                else:
                    self.preroll.append(frame)
                    # 噪声底缓慢跟随（只在非语音段更新）
                    self._noise = 0.95 * self._noise + 0.05 * min(rms, 0.05)
                continue

            self._frames.append(frame)
            if speech:
                self._silence = 0
            else:
                self._silence += 1

            seg_frames = len(self._frames)
            if self._silence >= self.hangover_frames and seg_frames >= self.min_speech_frames:
                finished.append(self._trim_and_concat())
                self._reset()
            elif seg_frames >= self.max_segment_frames:
                finished.append(self._trim_and_concat())
                self._reset()
        return finished

    def flush(self) -> list[np.ndarray]:
        """流结束时把未完成的片段吐出来。"""
        out: list[np.ndarray] = []
        if self._in_speech and len(self._frames) >= self.min_speech_frames:
            out.append(self._trim_and_concat())
        self._reset()
        self._buf = np.empty(0, dtype=np.float32)
        return out

    # ------------------------------------------------------------------
    def _trim_and_concat(self) -> np.ndarray:
        frames = self._frames
        # 去掉尾部的静音帧
        keep = len(frames)
        while keep > 0 and self._silence > 0 and keep > len(frames) - self._silence:
            keep -= 1
        audio = np.concatenate(frames[:keep]) if keep else np.concatenate(frames)
        return audio.astype(np.float32, copy=False)

    def _reset(self) -> None:
        self._in_speech = False
        self._frames = []
        self._silence = 0
        self.preroll.clear()
