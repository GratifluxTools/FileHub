"""音声・動画の情報。

- 音声（mp3 / flac / m4a / ogg）は ID3 などのタグを mutagen で読み書きする。
- 動画や、タグを書けない形式は、索引側（アプリのデータ）だけに保存する。
"""
from mutagen import File as MutagenFile

# 画面に出す項目（DB の media に保存するキー）
MEDIA_FIELDS = ["title", "artist", "album", "track", "year", "series", "season", "episode"]

# タグとして書き込む項目 -> mutagen の easy タグのキー
EASY_KEYS = {"title": "title", "artist": "artist", "album": "album", "track": "tracknumber", "year": "date"}


def read_tags(path):
    """ファイルに入っているタグを読む。読めなければ空の辞書。"""
    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        return {}
    if audio is None or not audio.tags:
        return {}
    out = {}
    for field_name, key in EASY_KEYS.items():
        values = audio.tags.get(key)
        if values:
            value = str(values[0])
            if field_name == "track":
                value = value.split("/")[0]
            out[field_name] = value
    return out


def write_tags(path, media):
    """タグを書き込む。空欄の項目はタグから消す。書けない形式なら ValueError。"""
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise ValueError("this file does not support tags")
    if audio.tags is None:
        audio.add_tags()
    for field_name, key in EASY_KEYS.items():
        value = str(media.get(field_name, "") or "").strip()
        if value:
            audio.tags[key] = [value]
        elif key in audio.tags:
            del audio.tags[key]
    audio.save(path)
