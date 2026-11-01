"""Minecraft 版本元数据解析：继承链合并、库规则判定、参数模板。

对标 HMCL/PCL2 的做法：支持 inheritsFrom 多层继承、1.13+ 的 arguments、
老版本的 minecraftArguments、以及 os/arch rules 过滤。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import paths


def _rule_hits(rule: dict, features: set[str]) -> bool:
    """判定某条规则的 os / features 条件是否与当前环境匹配。"""
    if r_os := rule.get("os"):
        name = r_os.get("name")
        if name and name != paths.OS_NAME:
            return False
        arch = r_os.get("arch")
        if arch and arch != paths.OS_ARCH:
            return False
        version = r_os.get("version")
        if version:
            import re as _re

            pattern = version.replace(".", r"\.").replace("+", r"\+").replace("*", ".*")
            try:
                if not _re.match(pattern, paths.OS_VERSION):
                    return False
            except Exception:
                return False
    if feats := rule.get("features"):
        for k, v in feats.items():
            if bool(v) != (k in features):
                return False
    return True


def rules_allow(rules: Iterable[dict] | None, features: set[str] | None = None) -> bool:
    """Minecraft 规则判定：无规则 -> 允许；有规则 -> 默认拒绝，最后一条命中的决定结果。"""
    features = features or set()
    if not rules:
        return True
    allowed = False
    for rule in rules:
        if "action" not in rule:
            continue
        if _rule_hits(rule, features):
            allowed = rule["action"] == "allow"
    return allowed


@dataclass
class Library:
    name: str
    path: Path
    url: str = ""
    sha1: str = ""
    size: int = 0
    native_classifier: str = ""

    @property
    def is_native(self) -> bool:
        return bool(self.native_classifier)


def _artifact_info(lib: dict) -> dict:
    """取当前 OS 适用的 artifacts / classifiers 信息。"""
    dl = lib.get("downloads") or {}
    if dl.get("artifact"):
        return dl["artifact"]
    return {}


class VersionProfile:
    """一个已安装版本的完整 profile（已合并继承链）。"""

    def __init__(self, raw: dict, versions_dir: Path, chain: list[dict] | None = None):
        self.versions_dir = Path(versions_dir)
        self.raw = raw
        self.chain = chain or [raw]
        self.id: str = raw.get("id", "")
        self.main_class: str = raw.get("mainClass", "")
        self.type: str = raw.get("type", "custom")
        self.asset_index_info: dict = raw.get("assetIndex", raw.get("assets")) or {}
        self.release_time: str = raw.get("releaseTime", "")
        self.java_version: dict = raw.get("javaVersion", {})
        self.compliance: int = raw.get("complianceLevel", 0)
        self.jvm_args: list[Any] = []
        self.game_args: list[Any] = []
        self.legacy_arguments: str = ""
        self.libraries_raw: list[dict] = []
        self._merge()

    # ---------------------------------------------------------------- 合并
    @classmethod
    def load(cls, versions_dir: Path, version_id: str, seen: set[str] | None = None) -> "VersionProfile":
        versions_dir = Path(versions_dir)
        seen = seen or set()
        if version_id in seen:
            raise RuntimeError(f"版本继承存在循环：{version_id}")
        seen.add(version_id)
        json_path = versions_dir / version_id / f"{version_id}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"找不到版本 {version_id} 的配置文件：{json_path}")
        raw = json.loads(json_path.read_text("utf-8"))
        parent = raw.get("inheritsFrom")
        chain: list[dict] = []
        if parent:
            try:
                p = cls.load(versions_dir, parent, set(seen))
                chain = p.chain + [raw]
            except FileNotFoundError as e:
                raise FileNotFoundError(f"版本 {version_id} 依赖 {parent}，但它未安装（{e}）")
        else:
            chain = [raw]
        return cls(chain[-1], versions_dir, chain)

    def _merge(self) -> None:
        jvm: list[Any] = []
        game: list[Any] = []
        libs: list[dict] = []
        asset_index: dict = {}
        main_class = ""
        minecraft_args = ""
        downloads: dict = {}
        java_version: dict = {}
        asset_type = ""
        for layer in self.chain:
            libs.extend(layer.get("libraries") or [])
            args = layer.get("arguments") or {}
            jvm.extend(args.get("jvm") or [])
            game.extend(args.get("game") or [])
            if layer.get("minecraftArguments"):
                minecraft_args = layer["minecraftArguments"]
            if layer.get("assetIndex"):
                asset_index = layer["assetIndex"]
            elif layer.get("assets"):
                asset_type = layer["assets"]
            if layer.get("mainClass"):
                main_class = layer["mainClass"]
            if layer.get("downloads"):
                downloads.update(layer["downloads"])
            if layer.get("javaVersion"):
                java_version = layer["javaVersion"]
        self.jvm_args, self.game_args = jvm, game
        self.libraries_raw = libs
        self.legacy_arguments = minecraft_args
        if asset_index:
            self.asset_index_info = asset_index
        elif asset_type:
            self.asset_index_info = {"id": asset_type, "legacy": True}
        if main_class:
            self.main_class = main_class
        # 顺序：父版本的 jvm 参数在前
        self.jvm_args = _dedup_flags(self.jvm_args)

    # ---------------------------------------------------------------- 库
    def libraries(self, libraries_dir: Path, features: set[str] | None = None) -> list[Library]:
        features = features or set()
        out: list[Library] = []
        seen: set[str] = set()
        for lib in self.libraries_raw:
            if not rules_allow(lib.get("rules"), features):
                continue
            name = lib["name"]
            if name in seen:
                continue
            seen.add(name)
            art = _artifact_info(lib)
            if art and art.get("path"):
                lpath = libraries_dir / art["path"]
                out.append(Library(name=name, path=lpath, url=art.get("url", ""),
                                   sha1=art.get("sha1", ""), size=art.get("size", 0)))
            else:
                out.append(Library(name=name, path=paths.library_path(libraries_dir.parent, name),
                                   url=lib.get("url", "")))
            # natives
            natives = lib.get("natives") or {}
            classifier_key = natives.get(paths.OS_NAME)
            if not classifier_key and paths.OS_ARCH == "arm64":
                classifier_key = natives.get(f"{paths.OS_NAME}-arm64")
            if classifier_key:
                final = classifier_key.replace("${arch}", paths.OS_ARCH)
                classifiers = (lib.get("downloads") or {}).get("classifiers") or {}
                info = classifiers.get(final) or {}
                cpath = info.get("path") or _default_native_path(name, final)
                out.append(Library(name=f"{name}:{final}", path=libraries_dir.parent / cpath if False else libraries_dir / (info.get("path") or cpath),
                                   url=info.get("url", (lib.get("url") or "") and _mangle_native_url(lib, final)),
                                   sha1=info.get("sha1", ""), size=info.get("size", 0),
                                   native_classifier=final))
            # 兼容 forgebootstrapper / maven only
            if not art and lib.get("downloads") is None and lib.get("url"):
                pass
        if self.jarless_entry():
            pass
        return out

    def jarless_entry(self) -> bool:
        return False

    # ---------------------------------------------------------------- 其它
    @property
    def jar_path(self) -> Path:
        return self.versions_dir / self.id / f"{self.id}.jar"

    @property
    def json_path(self) -> Path:
        return self.versions_dir / self.id / f"{self.id}.json"

    def required_java_major(self) -> int:
        v = self.java_version.get("majorVersion")
        if isinstance(v, int) and v:
            return v
        return 8 if str(self.id).startswith("1.") and int(str(self.id).split(".")[1] or 0) < 13 else 17


def _dedup_flags(args: list[Any]) -> list[Any]:
    """移除后面重复出现的 -Xmx / -Xms / Dfml 等JVM开关（后面优先）。"""
    flags = ("-Xmx", "-Xms", "-Xmn", "-XX:HeapDumpPath", "-DignoreList", "-Dos.name",
             "-DFabricMcEmu", "-Dlog4j.configurationFile", "-XX:+UseAdaptiveSizePolicy")
    seen_idx: dict[str, list[int]] = {}
    for i, a in enumerate(args):
        if isinstance(a, str):
            for f in flags:
                if a.startswith(f):
                    seen_idx.setdefault(f, []).append(i)
    drop = set()
    for f, idxs in seen_idx.items():
        if len(idxs) > 1:
            drop.update(idxs[:-1])
    return [a for i, a in enumerate(args) if i not in drop]


def _default_native_path(name: str, classifier: str) -> str:
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    return str(Path(*group.split(".")) / artifact / version / f"{artifact}-{version}-{classifier}.jar")


def _mangle_native_url(lib: dict, classifier: str) -> str:
    base = lib.get("url", "").rstrip("/")
    parts = lib["name"].split(":")
    if len(parts) < 4 and False:
        pass
    rel = _default_native_path(lib["name"], classifier)
    return f"{base}/{rel}" if base else ""


def list_installed(versions_dir: Path) -> list[str]:
    versions_dir = Path(versions_dir)
    if not versions_dir.exists():
        return []
    return sorted(p.name for p in versions_dir.iterdir() if p.is_dir() and (p / f"{p.name}.json").exists())


def read_json(versions_dir: Path, version_id: str) -> dict:
    return json.loads((Path(versions_dir) / version_id / f"{version_id}.json").read_text("utf-8"))
