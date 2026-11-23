"""フォルダの走査と索引への登録。

- 対象はユーザー自身のホームフォルダ内だけ（他のアカウント・システム領域は対象外）。
- Windows のシステムファイル・隠しファイル、シンボリックリンクは含めない（隠しは設定で含められる）。
- 再スキャンは差分更新。見つからなくなったファイルは「欠落」として印を付ける（削除はしない）。
"""
import os
import stat
import sys
import time
from dataclasses import dataclass, field

from app_files import is_app_dir, is_app_file, is_app_relpath, is_build_name
from categories import category_of, get_ext
from paths import join_path, norm

WINDOWS = sys.platform == "win32"
ATTR_HIDDEN = 0x2
ATTR_SYSTEM = 0x4

# 常に除外するフォルダ（ホーム配下でも、システム由来のものは入れない）
ALWAYS_SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "program files",
    "program files (x86)", "programdata", "recovery", "perflogs", "lost+found",
}
SYSTEM_FILE_NAMES = {
    "thumbs.db", "desktop.ini", "ntuser.dat", "pagefile.sys", "hiberfil.sys", "swapfile.sys",
}
CLOUD_HINTS = ("google drive", "googledrive", "onedrive", "dropbox", "icloud drive", "mydrive")
DEFAULT_FOLDER_NAMES = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
BATCH_SIZE = 500


@dataclass
class ScanOptions:
    exclude_names: set = field(default_factory=set)
    include_hidden: bool = False
    exclude_appdata: bool = True
    skip_paths: list = field(default_factory=list)


def detect_kind(path: str) -> str:
    base = os.path.basename(os.path.normpath(path)).lower()
    return "cloud" if any(h in base for h in CLOUD_HINTS) else "local"


def detect_default_folders(home: str):
    """初回スキャンで候補に出す、ホーム直下のよく使うフォルダ。"""
    found = []
    for name in DEFAULT_FOLDER_NAMES:
        p = os.path.join(home, name)
        if os.path.isdir(p):
            found.append({"name": name, "path": p, "kind": "local"})
    try:
        entries = sorted(os.listdir(home))
    except OSError:
        entries = []
    for name in entries:
        p = os.path.join(home, name)
        if os.path.isdir(p) and any(h in name.lower() for h in CLOUD_HINTS):
            found.append({"name": name, "path": p, "kind": "cloud"})
    return found


def _is_hidden(name, st):
    if name.startswith("."):
        return True
    return WINDOWS and bool(getattr(st, "st_file_attributes", 0) & ATTR_HIDDEN)


def _is_system(st):
    return WINDOWS and bool(getattr(st, "st_file_attributes", 0) & ATTR_SYSTEM)


def _skip_dir(name, full, names_lower, opts, skip_norm):
    low = name.lower()
    if low in ALWAYS_SKIP_DIRS or low in names_lower:
        return True
    if opts.exclude_appdata and low == "appdata":
        return True
    return norm(full) in skip_norm


def refresh_stale(db, loc_id, before):
    """今回のスキャンで触れなかったファイルについて、実際に存在するかを確かめて欠落フラグを更新する。"""
    updates = []
    for row in db.stale_files(loc_id, before):
        flag = 0 if os.path.exists(join_path(row["root"], row["relpath"])) else 1
        if flag != row["missing"]:
            updates.append((flag, row["id"]))
    if updates:
        db.set_missing(updates)


def scan_location(db, loc, opts, cancel, on_progress=None, start=None):
    """場所 loc の中を走査して索引を更新する。

    start を指定すると、その配下だけを走査する（展開したフォルダの取り込みなど）。
    戻り値は登録したファイル数。キャンセルされた場合は None。
    """
    root = loc["root"]
    started = time.time()
    names_lower = {n.lower() for n in opts.exclude_names}
    skip_norm = {norm(p) for p in opts.skip_paths}
    stack = [start or root]
    batch = []
    count = 0
    while stack:
        if cancel.is_set():
            return None
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue
        with it:
            for entry in it:
                name = entry.name
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode) or _is_system(st):
                    continue
                if not opts.include_hidden and _is_hidden(name, st):
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if _skip_dir(name, entry.path, names_lower, opts, skip_norm):
                        continue
                    if is_build_name(name) or is_app_dir(entry.path):
                        continue  # FileHub 自身のフォルダ（名前が変わっていても中身で判定）
                    stack.append(entry.path)
                elif stat.S_ISREG(st.st_mode):
                    if name.lower() in SYSTEM_FILE_NAMES:
                        continue
                    ext = get_ext(name)
                    rel = os.path.relpath(entry.path, root).replace(os.sep, "/")
                    if is_app_relpath(rel, name) or (ext in ("zip", "json") and is_app_file(entry.path, name)):
                        continue  # 配布 zip・書き出しファイルなど、FileHub 自身のもの
                    batch.append((rel, name, ext, category_of(ext), st.st_size, st.st_mtime))
                    if len(batch) >= BATCH_SIZE:
                        db.upsert_files(loc["id"], batch, started)
                        count += len(batch)
                        batch = []
                        if on_progress:
                            on_progress(count, current)
    if batch:
        db.upsert_files(loc["id"], batch, started)
        count += len(batch)
    if start is None:
        refresh_stale(db, loc["id"], started)
    return count


def index_abs(db, abs_path):
    """1つのファイルを索引に登録（または更新）する。どの場所にも属さなければ None。"""
    found = db.find_location_for(abs_path)
    if not found:
        return None
    loc, rel = found
    st = os.stat(abs_path)
    name = os.path.basename(abs_path)
    ext = get_ext(name)
    db.upsert_files(loc["id"], [(rel, name, ext, category_of(ext), st.st_size, st.st_mtime)], time.time())
    return db.file_id(loc["id"], rel)


def relocate_record(db, fid, new_abs):
    """名前変更・移動後に索引を付け替える。新しい場所に属さなければ索引から外して None を返す。"""
    found = db.find_location_for(new_abs)
    if not found:
        db.delete_file(fid)
        return None
    loc, rel = found
    st = os.stat(new_abs)
    name = os.path.basename(new_abs)
    ext = get_ext(name)
    db.update_file_record(fid, loc["id"], rel, name, ext, category_of(ext), st.st_size, st.st_mtime)
    return fid


def list_child_dirs(path, opts):
    """path 直下のフォルダ（除外ルールを適用済み・名前順）。ツリー表示用。"""
    names_lower = {n.lower() for n in opts.exclude_names}
    skip_norm = {norm(p) for p in opts.skip_paths}
    out = []
    try:
        it = os.scandir(path)
    except OSError:
        return out
    with it:
        for entry in it:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or _is_system(st):
                continue
            if not opts.include_hidden and _is_hidden(entry.name, st):
                continue
            if _skip_dir(entry.name, entry.path, names_lower, opts, skip_norm):
                continue
            if is_build_name(entry.name) or is_app_dir(entry.path):
                continue
            out.append(entry.path)
    return sorted(out, key=lambda p: os.path.basename(p).lower())


def parse_manual_lines(text):
    """手入力のファイル一覧（1行に1つ、相対パス）を索引の行に変換する。フォルダ（末尾が / ）と重複は除く。"""
    from categories import category_of as _cat
    out, seen = [], set()
    for line in (text or "").splitlines():
        rel = line.strip().replace("\\", "/").lstrip("/")
        if not rel or rel.endswith("/") or rel in seen:
            continue
        seen.add(rel)
        name = rel.rsplit("/", 1)[-1]
        ext = get_ext(name)
        out.append((rel, name, ext, _cat(ext), 0, 0.0))
    return out
