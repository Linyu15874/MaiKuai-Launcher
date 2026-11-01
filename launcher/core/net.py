"""网络层：会话管理、镜像源、断点续传下载器。

支持多镜像源（官方 / BMCLAPI / MC啊…）+ 失败自动切换 + 多线程下载 + SHA1 校验。
"""

from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .paths import USER_AGENT


class NetworkError(Exception):
    pass


def make_session(pool_size: int = 64) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET", "POST", "HEAD"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = make_session()


# ---------------------------------------------------------------------------- 镜像源


@dataclass
class Source:
    """一个下载源的定义。mirror 里是「原始仓库根地址 -> 镜像根地址」的映射。"""

    key: str
    name: str
    version_manifest: str
    assets_base: str  # + "/{hash[:2]}/{hash}"
    asset_index_base: str  # + "/{index_id}.json"
    client_url_template: str = ""  # 老版本 mc 可能走这里
    maven_mirrors: dict[str, str] = field(default_factory=dict)
    api: str = "https://api.modrinth.com/v2"


SOURCES: dict[str, Source] = {
    "official": Source(
        key="official",
        name="官方源（Mojang）",
        version_manifest="https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
        assets_base="https://resources.download.minecraft.net",
        asset_index_base="https://piston-meta.mojang.com/v1/packages",  # 需要完整 url 时直接用 json 内的
    ),
    "bmclapi": Source(
        key="bmclapi",
        name="BMCLAPI（国内镜像）",
        version_manifest="https://bmclapi2.bangbang93.com/mc/game/version_manifest.json",
        assets_base="https://bmclapi2.bangbang93.com/assets",
        asset_index_base="https://bmclapi2.bangbang93.com/assets/indexes",
        maven_mirrors={
            "https://libraries.minecraft.net/": "https://bmclapi2.bangbang93.com/libraries/",
            "https://maven.fabricmc.net/": "https://bmclapi2.bangbang93.com/maven/",
            "https://maven.minecraftforge.net/": "https://bmclapi2.bangbang93.com/maven/",
            "https://maven.neoforged.net/releases/": "https://bmclapi2.bangbang93.com/maven/",
            "https://maven.quiltmc.org/repository/release/": "https://bmclapi2.bangbang93.com/maven/",
        },
    ),
}

CUSTOM_SOURCE_KEY = "custom"


class SourceManager:
    """根据配置选择源，并对 URL 做镜像替换。"""

    def __init__(self, key: str = "official", custom: dict | None = None):
        if key == CUSTOM_SOURCE_KEY and custom:
            self.source = Source(
                key="custom", name=custom.get("name", "自定义源"),
                version_manifest=custom.get("version_manifest", SOURCES["official"].version_manifest),
                assets_base=custom.get("assets_base", SOURCES["official"].assets_base),
                asset_index_base=custom.get("asset_index_base", SOURCES["official"].asset_index_base),
                maven_mirrors=custom.get("maven_mirrors", {}),
                api=custom.get("api", "https://api.modrinth.com/v2"),
            )
        else:
            self.source = SOURCES.get(key, SOURCES["official"])

    def mirror_url(self, url: str) -> str:
        """把已知仓库地址换成镜像地址。"""
        for origin, mirror in self.source.maven_mirrors.items():
            if url.startswith(origin):
                return mirror + url[len(origin):]
        return url

    def asset_url(self, sha1: str) -> str:
        return f"{self.source.assets_base}/{sha1[:2]}/{sha1}"

    def asset_index_url(self, index_id: str, original: str = "") -> str:
        base = self.source.asset_index_base
        if self.source.key == "official":
            return original or ""
        return f"{base}/{index_id}.json"


# ---------------------------------------------------------------------------- 下载


@dataclass
class DownloadTask:
    url: str
    dest: Path
    sha1: str | None = None
    size: int | None = None
    key: str = ""          # 便于进度显示的名字
    mirrors: list[str] = field(default_factory=list)  # 备用地址

    def __post_init__(self):
        if not self.key:
            self.key = self.dest.name

    def urls(self) -> list[str]:
        return [self.url, *self.mirrors]


class Downloader:
    """多线程下载器。

    progress(task, done_files, total_files, downloaded_bytes, total_bytes)
    每个文件完成后触发 file_done(task)；失败触发 file_failed(task, exc)。
    """

    def __init__(self, threads: int = 32, source: SourceManager | None = None):
        self.threads = max(1, threads)
        self.source = source or SourceManager()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    # 单个文件 ---------------------------------------------------------------
    def fetch(self, task: DownloadTask, progress_cb: Callable[[int, int], None] | None = None) -> Path:
        if task.dest.exists() and self._check(task.dest, task.sha1, task.size):
            if progress_cb:
                total = task.size or task.dest.stat().st_size
                progress_cb(total, total)
            return task.dest
        last_err: Exception | None = None
        for url in task.urls():
            if self._cancel:
                raise NetworkError("已取消")
            try:
                self._http_get(url, task.dest, task.size, progress_cb)
                if self._check(task.dest, task.sha1, task.size):
                    return task.dest
                # 校验失败：删掉重试下一个源
                task.dest.unlink(missing_ok=True)
                last_err = NetworkError(f"文件校验失败：{task.key}")
            except Exception as e:
                last_err = e
                task.dest.unlink(missing_ok=True)
        raise NetworkError(f"下载失败 {task.key}：{last_err}")

    def _http_get(self, url: str, dest: Path, expect_size: int | None, progress_cb):
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        headers = {}
        pos = 0
        if tmp.exists():
            pos = tmp.stat().st_size
            if expect_size and pos < expect_size:
                headers["Range"] = f"bytes={pos}-"
            elif expect_size and pos >= expect_size:
                tmp.unlink(missing_ok=True)
                pos = 0
        r = SESSION.get(url, headers=headers, stream=True, timeout=(15, 60))
        if r.status_code == 404:
            raise NetworkError(f"404 {url}")
        r.raise_for_status()
        mode = "ab" if pos else "wb"
        got = pos
        with open(tmp, mode) as f:
            for chunk in r.iter_content(1 << 18):
                if self._cancel:
                    r.close()
                    raise NetworkError("已取消")
                f.write(chunk)
                got += len(chunk)
                if progress_cb:
                    progress_cb(got, expect_size or r.headers.get("Content-Length") and got or got)
        if expect_size and got < expect_size:  # 没下完，续传再来一轮
            self._http_get(url, tmp if False else dest if False else tmp, expect_size, None)
        tmp.replace(dest)

    @staticmethod
    def _check(path: Path, sha1: str | None, size: int | None) -> bool:
        if not path.exists():
            return False
        if size is not None and path.stat().st_size != size:
            return False
        if sha1:
            h = hashlib.sha1()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest().lower() != sha1.lower():
                return False
        return True

    # 批量 -------------------------------------------------------------------
    def download_all(
        self,
        tasks: Sequence[DownloadTask],
        on_start: Callable[[int], None] | None = None,
        on_progress: Callable[[str, int, int, int, int], None] | None = None,
        on_done_file: Callable[[DownloadTask], None] | None = None,
        on_error: Callable[[DownloadTask, Exception], None] | None = None,
    ) -> tuple[int, int]:
        total = len(tasks)
        done = 0
        failed = 0
        total_bytes = sum(t.size or 0 for t in tasks)
        got_bytes = 0
        lock_time = time.time()
        if on_start:
            on_start(total)
        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {}

            def worker(task: DownloadTask):
                return self.fetch(task)

            for t in tasks:
                futures[pool.submit(worker, t)] = t
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    fut.result()
                    done += 1
                    if on_done_file:
                        on_done_file(t)
                except Exception as e:
                    failed += 1
                    if on_error:
                        on_error(t, e)
                got_bytes += t.size or 0
                if on_progress and (time.time() - lock_time > 0.05 or done + failed == total):
                    lock_time = time.time()
                    on_progress(t.key, done + failed, total, min(got_bytes, total_bytes or got_bytes),
                                total_bytes or got_bytes)
        return done, failed


# ---------------------------------------------------------------------------- JSON / 文本


def get_json(url: str, timeout: int = 20, retries: int = 2, **kw) -> dict | list:
    err = None
    for i in range(retries + 1):
        try:
            r = SESSION.get(url, timeout=timeout, **kw)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            err = e
            time.sleep(0.4 * (i + 1))
    raise NetworkError(f"请求失败 {url}：{err}")


def get_bytes(url: str, timeout: int = 30) -> bytes:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def sha1_of(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def check_internet(timeout: int = 6) -> bool:
    for url in ("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
                "https://bmclapi2.bangbang93.com/mc/game/version_manifest.json"):
        try:
            SESSION.head(url, timeout=timeout)
            return True
        except Exception:
            continue
    return False


def human_size(n: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}" if i else f"{int(n)} B"
