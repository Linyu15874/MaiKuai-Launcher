"""核心层冒烟测试：真实下载安装 Minecraft，并尝试用 Java 启动验证 classpath。

用法：
    python tools/smoke_core.py versions                 # 列出可用版本
    python tools/smoke_core.py install 1.20.1           # 安装原版
    python tools/smoke_core.py fabric 1.20.1            # 安装 Fabric
    python tools/smoke_core.py forge 1.20.1 47.2.0      # 安装 Forge
    python tools/smoke_core.py launch <version-id>      # 生成启动命令并尝试启动（headless 会失败于 GLFW）
    python tools/smoke_core.py all                      # 一条龙测试
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from launcher.core.config import Config  # noqa: E402
from launcher.core.installer import GameInstaller, InstallerPaths, detect_loader  # noqa: E402
from launcher.core.net import SourceManager  # noqa: E402
from launcher.core import java as java_mod  # noqa: E402
from launcher.core.launch import Launcher, build_command, LaunchSettings  # noqa: E402
from launcher.core.auth import login_offline  # noqa: E402
from launcher.core.version import VersionProfile  # noqa: E402

TEST_ROOT = Path("/tmp/mcl-smoke")


def make_installer(source_key: str = "official", threads: int = 64) -> GameInstaller:
    ip = InstallerPaths.from_root(TEST_ROOT)
    last = {}

    def report(text, cur, tot, detail=""):
        key = (text, cur, tot)
        if key == last.get("key"):
            return
        last["key"] = key
        print(f"  [{cur}/{tot}] {text} {detail[:100]}", flush=True)

    return GameInstaller(ip, SourceManager(source_key), threads=threads, report=report)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--source", default="official")
    a = ap.parse_args()
    inst = make_installer(a.source)

    if a.cmd == "versions":
        vs = inst.version_list()
        print(f"共 {len(vs)} 个版本，前 5：{[v['id'] for v in vs[:5]]}")
        return 0

    if a.cmd == "install":
        t = time.time()
        vid = inst.install_vanilla(a.args[0])
        print(f"OK: {vid}  用时 {time.time() - t:.1f}s")
        return 0

    if a.cmd == "fabric":
        mc = a.args[0]
        loader = a.args[1] if len(a.args) > 1 else None
        t = time.time()
        vid = inst.install_fabric(mc, loader)
        print(f"OK: {vid}  用时 {time.time() - t:.1f}s")
        return 0

    if a.cmd == "forge":
        vid = inst.install_forge(a.args[0], a.args[1])
        print("OK:", vid)
        return 0

    if a.cmd == "neoforge":
        vid = inst.install_neoforge(a.args[0], a.args[1])
        print("OK:", vid)
        return 0

    if a.cmd == "detect":
        print(detect_loader(a.args[0], inst.p.versions))
        return 0

    if a.cmd == "launch":
        cfg = Config(TEST_ROOT / "config.json")
        version_id = a.args[0]
        acc = login_offline("SmokeTester")
        javas = java_mod.scan_system()
        print("Java:", [str(j) for j in javas])
        if not javas:
            print("!! 系统没有 Java")
            return 2
        profile = VersionProfile.load(inst.p.versions, version_id)
        natives = inst.extract_natives(profile)
        cmd, cwd, env = build_command(LaunchSettings(
            version_id=version_id, versions_dir=inst.p.versions, libraries_dir=inst.p.libraries,
            assets_dir=inst.p.assets, game_dir=inst.p.root / "game", account=acc,
            java=javas[0], min_memory=512, max_memory=2048, natives_dir=natives,
        ))
        print("\n命令行：\n", subprocess.list2cmdline(cmd)[:1200], "\ncwd:", cwd)
        print("类路径条目数：", sum(1 for x in cmd if "libraries" in x))
        if "--dry" not in a.args:
            print("\n--- 尝试启动（headless 环境会在 GLFW 阶段失败，属正常）---")
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=180,
                               encoding="utf-8", errors="replace")
            out = (p.stdout or "") + (p.stderr or "")
            print(out[-3000:])
            print("exit:", p.returncode)
        return 0

    if a.cmd == "all":
        print("== 安装原版 1.20.1 ==")
        inst.install_vanilla("1.20.1")
        print("== 安装 Fabric ==")
        vid = inst.install_fabric("1.20.1")
        print("Fabric 版本 id:", vid)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
