import hashlib, importlib, importlib.metadata, json, os, platform, subprocess, sys, time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
for k,v in {'TEMP':'temp','TMP':'temp','HF_HOME':'cache/huggingface','PYTHONPYCACHEPREFIX':'cache/pycache'}.items():os.environ[k]=str(R/v)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
r={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'dependencies':{}}
for n in ['soundcard','numpy','faster-whisper','PyQt6','ctranslate2','transformers','sentencepiece','scipy','psutil','opencc-python-reimplemented']:
 try:r['dependencies'][n]=importlib.metadata.version(n)
 except Exception as e:r['dependencies'][n]=str(e)
try:
 import soundcard as sc
 r['loopbacks']=[{'name':m.name,'id':m.id} for m in sc.all_microphones(include_loopback=True) if m.isloopback]
 r['default_speaker']=str(sc.default_speaker())
except Exception as e:r['audio_error']=repr(e)
try:
 import ctranslate2 as ct
 r['ct2_cpu_types']=list(ct.get_supported_compute_types('cpu'));r['cuda_devices']=ct.get_cuda_device_count()
except Exception as e:r['cuda_error']=repr(e)
r['models']={}
for n in ['whisper-small-int8','opus-mt-en-zh-ct2-int8']:
 p=R/'models'/n;r['models'][n]={'exists':(p/'model.bin').is_file(),'bytes':sum(f.stat().st_size for f in p.rglob('*') if f.is_file())}
r['integrity']={}
manifest=R/'models/model-sizes.json'
if manifest.exists():
 for entry in json.loads(manifest.read_text(encoding='utf-8-sig'))['files']:
  if '-int8' not in entry['path']:continue
  p=R/'models'/entry['path']
  if not p.is_file():r['integrity'][entry['path']]='missing';continue
  h=hashlib.sha256()
  with p.open('rb') as f:
   for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
  r['integrity'][entry['path']]=h.hexdigest()==entry['sha256']
r['all_model_bytes']=sum(f.stat().st_size for f in (R/'models').rglob('*') if f.is_file())
r['under_4GB']=r['all_model_bytes']<4_000_000_000
r['pip_check']=subprocess.run([sys.executable,'-m','pip','check'],capture_output=True,text=True).stdout
(R/'logs').mkdir(exist_ok=True)
s=json.dumps(r,ensure_ascii=False,indent=2);(R/'logs/diagnostics.json').write_text(s,encoding='utf-8');print(s)

