#!/usr/bin/env python3
"""把 msvc-runtime 包里的 VC++ 运行库 DLL 收集到 launcher/vcredist/。

供打包脚本调用（pip install msvc-runtime 之后执行），
让干净的 Windows 系统也能直接运行打包产物。
"""

from __future__ import annotations

import shutil
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "launcher" / "vcredist"
NAMES = ("msvcp140", "vcruntime140")

candidates = [
    Path(sys.prefix),
    Path(sys.base_prefix),
    Path(sysconfig.get_paths().get("scripts", "")),
    Path(sysconfig.get_paths().get("data", "")),
]

found: list[Path] = []
for base in candidates:
    if base and base.exists():
        for dll in base.glob("*.dll"):
            if dll.name.lower().startswith(NAMES) and dll not in found:
                found.append(dll)

if not found:
    print("未找到 VC++ 运行库 DLL，请先 pip install msvc-runtime")
    sys.exit(1)

DST.mkdir(parents=True, exist_ok=True)
for dll in found:
    shutil.copy2(dll, DST / dll.name)
    print("复制:", dll.name)
print("完成 ->", DST)
