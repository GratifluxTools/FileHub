"""GitHub Releases の最新版を確認する。ダウンロードはブラウザで行う（実行ファイルの自己更新はしない）。"""
import json
import re
import urllib.error
import urllib.request

from app_version import __version__

# リポジトリを移したらここを変更する
REPO = "GratifluxTools/FileHub"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REPO_URL = f"https://github.com/{REPO}"


def parse_version(v: str) -> tuple:
    nums = [int(n) for n in re.findall(r"\d+", v or "")][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def check_latest(timeout: int = 10):
    """最新リリース情報を返す。取得できなければ None。"""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "FileHub",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    tag = data.get("tag_name", "")
    return {
        "version": tag.lstrip("vV"),
        "url": data.get("html_url", ""),
        "newer": parse_version(tag) > parse_version(__version__),
    }
