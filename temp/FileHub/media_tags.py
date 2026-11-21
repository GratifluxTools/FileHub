"""音声・動画の情報と、ファイル自体のタグ（ID3・MP4 のメタデータ）の読み書き。

- MP4 / MOV / M4A / M4V : MP4 のタグ（タイトル・アルバム・トラック・年・シリーズ・シーズン・話数）を書き換える。
- MP3 / FLAC / OGG      : 共通タグ（タイトル・アーティスト・アルバム・トラック・年）を書き換える。
                          シリーズ・シーズン・話数はこの形式に無いので、索引だけに保存する。
- そのほかの動画（mkv・avi・webm・wmv）: タグは書けないので、索引だけに保存する。
"""
from mutagen import File as MutagenFile
from mutagen.mp4 import MP4

# 画面に出す項目（DB の media に保存するキー）
MEDIA_FIELDS = ["title", "artist", "album", "track", "year", "series", "season", "episode"]

MP4_EXTS = {"mp4", "mov", "m4a", "m4v"}
EASY_EXTS = {"mp3", "flac", "ogg"}
WRITABLE_EXTS = MP4_EXTS | EASY_EXTS

# MP4 のタグ名
MP4_KEYS = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "year": "\xa9day",
            "series": "tvsh", "season": "tvsn", "episode": "tves", "track": "trkn"}
# 共通（easy）のタグ名
EASY_KEYS = {"title": "title", "artist": "artist", "album": "album", "track": "tracknumber", "year": "date"}
# 形式によって書けない項目
EASY_UNSUPPORTED = ["series", "season", "episode"]


def _ext(path: str) -> str:
    return path.lower().rsplit(".", 1)[-1] if "." in path else ""


def read_tags(path):
    """ファイルに入っているタグを読む。読めなければ空の辞書。"""
    ext = _ext(path)
    try:
        if ext in MP4_EXTS:
            return _read_mp4(path)
        if ext in EASY_EXTS:
            return _read_easy(path)
    except Exception:
        return {}
    return {}


def _read_mp4(path):
    tags = MP4(path).tags or {}
    out = {}
    for name, key in MP4_KEYS.items():
        values = tags.get(key)
        if not values:
            continue
        v = values[0]
        if name == "track":
            out[name] = str(v[0] if isinstance(v, tuple) else v)
        else:
            out[name] = str(v)
    return out


def _read_easy(path):
    audio = MutagenFile(path, easy=True)
    if audio is None or not audio.tags:
        return {}
    out = {}
    for name, key in EASY_KEYS.items():
        values = audio.tags.get(key)
        if values:
            value = str(values[0])
            if name == "track":
                value = value.split("/")[0]
            out[name] = value
    return out


def write_tags(path, media):
    """タグを書き込む。空欄の項目はタグから消す。書けなかった項目の一覧を返す。

    数字で書く項目（トラック・シーズン・話数）に数字以外が入っていれば ValueError。
    書けない形式なら ValueError。
    """
    ext = _ext(path)
    if ext in MP4_EXTS:
        _write_mp4(path, media)
        return []
    if ext in EASY_EXTS:
        _write_easy(path, media)
        return list(EASY_UNSUPPORTED)
    raise ValueError("this file format does not support tags")


def _int_value(name, value):
    if not value.isdigit():
        raise ValueError(f"{name} must be a number")
    return int(value)


def _write_mp4(path, media):
    f = MP4(path)
    if f.tags is None:
        f.add_tags()
    for name, key in MP4_KEYS.items():
        value = str(media.get(name, "") or "").strip()
        if not value:
            if key in f.tags:
                del f.tags[key]
            continue
        if name == "track":
            f.tags[key] = [(_int_value(name, value), 0)]
        elif name in ("season", "episode"):
            f.tags[key] = [_int_value(name, value)]
        else:
            f.tags[key] = [value]
    f.save()


def _write_easy(path, media):
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise ValueError("this file does not support tags")
    if audio.tags is None:
        audio.add_tags()
    for name, key in EASY_KEYS.items():
        value = str(media.get(name, "") or "").strip()
        if value:
            audio.tags[key] = [value]
        elif key in audio.tags:
            del audio.tags[key]
    audio.save(path)
