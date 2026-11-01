"""PCL2 风格通用控件：卡片、导航按钮、徽章、异步任务、消息框。"""

from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import (QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, QSize)
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
                               QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

from . import icons
from .theme import Palette, REPORT_QSS


# --------------------------------------------------------------------------- 卡片


class Card(QFrame):
    """带标题的卡片容器（PCL2 的 MyCard）。"""

    def __init__(self, title: str = "", icon: str = "", subtitle: str = "",
                 accent: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(8)
        self._head = QHBoxLayout()
        outer.addLayout(self._head)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        self._head.addWidget(self.title_label)
        if icon:
            self.icon_label = QLabel()
            self.icon_label.setPixmap(icons.icon(icon, self.pal().accent, 18).pixmap(18, 18))
            self._head.insertWidget(0, self.icon_label)
        self._head.addStretch(1)
        self.sub_label = QLabel(subtitle)
        if subtitle:
            self.sub_label.setStyleSheet("color: %s;" % self.pal().text_dim)
            outer.addWidget(self.sub_label)
        else:
            self.sub_label.hide()
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(30, 45, 80, 26))
        self.setGraphicsEffect(shadow)

    def pal(self) -> Palette:
        app = QApplication.instance()
        return getattr(app, "palette_obj", None) or _fallback_palette

    def add(self, widget: QWidget, stretch: int = 0):
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.body.addLayout(layout)
        return layout

    def set_subtitle(self, text: str) -> None:
        self.sub_label.setText(text)
        self.sub_label.setVisible(bool(text))


class RowCard(QFrame):
    """横向排列表单项的浅色卡片。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cardAlt")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 8, 12, 8)
        self.layout.setSpacing(8)


# --------------------------------------------------------------------------- 按钮 / 标签


class NavButton(QPushButton):
    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setIcon(icons.icon(icon_name, self._accent(), 20))
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)

    def _accent(self) -> str:
        app = QApplication.instance()
        pal = getattr(app, "palette_obj", None)
        return pal.accent if pal else "#3B7BFF"

    def refresh_icon(self, color: str | None = None):
        self.setIcon(icons.icon(self._icon_name, color or self._accent(), 20))


# 保存初始图标名，供主题切换时重建
_orig_init = NavButton.__init__


def _patched_init(self, text, icon_name, parent=None):  # pragma: no cover
    self._icon_name = icon_name
    _orig_init(self, text, icon_name, parent)


NavButton.__init__ = _patched_init


class Badge(QLabel):
    """加载器/类型小标签。"""

    COLORS = {
        "fabric": ("#E8F2FF", "#2F6FD8"),
        "forge": ("#FFEDE3", "#D1541B"),
        "neoforge": ("#FFE9E6", "#D1352B"),
        "quilt": ("#EFE9FF", "#7B4FD8"),
        "vanilla": ("#E9F6EE", "#1E8A55"),
        "release": ("#E9F6EE", "#1E8A55"),
        "snapshot": ("#FFF3D9", "#B8790A"),
        "old_beta": ("#F1EDFF", "#6A4FD8"),
        "old_alpha": ("#FDE8F0", "#C43C7E"),
    }

    def __init__(self, text: str, kind: str = "vanilla", parent: QWidget | None = None):
        super().__init__(text, parent)
        bg, fg = self.COLORS.get(kind, ("#EEF1F7", "#576070"))
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 600;")
        self.setFixedHeight(19)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class TitleLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        f = QFont()
        f.setPointSize(15)
        f.setBold(True)
        self.setFont(f)


class DimLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setStyleSheet("color: %s;" % _fallback_palette.text_dim)


# --------------------------------------------------------------------------- 异步任务


class _TaskSignals(QObject):
    progress = Signal(str, int, int, str)   # text, cur, total, detail
    finished = Signal(object)
    error = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable, signals: _TaskSignals):
        super().__init__()
        self.fn = fn
        self.signals = signals

    def run(self):  # 子线程
        def report(text: str, cur: int = 0, total: int = 0, detail: str = ""):
            try:
                self.signals.progress.emit(text, int(cur), int(total), str(detail))
            except RuntimeError:
                pass

        try:
            result = self.fn(report)
            try:
                self.signals.finished.emit(result)
            except RuntimeError:
                pass
        except Exception as e:
            try:
                self.signals.error.emit(f"{e}\n{traceback.format_exc(limit=3)}")
            except RuntimeError:
                pass


def run_async(parent: QObject, fn: Callable, on_result=None, on_error=None, on_progress=None):
    """在工作线程执行耗时任务，回到主线程回调。"""
    signals = _TaskSignals()
    if on_progress:
        signals.progress.connect(on_progress)
    if on_result:
        signals.finished.connect(on_result)
    if on_error:
        signals.error.connect(on_error)
    signals.moveToThread(QApplication.instance().thread())
    task = _Task(fn, signals)
    QThreadPool.globalInstance().start(task)
    return signals


# --------------------------------------------------------------------------- 消息


def msg(parent, title: str, text: str, kind: str = "info", buttons=QMessageBox.StandardButton.Ok) -> int:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    pal = getattr(QApplication.instance(), "palette_obj", _fallback_palette)
    icon_name = {"info": "info", "warn": "warning", "error": "warning", "ok": "check"}[kind]
    box.setIconPixmap(icons.icon(icon_name, pal.accent if kind != "warn" else pal.warning, 32).pixmap(32, 32))
    box.setStandardButtons(buttons)
    box.setStyleSheet("QLabel{ min-width: 340px; }")
    if kind in ("error", "warn"):
        # 报错窗口：白底黑字，保证可读
        box.setStyleSheet(REPORT_QSS + "QLabel{ min-width: 340px; }")
    return box.exec()


def ask(parent, title: str, text: str) -> bool:
    return msg(parent, title, text, "info", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


def fatal(title: str, text: str, parent=None) -> None:
    """启动期致命错误：强制白底黑字弹窗，避免静默失败。"""
    from PySide6.QtWidgets import QApplication, QMessageBox

    own = QApplication.instance() is None
    app = QApplication(sys.argv) if own else QApplication.instance()
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title or "启动失败")
    box.setText("程序启动时发生错误，已无法继续：")
    box.setDetailedText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setStyleSheet(REPORT_QSS)
    box.exec()
    if own:
        app.quit()


def choose_file(parent, caption: str, start: str = "", filter: str = "") -> str:
    path, _ = QFileDialog.getOpenFileName(parent, caption, start, filter)
    return path


def choose_dir(parent, caption: str, start: str = "") -> str:
    return QFileDialog.getExistingDirectory(parent, caption, start)


_fallback_palette = None  # 由 app.py 注入


def set_fallback_palette(p: Palette):
    global _fallback_palette
    _fallback_palette = p


class SegmentedBar(QWidget):
    """顶部标签切换控件。"""

    changed = Signal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.buttons: list[QPushButton] = []
        for i, name in enumerate(items):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.set_current(idx))
            layout.addWidget(b)
            self.buttons.append(b)
        if self.buttons:
            self.buttons[0].setChecked(True)
        layout.addStretch(1)

    def set_current(self, index: int):
        for i, b in enumerate(self.buttons):
            b.setChecked(i == index)
            b.setObjectName("ghost" if i != index else "primary")
            b.setStyle(b.style())  # 触发样式刷新
        self.changed.emit(index)
