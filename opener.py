"""OS の既定アプリでファイルを開く・フォルダを開く。"""
import os
import subprocess
import sys


def open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - ユーザーが選んだファイルを既定アプリで開く
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal(path: str) -> None:
    """ファイルの場所（フォルダ）を開く。Windows ではファイルを選択した状態で開く。"""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        open_path(os.path.dirname(path))
