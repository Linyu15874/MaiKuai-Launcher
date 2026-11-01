"""Java 运行时管理：扫描本机 Java、版本识别、按需从 Adoptium 下载。"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .net import SESSION, Downloader, DownloadTask, human_size

jtraise = None


@dataclass
class JavaInfo:
    path: Path
    version: str = "unknown"
    major: int = 0
    arch: str = "64"
    vendor: str = ""
    is_jdk: bool = True
    source: str = "system"

    def __str__(self) -> str:
        arch_txt = "" if self.arch == "64" else f" ({self.arch})"
        return f"{self.vendor} {self.version}{arch_txt}  ·  {self.path}"

    @property
    def executable(self) -> str:
        return str(self.path)


def _candidate_dirs() -> list[Path]:
    cands: list[Path] = []
    home = Path.home()
    if paths.IS_WINDOWS:
        roots = [Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
                 Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
                 Path(os.environ.get("LOCALAPPDATA", "")),
                 home / "AppData" / "Local" / "Programs"]
        subdirs = ["Java", "Eclipse Adoptium", "Zulu", "BellSoft", "Semeru", "OpenLogic",
                   "GraalVM", "Microsoft", "Corretto", "Dragonwell", "JetBrains", "AdoptOpenJDK"]
        for r in roots:
            if not r or not r.exists():
                continue
            for s in subdirs:
                d = r / s
                if d.exists():
                    cands += [p for p in d.iterdir() if p.is_dir()]
        # 官方启动器的自带运行时
        xbox_rt = home / "AppData" / "Local" / "Packages" / "Microsoft.4297127D7D95F9B9_8wekyb3d8bbwe" / "LocalCache" / "Local" / "runtime"
        if xbox_rt.exists():
            for p in xbox_rt.iterdir():
                if p.is_dir():
                    cands.append(p)
        # PATH
    elif paths.IS_MAC:
        for base in [Path("/Library/Java/JavaVirtualMachines"), home / "Library" / "Java" / "JavaVirtualMachines"]:
            if base.exists():
                cands += [p / "Contents" / "Home" for p in base.iterdir() if p.is_dir()]
        cands.append(Path("/System/Library/Frameworks/JavaVM.framework/Home"))
    else:
        for base in [Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt/java"), Path("/opt/jdk"), home / ".local" / "share" / "gradle" if False else Path("/usr/lib/jvm")]:
            if base.exists():
                cands += [p for p in base.iterdir() if p.is_dir()]
    # PATH 里的 java
    p = shutil.which("java")
    if p:
        try:
            resolved = Path(p).resolve()
            cands.append(resolved.parents[1] if resolved.name == "java" and len(resolved.parents) > 1 else resolved.parent)
            cands.append(resolved)
        except Exception:
            pass
    return cands


def _java_bin(root: Path) -> Path | None:
    exe = "java.exe" if paths.IS_WINDOWS else "java"
    if root.is_file() and root.name.lower().startswith("java"):
        return root
    for sub in [root, root / "bin"]:
        b = sub / exe
        if b.exists():
            return b
    return None


def _probe(java_bin: Path, source: str = "system") -> JavaInfo | None:
    try:
        r = subprocess.run([str(java_bin), "-version"], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
    except Exception:
        return None
    if not out:
        return None
    version, major = "unknown", 0
    m = re.search(r'"([^"]+)"', out)
    if m:
        version = m.group(1)
        first = version.split(".")[0]
        if first.isdigit():
            major = int(first)
        elif first == "1" and len(version.split(".")) > 1:
            major = 8
    vendor = "Unknown"
    for key, name in [("Zulu", "Azul Zulu"), ("OpenJDK", "OpenJDK"), ("Temurin", "Eclipse Temurin"),
                      ("AdoptOpenJDK", "AdoptOpenJDK"), ("GraalVM", "GraalVM"), ("HotSpot", "OpenJDK"),
                      ("Dragonwell", "Dragonwell"), ("JetBrains", "JetBrains Runtime"),
                      ("Microsoft", "Microsoft Build"), ("Bisheng", "毕昇 JDK")]:
        if key in out:
            vendor = name
            break
    arch = "64" if ("64-Bit" in out or "64-bit" in out or "amd64" in out or "aarch64" in out or "arm64" in out) else "32"
    return JavaInfo(path=java_bin, version=version, major=major, arch=arch, vendor=vendor,
                    is_jdk=(java_bin.parent / "javac").exists() or (java_bin.parents[1] / "bin" / "javac").exists(),
                    source=source)


_PATH_CACHE: dict[str, JavaInfo] = {}


def probe(java_bin: str | Path, source: str = "system") -> JavaInfo | None:
    key = str(java_bin)
    if key in _PATH_CACHE:
        return _PATH_CACHE[key]
    b = Path(java_bin)
    if not b.is_file() and not _java_bin(b):
        return None
    b = b if b.is_file() else _java_bin(b)
    info = _probe(b, source) if b else None
    if info:
        _PATH_CACHE[key] = info
    return info


def scan_system() -> list[JavaInfo]:
    """扫描本机全部 Java（含 Mojang 自带运行时）。"""
    found: dict[str, JavaInfo] = {}
    for cand in _candidate_dirs():
        b = _java_bin(cand)
        if not b:
            continue
        info = probe(b)
        if info and str(info.path) not in found:
            found[str(info.path)] = info
    if paths.IS_WINDOWS:  # 注册表
        for info in _scan_registry():
            found.setdefault(str(info.path), info)
    return sorted(found.values(), key=lambda x: (x.major, str(x.path)), reverse=True)


def _scan_registry() -> list[JavaInfo]:
    res: list[JavaInfo] = []
    if not paths.IS_WINDOWS:
        return res
    try:
        import winreg  # type: ignore

        roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\Java Runtime Environment"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JDK"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\JavaSoft\Java Runtime Environment"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\JavaSoft\JDK"),
                 (winreg.HKEY_CURRENT_USER, r"SOFTWARE\JavaSoft\JDK")]
        for root, sub in roots:
            try:
                with winreg.OpenKey(root, sub) as k:
                    i = 0
                    while True:
                        try:
                            ver = winreg.EnumKey(k, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(k, f"{ver}\\MSI") if False else winreg.OpenKey(k, ver) as vk:
                                home = winreg.QueryValueEx(vk, "JavaHome")[0]
                            b = _java_bin(Path(home))
                            info = probe(b) if b else None
                            if info:
                                res.append(info)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass
    return res


def scan_runtime_dir(root: Path) -> list[JavaInfo]:
    """启动器自己下载/管理的 runtime 目录。"""
    res: list[JavaInfo] = []
    base = Path(root)
    if not base.exists():
        return res
    for p in base.iterdir():
        if not p.is_dir():
            continue
        b = _java_bin(p / "bin" if (p / "bin").exists() else p)
        if not b:
            for mac in p.glob("*.jdk"):  # macOS bundle
                b = _java_bin(mac / "Contents" / "Home")
                if b:
                    p = mac
                    break
        if b:
            info = probe(b, source="managed")
            if info:
                res.append(info)
    return sorted(res, key=lambda x: x.major, reverse=True)


# --------------------------------------------------------------------------- 选择策略


def _required_major(version_json: dict) -> int:
    """根据版本 json 判断需要的 Java 大版本。"""
    v = version_json.get("javaVersion", {}).get("majorVersion")
    if isinstance(v, int) and v:
        return v
    major = version_json.get("javaVersion", {}).get("component") == "java-runtime-gamma"
    if major:
        return 21
    mc = str(version_json.get("id", ""))
    try:
        parts = mc.split(".")
        toscale = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    except Exception:
        toscale = 0
    if mc.startswith("1."):
        return 8 if toscale < 12 else (17 if toscale <= 17 else 21)
    return 17


def pick_java(version_json: dict, candidates: list[JavaInfo], preferred: str = "") -> JavaInfo | None:
    """挑一个满足要求的 Java：优先用户指定，否则按「够用且最低」原则。"""
    need = _required_major(version_json)
    if preferred:
        info = probe(preferred, source="custom")
        if info:
            return info
    usable = [j for j in candidates if j.major >= need and (j.arch == paths.OS_ARCH or j.arch == "64" and paths.IS_64BIT)]
    if not usable:
        # 退而求其次：只要能跑就行
        usable = [j for j in candidates if j.major >= need]
    if not usable:
        # Forge 1.20 / Fabric 一般需要 >=17；没有的话给最高的
        usable = candidates
    if not usable:
        return None
    return min(usable, key=lambda j: (j.major, 0 if j.source == "managed" else 1))


# --------------------------------------------------------------------------- Adoptium 下载


ADOPTIUM = "https://api.adoptium.net/v3/assets"
_OS_NAME_MAP = {"windows": "windows", "osx": "mac", "linux": "linux"}


def adoptium_download_url(feature: int, jre: bool = True) -> str | None:
    """查 Adoptium 获取指定大版本的最新二进制下载地址。"""
    params = {
        "architecture": "x64" if paths.OS_ARCH == "64" else paths.OS_ARCH,
        "heap_size": "normal",
        "image_type": "jre" if jre and feature <= 17 else "jdk",
        "os": _OS_NAME_MAP.get(paths.OS_NAME, "linux"),
        "page_size": "1",
        "project": "jdk",
        "release_type": "ga",
        "sort_method": "DEFAULT",
        "sort_order": "DESC",
        "vendor": "eclipse",
    }
    for _ in range(2):
        try:
            r = SESSION.get(f"{ADOPTIUM}/feature_releases/{feature}/ga", params=params, timeout=25)
            r.raise_for_status()
            data = r.json()
            for item in data:
                for binary in item.get("binaries", []):
                    pkg = binary.get("package", {})
                    if pkg.get("link"):
                        return pkg["link"]
        except Exception:
            pass
    return None


def install_managed_java(feature: int, runtime_root: Path,
                         progress: callable = None) -> JavaInfo | None:
    """下载并解压 Temurin 到 runtime 目录，返回可用的 JavaInfo。"""
    url = adoptium_download_url(feature)
    if not url:
        raise RuntimeError("获取 Java 下载地址失败")
    name = url.split("/")[-1]
    dest = Path(runtime_root) / f"temurin-{feature}" / name
    dl = Downloader(threads=4)
    dl.fetch(DownloadTask(url=url, dest=dest, key=f"Java {feature}"))
    target = Path(runtime_root) / f"temurin-{feature}"
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(dest) as t:
            members = t.getmembers()
            root_member = members[0].name.split("/")[0]
            t.extractall(target, filter="data" if sys.version_info >= (3, 12) else None)
        extracted = target / root_member
    elif name.endswith(".zip"):
        with zipfile.ZipFile(dest) as z:
            z.extractall(target)
        roots = {n.split("/")[0] for n in zipfile.ZipFile(dest).namelist()}
        extracted = (target / roots.pop()) if roots else target
    else:
        raise RuntimeError(f"未知压缩包类型：{name}")
    dest.unlink(missing_ok=True)
    info = None
    if paths.IS_MAC:
        for mac_dir in extracted.glob("*.jdk"):
            info = probe(mac_dir / "Contents" / "Home" / "bin" / "java", source="managed")
            if info:
                break
    if info is None:
        info = probe(extracted / "Contents" / "Home" / "bin" / "java", source="managed") \
               or probe(extracted / "bin" / "java", source="managed")
    return info


def recommend_memory_mb() -> int:
    """按物理内存推荐最大堆内存（MB）。"""
    total = 4096
    try:
        if paths.IS_WINDOWS:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore
            total = stat.ullTotalPhys // (1024 * 1024)
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except Exception:
        pass
    suggestion = int(total * 0.5)
    # 取 512MB 的整数倍，限制在 [1024, 8192]
    suggestion = max(1024, min(8192, suggestion // 512 * 512))
    return suggestion
