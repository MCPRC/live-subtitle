from pathlib import Path
import os, sys, json, hashlib, urllib.request, subprocess, time
ROOT=Path(__file__).resolve().parents[1]
for name in ("temp","cache/huggingface","cache/torch","cache/pycache","models","tools"):
    (ROOT/name).mkdir(parents=True,exist_ok=True)
for key,val in {"TEMP":"temp","TMP":"temp","HF_HOME":"cache/huggingface","TORCH_HOME":"cache/torch","PYTHONPYCACHEPREFIX":"cache/pycache"}.items():
    os.environ[key]=str(ROOT/val)
os.environ["HF_HUB_DISABLE_TELEMETRY"]="1"
os.environ["HF_HUB_DISABLE_XET"]="1"
LIMIT=4_000_000_000
JOBS=[
("openai/whisper-small","973afd24965f72e36ca33b3055d56a652f456b4d","source-whisper-small","whisper-small-int8",["model.safetensors","config.json","generation_config.json","preprocessor_config.json","tokenizer.json","tokenizer_config.json","vocab.json","merges.txt","normalizer.json","added_tokens.json","special_tokens_map.json"]),
("Helsinki-NLP/opus-mt-en-zh","408d9bc410a388e1d9aef112a2daba955b945255","source-opus-en-zh","opus-mt-en-zh-ct2-int8",["pytorch_model.bin","config.json","generation_config.json","source.spm","target.spm","tokenizer_config.json","vocab.json"])]
def size():
    return sum(p.stat().st_size for base in (ROOT/"models",ROOT/"cache/huggingface") for p in base.rglob("*") if p.is_file())
def check(extra=0):
    n=size()
    if n+extra>=LIMIT: raise RuntimeError(f"MODEL LIMIT: actual={n}, planned extra={extra}")
    return n
def digest(p,algo,prefix=b""):
    h=hashlib.new(algo);h.update(prefix)
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def valid(p,meta):
    if not p.exists() or p.stat().st_size!=meta["size"]:return False
    if "lfs" in meta:return digest(p,"sha256")==meta["lfs"]["sha256"]
    return digest(p,"sha1",f"blob {meta['size']}\0".encode())==meta["blobId"]
def download():
    manifest=[]
    for repo,rev,src,out,names in JOBS:
        with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true",timeout=60) as r: meta=json.load(r)
        files={x["rfilename"]:x for x in meta["siblings"]}
        d=ROOT/"models"/src;d.mkdir(exist_ok=True)
        for name in names:
            m=files[name];p=d/name
            check(max(0,m["size"]-(p.stat().st_size if p.exists() else 0))+600_000_000)
            if not valid(p,m):
                if p.exists() and p.stat().st_size>=m["size"]:
                    raise RuntimeError(f"Existing invalid full file, refusing overwrite: {p}")
                url=f"https://huggingface.co/{repo}/resolve/{rev}/{name}?download=true"
                print("DOWNLOAD",repo,name,m["size"],flush=True)
                subprocess.run([r"C:\Windows\System32\curl.exe","--fail","--location","--continue-at","-","--retry","5","--retry-all-errors","--connect-timeout","30","--silent","--show-error","--output",str(p),url],check=True)
                if not valid(p,m):raise RuntimeError("Integrity failed: "+str(p))
            manifest.append({"repo":repo,"revision":rev,"path":str(p.relative_to(ROOT)),"bytes":p.stat().st_size,"sha256":digest(p,"sha256"),"verified_upstream":True})
            print("VERIFIED",name,flush=True)
    (ROOT/"models/download-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("DOWNLOAD_COMPLETE",check(),flush=True)
def convert():
    os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
    import ctranslate2
    from transformers import AutoTokenizer
    for repo,rev,src,out,names in JOBS:
        s=ROOT/"models"/src;d=ROOT/"models"/out
        if not (d/"model.bin").exists():
            check(600_000_000)
            print("CONVERT",out,flush=True)
            ctranslate2.converters.TransformersConverter(str(s),copy_files=["tokenizer.json","preprocessor_config.json"] if "whisper" in src else ["source.spm","target.spm"]).convert(str(d),quantization="int8")
        check()
    report={"total_model_bytes":size(),"limit_bytes":LIMIT,"files":[]}
    for p in (ROOT/"models").rglob("*"):
        if p.is_file() and p.name not in ("model-sizes.json",):
            report["files"].append({"path":str(p.relative_to(ROOT/"models")),"bytes":p.stat().st_size,"sha256":digest(p,"sha256")})
    (ROOT/"models/model-sizes.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("CONVERSION_COMPLETE",report["total_model_bytes"],flush=True)
if __name__=="__main__":
    if sys.argv[1]=="download":download()
    elif sys.argv[1]=="convert":convert()

