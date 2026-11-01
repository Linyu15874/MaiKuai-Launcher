"""游戏实例（即用「整合包/版本盒子」）管理。

每个实例拥有独立的 saves / mods / config 等目录，游戏核心文件（版本、库、资源）
共享同一份，和 PCL2 的「版本隔离」思路一致。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .installer import detect_loader


@dataclass
class Instance:
    id: str
    name: str
    version_id: str
    game_dir: Path
    loader: str = "vanilla"
    base_version: str = ""
    java_path: str = ""
    min_memory: int = 0
    max_memory: int = 0
    width: int = 0
    height: int = 0
    fullscreen: bool = False
    jvm_args: str = ""
    game_args: str = ""
    server: str = ""
    icon: str = ""
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    last_played: float = 0.0
    play_seconds: int = 0

    def dict(self) -> dict:
        d = self.__dict__.copy()
        d["game_dir"] = str(self.game_dir)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Instance":
        d = dict(d)
        d["game_dir"] = Path(d.get("game_dir") or "")
        known = set(cls.__annotations__.keys())
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def mods_dir(self) -> Path:
        return self.game_dir / "mods"

    @property
    def saves_dir(self) -> Path:
        return self.game_dir / "saves"


class InstanceManager:
    def __init__(self, config, root: Path):
        self.config = config
        self.root = Path(root)
        self.instances_dir = self.root / "instances"
        self.instances_dir.mkdir(parents=True, exist_ok=True)
        self._list: list[Instance] = [Instance.from_dict(d) for d in config.instances()]

    # ------------------------------------------------------------------ CRUD
    def all(self) -> list[Instance]:
        order = {"fabric": 1, "forge": 1, "neoforge": 1, "quilt": 1, "vanilla": 0}
        return sorted(self._list, key=lambda i: (order.get(i.loader, 0), i.last_played, i.created_at), reverse=True)

    def get(self, instance_id: str) -> Instance | None:
        for i in self._list:
            if i.id == instance_id:
                return i
        return None

    def create(self, name: str, version_id: str, versions_dir: Path, isolation: bool = True) -> Instance:
        safe = paths.safe_name(name)
        base = self.instances_dir / safe
        n = 1
        while base.exists():
            n += 1
            base = self.instances_dir / f"{safe}-{n}"
        game_dir = base if isolation else Path(self.config.get("game_root") or paths.default_game_dir())
        ins = Instance(
            id=uuid.uuid4().hex[:16], name=name, version_id=version_id,
            game_dir=game_dir, loader=detect_loader(version_id, versions_dir),
        )
        self.ensure_dirs(ins)
        self._list.append(ins)
        self.save()
        return ins

    def add_from_existing(self, name: str, version_id: str, game_dir: Path, versions_dir: Path) -> Instance:
        ins = Instance(id=uuid.uuid4().hex[:16], name=name, version_id=version_id,
                       game_dir=Path(game_dir), loader=detect_loader(version_id, versions_dir))
        self._list.append(ins)
        self.save()
        return ins

    def update(self, ins: Instance) -> None:
        for i, a in enumerate(self._list):
            if a.id == ins.id:
                self._list[i] = ins
                break
        self.save()

    def remove(self, ins: Instance, delete_files: bool = False) -> None:
        self._list = [i for i in self._list if i.id != ins.id]
        if delete_files and self._is_child(ins.game_dir):
            import shutil
            shutil.rmtree(ins.game_dir, ignore_errors=True)
        self.save()

    def _is_child(self, p: Path) -> bool:
        try:
            return Path(p).resolve().is_relative_to(self.instances_dir.resolve())
        except Exception:
            return False

    def save(self) -> None:
        self.config.save_instances([i.dict() for i in self._list])

    # ------------------------------------------------------------------ 目录
    def ensure_dirs(self, ins: Instance) -> None:
        d = ins.game_dir
        d.mkdir(parents=True, exist_ok=True)
        for sub in ("mods", "saves", "config", "resourcepacks", "shaderpacks", "screenshots",
                    "logs", "crash-reports", "optionshud"):
            (d / sub).mkdir(parents=True, exist_ok=True)

    def rename(self, ins: Instance, new_name: str) -> None:
        old_dir = ins.game_dir
        ins.name = new_name
        if self._is_child(old_dir):
            new_dir = self.instances_dir / paths.safe_name(new_name)
            if not new_dir.exists():
                try:
                    old_dir.rename(new_dir)
                    ins.game_dir = new_dir
                except Exception:
                    pass
        self.update(ins)
