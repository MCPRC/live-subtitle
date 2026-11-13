"""Strictly local multilingual Faster-Whisper backend."""
from dataclasses import dataclass
from pathlib import Path
import time
@dataclass
class AsrResult:
    text:str
    language:str
    probability:float
    duration_s:float
class FasterWhisperASR:
    def __init__(self,model_size='small',device='cpu',compute_type='int8',model_dir='models',language='auto'):
        path=Path(model_size)
        if not path.is_dir(): path=Path(model_dir)/'whisper-small-int8'
        for name in ('model.bin','config.json','tokenizer.json'):
            if not (path/name).is_file(): raise FileNotFoundError(f'Missing local ASR model file: {path/name}')
        self.path=path; self.language=language; self.model=None
        self._auto_language=None; self._auto_detected_at=0.; self._auto_segments=0
        self.requested_device=None; self.device='cpu'; self.verified=False; self.fallback_reason=''
        self.set_device(device)
    def _load(self,device):
        from backend import configure_cuda_dlls
        configure_cuda_dlls()
        from faster_whisper import WhisperModel
        import gc
        self.verified=False; self.model=None; gc.collect()
        self.model=WhisperModel(str(self.path),device=device,compute_type='int8_float16' if device=='cuda' else 'int8',local_files_only=True,cpu_threads=6,num_workers=1)
        self.device=device; self.verified=False
    def set_device(self,device):
        if device not in ('cpu','cuda'): raise ValueError('Unsupported compute device')
        if device==self.requested_device: return
        self.requested_device=device; self.fallback_reason=''
        try:self._load(device)
        except Exception as exc:
            if device!='cuda':raise
            self.fallback_reason='CUDA initialization failed: '+str(exc)
            self._load('cpu')
    def _infer(self,audio,language,task):
        segments,info=self.model.transcribe(audio,language=language,task=task,beam_size=1,best_of=1,vad_filter=False,condition_on_previous_text=False,temperature=0.,no_speech_threshold=.6,compression_ratio_threshold=2.4)
        text=''.join(seg.text for seg in segments).strip()
        self.verified=True
        return text,info
    def transcribe(self,audio,language=None,task='transcribe'):
        if task not in ('transcribe','translate'): raise ValueError('Invalid ASR task')
        language=self.language if language is None else language
        automatic=language in ('auto','')
        now=time.perf_counter()
        detect=automatic and (self._auto_language is None or now-self._auto_detected_at>=8.0 or self._auto_segments>=3)
        if automatic:
            language=None if detect else self._auto_language
        else:
            # A manual source selection resets auto state for the next switch.
            self._auto_language=None; self._auto_segments=0
        start=time.perf_counter()
        try:text,info=self._infer(audio,language,task)
        except Exception as exc:
            if self.device!='cuda':raise
            self.fallback_reason='CUDA inference failed: '+str(exc)
            self._load('cpu')
            text,info=self._infer(audio,language,task)
        if automatic:
            if detect:
                self._auto_detected_at=now; self._auto_segments=0
                self._auto_language=info.language if float(info.language_probability)>=.75 else None
            else:
                self._auto_segments+=1
        return AsrResult(text,info.language,float(info.language_probability),time.perf_counter()-start)
