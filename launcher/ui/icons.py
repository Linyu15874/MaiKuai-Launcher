"""矢量图标（自绘 SVG，无外部资源依赖）。"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 线框风格图标，坐标系统 24x24
_PATHS: dict[str, str] = {
    "home":      '<path d="M3 10.8 12 3.2l9 7.6"/><path d="M5.6 9.6V20.8h12.8V9.6"/><path d="M9.6 20.8v-6.2h4.8v6.2"/>',
    "rocket":    '<path d="M12 3.5c3.6 2 5.6 5.6 5.6 9.2L12 18.4 6.4 12.7c0-3.6 2-7.2 5.6-9.2z"/>'
                 '<path d="M6.4 12.7 3.6 15.2l2.4.8"/><path d="M17.6 12.7l2.8 2.5-2.4.8"/>'
                 '<path d="M8.8 19.6c1.2 1.6 5.2 1.6 6.4 0"/>',
    "download":  '<path d="M12 3.8v11.6"/><path d="M7.6 11.2 12 15.6l4.4-4.4"/><path d="M4 19.8h16"/>',
    "puzzle":    '<path d="M9.5 3.5h5v2.2a1.8 1.8 0 1 0 3.6 0V3.5H20a1.5 1.5 0 0 1 1.5 1.5v2.6h-3.2a1.8 1.8 0 1 0 0 3.6H21.5v4.2h-3.2a1.8 1.8 0 1 0 0 3.6h3.2v2.6A1.5 1.5 0 0 1 20 21.5h-1.9v-3.2a1.8 1.8 0 1 0-3.6 0v3.2H9.5v-3.2a1.8 1.8 0 1 0-3.6 0v3.2H4A1.5 1.5 0 0 1 2.5 20V5A1.5 1.5 0 0 1 4 3.5h5.5z"/>',
    "layers":    '<path d="M12 2.8 21 8l-9 5.2L3 8z"/><path d="M3 12.4 12 17.6 21 12.4"/><path d="M3 16.6 12 21.8 21 16.6"/>',
    "settings":  '<circle cx="12" cy="12" r="3.2"/>'
                 '<path d="M19.4 14.6a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1v.3a2 2 0 1 1-4 0v-.2a1.6 1.6 0 0 0-2.8-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7h-.3a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1.1-2.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3h.1a1.6 1.6 0 0 0 1-1.5v-.3a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7h.3a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.5 1z"/>',
    "info":      '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.4"/><path d="M12 7.8h.01"/>',
    "user":      '<circle cx="12" cy="8.4" r="3.9"/><path d="M4.8 20.5c0-3.7 3.2-5.6 7.2-5.6s7.2 1.9 7.2 5.6"/>',
    "folder":    '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.2l1.8 2.2h7A1.5 1.5 0 0 1 19 9.7v8.8A1.5 1.5 0 0 1 17.5 20h-13A1.5 1.5 0 0 1 3 18.5z"/>',
    "refresh":   '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.8 4.4v4.6h-4.6"/>',
    "trash":     '<path d="M4.5 6.6h15"/><path d="M9 6.6V4.8A1.2 1.2 0 0 1 10.2 3.6h3.6A1.2 1.2 0 0 1 15 4.8v1.8"/>'
                 '<path d="M6.4 6.6 7.2 20a1.2 1.2 0 0 0 1.2 1.1h7.2a1.2 1.2 0 0 0 1.2-1.1l.8-13.4"/>',
    "plus":      '<path d="M12 5.2v13.6"/><path d="M5.2 12h13.6"/>',
    "search":    '<circle cx="10.8" cy="10.8" r="6.6"/><path d="M15.6 15.6 20.4 20.4"/>',
    "console":   '<rect x="2.8" y="4.4" width="18.4" height="15.2" rx="2"/>'
                 '<path d="M7 10.2 9.6 12.6 7 15"/><path d="M12.6 15.4h4.4"/>',
    "chart":     '<path d="M4 20V9.5"/><path d="M10 20V4.5"/><path d="M16 20v-7"/><path d="M22 0v20" opacity="0"/>',
    "heart":     '<path d="M12 20.2s-7.4-4.5-7.4-9.4A4.1 4.1 0 0 1 12 8.4a4.1 4.1 0 0 1 7.4 2.4c0 4.9-7.4 9.4-7.4 9.4z"/>',
    "star":      '<path d="M12 3.6l2.6 5.4 5.8.8-4.2 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.6 9.8l5.8-.8z"/>',
    "cloud":     '<path d="M7.2 18.8A4.2 4.2 0 0 1 6.9 10.5a5.6 5.6 0 0 1 10.6-1.2 4.3 4.3 0 0 1 1 9.5z"/>',
    "java":      '<path d="M8.6 15.4s-4.2 2.4-4.2-1.6c0-3 4.2-6 4.2-6"/>'
                 '<path d="M12.4 13.4c3.4-2.6 3.4-6.8 3.4-6.8s1.4 3.6-1.4 6"/>'
                 '<path d="M15.6 9.2c2.4-2 2.2-5.4 2.2-5.4s1.6 2.6-.6 5"/>',
    "check":     '<path d="M4.5 12.8 9.4 17.6 19.6 6.6"/>',
    "warning":   '<path d="M12 3.8 21.4 20H2.6z"/><path d="M12 10v4.2"/><path d="M12 17.2h.01"/>',
    "media":     '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 9h18"/><circle cx="8.4" cy="14.6" r="2.2"/>',
    "wen":       '<path d="M4 6h16"/><path d="M8 6v13"/><path d="M4 12h8"/>',
}

_TEMPLATE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
             'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{p}</svg>')

_CACHE: dict[tuple[str, str, int], QIcon] = {}


def svg_bytes(name: str, color: str = "#4A8CF7", width: float = 1.8) -> bytes:
    p = _PATHS.get(name, _PATHS["info"])
    return _TEMPLATE.format(c=color, w=width, p=p).encode("utf-8")


def icon(name: str, color: str = "#4A8CF7", size: int = 20, width: float = 1.8) -> QIcon:
    key = (name, color, size)
    if key in _CACHE:
        return _CACHE[key]
    renderer = QSvgRenderer(QByteArray(svg_bytes(name, color, width)))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    ic = QIcon(pixmap)
    _CACHE[key] = ic
    return ic


def playable_names() -> list[str]:
    return sorted(_PATHS)
