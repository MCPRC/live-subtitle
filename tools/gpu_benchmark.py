import base64,json,os,subprocess,sys,time,gc,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[1]
for k,v in {'TEMP':'temp','TMP':'temp','HF_HOME':'cache/huggingface','PYTHONPYCACHEPREFIX':'cache/pycache'}.items():os.environ[k]=str(R/v)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
sys.path.insert(0,str(R/'source/src'))
import numpy as np,psutil
from asr import FasterWhisperASR
from translate import OpusTranslator
ps=r'''$v=New-Object -ComObject SAPI.SpVoice; $voice=$v.GetVoices()|Where-Object {$_.GetDescription() -like '*Zira*'}|Select-Object -First 1; if(!$voice){throw 'No local English voice'}; $v.Voice=$voice; $m=New-Object -ComObject SAPI.SpMemoryStream; $m.Format.Type=18; $v.AudioOutputStream=$m; $null=$v.Speak('The weather is beautiful today. We can go outside for a walk.'); [Convert]::ToBase64String([byte[]]$m.GetData())'''
b=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps],capture_output=True,text=True,check=True)
raw=base64.b64decode(b.stdout.strip())
audio=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768.
assert len(audio)>16000 and np.max(abs(audio))>.01
result={'audio_origin':'Windows local SAPI generated in memory; no playback/recording/file','samples':len(audio),'assumed_sample_rate':16000,'duration_s':len(audio)/16000,'cases':{}}
def gpu_mem():
 try:return subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()
 except:return 'unavailable'
result['gpu_total_used_before_mib']=gpu_mem()
for device in ('cpu','cuda'):
 start=time.perf_counter()
 a=FasterWhisperASR(str(R/'models/whisper-small-int8'),device=device,language='en')
 m=OpusTranslator(str(R/'models/opus-mt-en-zh-ct2-int8'),device=device)
 records=[]
 for i in range(3):
  t=time.perf_counter(); res=a.transcribe(audio,language='en'); after=time.perf_counter(); zh=m.translate(res.text); end=time.perf_counter()
  records.append({'asr_s':after-t,'mt_s':end-after,'combined_s':end-t,'english':res.text,'chinese':zh})
 result['cases'][device]={'actual_asr':a.device,'actual_mt':m.device,'asr_fallback':getattr(a,'fallback_reason',''),'mt_fallback':getattr(m,'fallback_reason',''),'wall_s':time.perf_counter()-start,'records':records,'rss_bytes':psutil.Process().memory_info().rss,'gpu_total_used_mib':gpu_mem()}
 del a,m;gc.collect()
result['gpu_total_used_after_mib']=gpu_mem()
result['gpu_memory_note']='Whole-GPU readings include other apps; not per-process VRAM measurement.'
(R/'logs/gpu-benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
