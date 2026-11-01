"""对话框：账号登录、游戏日志控制台、首次运行向导。"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QProgressBar, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from launcher.ui import icons
from launcher.ui.app import AppContext
from launcher.core.auth import (Account, DEFAULT_CLIENT_ID, KNOWN_YGGDRASIL, AccountStore, MicrosoftAuth, YggdrasilSession,
                    login_offline, login_yggdrasil)
from launcher.core import java as java_mod
from launcher.core.launch import analyze_log
from launcher.ui.widgets import Card, choose_dir, msg, run_async


# --------------------------------------------------------------------------- 登录


class LoginDialog(QDialog):
    """离线 / 微软 / 外置登录三合一。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.account: Account | None = None
        self.setWindowTitle("选择 / 登录账号")
        self.resize(560, 520)
        pal = ctx.palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        saved = Card("已保存的账号", icon="user", parent=self)
        self.list = QListWidget()
        self.list.setMaximumHeight(120)
        self.list.itemDoubleClicked.connect(self.use_saved)
        saved.add(self.list)
        row = QHBoxLayout()
        b_use = QPushButton("使用选中账号")
        b_use.setObjectName("primary")
        b_use.clicked.connect(self.use_saved)
        b_del = QPushButton("删除")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self.delete_saved)
        row.addWidget(b_use)
        row.addWidget(b_del)
        row.addStretch(1)
        saved.add_layout(row)
        layout.addWidget(saved)
        self.reload_saved()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_offline(pal), "离线登录")
        self.tabs.addTab(self._build_microsoft(pal), "微软账号")
        self.tabs.addTab(self._build_yggdrasil(pal), "外置登录")
        layout.addWidget(self.tabs, 1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("关闭")
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    # ------------------------------------------------------------------ 已保存
    def reload_saved(self):
        self.list.clear()
        for acc in self.ctx.accounts.accounts:
            kind = {"offline": "离线", "microsoft": "微软", "yggdrasil": "外置"}[acc.type]
            item = QListWidgetItem(f"{acc.username}   ·   {kind}")
            item.setData(Qt.UserRole, acc)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def use_saved(self):
        item = self.list.currentItem()
        if not item:
            return
        self.account = item.data(Qt.UserRole)
        self.ctx.set_account(self.account)
        self.accept()

    def delete_saved(self):
        item = self.list.currentItem()
        if not item:
            return
        acc = item.data(Qt.UserRole)
        self.ctx.accounts.remove(acc)
        if self.ctx.current_account is acc:
            self.ctx.set_account(None)
        self.reload_saved()

    # ------------------------------------------------------------------ 离线
    def _build_offline(self, pal) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        tip = QLabel("离线账号不需要联网，也无法进入开启了正版验证的服务器。"
                     "填一个你喜欢的名字即可开始游戏。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {pal.text_dim};")
        layout.addWidget(tip)
        form = QFormLayout()
        self.off_name = QLineEdit("Player")
        form.addRow("游戏昵称：", self.off_name)
        layout.addLayout(form)
        b = QPushButton("创建并登录")
        b.setObjectName("primary")
        b.setMinimumHeight(34)
        b.clicked.connect(self.do_offline)
        layout.addWidget(b)
        layout.addStretch(1)
        return w

    def do_offline(self):
        name = self.off_name.text().strip()
        if not name:
            return msg(self, "提示", "请填写昵称")
        acc = login_offline(name)
        self.ctx.accounts.add(acc)
        self.ctx.set_account(acc)
        self.account = acc
        self.accept()

    # ------------------------------------------------------------------ 微软
    def _build_microsoft(self, pal) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        tip = QLabel("使用微软账号登录正版 Minecraft。点击下面的按钮后，"
                     "会显示一个网址与一次性验证码，在浏览器中完成授权即可。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {pal.text_dim};")
        layout.addWidget(tip)
        form = QFormLayout()
        self.ms_client = QLineEdit(self.ctx.config.get("auth.ms_client_id", DEFAULT_CLIENT_ID))
        self.ms_client.setToolTip("可在设置页修改；个人可在 Azure 门户注册应用后替换")
        form.addRow("Client ID：", self.ms_client)
        layout.addLayout(form)

        self.ms_area = QWidget()
        ms_layout = QVBoxLayout(self.ms_area)
        self.ms_code_label = QLabel("")
        f = QFont("Consolas, Menlo, monospace")
        f.setPointSize(18)
        f.setBold(True)
        self.ms_code_label.setFont(f)
        self.ms_code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ms_code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ms_uri_label = QLabel("")
        self.ms_uri_label.setWordWrap(True)
        self.ms_uri_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.ms_uri_label.setOpenExternalLinks(True)
        ms_layout.addWidget(self.ms_code_label)
        ms_layout.addWidget(self.ms_uri_label)
        row = QHBoxLayout()
        b_copy = QPushButton("复制验证码")
        b_copy.clicked.connect(self.copy_code)
        b_open = QPushButton("打开授权网页")
        b_open.clicked.connect(self.open_auth_page)
        row.addWidget(b_copy)
        row.addWidget(b_open)
        ms_layout.addLayout(row)
        self.ms_area.hide()
        layout.addWidget(self.ms_area)

        self.ms_status = QLabel("")
        self.ms_status.setWordWrap(True)
        layout.addWidget(self.ms_status)
        self.ms_bar = QProgressBar()
        self.ms_bar.hide()
        layout.addWidget(self.ms_bar)
        self.btn_ms = QPushButton("开始登录")
        self.btn_ms.setObjectName("primary")
        self.btn_ms.setMinimumHeight(34)
        self.btn_ms.clicked.connect(self.do_microsoft)
        layout.addWidget(self.btn_ms)
        layout.addStretch(1)
        self._verification_uri = ""
        self._user_code = ""
        return w

    def copy_code(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._user_code)
        self.ms_status.setText("验证码已复制，粘贴到网页中即可")

    def open_auth_page(self):
        import webbrowser
        if self._verification_uri:
            webbrowser.open(self._verification_uri)

    def do_microsoft(self):
        self.btn_ms.setEnabled(False)
        self.ms_status.setText("正在获取设备码…")
        client_id = self.ms_client.text().strip() or DEFAULT_CLIENT_ID
        verify = bool(self.ctx.config.get("auth.https_verify", True))

        def work(report):
            auth = MicrosoftAuth(client_id, verify)
            res = auth.device_code()
            report("DEVICE_CODE", 0, 1, f"{res.verification_uri}|{res.user_code}")
            report("等待授权", 0, 1, "请在浏览器中完成登录")
            token = auth.poll_token(res, on_poll=lambda s: report("等待授权", 0, 1, s))
            report("正在获取游戏角色", 0, 1, "")
            return auth.xbox_to_minecraft(token)

        def progress(text, cur, tot, detail):
            if text == "DEVICE_CODE" and "|" in detail:
                uri, code = detail.split("|", 1)
                self._verification_uri, self._user_code = uri, code
                self.ms_area.show()
                self.ms_code_label.setText(code)
                self.ms_uri_label.setText(f'<a href="{uri}">{uri}</a>')
                self.ms_status.setText("请在网页中输入上面的验证码并完成登录")
                self.ms_bar.setRange(0, 0)
                self.ms_bar.show()
                return
            self.ms_status.setText(f"{text}　{detail}")

        def done(acc):
            self.ms_bar.setRange(0, 100)
            self.ms_bar.hide()
            self.ctx.accounts.add(acc)
            self.ctx.set_account(acc)
            self.account = acc
            self.ms_status.setText(f"登录成功：{acc.username}")
            self.btn_ms.setEnabled(True)
            QTimer.singleShot(400, self.accept)

        def err(e):
            self.btn_ms.setEnabled(True)
            self.ms_bar.hide()
            self.ms_status.setText(f"登录失败：{str(e).splitlines()[0]}")

        run_async(self, work, on_progress=progress, on_result=done, on_error=err)

    # ------------------------------------------------------------------ 外置登录
    def _build_yggdrasil(self, pal) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        tip = QLabel("外置登录（authlib-injector / Yggdrasil）用于各类第三方皮肤站账号。"
                     "如果你不知道这是什么，请选择离线登录或微软账号。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {pal.text_dim};")
        layout.addWidget(tip)
        form = QFormLayout()
        self.yg_server = QComboBox()
        self.yg_server.setEditable(True)
        default = self.ctx.config.get("auth.yggdrasil_default", KNOWN_YGGDRASIL[0][0])
        urls = [u for u, _ in KNOWN_YGGDRASIL]
        if default not in urls:
            urls.insert(0, default)
        for u in urls:
            self.yg_server.addItem(u)
        self.yg_server.setCurrentText(default)
        form.addRow("认证地址：", self.yg_server)
        self.yg_user = QLineEdit()
        self.yg_user.setPlaceholderText("邮箱或用户名")
        form.addRow("账号：", self.yg_user)
        self.yg_pass = QLineEdit()
        self.yg_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("密码：", self.yg_pass)
        self.yg_verify = QCheckBox("验证 HTTPS 证书")
        self.yg_verify.setChecked(bool(self.ctx.config.get("auth.https_verify", True)))
        form.addRow("", self.yg_verify)
        layout.addLayout(form)
        self.yg_status = QLabel("")
        self.yg_status.setWordWrap(True)
        layout.addWidget(self.yg_status)
        b = QPushButton("登录")
        b.setObjectName("primary")
        b.setMinimumHeight(34)
        b.clicked.connect(self.do_yggdrasil)
        layout.addWidget(b)
        layout.addStretch(1)
        return w

    def do_yggdrasil(self):
        server = self.yg_server.currentText().strip().rstrip("/")
        user = self.yg_user.text().strip()
        pwd = self.yg_pass.text()
        if not server or not user or not pwd:
            return msg(self, "提示", "请填写认证地址、账号和密码")
        verify = self.yg_verify.isChecked()
        self.yg_status.setText("正在登录…")

        def work(_r):
            return login_yggdrasil(server, user, pwd, verify=verify)

        def done(acc):
            self.ctx.accounts.add(acc)
            self.ctx.set_account(acc)
            self.account = acc
            self.yg_status.setText(f"登录成功：{acc.username}")
            QTimer.singleShot(400, self.accept)

        def err(e):
            self.yg_status.setText(f"登录失败：{str(e).splitlines()[0]}")

        run_async(self, work, on_result=done, on_error=err)


# --------------------------------------------------------------------------- 控制台


class ConsoleWindow(QWidget):
    """实时游戏日志窗口 + 崩溃分析。"""

    closed_signal = Signal()

    def __init__(self, ctx: AppContext, version_id: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(f"游戏日志 - {version_id or 'Minecraft'}")
        self.resize(900, 560)
        pal = ctx.palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        self.status_label = QLabel("正在启动…")
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        self.status_label.setFont(f)
        head.addWidget(self.status_label, 1)
        self.btn_stop = QPushButton("结束游戏")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self.stop_game)
        b_copy = QPushButton("复制全部")
        b_copy.clicked.connect(self.copy_all)
        b_save = QPushButton("保存日志")
        b_save.clicked.connect(self.save_log)
        b_clear = QPushButton("清空")
        b_clear.clicked.connect(self.text.clear)
        head.addWidget(b_save)
        head.addWidget(b_copy)
        head.addWidget(b_clear)
        head.addWidget(self.btn_stop)
        layout.addLayout(head)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        font = QFont("Consolas, Menlo, DejaVu Sans Mono, monospace")
        font.setPointSize(10)
        self.text.setFont(font)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text, 1)

        self.tips = QTextBrowser()
        self.tips.setMaximumHeight(110)
        self.tips.hide()
        layout.addWidget(self.tips)

        self._buffer: list[str] = []
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.flush)
        self._timer.start()
        self._killer = None

    def append(self, line: str):
        self._buffer.append(line)

    def flush(self):
        if not self._buffer:
            return
        lines = self._buffer
        self._buffer = []
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        for line in lines[-400:]:
            cursor.insertText(line + "\n")
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_stop_callback(self, fn):
        self._killer = fn

    def stop_game(self):
        if self._killer:
            self._killer()

    def copy_all(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text.toPlainText())

    def save_log(self):
        from datetime import datetime
        p = self.ctx.dirs["logs"] / f"launch-{datetime.now():%Y%m%d-%H%M%S}.log"
        p.write_text(self.text.toPlainText(), "utf-8")
        self.status_label.setText(f"日志已保存到 {p}")

    def finish(self, exit_code: int):
        self.flush()
        self.status_label.setText(f"游戏已退出，退出码 {exit_code}")
        self.btn_stop.setEnabled(False)
        if exit_code != 0:
            hits = analyze_log(self.text.toPlainText())
            if hits:
                self.tips.setHtml("<b>可能的原因与处理建议：</b><br>" +
                                  "<br>".join(f"• <b>{t}</b>：{d}" for t, d in hits))
                self.tips.show()
            else:
                self.tips.setHtml("游戏异常退出。可以把完整日志发到社区求助。")
                self.tips.show()

    def closeEvent(self, event):
        self.flush()
        self.closed_signal.emit()
        super().closeEvent(event)


# --------------------------------------------------------------------------- 首次运行向导


class FirstRunDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("欢迎使用麦块启动器")
        self.resize(620, 460)
        pal = ctx.palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("欢迎 👋")
        f = title.font()
        f.setPointSize(19)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)
        sub = QLabel("这是一个仿照 PCL2 思路实现的跨平台 Minecraft 启动器。"
                     "下面几步会帮你把游戏环境准备好。")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {pal.text_dim};")
        layout.addWidget(sub)

        card = Card("游戏文件保存位置", icon="folder", parent=self)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(ctx.game_root))
        row.addWidget(self.path_edit, 1)
        b = QPushButton("浏览")
        b.clicked.connect(self.browse)
        row.addWidget(b)
        card.add_layout(row)
        hint = QLabel("所有版本、依赖库、Mod 与实例都会放在这里，建议留空使用默认位置。")
        hint.setStyleSheet(f"color: {pal.text_dim};")
        card.add(hint)
        layout.addWidget(card)

        card2 = Card("下载源", icon="cloud", parent=self)
        row2 = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("官方源（海外网络推荐）", "official")
        self.source_combo.addItem("BMCLAPI 镜像（国内网络推荐）", "bmclapi")
        row2.addWidget(self.source_combo, 1)
        card2.add_layout(row2)
        card2.set_subtitle("下载卡顿时可以随时在「设置 → 下载与网络」里切换。")
        layout.addWidget(card2)

        card3 = Card("内存分配", icon="rocket", parent=self)
        row3 = QHBoxLayout()
        self.mem_spin = QSpinBox() if False else None
        from PySide6.QtWidgets import QSpinBox
        self.mem_spin = QSpinBox()
        self.mem_spin.setRange(1024, 65536)
        self.mem_spin.setSingleStep(512)
        self.mem_spin.setValue(java_mod.recommend_memory_mb())
        self.mem_auto = QCheckBox("自动推荐（推荐）")
        self.mem_auto.setChecked(True)
        self.mem_auto.toggled.connect(lambda v: self.mem_spin.setEnabled(not v))
        self.mem_spin.setEnabled(False)
        row3.addWidget(QLabel("最大内存"))
        row3.addWidget(self.mem_spin)
        row3.addWidget(QLabel("MB"))
        row3.addWidget(self.mem_auto)
        row3.addStretch(1)
        card3.add_layout(row3)
        layout.addWidget(card3)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("完成，开始使用")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("跳过")
        box.accepted.connect(self.apply)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def browse(self):
        d = choose_dir(self, "选择游戏文件保存位置", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def apply(self):
        p = self.path_edit.text().strip()
        if p:
            self.ctx.config.set("game_root", p)
        self.ctx.config.set("source", self.source_combo.currentData())
        self.ctx.config.set("memory.max", self.mem_spin.value())
        self.ctx.config.set("memory.auto", self.mem_auto.isChecked())
        self.ctx.config.set("first_run", False)
        self.ctx.rebuild()
        self.accept()
