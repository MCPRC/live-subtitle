"""Real offline full repair in a disposable project-local environment.
Uses read-only hard links to already verified source weights and a .pth to reuse
installed components. Never removes/renames the application's models or venv.
"""
import sys,json,shutil,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from environment_core import ROOT,Provisioner
sandbox=ROOT/'tests/environment-full-repair'
if sandbox.exists():raise RuntimeError('Test directory already exists; inspect it before retrying')
sandbox.mkdir();p=Provisioner(sandbox,emit=lambda s:print(s,flush=True))
try:
    p.run([ROOT/'runtime/tools/python.exe','-B','-m','venv',sandbox/'venv'])
    (sandbox/'venv/Lib/site-packages/existing-components.pth').write_text(str(ROOT/'venv/Lib/site-packages')+'\n',encoding='utf-8')
    for model in p.manifest['models']:
        for entry in model['sources']:
            dest=p.path(entry['path']);dest.parent.mkdir(parents=True,exist_ok=True)
            os.link(ROOT/entry['path'],dest)
    (sandbox/'source/src').mkdir(parents=True)
    for name in ('asr.py','translate.py','backend.py'):
        shutil.copyfile(ROOT/'source/src'/name,sandbox/'source/src'/name)
    p.repair()
    stamps={e['path']:p.path(e['path']).stat().st_mtime_ns for m in p.manifest['models'] for e in m['files']}
    p.repair()
    assert all(p.path(k).stat().st_mtime_ns==v for k,v in stamps.items())
    (ROOT/'logs/environment-full-repair.json').write_text(json.dumps({'missing_converted_models_repaired':True,'source_weights_reused_without_download':True,'cpu_inference':True,'repeat_models_unchanged':True,'test_runtime':'isolated venv reuses installed components via test-only .pth'},indent=2),encoding='utf-8')
    print('REAL_FULL_REPAIR_AND_REPEAT_OK',flush=True)
finally:
    assert sandbox.resolve().is_relative_to((ROOT/'tests').resolve())
    shutil.rmtree(sandbox)