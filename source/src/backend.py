"""Process-local NVIDIA DLL discovery. Never edits system PATH."""
import os
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[2]
_HANDLES=[]
_DONE=False

def configure_cuda_dlls():
    global _DONE
    if _DONE: return
    base=_ROOT/'venv'/'Lib'/'site-packages'/'nvidia'
    paths=sorted({str(p) for p in base.glob('*/bin') if p.is_dir()})
    if os.name=='nt':
        for path in paths:
            _HANDLES.append(os.add_dll_directory(path))
        if paths:
            os.environ['PATH']=os.pathsep.join(paths+[os.environ.get('PATH','')])
    _DONE=True
