"""圧縮・展開。zip / tar / tar.gz / gz は標準ライブラリで扱う。
7z は py7zr、rar は rarfile（と unrar 本体）が必要。無い場合は分かりやすいエラーにする。
展開先の外へ書き出すパス（../ を含むものなど）は必ず拒否する。
"""
import gzip
import os
import shutil
import tarfile
import zipfile

from paths import norm


class ArchiveError(Exception):
    pass


def _require(module_name):
    try:
        return __import__(module_name)
    except ImportError as ex:
        raise ArchiveError(f"{module_name} is not installed") from ex


def _kind(path):
    low = path.lower()
    if low.endswith((".tar.gz", ".tgz", ".tar")):
        return "tar"
    if low.endswith(".zip"):
        return "zip"
    if low.endswith(".7z"):
        return "7z"
    if low.endswith(".rar"):
        return "rar"
    if low.endswith(".gz"):
        return "gz"
    raise ArchiveError("unsupported archive format")


def _safe_target(dest, name):
    target = os.path.normpath(os.path.join(dest, name))
    base = norm(dest).rstrip(os.sep)
    if not (norm(target) == base or norm(target).startswith(base + os.sep)):
        raise ArchiveError(f"unsafe path in archive: {name}")
    return target


def list_archive(path, limit=2000):
    kind = _kind(path)
    if kind == "zip":
        with zipfile.ZipFile(path) as z:
            return z.namelist()[:limit]
    if kind == "tar":
        with tarfile.open(path, "r:*") as tf:
            return [m.name for m in tf.getmembers()][:limit]
    if kind == "7z":
        py7zr = _require("py7zr")
        with py7zr.SevenZipFile(path, mode="r") as z:
            return z.getnames()[:limit]
    if kind == "rar":
        rarfile = _require("rarfile")
        with rarfile.RarFile(path) as rf:
            return rf.namelist()[:limit]
    return [os.path.basename(path)[:-3]]


def extract_archive(path, dest):
    """dest フォルダを作って展開する。戻り値は展開したファイル数。"""
    kind = _kind(path)
    os.makedirs(dest, exist_ok=True)
    count = 0
    if kind == "zip":
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                target = _safe_target(dest, info.filename)
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
    elif kind == "tar":
        with tarfile.open(path, "r:*") as tf:
            for m in tf.getmembers():
                if m.issym() or m.islnk():
                    continue  # リンクは展開しない（安全のため）
                target = _safe_target(dest, m.name)
                if m.isdir():
                    os.makedirs(target, exist_ok=True)
                    continue
                if not m.isfile():
                    continue
                src = tf.extractfile(m)
                if src is None:
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
    elif kind == "gz":
        target = _safe_target(dest, os.path.basename(path)[:-3])
        with gzip.open(path, "rb") as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        count = 1
    elif kind == "7z":
        py7zr = _require("py7zr")
        with py7zr.SevenZipFile(path, mode="r") as z:
            names = z.getnames()
            for n in names:
                _safe_target(dest, n)
            z.extractall(path=dest)
            count = len(names)
    elif kind == "rar":
        rarfile = _require("rarfile")
        with rarfile.RarFile(path) as rf:
            names = rf.namelist()
            for n in names:
                _safe_target(dest, n)
            rf.extractall(dest)
            count = len(names)
    return count


def create_zip(sources, dest):
    """sources: (実際のパス, zip内の名前) のリスト。"""
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for src, arcname in sources:
            z.write(src, arcname)


def create_targz(sources, dest):
    with tarfile.open(dest, "w:gz") as tf:
        for src, arcname in sources:
            tf.add(src, arcname=arcname)
