"""全局路径与环境信息。

数据目录优先级：
    1. 环境变量 MCL_HOME
    2. 便携模式：程序目录下的 data/
    3. 平台默认用户目录
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

APP_ID = "pcl-launcher"
APP_NAME = "麦块启动器"
APP_VERSION = "1.0.0"
APP_CODENAME = "Neo Edition"
# 注意：HTTP 头必须为纯 ASCII
USER_AGENT = "PCL-Launcher/1.0.0 (Minecraft launcher, inspired by PCL2 & HMCL)"

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

OS_NAME = "windows" if IS_WINDOWS else ("osx" if IS_MAC else "linux")
OS_VERSION = platform.release()

_ARCH_MAP = {
    "amd64": "64",
    "x86_64": "64",
    "x64": "64",
    "i386": "32",
    "i686": "32",
    "x86": "32",
    "arm64": "arm64",
    "aarch64": "arm64",
}
OS_ARCH = _ARCH_MAP.get(platform.machine().lower(), platform.machine().lower())
IS_64BIT = sys.maxsize > 2**32


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_DIR = _exe_dir()


def _resource_dir() -> Path:
    # PyInstaller 冻结后，数据文件在 sys._MEIPASS 下
    for base in (Path(getattr(sys, "_MEIPASS", "")), APP_DIR):
        if str(base) and (base / "launcher" / "resources").exists():
            return base / "launcher" / "resources"
    return APP_DIR / "launcher" / "resources"


RESOURCE_DIR = _resource_dir()


def data_root() -> Path:
    env = os.environ.get("MCL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    portable = APP_DIR / "data"
    if portable.exists() or (APP_DIR / "portable.txt").exists():
        portable.mkdir(parents=True, exist_ok=True)
        return portable
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return (base / APP_ID).resolve()


def ensure_dirs(root: Path | None = None) -> dict[str, Path]:
    """创建并返回所有常用子目录。"""
    root = root or data_root()
    paths = {
        "root": root,
        "config": root,
        "versions": root / "versions",
        "libraries": root / "libraries",
        "assets": root / "assets",
        "instances": root / "instances",
        "cache": root / "cache",
        "runtime": root / "runtime",
        "logs": root / "logs",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def default_game_dir() -> Path:
    """默认 .minecraft 目录（可在设置里改为任何位置）。"""
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA") or Path.home()) / ".minecraft"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "minecraft"
    return Path.home() / ".minecraft"


def library_path(root: Path, name: str) -> Path:
    """把 maven 坐标 net.fabricmc:intermediary:1.20.1 转为本地相对路径。"""
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    if len(parts) > 3:  # 带 classifier
        version = f"{parts[2]}-{parts[3]}"
    filename = f"{artifact}-{version}.jar"
    return root / "libraries" / Path(*group.split(".")) / artifact / parts[2] / filename


def safe_name(text: str) -> str:
    """文件系统安全的文件名。"""
    bad = '<>:"/\\|?*\x00'
    out = "".join("_" if c in bad else c for c in text).strip().rstrip(".")
    return out or "unnamed"


def open_in_explorer(path: Path) -> None:
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif IS_MAC:
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass
