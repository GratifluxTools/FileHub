"""索引データの書き出し・読み込み（別のPCのFileHubへ移すため）。

書き出しは1つのJSONファイル。読み込みは既存の索引に「統合」する:
- このPCのデバイス（指紋が一致）は、読み込み先のこのPCのデバイスにまとめる。
- 同じ名前・種類・アカウントのデバイス、同じフォルダ（同じ根）の場所は、既存のものを使う。
- 同じ場所のファイルは、タグ・メモ・リンクを足し合わせる（メモが空なら既存のものを残す）。
"""
import time

FORMAT = "filehub-export"
VERSION = 1


def export_all(db) -> dict:
    with db._lock:
        c = db._conn
        rows = lambda sql: [dict(r) for r in c.execute(sql).fetchall()]  # noqa: E731
        return {
            "format": FORMAT,
            "version": VERSION,
            "exported_at": time.time(),
            "devices": rows("SELECT id, name, dtype, account, fingerprint, created_at FROM devices"),
            "locations": rows("SELECT id, name, kind, root, created_at, device_id, mode FROM locations"),
            "files": rows("""SELECT id, location_id, relpath, name, ext, category, size, mtime,
                             missing, memo, media, scanned_at FROM files"""),
            "tags": rows("SELECT id, name FROM tags"),
            "file_tags": rows("SELECT file_id, tag_id FROM file_tags"),
            "links": rows("SELECT file_a, file_b FROM links"),
        }


def import_all(db, data: dict, here_fingerprint: str, here_device_id: int) -> dict:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("this file is not a File Hub export")
    counts = {"devices": 0, "locations": 0, "files": 0, "tags": 0, "links": 0}

    # 1) デバイス
    dev_map = {}
    for d in data.get("devices", []):
        if d.get("fingerprint") and d["fingerprint"] == here_fingerprint:
            dev_map[d["id"]] = here_device_id
            continue
        same = db.find_device_same(d["name"], d["dtype"], d.get("account") or "")
        if same:
            dev_map[d["id"]] = same["id"]
            continue
        fp = d.get("fingerprint") if d["dtype"] == "external" else None  # 外付けの指紋は残す（別PCの指紋は捨てる）
        if fp and db.find_device_by_fingerprint(fp):
            fp = None
        dev_map[d["id"]] = db.add_device(d["name"], d["dtype"], d.get("account") or "", fp)
        counts["devices"] += 1

    # 2) 場所
    loc_map = {}
    for l in data.get("locations", []):
        existing = db.find_location_by_root_any(l["root"])
        if existing:
            loc_map[l["id"]] = existing["id"]
            continue
        did = dev_map.get(l.get("device_id"), here_device_id)
        loc_map[l["id"]] = db.add_location(l["name"], l["root"], l.get("kind") or "local", did,
                                           l.get("mode") or "scan")
        counts["locations"] += 1

    # 3) ファイル（同じ場所・同じ相対パスは、タグ・メモ・リンクを足す）
    file_map = {}
    for f in data.get("files", []):
        lid = loc_map.get(f["location_id"])
        if lid is None:
            continue
        fid = db.merge_file(lid, f)
        file_map[f["id"]] = fid
        counts["files"] += 1

    # 4) タグ
    tag_map = {}
    for tg in data.get("tags", []):
        tag_map[tg["id"]] = db.ensure_tag(tg["name"])
        counts["tags"] += 1
    for ft_ in data.get("file_tags", []):
        fid, tid = file_map.get(ft_["file_id"]), tag_map.get(ft_["tag_id"])
        if fid and tid:
            db.attach_tag(fid, tid)

    # 5) リンク
    for lk in data.get("links", []):
        a, b = file_map.get(lk["file_a"]), file_map.get(lk["file_b"])
        if a and b and a != b:
            db.link(a, b)
            counts["links"] += 1
    return counts
