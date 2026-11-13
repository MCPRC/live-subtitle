"""Local-only Opus-MT EN to simplified Chinese. No online fallback."""
from pathlib import Path
class OpusTranslator:
    name='opus'
    def __init__(self,model_dir,device='cpu'):
        import sentencepiece as spm
        from opencc import OpenCC
        root=Path(model_dir)
        for name in ('model.bin','config.json','source.spm','target.spm'):
            if not (root/name).is_file(): raise FileNotFoundError(f'Missing local MT file: {root/name}')
        self.root=root; self._tr=None; self.requested_device=None; self.device='cpu'; self.verified=False; self.fallback_reason=''
        self.set_device(device)
        self._src=spm.SentencePieceProcessor(model_file=str(root/'source.spm'))
        self._tgt=spm.SentencePieceProcessor(model_file=str(root/'target.spm'))
        self._simplify=OpenCC('t2s')
    def _load(self,device):
        from backend import configure_cuda_dlls
        configure_cuda_dlls()
        import ctranslate2, gc
        self.verified=False; self._tr=None; gc.collect()
        self._tr=ctranslate2.Translator(str(self.root),device=device,compute_type='int8_float16' if device=='cuda' else 'int8',inter_threads=1,intra_threads=2)
        self.device=device; self.verified=False
    def set_device(self,device):
        if device not in ('cpu','cuda'): raise ValueError('Unsupported compute device')
        if device==self.requested_device:return
        self.requested_device=device; self.fallback_reason=''
        try:self._load(device)
        except Exception as exc:
            if device!='cuda':raise
            self.fallback_reason='CUDA initialization failed: '+str(exc)
            self._load('cpu')
    def translate(self,text,src_lang='en'):
        if not text.strip(): return ''
        # Marian requires an explicit end-of-sentence marker.
        tokens=self._src.encode(text,out_type=str)+['</s>']
        try:
            result=self._tr.translate_batch([tokens],beam_size=2,max_decoding_length=256,repetition_penalty=1.1)
        except Exception as exc:
            if self.device!='cuda':raise
            self.fallback_reason='CUDA inference failed: '+str(exc)
            self._load('cpu')
            result=self._tr.translate_batch([tokens],beam_size=2,max_decoding_length=256,repetition_penalty=1.1)
        self.verified=True
        return self._simplify.convert(self._tgt.decode(result[0].hypotheses[0]).strip())
    def warmup(self): self.translate('Hello.')

def build_translator(kind='opus',target_lang='zh',opus_model_dir='',**kwargs):
    if kind!='opus': raise ValueError('This build permits only local Opus-MT translation')
    return OpusTranslator(opus_model_dir,device=kwargs.get('device','cpu'))
