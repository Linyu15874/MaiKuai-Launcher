"""游戏安装引擎：原版 / Fabric / Quilt / Forge / NeoForge 的下载与安装。

数据来源全部为官方公开 API：
    Mojang 版本清单、Fabric Meta、Quilt Meta、Forge Maven、NeoForge Maven、BMCLAPI 镜像
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import paths
from .net import Downloader, DownloadTask, NetworkError, SourceManager, get_json, get_bytes, SESSION
from .version import VersionProfile, read_json

ReportCB = Callable[[str, int, int, str], None]


def _noop_report(text: str, cur: int, total: int, detail: str = "") -> None:
    pass


# --------------------------------------------------------------------------- Maven 小工具


def maven_relative(name: str, ext: str = "jar") -> str:
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    extra = f"-{parts[3]}" if len(parts) > 3 else ""
    filename = f"{artifact}-{version}{extra}.{ext}"
    return f"{'/'.join(group.split('.'))}/{artifact}/{version}/{filename}"


def maven_url(base: str, name: str, ext: str = "jar") -> str:
    return f"{base.rstrip('/')}/{maven_relative(name, ext)}"


def maven_metadata_versions(url: str) -> list[str]:
    try:
        raw = SESSION.get(url, timeout=30).text
    except Exception:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    return [e.text for e in root.iter("version") if e.text]


# --------------------------------------------------------------------------- 加载器元数据


FABRIC_META = "https://meta.fabricmc.net/v2"
FABRIC_MAVEN = "https://maven.fabricmc.net/"
QUILT_META = "https://meta.quiltmc.org/v3"
QUILT_MAVEN = "https://maven.quiltmc.org/repository/release/"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
NEOFORGE_MAVEN_MIRROR = "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge"


def fabric_loader_list(mc: str) -> list[dict]:
    data = get_json(f"{FABRIC_META}/versions/loader/{mc}", timeout=25)
    out = []
    for entry in data:
        loader = entry.get("loader") or {}
        out.append({"version": loader.get("version", ""), "stable": True,
                    "maven": loader.get("maven", "")})
    return [x for x in out if x["version"]][::-1]


def fabric_game_versions() -> list[str]:
    data = get_json(f"{FABRIC_META}/versions/game", timeout=25)
    return [(x.get("version") or "") for x in data if (x.get("version") and x.get("stable"))]


def fabric_intermediary_list(mc: str) -> list[dict]:
    data = get_json(f"{FABRIC_META}/versions/intermediary/{mc}", timeout=25)
    return [{"version": x.get("version", "")} for x in data]


def quilt_loader_list(mc: str) -> list[dict]:
    data = get_json(f"{QUILT_META}/versions/loader/{mc}", timeout=25)
    out = []
    for entry in data or []:
        loader = entry.get("loader") or {}
        out.append({"version": loader.get("version", ""), "maven": loader.get("maven", "")})
    return [x for x in reversed(out) if x["version"]]


def quilt_installer_latest() -> tuple[str, str]:
    versions = maven_metadata_versions(f"{QUILT_MAVEN}org/quiltmc/quilt-installer/maven-metadata.xml")
    if not versions:
        raise NetworkError("获取 Quilt 安装器版本失败")
    ver = versions[-1]
    return ver, f"{QUILT_MAVEN}org/quiltmc/quilt-installer/{ver}/quilt-installer-{ver}.jar"


def forge_version_list(mc: str | None = None) -> list[str]:
    versions = maven_metadata_versions(f"{FORGE_MAVEN}/maven-metadata.xml")
    versions = [v for v in versions if "-" not in v or True]
    if mc:
        versions = [v for v in versions if v.startswith(f"{mc}-")]
    # 新版在前
    def key(v: str):
        try:
            return [int(x) for x in v.split("-")[-1].split(".")]
        except ValueError:
            return [0]
    return sorted(versions, key=key, reverse=True)


def forge_promos() -> dict:
    try:
        return get_json("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json",
                        timeout=25).get("promos", {})
    except Exception:
        return {}


def neoforge_version_list(mc: str | None = None) -> list[str]:
    versions = maven_metadata_versions(f"{NEOFORGE_MAVEN_MIRROR}/maven-metadata.xml") \
               or maven_metadata_versions(f"{NEOFORGE_MAVEN}/maven-metadata.xml")
    if mc:
        versions = [v for v in versions if v.startswith(mc)]
    return sorted(set(versions), reverse=True)


# --------------------------------------------------------------------------- 主安装器


@dataclass
class InstallerPaths:
    root: Path
    versions: Path
    libraries: Path
    assets: Path
    cache: Path

    @classmethod
    def from_root(cls, root: Path) -> "InstallerPaths":
        root = Path(root)
        p = cls(root=root, versions=root / "versions", libraries=root / "libraries",
                assets=root / "assets", cache=root / "cache")
        for d in (p.versions, p.libraries, p.assets, p.cache):
            d.mkdir(parents=True, exist_ok=True)
        return p


class GameInstaller:
    def __init__(self, paths_root: InstallerPaths, source: SourceManager | None = None,
                 threads: int = 32, report: ReportCB = _noop_report):
        self.p = paths_root
        self.source = source or SourceManager()
        self.threads = threads
        self.report = report

    # =========================================================== 版本清单
    def manifest(self, refresh: bool = False) -> dict:
        cache = self.p.cache / "version_manifest.json"
        if cache.exists() and not refresh and time.time() - cache.stat().st_mtime < 3600:
            try:
                return json.loads(cache.read_text("utf-8"))
            except Exception:
                pass
        data = get_json(self.source.source.version_manifest, timeout=30)
        try:
            cache.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        except Exception:
            pass
        return data

    def version_list(self, refresh: bool = False) -> list[dict]:
        return self.manifest(refresh).get("versions", [])

    def installed_versions(self) -> list[str]:
        return sorted(p.name for p in self.p.versions.iterdir()
                      if p.is_dir() and (p / f"{p.name}.json").exists())

    # =========================================================== 下载原版资源
    def download_libraries(self, profile: VersionProfile, features: set[str] | None = None) -> int:
        tasks: list[DownloadTask] = []
        for lib in profile.libraries(self.p.libraries, features):
            if lib.path.exists() and lib.sha1:
                continue
            url = lib.url
            if not url:
                url = maven_url("https://libraries.minecraft.net/", lib.name)
            url = self.source.mirror_url(url)
            tasks.append(DownloadTask(url=url, dest=lib.path, sha1=lib.sha1 or None,
                                      size=lib.size or None, key=lib.name,
                                      mirrors=[maven_url("https://libraries.minecraft.net/", lib.name)] if url != lib.url else []))
        return self._run_tasks(tasks, "正在下载依赖库")

    def download_client_jar(self, profile: VersionProfile) -> Path:
        jar_path = self.p.versions / profile.id / f"{profile.id}.jar"
        info = {}
        for layer in profile.chain:
            if layer.get("downloads", {}).get("client"):
                info = layer["downloads"]["client"]
        if not info:
            return jar_path
        if not jar_path.exists() or not jar_path.stat().st_size == info.get("size", -1):
            url = self.source.mirror_url(info["url"])
            self._run_tasks([DownloadTask(url=url, dest=jar_path, sha1=info.get("sha1"),
                                          size=info.get("size"), key=f"{profile.id}.jar")],
                            "正在下载游戏主文件")
        return jar_path

    def download_assets(self, profile: VersionProfile) -> None:
        idx_info = profile.asset_index_info or {}
        index_id = idx_info.get("id")
        if not index_id:
            return
        index_file = self.p.assets / "indexes" / f"{index_id}.json"
        if not index_file.exists():
            url = idx_info.get("url") or ""
            if self.source.source.key != "official":
                alt = f"{self.source.source.asset_index_base}/{index_id}.json"
                url = alt
            index_file.parent.mkdir(parents=True, exist_ok=True)
            ok = False
            for u in [url, idx_info.get("url"), f"https://bmclapi2.bangbang93.com/assets/indexes/{index_id}.json"]:
                if not u:
                    continue
                try:
                    data = get_bytes(self.source.mirror_url(u))
                    index_file.write_bytes(data)
                    ok = True
                    break
                except Exception:
                    continue
            if not ok:
                self.report("下载资源索引失败", 0, 0, "游戏仍能启动，但音效/材质可能缺失")
                return
        try:
            index = json.loads(index_file.read_text("utf-8"))
        except Exception:
            return
        objects: dict = index.get("objects") or {}
        tasks = []
        for _, obj in objects.items():
            h: str = obj.get("hash", "")
            if not h:
                continue
            dest = self.p.assets / "objects" / h[:2] / h
            if dest.exists() and dest.stat().st_size == obj.get("size", 0) if dest.exists() else False:
                continue
            tasks.append(DownloadTask(url=self.source.asset_url(h), dest=dest, sha1=h,
                                      size=obj.get("size"), key="资源文件",
                                      mirrors=[f"https://resources.download.minecraft.net/{h[:2]}/{h}"]))
        self._run_tasks(tasks, "正在下载游戏资源")
        # 老版本：复制/链接到 assets/virtual/legacy
        if index.get("virtual") or index.get("map_to_resources"):
            self._restore_virtual(index)

    def _restore_virtual(self, index: dict) -> None:
        root_dir = self.p.assets / "virtual" / "legacy"
        for name, obj in (index.get("objects") or {}).items():
            h = obj.get("hash")
            src = self.p.assets / "objects" / h[:2] / h
            dst = root_dir / name
            if dst.exists() or not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except Exception:
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

    def extract_natives(self, profile: VersionProfile) -> Path:
        """解压 native 库到 versions/<id>/natives/。"""
        natives_dir = self.p.versions / profile.id / "natives"
        natives_dir.mkdir(parents=True, exist_ok=True)
        marker = natives_dir / ".hashes.json"
        old = json.loads(marker.read_text("utf-8")) if marker.exists() else {}
        new = {}
        for lib in profile.libraries(self.p.libraries):
            if not lib.is_native or not lib.path.exists():
                continue
            new[lib.name] = str(lib.path.stat().st_mtime)
            if old.get(lib.name) == new[lib.name]:
                continue
            try:
                with zipfile.ZipFile(lib.path) as z:
                    for item in z.namelist():
                        if item.startswith("META-INF") or item.startswith("_data") or item.endswith("/"):
                            continue
                        target = natives_dir / item
                        if target.exists() and target.stat().st_size == z.getinfo(item).file_size:
                            continue
                        z.extract(item, natives_dir)
            except Exception as e:
                self.report("解压 native 失败", 0, 0, str(e))
        marker.write_text(json.dumps(new), "utf-8")
        return natives_dir

    # =========================================================== 安装：原版
    def install_vanilla(self, version_id: str, skip_assets: bool = False) -> str:
        self.report("获取版本信息…", 0, 1, version_id)
        versions_index = {v["id"]: v for v in self.version_list()}
        if version_id not in versions_index:
            raise NetworkError(f"找不到版本 {version_id}")
        entry = versions_index[version_id]
        # 版本 json（支持 inheritsFrom 时需要先建掉链接——这里直接下载）
        target_dir = self.p.versions / version_id
        target_dir.mkdir(parents=True, exist_ok=True)
        json_path = target_dir / f"{version_id}.json"
        if not json_path.exists():
            data = get_json(entry["url"], timeout=30)
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        profile = VersionProfile.load(self.p.versions, version_id)
        self.download_client_jar(profile)
        self.download_libraries(profile)
        self.extract_natives(profile)
        if not skip_assets:
            self.download_assets(profile)
        self.report("安装完成", 1, 1, version_id)
        return version_id

    # =========================================================== 安装：Fabric
    def install_fabric(self, mc: str, loader_version: str | None = None) -> str:
        self.report("获取 Fabric 版本…", 0, 1, mc)
        entries = get_json(f"{FABRIC_META}/versions/loader/{mc}", timeout=25)
        if not entries:
            raise NetworkError(f"Fabric 不支持 {mc}")
        pick = entries[0]
        if loader_version:
            cand = [e for e in entries if e["loader"]["version"] == loader_version]
            if not cand:
                raise NetworkError(f"找不到 Fabric Loader {loader_version}")
            pick = cand[0]
        loader = pick["loader"]
        intermediary = pick.get("intermediary", {})
        lver = loader["version"]
        vid = f"fabric-loader-{lver}-{mc}"
        self.report("正在装配 Fabric…", 0, 1, vid)
        lm = pick.get("launcherMeta") or {}
        main_class = lm.get("mainClass")
        if isinstance(main_class, dict):
            main_class = main_class.get("client") or "net.fabricmc.loader.impl.launch.knot.KnotClient"
        main_class = main_class or "net.fabricmc.loader.impl.launch.knot.KnotClient"

        libs: list[dict] = []

        def add_lib(name: str, url: str = FABRIC_MAVEN, sha1: str = "", size: int = 0):
            rel = maven_relative(name)
            full = f"{url.rstrip('/')}/{rel}"
            libs.append({"name": name, "url": url,
                         "downloads": {"artifact": {"path": rel, "url": full, "sha1": sha1, "size": size}}})

        for group in ("common", "client"):
            for l in (lm.get("libraries") or {}).get(group, []) or []:
                add_lib(l["name"], l.get("url") or FABRIC_MAVEN, l.get("sha1", ""), l.get("size", 0))
        # loader 与 intermediary 不在 libraries 里时会自己带上
        add_lib(f"net.fabricmc:fabric-loader:{lver}")
        iv = intermediary.get("version")
        if iv:
            add_lib(f"net.fabricmc:intermediary:{iv}")
        raw = {
            "id": vid, "inheritsFrom": mc, "type": "release", "mainClass": main_class,
            "libraries": libs,
            "arguments": {"jvm": ["-DFabricMcEmu=net.minecraft.client.main.Main"], "game": []},
            "releaseTime": "", "time": "",
            "extra": {"loader": "fabric", "fabricVersion": lver, "mcVersion": mc},
        }
        return self._write_modded_profile(vid, raw, mc)

    # =========================================================== 安装：Quilt
    def install_quilt(self, mc: str, loader_version: str | None = None) -> str:
        self.report("获取 Quilt 安装器…", 0, 1, mc)
        self._ensure_vanilla(mc)
        iver, url = quilt_installer_latest()
        jar = self.p.cache / f"quilt-installer-{iver}.jar"
        self._run_tasks([DownloadTask(url=url, dest=jar, key="Quilt 安装器")], "下载 Quilt 安装器")
        before = set(self.installed_versions())
        args = ["install", "client", mc]
        if loader_version:
            args.append(loader_version)
        args.append(f"--install-dir={self.p.root}")
        self._run_installer(jar, args, "Quilt")
        return self._new_version(before, "quilt")

    # =========================================================== 安装：Forge
    def install_forge(self, mc: str, forge_version: str, java_path: str = "") -> str:
        self.report("准备 Forge 安装…", 0, 1, f"{mc}-{forge_version}")
        self._ensure_vanilla(mc)
        self._ensure_launcher_profile(mc)
        full = forge_version if forge_version.startswith(mc) else f"{mc}-{forge_version}"
        name = f"net.minecraftforge:forge:{full}"
        url = f"{FORGE_MAVEN}/{full}/forge-{full}-installer.jar"
        jar = self.p.cache / f"forge-{full}-installer.jar"
        self._run_tasks([DownloadTask(url=url, dest=jar, key="Forge 安装器",
                                      mirrors=[maven_url("https://bmclapi2.bangbang93.com/maven/", name, "jar")
                                               .replace(f"net/minecraftforge/forge/{full}/",
                                                        f"net/minecraftforge/forge/{full}/")
                                               .replace(".jar", "-installer.jar")])],
                        "下载 Forge 安装器")
        before = set(self.installed_versions())
        self._run_installer(jar, [f"--installClient={self.p.root}"], "Forge")
        return self._new_version(before, "forge")

    # =========================================================== 安装：NeoForge
    def install_neoforge(self, mc: str, version: str, java_path: str = "") -> str:
        self.report("准备 NeoForge 安装…", 0, 1, f"{mc}-{version}")
        self._ensure_vanilla(mc)
        self._ensure_launcher_profile(mc)
        rel = maven_relative(f"net.neoforged:neoforge:{version}", "jar")
        url = f"{NEOFORGE_MAVEN}/{rel.replace('.jar', '-installer.jar')}"
        mirror_url = f"{NEOFORGE_MAVEN_MIRROR}/{rel.replace('.jar', '-installer.jar')}"
        jar = self.p.cache / f"neoforge-{version}-installer.jar"
        self._run_tasks([DownloadTask(url=mirror_url, dest=jar, key="NeoForge 安装器", mirrors=[url])],
                        "下载 NeoForge 安装器")
        before = set(self.installed_versions())
        self._run_installer(jar, [f"--installClient={self.p.root}"], "NeoForge")
        return self._new_version(before, "neoforge")

    # =========================================================== 辅助
    def _ensure_launcher_profile(self, mc: str) -> None:
        """Forge / NeoForge 安装器要求目标目录是「官方启动器认可的 .minecraft」。

        其中必须存在 launcher_profiles.json（且含目标版本 profile），否则会报
        「you need to run the launcher first」。这里按需生成一份最小可用文件。
        """
        path = self.p.root / "launcher_profiles.json"
        data: dict = {"profiles": {}, "selectedUser": {"account": "", "profile": ""},
                      "authenticationDatabase": {}, "settings": {},
                      "launcherVersion": {"profilesFormat": 2}}
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
            except Exception:
                pass
        now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data.setdefault("profiles", {})[mc] = {
            "name": mc, "type": "custom", "created": now, "lastUsed": now,
            "lastVersionId": mc, "gameDir": str(self.p.root),
        }
        data["selectedProfile"] = mc
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    def _ensure_vanilla(self, mc: str) -> None:
        if (self.p.versions / mc / f"{mc}.json").exists() and (self.p.versions / mc / f"{mc}.jar").exists():
            return
        self.install_vanilla(mc)

    def _write_modded_profile(self, vid: str, raw: dict, mc: str) -> str:
        """写入 mod 加载器版本 json 并补齐依赖/资源。"""
        target = self.p.versions / vid
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{vid}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), "utf-8")
        self._ensure_vanilla(mc)
        profile = VersionProfile.load(self.p.versions, vid)
        self.download_libraries(profile)
        self.extract_natives(profile)
        self.download_assets(profile)
        self.report("安装完成", 1, 1, vid)
        return vid

    def _run_tasks(self, tasks: list[DownloadTask], text: str) -> int:
        if not tasks:
            return 0
        total = len(tasks)
        self.report(text, 0, total, tasks[0].key)
        dl = Downloader(threads=self.threads, source=self.source)
        state = {"last": 0.0}

        def progress(key, done, tot, got, need):
            now = time.time()
            if now - state["last"] > 0.08 or done == tot:
                state["last"] = now
                pct_txt = f"{got / 1024 / 1024:.1f}/{need / 1024 / 1024:.1f} MB" if need else ""
                self.report(text, done, tot, f"{key}  ({pct_txt})")

        ok, bad = dl.download_all(tasks, on_progress=progress,
                                  on_error=lambda t, e: self.report("下载失败", 0, 0, f"{t.key}: {e}"))
        self.report(text, ok, total, "")
        return bad

    def _run_installer(self, jar: Path, args: list[str], name: str, java_path: str = "") -> None:
        java = java_path or shutil.which("java")
        if not java:
            raise RuntimeError(f"安装 {name} 需要 Java 运行环境，请先安装或指定 Java")
        cmd = [java, "-jar", str(jar), *args]
        self.report(f"正在安装 {name}…", 0, 1, "请稍候，安装器可能需要下载依赖")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                                  encoding="utf-8", errors="replace", cwd=str(self.p.cache))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{name} 安装超时")
        out = (proc.stdout or "") + (proc.stderr or "")
        self.report(f"{name} 安装输出", 1, 1, out[-1500:])
        if proc.returncode != 0 and "no installation" in (out or ""):
            raise RuntimeError(f"{name} 安装失败：目标目录缺少该 Minecraft 版本")
        if proc.returncode != 0:
            raise RuntimeError(f"{name} 安装失败（退出码 {proc.returncode}）\n{out[-800:]}")

    def _new_version(self, before: set[str], loader: str) -> str:
        after = set(self.installed_versions())
        new = after - before
        if not new:
            raise RuntimeError(f"{loader} 安装器执行完毕，但没有生成新的版本，请查看日志")
        return sorted(new)[-1]


def detect_loader(version_id: str, versions_dir: Path) -> str:
    """判断一个已安装版本属于什么类型的加载器。"""
    try:
        raw = read_json(versions_dir, version_id)
    except Exception:
        return "unknown"
    vid = raw.get("id", "")
    if vid.startswith("fabric-loader-") or raw.get("extra", {}).get("loader") == "fabric":
        return "fabric"
    if vid.startswith("quilt-loader-"):
        return "quilt"
    libs = json.dumps(raw.get("libraries", []))
    for chain in (raw.get("arguments", {}).get("jvm") or [],):
        libs += json.dumps(chain)
    if "net.neoforged" in libs or "neoforge" in vid.lower():
        return "neoforge"
    if "net.minecraftforge" in libs or "-forge-" in vid or vid.endswith("-forge"):
        return "forge"
    if raw.get("inheritsFrom"):
        try:
            parent = detect_loader(raw["inheritsFrom"], versions_dir)
            if parent != "unknown":
                return parent
        except Exception:
            pass
    return "vanilla"
