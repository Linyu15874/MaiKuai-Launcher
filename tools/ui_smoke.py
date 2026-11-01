#!/usr/bin/env python3
"""界面自检：离屏渲染主窗口并截图（不依赖显示器）。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher.ui.app import bootstrap  # noqa: E402


def main() -> int:
    app, ctx = bootstrap()
    ctx.config.set("first_run", False)
    from launcher.ui.window import MainWindow

    win = MainWindow(ctx, app)
    win.resize(1180, 780)
    win.show()
    app.processEvents()
    out = ROOT / "shots"
    out.mkdir(exist_ok=True)
    for key in ["home", "versions", "download", "mods", "settings"]:
        win.switch_page(key)
        app.processEvents()
        pix = win.grab()
        path = out / f"{key}.png"
        pix.save(str(path))
        print(f"saved {path.name} {pix.width()}x{pix.height()}")
    print("UI_SMOKE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
