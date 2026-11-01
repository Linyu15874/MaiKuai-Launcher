"""配置持久化：~/.config 或 %APPDATA% 下的 config.json。"""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import ensure_dirs

DEFAULTS: dict[str, Any] = {
    "source": "official",
    "download_threads": 32,
    "language": "zh_CN",
    "theme": "auto",              # auto / light / dark
    "game_root": "",              # 留空 = 数据目录
    "version_isolation": True,
    "memory": {"min": 512, "max": 0, "auto": True},   # max=0 -> 自动推荐
    "resolution": {"fullscreen": False, "width": 854, "height": 480},
    "java": {"auto": True, "path": "", "min_java": 0},
    "jvm_args": "",
    "game_args": "",
    "server": {"address": "", "hide": False},
    "launch": {
        "close_launcher_when_launch": False,
        "hide_launcher_when_launch": True,
        "show_console": True,
        "auto_update": True,
    },
    "auth": {
        "https_verify": True,
        "ms_client_id": "000000004C1D1682",
        "yggdrasil_default": "https://littleskin.cn/api/yggdrasil",
    },
    "modrinth": {"api": "https://api.modrinth.com/v2", "show_unsupported": False},
    "instances": [],
    "selected_instance": "",
    "ui": {"last_page": "home", "window_geometry": ""},
    "first_run": True,
}


class Config:
    def __init__(self, path: Path | None = None):
        self._dirs = ensure_dirs()
        self.path = Path(path or self._dirs["config"] / "config.json")
        self._data: dict[str, Any] = deepcopy(DEFAULTS)
        self._lock = threading.Lock()
        self.load()

    # ------------------------------------------------------------------ 基础读写
    def load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                self._data = self._merge(deepcopy(DEFAULTS), data)
            except Exception:
                self._data = deepcopy(DEFAULTS)
        self.save()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)

    @staticmethod
    def _merge(base: dict, new: dict) -> dict:
        for k, v in new.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = Config._merge(base[k], v)
            else:
                base[k] = v
        return base

    def get(self, key: str, default: Any = None) -> Any:
        """支持 a.b.c 形式取值。"""
        cur: Any = self._data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key: str, value: Any, autosave: bool = True) -> None:
        parts = key.split(".")
        cur = self._data
        for p in parts[:-1]:
            if not isinstance(cur.get(p), dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = value
        if autosave:
            self.save()

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    # ------------------------------------------------------------------ 实例
    def instances(self) -> list[dict]:
        return self._data.get("instances", [])

    def save_instances(self, instances: list[dict]) -> None:
        self.set("instances", instances)

    def selected_instance(self) -> dict | None:
        sid = self._data.get("selected_instance")
        for ins in self.instances():
            if ins.get("id") == sid:
                return ins
        return None

    def select_instance(self, instance_id: str) -> None:
        self.set("selected_instance", instance_id)

    # ------------------------------------------------------------------ 目录
    @property
    def root(self) -> Path:
        return Path(self._dirs["root"])

    def ensure_sub(self, name: str) -> Path:
        d = self._dirs.get(name) or (self.root / name)
        d.mkdir(parents=True, exist_ok=True)
        return d
