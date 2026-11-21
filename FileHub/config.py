import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields

from edition import EDITION

# スキャン時に無視するフォルダ名（大文字小文字は区別しない）
DEFAULT_EXCLUDE = ["node_modules", ".git", "__pycache__", ".venv", "venv", ".cache", ".Trash"]


def app_root() -> str:
    """アプリ本体があるフォルダ。ポータブル版はここに data/ を作る。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir() -> str:
    if EDITION == "portable":
        base = os.environ.get("FILEHUB_DATA_DIR") or os.path.join(app_root(), "data")
    else:
        base = os.environ.get("FLET_APP_STORAGE_DATA")
        if not base:
            if sys.platform == "win32":
                base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FileHub")
            else:
                base = os.path.join(os.path.expanduser("~"), ".file_hub")
    os.makedirs(base, exist_ok=True)
    return base


@dataclass
class Config:
    language: str = "en"
    preview_mb: int = 100
    exclude_names: list = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    include_hidden: bool = False
    exclude_appdata: bool = True
    use_trash: bool = True
    initial_scan_done: bool = False

    @classmethod
    def load(cls, path: str) -> "Config":
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, ensure_ascii=False, indent=2)
