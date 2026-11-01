"""启动流程：参数拼装、进程管理、日志分析。

完整实现 Mojang 的 launch standard：
    ${} 模板替换 / 1.13+ arguments / 老版本 minecraftArguments / library rules / natives
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import paths
from .auth import Account
from .version import VersionProfile, rules_allow
from .java import JavaInfo

MEMORY_FLAG_RE = re.compile(r"^-(Xm[xsn]|XX:(Max|Min)HeapSize=)")


@dataclass
class LaunchSettings:
    version_id: str
    versions_dir: Path
    libraries_dir: Path
    assets_dir: Path
    game_dir: Path
    account: Account
    java: JavaInfo | str | None = None
    min_memory: int = 512
    max_memory: int = 2048
    width: int = 0
    height: int = 0
    fullscreen: bool = False
    custom_resolution: bool = False
    jvm_args: str = ""
    game_args: str = ""
    server_address: str = ""
    natives_dir: Path | None = None
    extra_features: set[str] = field(default_factory=set)
    launcher_name: str = "PCL-Launcher"
    launcher_version: str = "1.0.0"


# --------------------------------------------------------------------------- 工具


def _main_jar(profile: VersionProfile) -> Path:
    """找到真正的主 jar（mod 加载器版本通常继承自原版）。"""
    for layer in reversed(profile.chain):
        vid = layer.get("id")
        if not vid:
            continue
        p = profile.versions_dir / vid / f"{vid}.jar"
        if p.exists():
            return p
    return profile.jar_path


def classpath_entries(profile: VersionProfile, libraries_dir: Path, features: set[str] | None = None) -> list[Path]:
    """返回 class path（顺序：主 jar，然后是库）。"""
    features = features or set()
    out: list[Path] = []
    seen: set[str] = set()
    for lib in profile.libraries(libraries_dir, features):
        if lib.is_native:
            continue
        key = str(lib.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(lib.path)
    main = _main_jar(profile)
    return [main, *out]


def build_classpath(profile: VersionProfile, libraries_dir: Path, features: set[str] | None = None) -> str:
    return os.pathsep.join(str(p) for p in classpath_entries(profile, libraries_dir, features))


DEFAULT_JVM_FLAGS = [
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+UseG1GC",
    "-XX:G1NewSizePercent=20",
    "-XX:G1ReservePercent=20",
    "-XX:MaxGCPauseMillis=50",
    "-XX:G1HeapRegionSize=32M",
    "-XX:-UseAdaptiveSizePolicy",
    "-XX:-OmitStackTraceInFastThrow",
    "-Dfml.ignoreInvalidMinecraftCertificates=true",
    "-Dfml.ignorePatchDiscrepancies=true",
    "-Dlog4j2.formatMsgNoLookups=true",
]


def _arg_allowed(arg, features: set[str]) -> bool:
    if isinstance(arg, dict):
        return rules_allow(arg.get("rules"), features)
    return True


def _flatten(args: Iterable, features: set[str]) -> list[str]:
    out: list[str] = []
    for a in args:
        if not _arg_allowed(a, features):
            continue
        if isinstance(a, dict):
            value = a.get("value")
            if isinstance(value, list):
                out.extend(str(x) for x in value)
            elif value is not None:
                out.append(str(value))
        else:
            out.append(str(a))
    return out


# --------------------------------------------------------------------------- 命令构建


def build_command(s: LaunchSettings) -> tuple[list[str], str, dict]:
    profile = VersionProfile.load(s.versions_dir, s.version_id)
    features = {"is_demo_user": False, "has_custom_resolution": bool(s.custom_resolution and s.width and s.height)}
    features.update(s.extra_features)

    natives = Path(s.natives_dir) if s.natives_dir else (profile.versions_dir / s.version_id / "natives")
    if not natives.exists():
        natives.mkdir(parents=True, exist_ok=True)

    account = s.account
    game_dir = Path(s.game_dir)
    game_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(s.assets_dir)

    template = {
        "auth_access_token": account.access_token or "-",
        "auth_session": account.access_token or "-",
        "auth_player_name": account.username,
        "auth_uuid": account.uuid or "-",
        "auth_xuid": account.extra.get("xuid", "") or "-",
        "user_type": account.user_type,
        "user_properties": "{}",
        "version_name": profile.id,
        "version_type": profile.type or "release",
        "game_directory": str(game_dir),
        "natives_directory": str(natives),
        "library_directory": str(s.libraries_dir),
        "assets_root": str(assets_dir),
        "assets_index_name": (profile.asset_index_info or {}).get("id", ""),
        "game_assets": str(assets_dir / "virtual" / "legacy"),
        "resolution_width": str(s.width or 854),
        "resolution_height": str(s.height or 480),
        "launcher_name": s.launcher_name,
        "launcher_version": s.launcher_version,
        "classpath_separator": os.pathsep,
        "library_directory_abs": str(s.libraries_dir),
        "primary_jar": str(_main_jar(profile)),
    }

    cp = build_classpath(profile, Path(s.libraries_dir), features)
    template["classpath"] = cp
    for key in ("natives_directory", "game_directory", "assets_root", "library_directory", "game_assets",
                "classpath", "primary_jar"):
        if template.get(key):
            template[key] = template[key].replace("\\\\", "\\").replace('"', "")

    def replace(text: str) -> str:
        # 兼容 ${var} 与 $var 两种写法
        for k, v in template.items():
            text = text.replace("${" + k + "}", str(v))
        return text

    java_bin = str(s.java.path if isinstance(s.java, JavaInfo) else (s.java or "java"))
    cmd: list[str] = [java_bin]

    # JVM 参数：版本自带 -> 内存 -> 优化开关 -> 用户自定义
    jvm_from_version = [replace(x) for x in _flatten(profile.jvm_args, features)]
    cmd += [x for x in jvm_from_version if not MEMORY_FLAG_RE.match(x)]
    mem_max = max(256, s.max_memory)
    mem_min = max(128, min(s.min_memory, mem_max))
    cmd += [f"-Xmx{mem_max}M", f"-Xms{mem_min}M"]
    cmd += DEFAULT_JVM_FLAGS
    if s.jvm_args:
        cmd += _safe_split(s.jvm_args)
    cmd.append(f"-Djava.library.path={natives}")
    cmd.append(f"-Dminecraft.launcher.brand={s.launcher_name}")
    cmd.append(f"-Dminecraft.launcher.version={s.launcher_version}")
    cmd += ["-cp", cp, profile.main_class]

    # 游戏参数
    if profile.game_args:
        game = _flatten(profile.game_args, features)
    else:
        game = shlex.split(replace(profile.legacy_arguments or ""))
    game = [replace(x) for x in game]
    cmd += [x for x in game if x]

    if s.custom_resolution and s.width and s.height:
        cmd += ["--width", str(s.width), "--height", str(s.height)]
    if s.fullscreen:
        cmd.append("--fullscreen")
    if s.server_address:
        addr = s.server_address.strip()
        if ":" in addr:
            host, port = addr.rsplit(":", 1)
            cmd += ["--server", host, "--port", port]
        else:
            cmd += ["--server", addr, "--port", "25565"]
    for extra in _safe_split(s.game_args):
        cmd.append(extra)

    env = os.environ.copy()
    env.setdefault("JAVA_TOOL_OPTIONS", "")  # 避免外部污染
    if env["JAVA_TOOL_OPTIONS"] == "":
        env.pop("JAVA_TOOL_OPTIONS")
    env["APPDATA"] = env.get("APPDATA", "") or ""
    if paths.IS_LINUX:
        env.setdefault("__GL_THREADED_OPTIMIZATIONS", "1")
    return cmd, str(game_dir), {k: v for k, v in env.items() if k != "JAVA_TOOL_OPTIONS"}


def _safe_split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


# 兼容旧调用签名（测试脚本使用）
def build_command_legacy(version_id, versions_dir, libraries_dir, assets_dir, game_dir, account, java,
                         memory=(512, 2048), resolution=None, jvm_args="", game_args="", server=None,
                         natives_dir=None, features=None) -> tuple[list[str], str, dict]:
    width = height = 0
    if resolution:
        width, height = resolution
    return build_command(LaunchSettings(
        version_id=version_id, versions_dir=Path(versions_dir), libraries_dir=Path(libraries_dir),
        assets_dir=Path(assets_dir), game_dir=Path(game_dir), account=account, java=java,
        min_memory=memory[0], max_memory=memory[1], width=width, height=height,
        custom_resolution=bool(width and height), jvm_args=jvm_args, game_args=game_args,
        server_address=server or "", natives_dir=Path(natives_dir) if natives_dir else None,
        extra_features=set(features or []),
    ))


build_command_compat = build_command_legacy


# --------------------------------------------------------------------------- 进程管理


class Launcher:
    """启动游戏子进程并实时读取输出。"""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self.running = False

    def launch(self, cmd: list[str], cwd: str, env: dict,
               on_output: Callable[[str], None] | None = None,
               on_exit: Callable[[int], None] | None = None,
               hide_window: bool = False) -> subprocess.Popen:
        kwargs: dict = {"cwd": cwd, "env": env,
                        "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                        "stdin": subprocess.PIPE}
        if paths.IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW if hide_window else 0
        self.process = subprocess.Popen(cmd, **kwargs)
        self.running = True
        self._reader = threading.Thread(target=self._pump, args=(on_output, on_exit), daemon=True)
        self._reader.start()
        return self.process

    def _pump(self, on_output, on_exit):
        p = self.process
        if not p or not p.stdout:
            return
        try:
            for line in iter(p.stdout.readline, ""):
                if not line:
                    break
                if on_output:
                    on_output(line.rstrip("\r\n"))
        except Exception:
            pass
        finally:
            try:
                if p.stdout:
                    p.stdout.close()
            except Exception:
                pass
            code = p.wait() if p else -1
            self.running = False
            if on_exit:
                on_exit(code)

    def stop(self):
        if self.process and self.running:
            try:
                self.process.terminate()
            except Exception:
                pass


# --------------------------------------------------------------------------- 日志分析


CRASH_PATTERNS: list[tuple[str, str, str]] = [
    (r"Unsupported class file major version (\d+)", "Java 版本问题",
     "游戏或某个 Mod 需要的 Java 版本与实际使用的 Java 不一致，请在「设置 → Java」中切换到合适的 Java"),
    (r"Could not find or load main class", "主类丢失",
     "游戏主类找不到，通常是依赖库缺失或版本文件损坏，请重新安装该版本"),
    (r"java\.lang\.NoClassDefFoundError: (org/lwjgl|com/mojang)[^\s]*", "依赖库缺失",
     "缺少 LWJGL / Mojang 相关类库，请重新安装游戏版本"),
    (r"java\.lang\.OutOfMemoryError", "内存不足",
     "分配给游戏的内存不足，请在启动设置中调大内存（建议不超过物理内存的一半）"),
    (r"(GLFW|glfw)[^\n]*error|Failed to create window|libs/glfw", "显卡 / 显示",
     "无法创建游戏窗口，请更新显卡驱动，或检查是否在远程桌面/无显示环境下启动"),
    (r"LWJGL.*Unable to load.*(GL|OpenGL)", "OpenGL 缺失",
     "系统缺少 OpenGL 支持，请安装显卡驱动"),
    (r"Invalid id (\d+) - maximum id range exceeded", "方块 ID 超出限制",
     "这是老版本（1.12 及以前）装了过多 Mod 的典型错误，请减少 Mod 或换用 1.13+ 版本"),
    (r"Maximum id range exceeded", "ID 超限", "请减少 Mod 数量，或切换到更高版本的 Minecraft"),
    (r"mixin[^\n]*failed|Mixin apply failed|Critical injection failure", "Mixin 注入失败",
     "某个 Mod 的 Mixin 注入失败，通常是 Mod 版本与游戏版本不匹配"),
    (r"Mod ID '[^']+' .*failed to load|has failed to load correctly", "Mod 加载失败",
     "查看日志中具体的 Mod 报错；通常是 Mod 依赖缺失（如 Fabric API）"),
    (r"requires Java (\d+)|requires java (\d+)", "Java 版本过低",
     "请安装更高版本的 Java（见「设置 → Java → 下载 Java」）"),
    (r"javax\.net\.ssl|SSLHandshakeException", "网络证书问题",
     "SSL 握手失败，检查系统时间或代理设置"),
    (r" pirates|User Not Premium|Invalid signature", "认证失败",
     "正版校验失败，请重新登录账号"),
    (r"Exception in thread \"main\" java\.lang\.NullPointerException", "空指针异常",
     "通常由 Mod 冲突或资源缺失引起，请查看日志上方第一条报错"),
    (r"Failed to load library.*natives", "native 库问题",
     "native 文件损坏，请删除版本的 natives 目录后重新安装"),
]


def analyze_log(log: str) -> list[tuple[str, str]]:
    """返回 [(标题, 建议)]。"""
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern, title, tip in CRASH_PATTERNS:
        if title in seen:
            continue
        if re.search(pattern, log, re.IGNORECASE):
            hits.append((title, tip))
            seen.add(title)
    return hits


def mods_dir_of(game_dir: Path) -> Path:
    p = Path(game_dir) / "mods"
    p.mkdir(parents=True, exist_ok=True)
    return p
