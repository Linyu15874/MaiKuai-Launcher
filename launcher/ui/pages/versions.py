"""「版本管理」页面：已安装版本列表、修复、删除、导入本地游戏。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from launcher.ui import icons
from launcher.ui.app import AppContext
from launcher.core.installer import detect_loader
from launcher.core.version import VersionProfile, read_json
from launcher.ui.widgets import Badge, Card, ask, choose_dir, msg, run_async


class VersionsPage(QWidget):
    COLUMNS = ["版本名称", "类型", "Game 版本", "大小", "目录"]

    def __init__(self, ctx: AppContext, win):
        super().__init__()
        self.ctx = ctx
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        card = Card("已安装的版本", icon="layers", parent=self)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(260)
        card.add(self.table)

        btns = QHBoxLayout()
        for text, icon_name, slot in [
            ("启动选中版本", "rocket", self.launch_selected),
            ("设为默认", "check", self.set_default),
            ("打开目录", "folder", self.open_dir),
            ("修复/重装", "refresh", self.repair),
            ("删除", "trash", self.remove),
            ("刷新", "refresh", self.refresh),
        ]:
            b = QPushButton(text)
            b.setIcon(icons.icon(icon_name, ctx.palette().accent, 16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        card.add_layout(btns)
        root.addWidget(card)

        imp = Card("导入已有的 Minecraft", icon="media",
                   subtitle="把其它启动器里的游戏版本加入列表（不会移动原文件）", parent=self)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(Path.home() / ".minecraft"))
        row.addWidget(self.path_edit, 1)
        b1 = QPushButton("浏览")
        b1.clicked.connect(self.browse)
        b2 = QPushButton("扫描并导入")
        b2.setObjectName("primary")
        b2.clicked.connect(self.import_versions)
        row.addWidget(b1)
        row.addWidget(b2)
        imp.add_layout(row)
        root.addWidget(imp)
        root.addStretch(1)

        ctx.instances_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ 数据
    def _dir_size(self, version_dir: Path) -> str:
        total = 0
        try:
            for f in version_dir.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return f"{total / 1024 / 1024:.1f} MB"

    def refresh(self):
        versions_dir = self.ctx.paths.versions
        ids = sorted(self.ctx.installer.installed_versions())
        self.table.setRowCount(0)
        for vid in ids:
            try:
                raw = read_json(versions_dir, vid)
            except Exception:
                continue
            loader = detect_loader(vid, versions_dir)
            base = raw.get("inheritsFrom") or raw.get("id", vid)
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                vid,
                {"vanilla": "原版", "fabric": "Fabric", "forge": "Forge",
                 "neoforge": "NeoForge", "quilt": "Quilt"}.get(loader, loader),
                base,
                self._dir_size(versions_dir / vid),
                str(versions_dir / vid),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, vid)
                self.table.setItem(row, col, item)
        if self.table.rowCount():
            self.table.selectRow(0)

    def selected_version_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    # ------------------------------------------------------------------ 操作
    def launch_selected(self):
        vid = self.selected_version_id()
        if not vid:
            return msg(self, "提示", "请先选择一个版本")
        ins = None
        for i in self.ctx.instances:
            if i.version_id == vid:
                ins = i
                break
        if ins is None:
            ins = self.ctx.instance_mgr.create(vid, vid, self.ctx.paths.versions,
                                               isolation=bool(self.ctx.config.get("version_isolation", True)))
            self.ctx.refresh_instances()
        self.ctx.set_instance(ins)
        self.win.launch_current()

    def set_default(self):
        vid = self.selected_version_id()
        if not vid:
            return
        for ins in self.ctx.instances:
            if ins.version_id == vid:
                self.ctx.set_instance(ins)
                self.win.toast_msg(f"已把 {ins.name} 设为默认版本", "ok")
                return
        ins = self.ctx.instance_mgr.create(vid, vid, self.ctx.paths.versions)
        self.ctx.refresh_instances()
        self.ctx.set_instance(ins)

    def open_dir(self):
        vid = self.selected_version_id()
        if vid:
            from launcher.core import paths as cp
            cp.open_in_explorer(self.ctx.paths.versions / vid)

    def repair(self):
        vid = self.selected_version_id()
        if not vid:
            return

        def work(report):
            inst = self.ctx.installer
            profile = VersionProfile.load(inst.p.versions, vid)
            report("重新下载主文件", 0, 4, vid)
            inst.download_client_jar(profile)
            report("重新下载依赖库", 1, 4, "")
            inst.download_libraries(profile)
            report("解压 native", 2, 4, "")
            inst.extract_natives(profile)
            report("重新下载资源", 3, 4, "")
            inst.download_assets(profile)
            return True

        run_async(self, work,
                  on_result=lambda _: (self.win.toast_msg(f"{vid} 修复完成", "ok"), self.refresh()),
                  on_error=lambda e: self.win.toast_msg(f"修复失败：{str(e).splitlines()[0]}", "error"))

    def remove(self):
        vid = self.selected_version_id()
        if not vid:
            return
        if not ask(self, "确认删除", f"确定要删除版本 {vid} 吗？\n它对应的游戏文件会被删除，Mod 与存档不受影响。"):
            return
        try:
            shutil.rmtree(self.ctx.paths.versions / vid, ignore_errors=True)
        except Exception as e:
            msg(self, "删除失败", str(e))
            return
        for ins in list(self.ctx.instances):
            if ins.version_id == vid:
                self.ctx.instance_mgr.remove(ins)
        self.ctx.refresh_instances()
        self.refresh()
        self.win.toast_msg(f"已删除 {vid}", "ok")

    def browse(self):
        d = choose_dir(self, "选择 .minecraft 目录", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def import_versions(self):
        base = Path(self.path_edit.text().strip())
        vdir = base / "versions"
        if not vdir.exists():
            return msg(self, "提示", "该目录下没有 versions 文件夹，看起来不是 Minecraft 游戏目录")
        count = 0
        for p in sorted(vdir.iterdir()):
            if not (p / f"{p.name}.json").exists():
                continue
            if any(i.version_id == p.name for i in self.ctx.instances):
                continue
            self.ctx.instance_mgr.add_from_existing(p.name, p.name, self.ctx.game_root, self.ctx.paths.versions)
            count += 1
        self.ctx.refresh_instances()
        msg(self, "导入完成", f"已导入 {count} 个版本的启动入口" if count else "没有发现新的版本")
