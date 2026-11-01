#!/usr/bin/env python3
"""麦块启动器 - 入口。

用法：
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本 / 冻结后的程序都能找到 launcher 包
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def main() -> int:
    from launcher.ui.app import bootstrap

    app, ctx = bootstrap()  # noqa
    try:
        from launcher.ui.window import MainWindow  # noqa

        win = MainWindow(ctx, app)
        win.show()
        return app.exec()  # noqa
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"启动失败：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
