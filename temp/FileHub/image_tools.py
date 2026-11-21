"""画像のプレビューと簡単な加工（回転・反転・白黒・縮小）。Pillow を使う。

HEIC は pillow-heif が入っている場合のみ表示できる（無ければ例外になる）。
"""
import hashlib
import os

from PIL import Image, ImageOps

_heif_ready = False
SAVE_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "gif": "GIF", "bmp": "BMP", "webp": "WEBP"}


def _ensure_heif():
    global _heif_ready
    if not _heif_ready:
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except Exception:
            pass
        _heif_ready = True


def preview_path(path, cache_dir):
    """表示に使うファイルのパスを返す。HEIC は PNG に変換してキャッシュする。"""
    if not path.lower().endswith(".heic"):
        return path
    _ensure_heif()
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.md5(f"{path}|{os.path.getmtime(path)}".encode("utf-8")).hexdigest()
    out = os.path.join(cache_dir, key + ".png")
    if not os.path.exists(out):
        with Image.open(path) as im:
            im.convert("RGBA").save(out, "PNG")
    return out


def apply_op(src, dst, op, max_side=None):
    """画像を加工して dst に保存する。保存形式は dst の拡張子で決まる。"""
    ext = dst.lower().rsplit(".", 1)[-1]
    fmt = SAVE_FORMATS.get(ext)
    if fmt is None:
        raise ValueError(f"cannot save as .{ext}")
    with Image.open(src) as im:
        im.load()
        if op == "rot_cw":
            out = im.rotate(-90, expand=True)
        elif op == "rot_ccw":
            out = im.rotate(90, expand=True)
        elif op == "rot_180":
            out = im.rotate(180, expand=True)
        elif op == "flip_h":
            out = ImageOps.mirror(im)
        elif op == "flip_v":
            out = ImageOps.flip(im)
        elif op == "gray":
            out = ImageOps.grayscale(im)
        elif op == "resize":
            if not max_side:
                raise ValueError("max_side is required for resize")
            out = im.copy()
            out.thumbnail((max_side, max_side))
        else:
            raise ValueError(f"unknown operation: {op}")
        if fmt == "JPEG" and out.mode not in ("RGB", "L"):
            out = out.convert("RGB")
        if fmt == "JPEG":
            out.save(dst, fmt, quality=92)
        else:
            out.save(dst, fmt)
