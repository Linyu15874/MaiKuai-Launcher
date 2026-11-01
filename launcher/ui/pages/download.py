"""「下载新版」页面：选版本 → 选加载器 → 一键安装。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from launcher.ui import icons
from launcher.ui.app import AppContext
from launcher.core.installer import (fabric_loader_list, forge_version_list, neoforge_version_list,
                              quilt_loader_list, forge_promos)
from launcher.ui.widgets import Card, Badge, SegmentedBar, run_async


VERSION_TABS = ["正式版", "快照", "远古版"]


class DownloadPage(QWidget):
    def __init__(self, ctx: AppContext, win):
        super().__init__()
        self.ctx = ctx
        self.win = win
        self.manifest: list[dict] = []
        self.current_tab = 0
        self.cache: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        # ---------------- 版本选择
        card = Card("选择 Minecraft 版本", icon="layers", parent=self)
        self.tabs = SegmentedBar(VERSION_TABS)
        self.tabs.changed.connect(self.on_tab_changed)
        card.add(self.tabs)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("输入版本号筛选，如 1.20")
        self.filter_edit.textChanged.connect(self.fill_versions)
        card.add(self.filter_edit)
        self.version_list = QListWidget()
        self.version_list.setMinimumHeight(230)
        self.version_list.currentItemChanged.connect(lambda *_: self.on_version_selected())
        card.add(self.version_list)
        self.hint = QLabel("正在获取版本列表…")
        self.hint.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        card.add(self.hint)
        root.addWidget(card)

        # ---------------- 加载器
        lcard = Card("Mod 加载器（可留空）", icon="puzzle", parent=self)
        row = QHBoxLayout()
        row.addWidget(QLabel("加载器："))
        self.loader_combo = QComboBox()
        self.loader_combo.addItems(["不安装（原版）", "Fabric", "Quilt", "Forge", "NeoForge"])
        row.addWidget(self.loader_combo, 1)
        row.addWidget(QLabel("版本："))
        self.loader_version = QComboBox()
        self.loader_version.setMinimumWidth(190)
        row.addWidget(self.loader_version, 1)
        lcard.add_layout(row)
        self.loader_hint = QLabel("选择 Fabric / Quilt / Forge / NeoForge 后即可安装对应 Mod 环境")
        self.loader_hint.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        lcard.add(self.loader_hint)
        self.loader_combo.currentIndexChanged.connect(self.reload_loader_versions)
        root.addWidget(lcard)

        # ---------------- 安装
        icard = Card("开始安装", icon="download", parent=self)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("实例名称："))
        self.name_edit = QLineEdit()
        row2.addWidget(self.name_edit, 1)
        icard.add_layout(row2)
        self.isolation = QCheckBox("为这个版本创建独立游戏目录（推荐，Mod 与存档互不干扰）")
        self.isolation.setChecked(bool(ctx.config.get("version_isolation", True)))
        icard.add(self.isolation)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        icard.add(self.progress)
        self.progress_text = QLabel("")
        self.progress_text.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        icard.add(self.progress_text)
        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("安装并创建实例")
        self.install_btn.setObjectName("primary")
        self.install_btn.setMinimumHeight(38)
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self.start_install)
        btn_row.addWidget(self.install_btn)
        btn_row.addStretch(1)
        icard.add_layout(btn_row)
        root.addWidget(icard)
        root.addStretch(1)

        self.load_manifest()

    # ------------------------------------------------------------------ 列表
    def load_manifest(self, refresh: bool = False):
        self.hint.setText("正在获取版本列表…")

        def work(report):
            report("获取版本列表…", 0, 1, "")
            return self.ctx.installer.version_list(refresh)

        run_async(self, work, on_result=self.on_manifest,
                  on_error=lambda e: self.hint.setText(f"获取失败：{e.splitlines()[0]}"))

    def on_manifest(self, versions: list[dict]):
        self.manifest = versions
        self.hint.setText(f"共 {len(versions)} 个版本可用")
        self.fill_versions()
        if self.version_list.count():
            self.version_list.setCurrentRow(0)

    def on_tab_changed(self, index: int):
        self.current_tab = index
        self.fill_versions()

    def _type_filter(self, t: str) -> bool:
        if self.current_tab == 0:
            return t == "release"
        if self.current_tab == 1:
            return t in ("snapshot", "pending")
        return t in ("old_beta", "old_alpha", "old_version")

    def fill_versions(self):
        self.version_list.blockSignals(True)
        self.version_list.clear()
        kw = self.filter_edit.text().strip().lower()
        for v in self.manifest:
            if not self._type_filter(v.get("type", "release")):
                continue
            vid = v["id"]
            if kw and kw not in vid.lower():
                continue
            item = QListWidgetItem(f"{vid}    {v.get('releaseTime', '')[:10]}")
            item.setData(Qt.UserRole, v)
            self.version_list.addItem(item)
        self.version_list.blockSignals(False)
        if self.version_list.count() and self.version_list.currentRow() < 0:
            self.version_list.setCurrentRow(0)
        self.on_version_selected()

    def selected_version(self) -> dict | None:
        item = self.version_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def on_version_selected(self):
        v = self.selected_version()
        if not v:
            return
        installed = set(self.ctx.installer.installed_versions())
        tip = "已安装" if v["id"] in installed else ""
        self.hint.setText(f"已选择 {v['id']}（{v.get('type', '')[:12]}）  {tip}")
        self.reload_loader_versions()
        self.suggest_name()

    def suggest_name(self):
        v = self.selected_version()
        if not v:
            return
        loader = self.loader_combo.currentText()
        suffix = {"不安装（原版）": "", "Fabric": " Fabric", "Quilt": " Quilt",
                  "Forge": " Forge", "NeoForge": " NeoForge"}[loader]
        self.name_edit.setText(f"{v['id']}{suffix}")

    # ------------------------------------------------------------------ 加载器版本
    def reload_loader_versions(self, *_):
        self.loader_version.clear()
        self.loader_version.addItem("加载中…", None)
        v = self.selected_version()
        if not v:
            return
        mc = v["id"]
        kind = self.loader_combo.currentIndex()
        self.suggest_name()
        if kind == 0:
            self.loader_version.clear()
            self.loader_version.addItem("（不安装加载器）", "")
            return
        key = (kind, mc)
        if key in self.cache:
            self._fill_loader_versions(self.cache[key])
            return

        def work(_report):
            if kind == 1:
                return [x["version"] for x in fabric_loader_list(mc)]
            if kind == 2:
                return [x["version"] for x in quilt_loader_list(mc)]
            if kind == 3:
                return forge_version_list(mc)
            return neoforge_version_list(mc)

        def done(result):
            self.cache[key] = result
            self._fill_loader_versions(result)

        run_async(self, work, on_result=done,
                  on_error=lambda e: self._fill_loader_versions([], f"获取失败：{str(e).splitlines()[0]}"))

    def _fill_loader_versions(self, versions: list[str], error: str = ""):
        self.loader_version.clear()
        if error or not versions:
            self.loader_version.addItem(error or "无可用版本", "")
            self.loader_hint.setText("该 Minecraft 版本可能暂不支持此加载器")
            return
        for v in versions[:300]:
            self.loader_version.addItem(v, v)
        self.loader_hint.setText(f"共 {len(versions)} 个版本，默认选择最新的稳定版")

    # ------------------------------------------------------------------ 安装
    def start_install(self):
        v = self.selected_version()
        if not v:
            return
        kind = self.loader_combo.currentIndex()
        loader_ver = self.loader_version.currentData() or None
        name = self.name_edit.text().strip() or v["id"]
        iso = self.isolation.isChecked()
        self.install_btn.setEnabled(False)
        self.progress.setValue(0)

        def work(report):
            inst = self.ctx.installer
            mc = v["id"]
            if kind == 0:
                vid = inst.install_vanilla(mc)
            elif kind == 1:
                vid = inst.install_fabric(mc, loader_ver)
            elif kind == 2:
                vid = inst.install_quilt(mc, loader_ver)
            elif kind == 3:
                if not loader_ver:
                    raise RuntimeError("请选择 Forge 版本")
                java = self.ctx.config.get("java.path", "")
                vid = inst.install_forge(mc, loader_ver, java)
            else:
                if not loader_ver:
                    raise RuntimeError("请选择 NeoForge 版本")
                java = self.ctx.config.get("java.path", "")
                vid = inst.install_neoforge(mc, loader_ver, java)
            report("正在创建实例…", 1, 1, "")
            ins = self.ctx.instance_mgr.create(name, vid, self.ctx.paths.versions, isolation=iso)
            return ins

        def progress(text, cur, tot, detail):
            pct = int(cur * 100 / max(1, tot))
            self.progress.setValue(pct)
            self.progress_text.setText(f"{text}  {detail}"[:120])

        def error(e):
            self.install_btn.setEnabled(True)
            self.progress_text.setText(f"安装失败：{e.splitlines()[0]}")
            self.win.toast_msg(f"安装失败：{e.splitlines()[0]}", "error")

        def done(ins):
            self.install_btn.setEnabled(True)
            self.progress.setValue(100)
            self.progress_text.setText(f"安装完成：{ins.version_id}")
            self.ctx.refresh_instances()
            self.ctx.set_instance(ins)
            self.win.toast_msg(f"已安装 {ins.name}，可以启动游戏了！", "ok")
            self.win.switch_page("home")

        run_async(self, work, on_progress=progress, on_result=done, on_error=error)
