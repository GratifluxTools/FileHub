"""デバイス（親）の識別。

「現在のPC」かどうかは、ホスト名・OS・ユーザー名から作る指紋で判定する。
Google Drive などのクラウドは PC に紐づかないので、指紋を持たない。
"""
import hashlib
import os
import platform
import socket

LOCAL_TYPES = ["windows", "linux", "mac"]
CLOUD_TYPES = ["gdrive", "onedrive", "dropbox"]
DEVICE_TYPES = LOCAL_TYPES + CLOUD_TYPES + ["other"]
# 外付けSSD・USBなどは、登録時に自動で作る（手動では選ばせない）
EXTERNAL_TYPE = "external"


def _user() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def current_fingerprint() -> str:
    raw = "|".join([socket.gethostname(), platform.system(), _user()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def current_type() -> str:
    return {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")


def current_name() -> str:
    return socket.gethostname() or "PC"
