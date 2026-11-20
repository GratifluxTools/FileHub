"""拡張子とカテゴリの対応表。プレビュー・編集・圧縮ができる拡張子の一覧もここで管理する。

ここに無い拡張子も普通に登録できる（カテゴリは「other」になる）。
"""
import os

CATEGORY_EXTS = {
    "document": ["txt", "md", "doc", "docx", "pdf", "rtf", "odt"],
    "data": ["xls", "xlsx", "ods", "csv", "tsv", "json", "xml", "yaml", "yml"],
    "presentation": ["ppt", "pptx", "key", "odp"],
    "image": ["jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "heic", "psd", "ai"],
    "audio": ["mp3", "wav", "aac", "m4a", "flac", "ogg"],
    "video": ["mp4", "mov", "avi", "mkv", "webm", "wmv"],
    "archive": ["zip", "rar", "7z", "tar", "gz", "tgz", "tar.gz"],
    "program": ["exe", "msi", "app", "dmg", "apk", "ipa"],
    "code": ["html", "htm", "css", "js", "ts", "php", "py", "java", "c", "cpp", "h", "hpp",
             "cs", "go", "rs", "rb", "sh", "ps1", "bat", "sql"],
    "disk_image": ["iso", "bin", "cue"],
    "config": ["log", "ini", "cfg"],
}

EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORY_EXTS.items() for ext in exts}
CATEGORY_ORDER = list(CATEGORY_EXTS) + ["other"]

# 画面内で文字として読み書きできる拡張子
TEXT_EDITABLE = {
    "txt", "md", "csv", "tsv", "json", "xml", "yaml", "yml", "log", "ini", "cfg",
    "html", "htm", "css", "js", "ts", "py", "php", "java", "c", "cpp", "h", "hpp", "cs",
    "go", "rs", "rb", "sh", "ps1", "bat", "sql", "svg",
}
# 画像としてプレビューできる拡張子（HEIC は pillow-heif が入っている場合のみ）
IMAGE_PREVIEW = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic"}
# 画面内で簡単な加工（回転・反転・白黒・縮小）ができる拡張子
IMAGE_EDITABLE = {"jpg", "jpeg", "png", "bmp", "gif", "webp"}
# 文章を取り出してプレビューできる拡張子（Office・PDF・RTF）
OFFICE_TEXT = {"docx", "odt", "pptx", "odp", "xlsx", "ods", "pdf", "rtf"}
# 中身を一覧表示・展開できる圧縮形式
ARCHIVE_READ = {"zip", "tar", "tgz", "tar.gz", "gz", "7z", "rar"}
MEDIA_CATEGORIES = {"audio", "video"}
# 音声ファイルのタグ（ID3 など）を書き換えられる拡張子
MEDIA_TAG_EXTS = {"mp3", "flac", "m4a", "ogg"}


def get_ext(name: str) -> str:
    """ファイル名から拡張子（小文字・点なし）を取り出す。.tar.gz は一つの拡張子として扱う。"""
    low = name.lower()
    if low.endswith(".tar.gz"):
        return "tar.gz"
    return os.path.splitext(low)[1][1:]


def category_of(ext: str) -> str:
    return EXT_TO_CATEGORY.get(ext, "other")
