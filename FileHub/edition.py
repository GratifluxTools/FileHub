"""配布版の種類。
- "single"   : 1台のPCで使う版。データはユーザーのアプリデータフォルダに保存する。
- "portable" : USBメモリなどで持ち運ぶ版。データはアプリと同じフォルダの data/ に保存する。

このファイルは GitHub Actions（build.yml）がポータブル版のビルド時に書き換える。
"""

EDITION = "single"
