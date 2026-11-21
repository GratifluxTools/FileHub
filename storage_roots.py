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


def volume_label(root: str) -> str:
    """Windows のボリュームラベル（SSD などの名前）。取れなければ空。"""
    if platform.system() != "Windows":
        return ""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
        return buf.value if ok else ""
    except Exception:  # noqa: BLE001
        return ""


def display_name(root: str) -> str:
    """外付けドライブの表示名。ボリュームラベル → ドライブ文字 → フォルダ名の順。"""
    label = volume_label(root)
    if label:
        return label
    base = os.path.basename(os.path.normpath(root)).rstrip("\\/")
    return base or root.rstrip("\\/") or root


def volume_key(root: str) -> str:
    """ボリュームを見分ける指紋（つなぎ直しても同じになるよう、ドライブ文字ではなく名前で作る）。"""
    return "vol:" + display_name(root)


def connected_root(dev):
    """このデバイス（外付けドライブ）が今このPCに接続されていれば、その根のパス。なければ None。"""
    if not dev or dev["dtype"] != "external":
        return None
    for root in external_roots():
        if dev["fingerprint"]:
            if dev["fingerprint"] == volume_key(root):
                return root
        elif dev["name"] == display_name(root):
            return root
    return None


def device_for_path(db, path, here_id, device_type="external"):
    """フォルダが属するデバイス。ホームの中はこのPC、外付けドライブはそのボリュームのデバイス。"""
    if is_inside_home(path):
        return here_id
    root = next((r for r in external_roots() if is_within(path, r)), None) or path
    key, name = volume_key(root), display_name(root)
    dev = db.find_device_by_fingerprint(key)
    if dev:
        return dev["id"]
    dev = db.find_device(name, device_type)
    if dev:  # 以前の登録（指紋なし）には、今の指紋を付けておく
        if not dev["fingerprint"]:
            db.set_device_fingerprint(dev["id"], key)
        return dev["id"]
    return db.add_device(name, device_type, "", key)
