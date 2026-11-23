"""ロジック層のテスト（GUI を使わない）。実行: python -m pytest tests -q"""
import json
import os
import sys
import threading
import zipfile
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """ホームフォルダと データフォルダを一時ディレクトリに差し替える。"""
    home = tmp_path / "home"
    home.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(data))
    return {"home": home, "data": data, "tmp": tmp_path}


def make_db(env):
    from db import Database
    return Database(str(env["data"] / "index.db"))


def opts(**kw):
    from scanner import ScanOptions
    return ScanOptions(**kw)


# ---------- 拡張子・カテゴリ ----------
def test_get_ext_and_category():
    from categories import category_of, get_ext
    assert get_ext("Report.PDF") == "pdf"
    assert get_ext("backup.tar.gz") == "tar.gz"
    assert get_ext("noext") == ""
    assert category_of("jpg") == "image"
    assert category_of("cpp") == "code"
    assert category_of("xyz") == "other"


# ---------- 走査・索引 ----------
def test_scan_skips_hidden_appdata_and_excluded(env):
    from scanner import scan_location
    from config import DEFAULT_EXCLUDE
    home = env["home"]
    docs = home / "Documents"
    (docs / "sub").mkdir(parents=True)
    (docs / "AppData").mkdir()
    (docs / "node_modules").mkdir()
    (docs / ".hidden_dir").mkdir()
    (docs / "a.txt").write_text("hello", encoding="utf-8")
    (docs / "sub" / "b.jpg").write_bytes(b"\xff\xd8\xff")
    (docs / "AppData" / "c.txt").write_text("x")
    (docs / "node_modules" / "d.js").write_text("x")
    (docs / ".hidden_dir" / "e.txt").write_text("x")
    (docs / ".secret").write_text("x")
    (docs / "desktop.ini").write_text("x")

    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    loc = db.location(lid)
    n = scan_location(db, loc, opts(exclude_names=set(DEFAULT_EXCLUDE), exclude_appdata=True),
                      threading.Event())
    assert n == 2
    names = sorted(r["relpath"] for r in db.search({"include_missing": True}, limit=100))
    assert names == ["a.txt", "sub/b.jpg"]


def test_include_hidden_option(env):
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir()
    (docs / ".config_file").write_text("x")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(include_hidden=True), threading.Event())
    assert db.count({"include_missing": True})["n"] == 1


def test_missing_files_are_marked_and_not_deleted(env):
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir()
    f = docs / "gone.txt"
    f.write_text("x")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    f.unlink()
    scan_location(db, db.location(lid), opts(), threading.Event())
    stats = db.count({"include_missing": True})
    assert stats["n"] == 1 and stats["missing"] == 1
    assert db.count({"include_missing": False})["n"] == 0


def test_cancelled_scan_returns_none(env):
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir()
    (docs / "a.txt").write_text("x")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    cancel = threading.Event()
    cancel.set()
    assert scan_location(db, db.location(lid), opts(), cancel) is None


def test_home_restriction(env):
    from paths import is_inside_home
    assert is_inside_home(str(env["home"] / "Documents"))
    assert not is_inside_home(str(env["tmp"]))


# ---------- 検索・タグ・リンク・メモ ----------
def test_search_filters_tags_links_memo(env):
    from scanner import scan_location, index_abs
    docs = env["home"] / "Documents"
    (docs / "sub").mkdir(parents=True)
    (docs / "invoice_2025.pdf").write_bytes(b"%PDF-1.4")
    (docs / "sub" / "photo.jpg").write_bytes(b"x" * 2048)
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())

    hits = db.search({"text": "invoice"})
    assert [h["name"] for h in hits] == ["invoice_2025.pdf"]
    assert db.search({"exts": ["jpg"]})[0]["relpath"] == "sub/photo.jpg"
    assert db.search({"categories": ["image"]})[0]["name"] == "photo.jpg"
    assert db.search({"min_size": 1000})[0]["name"] == "photo.jpg"
    assert db.count({"text": "nomatch"})["n"] == 0

    fid = hits[0]["id"]
    db.add_tag(fid, "tax")
    db.add_tag(fid, "2025")
    tid = [tg["id"] for tg in db.all_tags() if tg["name"] == "tax"][0]
    assert [h["name"] for h in db.search({"tags": [tid]})] == ["invoice_2025.pdf"]
    db.remove_tag(fid, tid)
    assert db.search({"tags": [tid]}) == []

    photo_id = db.search({"exts": ["jpg"]})[0]["id"]
    db.link(fid, photo_id)
    db.link(photo_id, fid)  # 二重に作っても一件
    linked = db.linked_files(fid)
    assert [x["name"] for x in linked] == ["photo.jpg"]
    db.unlink(fid, photo_id)
    assert db.linked_files(fid) == []

    db.set_memo(fid, "確定申告用")
    assert db.search({"text": "確定申告"})[0]["name"] == "invoice_2025.pdf"
    assert index_abs(db, str(docs / "invoice_2025.pdf")) == fid


def test_like_wildcards_are_escaped(env):
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir()
    (docs / "100%_done.txt").write_text("x")
    (docs / "1000done.txt").write_text("x")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    assert [r["name"] for r in db.search({"text": "100%_"})] == ["100%_done.txt"]


def test_relocate_keeps_tags_and_memo(env):
    from scanner import scan_location, index_abs, relocate_record
    docs = env["home"] / "Documents"
    other = env["home"] / "Downloads"
    docs.mkdir()
    other.mkdir()
    f = docs / "memo.txt"
    f.write_text("hi")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    db.add_location("Downloads", str(other), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    fid = index_abs(db, str(f))
    db.add_tag(fid, "keep")
    db.set_memo(fid, "memo kept")

    new_path = other / "memo.txt"
    os.rename(f, new_path)
    assert relocate_record(db, fid, str(new_path)) == fid
    rec = db.get_file(fid)
    assert rec["path"] == str(new_path)
    assert rec["location_name"] == "Downloads"
    assert [t["name"] for t in db.tags_of(fid)] == ["keep"]
    assert rec["memo"] == "memo kept"

    outside = env["tmp"] / "outside.txt"
    outside.write_text("x")
    os.rename(new_path, outside)
    assert relocate_record(db, fid, str(outside)) is None
    assert db.get_file(fid) is None


def test_stale_scan_detects_moved_inside_same_root(env):
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir()
    (docs / "x.txt").write_text("x")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    assert db.count({"include_missing": True})["n"] == 1


def test_db_overlap_and_location_lookup(env):
    db = make_db(env)
    home = env["home"]
    (home / "Documents" / "Sub").mkdir(parents=True)
    db.add_location("Documents", str(home / "Documents"), "local")
    assert db.find_overlap(str(home / "Documents" / "Sub")) is not None
    assert db.find_overlap(str(home)) is not None
    assert db.find_overlap(str(home / "Pictures")) is None
    loc, rel = db.find_location_for(str(home / "Documents" / "Sub" / "a.txt"))
    assert rel == "Sub/a.txt"


# ---------- 圧縮・展開 ----------
def test_zip_roundtrip_and_zip_slip_rejected(env):
    from archive_utils import ArchiveError, create_zip, extract_archive, list_archive
    src = env["tmp"] / "src.txt"
    src.write_text("content")
    zpath = env["tmp"] / "out.zip"
    create_zip([(str(src), "src.txt")], str(zpath))
    assert list_archive(str(zpath)) == ["src.txt"]
    dest = env["tmp"] / "ex"
    assert extract_archive(str(zpath), str(dest)) == 1
    assert (dest / "src.txt").read_text() == "content"

    evil = env["tmp"] / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../escape.txt", "x")
    with pytest.raises(ArchiveError):
        extract_archive(str(evil), str(env["tmp"] / "ex2"))
    assert not (env["tmp"] / "escape.txt").exists()


def test_targz_roundtrip(env):
    import tarfile
    from archive_utils import create_targz, extract_archive
    src = env["tmp"] / "a.txt"
    src.write_text("tar body")
    tpath = env["tmp"] / "pack.tar.gz"
    create_targz([(str(src), "a.txt")], str(tpath))
    dest = env["tmp"] / "unpacked"
    assert extract_archive(str(tpath), str(dest)) == 1
    assert (dest / "a.txt").read_text() == "tar body"
    with tarfile.open(tpath) as tf:
        assert "a.txt" in tf.getnames()


# ---------- テキスト ----------
def test_text_encodings_roundtrip(env):
    from text_io import read_text, write_text
    p = env["tmp"] / "sjis.txt"
    p.write_bytes("日本語のテキスト".encode("cp932"))
    text, enc, truncated = read_text(str(p), 1024)
    assert text == "日本語のテキスト" and enc == "cp932" and not truncated
    write_text(str(p), "書き換え", enc)
    assert p.read_bytes() == "書き換え".encode("cp932")

    u = env["tmp"] / "u8.txt"
    u.write_text("hello 世界", encoding="utf-8")
    text, enc, _ = read_text(str(u), 1024)
    assert text == "hello 世界" and enc == "utf-8"
    write_text(str(u), text, enc)
    assert u.read_bytes() == "hello 世界".encode("utf-8")  # BOM を勝手に付けない


def test_truncated_read_flags_and_handles_multibyte(env):
    from text_io import read_text
    p = env["tmp"] / "long.txt"
    p.write_text("あ" * 100, encoding="utf-8")
    text, enc, truncated = read_text(str(p), 10)
    assert truncated is True
    assert text and set(text) <= {"あ"}


def test_office_and_rtf_text_extraction(env):
    from text_io import extract_office_text
    docx = env["tmp"] / "a.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p><w:r><w:t>一段落目</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>二段落目</w:t></w:r></w:p></w:body></w:document>')
    text = extract_office_text(str(docx), "docx")
    assert "一段落目" in text and "二段落目" in text

    rtf = env["tmp"] / "a.rtf"
    rtf.write_bytes(rb"{\rtf1\ansi Hello \b bold\b0 world\par}")
    assert "Hello" in extract_office_text(str(rtf), "rtf")


# ---------- 画像 ----------
def test_image_operations(env):
    from PIL import Image
    from image_tools import apply_op
    src = env["tmp"] / "in.png"
    Image.new("RGB", (40, 20), (255, 0, 0)).save(src)
    out = env["tmp"] / "rot.png"
    apply_op(str(src), str(out), "rot_cw")
    with Image.open(out) as im:
        assert im.size == (20, 40)
    out2 = env["tmp"] / "small.jpg"
    apply_op(str(src), str(out2), "resize", max_side=10)
    with Image.open(out2) as im:
        assert max(im.size) == 10
    out3 = env["tmp"] / "gray.png"
    apply_op(str(src), str(out3), "gray")
    with Image.open(out3) as im:
        assert im.mode == "L"
    with pytest.raises(ValueError):
        apply_op(str(src), str(env["tmp"] / "x.svg"), "gray")


# ---------- 音声タグ ----------
def _mp3_bytes(frames=12):
    # MPEG-1 Layer III, 128kbps, 44.1kHz の無音フレーム（タグ読み書きの確認用）
    header = bytes([0xFF, 0xFB, 0x90, 0x64])
    return (header + bytes(413)) * frames


def test_read_write_mp3_tags(env):
    from media_tags import read_tags, write_tags
    p = env["tmp"] / "song.mp3"
    p.write_bytes(_mp3_bytes())
    assert read_tags(str(p)) == {}
    write_tags(str(p), {"title": "Blue", "artist": "Band", "album": "Album", "track": "3", "year": "2020"})
    got = read_tags(str(p))
    assert got.get("title") == "Blue" and got.get("artist") == "Band" and got.get("track") == "3"


def test_tags_not_supported_for_plain_text(env):
    from media_tags import read_tags, write_tags
    p = env["tmp"] / "plain.txt"
    p.write_text("not audio")
    assert read_tags(str(p)) == {}
    with pytest.raises(ValueError):
        write_tags(str(p), {"title": "x"})


# ---------- 画面（UI）の組み立てスモークテスト ----------
def test_ui_builds_without_error(env):
    """実際の画面は起動しないが、画面の組み立て（コンストラクタ引数など）が落ちないことを確かめる。"""
    import flet as ft
    from scanner import scan_location
    import main as app

    docs = env["home"] / "Documents"
    docs.mkdir()
    (docs / "a.txt").write_text("hello")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    mark_initial_scan_done(env)
    fake = mock.MagicMock()
    fake.overlay = []
    fake.run_thread = lambda fn, *a, **k: fn(*a, **k)
    with mock.patch.object(ft, "FilePicker", mock.MagicMock()):
        app.main(fake)
    added = [c.args[0] for c in fake.add.call_args_list]
    assert added, "page.add was not called"


def mark_initial_scan_done(env):
    import json
    (env["data"] / "config.json").write_text(json.dumps({"initial_scan_done": True}), encoding="utf-8")


def _walk(control):
    """Flet のコントロール木を深さ優先で列挙する。"""
    stack = [control]
    while stack:
        c = stack.pop()
        if c is None or isinstance(c, (str, int, float, bool)):
            continue
        yield c
        for attr in ("controls", "tabs"):
            kids = getattr(c, attr, None)
            if isinstance(kids, list):
                stack.extend(kids)
        for attr in ("content", "leading", "trailing", "title", "subtitle", "actions"):
            kid = getattr(c, attr, None)
            if kid is not None and not isinstance(kid, (list, str)):
                stack.append(kid)
            elif isinstance(kid, list):
                stack.extend(kid)


def test_ui_interactions_search_detail_tags_memo(env):
    """検索 → 詳細 → タグ追加 → メモ保存 を画面部品の操作として実行する。"""
    import flet as ft
    from scanner import scan_location
    import main as app

    docs = env["home"] / "Documents"
    docs.mkdir()
    (docs / "notes_2025.txt").write_text("first line\nsecond line", encoding="utf-8")
    (docs / "photo.png").write_bytes(b"x")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())

    mark_initial_scan_done(env)
    fake = mock.MagicMock()
    fake.overlay = []
    fake.run_thread = lambda fn, *a, **k: fn(*a, **k)
    with mock.patch.object(ft, "FilePicker", mock.MagicMock()):
        app.main(fake)
    root = fake.add.call_args_list[-1].args[0]
    body = root.controls[-1]
    tabs = body.content
    search_view = tabs.tabs[0].content

    keyword = [c for c in _walk(search_view) if isinstance(c, ft.TextField)
               and c.label and c.label == app.t("keyword")][0]
    keyword.value = "notes"
    keyword.on_submit(None)
    rows = [c for c in _walk(search_view) if isinstance(c, ft.ListTile)]
    assert len(rows) == 1

    # 詳細画面を開く（テキストは編集できる）
    rows[0].on_click(None)
    detail_titles = [c.value for c in _walk(body) if isinstance(c, ft.Text)]
    assert "notes_2025.txt" in detail_titles
    tag_in = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.label == app.t("add_tag")][0]
    tag_in.value = "meeting"
    tag_in.on_submit(None)
    assert [tg["name"] for tg in db.tags_of(db.search({"text": "notes"})[0]["id"])] == ["meeting"]

    memo = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.multiline and c.value == ""]
    assert memo
    memo[-1].value = "会議メモ"
    # 画面の「保存」ボタンはテキスト編集用とメモ用の2つ。どちらを押しても中身は同じ
    for save_btn in [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("save")]:
        save_btn.on_click(None)
    assert db.search({"text": "会議"})[0]["name"] == "notes_2025.txt"

    # 画像の詳細へ移動し、プレビューと加工ボタンが出ること
    back = [c for c in _walk(body) if isinstance(c, ft.IconButton) and c.icon == ft.Icons.ARROW_BACK]
    back[0].on_click(None)
    keyword.value = "photo"
    keyword.on_submit(None)
    photo_rows = [c for c in _walk(search_view) if isinstance(c, ft.ListTile)]
    assert len(photo_rows) == 1
    photo_rows[0].on_click(None)
    labels = [c.text for c in _walk(body) if isinstance(c, ft.ElevatedButton)]
    assert app.t("op_rot_cw") in labels
    assert any(isinstance(c, ft.Image) for c in _walk(body))

    # 一覧に戻る
    back = [c for c in _walk(body) if isinstance(c, ft.IconButton) and c.icon == ft.Icons.ARROW_BACK]
    back[0].on_click(None)
    assert body.content is tabs


def test_ui_image_op_compress_and_settings(env):
    import time as _time
    import flet as ft
    from PIL import Image
    from scanner import scan_location
    import main as app

    docs = env["home"] / "Documents"
    docs.mkdir()
    Image.new("RGB", (30, 10), (0, 128, 255)).save(docs / "pic.png")
    (docs / "memo.txt").write_text("abc", encoding="utf-8")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())

    mark_initial_scan_done(env)
    mark_initial_scan_done(env)
    fake = mock.MagicMock()
    fake.overlay = []
    fake.run_thread = lambda fn, *a, **k: fn(*a, **k)
    with mock.patch.object(ft, "FilePicker", mock.MagicMock()):
        app.main(fake)
    root = fake.add.call_args_list[-1].args[0]
    body = root.controls[-1]
    tabs = body.content
    search_view = tabs.tabs[0].content
    settings_view = tabs.tabs[3].content

    keyword = [c for c in _walk(search_view) if isinstance(c, ft.TextField)
               and c.label == app.t("keyword")][0]
    keyword.value = "pic"
    keyword.on_submit(None)
    [c for c in _walk(search_view) if isinstance(c, ft.ListTile)][0].on_click(None)
    rot = [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("op_rot_cw")][0]
    rot.on_click(None)
    edited = docs / "pic_edited.png"
    assert edited.exists()
    with Image.open(edited) as im:
        assert im.size == (10, 30)
    assert db.search({"text": "pic_edited"})  # 新しい画像は索引にも入る

    # 複数選択 → 圧縮
    keyword.value = ""
    keyword.on_submit(None)
    for tile in [c for c in _walk(search_view) if isinstance(c, ft.ListTile)]:
        for c in tile.leading.controls:
            if isinstance(c, ft.Checkbox):
                c.value = True
                c.on_change(mock.MagicMock(control=c))
    compress = [c for c in _walk(search_view) if isinstance(c, ft.ElevatedButton)
                and c.text == app.t("compress_selected")][0]
    compress.on_click(None)
    _time.sleep(0.2)  # バックグラウンド処理の完了を待つ
    zips = list(docs.glob("archive-*.zip"))
    assert zips, "zip was not created"

    # 設定の保存（言語は英語のまま、除外フォルダを変更）
    s_ex = [c for c in _walk(settings_view) if isinstance(c, ft.TextField)
            and c.label == app.t("set_exclude")][0]
    s_ex.value = "node_modules, build"
    save = [c for c in _walk(settings_view) if isinstance(c, ft.ElevatedButton)
            and c.text == app.t("btn_save")][0]
    save.on_click(None)
    import json
    saved = json.loads((env["data"] / "config.json").read_text(encoding="utf-8"))
    assert saved["exclude_names"] == ["node_modules", "build"]


def test_portable_data_dir_and_edition(env, monkeypatch):
    import config
    portable = env["tmp"] / "usb" / "data"
    monkeypatch.setattr(config, "EDITION", "portable")
    monkeypatch.setenv("FILEHUB_DATA_DIR", str(portable))
    assert config.data_dir() == str(portable)
    assert portable.is_dir()
    monkeypatch.setattr(config, "EDITION", "single")
    monkeypatch.delenv("FILEHUB_DATA_DIR")
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(env["data"]))
    assert config.data_dir() == str(env["data"])


# ---------- 0.2 の追加機能 ----------
def test_preview_default_is_100mb_and_old_keys_ignored(env, tmp_path):
    import json
    from config import Config
    assert Config().preview_mb == 100
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"preview_kb": 512, "preview_mb": 100}), encoding="utf-8")
    assert Config.load(str(p)).preview_mb == 100


def test_folder_tree_check_and_uncheck_rules(tmp_path):
    from folder_tree import check, covered, minimal, uncheck
    from scanner import ScanOptions, list_child_dirs
    root = tmp_path / "home"
    (root / "A" / "A1" / "deep").mkdir(parents=True)
    (root / "A" / "A2").mkdir()
    (root / "B").mkdir()
    lister = lambda p: list_child_dirs(p, ScanOptions())  # noqa: E731
    A, A1, A2, B = (str(root / x) for x in ("A", "A/A1", "A/A2", "B"))

    sel = check(A, set())
    assert sel == {A} and covered(A1, sel) and not covered(B, sel)
    # 上位が選ばれたまま、下位の一つを外すと、上位は兄弟に分解される
    sel = uncheck(A1, sel, lister)
    assert covered(A2, sel) and not covered(A1, sel) and covered(str(root / "A"), {A}) is True
    assert A1 not in sel
    # 上位を外すと、下位もすべて外れる
    assert uncheck(A, {A, B}, lister) == {B}
    # 下位を先に選んでから上位を選ぶと、下位は吸収される
    sel = check(A1, set())
    sel = check(A, sel)
    assert sel == {A}
    # 上位に含まれるものは登録の一覧から外す
    assert sorted(minimal({A, A1, B})) == sorted([A, B])


def test_list_child_dirs_skips_hidden_and_appdata(env):
    from scanner import ScanOptions, list_child_dirs
    home = env["home"]
    for name in ("Docs", ".hidden", "AppData", "node_modules", "Pics"):
        (home / name).mkdir()
    (home / "file.txt").write_text("x")
    names = [os.path.basename(p) for p in list_child_dirs(str(home), ScanOptions(
        exclude_names={"node_modules"}, include_hidden=False, exclude_appdata=True))]
    assert names == ["Docs", "Pics"]
    names = [os.path.basename(p) for p in list_child_dirs(str(home), ScanOptions(
        exclude_names=set(), include_hidden=True, exclude_appdata=False))]
    assert names == [".hidden", "AppData", "Docs", "node_modules", "Pics"]


def test_devices_migration_and_current_device(env):
    import sqlite3
    from db import Database
    path = env["data"] / "index.db"
    # 0.1.x の索引（devices・device_id・mode が無い）を作る
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE locations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'local', root TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
        INSERT INTO locations(name, root, created_at) VALUES ('Old', '/x/old', 0);
    """)
    con.commit()
    con.close()
    db = Database(str(path))
    old = db.locations()
    assert old and old[0]["device_id"] is None and old[0]["mode"] == "scan"
    did = db.ensure_current_device("PC-A", "windows", "fp-1")
    assert db.locations()[0]["device_id"] == did  # 紐付けの無い場所はこのPCのものになる
    assert db.ensure_current_device("PC-A", "windows", "fp-1") == did  # 二度目は同じデバイス
    other = db.add_device("Old PC", "windows", "")
    lid = db.add_location("Other", str(env["tmp"] / "other"), "local", other, "scan")
    db.delete_device(other)
    assert db.location(lid) is None  # デバイスを消すと、その場所も消える


def test_manual_locations_and_files(env):
    from scanner import parse_manual_lines
    db = make_db(env)
    did = db.add_device("Google Drive", "gdrive", "taro@example.com")
    lid = db.add_location("GDrive docs", "manual://abc", "manual", did, "manual")
    rows = parse_manual_lines("Documents/report.docx\n\nPhotos/2025/\nPhotos\\trip.JPG\nDocuments/report.docx")
    assert [r[0] for r in rows] == ["Documents/report.docx", "Photos/trip.JPG"]
    db.upsert_files(lid, rows, 1.0)
    hits = db.search({"text": "report"})
    assert len(hits) == 1 and hits[0]["location_mode"] == "manual"
    rec = db.get_file(hits[0]["id"])
    assert rec["device_account"] == "taro@example.com"
    assert rec["device_dtype"] == "gdrive"
    # 手動の場所は走査されない・ディスクに無いファイルを欠落扱いにもしない
    from scanner import index_abs
    assert index_abs(db, str(env["tmp"] / "nowhere.txt")) is None


def _mp3_path(env):
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    import subprocess
    out = env["tmp"] / "song.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=1", "-c:a", "libmp3lame", str(out)], check=True)
    return out


def test_write_tags_mp3_and_mp4(env):
    import shutil
    import subprocess
    import media_tags as m
    mp3 = _mp3_path(env)
    unsupported = m.write_tags(str(mp3), {"title": "Blue", "artist": "Band", "track": "3",
                                          "series": "Show", "season": "2"})
    assert unsupported == ["series", "season", "episode"]
    got = m.read_tags(str(mp3))
    assert got["title"] == "Blue" and got["artist"] == "Band" and got["track"] == "3"
    m.write_tags(str(mp3), {"track": "3/12"})  # ID3 のトラック番号は「3/12」形式も書ける
    assert m.read_tags(str(mp3))["track"] == "3"

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    mp4 = env["tmp"] / "show.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=64x64:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    assert m.write_tags(str(mp4), {"title": "Pilot", "album": "Season One", "track": "1",
                                   "year": "2024", "series": "My Show", "season": "1", "episode": "4"}) == []
    got = m.read_tags(str(mp4))
    assert got == {"title": "Pilot", "album": "Season One", "track": "1", "year": "2024",
                   "series": "My Show", "season": "1", "episode": "4"}
    m.write_tags(str(mp4), {"series": "", "season": "", "episode": ""})
    assert "series" not in m.read_tags(str(mp4))


def test_ui_registration_manual_entry_on_first_run(env):
    """初回起動は登録画面を開く。手動登録のフォームから、場所とファイル一覧を登録できる。"""
    import flet as ft
    import main as app
    fake = mock.MagicMock()
    fake.overlay = []
    fake.run_thread = lambda fn, *a, **k: fn(*a, **k)
    with mock.patch.object(ft, "FilePicker", mock.MagicMock()):
        app.main(fake)
    root = fake.add.call_args_list[-1].args[0]
    body = root.controls[-1]
    # 登録画面（戻るボタンがあり、タブは無い）
    assert not hasattr(body.content, "tabs")
    # 初回は現在のPCなので、既定はツリー。「手動で登録」に切り替える
    manual_btn = [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("manual_mode")]
    manual_btn[0].on_click(None)
    # 場所の名前は、登録済みデバイスのプルダウン（選んだデバイス名が場所の名前になる）
    dd = [c for c in _walk(body) if isinstance(c, ft.Dropdown) and c.label == app.t("manual_location_name")]
    files_tf = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.label == app.t("manual_files_label")]
    assert dd and files_tf
    db = make_db(env)
    gdrive = db.add_device("Google Drive", "gdrive", "taro@example.com")
    dd[0].value = str(gdrive)
    dd[0].on_change(mock.MagicMock(control=dd[0]))  # 選ぶと登録画面が作り直される
    dd = [c for c in _walk(body) if isinstance(c, ft.Dropdown) and c.label == app.t("manual_location_name")]
    files_tf = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.label == app.t("manual_files_label")]
    files_tf[0].value = "Docs/report.docx\nPics/cat.jpg"
    btn = [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("manual_register")]
    btn[0].on_click(None)
    hits = db.search({"text": "cat", "include_missing": True})
    assert hits and hits[0]["location_name"] == "Google Drive"
    assert db.get_file(hits[0]["id"])["device_name"] == "Google Drive"
    assert hits[0]["location_mode"] == "manual"


def test_folder_tree_view_expand_and_check(tmp_path):
    """ツリー部品を開いて、チェックを入れる・外す操作が選択に反映されること。"""
    from folder_tree import FolderTreeView
    from scanner import ScanOptions, list_child_dirs
    root = tmp_path / "home"
    (root / "Docs" / "Sub").mkdir(parents=True)
    (root / "Pics").mkdir()
    state = {"sel": set()}
    opts = ScanOptions()
    tree = FolderTreeView(str(root), lambda p: list_child_dirs(p, opts), state,
                          lambda: None, empty_text="-", page=None)
    # ルートは開いた状態。子（Docs, Pics）が見える
    cbs = dict((os.path.basename(p), cb) for p, cb in tree.rendered)
    assert "Docs" in cbs and "Pics" in cbs
    # Docs にチェック → Docs 以下が対象になる
    cbs["Docs"].on_change(mock.MagicMock(control=mock.MagicMock(value=True)))
    assert state["sel"] == {str(root / "Docs")}
    # 展開していない子（Sub）も、上位の選択に含まれて表示上はチェック済み
    assert tree.rendered and all(cb.value for p, cb in tree.rendered if os.path.basename(p) in ("Docs", "Sub"))
    assert not [cb for p, cb in tree.rendered if os.path.basename(p) == "Pics" and cb.value]
    # 外すと、下位も対象外になる
    cbs["Docs"].on_change(mock.MagicMock(control=mock.MagicMock(value=False)))
    assert state["sel"] == set()


def test_external_drive_is_allowed_but_random_folders_are_not(env, tmp_path, monkeypatch):
    import storage_roots
    drive = tmp_path / "SSD"
    (drive / "Photos").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setattr(storage_roots, "external_roots", lambda: [str(drive)])
    assert storage_roots.is_allowed_root(str(env["home"] / "Documents"))   # ホーム
    assert storage_roots.is_allowed_root(str(drive / "Photos"))            # 外付けの中
    assert not storage_roots.is_allowed_root(str(outside))                 # どちらでもない


def test_tree_shows_every_root(tmp_path):
    from folder_tree import FolderTreeView
    from scanner import ScanOptions, list_child_dirs
    home = tmp_path / "home"
    ssd = tmp_path / "ssd"
    (home / "A").mkdir(parents=True)
    (ssd / "Movies").mkdir(parents=True)
    state = {"sel": set()}
    opts = ScanOptions()
    tree = FolderTreeView([str(home), str(ssd)], lambda p: list_child_dirs(p, opts), state,
                          lambda: None, empty_text="-", page=None)
    assert len(tree.container.controls) == 2
    paths = {p for p, _cb in tree.rendered}
    assert {str(home), str(ssd), str(home / "A"), str(ssd / "Movies")} <= paths


def test_language_notice_is_in_the_new_language():
    import i18n
    i18n.set_language("en")
    assert i18n.t_for("ja", "lang_restart").startswith("アプリを一度完全に閉じて")
    assert "close the app" in i18n.t("lang_restart")
    assert i18n.t_for("en", "lang_restart_title") == "Language changed"


def test_saving_a_new_language_shows_notice_in_the_new_language(env):
    import flet as ft
    import main as app
    mark_initial_scan_done(env)
    fake = mock.MagicMock()
    fake.overlay = []
    fake.run_thread = lambda fn, *a, **k: fn(*a, **k)
    with mock.patch.object(ft, "FilePicker", mock.MagicMock()):
        app.main(fake)
    root = fake.add.call_args_list[-1].args[0]
    body = root.controls[-1]
    settings_view = body.content.tabs[3].content
    lang = [c for c in _walk(settings_view) if isinstance(c, ft.Dropdown) and c.label == app.t("set_language")][0]
    lang.value = "ja"
    save = [c for c in _walk(settings_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("btn_save")][0]
    save.on_click(None)
    status = root.controls[1]  # 通知の行（画面の上）
    assert status.value.startswith("アプリを一度完全に閉じて")
    assert "再起動" in status.value
    assert json.loads((env["data"] / "config.json").read_text(encoding="utf-8"))["language"] == "ja"



def _open_app(env):
    import flet as ft
    import main as app
    mark_initial_scan_done(env)
    fake = mock.MagicMock()
    fake.overlay = []
    fake.run_thread = lambda fn, *a, **k: fn(*a, **k)
    with mock.patch.object(ft, "FilePicker", mock.MagicMock()):
        app.main(fake)
    body = fake.add.call_args_list[-1].args[0].controls[-1]
    return app, fake, body


def _serializes(control):
    """Flet が画面を送るときと同じ変換が通ること（例外が出ないこと）を確かめる。"""
    cmds = control._build_add_commands(index={"page": None})
    assert cmds


def test_filter_page_opens_and_reset_button_exists(env):
    import flet as ft
    app, fake, body = _open_app(env)
    tabs = body.content
    search_view = tabs.tabs[0].content
    # 検索画面に「絞り込みをリセット」がある
    assert [c for c in _walk(search_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("reset_filters")]
    # 絞り込みを押すと、画面（ダイアログではなく）に条件が並ぶ
    [c for c in _walk(search_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("filters")][0].on_click(None)
    assert body.content is not tabs  # 画面が切り替わる（ダイアログは使わない）
    assert [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("filter_apply")]
    _serializes(body)


def test_link_picker_page_links_a_file(env):
    import flet as ft
    from scanner import scan_location
    app, fake, body = _open_app(env)
    docs = env["home"] / "Documents"
    docs.mkdir(exist_ok=True)
    (docs / "a.txt").write_text("a", encoding="utf-8")
    (docs / "b.txt").write_text("b", encoding="utf-8")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    a = db.search({"text": "a.txt"})[0]["id"]
    # 検索画面から、ファイルの詳細を開く
    kw = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.label == app.t("keyword")][0]
    kw.value = "a.txt"
    kw.on_submit(None)
    [c for c in _walk(body) if isinstance(c, ft.ListTile)][0].on_click(None)
    [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("add_link")][0].on_click(None)
    _serializes(body)
    q = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.label == app.t("keyword")][0]
    q.value = "b.txt"
    q.on_submit(None)
    picks = [c for c in _walk(body) if isinstance(c, ft.ListTile)]
    assert len(picks) == 1
    picks[0].on_click(None)
    assert [x["name"] for x in db.linked_files(a)] == ["b.txt"]


def test_device_form_page_adds_device(env):
    import flet as ft
    app, fake, body = _open_app(env)
    locations_view = body.content.tabs[1].content
    [c for c in _walk(locations_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("add_device")][0].on_click(None)
    _serializes(body)
    name = [c for c in _walk(body) if isinstance(c, ft.TextField) and c.label == app.t("device_name")][0]
    name.value = "Desk NAS"
    save = [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("save")][0]
    save.on_click(None)
    db = make_db(env)
    assert [d["name"] for d in db.devices() if d["name"] == "Desk NAS"] == ["Desk NAS"]


def test_external_drive_gets_its_own_device(env, tmp_path, monkeypatch):
    import storage_roots
    from device import EXTERNAL_TYPE
    drive = tmp_path / "SSD"
    (drive / "Movies").mkdir(parents=True)
    monkeypatch.setattr(storage_roots, "external_roots", lambda: [str(drive)])
    db = make_db(env)
    here = db.ensure_current_device("PC-A", "windows", "fp-here")
    # ホームの中はこのPC、外付けは別デバイス
    assert storage_roots.device_for_path(db, str(env["home"] / "Documents"), here) == here
    ext = storage_roots.device_for_path(db, str(drive / "Movies"), here)
    assert ext != here
    assert db.device(ext)["dtype"] == EXTERNAL_TYPE and db.device(ext)["name"] == "SSD"
    # 二度目は同じデバイスを使う
    assert storage_roots.device_for_path(db, str(drive / "Movies"), here) == ext


def test_delete_other_device_via_confirm_page_and_current_device_is_refused(env):
    import flet as ft
    db = make_db(env)
    other = db.add_device("Old PC", "windows", "", "fp-old")
    db.add_location("Old loc", str(env["tmp"] / "oldroot"), "local", other, "scan")
    app, fake, body = _open_app(env)
    locations_view = body.content.tabs[1].content
    dels = [c for c in _walk(locations_view) if isinstance(c, ft.IconButton)
            and c.tooltip == app.t("delete_device")]
    assert len(dels) >= 2
    # 各ボタンが持つデバイス（lambda の既定値）で、このPCと他のデバイスを選ぶ
    here_btn = [b for b in dels if b.on_click.__defaults__[0]["fingerprint"] == app.CUR_FP][0]
    other_btn = [b for b in dels if b.on_click.__defaults__[0]["fingerprint"] != app.CUR_FP][0]
    root = fake.add.call_args_list[-1].args[0]
    # このPCのデバイスは削除できない（上の行に理由が出る）
    here_btn.on_click(None)
    assert root.controls[1].value == app.t("cannot_delete_current")
    # 他のデバイスは、画面で確認してから削除する
    other_btn.on_click(None)
    assert any(isinstance(c, ft.ElevatedButton) and c.text == app.t("delete") for c in _walk(body))
    [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("delete")][0].on_click(None)
    assert "Old PC" not in [d["name"] for d in db.devices()]


def test_clear_index_asks_on_a_page_and_then_clears(env):
    import flet as ft
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir(exist_ok=True)
    (docs / "keep.txt").write_text("x", encoding="utf-8")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    app, fake, body = _open_app(env)
    settings_view = body.content.tabs[3].content
    [c for c in _walk(settings_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("clear_index")][0].on_click(None)
    _serializes(body)
    assert db.count({"include_missing": True})["n"] == 1  # まだ消えていない（確認画面）
    [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("clear_index")][0].on_click(None)
    assert db.count({"include_missing": True})["n"] == 0


def test_remove_missing_reports_the_count(env):
    import flet as ft
    from scanner import scan_location
    docs = env["home"] / "Documents"
    docs.mkdir(exist_ok=True)
    f = docs / "gone.txt"
    f.write_text("x", encoding="utf-8")
    db = make_db(env)
    lid = db.add_location("Documents", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    f.unlink()
    scan_location(db, db.location(lid), opts(), threading.Event())
    app, fake, body = _open_app(env)
    settings_view = body.content.tabs[3].content
    [c for c in _walk(settings_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("remove_missing")][0].on_click(None)
    root = fake.add.call_args_list[-1].args[0]
    assert root.controls[1].value == app.t("removed_missing", n=1)
    assert db.count({"include_missing": True})["n"] == 0


def test_connected_volume_is_selectable_like_this_pc(env, tmp_path, monkeypatch):
    import flet as ft
    import storage_roots
    drive = tmp_path / "SSD"
    (drive / "Movies").mkdir(parents=True)
    monkeypatch.setattr(storage_roots, "external_roots", lambda: [str(drive)])
    db = make_db(env)
    vol = db.add_device("SSD", "external", "", "vol:SSD")
    # 接続されている時は、そのボリュームを根にしたツリーを選べる
    assert storage_roots.connected_root(db.device(vol)) == str(drive)
    # 接続されていないボリュームは選べない
    monkeypatch.setattr(storage_roots, "external_roots", lambda: [])
    assert storage_roots.connected_root(db.device(vol)) is None
    monkeypatch.setattr(storage_roots, "external_roots", lambda: [str(drive)])

    app, fake, body = _open_app(env)
    locations_view = body.content.tabs[1].content
    [c for c in _walk(locations_view) if isinstance(c, ft.ElevatedButton) and c.text == app.t("register")][0].on_click(None)
    reg = body  # 登録画面
    dd = [c for c in _walk(reg) if isinstance(c, ft.Dropdown) and c.label == app.t("device")][0]
    dd.value = str(vol)
    dd.on_change(mock.MagicMock(control=dd))
    # ツリーの根は、この接続ボリュームだけになる（ホームや他のドライブは出ない）
    texts = [c.value for c in _walk(reg) if isinstance(c, ft.Text) and isinstance(c.value, str)]
    assert "SSD" in texts and "Movies" in texts
    assert "Documents" not in texts


def test_volume_identity_and_device_mapping(env, tmp_path, monkeypatch):
    import storage_roots
    drive = tmp_path / "BACKUP"
    (drive / "Docs").mkdir(parents=True)
    monkeypatch.setattr(storage_roots, "external_roots", lambda: [str(drive)])
    db = make_db(env)
    here = db.ensure_current_device("PC", "windows", "fp-here")
    assert storage_roots.volume_key(str(drive)) == "vol:BACKUP"
    dev = storage_roots.device_for_path(db, str(drive / "Docs"), here)
    assert dev != here and db.device(dev)["fingerprint"] == "vol:BACKUP"
    assert storage_roots.device_for_path(db, str(drive / "Docs"), here) == dev
    assert storage_roots.connected_root(db.device(dev)) == str(drive)


# ---------- FileHub 自身のファイルの除外 ----------
def _make_install(d):
    """配布物（プログラム一式）と同じ中身のフォルダを作る。"""
    (d / "data" / "flutter_assets").mkdir(parents=True, exist_ok=True)
    (d / "file_hub.exe").write_bytes(b"MZ")
    (d / "data" / "app.so").write_bytes(b"\x7fELF")
    (d / "site-packages" / "httpcore").mkdir(parents=True, exist_ok=True)
    (d / "site-packages" / "httpcore" / "__init__.py").write_text("x", encoding="utf-8")


def test_downloads_scan_skips_install_folder_even_if_renamed(env):
    from scanner import scan_location
    from app_files import is_app_dir
    dl = env["home"] / "Downloads"
    dl.mkdir()
    (dl / "notes.txt").write_text("mine", encoding="utf-8")
    _make_install(dl / "FileHub-single-windows-x64")
    _make_install(dl / "おかしな名前の展開先")  # 名前が変わっていても中身で判定する
    assert is_app_dir(str(dl / "おかしな名前の展開先"))
    db = make_db(env)
    lid = db.add_location("Downloads", str(dl), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    names = sorted(r["relpath"] for r in db.search({"include_missing": True}, limit=1000))
    assert names == ["notes.txt"]


def test_data_folder_is_skipped_by_marker_or_by_config_plus_index(env):
    from scanner import scan_location
    docs = env["home"] / "Stuff"
    (docs / "moved-data").mkdir(parents=True)
    (docs / "moved-data" / "index.db").write_bytes(b"SQLite format 3\x00")
    (docs / "moved-data" / "config.json").write_text("{}", encoding="utf-8")
    (docs / "other-data").mkdir()
    (docs / "other-data" / "filehub-data.marker").write_text("{}", encoding="utf-8")
    (docs / "other-data" / "instance.lock").write_text("", encoding="utf-8")
    (docs / "keep.txt").write_text("mine", encoding="utf-8")
    db = make_db(env)
    lid = db.add_location("Stuff", str(docs), "local")
    scan_location(db, db.location(lid), opts(), threading.Event())
    assert [r["relpath"] for r in db.search({"include_missing": True}, limit=100)] == ["keep.txt"]


def test_export_and_build_zip_are_recognised_by_content_not_name(env):
    import zipfile
    from app_files import is_app_file
    d = env["home"] / "Downloads"
    d.mkdir()
    (d / "whatever.json").write_text('{"format": "filehub-export", "version": 1}', encoding="utf-8")
    (d / "my-data.json").write_text('{"name": "mine"}', encoding="utf-8")
    with zipfile.ZipFile(d / "renamed-archive.zip", "w") as z:
        z.writestr("file_hub.exe", "MZ")
        z.writestr("edition.py", "EDITION='x'")
    with zipfile.ZipFile(d / "photos.zip", "w") as z:
        z.writestr("cat.jpg", "x")
    assert is_app_file(str(d / "whatever.json"), "whatever.json")
    assert not is_app_file(str(d / "my-data.json"), "my-data.json")
    assert is_app_file(str(d / "renamed-archive.zip"), "renamed-archive.zip")
    assert not is_app_file(str(d / "photos.zip"), "photos.zip")


def test_no_false_positives_for_unrelated_names(env):
    from app_files import is_app_dir, is_app_relpath
    notes = env["home"] / "FileHub-notes"          # 名前は似ているが中身は関係ない
    notes.mkdir()
    (notes / "todo.txt").write_text("x", encoding="utf-8")
    assert not is_app_dir(str(notes))
    assert not is_app_relpath("FileHub-notes/todo.txt", "todo.txt")
    only_config = env["home"] / "Tools"           # config.json だけでは索引とはみなさない
    only_config.mkdir()
    (only_config / "config.json").write_text("{}", encoding="utf-8")
    assert not is_app_dir(str(only_config))
    assert is_app_relpath("FileHub-single-windows-x64/x.py", "x.py")
    assert not is_app_relpath("FileHub-single-notes/x.py", "x.py")


def test_purge_removes_existing_app_records_but_not_user_files(env):
    from app_files import find_app_records
    dl = env["home"] / "Downloads"
    dl.mkdir()
    (dl / "mine.txt").write_text("mine", encoding="utf-8")
    _make_install(dl / "FileHub-single-windows-x64")
    db = make_db(env)
    lid = db.add_location("Downloads", str(dl), "local")
    # 以前の版で登録されてしまった状態を作る（除外が無かった頃の索引）
    db.upsert_files(lid, [
        ("mine.txt", "mine.txt", "txt", "document", 4, 1.0),
        ("FileHub-single-windows-x64/file_hub.exe", "file_hub.exe", "exe", "program", 2, 1.0),
        ("FileHub-single-windows-x64/site-packages/httpcore/__init__.py", "__init__.py", "py", "code", 1, 1.0),
        ("Renamed/file_hub.exe", "file_hub.exe", "exe", "program", 9, 1.0),
    ], 1.0)
    ids = find_app_records(db.all_file_rows())
    assert len(ids) == 3  # 配布フォルダの2件と、名前を変えて残った実行ファイル1件
    db.delete_files(ids)
    assert [r["relpath"] for r in db.search({"include_missing": True}, limit=100)] == ["mine.txt"]


def test_tree_does_not_offer_app_folders(env):
    from scanner import ScanOptions, list_child_dirs
    home = env["home"]
    _make_install(home / "Downloads" / "FileHub-portable-linux-x64")
    (home / "Downloads" / "Pics").mkdir(parents=True)
    names = [os.path.basename(p) for p in list_child_dirs(str(home / "Downloads"), ScanOptions())]
    assert names == ["Pics"]


def test_app_folder_cannot_be_registered_by_path(env):
    from app_files import is_app_dir
    d = env["home"] / "Downloads" / "anything"
    _make_install(d)
    assert is_app_dir(str(d))
    # 登録画面の検査と同じ判定（ensure_location の先頭で使う）
    from app_files import is_build_name
    assert is_build_name("FileHub-single-windows-x64")
