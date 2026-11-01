#!/usr/bin/env python3
"""跨平台构建 Windows 单文件 exe（PCL-Launcher.exe）。

- Windows 本机：直接调用本机 PyInstaller 构建。
- 其它平台（CI / 本沙箱 Linux）：通过 Wine 调用 Windows 版 PyInstaller 交叉构建，
  复用已就绪的 Wine 前缀（含 embeddable Python 3.11 + PySide6 + PyInstaller）。

用法：
    python tools/build_exe.py            # 自动选择（Windows 本机 / 其它 Wine）
    python tools/build_exe.py --wine     # 强制 Wine 交叉构建
    python tools/build_exe.py --native   # 强制本机（需在 Windows 上）构建
    python tools/build_exe.py --out DIR  # 输出目录（默认仓库下 dist/）

退出码 0 表示成功，且产物位于 <out>/PCL-Launcher.exe。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "pcl-launcher.spec"
DIST = ROOT / "dist"


def _run(cmd: list[str], cwd: str | None = None, **kw) -> int:
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.call(cmd, cwd=cwd, **kw)


def ensure_icon() -> None:
    """确保图标存在（无外部素材，纯 PIL 绘制）。"""
    ico = ROOT / "launcher" / "resources" / "app.ico"
    if not ico.exists():
        _run([sys.executable, str(ROOT / "tools" / "make_icon.py")])


def build_native() -> Path:
    ensure_icon()
    DIST.mkdir(parents=True, exist_ok=True)
    code = _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(DIST), str(SPEC),
    ])
    if code != 0:
        raise RuntimeError(f"PyInstaller 本机构建失败（exit={code}）")
    exe = DIST / "PCL-Launcher.exe"
    if not exe.exists():
        raise RuntimeError("构建完成但未找到 PCL-Launcher.exe")
    return exe


def _find_wine() -> str:
    for cand in ("wine64", "wine"):
        if shutil.which(cand):
            return cand
    alt = "/usr/lib/wine/wine64"
    if Path(alt).exists():
        return alt
    raise RuntimeError("未找到 wine，请先安装 Wine 或改用 --native（Windows）")


def build_wine() -> Path:
    ensure_icon()
    wine = _find_wine()
    wineprefix = os.environ.get("WINEPREFIX", "/tmp/winbuild/wineprefix")
    py = os.environ.get("WIN_PYTHON", r"C:\Python311\python.exe")
    env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=wineprefix)

    dst = Path(wineprefix) / "drive_c" / "build" / "pcl-launcher"
    print(f"== 同步源码到 {dst}")
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "launcher", dst / "launcher")
    for f in (ROOT / "main.py", SPEC, ROOT / "requirements.txt"):
        shutil.copy(f, dst / f.name)

    print("== 运行 PyInstaller (Wine)")
    # 关键：cwd 必须为 dst（Wine 会把宿主机 drive_c 下的目录翻译成 C:\...），
    # 且 spec 用相对名，避免把宿主机绝对路径当成 Windows 路径。
    code = _run([wine, py, "-m", "PyInstaller", "--noconfirm", "--clean",
                 "pcl-launcher.spec"], env=env, cwd=str(dst))
    if code != 0:
        raise RuntimeError(f"Wine 构建失败（exit={code}）")

    DIST.mkdir(parents=True, exist_ok=True)
    src_exe = dst / "dist" / "PCL-Launcher.exe"
    if not src_exe.exists():
        raise RuntimeError(f"Wine 构建未产出 exe：{src_exe}")
    shutil.copy(src_exe, DIST / "PCL-Launcher.exe")
    return DIST / "PCL-Launcher.exe"


def main() -> int:
    global DIST
    ap = argparse.ArgumentParser(description="构建 PCL-Launcher.exe")
    ap.add_argument("--wine", action="store_true", help="强制 Wine 交叉构建")
    ap.add_argument("--native", action="store_true", help="强制本机构建（Windows）")
    ap.add_argument("--out", default=str(DIST), help="输出目录")
    args = ap.parse_args()

    DIST = Path(args.out)
    mode = "wine" if args.wine else ("native" if args.native else
            ("native" if sys.platform == "win32" else "wine"))
    print(f"[build] 模式={mode}")
    try:
        if mode == "native":
            exe = build_native()
        else:
            exe = build_wine()
    except Exception as e:  # noqa: BLE001
        print(f"[build] 失败：{e}", file=sys.stderr)
        return 1
    print(f"[build] 成功：{exe}  （{exe.stat().st_size / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
