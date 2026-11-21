"""索引データベース（SQLite）。実ファイルは移動・変更せず、デバイス・場所・タグ・リンク・メモなどを持つ。

- devices   : 親デバイス（このPC・他のPC・Google Drive など）
- locations : ファイルがある場所。mode が 'scan'（フォルダを走査）か 'manual'（手入力の一覧）
"""
import json
import os
import sqlite3
import threading
import time

from paths import is_within, join_path, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dtype TEXT NOT NULL DEFAULT 'other',
    account TEXT NOT NULL DEFAULT '',
    fingerprint TEXT UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'local',
    root TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    device_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'scan'
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    relpath TEXT NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    memo TEXT NOT NULL DEFAULT '',
    media TEXT NOT NULL DEFAULT '{}',
    scanned_at REAL NOT NULL DEFAULT 0,
    UNIQUE (location_id, relpath)
);
CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (file_id, tag_id)
);
CREATE TABLE IF NOT EXISTS links (
    file_a INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    file_b INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    PRIMARY KEY (file_a, file_b),
    CHECK (file_a < file_b)
);
"""

SORTS = {
    "name": "f.name COLLATE NOCASE",
    "mtime": "f.mtime DESC",
    "size": "f.size DESC",
    "path": "l.name COLLATE NOCASE, f.relpath COLLATE NOCASE",
}

LOC_SELECT = """
    SELECT l.*, d.name AS device_name, d.dtype AS device_dtype,
           d.account AS device_account, d.fingerprint AS device_fp,
           (SELECT COUNT(*) FROM files f WHERE f.location_id = l.id) AS total,
           (SELECT COUNT(*) FROM files f WHERE f.location_id = l.id AND f.missing = 1) AS missing
    FROM locations l LEFT JOIN devices d ON d.id = l.device_id
"""


def escape_like(text: str) -> str:
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")


class Database:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self):
        """0.1.x の索引（devices などが無い）を新しい形に合わせる。"""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(locations)").fetchall()}
        if "device_id" not in cols:
            self._conn.execute("ALTER TABLE locations ADD COLUMN device_id INTEGER")
        if "mode" not in cols:
            self._conn.execute("ALTER TABLE locations ADD COLUMN mode TEXT NOT NULL DEFAULT 'scan'")

    # ---- 低レベル ----
    def _rows(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    def _run(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur.lastrowid

    def _many(self, sql, seq):
        with self._lock:
            self._conn.executemany(sql, seq)
            self._conn.commit()

    # ---- デバイス ----
    def devices(self):
        return self._rows("""
            SELECT d.*, (SELECT COUNT(*) FROM locations l WHERE l.device_id = d.id) AS locs
            FROM devices d ORDER BY d.id""")

    def device(self, did):
        return self._one("SELECT * FROM devices WHERE id = ?", (did,))

    def add_device(self, name, dtype, account="", fingerprint=None):
        return self._run(
            "INSERT INTO devices(name, dtype, account, fingerprint, created_at) VALUES (?,?,?,?,?)",
            (name, dtype, account, fingerprint, time.time()))

    def update_device(self, did, name, account):
        self._run("UPDATE devices SET name = ?, account = ? WHERE id = ?", (name, account, did))

    def delete_device(self, did):
        """デバイスと、その下の場所（索引の情報）を消す。ディスク上のファイルは消さない。"""
        with self._lock:
            self._conn.execute("DELETE FROM locations WHERE device_id = ?", (did,))
            self._conn.execute("DELETE FROM devices WHERE id = ?", (did,))
            self._conn.commit()

    def ensure_current_device(self, name, dtype, fingerprint):
        """このPCのデバイスを用意する。紐付けの無い場所は、このPCのものとして扱う。"""
        with self._lock:
            row = self._conn.execute("SELECT id FROM devices WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if row:
                did = row["id"]
            else:
                cur = self._conn.execute(
                    "INSERT INTO devices(name, dtype, account, fingerprint, created_at) VALUES (?,?,?,?,?)",
                    (name, dtype, "", fingerprint, time.time()))
                did = cur.lastrowid
            self._conn.execute("UPDATE locations SET device_id = ? WHERE device_id IS NULL", (did,))
            self._conn.commit()
            return did

    # ---- 場所（ロケーション） ----
    def locations(self):
        return self._rows(LOC_SELECT + " ORDER BY l.name COLLATE NOCASE, l.id")

    def location(self, lid):
        return self._one(LOC_SELECT + " WHERE l.id = ?", (lid,))

    def find_location_by_root(self, root):
        for loc in self._rows("SELECT id, root FROM locations WHERE mode = 'scan'"):
            if norm(loc["root"]) == norm(root):
                return loc
        return None

    def add_location(self, name, root, kind, device_id=None, mode="scan"):
        return self._run(
            "INSERT INTO locations(name, kind, root, created_at, device_id, mode) VALUES (?,?,?,?,?,?)",
            (name, kind, root, time.time(), device_id, mode))

    def update_location(self, lid, **fields):
        allowed = {"name", "kind", "root", "device_id"}
        cols = [k for k in fields if k in allowed]
        if cols:
            sql = "UPDATE locations SET " + ", ".join(f"{c} = ?" for c in cols) + " WHERE id = ?"
            self._run(sql, [fields[c] for c in cols] + [lid])

    def delete_location(self, lid):
        self._run("DELETE FROM locations WHERE id = ?", (lid,))

    def find_location_for(self, abs_path):
        """絶対パスが属する走査対象の場所と、その場所からの相対パスを返す（最も深く一致する場所を選ぶ）。"""
        best = None
        for loc in self._rows("SELECT id, root FROM locations WHERE mode = 'scan'"):
            if is_within(abs_path, loc["root"]) and (best is None or len(loc["root"]) > len(best["root"])):
                best = loc
        if best is None:
            return None
        rel = os.path.relpath(abs_path, best["root"]).replace(os.sep, "/")
        return best, rel

    def find_overlap(self, root, exclude_id=None):
        """新しい場所が既存の走査対象と重なる（同じ・親子関係）場合、その場所を返す。"""
        for loc in self._rows("SELECT id, name, root FROM locations WHERE mode = 'scan'"):
            if loc["id"] == exclude_id:
                continue
            if is_within(root, loc["root"]) or is_within(loc["root"], root):
                return loc
        return None

    # ---- ファイル ----
    def upsert_files(self, loc_id, rows, scanned_at):
        """rows: (relpath, name, ext, category, size, mtime) のリスト。"""
        self._many(
            """INSERT INTO files(location_id, relpath, name, ext, category, size, mtime, missing, scanned_at)
               VALUES (?,?,?,?,?,?,?,0,?)
               ON CONFLICT(location_id, relpath) DO UPDATE SET
                 name = excluded.name, ext = excluded.ext, category = excluded.category,
                 size = excluded.size, mtime = excluded.mtime, missing = 0,
                 scanned_at = excluded.scanned_at""",
            [(loc_id, rel, name, ext, cat, size, mtime, scanned_at)
             for rel, name, ext, cat, size, mtime in rows])

    def file_id(self, loc_id, relpath):
        row = self._one("SELECT id FROM files WHERE location_id = ? AND relpath = ?", (loc_id, relpath))
        return row["id"] if row else None

    def stale_files(self, loc_id, before):
        """今回のスキャンで触れなかった（古いままの）ファイル。"""
        return self._rows("""
            SELECT f.id, f.relpath, f.missing, l.root FROM files f
            JOIN locations l ON l.id = f.location_id
            WHERE f.location_id = ? AND f.scanned_at < ?""", (loc_id, before))

    def set_missing(self, pairs):
        """pairs: (missing_flag, file_id) のリスト。"""
        self._many("UPDATE files SET missing = ? WHERE id = ?", pairs)

    def get_file(self, fid):
        row = self._one("""
            SELECT f.*, l.name AS location_name, l.root AS root, l.mode AS location_mode,
                   l.device_id AS device_id, d.name AS device_name, d.dtype AS device_dtype,
                   d.account AS device_account, d.fingerprint AS device_fp
            FROM files f JOIN locations l ON l.id = f.location_id
            LEFT JOIN devices d ON d.id = l.device_id
            WHERE f.id = ?""", (fid,))
        if row:
            row["path"] = join_path(row["root"], row["relpath"])
            row["media"] = json.loads(row["media"] or "{}")
        return row

    def update_file_record(self, fid, loc_id, relpath, name, ext, category, size, mtime):
        """名前変更・移動のあとに索引を付け替える。タグ・メモ・リンクは残す。"""
        with self._lock:
            self._conn.execute(
                "DELETE FROM files WHERE location_id = ? AND relpath = ? AND id <> ?",
                (loc_id, relpath, fid))
            self._conn.execute(
                """UPDATE files SET location_id=?, relpath=?, name=?, ext=?, category=?,
                   size=?, mtime=?, missing=0 WHERE id=?""",
                (loc_id, relpath, name, ext, category, size, mtime, fid))
            self._conn.commit()

    def set_memo(self, fid, memo):
        self._run("UPDATE files SET memo = ? WHERE id = ?", (memo, fid))

    def set_media(self, fid, media):
        self._run("UPDATE files SET media = ? WHERE id = ?",
                  (json.dumps(media, ensure_ascii=False), fid))

    def delete_file(self, fid):
        self._run("DELETE FROM files WHERE id = ?", (fid,))

    def delete_missing(self):
        self._run("DELETE FROM files WHERE missing = 1")

    def clear_index(self):
        self._run("DELETE FROM files")

    # ---- 検索 ----
    def _where(self, flt):
        clauses, args = [], []
        for token in (flt.get("text") or "").split():
            like = f"%{escape_like(token)}%"
            clauses.append("(f.name LIKE ? ESCAPE '!' OR f.relpath LIKE ? ESCAPE '!' "
                           "OR f.memo LIKE ? ESCAPE '!')")
            args += [like, like, like]
        exts = [e for e in flt.get("exts") or [] if e]
        if exts:
            clauses.append(f"f.ext IN ({','.join('?' * len(exts))})")
            args += exts
        cats = flt.get("categories") or []
        if cats:
            clauses.append(f"f.category IN ({','.join('?' * len(cats))})")
            args += cats
        if flt.get("min_size") is not None:
            clauses.append("f.size >= ?")
            args.append(flt["min_size"])
        if flt.get("max_size") is not None:
            clauses.append("f.size <= ?")
            args.append(flt["max_size"])
        if flt.get("mtime_from") is not None:
            clauses.append("f.mtime >= ?")
            args.append(flt["mtime_from"])
        if flt.get("mtime_to") is not None:
            clauses.append("f.mtime < ?")
            args.append(flt["mtime_to"])
        if flt.get("location_id"):
            clauses.append("f.location_id = ?")
            args.append(flt["location_id"])
        if flt.get("device_id"):
            clauses.append("l.device_id = ?")
            args.append(flt["device_id"])
        if not flt.get("include_missing"):
            clauses.append("f.missing = 0")
        for tid in flt.get("tags") or []:
            clauses.append("EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = f.id AND ft.tag_id = ?)")
            args.append(tid)
        return " AND ".join(clauses) or "1=1", args

    def search(self, flt, limit=300, offset=0):
        where, args = self._where(flt)
        order = SORTS.get(flt.get("sort"), SORTS["name"])
        rows = self._rows(f"""
            SELECT f.id, f.relpath, f.name, f.ext, f.category, f.size, f.mtime, f.missing, f.memo,
                   l.name AS location_name, l.root AS root, l.mode AS location_mode,
                   (SELECT GROUP_CONCAT(tg.name, ', ') FROM file_tags ft
                    JOIN tags tg ON tg.id = ft.tag_id WHERE ft.file_id = f.id) AS tags
            FROM files f JOIN locations l ON l.id = f.location_id
            WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""", args + [limit, offset])
        for r in rows:
            r["path"] = join_path(r["root"], r["relpath"])
        return rows

    def count(self, flt):
        """該当件数と、そのうち欠落している件数。"""
        where, args = self._where(flt)
        return self._one(f"""
            SELECT COUNT(*) AS n, COALESCE(SUM(f.missing), 0) AS missing
            FROM files f JOIN locations l ON l.id = f.location_id WHERE {where}""", args)

    # ---- タグ ----
    def tags_of(self, fid):
        return self._rows("""SELECT t.id, t.name FROM tags t
            JOIN file_tags ft ON ft.tag_id = t.id WHERE ft.file_id = ? ORDER BY t.name""", (fid,))

    def all_tags(self):
        return self._rows("""
            SELECT t.id, t.name, COUNT(ft.file_id) AS n FROM tags t
            LEFT JOIN file_tags ft ON ft.tag_id = t.id
            GROUP BY t.id ORDER BY t.name COLLATE NOCASE""")

    def add_tag(self, fid, name):
        name = name.strip()
        if not name:
            return
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
            tid = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
            self._conn.execute("INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?,?)", (fid, tid))
            self._conn.commit()

    def remove_tag(self, fid, tid):
        self._run("DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?", (fid, tid))

    def rename_tag(self, tid, name):
        """同名のタグがあれば sqlite3.IntegrityError になる。"""
        self._run("UPDATE tags SET name = ? WHERE id = ?", (name.strip(), tid))

    def delete_tag(self, tid):
        self._run("DELETE FROM tags WHERE id = ?", (tid,))

    # ---- リンク（関連ファイル） ----
    def linked_files(self, fid):
        rows = self._rows("""
            SELECT f.id, f.name, f.relpath, l.root AS root FROM links k
            JOIN files f ON f.id = CASE WHEN k.file_a = ? THEN k.file_b ELSE k.file_a END
            JOIN locations l ON l.id = f.location_id
            WHERE ? IN (k.file_a, k.file_b) ORDER BY f.name COLLATE NOCASE""", (fid, fid))
        for r in rows:
            r["path"] = join_path(r["root"], r["relpath"])
        return rows

    def link(self, a, b):
        if a == b:
            return
        lo, hi = sorted((a, b))
        self._run("INSERT OR IGNORE INTO links(file_a, file_b) VALUES (?,?)", (lo, hi))

    def unlink(self, a, b):
        lo, hi = sorted((a, b))
        self._run("DELETE FROM links WHERE file_a = ? AND file_b = ?", (lo, hi))
