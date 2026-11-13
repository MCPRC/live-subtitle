"""Thread-safe, local-only floating subtitles and system-tray controls."""
from __future__ import annotations

from collections import deque

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QFont, QFontDatabase, QGuiApplication, QRegion
from PyQt6.QtWidgets import (
    QApplication, QLabel, QMenu, QVBoxLayout, QWidget, QSystemTrayIcon,
    QStyle, QInputDialog,
)


class _BottomOverlay(QWidget):
    text_updated = pyqtSignal(str, str)

    def __init__(self, font_size: int = 26, max_lines: int = 3, opacity: float = 0.78,
                 show_source: bool = True, clear_after: float = 6.0):
        super().__init__()
        self.font_size = max(12, min(64, font_size))
        self.max_lines = max(1, min(3, max_lines))
        self.opacity = max(0.0, min(1.0, opacity))
        self.show_source = show_source
        self.clear_after = max(0, clear_after)
        self._drag_pos = None
        self._user_position = False
        self._click_through = False
        self._pairs: deque[tuple[str, str]] = deque(maxlen=self.max_lines)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear_text)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("LiveSubtitle")
        self.setObjectName("subtitleRoot")
        families = set(QFontDatabase.families())
        self._font_family = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei",
                                              "Noto Sans CJK SC", "SimHei") if f in families),
                                 QApplication.font().family())
        self.src_label = QLabel("", self)
        self.dst_label = QLabel("等待语音… 右键或托盘图标打开设置", self)
        for label, color in ((self.src_label, "#c8c8c8"), (self.dst_label, "#ffffff")):
            label.setStyleSheet(f"color: {color}; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 12)
        layout.setSpacing(3)
        layout.addWidget(self.src_label)
        layout.addWidget(self.dst_label)
        self._menu = self._build_menu()
        self._tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume), self)
            self._tray.setToolTip("实时翻译字幕 · 右键设置 / 双击恢复字幕")
            self._tray.setContextMenu(self._menu)
            self._tray.activated.connect(self._tray_activated)
            self._tray.show()
        self._apply_style()
        self.text_updated.connect(self._on_text)
        QApplication.instance().aboutToQuit.connect(self._cleanup)

    def _apply_style(self) -> None:
        self.setStyleSheet(f"QWidget#subtitleRoot {{ background: rgba(0,0,0,{int(255*self.opacity)}); border-radius: 12px; }}")
        self.src_label.setFont(QFont(self._font_family, max(10, self.font_size - 8)))
        self.dst_label.setFont(QFont(self._font_family, self.font_size, QFont.Weight.Bold))
        self.src_label.setVisible(self.show_source)

    def _on_text(self, src: str, dst: str) -> None:
        self._pairs.append((src.strip()[:1600], dst.strip()[:1000]))
        self._render_pairs()
        if not self.isVisible():
            self.show()
        self._fit_and_place()
        if self.clear_after > 0:
            self._clear_timer.start(int(self.clear_after * 1000))

    def _render_pairs(self):
        self.src_label.setText("\n".join(p[0] for p in self._pairs if p[0]))
        self.dst_label.setText("\n".join(p[1] for p in self._pairs if p[1]))

    def _clear_text(self) -> None:
        self._pairs.clear()
        self.src_label.clear()
        self.dst_label.clear()
        self.hide()

    def update_text(self, src: str, dst: str) -> None:
        """Safe to call from the translation worker."""
        self.text_updated.emit(src, dst)

    def _fit_and_place(self) -> None:
        screen = self.screen() if self._user_position else QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        width = min(1100, int(geo.width() * 0.75))
        self.setFixedWidth(width)
        # Bound the overlay even if ASR returns a very long paragraph.
        budget = max(80, int(geo.height() * 0.28) - 28)
        self.src_label.setMaximumHeight(int(budget * 0.4))
        self.dst_label.setMaximumHeight(int(budget * (0.6 if self.show_source else 1.0)))
        self.layout().activate()
        self.adjustSize()
        if self._user_position:
            x = min(max(self.x(), geo.left()), max(geo.left(), geo.right()-self.width()+1))
            y = min(max(self.y(), geo.top()), max(geo.top(), geo.bottom()-self.height()+1))
        else:
            x = geo.x() + (geo.width()-self.width())//2
            y = geo.bottom()-self.height()-39
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_and_place()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()-self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._user_position = True
            self.move(event.globalPosition().toPoint()-self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._fit_and_place()

    def _build_menu(self):
        menu = QMenu(self)
        menu.addAction("恢复字幕 / 关闭点击穿透", self.restore_overlay)
        self._bilingual_action = menu.addAction("显示原文（双语）")
        self._bilingual_action.setCheckable(True)
        self._bilingual_action.setChecked(self.show_source)
        self._bilingual_action.toggled.connect(self.set_bilingual)
        self._click_action = menu.addAction("点击穿透（从托盘恢复）")
        self._click_action.setCheckable(True)
        self._click_action.toggled.connect(self.set_click_through)
        menu.addAction("字体大小…", self._choose_font)
        menu.addAction("背景不透明度…", self._choose_opacity)
        menu.addAction("自动消失时间…", self._choose_clear_after)
        menu.addAction("位置重置到底部中央", self.reset_position)
        menu.addSeparator()
        menu.addAction("退出字幕", QApplication.instance().quit)
        return menu

    def contextMenuEvent(self, event):
        self._menu.exec(event.globalPos())

    def set_bilingual(self, enabled):
        self.show_source = bool(enabled)
        self._apply_style()
        self._fit_and_place()

    def set_click_through(self, enabled):
        # Do not make the only control surface inaccessible if there is no tray.
        if enabled and self._tray is None:
            self._click_action.blockSignals(True)
            self._click_action.setChecked(False)
            self._click_action.blockSignals(False)
            return
        visible = self.isVisible()
        self._click_through = bool(enabled)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self._click_through)
        if visible:
            self.show()

    def toggle_click_through(self):
        self._click_action.setChecked(not self._click_through)

    def restore_overlay(self):
        self._click_action.setChecked(False)
        if not self._pairs:
            self.dst_label.setText("等待语音…")
        self.show()
        self.raise_()

    def reset_position(self):
        self._user_position = False
        self.restore_overlay()
        self._fit_and_place()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_overlay()

    def _choose_font(self):
        value, ok = QInputDialog.getInt(self, "字体大小", "中文字号（12–64）", self.font_size, 12, 64)
        if ok:
            self.font_size = value
            self._apply_style()
            self._fit_and_place()

    def _choose_opacity(self):
        value, ok = QInputDialog.getInt(self, "背景不透明度", "5–100%，越小越透明", round(self.opacity*100), 5, 100)
        if ok:
            self.opacity = value/100
            self._apply_style()

    def _choose_clear_after(self):
        value, ok = QInputDialog.getInt(self, "自动消失", "无新字幕后等待秒数；0 表示不消失", round(self.clear_after), 0, 120)
        if ok:
            self.clear_after = value
            self._clear_timer.stop()
            if value and self._pairs:
                self._clear_timer.start(value*1000)

    def _cleanup(self):
        self._clear_timer.stop()
        if self._tray:
            self._tray.hide()

    def closeEvent(self, event):
        self._cleanup()
        QApplication.instance().quit()
        event.accept()
# Sidebar history is memory-only. No transcript or settings are written here.
import time
import uuid
from collections import OrderedDict
from PyQt6.QtWidgets import (QScrollArea, QFrame, QPushButton, QHBoxLayout,
                             QDialog, QComboBox, QFormLayout, QDialogButtonBox, QSizePolicy, QLayout, QSlider, QCheckBox)


class OverlayWindow(_BottomOverlay):
    settings_changed = pyqtSignal(dict)
    entry_updated = pyqtSignal(str, str, str, str, str)
    backend_updated = pyqtSignal(str, str, str)

    def __init__(self, font_size=26, max_lines=3, opacity=0.78,
                 show_source=True, clear_after=6.0, source_language='auto',
                 target_language='zh', layout_mode='sidebar', speed='original', text_opacity=1.0, compute_device='cpu'):
        self.speed = speed if speed in ('original', 'normal', 'fast', 'balanced') else 'original'
        self.compute_device = compute_device if compute_device in ('cpu', 'cuda') else 'cpu'
        self._actual_asr_device = 'unknown'
        self._actual_mt_device = 'unknown'
        self._backend_status = '等待引擎报告实际设备'
        self._active_backend_label = None
        self.text_opacity = max(0.0, min(1.0, text_opacity))
        self._history_interactive = False
        self.source_language = source_language or 'auto'
        self.target_language = target_language if target_language in ('zh', 'en', 'source') else 'zh'
        self.layout_mode = layout_mode if layout_mode in ('sidebar', 'bottom') else 'sidebar'
        self._entries = OrderedDict()
        self._scroll_updating = False
        self._follow_latest = True
        self._user_scroll_active = False
        super().__init__(font_size, max_lines, opacity, show_source, clear_after)
        self._sidebar = QWidget(self)
        side_layout = QVBoxLayout(self._sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        title = QLabel('实时字幕 · 本地', self._sidebar)
        title.setStyleSheet('color: #f4f4f8; font-weight: bold;')
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        heading.addWidget(title)
        heading.addStretch()
        settings = QPushButton('设置', self._sidebar)
        settings.clicked.connect(self._choose_languages)
        settings.hide()
        # Interactive controls live in a separate native window, never this surface.
        side_layout.addLayout(heading)
        self._capability_label = QLabel(self._sidebar)
        self._capability_label.setWordWrap(True)
        self._capability_label.setStyleSheet('color: #c7b7ed; font-size: 11px;')
        self._capability_label.setTextFormat(Qt.TextFormat.PlainText)
        side_layout.addWidget(self._capability_label)
        self._scroll = QScrollArea(self._sidebar)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet('QScrollArea {border: 0; background: transparent;} QScrollBar:vertical {width: 9px;}')
        self._history_widget = QWidget()
        self._history_widget.setStyleSheet('background: transparent;')
        self._history_layout = QVBoxLayout(self._history_widget)
        self._history_layout.setContentsMargins(0, 0, 2, 0)
        self._history_layout.setSpacing(8)
        self._history_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._history_layout.addStretch()
        self._scroll.setWidget(self._history_widget)
        side_layout.addWidget(self._scroll, 1)
        self._latest_button = QPushButton('↓ 返回最新字幕', self._sidebar)
        self._latest_button.clicked.connect(self.scroll_to_latest)
        side_layout.addWidget(self._latest_button)
        self.layout().addWidget(self._sidebar)
        bar = self._scroll.verticalScrollBar()
        bar.valueChanged.connect(self._scroll_changed)
        bar.rangeChanged.connect(self._schedule_follow)
        bar.sliderPressed.connect(self._begin_user_scroll)
        bar.sliderReleased.connect(self._finish_user_scroll)
        bar.actionTriggered.connect(self._scroll_action)
        for target in (self._scroll, self._scroll.viewport(), bar):
            target.installEventFilter(self)
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._apply_follow)
        self.entry_updated.connect(self._on_entry)
        self.backend_updated.connect(self._on_backend)
        self._history_timer = QTimer(self)
        self._history_timer.timeout.connect(self._prune_history)
        self._history_timer.start(5000)
        self._refresh_capability()
        self._apply_style()
        self._latest_button.hide()
        self._create_controls()
        self._refresh_backend_display()
        self.set_history_interactive(False)

    def _build_menu(self):
        menu = super()._build_menu()
        menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._bilingual_action.setText('显示原文（双语）')
        self._click_action.setText('字幕点击穿透（默认；设置/拖动仍可用）')
        menu.insertAction(menu.actions()[1], QAction('语言设置…', menu, triggered=self._choose_languages))
        self._sidebar_action = QAction('右侧历史字幕流', menu)
        self._sidebar_action.setCheckable(True)
        self._sidebar_action.setChecked(self.layout_mode == 'sidebar')
        self._sidebar_action.toggled.connect(lambda checked: self.set_layout_mode('sidebar' if checked else 'bottom'))
        menu.insertAction(menu.actions()[1], self._sidebar_action)
        speed_menu = menu.addMenu('速度 / 分段时长')
        speed_group = QActionGroup(speed_menu)
        speed_group.setExclusive(True)
        for label, code in [('提速前原版 · 3.2 秒', 'original'), ('快速 · 1.6 秒', 'fast'), ('普通 · 2.0 秒', 'normal'), ('均衡 · 2.4 秒', 'balanced')]:
            action = speed_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.speed == code)
            speed_group.addAction(action)
            action.triggered.connect(lambda checked, value=code: self.set_speed(value))
        device_menu = menu.addMenu('计算设备（请求）')
        self._device_actions = {}
        device_group = QActionGroup(device_menu)
        device_group.setExclusive(True)
        for label, code in [('CPU', 'cpu'), ('GPU · NVIDIA RTX 3060', 'cuda')]:
            action = device_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.compute_device == code)
            device_group.addAction(action)
            action.triggered.connect(lambda checked, value=code: self.set_compute_device(value))
            self._device_actions[code] = action
        self._backend_menu_status = device_menu.addAction('实际设备：等待引擎报告')
        self._backend_menu_status.setEnabled(False)
        return menu

    def _apply_style(self):
        super()._apply_style()
        if hasattr(self, '_sidebar'):
            sidebar = self.layout_mode == 'sidebar'
            self._sidebar.setVisible(sidebar)
            self.src_label.setVisible(not sidebar and self.show_source)
            self.dst_label.setVisible(not sidebar)
            alpha = round(255*self.text_opacity)
            self.src_label.setStyleSheet(f'color: rgba(200,200,212,{alpha}); background: transparent;')
            self.dst_label.setStyleSheet(f'color: rgba(255,255,255,{alpha}); background: transparent;')
            self._capability_label.setStyleSheet(f'color: rgba(199,183,237,{alpha}); font-size: 11px;')
            for label in self._sidebar.findChildren(QLabel):
                if label not in (self._capability_label,):
                    label.setStyleSheet(f'color: rgba(240,240,248,{alpha}); background: transparent;')
            for entry in self._entries.values():
                self._style_card(entry)

    def _style_card(self, entry):
        bg, fg = round(255*self.opacity), round(255*self.text_opacity)
        border = round(55*self.opacity)
        entry['frame'].setStyleSheet(f'QFrame#subtitleCard {{background: rgba(40,37,52,{bg}); border: 1px solid rgba(140,120,190,{border}); border-radius: 9px;}} QLabel {{background: transparent; border: 0;}}')
        entry['meta'].setStyleSheet(f'color: rgba(183,165,215,{fg}); font-size: 10px;')
        entry['src_label'].setStyleSheet(f'color: rgba(200,200,212,{fg});')
        entry['dst_label'].setStyleSheet(f'color: rgba(255,255,255,{fg});')
        entry['src_label'].setFont(QFont(self._font_family, max(10, int(self.font_size * 0.55))))
        entry['dst_label'].setFont(QFont(self._font_family, max(12, int(self.font_size * 0.67))))
        # Unsupported translation must still show the source, even in Chinese-only mode.
        entry['src_label'].setVisible(bool(entry['src']) and (self.show_source or not entry['dst']))
        entry['dst_label'].setVisible(bool(entry['dst']))

    def update_entry(self, entry_id, src, dst='', language='', status=''):
        """Thread-safe stable-ID update: source first, translation later, one card."""
        self.entry_updated.emit(str(entry_id), str(src or ''), str(dst or ''),
                                str(language or ''), str(status or ''))

    def _on_text(self, src, dst):
        self._on_entry(uuid.uuid4().hex, src, dst, '', '已翻译' if dst else '原文')

    def _on_entry(self, entry_id, src, dst, language, status):
        bar = self._scroll.verticalScrollBar()
        self._scroll_updating = True
        entry = self._entries.get(entry_id)
        if entry is None:
            frame = QFrame(self._history_widget)
            frame.setObjectName('subtitleCard')
            frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            frame.setStyleSheet('QFrame#subtitleCard {background: rgba(40,37,52,215); border: 1px solid rgba(140,120,190,55); border-radius: 9px;} QLabel {background: transparent; border: 0;}')
            card_layout = QVBoxLayout(frame)
            card_layout.setContentsMargins(12, 9, 12, 10)
            card_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            meta, src_label, dst_label = (QLabel(frame) for _ in range(3))
            meta.setStyleSheet('color: #b7a5d7; font-size: 10px;')
            src_label.setStyleSheet('color: #c8c8d4;')
            dst_label.setStyleSheet('color: #ffffff;')
            for label in (meta, src_label, dst_label):
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                card_layout.addWidget(label)
            entry = {'created': time.monotonic(), 'clock': time.strftime('%H:%M:%S'),
                     'frame': frame, 'meta': meta, 'src_label': src_label, 'dst_label': dst_label}
            self._entries[entry_id] = entry
            self._history_layout.insertWidget(self._history_layout.count()-1, frame)
        entry.update(src=src.strip()[:1600], dst=dst.strip()[:1000], language=language[:24], status=status[:100])
        entry['src_label'].setText(entry['src'])
        entry['dst_label'].setText(entry['dst'])
        entry['meta'].setText(f"{entry['clock']}  ·  {language or '识别中'}  ·  {status or ('已翻译' if dst else '原文 / 待翻译')}")
        self._style_card(entry)
        self._prune_history()
        self._pairs.clear()
        for recent in list(self._entries.values())[-self.max_lines:]:
            self._pairs.append((recent['src'], recent['dst']))
        self._render_pairs()
        # Bottom mode also makes an unsupported translation explicit, never invents one.
        if not self.show_source and not dst:
            self.dst_label.setText(src)
        if not self.isVisible():
            self.show()
        self._fit_and_place()
        self._scroll_updating = False
        self._schedule_follow()
        self._scroll_changed()
        if self.clear_after > 0 and self.layout_mode == 'bottom':
            self._clear_timer.start(int(self.clear_after * 1000))

    def _prune_history(self):
        cutoff = time.monotonic() - 300
        while self._entries and (len(self._entries) > 100 or next(iter(self._entries.values()))['created'] < cutoff):
            _, old = self._entries.popitem(last=False)
            self._history_layout.removeWidget(old['frame'])
            old['frame'].deleteLater()

    def _schedule_follow(self, *_):
        # Layout and scrollbar ranges can settle over several Qt event turns.
        # rangeChanged re-arms this timer; only explicit user input disables follow.
        if hasattr(self, '_follow_timer') and self._follow_latest:
            self._follow_timer.start(0)

    def _apply_follow(self):
        if not self._follow_latest or self._user_scroll_active:
            return
        self._history_layout.activate()
        bar = self._scroll.verticalScrollBar()
        self._scroll_updating = True
        bar.setValue(bar.maximum())
        self._scroll_updating = False
        self._latest_button.hide()

    def _begin_user_scroll(self):
        self._user_scroll_active = True
        self._follow_latest = False
        self._follow_timer.stop()

    def _finish_user_scroll(self):
        self._user_scroll_active = False
        bar = self._scroll.verticalScrollBar()
        self._follow_latest = bar.maximum() - bar.value() <= 2
        self._scroll_changed()
        self._schedule_follow()

    def _scroll_action(self, *_):
        # actionTriggered is emitted for user wheel/key/scrollbar actions,
        # unlike range/value changes caused by new cards and translation reflow.
        self._begin_user_scroll()
        QTimer.singleShot(0, self._finish_user_scroll)

    def eventFilter(self, watched, event):
        if hasattr(self, '_scroll'):
            kind = event.type()
            is_scroll = watched in (self._scroll, self._scroll.viewport(), self._scroll.verticalScrollBar())
            if is_scroll and kind == QEvent.Type.Wheel:
                self._begin_user_scroll()
                QTimer.singleShot(0, self._finish_user_scroll)
            elif is_scroll and kind == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp,
                Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End):
                self._begin_user_scroll()
                QTimer.singleShot(0, self._finish_user_scroll)
            elif watched is self._scroll.verticalScrollBar() and kind == QEvent.Type.MouseButtonPress:
                self._begin_user_scroll()
            elif watched is self._scroll.verticalScrollBar() and kind == QEvent.Type.MouseButtonRelease:
                QTimer.singleShot(0, self._finish_user_scroll)
        return super().eventFilter(watched, event)

    def _scroll_changed(self, *_):
        if not self._scroll_updating:
            self._latest_button.setVisible(not self._follow_latest)

    def scroll_to_latest(self):
        self._user_scroll_active = False
        self._follow_latest = True
        self._apply_follow()
        self._schedule_follow()

    def _clear_text(self):
        if self.layout_mode == 'bottom':
            super()._clear_text()

    def _fit_and_place(self):
        if not hasattr(self, '_sidebar') or self.layout_mode == 'bottom':
            if hasattr(self, '_sidebar'):
                self.setMinimumHeight(0)
                self.setMaximumHeight(16777215)
            return super()._fit_and_place()
        screen = self.screen() if self._user_position else QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        width = min(440, max(260, int(geo.width() * 0.24)))
        height = min(820, int(geo.height() * 0.72))
        self.setFixedSize(width, height)
        if self._user_position:
            x = min(max(self.x(), geo.left()), geo.right()-width+1)
            y = min(max(self.y(), geo.top()), geo.bottom()-height+1)
        else:
            x, y = geo.right()-width-19, geo.y()+(geo.height()-height)//2
        self.move(x, y)

    def set_layout_mode(self, mode):
        self.layout_mode = 'sidebar' if mode == 'sidebar' else 'bottom'
        self._user_position = False
        self._clear_timer.stop()
        self._apply_style()
        self._fit_and_place()
        self.show()
        self.settings_changed.emit({'layout_mode': self.layout_mode})

    def set_speed(self, speed):
        if speed in ('original', 'normal', 'fast', 'balanced'):
            self.speed = speed
            self.settings_changed.emit({'speed': speed})

    def set_compute_device(self, device):
        if device not in ('cpu', 'cuda'):
            return
        self.compute_device = device
        self._sync_device_actions()
        self._refresh_backend_display()
        self.settings_changed.emit({'compute_device': device})

    def _sync_device_actions(self):
        for code, action in self._device_actions.items():
            action.setChecked(code == self.compute_device)

    def update_backend(self, asr_device, mt_device, status=''):
        """Thread-safe engine report. A requested GPU is never treated as actual GPU."""
        self.backend_updated.emit(str(asr_device or 'unknown'), str(mt_device or 'unknown'), str(status or ''))

    @staticmethod
    def _device_label(device):
        return {'cpu': 'CPU', 'cuda': 'GPU (CUDA)', 'unknown': '未确认',
                'none': '未启用', 'loading': '加载中'}.get(device, device[:60])

    def _backend_summary(self):
        requested = 'GPU' if self.compute_device == 'cuda' else 'CPU'
        return (f'请求：{requested} | 实际 ASR：{self._device_label(self._actual_asr_device)}'
                f' / MT：{self._device_label(self._actual_mt_device)}'
                + (f'\n{self._backend_status}' if self._backend_status else ''))

    def _on_backend(self, asr_device, mt_device, status):
        self._actual_asr_device = asr_device[:60]
        self._actual_mt_device = mt_device[:60]
        self._backend_status = status[:600]
        self._refresh_backend_display()

    def _refresh_backend_display(self):
        summary = self._backend_summary()
        if hasattr(self, '_capability_label'):
            self._capability_label.setText(getattr(self, '_capability_text', '') + '\n' + summary)
        if hasattr(self, '_backend_menu_status'):
            self._backend_menu_status.setText(summary.replace('\n', ' · '))
            self._backend_menu_status.setToolTip(summary)
        if hasattr(self, '_controls'):
            self._controls.setToolTip(summary)
            self._settings_button.setToolTip(summary)
            self._drag_button.setToolTip('按住拖动整个字幕窗口\n' + summary)
        if self._active_backend_label is not None:
            self._active_backend_label.setText(summary)

    def _refresh_capability(self):
        if self.target_language == 'source':
            msg = '仅原文 · 不翻译'
        elif self.target_language == 'en':
            msg = '目标英语 · 使用 Whisper 本地语音翻译'
        elif self.source_language == 'en':
            msg = '英语 → 简体中文 · 本地 Opus-MT'
        elif self.source_language == 'auto':
            msg = '自动识别 → 中文：仅英语可翻译；其他语言显示原文'
        else:
            msg = '⚠ 当前源语言无中文翻译模型，仅显示原文'
        self._capability_text = msg
        self._refresh_backend_display()

    def set_languages(self, source, target):
        self.source_language = source or 'auto'
        self.target_language = target if target in ('zh', 'en', 'source') else 'source'
        self._refresh_capability()
        self.settings_changed.emit({'source_language': self.source_language, 'target_language': self.target_language})

    def _choose_languages(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('本地字幕设置')
        form = QFormLayout(dialog)
        source = QComboBox(dialog)
        for label, code in [('自动检测', 'auto'), ('英语', 'en'), ('中文', 'zh'), ('日语', 'ja'),
                            ('韩语', 'ko'), ('法语', 'fr'), ('德语', 'de'), ('西班牙语', 'es'),
                            ('俄语', 'ru'), ('意大利语', 'it'), ('葡萄牙语', 'pt'), ('阿拉伯语', 'ar'),
                            ('印地语', 'hi'), ('泰语', 'th'), ('越南语', 'vi'), ('荷兰语', 'nl'),
                            ('波兰语', 'pl'), ('土耳其语', 'tr'), ('印尼语', 'id'), ('乌克兰语', 'uk')]:
            source.addItem(label, code)
        source.setCurrentIndex(max(0, source.findData(self.source_language)))
        target = QComboBox(dialog)
        for label, code in [('简体中文（仅英语源支持）', 'zh'), ('英语（Whisper）', 'en'), ('仅原文', 'source')]:
            target.addItem(label, code)
        target.setCurrentIndex(max(0, target.findData(self.target_language)))
        form.addRow('语音源语言', source)
        form.addRow('目标语言', target)
        device = QComboBox(dialog)
        device.setObjectName('computeDeviceCombo')
        device.addItem('CPU', 'cpu')
        device.addItem('GPU · NVIDIA RTX 3060（不可用时回退 CPU）', 'cuda')
        device.setCurrentIndex(max(0, device.findData(self.compute_device)))
        form.addRow('计算设备（请求）', device)
        backend_label = QLabel(self._backend_summary(), dialog)
        backend_label.setWordWrap(True)
        backend_label.setMaximumWidth(430)
        backend_label.setTextFormat(Qt.TextFormat.PlainText)
        self._active_backend_label = backend_label
        form.addRow('实际运行状态', backend_label)
        old_opacity, old_text_opacity = self.opacity, self.text_opacity
        background_slider = QSlider(Qt.Orientation.Horizontal, dialog)
        background_slider.setObjectName('backgroundOpacitySlider')
        background_slider.setRange(0, 100)
        background_slider.setValue(round(self.opacity*100))
        text_slider = QSlider(Qt.Orientation.Horizontal, dialog)
        text_slider.setObjectName('textOpacitySlider')
        text_slider.setRange(0, 100)
        text_slider.setValue(round(self.text_opacity*100))
        form.addRow('背景不透明度（0=全透明，100=不透明）', background_slider)
        form.addRow('文字不透明度（0=全透明，100=不透明）', text_slider)
        def preview():
            self.opacity = background_slider.value()/100
            self.text_opacity = text_slider.value()/100
            self._apply_style()
        background_slider.valueChanged.connect(preview)
        text_slider.valueChanged.connect(preview)
        history = QCheckBox('查看历史：暂时允许字幕区交互', dialog)
        history.setChecked(self._history_interactive)
        form.addRow(history)
        hint = QLabel('默认仅“设置”和“拖动”接收点击，其余字幕区域穿透。查看历史时可滚动；取消勾选即可恢复穿透。即使两项透明度为 0，两个控制按钮也始终可见。', dialog)
        hint.setWordWrap(True)
        hint.setMaximumWidth(380)
        form.addRow(hint)
        note = QLabel('只有 EN→ZH 配备本地机器翻译模型。其他源→英语使用 Whisper 语音翻译；其他源→中文不支持，将显示原文和警告。不会下载新模型或调用云服务。', dialog)
        note.setWordWrap(True)
        note.setMaximumWidth(380)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        dialog_result = self._exec_top_dialog(dialog)
        self._active_backend_label = None
        if dialog_result == QDialog.DialogCode.Accepted:
            self.compute_device = device.currentData()
            self._sync_device_actions()
            self.source_language = source.currentData()
            self.target_language = target.currentData()
            self._refresh_capability()
            self.set_history_interactive(history.isChecked())
            self.settings_changed.emit({'source_language': self.source_language,
                                        'target_language': self.target_language,
                                        'opacity': self.opacity, 'text_opacity': self.text_opacity,
                                        'compute_device': self.compute_device})
        else:
            self.opacity, self.text_opacity = old_opacity, old_text_opacity
            self._apply_style()

    def set_bilingual(self, enabled):
        super().set_bilingual(enabled)
        self.settings_changed.emit({'show_source': self.show_source})

    def _exec_top_dialog(self, dialog):
        """A modal settings window must stay above the topmost subtitle overlay."""
        old_flags, old_pos, old_visible = self.windowFlags(), self.pos(), self.isVisible()
        old_user_position = self._user_position
        try:
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            if old_visible:
                self.show()
                self.move(old_pos)
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return dialog.exec()
        finally:
            self.setWindowFlags(old_flags)
            self._user_position = old_user_position
            if old_visible:
                self.show()
                self.move(old_pos)
            else:
                self.hide()
            dialog.deleteLater()

    def _get_int(self, title, label, value, minimum, maximum):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.InputMode.IntInput)
        dialog.setIntRange(minimum, maximum)
        dialog.setIntValue(value)
        result = self._exec_top_dialog(dialog)
        return dialog.intValue(), result == QDialog.DialogCode.Accepted

    def _choose_font(self):
        value, ok = self._get_int('字体大小', '字号（12–64）', self.font_size, 12, 64)
        if ok:
            self.font_size = value
            self._apply_style()
            self._fit_and_place()
            self.settings_changed.emit({'font_size': self.font_size})

    def _choose_opacity(self):
        self._choose_languages()

    def _choose_clear_after(self):
        value, ok = self._get_int('自动消失', '无新字幕后等待秒数；0 表示不消失', round(self.clear_after), 0, 120)
        if ok:
            self.clear_after = value
            self._clear_timer.stop()
            if value and self._pairs and self.layout_mode == 'bottom':
                self._clear_timer.start(value*1000)
            self.settings_changed.emit({'clear_after': self.clear_after})

    def _cleanup(self):
        if hasattr(self, '_history_timer'):
            self._history_timer.stop()
        if hasattr(self, '_follow_timer'):
            self._follow_timer.stop()
        if hasattr(self, '_controls'):
            self._controls.hide()
            self._controls.deleteLater()
        super()._cleanup()



    def _create_controls(self):
        self._controls = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self._controls.setWindowTitle('LiveSubtitle Controls')
        self._controls.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        row = QHBoxLayout(self._controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._settings_button = QPushButton('设置', self._controls)
        self._drag_button = _DragControlButton(self, self._controls)
        for button in (self._settings_button, self._drag_button):
            button.setFixedSize(76, 32)
            row.addWidget(button)
        self._controls.setFixedSize(152, 32)
        row.activate()
        self._controls.setMask(QRegion(self._settings_button.geometry()).united(QRegion(self._drag_button.geometry())))
        self._controls.setStyleSheet('QPushButton {background: #292335; color: white; border: 1px solid #6d5a89; font: 12px "Microsoft YaHei";} QPushButton:hover {background: #49355e;}')
        self._settings_button.clicked.connect(self._choose_languages)
        self._sync_controls()
        self._controls.show()

    def _sync_controls(self):
        if not hasattr(self, '_controls'):
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = min(max(self.x()+self.width()-152, geo.left()), geo.right()-151)
        y = max(geo.top(), self.y()-32)
        self._controls.move(x, y)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._sync_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_controls()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, '_controls'):
            self._sync_controls()
            self._controls.show()

    def set_history_interactive(self, enabled):
        self._history_interactive = bool(enabled)
        self.set_click_through(not enabled)
        if not enabled:
            self.scroll_to_latest()

    def set_click_through(self, enabled):
        # The separate controls remain reachable even without a system tray.
        visible, pos = self.isVisible(), self.pos()
        self._click_through = bool(enabled)
        self._history_interactive = not self._click_through
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self._click_through)
        if hasattr(self, '_click_action'):
            self._click_action.blockSignals(True)
            self._click_action.setChecked(self._click_through)
            self._click_action.blockSignals(False)
        if visible:
            self.show()
            self.move(pos)
        if hasattr(self, '_controls'):
            self._controls.show()
            self._sync_controls()

    def restore_overlay(self):
        self.show()
        self._sync_controls()
        if hasattr(self, '_controls'):
            self._controls.show()
            self._controls.raise_()


class _DragControlButton(QPushButton):
    def __init__(self, overlay, parent):
        super().__init__('拖动', parent)
        self.overlay = overlay
        self._anchor = None
        self._origin = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip('按住拖动整个字幕窗口')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._anchor = event.globalPosition().toPoint()
            self._origin = self.overlay.pos()
            self.overlay._user_position = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.overlay.move(self._origin + event.globalPosition().toPoint() - self._anchor)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._anchor = None
        self.overlay._fit_and_place()
        super().mouseReleaseEvent(event)
