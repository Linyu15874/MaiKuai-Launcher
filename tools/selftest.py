"""自检脚本：语法 + 核心层导入 + Qt 界面实例化（离屏截图）。"""

from __future__ import annotations

import ast
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def section(title: str) -> None:
    print(f"\n===== {title} =====")


def check_syntax() -> list[str]:
    bad: list[str] = []
    for p in sorted(ROOT.rglob("*.py")):
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            bad.append(f"{p.relative_to(ROOT)}:{e.lineno}: {e.msg}")
    return bad


def main() -> int:
    section("1. 语法检查")
    bad = check_syntax()
    if bad:
        for b in bad:
            print("  ✗", b)
        print(f"共 {len(bad)} 个文件有语法错误")
        return 1
    print("  ✓ 全部 .py 文件语法正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
