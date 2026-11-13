"""Local real-time subtitles. Audio and transcripts remain in memory only."""
from __future__ import annotations
import argparse, json, os, queue, re, sys, threading, time
from collections import deque
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HOME']=str(ROOT/'cache'/'huggingface')
os.environ['TEMP']=os.environ['TMP']=str(ROOT/'temp')
import numpy as np
from audio import LoopbackRecorder, resolve_loopback, list_loopback_devices
from vad import EnergyVAD
from asr import FasterWhisperASR
from translate import OpusTranslator
from single_instance import SingleInstance
STOP=threading.Event()

def segmentation(speed):
    return {'original':(3.2,.35),'normal':(2.0,.25),'fast':(1.6,.25),'balanced':(2.4,.25)}[speed]

class Pipeline:
    def __init__(self,args,overlay=None):
        self.args=args; self.overlay=overlay
        self.audio_q=queue.Queue(maxsize=2); self.mt_q=queue.Queue(maxsize=3)
        self.threads=[]; self.lock=threading.RLock()
        self.settings={'source_language':getattr(args,'language','en'),'target_language':getattr(args,'target_lang','zh'),'speed':getattr(args,'speed','original'),'layout_mode':getattr(args,'layout_mode','sidebar')}
        self.settings['compute_device']=getattr(args,'compute_device',None) or getattr(args,'asr_device','cpu')
        self._last_backend=None
        self.settings_version=0; self.entry_id=0
        self.metrics={'audio_segments_dropped':0,'mt_segments_dropped':0,'capture_blocks':0,'max_rms':0.,'asr_count':0,'mt_count':0,'errors':0}
        self.recent=deque(maxlen=1000)
        self.stop_file=ROOT/'control'/'stop.request'
        self.stop_file.parent.mkdir(exist_ok=True)
        self.stop_file.unlink(missing_ok=True)
        self.started=time.perf_counter(); self.ready=False
    def snapshot(self):
        with self.lock: return dict(self.settings),self.settings_version
    def update_settings(self,changes):
        if not isinstance(changes,dict): return
        from faster_whisper.tokenizer import _LANGUAGE_CODES
        allowed={'source_language':set(_LANGUAGE_CODES)|{'auto'},'target_language':{'zh','en','source'},'compute_device':{'cpu','cuda'},'speed':{'original','normal','fast','balanced'},'layout_mode':{'sidebar','overlay'}}
        accepted={k:v for k,v in changes.items() if k in allowed and v in allowed[k]}
        with self.lock:
            changed=any(self.settings.get(k)!=v for k,v in accepted.items())
            self.settings.update(accepted)
            if changed: self.settings_version+=1
            try:
                path=ROOT/'settings.json'
                saved=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
                saved.update(changes); saved.update(self.settings)
                temporary=ROOT/'settings.json.tmp'
                temporary.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
                temporary.replace(path)
            except Exception as exc: self.event(event='settings_save_error',error=str(exc))
    def publish(self,entry,src,dst,language,status,version):
        with self.lock:
            if version!=self.settings_version or STOP.is_set(): return
            if self.overlay is not None:
                self.overlay.update_entry(str(entry),src,dst,language,status)
    def backend_status(self):
        asr=getattr(self,'asr',None); mt=getattr(self,'mt',None)
        if asr is None or mt is None:return
        state=(asr.device,mt.device,asr.verified,mt.verified,asr.fallback_reason,mt.fallback_reason)
        if state==self._last_backend:return
        self._last_backend=state
        notes=[]
        for name,backend in (('ASR',asr),('MT',mt)):
            if backend.fallback_reason:notes.append(name+' 已回退 CPU: '+backend.fallback_reason)
            elif not backend.verified:notes.append(name+' 等待实际推理验证')
        status='；'.join(notes) or 'ASR 和 MT 均已实际推理验证'
        self.event(event='backend',asr_device=asr.device,mt_device=mt.device,asr_verified=asr.verified,mt_verified=mt.verified,status=status)
        if self.overlay is not None:self.overlay.update_backend(asr.device,mt.device,status)
    def sync_backend(self,backend):
        cfg,version=self.snapshot()
        if backend.requested_device!=cfg['compute_device']:
            if self.overlay is not None:
                self.overlay.update_backend(getattr(self.asr,'device','cpu'),getattr(self.mt,'device','cpu'),'正在切换计算设备…')
            try:backend.set_device(cfg['compute_device'])
            except Exception:
                backend.requested_device=None
                raise
            self.backend_status()
    def event(self,**data):
        row={'elapsed_s':round(time.perf_counter()-self.started,3),**data}
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def put_latest(self,q,item,key):
        try: q.put_nowait(item)
        except queue.Full:
            try: q.get_nowait(); self.metrics[key]+=1
            except queue.Empty: pass
            try: q.put_nowait(item)
            except queue.Full: self.metrics[key]+=1
    def start(self):
        t=threading.Thread(target=self.initialize,name='models',daemon=True)
        self.threads.append(t); t.start()
    def initialize(self):
        try:
            device=self.snapshot()[0]['compute_device']
            self.asr=FasterWhisperASR(str(self.args.model),device=device,compute_type='int8',language='auto')
            self.mt=OpusTranslator(str(self.args.opus_dir),device=device)
            self.asr.transcribe(np.zeros(16000,dtype=np.float32),language='en'); self.mt.warmup()
            self.ready=True
            self.backend_status()
            self.event(event='models_ready',asr_device=self.asr.device)
            for fn,name in ((self.capture,'capture'),(self.recognize,'asr'),(self.translate,'mt'),(self.monitor,'metrics')):
                t=threading.Thread(target=fn,name=name,daemon=True); self.threads.append(t); t.start()
        except Exception as exc:
            self.event(event='initialization_failed',error=str(exc)); STOP.set()
    def capture(self):
        retries=0
        while not STOP.is_set() and retries<3:
            vad=EnergyVAD(max_segment_s=3.2,min_speech_s=.4,hangover_s=.35)
            onset=None
            try:
                device=resolve_loopback(self.args.device)
                self.event(event='capture_ready',device=device.name)
                with LoopbackRecorder(device,16000,.1) as recorder:
                    for chunk in recorder.chunks():
                        if STOP.is_set(): break
                        end=time.perf_counter()
                        self.metrics['capture_blocks']+=1
                        rms=float(np.sqrt(np.mean(chunk*chunk)))
                        self.metrics['max_rms']=max(self.metrics['max_rms'],rms)
                        was=vad._in_speech
                        cfg,version=self.snapshot()
                        if not was:
                            seconds,hangover=segmentation(cfg['speed'])
                            vad.max_segment_frames=max(1,int(seconds*1000/30))
                            vad.hangover_frames=max(1,int(hangover*1000/30))
                        segments=vad.push(chunk)
                        if not was and (vad._in_speech or segments):
                            # Capture-return timestamp minus this block and VAD preroll.
                            # Hardware buffering is not included; documented estimate.
                            onset=end-len(chunk)/16000-.3
                        for seg in segments:
                            begin=onset if onset is not None else end-len(seg)/16000
                            self.put_latest(self.audio_q,(seg,begin,end,cfg,version),'audio_segments_dropped')
                            onset=end if vad._in_speech else None
                break
            except Exception as exc:
                retries+=1; self.metrics['errors']+=1
                self.event(event='capture_retry',attempt=retries,error=str(exc))
                STOP.wait(1)
        if retries>=3: STOP.set()
    def recognize(self):
        last=''; last_version=-1; last_audio_end=-1.
        while not STOP.is_set():
            try:self.sync_backend(self.asr)
            except Exception as exc:
                self.event(event='asr_backend_error',error=str(exc));STOP.wait(1);continue
            try: audio,onset,seg_end,cfg,version=self.audio_q.get(timeout=.2)
            except queue.Empty: continue
            if time.perf_counter()-seg_end>5 or version!=self.snapshot()[1]:
                self.metrics['audio_segments_dropped']+=1; continue
            try:
                target=cfg['target_language']
                result=self.asr.transcribe(audio,language=cfg['source_language'],task='translate' if target=='en' else 'transcribe')
                self.backend_status()
                if version!=self.snapshot()[1]: continue
                text=result.text.strip(); language=result.language
                key=re.sub(r'\W+',' ',text.lower()).strip()
                if not key or (key==last and last_version==version and seg_end==last_audio_end): continue
                if len(text)>12 and len(set(text))<=4: continue
                last=key; last_version=version; last_audio_end=seg_end
                self.metrics['asr_count']+=1; self.entry_id+=1; entry=self.entry_id
                elapsed=time.perf_counter()-onset
                self.event(event='asr',asr_s=round(result.duration_s,4),capture_to_source_s=round(elapsed,4),detected_language=language,language_probability=round(result.probability,3),target=target)
                if target=='en':
                    self.publish(entry,'',text,language,'Whisper → English；为降低延迟不另行识别原文',version)
                elif target=='source':
                    self.publish(entry,text,'',language,'仅识别原文',version)
                elif cfg['source_language']=='auto' and result.probability<.65:
                    self.publish(entry,text,'',language,'语言判断置信度低，请手选源语言以稳定翻译',version)
                elif language=='zh':
                    from opencc import OpenCC
                    self.publish(entry,text,OpenCC('t2s').convert(text),language,'简体中文',version)
                elif language!='en':
                    self.publish(entry,text,'',language,'未安装此源语言 → 中文模型；可切换英语目标或仅原文',version)
                else:
                    if cfg['speed']!='original':
                        self.publish(entry,text,'',language,'翻译中…',version)
                    self.put_latest(self.mt_q,(entry,text,onset,seg_end,result.duration_s,language,cfg,version),'mt_segments_dropped')
            except Exception as exc:
                self.metrics['errors']+=1; self.event(event='asr_error',error=str(exc))
    def translate(self):
        pending=None
        while not STOP.is_set():
            try:self.sync_backend(self.mt)
            except Exception as exc:
                self.event(event='mt_backend_error',error=str(exc));STOP.wait(1);continue
            try:
                item=pending if pending is not None else self.mt_q.get(timeout=.2)
                pending=None
                entry,text,onset,seg_end,asr_s,language,cfg,version=item
            except queue.Empty: continue
            if version!=self.snapshot()[1]: continue
            if time.perf_counter()-seg_end>8:
                self.metrics['mt_segments_dropped']+=1
                self.publish(entry,text,'',language,'为保持实时性已跳过过期翻译',version); continue
            if cfg['speed']=='original':
                # Restore the original brief adjacent-fragment merge. Only this
                # mode defers display, so consuming the second item makes one card.
                if not text.rstrip(chr(34)+chr(39)).endswith(('.', '!', '?')) and len(text)<280:
                    try:
                        nxt=self.mt_q.get(timeout=.25)
                        if nxt[7]==version and nxt[6]==cfg and nxt[5]==language:
                            text+=' '+nxt[1]; seg_end=nxt[3]; asr_s+=nxt[4]
                        else:
                            # Preserve a differently configured item for the next
                            # iteration, rather than losing it or misrouting it.
                            pending=nxt
                    except queue.Empty: pass
                text=re.sub(r'\s+\S+-$','',text).strip()
                if not text or version!=self.snapshot()[1]: continue
            try:
                start=time.perf_counter(); translated=self.mt.translate(text); end=time.perf_counter()
                self.backend_status()
                if STOP.is_set() or version!=self.snapshot()[1]: continue
                self.metrics['mt_count']+=1
                row={'asr_s':round(asr_s,4),'mt_s':round(end-start,4),'capture_to_result_s':round(end-onset,4),'segment_end_to_result_s':round(end-seg_end,4),'audio_queue':self.audio_q.qsize(),'mt_queue':self.mt_q.qsize()}
                self.recent.append(row); self.event(event='translation',**row)
                self.publish(entry,text,translated,language,'',version)
            except Exception as exc:
                self.metrics['errors']+=1; self.event(event='mt_error',error=str(exc))
                self.publish(entry,text,'',language,'本地翻译失败',version)
    def monitor(self):
        import psutil
        process=psutil.Process()
        while not STOP.wait(5):
            if self.stop_file.exists(): STOP.set(); break
            self.event(event='health',rss_bytes=process.memory_info().rss,audio_queue=self.audio_q.qsize(),mt_queue=self.mt_q.qsize(),**self.metrics)
        self.event(event='stopping',**self.metrics)
    def stop(self):
        STOP.set()
        for t in list(self.threads):
            if t is not threading.current_thread(): t.join(timeout=12)
        alive=[t.name for t in self.threads if t.is_alive()]
        if alive: self.event(event='stop_pending_workers',workers=alive)
        else:
            self.asr=None; self.mt=None
        self.stop_file.unlink(missing_ok=True)

def build_parser():
    p=argparse.ArgumentParser(description='Offline multilingual transcription and local translation')
    p.add_argument('--list-devices',action='store_true'); p.add_argument('--device')
    p.add_argument('--model',default=str(ROOT/'models'/'whisper-small-int8'))
    p.add_argument('--opus-dir',default=str(ROOT/'models'/'opus-mt-en-zh-ct2-int8'))
    p.add_argument('--language',default='en'); p.add_argument('--translator',choices=['opus'],default='opus')
    p.add_argument('--target-lang',choices=['zh','en','source'],default='zh'); p.add_argument('--asr-device',choices=['cpu','cuda'],default='cpu')
    p.add_argument('--speed',choices=['original','normal','fast','balanced'],default='original')
    p.add_argument('--layout-mode',choices=['sidebar','overlay'],default='sidebar')
    p.add_argument('--compute-device',choices=['cpu','cuda'],default=None)
    p.add_argument('--compute-type',choices=['int8'],default='int8')
    p.add_argument('--font-size',type=int,default=26); p.add_argument('--max-lines',type=int,default=2)
    p.add_argument('--text-opacity',type=float,default=1.0); p.add_argument('--opacity',type=float,default=.78); p.add_argument('--clear-after',type=float,default=6.)
    p.add_argument('--hide-source',action='store_true'); p.add_argument('--no-overlay',action='store_true')
    p.add_argument('--duration',type=float,default=0,help='Optional timed diagnostic run')
    return p

def main():
    args=build_parser().parse_args()
    if args.list_devices:
        for d in list_loopback_devices(): print(d.name)
        return 0
    guard=SingleInstance('Local\\LiveSubtitle_Offline_English')
    if guard.already_running(): return 2
    STOP.clear()
    if args.no_overlay:
        pipe=Pipeline(args); pipe.start()
        try:
            while not STOP.wait(.2):
                if args.duration and time.perf_counter()-pipe.started>=args.duration: break
        except KeyboardInterrupt: pass
        finally: pipe.stop(); guard.release()
        return 0
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    from overlay import OverlayWindow
    app=QApplication(sys.argv)
    win=OverlayWindow(font_size=args.font_size,max_lines=args.max_lines,opacity=args.opacity,text_opacity=args.text_opacity,show_source=not args.hide_source,clear_after=args.clear_after,source_language=args.language,target_language=args.target_lang,layout_mode=args.layout_mode,speed=args.speed,compute_device=args.compute_device or args.asr_device)
    pipe=Pipeline(args,win); win.settings_changed.connect(pipe.update_settings); win.show(); pipe.start()
    timer=QTimer()
    timer.timeout.connect(lambda: app.quit() if STOP.is_set() or (args.duration and time.perf_counter()-pipe.started>=args.duration) else None)
    timer.start(200)
    app.aboutToQuit.connect(pipe.stop)
    try: return app.exec()
    finally: pipe.stop(); guard.release()

if __name__=='__main__': raise SystemExit(main())



