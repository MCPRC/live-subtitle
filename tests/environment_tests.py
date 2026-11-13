import unittest,tempfile,sys,json,hashlib,threading,http.server,socketserver,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from environment_core import Provisioner,Cancelled,ROOT
DATA=b'fixture-only-model'*1000
DIGEST=hashlib.sha256(DATA).hexdigest()
class Handler(http.server.BaseHTTPRequestHandler):
    hits=0; ranges=[]
    def log_message(self,*a):pass
    def do_GET(self):
        type(self).hits+=1
        if self.path=='/fail':self.send_error(503);return
        start=int(self.headers.get('Range','bytes=0-').split('=')[1].split('-')[0]);type(self).ranges.append(start)
        self.send_response(206);self.send_header('Content-Range',f'bytes {start}-{len(DATA)-1}/{len(DATA)}');self.end_headers();self.wfile.write(DATA[start:])
class Tests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'tests/environment-sandbox';base.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.tmp.name)
        self.e=dict(path='models/test/model.bin',bytes=len(DATA),sha256=DIGEST)
        self.manifest={'dependencies':{},'models':[dict(key='test',label='fixture',files=[self.e])]}
        self.p=Provisioner(self.root,manifest=self.manifest)
    def tearDown(self):self.tmp.cleanup()
    def test_valid_import_and_repeat(self):
        src=self.root/'input';src.mkdir();(src/'model.bin').write_bytes(DATA)
        self.p.import_model('test',src);p=self.root/self.e['path'];before=p.stat().st_mtime_ns
        self.p.import_model('test',src);self.assertEqual(p.stat().st_mtime_ns,before)
    def test_bad_import_atomic(self):
        src=self.root/'input';src.mkdir();(src/'model.bin').write_bytes(b'bad')
        with self.assertRaisesRegex(RuntimeError,'导入校验失败'):self.p.import_model('test',src)
        self.assertFalse((self.root/self.e['path']).exists())
    def test_corrupt_existing_preserved(self):
        p=self.root/self.e['path'];p.parent.mkdir(parents=True);p.write_bytes(b'bad')
        src=self.root/'input';src.mkdir();(src/'model.bin').write_bytes(DATA)
        with self.assertRaisesRegex(RuntimeError,'拒绝覆盖'):self.p.import_model('test',src)
        self.assertEqual(p.read_bytes(),b'bad')
    def test_cancel_import(self):
        self.p.stop.set()
        with self.assertRaises(Cancelled):self.p.import_model('test',self.root)
    def test_path_escape(self):
        with self.assertRaises(ValueError):self.p.path('../escape')
    def test_missing_runtime(self):
        with self.assertRaisesRegex(RuntimeError,'Python 3.11'):self.p.python()
    def test_missing_dependencies_mock(self):
        self.p.manifest['dependencies']={'missing-fixture':'1.0'}
        with patch.object(self.p,'python',return_value='fixture-python'),patch.object(self.p,'run',return_value='{"missing-fixture":null}'):
            self.assertEqual(self.p.dependencies(),(['missing-fixture'],[]))
    def test_http_resume_repeat_failure_and_bad_checksum(self):
        server=socketserver.TCPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_address[1]}'
            part=self.root/('downloads/environment/'+self.e['path']+'.part');part.parent.mkdir(parents=True);part.write_bytes(DATA[:123])
            self.p.download(self.e,url+'/ok');self.assertEqual(Handler.ranges[-1],123);hits=Handler.hits
            self.p.download(self.e,url+'/ok');self.assertEqual(Handler.hits,hits)
            e=dict(self.e,path='models/fail/model.bin')
            with self.assertRaises(urllib.error.HTTPError):self.p.download(e,url+'/fail')
            e=dict(self.e,path='models/bad/model.bin',sha256='0'*64)
            with self.assertRaisesRegex(RuntimeError,'SHA-256'):self.p.download(e,url+'/ok')
            self.assertFalse((self.root/e['path']).exists())
        finally:server.shutdown();server.server_close();thread.join()
    def test_http_cancel_retains_partial(self):
        server=socketserver.TCPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def emit(s):
                if s.startswith('下载 '):self.p.stop.set()
            self.p.emit=emit
            with self.assertRaises(Cancelled):self.p.download(self.e,f'http://127.0.0.1:{server.server_address[1]}/ok')
            self.assertFalse((self.root/self.e['path']).exists());self.assertTrue((self.root/('downloads/environment/'+self.e['path']+'.part')).exists())
            self.p.stop.clear();self.p.emit=lambda s:None;self.p.download(self.e,f'http://127.0.0.1:{server.server_address[1]}/ok')
            self.assertTrue(self.p.valid(self.root/self.e['path'],self.e))
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main(verbosity=2)