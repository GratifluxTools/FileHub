"""このPCから直接見えるフォルダの根（外付けSSD・USBメモリ・追加ドライブ）。

- ホームフォルダは常に対象。
- 外付けなどは、システムのドライブ（Windows の C: など）を除いて見つけたものを対象にする。
- 見つからない・接続されていないものは一覧に出ない。
"""
import os
import platform
import string

from paths import is_inside_home, is_within


def system_drive() -> str:
    return (os.environ.get("SystemDrive") or "C:").upper()


def _children(base):
    try:
        return [os.path.join(base, n) for n in sorted(os.listdir(base))]
    except OSError:
        return []


def external_roots():
    """ホーム以外で、このPCから見えるフォルダの根の一覧。"""
    system = platform.system()
    roots = []
    if system == "Windows":
        sys_drive = system_drive()
        for letter in string.ascii_uppercase:
            drive = f"{letter}:"
            if drive == sys_drive:
                continue
            root = drive + "\\"
            if os.path.isdir(root):
                roots.append(root)
    elif system == "Darwin":
        roots = [p for p in _children("/Volumes") if os.path.isdir(p)]
    else:
        user = os.environ.get("USER") or ""
        for base in (os.path.join("/media", user), os.path.join("/run/media", user), "/mnt"):
            roots += [p for p in _children(base) if os.path.isdir(p)]
    return roots


def is_allowed_root(path: str) -> bool:
    """登録してよいフォルダか。ホームの中、または外付けなどの根の中。"""
    if is_inside_home(path):
        return True
    real = os.path.realpath(path)
    return any(is_within(real, root) for root in external_roots())


def scan_roots():
    """登録画面のツリーの一番上に出す根（ホーム → 外付けの順）。"""
    from paths import home_dir
    return [home_dir()] + external_roots()


def device_for_path(db, path, here_id, device_type="external"):
    """フォルダが属するデバイスを決める。ホームの中はこのPC、外付けドライブは別の「外付けドライブ」デバイス。"""
    if is_inside_home(path):
        return here_id
    root = next((r for r in external_roots() if is_within(path, r)), None) or path
    label = os.path.basename(os.path.normpath(root)) or root
    label = label.rstrip("\\/") or root
    dev = db.find_device(label, device_type)
    return dev["id"] if dev else db.add_device(label, device_type, "")
