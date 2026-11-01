"""「设置」与「关于」页面。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from launcher.ui import icons
from launcher.ui.app import AppContext
from launcher.core import java as java_mod
from launcher.core import paths as core_paths
from launcher.ui.widgets import Card, choose_dir, choose_file, msg, run_async
from launcher.ui.dialogs import FirstRunDialog


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, win):
        super().__init__()
        self.ctx = ctx
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)
        pal = ctx.palette()

        # ---------------- 启动设置
        c1 = Card("启动设置", icon="rocket", parent=self)
        form = QFormLayout()
        # 内存
        mem_row = QHBoxLayout()
        self.mem_min = self._spin(128, 32768, ctx.config.get("memory.min", 512))
        self.mem_max = self._spin(512, 131072, ctx.config.get("memory.max", 0) or java_mod.recommend_memory_mb())
        self.mem_auto = QCheckBox("自动推荐")
        self.mem_auto.setChecked(bool(ctx.config.get("memory.auto", True)))
        self.mem_auto.toggled.connect(self._toggle_mem_auto)
        mem_row.addWidget(QLabel("最小"))
        mem_row.addWidget(self.mem_min)
        mem_row.addWidget(QLabel("MB   最大"))
        mem_row.addWidget(self.mem_max)
        mem_row.addWidget(QLabel("MB"))
        mem_row.addWidget(self.mem_auto)
        mem_row.addStretch(1)
        form.addRow("内存分配：", mem_row)
        self.rec_label = QLabel("")
        self._update_rec_label()
        form.addRow("", self.rec_label)
        # 分辨率
        res_row = QHBoxLayout()
        self.res_width = self._spin(320, 7680, ctx.config.get("resolution.width", 854))
        self.res_height = self._spin(240, 4320, ctx.config.get("resolution.height", 480))
        self.fullscreen = QCheckBox("全屏启动")
        self.fullscreen.setChecked(bool(ctx.config.get("resolution.fullscreen", False)))
        self.custom_res = QCheckBox("自定义窗口大小")
        self.custom_res.setChecked(True)
        res_row.addWidget(self.res_width)
        res_row.addWidget(QLabel("×"))
        res_row.addWidget(self.res_height)
        res_row.addWidget(self.custom_res)
        res_row.addWidget(self.fullscreen)
        res_row.addStretch(1)
        form.addRow("游戏窗口：", res_row)
        self.server_edit = QLineEdit(ctx.config.get("server.address", ""))
        self.server_edit.setPlaceholderText("留空则不自动进服，格式：play.example.com:25565")
        form.addRow("默认服务器：", self.server_edit)
        self.jvm_edit = QLineEdit(ctx.config.get("jvm_args", ""))
        self.jvm_edit.setPlaceholderText("例如 -XX:+DisableExplicitGC")
        form.addRow("JVM 参数：", self.jvm_edit)
        self.game_args_edit = QLineEdit(ctx.config.get("game_args", ""))
        form.addRow("游戏参数：", self.game_args_edit)
        c1.add_layout(form)
        row = QHBoxLayout()
        b = QPushButton("保存启动设置")
        b.setObjectName("primary")
        b.clicked.connect(self.save_basic)
        row.addWidget(b)
        row.addStretch(1)
        c1.add_layout(row)
        root.addWidget(c1)

        # ---------------- Java
        c2 = Card("Java 运行时", icon="java", parent=self)
        jrow = QHBoxLayout()
        self.java_combo = QComboBox()
        self.java_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.java_combo.setMinimumWidth(360)
        jrow.addWidget(self.java_combo, 1)
        b_scan = QPushButton("扫描")
        b_scan.setIcon(icons.icon("refresh", pal.accent, 16))
        b_scan.clicked.connect(self.scan_java)
        b_browse = QPushButton("浏览…")
        b_browse.clicked.connect(self.browse_java)
        jrow.addWidget(b_scan)
        jrow.addWidget(b_browse)
        c2.add_layout(jrow)
        self.java_auto = QCheckBox("自动选择合适的 Java（推荐）")
        self.java_auto.setChecked(bool(ctx.config.get("java.auto", True)))
        self.java_auto.toggled.connect(lambda v: (self.java_combo.setEnabled(not v), self.ctx.config.set("java.auto", v)))
        c2.add(self.java_auto)
        self.java_hint = QLabel("")
        self.java_hint.setStyleSheet("color: %s;" % pal.text_dim)
        c2.add(self.java_hint)
        dl = QHBoxLayout()
        dl.addWidget(QLabel("下载官方 Temurin JDK："))
        for v in (8, 17, 21):
            b = QPushButton(f"Java {v}")
            b.clicked.connect(lambda _=False, ver=v: self.download_java(ver))
            dl.addWidget(b)
        dl.addStretch(1)
        c2.add_layout(dl)
        root.addWidget(c2)

        # ---------------- 游戏目录
        c3 = Card("游戏目录", icon="folder", parent=self)
        row3 = QHBoxLayout()
        self.root_edit = QLineEdit(str(ctx.game_root))
        row3.addWidget(self.root_edit, 1)
        b_change = QPushButton("浏览")
        b_change.clicked.connect(self.browse_root)
        b_open = QPushButton("打开")
        b_open.clicked.connect(lambda: core_paths.open_in_explorer(Path(self.root_edit.text())))
        row3.addWidget(b_change)
        row3.addWidget(b_open)
        c3.add_layout(row3)
        self.isolation = QCheckBox("新建实例时使用独立目录（Mod、存档、设置互不干扰）")
        self.isolation.setChecked(bool(ctx.config.get("version_isolation", True)))
        self.isolation.toggled.connect(lambda v: ctx.config.set("version_isolation", v))
        c3.add(self.isolation)
        row3b = QHBoxLayout()
        b_apply_root = QPushButton("应用目录（重启后生效）")
        b_apply_root.setObjectName("primary")
        b_apply_root.clicked.connect(self.apply_root)
        row3b.addWidget(b_apply_root)
        row3b.addStretch(1)
        c3.add_layout(row3b)
        root.addWidget(c3)

        # ---------------- 下载
        c4 = Card("下载与网络", icon="cloud", parent=self)
        f4 = QFormLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("官方源（海外推荐）", "official")
        self.source_combo.addItem("BMCLAPI 镜像（国内推荐）", "bmclapi")
        idx = self.source_combo.findData(ctx.config.get("source", "official"))
        self.source_combo.setCurrentIndex(max(0, idx))
        f4.addRow("下载源：", self.source_combo)
        self.threads = self._spin(1, 256, ctx.config.get("download_threads", 32))
        f4.addRow("下载线程：", self.threads)
        self.mr_api = QLineEdit(ctx.config.get("modrinth.api", "https://api.modrinth.com/v2"))
        f4.addRow("Modrinth API：", self.mr_api)
        self.ms_id = QLineEdit(ctx.config.get("auth.ms_client_id", "000000004C1D1682"))
        self.ms_id.setToolTip("微软登录使用的 Azure 应用 Client ID，个人可在 Azure 门户免费注册一个")
        f4.addRow("微软 Client ID：", self.ms_id)
        self.yg_default = QLineEdit(ctx.config.get("auth.yggdrasil_default", "https://littleskin.cn/api/yggdrasil"))
        f4.addRow("默认外置登录：", self.yg_default)
        self.verify_ssl = QCheckBox("验证 HTTPS 证书")
        self.verify_ssl.setChecked(bool(ctx.config.get("auth.https_verify", True)))
        f4.addRow("", self.verify_ssl)
        c4.add_layout(f4)
        row4 = QHBoxLayout()
        b_save_net = QPushButton("保存网络设置")
        b_save_net.setObjectName("primary")
        b_save_net.clicked.connect(self.save_net)
        row4.addWidget(b_save_net)
        row4.addStretch(1)
        c4.add_layout(row4)
        root.addWidget(c4)

        # ---------------- 外观 / 行为
        c5 = Card("外观与启动行为", icon="media", parent=self)
        f5 = QFormLayout()
        self.theme_combo = QComboBox()
        for label, key in [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")]:
            self.theme_combo.addItem(label, key)
        i5 = self.theme_combo.findData(ctx.config.get("theme", "auto"))
        self.theme_combo.setCurrentIndex(max(0, i5))
        self.theme_combo.currentIndexChanged.connect(self.apply_theme)
        f5.addRow("主题：", self.theme_combo)
        self.hide_launcher = QCheckBox("启动游戏后隐藏启动器")
        self.hide_launcher.setChecked(bool(ctx.config.get("launch.hide_launcher_when_launch", True)))
        self.close_launcher = QCheckBox("启动游戏后退出启动器")
        self.close_launcher.setChecked(bool(ctx.config.get("launch.close_launcher_when_launch", False)))
        self.show_console = QCheckBox("启动时显示游戏日志窗口")
        self.show_console.setChecked(bool(ctx.config.get("launch.show_console", True)))
        f5.addRow("", self.hide_launcher)
        f5.addRow("", self.close_launcher)
        f5.addRow("", self.show_console)
        c5.add_layout(f5)
        root.addWidget(c5)

        row_end = QHBoxLayout()
        b_reset = QPushButton("打开数据目录")
        b_reset.clicked.connect(lambda: core_paths.open_in_explorer(ctx.dirs["root"]))
        b_first = QPushButton("重新运行首次设置向导")
        b_first.clicked.connect(lambda: FirstRunDialog(ctx, self).exec())
        row_end.addWidget(b_reset)
        row_end.addWidget(b_first)
        row_end.addStretch(1)
        root.addLayout(row_end)
        root.addStretch(1)

        self._toggle_mem_auto(self.mem_auto.isChecked())
        self.scan_java()

    # ------------------------------------------------------------------ 工具
    def _spin(self, lo: int, hi: int, val: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(int(val or lo))
        s.setSingleStep(128 if hi > 1000 else 1)
        s.setSuffix("")
        return s

    def _update_rec_label(self):
        from launcher.core.java import recommend_memory_mb
        self.rec_label.setText(f"本机物理内存推荐最大值：{recommend_memory_mb()} MB")

    def _toggle_mem_auto(self, checked: bool):
        self.mem_max.setEnabled(not checked)
        if checked:
            self.mem_max.setValue(java_mod.recommend_memory_mb())

    # ------------------------------------------------------------------ 各分组保存
    def save_basic(self):
        c = self.ctx.config
        c.set("memory.min", self.mem_min.value())
        c.set("memory.max", self.mem_max.value())
        c.set("memory.auto", self.mem_auto.isChecked())
        c.set("resolution.width", self.res_width.value())
        c.set("resolution.height", self.res_height.value())
        c.set("resolution.fullscreen", self.fullscreen.isChecked())
        c.set("server.address", self.server_edit.text().strip())
        c.set("jvm_args", self.jvm_edit.text().strip())
        c.set("game_args", self.game_args_edit.text().strip())
        self.custom_res.isChecked()
        self.win.toast_msg("启动设置已保存", "ok")

    def save_net(self):
        c = self.ctx.config
        c.set("source", self.source_combo.currentData())
        c.set("download_threads", self.threads.value())
        c.set("modrinth.api", self.mr_api.text().strip() or "https://api.modrinth.com/v2")
        c.set("auth.ms_client_id", self.ms_id.text().strip())
        c.set("auth.yggdrasil_default", self.yg_default.text().strip())
        c.set("auth.https_verify", self.verify_ssl.isChecked())
        self.ctx.rebuild()
        self.win.toast_msg("网络设置已保存并生效", "ok")

    def browse_root(self):
        d = choose_dir(self, "选择游戏文件保存目录", self.root_edit.text())
        if d:
            self.root_edit.setText(d)

    def apply_root(self):
        p = self.root_edit.text().strip()
        if not p:
            return
        self.ctx.config.set("game_root", p)
        try:
            Path(p).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return msg(self, "目录无效", str(e))
        self.ctx.rebuild()
        self.win.toast_msg(f"游戏目录已切换到 {p}", "ok")

    def browse_java(self):
        f = choose_file(self, "选择 java 可执行文件", "",
                        "java" if not core_paths.IS_WINDOWS else "java.exe")
        if f:
            self.java_combo.insertItem(0, f, f)
            self.java_combo.setCurrentIndex(0)
            self.java_auto.setChecked(False)
            self.ctx.config.set("java.path", f)
            self.ctx.config.set("java.auto", False)

    def scan_java(self):
        self.java_hint.setText("正在扫描已安装的 Java…")
        self.java_combo.clear()

        def work(_r):
            items = java_mod.scan_system()
            try:
                items += java_mod.scan_runtime_dir(self.ctx.dirs["runtime"])
            except Exception:
                pass
            return items

        def done(items):
            self.java_combo.clear()
            seen = set()
            for j in items:
                if str(j.path) in seen:
                    continue
                seen.add(str(j.path))
                self.java_combo.addItem(str(j), str(j.path))
            cur = self.ctx.config.get("java.path", "")
            if cur:
                idx = self.java_combo.findData(str(cur))
                if idx >= 0:
                    self.java_combo.setCurrentIndex(idx)
            if not items:
                self.java_hint.setText("没有找到 Java，请点击下方按钮下载，或手动浏览选择")
            else:
                self.java_hint.setText(f"共发现 {len(items)} 个 Java，1.17 以上版本建议使用 Java 17 或 21")

        run_async(self, work, on_result=done,
                  on_error=lambda e: self.java_hint.setText(f"扫描失败：{str(e).splitlines()[0]}"))

    def download_java(self, feature: int):
        self.java_hint.setText(f"正在下载 Temurin Java {feature}，请耐心等待…")

        def work(report):
            report("下载 Java", 0, 2, f"Temurin {feature}")
            return java_mod.install_managed_java(feature, self.ctx.dirs["runtime"])

        def done(info):
            if info is None:
                self.java_hint.setText("下载完成，但未能识别 Java，请手动浏览选择")
                return
            self.java_hint.setText(f"已安装：{info}")
            self.java_combo.insertItem(0, str(info), str(info.path))
            self.java_combo.setCurrentIndex(0)
            self.java_auto.setChecked(False)
            self.ctx.config.set("java.path", str(info.path))
            self.ctx.config.set("java.auto", False)
            self.win.toast_msg(f"Java {feature} 安装完成", "ok")

        run_async(self, work, on_result=done,
                  on_error=lambda e: self.java_hint.setText(f"下载失败：{str(e).splitlines()[0]}"))

    def apply_theme(self):
        key = self.theme_combo.currentData()
        self.ctx.config.set("theme", key)
        self.win.app.refresh_theme()


# --------------------------------------------------------------------------- 关于


class AboutPage(QWidget):
    def __init__(self, ctx: AppContext, win):
        super().__init__()
        pal = ctx.palette()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        head = Card("", icon="wen", parent=self)
        head.title_label.hide()
        title = QLabel("麦块启动器  ·  PCL-Py")
        f = title.font()
        f.setPointSize(20)
        f.setBold(True)
        title.setFont(f)
        head.add(title)
        ver = QLabel(f"版本 {core_paths.APP_VERSION}　{ core_paths.APP_CODENAME }　·　跨平台 · Python + Qt")
        ver.setStyleSheet("color: %s;" % pal.text_dim)
        head.add(ver)
        root.addWidget(head)

        c = Card("项目说明", icon="info", parent=self)
        text = QLabel(
            "这是一个完全开源、可自由使用的 Minecraft 启动器实现。\n\n"
            "功能上参考了 PCL2 与 HMCL 的思路：卡片式界面、版本隔离、"
            "离线/外置/微软三种登录、Fabric 与 Quilt 的免安装器装配、"
            "Forge 与 NeoForge 的官方安装器静默安装、Modrinth 资源市场、"
            "以及游戏崩溃日志的分析助手。\n\n"
            "本项目为独立实现（Python / PySide6），不含上述项目的源代码，"
            "仅在交互与视觉上对它们致敬。")
        text.setWordWrap(True)
        c.add(text)
        root.addWidget(c)

        c2 = Card("致谢", icon="heart", parent=self)
        thanks = QLabel(
            "• PCL2（Plain Craft Launcher 2）—— 卡片式界面与整体交互灵感\n"
            "• HMCL —— 账号体系、Mod 加载器支持的设计参考\n"
            "• BMCLAPI —— 国内镜像源\n"
            "• Modrinth —— 资源市场数据\n"
            "• Fabric / Quilt / Forge / NeoForge —— 开放的元数据与 Maven 仓库\n"
            "• Eclipse Temurin（Adoptium）—— Java 运行时")
        thanks.setWordWrap(True)
        c2.add(thanks)
        root.addWidget(c2)

        c3 = Card("信息与免责声明", icon="warning", parent=self)
        disclaimer = QLabel(
            "• 本软件为第三方开源启动器，与 Mojang Studios、Microsoft 无隶属关系。\n"
            "• 使用正版登录时，Minecraft 的正版验证由官方服务完成，凭据保存在本机。"
            "请妥善保管自己的登录信息。\n"
            "• 通过 Microsoft 账号登录使用的是 Azure 公共客户端流程，"
            "默认 Client ID 为社区公开流传的值；若失效，可在设置里替换为自己在 Azure 注册的应用 ID。\n"
            "• 下载第三方 Mod 请注意其开源协议与安全风险，本软件不对 Mod 内容负责。")
        disclaimer.setWordWrap(True)
        c3.add(disclaimer)
        row = QHBoxLayout()
        b1 = QPushButton("打开数据目录")
        b1.clicked.connect(lambda: core_paths.open_in_explorer(ctx.dirs["root"]))
        b2 = QPushButton("打开日志目录")
        b2.clicked.connect(lambda: core_paths.open_in_explorer(ctx.dirs["logs"]))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        c3.add_layout(row)
        root.addWidget(c3)
        root.addStretch(1)
