"""Independent PyQt6 UI; provisioned inference stays in the project runtime."""
import os,sys,threading,time,json
from pathlib import Path
from environment_core import ROOT,Provisioner,Cancelled,local_env
os.environ.update(local_env(ROOT))
from PyQt6.QtCore import QThread,pyqtSignal,QTimer,Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QPlainTextEdit,QProgressBar,QFileDialog,QMessageBox
class Worker(QThread):
    message=pyqtSignal(str);outcome=pyqtSignal(str)
    def __init__(self,action,key=None,folder=None):
        super().__init__();self.action=action;self.key=key;self.folder=folder;self.stop=threading.Event()
    def run(self):
        try:
            import msvcrt
            lock_path=ROOT/'control/environment.lock';lock_path.parent.mkdir(exist_ok=True)
            self.lock=lock_path.open('a+b');self.lock.seek(0);self.lock.write(b'0');self.lock.flush();self.lock.seek(0)
            try:msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError('另一个环境补齐工具正在工作，请等待其结束。')
            p=Provisioner(emit=self.message.emit,cancel=self.stop)
            if self.action=='import':p.import_model(self.key,self.folder);p.check()
            else:getattr(p,self.action)()
            self.outcome.emit('操作完成')
        except Cancelled as e:self.outcome.emit(str(e))
        except Exception as e:self.message.emit('错误：'+str(e));self.outcome.emit('未完成，请查看详情并重试')
        finally:
            if hasattr(self,'lock'):self.lock.close()
class Window(QWidget):
    def __init__(self):
        super().__init__();self.worker=None;self.setWindowTitle('环境补齐 · 本地实时翻译');self.resize(900,670);self.setMinimumSize(720,540)
        layout=QVBoxLayout(self);layout.setContentsMargins(28,24,28,24);layout.setSpacing(16)
        title=QLabel('准备本地翻译环境');title.setObjectName('heading');title.setFont(QFont('Microsoft YaHei UI',20,QFont.Weight.DemiBold));layout.addWidget(title)
        intro=QLabel('检查后只补齐缺失项。现有字幕可继续运行；模型推理始终在本机完成。');intro.setWordWrap(True);layout.addWidget(intro)
        row=QHBoxLayout();row.addWidget(QLabel('支持的语言组合'))
        pair=QComboBox();pair.addItem('英语 → 简体中文   ·   Whisper small + Opus-MT');pair.setAccessibleName('已验证的源语言和目标语言组合');row.addWidget(pair,1);layout.addLayout(row)
        detail=QLabel('仅开放本项目已验证的组合。模型总量上限 4 GB；GPU 为可选加速。\n界面自带运行库；补齐推理环境仍需项目内 Python 3.11（runtime/tools 或 venv）。');detail.setWordWrap(True);layout.addWidget(detail)
        actions=QHBoxLayout();self.buttons=[]
        for text,action in [('检查环境','check'),('补齐缺失项','repair'),('本地推理自检','verify')]:
            b=QPushButton(text);b.setMinimumHeight(38);b.clicked.connect(lambda checked=False,a=action:self.start(a));actions.addWidget(b);self.buttons.append(b)
        layout.addLayout(actions)
        imports=QHBoxLayout();imports.addWidget(QLabel('已有模型？导入指定的 INT8 模型文件夹：'))
        for text,key in [('导入语音模型…','asr'),('导入翻译模型…','mt')]:
            b=QPushButton(text);b.setMinimumHeight(34);b.clicked.connect(lambda checked=False,k=key:self.choose(k));imports.addWidget(b);self.buttons.append(b)
        layout.addLayout(imports)
        self.status=QLabel('准备就绪。点击“检查环境”查看模型和运行组件。');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setTextVisible(False);self.progress.setMaximumHeight(5);layout.addWidget(self.progress)
        self.log=QPlainTextEdit();self.log.setMaximumBlockCount(1500);self.log.setReadOnly(True);self.log.setAccessibleName('检查结果和操作详情');self.log.setPlaceholderText('校验结果、下载字节进度和错误会显示在这里。');layout.addWidget(self.log,1)
        bottom=QHBoxLayout();note=QLabel('联网仅用于你发起的组件/模型下载；不上传音频，不启用在线翻译 API。');note.setWordWrap(True);bottom.addWidget(note,1)
        self.cancel=QPushButton('取消操作');self.cancel.setEnabled(False);self.cancel.clicked.connect(self.cancel_work);bottom.addWidget(self.cancel);layout.addLayout(bottom)
        self.setStyleSheet('QWidget {font-family: "Microsoft YaHei UI"; font-size: 14px; background: #f5f6f8; color:#202832;} QPushButton {background:#ffffff; border:1px solid #8995a3; border-radius:5px; padding:7px 14px;} QLabel#heading {font-size:24px;font-weight:600;} QPushButton:hover {background:#e6edf6; border-color:#315d8c;} QPushButton:focus {border:2px solid #315d8c;} QPushButton:disabled {color:#697583; background:#e9edf1; border-color:#bdc5ce;} QComboBox {background:white; padding:8px; border:1px solid #8995a3; border-radius:4px;} QPlainTextEdit {background:white; border:1px solid #b3bcc7; padding:10px;} QProgressBar {border:0;background:#dbe1e9;} QProgressBar::chunk {background:#315d8c;}')
    def record(self,s):
        if s.startswith('下载 '):
            self.status.setText(s)
            # Keep log bounded while preserving byte progress in the status line.
            if time.monotonic()-getattr(self,'last_download',0)<1:return
            self.last_download=time.monotonic()
        self.log.appendPlainText(s)
        p=ROOT/'logs/environment.log';p.parent.mkdir(exist_ok=True)
        with p.open('a',encoding='utf-8') as f:f.write(time.strftime('%Y-%m-%d %H:%M:%S ')+s+'\n')
    def start(self,action,key=None,folder=None):
        if self.worker and self.worker.isRunning():return
        self.log.clear();self.status.setText('正在处理，请稍候…');self.progress.setRange(0,0)
        for b in self.buttons:b.setEnabled(False)
        self.cancel.setEnabled(True);self.worker=Worker(action,key,folder);self.worker.message.connect(self.record);self.worker.outcome.connect(self.done);self.worker.start()
    def choose(self,key):
        folder=QFileDialog.getExistingDirectory(self,'选择已转换的 INT8 模型文件夹',str(ROOT/'models'))
        if folder:self.start('import',key,folder)
    def cancel_work(self):
        if self.worker:self.worker.stop.set();self.cancel.setEnabled(False);self.status.setText('正在取消；等待当前网络读取结束（连接超时 20 秒）；下载片段会保留。')
    def done(self,s):
        self.status.setText(s);self.progress.setRange(0,100);self.progress.setValue(100 if s=='操作完成' else 0)
        for b in self.buttons:b.setEnabled(True)
        self.cancel.setEnabled(False)
    def closeEvent(self,e):
        if self.worker and self.worker.isRunning():self.cancel_work();e.ignore()
        else:e.accept()
def main():
    app=QApplication(sys.argv);app.setStyle('Fusion');w=Window();w.show()
    if '--smoke-test' in sys.argv:
        w.start('check')
        def finish():
            if not w.worker.isRunning():
                evidence={'title':w.windowTitle(),'visible':w.isVisible(),'status':w.status.text(),'log':w.log.toPlainText(),'size':[w.width(),w.height()]}
                (ROOT/'logs/environment-exe-smoke.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');w.grab().save(str(ROOT/'logs/environment-exe.png'));app.quit()
        timer=QTimer();timer.timeout.connect(finish);timer.start(200)
    return app.exec()
if __name__=='__main__':sys.exit(main())