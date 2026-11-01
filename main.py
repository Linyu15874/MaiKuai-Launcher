#!/usr/bin/env python3
"""麦块启动器 - 入口。

用法：
    python main.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 让脚本 / 冻结后的程序都能找到 launcher 包
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def main() -> int:
    try:
        from launcher.ui.app import bootstrap

        app, ctx = bootstrap()  # noqa
        from launcher.ui.window import MainWindow  # noqa

        win = MainWindow(ctx, app)
        win.show()
        return app.exec()  # noqa
    except Exception as e:
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        try:
            from launcher.ui.widgets import fatal

            fatal("启动失败", tb)
        except Exception:
            # 最终兜底：至少打印到控制台
            sys.stderr.write(tb)
        return 1


if __name__ == "__main__":
    sys.exit(main())
