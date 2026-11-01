"""「我的家」页面：版本选择、启动、账号、快捷操作。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from launcher.ui import icons
from launcher.ui.widgets import Badge, Card
from launcher.ui.app import AppContext
from launcher.core.launch import LaunchSettings, analyze_log
from launcher.core import paths as core_paths


def make_avatar(name: str, color: str, size: int = 44) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QColor("#FFFFFF"))
    f = QFont()
    f.setPointSize(size // 3)
    f.setBold(True)
    p.setFont(f)
    ch = (name or "?")[0].upper()
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    return pm


class InstanceSelector(QWidget):
    """横向「上一个 / 当前版本 / 下一个」选择器，PCL2 风格。"""

    instance_changed = Signal(object)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(icons.icon("search", ctx.palette().text_dim, 18))
        self.btn_prev.setFixedWidth(34)
        self.btn_prev.setText("‹")
        self.btn_next = QPushButton()
        self.btn_next.setText("›")
        self.btn_next.setFixedWidth(34)
        self.label = QLabel("未选择版本")
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.label.setFont(f)
        layout.addWidget(self.btn_prev)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.btn_next)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))

    def step(self, delta: int):
        items = self.ctx.instances
        if not items:
            return
        cur = self.ctx.current_instance()
        idx = items.index(cur) if cur in items else 0
        nxt = items[(idx + delta) % len(items)]
        self.ctx.set_instance(nxt)
        self.refresh()

    def refresh(self):
        ins = self.ctx.current_instance()
        if ins is None:
            self.label.setText("还没有任何版本，去「下载新版」安装吧")
            self.label.setStyleSheet("color: %s;" % self.ctx.palette().text_dim)
            return
        self.label.setStyleSheet("")
        self.label.setText(f"{ins.name}")
        if self.receivers(self.instance_changed) or True:
            self.instance_changed.emit(ins)


class HomePage(QWidget):
    def __init__(self, ctx: AppContext, win):
        super().__init__()
        self.ctx = ctx
        self.win = win
        self._crash_log = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        # ---------------- 启动卡片
        launch_card = Card("", parent=self)
        launch_card.title_label.hide()
        head = QHBoxLayout()
        self.selector = InstanceSelector(ctx, self)
        head.addWidget(self.selector, 1)
        self.version_badge = Badge("原版", "vanilla")
        self.loader_badge = Badge("Minecraft", "release")
        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        head.addWidget(self.loader_badge)
        head.addWidget(self.version_badge)
        launch_card.add_layout(head)

        mid = QHBoxLayout()
        self.launch_btn = QPushButton("  启动游戏")
        self.launch_btn.setObjectName("primary")
        self.launch_btn.setIcon(icons.icon("rocket", "#FFFFFF", 20, 2.0))
        self.launch_btn.setIconSize(self.launch_btn.iconSize())
        self.launch_btn.setMinimumHeight(46)
        self.launch_btn.setMinimumWidth(180)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        self.launch_btn.setFont(f)
        self.launch_btn.clicked.connect(lambda: win.launch_current())
        mid.addWidget(self.launch_btn, 0)
        info_col = QVBoxLayout()
        self.info_version = QLabel("版本：-")
        self.info_java = QLabel("Java：-")
        self.info_mem = QLabel("内存：-")
        for lb in (self.info_version, self.info_java, self.info_mem):
            lb.setStyleSheet("color: %s;" % ctx.palette().text_dim)
            info_col.addWidget(lb)
        mid.addLayout(info_col, 1)
        mid.addStretch(1)
        launch_card.add_layout(mid)
        launch_card.add(self.detail_label)
        root.addWidget(launch_card)

        # ---------------- 账号
        acc_card = Card("当前账号", icon="user", parent=self)
        row = QHBoxLayout()
        self.avatar = QLabel()
        self.avatar.setFixedSize(46, 46)
        row.addWidget(self.avatar)
        col = QVBoxLayout()
        self.acc_name = QLabel("未登录")
        f2 = QFont()
        f2.setPointSize(12)
        f2.setBold(True)
        self.acc_name.setFont(f2)
        self.acc_type = Badge("离线", "vanilla")
        hrow = QHBoxLayout()
        hrow.addWidget(self.acc_name)
        hrow.addWidget(self.acc_type)
        hrow.addStretch(1)
        col.addLayout(hrow)
        self.acc_uuid = QLabel("")
        self.acc_uuid.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        col.addWidget(self.acc_uuid)
        row.addLayout(col, 1)
        btn_switch = QPushButton("切换账号")
        btn_switch.clicked.connect(win.show_accounts)
        row.addWidget(btn_switch)
        acc_card.add_layout(row)
        root.addWidget(acc_card)

        # ---------------- 快捷操作
        quick = Card("快捷操作", icon="folder", parent=self)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.quick_buttons: list[tuple[QPushButton, str]] = []
        items = [
            ("游戏目录", "folder", lambda: self.open_path(self.ctx.current_instance().game_dir if self.ctx.current_instance() else self.ctx.game_root)),
            ("Mod 目录", "puzzle", lambda: self.open_path(self.mods_dir())),
            ("资源包", "media", lambda: self.open_path(self.sub("resourcepacks"))),
            ("光影包", "media", lambda: self.open_path(self.sub("shaderpacks"))),
            ("存档", "layers", lambda: self.open_path(self.sub("saves"))),
            ("截图", "media", lambda: self.open_path(self.sub("screenshots"))),
            ("崩溃报告", "warning", lambda: self.open_path(self.sub("crash-reports"))),
            ("查看日志", "console", lambda: win.show_console(self._crash_log or "(暂无日志)")),
        ]
        for i, (name, icon, slot) in enumerate(items):
            b = QPushButton(name)
            b.setIcon(icons.icon(icon, ctx.palette().accent, 18))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            grid.addWidget(b, i // 4, i % 4)
        quick.add_layout(grid)
        root.addWidget(quick)

        # ---------------- 崩溃助手 / 资源推荐
        self.crash_card = Card("启动失败助手", icon="warning", parent=self)
        self.crash_label = QLabel("尚无崩溃记录")
        self.crash_label.setWordWrap(True)
        self.crash_card.add(self.crash_label)
        btn_open_report = QPushButton("打开崩溃报告目录")
        btn_open_report.clicked.connect(lambda: self.open_path(self.sub("crash-reports")))
        self.crash_card.add(btn_open_report)
        self.crash_card.hide()
        root.addWidget(self.crash_card)

        links = Card("社区资源", icon="star", parent=self)
        grid2 = QGridLayout()
        grid2.setSpacing(8)
        sites = [
            ("Modrinth（Mod 下载）", "https://modrinth.com"),
            ("CurseForge", "https://www.curseforge.com/minecraft"),
            ("我的世界中文百科", "https://zh.minecraft.wiki"),
            ("Fabric 官网", "https://fabricmc.net"),
            ("Forge 官网", "https://forums.minecraftforge.net"),
            ("MCBBS 镜像源", "https://bmclapidoc.bangbang93.com"),
        ]
        for i, (title, url) in enumerate(sites):
            b = QPushButton(title)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(icons.icon("cloud", ctx.palette().accent, 16))
            b.clicked.connect(lambda _=False, u=url: self.open_url(u))
            grid2.addWidget(b, i // 3, i % 3)
        links.add_layout(grid2)
        root.addWidget(links)

        root.addStretch(1)
        self.ctx.instance_changed.connect(self.on_instance_changed)
        self.ctx.instances_changed.connect(self.refresh)
        ctx.account_changed.connect(self.refresh_account)
        self.refresh()

    # ------------------------------------------------------------------ 行为
    def sub(self, name: str) -> Path:
        ins = self.ctx.current_instance()
        base = ins.game_dir if ins else self.ctx.game_root
        p = Path(base) / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def mods_dir(self) -> Path:
        p = self.sub("mods")
        return p

    def open_path(self, path: Path):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        core_paths.open_in_explorer(p)

    def open_url(self, url: str):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def refresh_account(self, acc=None):
        acc = acc or self.ctx.current_account
        pal = self.ctx.palette()
        if acc is None:
            self.avatar.setPixmap(make_avatar("?", pal.text_dim))
            self.acc_name.setText("未登录")
            self.acc_type.setText("离线")
            self.acc_uuid.setText("点击右侧按钮登录或创建离线账号")
            return
        color = {"offline": "#7A8794", "microsoft": "#2E8CD8", "yggdrasil": "#21A366"}[acc.type]
        self.avatar.setPixmap(make_avatar(acc.username, color))
        self.acc_name.setText(acc.username)
        self.acc_type.setText({"offline": "离线", "microsoft": "微软", "yggdrasil": "外置"}[acc.type])
        self.acc_uuid.setText(f"UUID：{acc.uuid}")
        self.acc_type.setStyleSheet(f"background:{color}22; color:{color}; border-radius:5px; padding:2px 7px;")

    def refresh(self):
        self.selector.refresh()
        ins = self.ctx.current_instance()
        self.on_instance_changed(ins)
        self.refresh_account()

    def on_instance_changed(self, ins):
        pal = self.ctx.palette()
        if ins is None:
            self.info_version.setText("版本：-")
            self.version_badge.hide()
            self.loader_badge.hide()
            self.detail_label.setText("还没有任何版本，请到「下载新版」页面安装一个 Minecraft 版本")
            return
        self.version_badge.show()
        self.loader_badge.show()
        base = ins.base_version or ins.version_id
        self.version_badge.setText(base)
        loader_txt = {"vanilla": "原版", "fabric": "Fabric", "forge": "Forge",
                      "neoforge": "NeoForge", "quilt": "Quilt"}.get(ins.loader, ins.loader)
        self.loader_badge.setText(loader_txt)
        self.loader_badge.setStyleSheet(
            f"background:{pal.accent_soft}; color:{pal.accent}; border-radius:5px; padding:2px 7px; font-weight:600;")
        self.info_version.setText(f"版本：{ins.version_id}")
        java = ins.java_path or self.ctx.config.get("java.path", "")
        if not java and self.ctx.config.get("java.auto", True):
            java = "自动选择（推荐）"
        self.info_java.setText(f"Java：{java or '未设置'}")
        mem_max = ins.max_memory or self.ctx.config.get("memory.max", 0)
        if not mem_max:
            from launcher.core.java import recommend_memory_mb
            mem_max = recommend_memory_mb()
        mem_min = ins.min_memory or self.ctx.config.get("memory.min", 512)
        self.info_mem.setText(f"内存：{mem_min} ~ {mem_max} MB")
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(ins.last_played)) if ins.last_played else "从未启动"
        played = f"，累计 {ins.play_seconds // 3600} 小时 {(ins.play_seconds % 3600) // 60} 分钟" if ins.play_seconds else ""
        self.detail_label.setText(f"上次启动：{last}{played}　·　目录：{ins.game_dir}")

    def report_crash(self, log: str, exit_code: int):
        """游戏进程结束时由主窗口调用。"""
        self._crash_log = log
        hits = analyze_log(log)
        if exit_code == 0:
            self.crash_card.hide()
            return
        if not hits:
            return
        text = "\n".join(f"• <b>{t}</b>：{d}" for t, d in hits[:3])
        self.crash_label.setText(text)
        self.crash_card.set_subtitle("根据日志分析，可能的原因如下")
        self.crash_card.show()
