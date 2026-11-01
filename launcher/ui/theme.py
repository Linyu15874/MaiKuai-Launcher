"""PCL2 风格主题：配色 + QSS。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    accent: str
    accent_hover: str
    accent_press: str
    accent_soft: str
    danger: str
    success: str
    warning: str
    window: str
    panel: str
    card: str
    card_alt: str
    border: str
    border_strong: str
    text: str
    text_dim: str
    text_on_accent: str
    scroll: str
    field: str
    shadow: str


LIGHT = Palette(
    name="light", accent="#3B7BFF", accent_hover="#5C93FF", accent_press="#2A63DC", accent_soft="#E8F0FF",
    danger="#E0483C", success="#26A65B", warning="#E39C1B",
    window="#F3F5FA", panel="#FBFCFE", card="#FFFFFF", card_alt="#F7F9FD",
    border="#E4E8F0", border_strong="#CDD4E0", text="#1B1F27", text_dim="#6E7683",
    text_on_accent="#FFFFFF", scroll="#CFD6E2", field="#FFFFFF", shadow="rgba(30,45,80,0.10)",
)

DARK = Palette(
    name="dark", accent="#6C9DFF", accent_hover="#89B1FF", accent_press="#4E81F0", accent_soft="#1E2A42",
    danger="#FF6B63", success="#48C986", warning="#F0B429",
    window="#111318", panel="#16191F", card="#1B1F26", card_alt="#212630",
    border="#2A2F39", border_strong="#3A4150", text="#E8ECF3", text_dim="#98A1B0",
    text_on_accent="#0B1020", scroll="#333A46", field="#14171D", shadow="rgba(0,0,0,0.45)",
)


def palette(dark: bool) -> Palette:
    return DARK if dark else LIGHT


# 报错 / 崩溃分析窗口：强制白底黑字，保证任何主题下都可读
REPORT_QSS = """
QWidget { background: #ffffff; color: #111111; font-size: 13px; }
QLabel { background: transparent; color: #111111; }
QPlainTextEdit, QTextEdit {
    background: #ffffff; color: #111111; border: 1px solid #d0d0d0; border-radius: 6px;
}
QTextBrowser {
    background: #fffbea; color: #5a4a00; border: 1px solid #e6d27a;
    border-radius: 8px; padding: 8px;
}
QPushButton {
    background: #f4f4f4; color: #111111; border: 1px solid #cccccc;
    border-radius: 7px; padding: 6px 14px;
}
QPushButton:hover { background: #e8e8e8; }
QPushButton#danger { color: #c0392b; border-color: #c0392b; background: #ffffff; }
QPushButton#danger:hover { background: #c0392b; color: #ffffff; }
QFrame { background: #ffffff; }
"""


def qss(p: Palette) -> str:
    return f"""
/* ---------- 基础 ---------- */
QWidget, QMainWindow, QDialog {{
    background: transparent;
    color: {p.text};
    font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {p.card}; color: {p.text}; border: 1px solid {p.border};
    padding: 4px 7px; border-radius: 6px;
}}

/* ---------- 卡片 ---------- */
QFrame#card {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
QFrame#cardAlt {{
    background: {p.card_alt};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
QFrame#cardHead {{
    background: {p.card_alt};
    border-radius: 0px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 6px 14px;
    color: {p.text};
}}
QPushButton:hover {{ background: {p.card_alt}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:disabled {{ color: {p.text_dim}; background: {p.card_alt}; border-color: {p.border}; }}

QPushButton#primary {{
    background: {p.accent}; color: {p.text_on_accent}; border: 1px solid {p.accent};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton#primary:pressed {{ background: {p.accent_press}; }}
QPushButton#danger {{ color: {p.danger}; border-color: {p.danger}; }}
QPushButton#danger:hover {{ background: {p.danger}; color: #fff; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; }}
QPushButton#ghost:hover {{ background: {p.accent_soft}; border-color: {p.accent_soft}; }}

/* ---------- 输入框 / 下拉 ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {p.field};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {p.accent};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {p.accent};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p.card}; border: 1px solid {p.border}; selection-background-color: {p.accent_soft};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}

/* ---------- 列表 / 树 / 表格 ---------- */
QListWidget, QTreeWidget, QTableWidget {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 9px;
    outline: none;
    show-decoration-selected: 0;
}}
QListWidget::item, QTreeWidget::item, QTableWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {p.card_alt}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background: {p.accent_soft}; color: {p.text};
}}
QHeaderView::section {{
    background: {p.panel}; border: none; border-bottom: 1px solid {p.border};
    padding: 7px 8px; font-weight: 600;
}}

/* ---------- 进度条 / 滚动条 ---------- */
QProgressBar {{
    background: {p.card_alt}; border: 1px solid {p.border}; border-radius: 7px;
    height: 14px; text-align: center; color: {p.text_dim};
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{ background: {p.scroll}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{ background: {p.scroll}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---------- 导航 ---------- */
QFrame#sidebar {{ background: {p.panel}; border-right: 1px solid {p.border}; }}
QPushButton#nav {{
    background: transparent; border: none; border-radius: 8px;
    padding: 9px 10px; text-align: left; qproperty-iconSize: 20px 20px;
}}
QPushButton#nav:hover {{ background: {p.card_alt}; }}
QPushButton#nav:checked {{ background: {p.accent_soft}; color: {p.accent}; font-weight: 600; }}
QFrame#titlebar {{ background: {p.panel}; border-bottom: 1px solid {p.border}; }}
QPushButton#titleBtn {{
    background: transparent; border: none; border-radius: 6px; padding: 4px 10px;
}}
QPushButton#titleBtn:hover {{ background: {p.card_alt}; }}
QPushButton#titleBtnClose:hover {{ background: {p.danger}; color: #fff; }}

/* ---------- 分组 ---------- */
QGroupBox {{
    border: 1px solid {p.border}; border-radius: 9px; margin-top: 14px; padding: 12px 10px 10px 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p.text_dim}; }}
QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 9px; background: {p.card}; top: -1px; }}
QTabBar::tab {{
    background: transparent; border: none; padding: 8px 16px; margin-right: 4px;
    border-radius: 8px; color: {p.text_dim};
}}
QTabBar::tab:hover {{ background: {p.card_alt}; }}
QTabBar::tab:selected {{ background: {p.accent_soft}; color: {p.accent}; font-weight: 600; }}
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator:unchecked {{ border: 1px solid {p.border_strong}; border-radius: 4px; background: {p.field}; }}
QCheckBox::indicator:checked {{ border: 1px solid {p.accent}; border-radius: 4px; background: {p.accent}; }}
QSplitter::handle {{ background: {p.border}; }}
QStatusBar {{ background: {p.panel}; border-top: 1px solid {p.border}; color: {p.text_dim}; }}
QMenu {{ background: {p.card}; border: 1px solid {p.border}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.accent_soft}; color: {p.accent}; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {p.card_alt}; }}
"""
