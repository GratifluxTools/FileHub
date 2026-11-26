"""FileHub 自身のファイル（プログラム・索引・設定・書き出しデータ）を見分ける。

フォルダ名が変わっていても見分けられるように、名前ではなく中身で判定する。
- プログラム一式のフォルダ   : 実行ファイル＋Flutter/アプリ本体の組み合わせ
- データのフォルダ           : 目印ファイル、または設定と索引の両方がある
- ソースのフォルダ           : FileHub のソースの組み合わせ
- 書き出しファイル（.json）  : 中身が FileHub の書き出し形式
- 配布用の zip               : 中身に FileHub のプログラムが入っている
名前だけで除外するのは、配布物の決まった名前（FileHub-single-windows-x64 など）だけ。
"""
import os
import re
import zipfile

DATA_MARKER = "filehub-data.marker"
EXE_NAMES = ("file_hub.exe", "file_hub")
SOURCE_FILES = ("main.py", "edition.py", "db.py", "scanner.py")
EXPORT_MARK = b'"filehub-export"'
ZIP_MARKERS = {"file_hub.exe", "edition.py", "scanner.py", "db.py"}
# 配布物のフォルダ名・zip 名（例：FileHub-single-windows-x64）
BUILD_NAME_RE = re.compile(r"^file[ _-]?hub[ _-](single|portable)[ _-](windows|linux|mac)[ _-](x64|arm64)$",
                           re.IGNORECASE)


def is_build_name(name: str) -> bool:
    base = name[:-4] if name.lower().endswith(".zip") else name
    return bool(BUILD_NAME_RE.match(base))


def _isfile(*parts) -> bool:
    return os.path.isfile(os.path.join(*parts))


def _isdir(*parts) -> bool:
    return os.path.isdir(os.path.join(*parts))


def is_install_dir(d: str) -> bool:
    """FileHub のプログラム一式のフォルダか（実行ファイル＋アプリ本体・Flutter の組み合わせ）。"""
    if not any(_isfile(d, e) for e in EXE_NAMES):
        return False
    return (_isdir(d, "data", "flutter_assets") or _isfile(d, "data", "app.so")
            or _isfile(d, "flutter_windows.dll") or _isfile(d, "lib", "libflutter_linux_gtk.so"))


def is_data_dir(d: str) -> bool:
    """FileHub の索引・設定のフォルダか（目印、または設定と索引の両方がある）。"""
    if _isfile(d, DATA_MARKER):
        return True
    return _isfile(d, "config.json") and _isfile(d, "index.db")


def is_source_dir(d: str) -> bool:
    return all(_isfile(d, f) for f in SOURCE_FILES)


def is_app_dir(d: str) -> bool:
    try:
        return is_install_dir(d) or is_data_dir(d) or is_source_dir(d)
    except OSError:
        return False


def is_app_file(path: str, name: str) -> bool:
    """ファイルの中身で FileHub のものかを判定する（名前は見ない）。"""
    low = name.lower()
    if low == DATA_MARKER:
        return True
    ext = low.rsplit(".", 1)[-1] if "." in low else ""
    try:
        if ext == "json":
            with open(path, "rb") as fh:
                return EXPORT_MARK in fh.read(4096)
        if ext == "zip":
            with zipfile.ZipFile(path) as z:
                names = z.namelist()[:5000]
            found = {n.split("/")[-1].lower() for n in names}
            return len(found & ZIP_MARKERS) >= 2
    except (OSError, zipfile.BadZipFile, ValueError):
        return False
    return False


# 名前だけで FileHub のものと分かるファイル（フォルダが消えた後の索引の残りも、これで外せる）
APP_ONLY_NAMES = {"file_hub.exe", DATA_MARKER, "flutter_windows.dll", "libflutter_linux_gtk.so"}


def is_app_relpath(relpath: str, name: str) -> bool:
    """パスの名前だけで FileHub のものと分かるもの（配布フォルダの中・配布 zip・FileHub 独自の名前のファイル）。"""
    segments = relpath.split("/")
    if any(BUILD_NAME_RE.match(s) for s in segments[:-1]):
        return True
    if name.lower() in APP_ONLY_NAMES:
        return True
    return name.lower().endswith(".zip") and is_build_name(name)


def _ancestor_is_app(root: str, relpath: str, cache: dict) -> bool:
    cur = root
    for seg in ["."] + relpath.split("/")[:-1]:
        if seg != ".":
            cur = os.path.join(cur, seg)
        if cur not in cache:
            cache[cur] = is_app_dir(cur)
        if cache[cur]:
            return True
    return False


def record_is_app(root, relpath: str, name: str, ext: str, cache: dict = None) -> bool:
    """索引の1件が FileHub 自身のものか。root が None（手入力の場所）なら、名前だけで判定する。"""
    cache = {} if cache is None else cache
    if is_app_relpath(relpath, name):
        return True
    if root is None:
        return False
    if _ancestor_is_app(root, relpath, cache):
        return True
    if ext in ("json", "zip"):
        path = os.path.join(root, *relpath.split("/"))
        if os.path.isfile(path) and is_app_file(path, name):
            return True
    return False


def find_app_records(rows) -> list:
    """索引の行（id, root, mode, relpath, name, ext）から、FileHub 自身のものの id を集める。"""
    cache = {}
    ids = []
    for r in rows:
        root = r["root"] if r["mode"] == "scan" else None
        if record_is_app(root, r["relpath"], r["name"], r["ext"], cache):
            ids.append(r["id"])
    return ids


def write_data_marker(data_dir: str) -> None:
    """データのフォルダに目印を付ける（フォルダの名前や場所が変わっても見分けられるように）。"""
    path = os.path.join(data_dir, DATA_MARKER)
    if not os.path.exists(path):
        import json
        import uuid
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"app": "FileHub", "id": uuid.uuid4().hex}, fh)
