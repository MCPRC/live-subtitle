# Build from project root with project-local TEMP and cache.
from pathlib import Path
root=Path(SPECPATH).parent
analysis=Analysis([str(root/'tools/environment_gui.py')],pathex=[str(root/'tools')],datas=[(str(root/'tools/environment-manifest.json'),'.')],binaries=[],hiddenimports=[],excludes=['torch','transformers','ctranslate2','numpy','faster_whisper'],noarchive=False)
# Qt 6.12 ships a newer VC runtime than Python 3.11; collect it app-locally.
qtbin=root/'venv/Lib/site-packages/PyQt6/Qt6/bin'
vc=list(qtbin.glob('*140*.dll'))
names={p.name.lower() for p in vc}
# Qt uses Windows' native ICU ABI; never bundle Poppler's renamed ICU.
analysis.binaries=[e for e in analysis.binaries if Path(e[0]).name.lower() not in names|{'icuuc.dll','icudt78.dll'}]+[(p.name,str(p),'BINARY') for p in vc]
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='环境补齐',console=False,contents_directory='environment_internal',upx=False)
coll=COLLECT(exe,analysis.binaries,analysis.datas,name='environment',upx=False)