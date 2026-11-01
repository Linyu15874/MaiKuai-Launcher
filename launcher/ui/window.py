"""主窗口：PCL2 风格的卡片式布局 + 左侧导航 + 自定义标题栏。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea,
                               QSizeGrip, QSizePolicy, QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from . import icons
from .app import AppContext, LauncherApp
from launcher.core import java as java_mod
from launcher.core.auth import login_offline
from launcher.core.installer import GameInstaller
from launcher.core.launch import LaunchSettings, Launcher, build_command
from launcher.core.version import VersionProfile
from launcher.core import paths
from .dialogs import ConsoleWindow, FirstRunDialog, LoginDialog
from .pages.download import DownloadPage
from .pages.home import HomePage
from .pages.mods import ModsPage
from .pages.settings import AboutPage, SettingsPage
from .pages.versions import VersionsPage
from .widgets import ask, msg

PAGES = [
    ("home", "我的家", "home", HomePage),
    ("versions", "版本管理", "layers", VersionsPage),
    ("download", "下载新版", "download", DownloadPage),
    ("mods", "Mod 市场", "puzzle", ModsPage),
    ("settings", "设置", "settings", SettingsPage),
    ("about", "关于", "info", AboutPage),
]


class TitleBar(QFrame):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.setObjectName("titlebar")
        self.win = win
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)
        self.logo = QLabel()
        self.logo.setPixmap(icons.icon("rocket", "#FFFFFF", 18, 2).pixmap(18, 18))
        layout.addWidget(self.logo)
        self.title = QLabel("麦块启动器")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self.title.setFont(f)
        layout.addWidget(self.title)
        layout.addStretch(1)
        for text, slot, obj in [("—", win.showMinimized, "titleBtn"),
                                ("□", win.toggle_max, "titleBtn"),
                                ("✕", win.close, "titleBtnClose")]:
            b = QPushButton(text)
            b.setObjectName(obj)
            b.setFixedSize(34, 28)
            b.clicked.connect(slot)
            layout.addWidget(b)
        self._drag_start = None

    def refresh_icons(self, accent: str):
        self.logo.setPixmap(icons.icon("rocket", accent, 18, 2).pixmap(18, 18))

    def mousePressEvent(self, event):  # 拖动窗口
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint() - self.win.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start and self.win.windowState() == Qt.WindowNoState:
            self.win.move(event.globalPosition().toPoint() - self._drag_start)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_start = None


class MainWindow(QMainWindow):
    game_started = Signal(str)
    game_exited = Signal(int, str)

    def __init__(self, ctx: AppContext, app: LauncherApp):
        super().__init__()
        self.ctx = ctx
        self.app = app
        self.game_launcher = Launcher()
        self.console: ConsoleWindow | None = None
        self._start_time = 0.0
        self.setWindowTitle("麦块启动器")
        self.resize(1080, 700)
        self.setMinimumSize(880, 560)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---------------- 侧边栏
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(178)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 12, 10, 12)
        side_layout.setSpacing(4)
        brand = QLabel("  PCL-Py")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        brand.setFont(f)
        side_layout.addWidget(brand)
        hint = QLabel("  致敬 PCL2 / HMCL")
        hint.setStyleSheet("color: %s; font-size: 11px;" % ctx.palette().text_dim)
        side_layout.addWidget(hint)
        side_layout.addSpacing(10)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, icon_name, _cls in PAGES:
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            b._icon_name = icon_name
            side_layout.addWidget(b)
            self.nav_buttons[key] = b
        side_layout.addStretch(1)
        self.version_tip = QLabel(f"v{paths.APP_VERSION}")
        self.version_tip.setStyleSheet("color: %s; font-size: 11px;" % ctx.palette().text_dim)
        side_layout.addWidget(self.version_tip)
        body.addWidget(self.sidebar)

        # ---------------- 内容区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        for key, text, icon_name, cls in PAGES:
            page = cls(ctx, self)
            page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.pages[key] = page
            self.stack.addWidget(page)
        self.scroll.setWidget(self.stack)
        body.addWidget(self.scroll, 1)

        # ---------------- 状态栏
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_label = QLabel("就绪")
        bar.addWidget(self.status_label, 1)
        bar.addPermanentWidget(QSizeGrip(self))

        # toast
        self.toast_label = QLabel(self)
        self.toast_label.setWindowFlags(Qt.WindowType.ToolTip)
        self.toast_label.hide()

        self.ctx.status.connect(self.set_status)
        self.ctx.theme_changed.connect(self.on_theme_changed)
        self.game_exited.connect(self.on_game_exit)
        self.apply_theme_visuals()
        app.aboutToQuit.connect(self._on_app_quit)
        QTimer.singleShot(0, self.on_startup)

    # ------------------------------------------------------------------ 主题
    def apply_theme_visuals(self):
        pal = self.ctx.palette()
        self.sidebar.setStyleSheet(f"background: {pal.panel}; border-right: 1px solid {pal.border};")
        for b in self.nav_buttons.values():
            b.setIcon(icons.icon(getattr(b, "_icon_name", "info"), pal.text_dim, 20))
        self.titlebar.refresh_icons(pal.accent)
        self.version_tip.setStyleSheet(f"color: {pal.text_dim}; font-size: 11px;")

    def on_theme_changed(self):
        self.apply_theme_visuals()
        for b in self.nav_buttons.values():
            if b.isChecked():
                b.setChecked(False)
                b.setChecked(True)

    # ------------------------------------------------------------------ 导航
    def switch_page(self, key: str):
        if key not in self.pages:
            return
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        pal = self.ctx.palette()
        for k, b in self.nav_buttons.items():
            color = pal.accent if b.isChecked() else pal.text_dim
            b.setIcon(icons.icon(getattr(b, "_icon_name", "info"), color, 20))
        if hasattr(page, "refresh") and callable(getattr(page, "refresh")):
            try:
                page.refresh()
            except Exception:
                pass
        self.ctx.config.set("ui.last_page", key)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def toast_msg(self, text: str, kind: str = "info"):
        pal = self.ctx.palette()
        color = {"ok": pal.success, "error": pal.danger, "warn": pal.warning}.get(kind, pal.accent)
        self.toast_label.setText(text)
        self.toast_label.setStyleSheet(
            f"background: {pal.card}; color: {pal.text}; border: 1px solid {color};"
            f" border-left-width: 4px; border-radius: 8px; padding: 8px 14px;")
        self.toast_label.adjustSize()
        pos = self.geometry().bottomRight() - self.toast_label.rect().bottomRight() - QPoint(20, 46)
        self.toast_label.move(pos)
        self.toast_label.show()
        QTimer.singleShot(3200, self.toast_label.hide)

    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ------------------------------------------------------------------ 启动流程
    def on_startup(self):
        last = self.ctx.config.get("ui.last_page", "home")
        self.switch_page(last if last in self.pages else "home")
        if self.ctx.config.get("first_run", True):
            dlg = FirstRunDialog(self.ctx, self)
            dlg.exec()
        accs = self.ctx.accounts.accounts
        if accs:
            self.ctx.set_account(accs[0])
        else:
            acc = login_offline("Player")
            self.ctx.accounts.add(acc)
            self.ctx.set_account(acc)
            self.set_status("已自动创建一个离线账号，可在「我的家」里切换")

    def show_accounts(self):
        dlg = LoginDialog(self.ctx, self)
        if dlg.exec():
            self.toast_msg(f"已切换到 {dlg.account.username}", "ok")

    def show_console(self, initial_text: str = ""):
        if self.console is None:
            self.console = ConsoleWindow(self.ctx)
            self.console.closed_signal.connect(self.on_console_closed)
        if initial_text:
            self.console.text.setPlainText(initial_text)
        self.console.show()
        self.console.raise_()
        return self.console

    def on_console_closed(self):
        self.console = None

    def resolve_java(self, profile: VersionProfile, ins) -> object | None:
        candidates: list = []
        try:
            candidates += java_mod.scan_runtime_dir(self.ctx.dirs["runtime"])
        except Exception:
            pass
        try:
            candidates += java_mod.scan_system()
        except Exception:
            pass
        auto = bool(self.ctx.config.get("java.auto", True))
        preferred = ""
        if ins and ins.java_path:
            preferred = ins.java_path
            auto = False
        elif not auto:
            preferred = self.ctx.config.get("java.path", "")
        meta = {"id": profile.id, "javaVersion": profile.java_version or {}}
        info = java_mod.pick_java(meta, candidates, preferred=preferred)
        if info is None and preferred:
            info = java_mod.probe(preferred)
        return info

    def launch_current(self):
        ins = self.ctx.current_instance()
        if ins is None:
            self.toast_msg("还没有安装任何版本，请先到「下载新版」安装", "warn")
            self.switch_page("download")
            return
        acc = self.ctx.current_account
        if acc is None or not acc.username:
            dlg = LoginDialog(self.ctx, self)
            if not dlg.exec() or self.ctx.current_account is None:
                return
            acc = self.ctx.current_account
        versions_dir = self.ctx.paths.versions
        if not (versions_dir / ins.version_id / f"{ins.version_id}.json").exists():
            self.toast_msg(f"版本 {ins.version_id} 的文件已丢失，请重新安装", "error")
            return
        try:
            profile = VersionProfile.load(versions_dir, ins.version_id)
        except Exception as e:
            self.toast_msg(f"加载版本失败：{e}", "error")
            return

        java = self.resolve_java(profile, ins)
        if java is None:
            self.toast_msg("没有找到可用的 Java，请在「设置 → Java 运行时」中下载或指定", "error")
            self.switch_page("settings")
            return
        self.set_status(f"使用 Java：{java}")

        try:
            natives = self.ctx.installer.extract_natives(profile)
        except Exception as e:
            self.toast_msg(f"准备 native 失败：{e}", "error")
            return

        mem_auto = bool(self.ctx.config.get("memory.auto", True))
        max_mem = ins.max_memory or self.ctx.config.get("memory.max", 0)
        if not max_mem or (mem_auto and not ins.max_memory):
            max_mem = java_mod.recommend_memory_mb()
        min_mem = ins.min_memory or self.ctx.config.get("memory.min", 512)

        width = self.ctx.config.get("resolution.width", 854)
        height = self.ctx.config.get("resolution.height", 480)
        settings = LaunchSettings(
            version_id=ins.version_id,
            versions_dir=versions_dir,
            libraries_dir=self.ctx.paths.libraries,
            assets_dir=self.ctx.paths.assets,
            game_dir=ins.game_dir,
            account=acc,
            java=java,
            min_memory=min_mem,
            max_memory=max_mem,
            width=ins.width or width,
            height=ins.height or height,
            fullscreen=ins.fullscreen or bool(self.ctx.config.get("resolution.fullscreen", False)),
            custom_resolution=True,
            jvm_args=ins.jvm_args or self.ctx.config.get("jvm_args", ""),
            game_args=ins.game_args or self.ctx.config.get("game_args", ""),
            server_address=ins.server or self.ctx.config.get("server.address", ""),
            natives_dir=natives,
            launcher_name="PCL-Py",
            launcher_version=paths.APP_VERSION,
        )
        try:
            cmd, cwd, env = build_command(settings)
        except Exception as e:
            self.toast_msg(f"生成启动命令失败：{e}", "error")
            return

        show = bool(self.ctx.config.get("launch.show_console", True))
        if show:
            console = self.show_console()
            console.status_label.setText(f"正在启动 {ins.name}")
            console.set_stop_callback(lambda: self.game_launcher.stop())
            console.append("启动命令：" + subprocess.list2cmdline(cmd))
            console.append("-" * 80)

        self._start_time = time.time()
        self.ctx.instance_mgr.ensure_dirs(ins)
        try:
            self.game_launcher.launch(
                cmd, cwd, env,
                on_output=lambda line: self.console.append(line) if self.console else None,
                on_exit=lambda code: self.game_exited.emit(code, ins.version_id),
                hide_window=False,
            )
        except Exception as e:
            self.toast_msg(f"启动失败：{e}", "error")
            return
        self.set_status(f"游戏正在运行：{ins.name}")
        self.toast_msg(f"已启动 {ins.name}", "ok")
        if self.ctx.config.get("launch.close_launcher_when_launch", False):
            QTimer.singleShot(600, self.close)
        elif self.ctx.config.get("launch.hide_launcher_when_launch", True):
            QTimer.singleShot(600, self.hide)

    def on_game_exit(self, code: int, version_id: str):
        ins = self.ctx.current_instance()
        if ins is not None:
            ins.last_played = time.time()
            ins.play_seconds += int(time.time() - self._start_time)
            self.ctx.instance_mgr.update(ins)
            self.ctx.instance_changed.emit(ins)
        self.set_status(f"游戏已退出（退出码 {code}）")
        if self.isHidden():
            self.show()
            self.raise_()
        if self.console is not None:
            self.console.finish(code)
        if code != 0:
            self.toast_msg("游戏异常退出，请查看日志窗口的分析建议", "error")
            home = self.pages.get("home")
            if home and self.console:
                home.report_crash(self.console.text.toPlainText(), code)

    def closeEvent(self, event):
        try:
            self.game_launcher.stop()
        except Exception:
            pass
        self.ctx.config.set("ui.window_geometry", bytes(self.saveGeometry().toHex()).decode())
        super().closeEvent(event)

    def _on_app_quit(self):
        """应用退出前清理：结束游戏子进程、清空后台线程池，确保进程彻底退出。"""
        try:
            self.game_launcher.stop()
        except Exception:
            pass
        try:
            from PySide6.QtCore import QThreadPool

            QThreadPool.globalInstance().clear()
        except Exception:
            pass
