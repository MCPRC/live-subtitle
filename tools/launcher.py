import ctypes, json, os, subprocess, sys
from pathlib import Path
ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
def main():
    for key, sub in {'TEMP':'temp','TMP':'temp','HF_HOME':'cache/huggingface','XDG_CACHE_HOME':'cache','PYTHONPYCACHEPREFIX':'cache/pycache','TORCH_HOME':'cache/torch','NUMBA_CACHE_DIR':'cache/numba','MPLCONFIGDIR':'cache/matplotlib'}.items():
        os.environ[key] = str(ROOT/sub)
        (ROOT/sub).mkdir(parents=True, exist_ok=True)
    os.environ['PYTHONPATH'] = str(ROOT/'runtime/environment-packages')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    os.chdir(ROOT)
    py = ROOT/'venv/Scripts/pythonw.exe'
    if not py.exists(): py = ROOT/'runtime/tools/pythonw.exe'
    if not py.exists(): raise RuntimeError('项目内Python环境缺失，请运行环境补齐.exe查看限制')
    settings = ROOT/'settings.json'
    options=json.loads(settings.read_text(encoding='utf-8-sig')) if settings.exists() else {}
    asr_path=(ROOT/options.get('asr_model','models/whisper-small-int8')).resolve()
    mt_path=(ROOT/options.get('mt_model','models/opus-mt-en-zh-ct2-int8')).resolve()
    for path in (asr_path,mt_path):
        if not path.is_relative_to(ROOT.resolve()): raise RuntimeError('模型路径必须位于项目目录内')
    for directory in (asr_path,mt_path):
        if not (directory/'model.bin').is_file():
            raise RuntimeError('本地模型缺失：'+str(directory)+'。请先完成部署，不会自动联网下载。')
    settings = ROOT/'settings.json'
    options=json.loads(settings.read_text(encoding='utf-8-sig')) if settings.exists() else {}
    args=[str(py),'-B',str(ROOT/'source/src/main.py'),'--language',options.get('source_language','en'),'--target-lang',options.get('target_language','zh'),'--speed',options.get('speed','original'),'--layout-mode',options.get('layout_mode','sidebar'),'--translator','opus','--asr-device','cpu','--compute-device',options.get('compute_device','cpu'),'--compute-type','int8','--model',str(asr_path),'--opus-dir',str(mt_path)]
    args += ['--opacity',str(options.get('opacity',0.78)),'--text-opacity',str(options.get('text_opacity',1.0)),'--font-size',str(options.get('font_size',26)),'--clear-after',str(options.get('clear_after',6.0))]
    if options.get('show_source') is False: args += ['--hide-source']
    if options.get('device'): args += ['--device',str(options['device'])]
    if '--check-only' in sys.argv:
        (ROOT/'logs').mkdir(exist_ok=True)
        (ROOT/'logs/launcher-check.json').write_text(json.dumps({'python':str(py),'args':args,'pythonpath':os.environ['PYTHONPATH'],'spawned':False},ensure_ascii=False,indent=2),encoding='utf-8')
        return
    (ROOT/'logs').mkdir(exist_ok=True)
    with open(ROOT/'logs/app.log','a',encoding='utf-8') as out,open(ROOT/'logs/app.err.log','a',encoding='utf-8') as err:
        subprocess.Popen(args,cwd=ROOT,env=os.environ.copy(),stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
if __name__=='__main__':
    try: main()
    except Exception as exc: ctypes.windll.user32.MessageBoxW(None,str(exc),'本地字幕启动失败',0x10)





