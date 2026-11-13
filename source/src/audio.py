"""WASAPI shared-mode capture, downmix and anti-aliased resampling."""
from __future__ import annotations
import numpy as np
import soundcard as sc
from scipy.signal import resample_poly

def list_loopback_devices():
    return [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]

def resolve_loopback(name=None):
    devices=list_loopback_devices()
    if not devices: raise RuntimeError('No WASAPI loopback devices')
    if name:
        matches=[d for d in devices if name.lower() in d.name.lower()]
        if len(matches)!=1: raise RuntimeError('Device must uniquely match: '+str([d.name for d in devices]))
        return matches[0]
    speaker=sc.default_speaker()
    return sc.get_microphone(id=speaker.id, include_loopback=True)

class LoopbackRecorder:
    def __init__(self, device, samplerate=16000, block_s=.1):
        if samplerate!=16000: raise ValueError('ASR requires 16 kHz')
        self.device=device
        self.block_frames=max(480,int(48000*block_s)//3*3)
        self._rec=None
    def __enter__(self):
        # WASAPI shared mode converts the device mix rate to 48 kHz.
        # Capture every channel; mono WASAPI capture is unreliable on some devices.
        self._rec=self.device.recorder(samplerate=48000)
        self._rec.__enter__()
        return self
    def __exit__(self,*exc):
        if self._rec: self._rec.__exit__(*exc)
    def chunks(self):
        while True:
            data=self._rec.record(numframes=self.block_frames)
            if data is None or not data.size: continue
            mono=np.mean(data,axis=1) if data.ndim==2 else data
            yield resample_poly(mono,1,3).astype(np.float32)
