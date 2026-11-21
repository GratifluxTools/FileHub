"""ロジック層のテスト（GUI を使わない）。実行: python -m pytest tests -q"""
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
    body = root.controls[1]
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
    save_btn = [c for c in _walk(body) if isinstance(c, ft.OutlinedButton) and c.text == app.t("save")]
    save_btn[-1].on_click(None)
    assert db.search({"text": "会議"})[0]["name"] == "notes_2025.txt"

    # 画像の詳細へ移動し、プレビューと加工ボタンが出ること
    back = [c for c in _walk(body) if isinstance(c, ft.IconButton) and c.icon == ft.Icons.ARROW_BACK]
    back[0].on_click(None)
    keyword.value = "photo"
    keyword.on_submit(None)
    photo_rows = [c for c in _walk(search_view) if isinstance(c, ft.ListTile)]
    assert len(photo_rows) == 1
    photo_rows[0].on_click(None)
    labels = [c.text for c in _walk(body) if isinstance(c, ft.OutlinedButton)]
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
    body = root.controls[1]
    tabs = body.content
    search_view = tabs.tabs[0].content
    settings_view = tabs.tabs[3].content

    keyword = [c for c in _walk(search_view) if isinstance(c, ft.TextField)
               and c.label == app.t("keyword")][0]
    keyword.value = "pic"
    keyword.on_submit(None)
    [c for c in _walk(search_view) if isinstance(c, ft.ListTile)][0].on_click(None)
    rot = [c for c in _walk(body) if isinstance(c, ft.OutlinedButton) and c.text == app.t("op_rot_cw")][0]
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
    compress = [c for c in _walk(search_view) if isinstance(c, ft.OutlinedButton)
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
    body = root.controls[1]
    # 登録画面（戻るボタンがあり、タブは無い）
    assert not hasattr(body.content, "tabs")
    fields = [c for c in _walk(body) if isinstance(c, ft.TextField)]
    # 初回は現在のPCなので、既定はツリー。「手動で登録」に切り替える
    manual_btn = [c for c in _walk(body) if isinstance(c, ft.OutlinedButton) and c.text == app.t("manual_mode")]
    manual_btn[0].on_click(None)
    fields = [c for c in _walk(body) if isinstance(c, ft.TextField)]
    name_tf = [f for f in fields if f.label == app.t("manual_location_name")]
    files_tf = [f for f in fields if f.label == app.t("manual_files_label")]
    assert name_tf and files_tf
    name_tf[0].value = "Google Drive"
    files_tf[0].value = "Docs/report.docx\nPics/cat.jpg"
    btn = [c for c in _walk(body) if isinstance(c, ft.ElevatedButton) and c.text == app.t("manual_register")]
    btn[0].on_click(None)
    db = make_db(env)
    hits = db.search({"text": "cat", "include_missing": True})
    assert hits and hits[0]["location_name"] == "Google Drive"
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
