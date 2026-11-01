"""Modrinth 资源市场 API（Mod / 整合包 / 材质包 / 光影 / 数据包）。

API 文档：https://docs.modrinth.com/api-reference/
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .net import SESSION, Downloader, DownloadTask, NetworkError

DEFAULT_API = "https://api.modrinth.com/v2"

PROJECT_TYPES = {
    "mod": "模组",
    "resourcepack": "材质包",
    "shader": "光影",
    "datapack": "数据包",
    "plugin": "插件",
}

SORT_INDEX = {
    "综合": "relevance",
    "下载量": "downloads",
    "最近更新": "updated",
    "最新发布": "newest",
    "收藏数": "follows",
}


@dataclass
class ProjectHit:
    id: str
    slug: str
    title: str
    description: str
    author: str
    icon_url: str
    downloads: int
    follows: int
    project_type: str
    categories: list[str]
    date_modified: str

    summary = None

    def short_desc(self) -> str:
        d = (self.description or "").strip()
        return d if len(d) <= 120 else d[:117] + "…"


@dataclass
class ModFile:
    version_id: str
    name: str
    version_number: str
    url: str
    filename: str
    sha1: str
    sha512: str
    size: int
    primary: bool
    game_versions: list[str]
    loaders: list[str]
    dependencies: list[dict]

    @property
    def label(self) -> str:
        return f"{self.name} · {self.version_number}"


class ModrinthClient:
    def __init__(self, api_base: str = DEFAULT_API, timeout: int = 25):
        self.base = (api_base or DEFAULT_API).rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        r = SESSION.get(url, timeout=self.timeout)
        if r.status_code >= 400:
            raise NetworkError(f"Modrinth 请求失败 {r.status_code}：{r.text[:150]}")
        return r.json()

    # ------------------------------------------------------------------ 搜索
    def search(self, query: str, project_type: str = "mod", game_version: str = "",
               loaders: Iterable[str] = (), index: str = "relevance",
               limit: int = 20, offset: int = 0) -> tuple[list[ProjectHit], int]:
        facets: list[list[str]] = [[f"project_type:{project_type}"]]
        if game_version:
            facets.append([f"versions:{game_version}"])
        if loaders:
            facets.append([f"categories:{l}" for l in loaders])
        data = self._get("/search", {
            "query": query or "", "facets": json.dumps(facets, separators=(",", ":")),
            "index": index, "limit": limit, "offset": offset,
        })
        hits = []
        for h in data.get("hits", []):
            hits.append(ProjectHit(
                id=h.get("project_id") or h.get("slug"), slug=h.get("slug", ""),
                title=h.get("title", ""), description=h.get("description", ""),
                author=h.get("author", ""), icon_url=h.get("icon_url", ""),
                downloads=h.get("downloads", 0), follows=h.get("follows", 0),
                project_type=h.get("project_type", "mod"),
                categories=h.get("categories") or [], date_modified=h.get("date_modified", ""),
            ))
        return hits, data.get("total_hits", len(hits))

    def project(self, project_id: str) -> ProjectHit:
        d = self._get(f"/project/{project_id}")
        return ProjectHit(
            id=d.get("id") or project_id, slug=d.get("slug", ""), title=d.get("title", ""),
            description=d.get("description", ""), author=d.get("author", ""),
            icon_url=d.get("icon_url", ""), downloads=d.get("downloads", 0),
            follows=d.get("follows", 0), project_type=d.get("project_type", "mod"),
            categories=d.get("categories") or [], date_modified=d.get("date_modified", ""),
        )

    # ------------------------------------------------------------------ 版本
    def versions(self, project_id: str, loaders: Iterable[str] = (),
                 game_versions: Iterable[str] = ()) -> list[ModFile]:
        params: dict = {}
        if loaders:
            params["loaders"] = json.dumps(list(loaders), separators=(",", ":"))
        if game_versions:
            params["game_versions"] = json.dumps(list(game_versions), separators=(",", ":"))
        data = self._get(f"/project/{project_id}/version", params)
        out: list[ModFile] = []
        for v in data:
            files = v.get("files") or []
            primary = next((f for f in files if f.get("primary")), files[0] if files else None)
            if not primary:
                continue
            hashes = primary.get("hashes") or {}
            out.append(ModFile(
                version_id=v.get("id", ""), name=v.get("name", ""), version_number=v.get("version_number", ""),
                url=primary.get("url", ""), filename=primary.get("filename", ""),
                sha1=hashes.get("sha1", ""), sha512=hashes.get("sha512", ""),
                size=primary.get("size", 0), primary=True,
                game_versions=v.get("game_versions") or [], loaders=v.get("loaders") or [],
                dependencies=v.get("dependencies") or [],
            ))
        return out

    # ------------------------------------------------------------------ 下载
    def download(self, mod: ModFile, dest_dir: Path, threads: int = 8,
                 progress_cb=None) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / mod.filename
        mirrors = [f"https://bmclapi2.bangbang93.com/maven/modrinth/{Path(mod.url).name}"]
        dl = Downloader(threads=threads)
        dl.fetch(DownloadTask(url=mod.url, dest=dest, sha1=mod.sha1 or None,
                              size=mod.size or None, key=mod.filename, mirrors=mirrors))
        return dest

    def resolve_dependencies(self, mod: ModFile, game_version: str, loader: str, depth: int = 2
                             ) -> list[ModFile]:
        """拉取必需的依赖 Mod（ iterative，广度优先）。"""
        result: list[ModFile] = []
        seen: set[str] = {mod.version_id}
        queue = [(d, 0) for d in mod.dependencies if d.get("dependency_type") == "required"]
        while queue:
            dep, level = queue.pop(0)
            pid = dep.get("project_id")
            if not pid or level >= depth:
                continue
            try:
                versions = self.versions(pid, loaders=[loader], game_versions=[game_version])
            except Exception:
                continue
            if not versions:
                continue
            v = versions[0]
            if v.version_id in seen:
                continue
            seen.add(v.version_id)
            result.append(v)
            for d in v.dependencies:
                if d.get("dependency_type") == "required":
                    queue.append((d, level + 1))
        return result
