"""「Mod 市场」页面：Modrinth 搜索安装 + 本地 Mod 启停管理。"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from launcher.ui import icons
from launcher.ui.app import AppContext
from launcher.core.modrinth import (ModrinthClient, ModFile, PROJECT_TYPES, SORT_INDEX)
from launcher.ui.widgets import Card, ask, msg, run_async


class ModsPage(QWidget):
    def __init__(self, ctx: AppContext, win):
        super().__init__()
        self.ctx = ctx
        self.win = win
        self.client = ModrinthClient(ctx.config.get("modrinth.api", "https://api.modrinth.com/v2"))
        self.hits: list = []
        self.offset = 0
        self.query = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        target = Card("目标实例", icon="layers", parent=self)
        row = QHBoxLayout()
        self.instance_combo = QComboBox()
        self.instance_combo.currentIndexChanged.connect(lambda *_: (self.fill_installed(), self.update_loader()))
        row.addWidget(self.instance_combo, 1)
        self.loader_label = QLabel("")
        self.loader_label.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        row.addWidget(self.loader_label)
        b_open = QPushButton("打开 Mod 目录")
        b_open.setIcon(icons.icon("folder", ctx.palette().accent, 16))
        b_open.clicked.connect(self.open_mods_dir)
        row.addWidget(b_open)
        target.add_layout(row)
        root.addWidget(target)

        search_card = Card("搜索 Modrinth", icon="search", parent=self)
        srow = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索模组、整合包、材质包…（支持中文？仅英文更全）")
        self.search_edit.returnPressed.connect(self.do_search)
        srow.addWidget(self.search_edit, 1)
        self.type_combo = QComboBox()
        for k, v in PROJECT_TYPES.items():
            self.type_combo.addItem(v, k)
        srow.addWidget(self.type_combo)
        self.sort_combo = QComboBox()
        for k in SORT_INDEX:
            self.sort_combo.addItem(k)
        srow.addWidget(self.sort_combo)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setObjectName("primary")
        self.btn_search.clicked.connect(self.do_search)
        srow.addWidget(self.btn_search)
        search_card.add_layout(srow)

        self.result_list = QListWidget()
        self.result_list.setMinimumHeight(200)
        self.result_list.itemSelectionChanged.connect(self.show_detail)
        search_card.add(self.result_list)
        self.detail_label = QLabel("选择一个项目查看详情")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: %s;" % ctx.palette().text_dim)
        search_card.add(self.detail_label)

        opt = QHBoxLayout()
        self.dep_check = QCheckBox("同时安装必需依赖")
        self.dep_check.setChecked(True)
        opt.addWidget(self.dep_check)
        opt.addStretch(1)
        self.btn_prev = QPushButton("上一页")
        self.btn_prev.clicked.connect(lambda: self.do_search(delta=-20))
        self.btn_next = QPushButton("下一页")
        self.btn_next.clicked.connect(lambda: self.do_search(delta=20))
        self.btn_install = QPushButton("安装所选")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self.install_selected)
        opt.addWidget(self.btn_prev)
        opt.addWidget(self.btn_next)
        opt.addWidget(self.btn_install)
        search_card.add_layout(opt)
        self.progress = QProgressBar()
        search_card.add(self.progress)
        root.addWidget(search_card)

        local = Card("本地 Mod", icon="puzzle",
                     subtitle="勾选表示启用；取消勾选会把文件重命名为 .disabled", parent=self)
        self.local_list = QListWidget()
        self.local_list.setMinimumHeight(150)
        self.local_list.itemChanged.connect(self.on_local_toggled)
        local.add(self.local_list)
        lrow = QHBoxLayout()
        bt = QPushButton("刷新")
        bt.setIcon(icons.icon("refresh", ctx.palette().accent, 16))
        bt.clicked.connect(self.fill_installed)
        bt2 = QPushButton("删除所选")
        bt2.setIcon(icons.icon("trash", ctx.palette().danger, 16))
        bt2.setObjectName("danger")
        bt2.clicked.connect(self.delete_local)
        bt3 = QPushButton("打开目录")
        bt3.setIcon(icons.icon("folder", ctx.palette().accent, 16))
        bt3.clicked.connect(self.open_mods_dir)
        lrow.addWidget(bt)
        lrow.addWidget(bt2)
        lrow.addWidget(bt3)
        lrow.addStretch(1)
        local.add_layout(lrow)
        root.addWidget(local)
        root.addStretch(1)

        ctx.instances_changed.connect(self.refresh_instances)
        self.refresh_instances()

    # ------------------------------------------------------------------ 实例
    def refresh_instances(self):
        self.instance_combo.blockSignals(True)
        self.instance_combo.clear()
        for ins in self.ctx.instances:
            self.instance_combo.addItem(f"{ins.name}（{ins.version_id}）", ins.id)
        cur = self.ctx.current_instance()
        if cur:
            idx = self.instance_combo.findData(cur.id)
            if idx >= 0:
                self.instance_combo.setCurrentIndex(idx)
        self.instance_combo.blockSignals(False)
        self.fill_installed()
        self.update_loader()

    def current_instance(self):
        iid = self.instance_combo.currentData()
        return self.ctx.instance_mgr.get(iid) if iid else None

    def update_loader(self):
        ins = self.current_instance()
        if not ins:
            self.loader_label.setText("先创建一个实例")
            return
        self.loader_label.setText(f"加载器：{ins.loader}　游戏版本：{ins.base_version or ins.version_id}")

    def open_mods_dir(self):
        ins = self.current_instance()
        if not ins:
            return msg(self, "提示", "请先选择实例")
        from launcher.core import paths as cp
        d = Path(ins.game_dir) / "mods"
        d.mkdir(parents=True, exist_ok=True)
        cp.open_in_explorer(d)

    # ------------------------------------------------------------------ 搜索
    def do_search(self, *_, delta: int = 0):
        self.query = self.search_edit.text().strip()
        self.offset = max(0, self.offset + delta)
        self.btn_search.setEnabled(False)
        self.result_list.clear()
        self.result_list.addItem("搜索中…")
        kwargs = {
            "query": self.query, "project_type": self.type_combo.currentData(),
            "index": SORT_INDEX[self.sort_combo.currentText()],
            "limit": 20, "offset": self.offset,
        }

        def work(_report):
            return self.client.search(**kwargs)

        def done(result):
            self.btn_search.setEnabled(True)
            self.hits, total = result
            self.result_list.clear()
            for h in self.hits:
                item = QListWidgetItem(f"{h.title}   ·   ⬇ {h.downloads:,}   ·   ★ {h.follows:,}")
                item.setData(Qt.UserRole, h)
                self.result_list.addItem(item)
            if self.result_list.count():
                self.result_list.setCurrentRow(0)
            self.detail_label.setText(f"共 {total} 个结果，第 {self.offset // 20 + 1} 页"
                                      + ("" if self.hits else "（没有更多了）"))

        def err(e):
            self.btn_search.setEnabled(True)
            self.result_list.clear()
            self.detail_label.setText(f"搜索失败：{str(e).splitlines()[0]}")

        run_async(self, work, on_result=done, on_error=err)

    def show_detail(self):
        item = self.result_list.currentItem()
        hit = item.data(Qt.UserRole) if item else None
        if not hit:
            return
        self.detail_label.setText(f"<b>{hit.title}</b>（{hit.slug}）　作者：{hit.author}<br>{hit.short_desc()}")

    # ------------------------------------------------------------------ 安装
    def install_selected(self):
        item = self.result_list.currentItem()
        hit = item.data(Qt.UserRole) if item else None
        ins = self.current_instance()
        if not hit or not ins:
            return msg(self, "提示", "请选择一个项目和实例")
        if ins.loader == "vanilla":
            if not ask(self, "提示", "该实例是原版 Minecraft，安装 Mod 还需要 Fabric/Forge 加载器。\n仍然继续吗？"):
                return
        loader = ins.loader if ins.loader in ("fabric", "quilt", "forge", "neoforge") else "fabric"
        game_version = ins.base_version or ins.version_id
        dest = Path(ins.game_dir) / "mods"
        dest.mkdir(parents=True, exist_ok=True)
        self.btn_install.setEnabled(False)

        def work(report):
            versions = self.client.versions(hit.id, loaders=[loader], game_versions=[game_version])
            if not versions:
                versions = self.client.versions(hit.id)
            if not versions:
                raise RuntimeError(f"{hit.title} 没有适配 {game_version} 的版本")
            targets = [versions[0]]
            if self.dep_check.isChecked():
                report("解析依赖…", 0, 4, hit.title)
                targets += self.client.resolve_dependencies(versions[0], game_version, loader)
            for i, mod in enumerate(targets):
                report("下载 Mod", i + 1, len(targets) + 1, mod.filename)
                self.client.download(mod, dest)
            return [m.filename for m in targets]

        def done(files):
            self.btn_install.setEnabled(True)
            self.progress.setValue(100)
            self.fill_installed()
            self.win.toast_msg(f"已安装 {len(files)} 个文件到 {dest.name}", "ok")

        def err(e):
            self.btn_install.setEnabled(True)
            self.win.toast_msg(f"下载失败：{str(e).splitlines()[0]}", "error")

        run_async(self, work,
                  on_progress=lambda t, c, to, d: (self.progress.setValue(int(c * 100 / max(1, to))),
                                                   self.detail_label.setText(f"{t}：{d}")),
                  on_result=done, on_error=err)

    # ------------------------------------------------------------------ 本地
    def fill_installed(self):
        self.local_list.blockSignals(True)
        self.local_list.clear()
        ins = self.current_instance()
        if not ins:
            self.local_list.blockSignals(False)
            return
        mods = Path(ins.game_dir) / "mods"
        mods.mkdir(parents=True, exist_ok=True)
        for f in sorted(mods.glob("*")):
            if f.suffix not in (".jar", ".disabled") or not f.is_file():
                continue
            enabled = f.suffix == ".jar"
            item = QListWidgetItem(f.name.replace(".disabled", "") if not enabled else f.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            item.setData(Qt.UserRole, str(f))
            self.local_list.addItem(item)
        self.local_list.blockSignals(False)

    def on_local_toggled(self, item: QListWidgetItem):
        path = Path(item.data(Qt.UserRole))
        enable = item.checkState() == Qt.CheckState.Checked
        try:
            if enable and path.suffix == ".disabled":
                path.rename(path.with_suffix(".jar"))
                item.setData(Qt.UserRole, str(path.with_suffix(".jar")))
            elif not enable and path.suffix == ".jar":
                path.rename(path.with_name(path.name + ".disabled"))
                item.setData(Qt.UserRole, str(path.with_name(path.name + ".disabled")))
        except Exception as e:
            msg(self, "操作失败", str(e))

    def delete_local(self):
        item = self.local_list.currentItem()
        if not item:
            return
        path = Path(item.data(Qt.UserRole))
        if ask(self, "确认删除", f"确定删除 {path.name} 吗？"):
            path.unlink(missing_ok=True)
            self.fill_installed()
