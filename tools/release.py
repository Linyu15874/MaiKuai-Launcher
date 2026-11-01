#!/usr/bin/env python3
"""发布新版本：版本号自增 → 构建 → 提交+打 tag+推送 → 创建 GitHub Release 并上传 exe。

版本号唯一来源：launcher/__init__.py 的 ``__version__``。

用法：
    python tools/release.py                       # 默认 patch 自增（1.0.0 -> 1.0.1）并完整发布
    python tools/release.py --bump minor          # 1.0.0 -> 1.1.0
    python tools/release.py --bump major          # 1.0.0 -> 2.0.0
    python tools/release.py --no-build            # 用已有 dist/PCL-Launcher.exe，不重新构建
    python tools/release.py --dry-run             # 只打印计划，不实际提交/发布
    python tools/release.py --token ghp_xxx        # 或用环境变量 GITHUB_PAT / GH_TOKEN

GitHub 上传所需 Token：通过 --token 或环境变量 GITHUB_PAT / GH_TOKEN 提供（需 repo 权限）。
仓库地址自动从 git remote 'origin' 推断。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "launcher" / "__init__.py"
EXE = ROOT / "dist" / "PCL-Launcher.exe"
VER_RE = re.compile(r'^__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.M)
SEMVER_RE = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')


# --------------------------------------------------------------------------- 版本号
def read_version() -> str:
    m = VER_RE.search(INIT.read_text("utf-8"))
    if not m:
        raise RuntimeError("无法在 launcher/__init__.py 中找到 __version__")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def write_version(new: str) -> None:
    text = INIT.read_text("utf-8")
    text = VER_RE.sub(f'__version__ = "{new}"', text, count=1)
    INIT.write_text(text, "utf-8")


def bump(ver: str, part: str) -> str:
    major, minor, patch = (int(x) for x in ver.split("."))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


# --------------------------------------------------------------------------- git / repo
def run_git(args: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(ROOT)] + args
    res = subprocess.run(cmd, capture_output=capture, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{res.stderr.strip()}")
    return res


def repo_owner_name() -> tuple[str, str]:
    res = run_git(["remote", "get-url", "origin"], check=False)
    url = (res.stdout or res.stderr or "").strip()
    if not url:
        raise RuntimeError("未配置 git remote 'origin'")
    if "@" in url:                      # git@github.com:owner/repo.git
        url = url.split("@", 1)[1]
        url = url.split(":", 1)[1] if ":" in url else url
    elif "github.com/" in url:          # https://.../owner/repo.git
        url = url.split("github.com/", 1)[1]
    url = url.replace(".git", "")
    parts = [p for p in url.split("/") if p]
    if len(parts) < 2:
        raise RuntimeError(f"无法从 remote 解析仓库：{url}")
    return parts[-2], parts[-1]


def last_tag() -> str | None:
    res = run_git(["tag", "--list"], check=False)
    tags = [t.strip() for t in (res.stdout or "").splitlines() if t.strip()]
    best = None
    for t in tags:
        m = SEMVER_RE.search(t)
        if not m:
            continue
        key = tuple(int(x) for x in m.groups())
        if best is None or key > best[0]:
            best = (key, t)
    return best[1] if best else None


def release_notes(version: str, since_tag: str | None) -> str:
    if since_tag:
        rng, header = f"{since_tag}..HEAD", f"自 {since_tag} 起的变更："
    else:
        rng, header = "HEAD", "变更内容："
    res = run_git(["log", rng, "--pretty=format:- %s"], check=False)
    lines = [l for l in (res.stdout or "").splitlines() if l.strip()]
    body = "\n".join(lines) if lines else "- （无提交记录）"
    return (
        f"## 麦块启动器 {version}\n\n"
        f"{header}\n{body}\n\n"
        f"Windows 单文件绿色版（内置 VC++ 运行库）见下方附件 `PCL-Launcher.exe`。\n"
        f"源码见仓库文件；本地重新打包请使用 `build_exe.bat`（Windows）或 `tools/build_exe.py`。"
    )


# --------------------------------------------------------------------------- GitHub
def gh_api(method: str, url: str, token: str, data=None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "pcl-release-script")
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode("utf-8")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw).get("message", raw)
        except Exception:
            msg = raw
        return e.code, {"message": msg}


def github_release(owner: str, repo: str, tag: str, name: str, body: str, token: str) -> dict:
    status, data = gh_api("POST", f"https://api.github.com/repos/{owner}/{repo}/releases", token,
                          data={"tag_name": tag, "name": name, "body": body,
                                "draft": False, "prerelease": False})
    if status == 201:
        return data
    if status == 422:  # 已存在同名 tag 的 release
        st2, data2 = gh_api("GET", f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}", token)
        if st2 == 200:
            return data2
    raise RuntimeError(f"创建 Release 失败（{status}）：{data.get('message')}")


def delete_existing_asset(owner: str, repo: str, tag: str, asset_name: str, token: str) -> None:
    st, rel = gh_api("GET", f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}", token)
    if st != 200:
        return
    for a in rel.get("assets", []):
        if a.get("name") == asset_name:
            gh_api("DELETE", f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{a['id']}", token)


def upload_asset(upload_url: str, asset_path: Path, token: str) -> str:
    url = upload_url.split("{")[0] + f"?name={asset_path.name}"
    with open(asset_path, "rb") as fh:
        data = fh.read()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("User-Agent", "pcl-release-script")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8")).get("browser_download_url", "")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"上传附件失败（{e.code}）：{raw}")


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="发布新版本")
    ap.add_argument("--bump", choices=["major", "minor", "patch"], default="patch")
    ap.add_argument("--no-build", action="store_true", help="不重新构建，使用已有 dist/PCL-Launcher.exe")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不实际提交/发布")
    ap.add_argument("--token", default=os.environ.get("GITHUB_PAT") or os.environ.get("GH_TOKEN"),
                    help="GitHub Token（也可用环境变量 GITHUB_PAT / GH_TOKEN）")
    ap.add_argument("--message", default="", help="附加到发布说明的摘要")
    args = ap.parse_args()

    old = read_version()
    new = bump(old, args.bump)
    print(f"[release] {old} -> {new}  (bump={args.bump})")

    owner, repo = repo_owner_name()
    print(f"[release] 仓库：{owner}/{repo}")
    since = last_tag()
    print(f"[release] 上一 tag：{since or '（无）'}")

    if args.dry_run:
        notes = release_notes(new, since)
        print("---- 发行说明预览 ----\n" + notes)
        print(f"[release] dry-run 完成。将构建并发布 v{new}")
        return 0

    write_version(new)
    print(f"[release] 已更新 launcher/__init__.py -> {new}")

    if not args.no_build:
        rc = subprocess.call([sys.executable, str(ROOT / "tools" / "build_exe.py")])
        if rc != 0:
            print("[release] 构建失败，中止", file=sys.stderr)
            return 1
    if not EXE.exists():
        print(f"[release] 找不到产物：{EXE}", file=sys.stderr)
        return 1

    run_git(["add", "-A"])
    commit_msg = f"Release v{new}"
    if args.message:
        commit_msg += f"\n\n{args.message}"
    run_git(["commit", "-m", commit_msg], check=False)
    run_git(["tag", f"v{new}"])
    run_git(["push", "origin", "main"], check=False)
    run_git(["push", "origin", "--tags"], check=False)
    print(f"[release] 已提交并推送 v{new}")

    if not args.token:
        print("[release] 未提供 GitHub Token，跳过 Release 创建（代码已推送）。")
        print(f"[release] 手动发布：https://github.com/{owner}/{repo}/releases/new?tag=v{new}")
        return 0

    notes = release_notes(new, since)
    rel = github_release(owner, repo, f"v{new}", f"v{new}", notes, args.token)
    delete_existing_asset(owner, repo, f"v{new}", EXE.name, args.token)
    url = upload_asset(rel["upload_url"], EXE, args.token)
    print(f"[release] Release 已发布：https://github.com/{owner}/{repo}/releases/tag/v{new}")
    if url:
        print(f"[release] 下载链接：{url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
