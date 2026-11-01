"""应用程序上下文与入口。

集中管理配置、下载器、实例、账号，并为 UI 提供线程安全的信号。
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from ..core import paths as core_paths
from ..core.auth import Account, AccountStore
from ..core.config import Config
from ..core.installer import GameInstaller, InstallerPaths
from ..core.instances import Instance, InstanceManager
from ..core.net import SourceManager
from .theme import Palette, palette, qss
from . import widgets


class AppContext(QObject):
    """全局共享状态。"""

    account_changed = Signal(object)
    instance_changed = Signal(object)
    instances_changed = Signal()
    theme_changed = Signal()
    status = Signal(str)          # 状态栏消息
    toast = Signal(str, str)      # 消息浮层（文本, 类型）

    def __init__(self, root: Path | None = None):
        super().__init__()
        dirs = core_paths.ensure_dirs(root)
        self.dirs = dirs
        self.config = Config(dirs["config"] / "config.json")
        self.accounts = AccountStore(dirs["config"] / "accounts.json")
        self.game_root = Path(self.config.get("game_root") or dirs["root"])
        self.paths = InstallerPaths.from_root(self.game_root)
        self.source = SourceManager(self.config.get("source", "official"))
        self.installer = self._build_installer()
        self.instance_mgr = InstanceManager(self.config, self.game_root)
        self.current_account: Account | None = None
        self._current_instance_id: str = self.config.get("selected_instance", "")
        self.log(f"数据目录：{self.dirs['root']}")

    # ------------------------------------------------------------------ 组件
    def _build_installer(self) -> GameInstaller:
        return GameInstaller(self.paths, self.source,
                             threads=max(1, int(self.config.get("download_threads", 32))),
                             report=self._report)

    def rebuild(self) -> None:
        """配置项（下载源/线程/游戏目录）变化后重建。"""
        self.game_root = Path(self.config.get("game_root") or self.dirs["root"])
        self.paths = InstallerPaths.from_root(self.game_root)
        self.source = SourceManager(self.config.get("source", "official"))
        self.installer = self._build_installer()
        self.instance_mgr = InstanceManager(self.config, self.game_root)

    def _report(self, text: str, cur: int, total: int, detail: str = "") -> None:
        self.status.emit(f"{text} {detail}".strip())

    def log(self, text: str) -> None:
        self.status.emit(text)

    # ------------------------------------------------------------------ 账号
    def set_account(self, acc: Account | None) -> None:
        self.current_account = acc
        self.account_changed.emit(acc)

    # ------------------------------------------------------------------ 实例
    @property
    def instances(self) -> list[Instance]:
        return self.instance_mgr.all()

    def current_instance(self) -> Instance | None:
        ins = self.instance_mgr.get(self._current_instance_id)
        if ins is None:
            lst = self.instance_mgr.all()
            ins = lst[0] if lst else None
            if ins:
                self._current_instance_id = ins.id
        return ins

    def set_instance(self, ins: Instance | None) -> None:
        if ins is None:
            return
        self._current_instance_id = ins.id
        self.config.select_instance(ins.id)
        self.instance_changed.emit(ins)

    def refresh_instances(self) -> None:
        self.instances_changed.emit()

    # ------------------------------------------------------------------ 主题
    def is_dark(self) -> bool:
        mode = self.config.get("theme", "auto")
        if mode == "dark":
            return True
        if mode == "light":
            return False
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            return False

    def palette(self) -> Palette:
        return palette(self.is_dark())


class LauncherApp(QApplication):
    """带主题管理的 Application。"""

    def __init__(self, argv: list[str], ctx: AppContext):
        super().__init__(argv)
        self.ctx = ctx
        self.palette_obj = ctx.palette()
        widgets.set_fallback_palette(self.palette_obj)
        self.apply_theme()
        font = QFont("Microsoft YaHei UI", 9)
        font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
        self.setFont(font)
        self.setAttribute(Qt.AA_DontShowIconsInMenus, False)
        # 应用图标
        for name in ("app.ico", "app.png"):
            p = core_paths.RESOURCE_DIR / name
            if p.exists():
                self.setWindowIcon(QIcon(str(p)))
                break

    palette_obj: Palette

    def apply_theme(self) -> None:
        self.palette_obj = self.ctx.palette()
        widgets.set_fallback_palette(self.palette_obj)
        self.setStyleSheet(qss(self.palette_obj))

    def refresh_theme(self) -> None:
        self.apply_theme()
        self.ctx.theme_changed.emit()


def bootstrap(root: Path | None = None) -> tuple[LauncherApp, AppContext]:
    argv = sys.argv[:]
    # 高 DPI
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    ctx = AppContext(root)
    app = LauncherApp(argv, ctx)
    return app, ctx
