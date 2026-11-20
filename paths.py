"""パス操作の共通関数。比較は Windows の大文字小文字を区別しない形に正規化する。"""
import os


def join_path(root: str, relpath: str) -> str:
    """索引内の相対パス（/区切り）を、そのPCで使える実際のパスに変換する。"""
    if not relpath:
        return root
    return os.path.join(root, *relpath.split("/"))


def norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_within(path: str, parent: str) -> bool:
    """path が parent と同じか、その配下にあるかを判定する。"""
    p = norm(path)
    q = norm(parent).rstrip(os.sep)
    return p == q or p.startswith(q + os.sep)


def home_dir() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def is_inside_home(path: str) -> bool:
    """自分のアカウント（ホームフォルダ）の内側にあるか。リンクは実体の場所で判定する。"""
    return is_within(os.path.realpath(path), home_dir())
