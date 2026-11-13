"""Project-local environment provisioning. No audio/network inference APIs."""
from pathlib import Path
import hashlib, json, os, sys, subprocess, threading, urllib.request, urllib.error, shutil, time
ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
DATA = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
LIMIT = 4_000_000_000
class Cancelled(Exception): pass

def local_env(root):
    env = os.environ.copy()
    for k,v in {'TEMP':'temp','TMP':'temp','HF_HOME':'cache/huggingface','TORCH_HOME':'cache/torch','PYTHONPYCACHEPREFIX':'cache/pycache','PIP_CACHE_DIR':'cache/pip','XDG_CACHE_HOME':'cache'}.items():
        (root/v).mkdir(parents=True,exist_ok=True); env[k]=str(root/v)
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONPATH=str(root/'runtime/environment-packages'))
    return env

def sha(path, cancel=lambda:None):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): cancel(); h.update(b)
    return h.hexdigest()

class Provisioner:
    def __init__(self,root=ROOT,emit=lambda s:None,cancel=None,manifest=None):
        self.root=Path(root).resolve(); self.emit=emit; self.stop=cancel or threading.Event()
        self.manifest=manifest or json.loads((DATA/'environment-manifest.json').read_text(encoding='utf-8'))
        self.env=local_env(self.root)
    def tick(self):
        if self.stop.is_set(): raise Cancelled('已取消；下载片段保留，下次可继续。')
    def path(self,rel):
        p=(self.root/rel).resolve()
        if not p.is_relative_to(self.root): raise ValueError('路径必须在项目目录内')
        return p
    def valid(self,p,e):
        return p.is_file() and p.stat().st_size==e['bytes'] and sha(p,self.tick)==e['sha256']
    def python(self):
        for rel in ('venv/Scripts/python.exe','runtime/tools/python.exe'):
            p=self.path(rel)
            if p.is_file(): return p
        raise RuntimeError('缺少项目内 Python 3.11。此 EXE 可独立打开界面，但尚不支持无 Python 的推理环境自举。请恢复项目 runtime/tools 或 venv。不会修改系统 PATH。')
    def run(self,args):
        self.tick()
        log=self.path('logs/environment-child.log');log.parent.mkdir(exist_ok=True)
        with log.open('w',encoding='utf-8') as f:
            p=subprocess.Popen([str(x) for x in args],cwd=self.root,env=self.env,stdout=f,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while p.poll() is None:
                if self.stop.wait(.15):
                    p.terminate();p.wait();raise Cancelled('已取消；已完成的文件保留。')
            output=log.read_text(encoding='utf-8',errors='replace')
        if p.returncode: raise RuntimeError(output[-6000:] or f'子进程失败 {p.returncode}')
        return output
    def dependencies(self):
        code="import importlib.metadata as m,json; wanted="+repr(self.manifest['dependencies'])+"; got={};\nfor n,v in wanted.items():\n try: got[n]=m.version(n)\n except m.PackageNotFoundError: got[n]=None\nprint(json.dumps(got))"
        got=json.loads(self.run([self.python(),'-B','-c',code]).strip().splitlines()[-1])
        missing=[n for n,v in got.items() if v is None]
        mismatch=[f'{n}: {v} (清单 {self.manifest["dependencies"][n]})' for n,v in got.items() if v is not None and v!=self.manifest['dependencies'][n]]
        return missing,mismatch
    def check(self):
        rows=[]
        for model in self.manifest['models']:
            bad=[]
            for e in model['files']:
                self.tick();p=self.path(e['path']);self.emit('校验 '+e['path'])
                if not self.valid(p,e):bad.append(e['path'])
            rows.append((model['label'],'完整（SHA-256）' if not bad else '缺失/校验失败：'+', '.join(bad)))
        try:
            missing,mismatch=self.dependencies()
            rows.append(('运行组件','缺少：'+', '.join(missing) if missing else '已安装'))
            if mismatch: rows.append(('版本差异','；'.join(mismatch)))
        except Exception as e: rows.append(('运行组件',str(e)))
        self.emit('\n'.join(a+'：'+b for a,b in rows));return rows
    def budget(self,extra):
        total=sum(p.stat().st_size for folder in ('models','cache/huggingface','downloads/environment','temp/environment') for p in self.path(folder).rglob('*') if p.is_file())
        if total+extra>=LIMIT:raise RuntimeError(f'模型空间上限 4GB：现有 {total:,}，需增加 {extra:,} 字节；请先自行整理重复文件。')
        if shutil.disk_usage(self.root).free<extra+100_000_000:raise RuntimeError('磁盘剩余空间不足')
    def download(self,e,url):
        dest=self.path(e['path'])
        if self.valid(dest,e):self.emit('复用 '+e['path']);return
        if dest.exists():raise RuntimeError('现有文件校验失败，未覆盖：'+str(dest)+'。请关闭字幕后自行移走损坏文件再重试。')
        part=self.path('downloads/environment/'+e['path']+'.part');part.parent.mkdir(parents=True,exist_ok=True)
        offset=part.stat().st_size if part.exists() else 0
        if offset>e['bytes']:raise RuntimeError('下载片段超过清单大小，请移走：'+str(part))
        self.budget(e['bytes']-offset)
        if offset<e['bytes']:
            req=urllib.request.Request(url,headers={'Range':f'bytes={offset}-','User-Agent':'LocalSubtitleEnvironment/1'})
            with urllib.request.urlopen(req,timeout=20) as response:
                status=response.status
                if offset and status!=206:
                    self.emit('服务器不支持续传，重新下载该文件');offset=0
                elif status==206:
                    if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise RuntimeError('续传响应范围不匹配')
                with part.open('ab' if offset else 'wb') as f:
                    while True:
                        self.tick();b=response.read(256*1024)
                        if not b:break
                        offset+=len(b)
                        if offset>e['bytes']:raise RuntimeError('下载超过清单大小')
                        f.write(b);self.emit(f'下载 {Path(e["path"]).name} {offset:,}/{e["bytes"]:,} 字节')
        if not self.valid(part,e):raise RuntimeError('SHA-256 校验失败，片段已保留供检查，请移走后重试：'+str(part))
        self.tick();dest.parent.mkdir(parents=True,exist_ok=True);os.replace(part,dest)
    def import_model(self,key,folder):
        self.tick()
        model=next(m for m in self.manifest['models'] if m['key']==key);folder=Path(folder)
        # Validate ALL source files before publishing anything.
        for e in model['files']:
            p=folder/Path(e['path']).name
            if not self.valid(p,e):raise RuntimeError('导入校验失败，现有模型未改动：'+str(p))
        todo=[e for e in model['files'] if not self.valid(self.path(e['path']),e)]
        for e in todo:
            if self.path(e['path']).exists():raise RuntimeError('拒绝覆盖现有损坏文件；关闭字幕后请自行移走：'+e['path'])
        self.budget(sum(e['bytes'] for e in todo))
        for e in todo:
            self.tick();dest=self.path(e['path']);dest.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path('temp/environment/import/'+key+'/'+dest.name);tmp.parent.mkdir(parents=True,exist_ok=True)
            with (folder/dest.name).open('rb') as src,tmp.open('wb') as out:
                while True:
                    self.tick();b=src.read(1024*1024)
                    if not b:break
                    out.write(b)
            if not self.valid(tmp,e):raise RuntimeError('复制后校验失败：'+str(tmp))
            os.replace(tmp,dest);self.emit('已导入 '+dest.name)
        self.emit('导入完成；已有完整文件已复用。')
    def repair_dependencies(self):
        if not self.path('venv/Scripts/python.exe').is_file():
            self.emit('从项目 runtime/tools 创建项目内 venv…')
            self.run([self.python(),'-B','-m','venv',self.path('venv')])
        missing,mismatch=self.dependencies()
        if mismatch:raise RuntimeError('发现现有版本差异，拒绝自动升级/覆盖：'+'；'.join(mismatch))
        if not missing:self.emit('运行组件已完整，跳过安装');return
        # Target overlay; never modify the existing site-packages or system software.
        self.emit('仅补齐缺失组件到 runtime/environment-packages：'+', '.join(missing))
        stage=self.path('temp/environment/packages')
        if stage.exists():shutil.rmtree(stage)
        stage.mkdir(parents=True)
        args=[self.python(),'-B','-m','pip','install','--no-deps','--retries','1','--timeout','20','--only-binary=:all:','--target',stage,'--cache-dir',self.path('cache/pip')]
        regular=[n for n in missing if n!='torch']
        if regular:self.run(args+[f'{n}=={self.manifest["dependencies"][n]}' for n in regular])
        if 'torch' in missing:self.run(args+['--index-url','https://download.pytorch.org/whl/cpu','torch=='+self.manifest['dependencies']['torch']])
        target=self.path('runtime/environment-packages');target.mkdir(parents=True,exist_ok=True)
        items=[p for p in stage.iterdir() if p.name not in ('bin','Scripts','__pycache__')]
        for item in items:
            if (target/item.name).exists():raise RuntimeError('组件目录冲突，未覆盖：'+str(target/item.name))
        self.tick()
        for item in items:os.replace(item,target/item.name)
        remaining,_=self.dependencies()
        if remaining:raise RuntimeError('组件仍缺失：'+', '.join(remaining))
    def repair(self):
        self.repair_dependencies()
        for model in self.manifest['models']:
            if all(self.valid(self.path(e['path']),e) for e in model['files']):self.emit('复用 '+model['label']);continue
            for e in model['files']:
                if self.path(e['path']).exists() and not self.valid(self.path(e['path']),e):raise RuntimeError('现有模型文件损坏，未覆盖：'+e['path'])
            for e in model['sources']:
                self.download(e,e['url'])
            stage=self.path('temp/environment/convert-'+model['key'])
            if stage.exists():
                # Only delete our isolated conversion output, never installed models.
                if not stage.is_relative_to(self.path('temp/environment')):raise RuntimeError('非法暂存路径')
                shutil.rmtree(stage)
            self.budget(sum(e['bytes'] for e in model['files']))
            self.emit('离线转换 '+model['label'])
            src=self.path(model['source_dir'])
            code="import ctranslate2; ctranslate2.converters.TransformersConverter("+repr(str(src))+",copy_files="+repr(model['copy_files'])+").convert("+repr(str(stage))+",quantization='int8')"
            self.run([self.python(),'-B','-c',code]);self.import_model(model['key'],stage)
            shutil.rmtree(stage)
        self.verify()
    def verify(self):
        for model in self.manifest['models']:
            if not all(self.valid(self.path(e['path']),e) for e in model['files']):raise RuntimeError('模型不完整，请先补齐')
        self.emit('执行本地 CPU 推理自检（不录音、不联网）…')
        code="import sys;sys.path.insert(0,"+repr(str(self.path('source/src')))+");import numpy as np;from asr import FasterWhisperASR;from translate import OpusTranslator;a=FasterWhisperASR(model_size="+repr(str(self.path('models/whisper-small-int8')))+",device='cpu',language='en');a.transcribe(np.zeros(16000,dtype=np.float32));t=OpusTranslator("+repr(str(self.path('models/opus-mt-en-zh-ct2-int8')))+",device='cpu');s=t.translate('Hello, welcome to the world.');assert s.strip();print(s)"
        self.emit(self.run([self.python(),'-B','-c',code]));self.emit('英语 → 简体中文：模型校验与本地 CPU 推理通过。GPU 为可选项，仍沿用字幕程序的 CPU 回退。')