import csv
import os
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime

import flet as ft

from app_version import __version__
from archive_utils import create_zip, extract_archive, list_archive
from categories import (ARCHIVE_READ, CATEGORY_ORDER, IMAGE_EDITABLE, IMAGE_PREVIEW,
                        MEDIA_CATEGORIES, OFFICE_TEXT, TEXT_EDITABLE)
from config import EDITION, Config, data_dir
from db import Database
from device import DEVICE_TYPES, LOCAL_TYPES, current_fingerprint, current_name, current_type
from folder_tree import FolderTreeView, minimal
from i18n import set_language, t
from image_tools import apply_op, preview_path
from media_tags import MEDIA_FIELDS, WRITABLE_EXTS, read_tags, write_tags
from opener import open_path, reveal
from paths import home_dir, is_inside_home
from scanner import (ScanOptions, detect_default_folders, detect_kind, index_abs,
                     list_child_dirs, parse_manual_lines, relocate_record, scan_location)
from single_instance import acquire as acquire_instance, activate_existing_window
from text_io import extract_office_text, read_text, write_text
from updater import REPO_URL, check_latest

try:
    from send2trash import send2trash
except ImportError:  # ごみ箱へ移せない環境では完全削除になる
    send2trash = None

GREY = ft.Colors.GREY
RED = ft.Colors.RED
MB = 1024 * 1024
SEARCH_LIMIT = 300
PROGRESS_INTERVAL = 0.4
CUR_FP = current_fingerprint()

CATEGORY_ICON = {
    "document": ft.Icons.DESCRIPTION, "data": ft.Icons.TABLE_CHART,
    "presentation": ft.Icons.SLIDESHOW, "image": ft.Icons.IMAGE,
    "audio": ft.Icons.AUDIOTRACK, "video": ft.Icons.MOVIE,
    "archive": ft.Icons.FOLDER_ZIP, "program": ft.Icons.APPS, "code": ft.Icons.CODE,
    "disk_image": ft.Icons.ALBUM, "config": ft.Icons.SETTINGS, "other": ft.Icons.INSERT_DRIVE_FILE,
}


# ---------- 小さな補助関数 ----------
def fmt_size(n):
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return str(n)


def fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "-"


def parse_date(text, end=False):
    ts = datetime.strptime(text.strip(), "%Y-%m-%d").timestamp()
    return ts + 86400 if end else ts


def unique_path(path):
    base, ext = os.path.splitext(path)
    candidate, n = path, 2
    while os.path.exists(candidate):
        candidate = f"{base} ({n}){ext}"
        n += 1
    return candidate


def archive_base(path):
    """圧縮ファイル名から拡張子を外したパス（展開先フォルダの名前にする）。"""
    folder, name = os.path.split(path)
    low = name.lower()
    for ext in (".tar.gz", ".tgz", ".tar", ".zip", ".7z", ".rar", ".gz"):
        if low.endswith(ext):
            name = name[: -len(ext)]
            break
    return os.path.join(folder, name or "extracted")


def device_title(name, fingerprint, account, dtype):
    """デバイスの表示名。このPCには「(このPC)」を先頭に付け、アカウントやメールを後ろに添える。"""
    is_here = bool(fingerprint) and fingerprint == CUR_FP
    text = f"({t('this_device')}) {name}" if is_here else name
    return f"{text} · {account or t('type_' + (dtype or 'other'))}"


def section(title, *controls):
    return ft.Container(
        padding=ft.padding.only(top=12),
        content=ft.Column([ft.Text(title, weight=ft.FontWeight.BOLD, size=15), *controls], spacing=8),
    )


def pill(text, on_x=None):
    row_controls = [ft.Text(text, size=12)]
    if on_x is not None:
        row_controls.append(ft.IconButton(icon=ft.Icons.CLOSE, icon_size=12, on_click=on_x))
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=8, vertical=2),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.BLUE),
        content=ft.Row(row_controls, spacing=0, tight=True),
    )


def card_border():
    return ft.border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE))


# ---------- メイン画面 ----------
def main(page: ft.Page):
    page.title = "File Hub" + (" (Portable)" if EDITION == "portable" else "")
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 10

    ddir = data_dir()
    cfg_path = os.path.join(ddir, "config.json")
    cfg = Config.load(cfg_path)
    set_language(cfg.language)
    db = Database(os.path.join(ddir, "index.db"))
    db.ensure_current_device(current_name(), current_type(), CUR_FP)
    cache_dir = os.path.join(ddir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    selected = set()
    scan_state = {"cancel": None}
    dir_callback = {"fn": None}
    save_callback = {"fn": None}

    def snack(msg):
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    def open_dialog(title, content, actions):
        page.dialog = ft.AlertDialog(modal=True, title=ft.Text(title), content=content, actions=actions)
        page.dialog.open = True
        page.update()

    def close_dialog(_=None):
        if page.dialog is not None:
            page.dialog.open = False
            page.update()

    def ask_text(title, label, initial, on_ok):
        tf = ft.TextField(label=label, value=initial, autofocus=True, width=420)

        def ok(_=None):
            value = (tf.value or "").strip()
            close_dialog()
            if value:
                on_ok(value)

        tf.on_submit = ok
        open_dialog(title, tf, [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("ok"), on_click=ok),
        ])

    def run_bg(work, busy_msg=None):
        """重い処理をバックグラウンドで行い、終わったら結果を表示して一覧を更新する。"""
        if busy_msg:
            snack(busy_msg)

        def worker():
            try:
                msg = work()
            except Exception as ex:  # noqa: BLE001 - 失敗理由をそのまま見せる
                msg = t("op_failed", ex=ex)

            def done():
                snack(msg)
                refresh_all()

            page.run_thread(done)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- ファイル選択（フォルダ・保存先） ----------
    def on_dir_result(e):
        fn = dir_callback["fn"]
        dir_callback["fn"] = None
        if fn and e.path:
            fn(e.path)

    def on_save_result(e):
        fn = save_callback["fn"]
        save_callback["fn"] = None
        if fn and e.path:
            fn(e.path)

    dir_picker = ft.FilePicker(on_result=on_dir_result)
    save_picker = ft.FilePicker(on_result=on_save_result)
    page.overlay.extend([dir_picker, save_picker])

    def pick_dir(fn):
        dir_callback["fn"] = fn
        dir_picker.get_directory_path(dialog_title=t("pick_folder"), initial_directory=home_dir())

    # ---------- 画面の切り替え ----------
    body = ft.Container(expand=True)

    def show_tabs(_=None):
        body.content = tabs
        page.update()

    def show_screen(title, controls):
        body.content = ft.Column(expand=True, controls=[
            ft.Row([ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip=t("back"), on_click=show_tabs),
                    ft.Text(title, size=18, weight=ft.FontWeight.BOLD)]),
            ft.Column(controls, scroll=ft.ScrollMode.AUTO, expand=True, spacing=6),
        ])
        page.update()

    # ---------- 検索 ----------
    f_text = ft.TextField(label=t("keyword"), hint_text=t("search_hint"), width=380,
                          on_submit=lambda _: run_search())
    # 絞り込み条件は dict で持ち、ダイアログを開くたびに部品を作り直す
    filt = {"cat": "", "ext": "", "loc": "", "tag": "", "min": "", "max": "",
            "from": "", "to": "", "sort": "name", "missing": False}
    filter_label = ft.Text(size=12, color=GREY)
    summary = ft.Text(size=13)
    sel_text = ft.Text(size=12, color=GREY)
    results = ft.ListView(expand=True, spacing=4)
    bulk_tag = ft.TextField(label=t("tag_name"), width=200)

    def filter_count():
        return sum(1 for k, v in filt.items() if k != "sort" and v not in ("", False, None))

    def update_filter_label():
        n = filter_count()
        filter_label.value = t("filters_active", n=n) if n else ""

    def parse_filter():
        try:
            flt = {
                "text": (f_text.value or "").strip(),
                "exts": [x.strip().lower().lstrip(".") for x in (filt["ext"] or "").split(",") if x.strip()],
                "sort": filt["sort"] or "name",
                "include_missing": bool(filt["missing"]),
            }
            if filt["cat"]:
                flt["categories"] = [filt["cat"]]
            if filt["loc"]:
                flt["location_id"] = int(filt["loc"])
            if filt["tag"]:
                flt["tags"] = [int(filt["tag"])]
            if (filt["min"] or "").strip():
                flt["min_size"] = int(float(filt["min"]) * MB)
            if (filt["max"] or "").strip():
                flt["max_size"] = int(float(filt["max"]) * MB)
            if (filt["from"] or "").strip():
                flt["mtime_from"] = parse_date(filt["from"])
            if (filt["to"] or "").strip():
                flt["mtime_to"] = parse_date(filt["to"], end=True)
        except ValueError:
            snack(t("invalid_input"))
            return None
        return flt

    def open_filters(_=None):
        locs = db.locations()
        tags = db.all_tags()
        loc_keys = {str(l["id"]) for l in locs}
        tag_keys = {str(tg["id"]) for tg in tags}
        f_cat = ft.Dropdown(label=t("category"), width=220, value=filt["cat"], options=(
            [ft.dropdown.Option(key="", text=t("all"))]
            + [ft.dropdown.Option(key=c, text=t("cat_" + c)) for c in CATEGORY_ORDER]))
        f_ext = ft.TextField(label=t("extensions"), hint_text="jpg, pdf", width=220, value=filt["ext"])
        f_loc = ft.Dropdown(label=t("location"), width=220,
                            value=filt["loc"] if filt["loc"] in loc_keys else "",
                            options=[ft.dropdown.Option(key="", text=t("all"))] + [
                                ft.dropdown.Option(key=str(l["id"]), text=l["name"]) for l in locs])
        f_tag = ft.Dropdown(label=t("tag"), width=220,
                            value=filt["tag"] if filt["tag"] in tag_keys else "",
                            options=[ft.dropdown.Option(key="", text=t("all"))] + [
                                ft.dropdown.Option(key=str(tg["id"]), text=tg["name"]) for tg in tags])
        f_min = ft.TextField(label=t("min_mb"), width=220, value=filt["min"])
        f_max = ft.TextField(label=t("max_mb"), width=220, value=filt["max"])
        f_from = ft.TextField(label=t("modified_from"), hint_text="2025-01-01", width=220, value=filt["from"])
        f_to = ft.TextField(label=t("modified_to"), hint_text="2025-12-31", width=220, value=filt["to"])
        f_sort = ft.Dropdown(label=t("sort"), width=220, value=filt["sort"], options=[
            ft.dropdown.Option(key="name", text=t("sort_name")),
            ft.dropdown.Option(key="mtime", text=t("sort_mtime")),
            ft.dropdown.Option(key="size", text=t("sort_size")),
            ft.dropdown.Option(key="path", text=t("sort_path")),
        ])
        f_missing = ft.Checkbox(label=t("include_missing"), value=filt["missing"])

        def apply(_=None):
            filt.update(cat=f_cat.value or "", ext=f_ext.value or "", loc=f_loc.value or "",
                        tag=f_tag.value or "", min=f_min.value or "", max=f_max.value or "",
                        **{"from": f_from.value or "", "to": f_to.value or ""},
                        sort=f_sort.value or "name", missing=bool(f_missing.value))
            close_dialog()
            update_filter_label()
            run_search()

        def reset(_=None):
            filt.update(cat="", ext="", loc="", tag="", min="", max="", **{"from": "", "to": ""},
                        sort="name", missing=False)
            close_dialog()
            update_filter_label()
            run_search()

        content = ft.Column([
            ft.Row([f_cat, f_ext], wrap=True), ft.Row([f_loc, f_tag], wrap=True),
            ft.Row([f_min, f_max], wrap=True), ft.Row([f_from, f_to], wrap=True),
            ft.Row([f_sort, f_missing], wrap=True),
        ], tight=True, scroll=ft.ScrollMode.AUTO, width=520, height=420)
        open_dialog(t("filters"), content, [
            ft.TextButton(t("filter_reset"), on_click=reset),
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("filter_apply"), on_click=apply),
        ])

    def update_selection_text():
        sel_text.value = t("selected_count", n=len(selected))

    def toggle_select(fid, on):
        if on:
            selected.add(fid)
        else:
            selected.discard(fid)
        update_selection_text()
        page.update()

    def file_row(r):
        fid = r["id"]
        title = r["name"] + (f"  [{t('missing_mark')}]" if r["missing"] else "")
        line2 = f"{fmt_size(r['size'])} · {fmt_time(r['mtime'])}"
        if r.get("tags"):
            line2 += f" · # {r['tags']}"
        where = f"{r['location_name']} / {r['relpath']}"
        return ft.ListTile(
            leading=ft.Row([
                ft.Checkbox(value=fid in selected, on_change=lambda e, i=fid: toggle_select(i, e.control.value)),
                ft.Icon(CATEGORY_ICON.get(r["category"], ft.Icons.INSERT_DRIVE_FILE)),
            ], tight=True, spacing=0),
            title=ft.Text(title, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            subtitle=ft.Text(f"{where}\n{line2}", size=12, color=GREY,
                             max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            on_click=lambda _, i=fid: show_detail(i),
        )

    def run_search(_=None):
        flt = parse_filter()
        if flt is None:
            return
        rows = db.search(flt, limit=SEARCH_LIMIT)
        stats = db.count(flt)
        if stats["n"] == 0:
            summary.value = t("no_match_check")
        else:
            summary.value = t("search_summary", n=stats["n"], m=stats["missing"])
            if stats["n"] > len(rows):
                summary.value += "  " + t("showing_first", n=len(rows))
        results.controls = [file_row(r) for r in rows] or [ft.Text(t("no_results"))]
        update_selection_text()
        page.update()

    def bulk_add_tag(_=None):
        name = (bulk_tag.value or "").strip()
        if not name or not selected:
            snack(t("nothing_selected"))
            return
        for fid in list(selected):
            db.add_tag(fid, name)
        bulk_tag.value = ""
        snack(t("tag_added", n=len(selected)))
        refresh_all()

    def bulk_clear_selection(_=None):
        selected.clear()
        run_search()

    def export_csv(_=None):
        flt = parse_filter()
        if flt is None:
            return
        rows = db.search(flt, limit=1000000)
        if not rows:
            snack(t("no_results"))
            return

        def write(path):
            if not path.lower().endswith(".csv"):
                path += ".csv"
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                    w = csv.writer(fh)
                    w.writerow(["name", "path", "location", "category", "ext", "size", "modified", "tags", "memo"])
                    for r in rows:
                        w.writerow([r["name"], r["path"], r["location_name"], r["category"], r["ext"],
                                    r["size"], fmt_time(r["mtime"]), r.get("tags") or "", r["memo"]])
                snack(t("exported", n=len(rows), path=path))
            except OSError as ex:
                snack(t("op_failed", ex=ex))

        save_callback["fn"] = write
        save_picker.save_file(file_name="file_hub_search.csv")

    search_view = ft.Column(expand=True, spacing=6, controls=[
        ft.Row([f_text,
                ft.ElevatedButton(t("search"), icon=ft.Icons.SEARCH, on_click=run_search),
                ft.OutlinedButton(t("filters"), icon=ft.Icons.FILTER_LIST, on_click=open_filters),
                filter_label], wrap=True, spacing=8),
        ft.Row([
            ft.OutlinedButton(t("export_csv"), icon=ft.Icons.DOWNLOAD, on_click=export_csv),
        ], wrap=True),
        summary,
        ft.Row([sel_text, bulk_tag, ft.OutlinedButton(t("add_tag_selected"), on_click=bulk_add_tag),
                ft.OutlinedButton(t("compress_selected"), icon=ft.Icons.FOLDER_ZIP,
                                  on_click=lambda _: compress_ids(list(selected))),
                ft.TextButton(t("clear_selection"), on_click=bulk_clear_selection)], wrap=True),
        ft.Container(content=results, expand=True),
    ])

    def search_location(lid):
        filt["loc"] = str(lid)
        tabs.selected_index = 0
        update_filter_label()
        show_tabs()
        run_search()

    def search_tag(tid):
        filt["tag"] = str(tid)
        tabs.selected_index = 0
        update_filter_label()
        show_tabs()
        run_search()

    # ---------- 圧縮 ----------
    def compress_ids(ids):
        recs = [db.get_file(i) for i in ids]
        recs = [r for r in recs if r and os.path.exists(r["path"])]
        if not recs:
            snack(t("nothing_to_compress"))
            return
        folder = os.path.dirname(recs[0]["path"])
        dest = unique_path(os.path.join(folder, f"archive-{datetime.now():%Y%m%d-%H%M%S}.zip"))
        sources, used = [], set()
        for r in recs:
            arc, n = r["name"], 2
            stem, ext = os.path.splitext(r["name"])
            while arc in used:
                arc = f"{stem} ({n}){ext}"
                n += 1
            used.add(arc)
            sources.append((r["path"], arc))

        def work():
            create_zip(sources, dest)
            index_abs(db, dest)
            return t("compressed", name=os.path.basename(dest))

        run_bg(work, t("compressing"))

    # ---------- 詳細画面 ----------
    def show_detail(fid, _=None):
        rec = db.get_file(fid)
        if rec is None:
            snack(t("not_found"))
            return
        path = rec["path"]
        manual = rec["location_mode"] == "manual"
        exists = (not manual) and os.path.exists(path)
        ext, cat = rec["ext"], rec["category"]
        where = (f"{t('manual_entry')}: {rec['relpath']}" if manual else path)

        info = ft.Column(spacing=2, controls=[
            ft.Text(rec["name"], size=20, weight=ft.FontWeight.BOLD, selectable=True),
            ft.Text(where, size=12, color=GREY, selectable=True),
            ft.Text(f"{t('device_line')}: " + device_title(
                rec["device_name"] or "-", rec["device_fp"], rec["device_account"], rec["device_dtype"])),
            ft.Text(f"{t('location')}: {rec['location_name']}"),
            ft.Text(f"{t('category')}: {t('cat_' + cat)}    {t('extension')}: .{ext or '-'}"),
            ft.Text(f"{t('size')}: {fmt_size(rec['size'])}    {t('modified')}: {fmt_time(rec['mtime'])}"),
            ft.Text(t("manual_file_note") if manual else
                    (t("file_present") if exists else t("file_missing_note")),
                    color=None if exists else RED),
        ])

        def copy_path(_):
            page.set_clipboard(path)
            snack(t("copied"))

        def run_open(_):
            try:
                open_path(path)
            except OSError as ex:
                snack(t("op_failed", ex=ex))

        def run_reveal(_):
            try:
                reveal(path)
            except OSError as ex:
                snack(t("op_failed", ex=ex))

        actions = ft.Row(wrap=True, spacing=6, controls=[
            ft.ElevatedButton(t("open"), icon=ft.Icons.OPEN_IN_NEW, disabled=not exists, on_click=run_open),
            ft.OutlinedButton(t("reveal"), icon=ft.Icons.FOLDER_OPEN, disabled=not exists, on_click=run_reveal),
            ft.OutlinedButton(t("copy_path"), icon=ft.Icons.CONTENT_COPY, on_click=copy_path),
            ft.OutlinedButton(t("rename"), icon=ft.Icons.EDIT, disabled=not exists,
                              on_click=lambda _: rename_action(rec)),
            ft.OutlinedButton(t("move"), icon=ft.Icons.DRIVE_FILE_MOVE, disabled=not exists,
                              on_click=lambda _: move_action(rec)),
            ft.OutlinedButton(t("compress"), icon=ft.Icons.FOLDER_ZIP, disabled=not exists,
                              on_click=lambda _: compress_ids([fid])),
            ft.OutlinedButton(t("remove_index"), icon=ft.Icons.LINK_OFF,
                              on_click=lambda _: remove_from_index(rec)),
            ft.OutlinedButton(t("delete_file"), icon=ft.Icons.DELETE_OUTLINE, disabled=not exists,
                              style=ft.ButtonStyle(color=RED), on_click=lambda _: delete_action(rec)),
        ])

        parts = [info, actions]
        if exists:
            parts.append(preview_section(rec))
        if exists and ext in IMAGE_EDITABLE:
            parts.append(image_section(rec))
        if exists and ext in ARCHIVE_READ:
            parts.append(archive_section(rec))
        if cat in MEDIA_CATEGORIES:
            parts.append(media_section(rec, exists))
        parts += [tags_section(rec), links_section(rec), memo_section(rec)]
        show_screen(t("details"), parts)

    def preview_section(rec):
        path, ext = rec["path"], rec["ext"]
        limit = max(1, cfg.preview_mb) * MB
        if ext in IMAGE_PREVIEW:
            try:
                src = preview_path(path, cache_dir)
            except Exception as ex:  # noqa: BLE001
                return section(t("preview"), ft.Text(t("preview_failed", ex=ex)))
            return section(t("preview"), ft.Image(src=src, height=360, fit=ft.ImageFit.CONTAIN, border_radius=8))
        if ext in TEXT_EDITABLE:
            try:
                text, enc, truncated = read_text(path, limit)
            except OSError as ex:
                return section(t("preview"), ft.Text(t("preview_failed", ex=ex)))
            field = ft.TextField(value=text, multiline=True, min_lines=8, max_lines=20,
                                 text_size=13, read_only=truncated)

            def save(_):
                try:
                    write_text(path, field.value or "", enc)
                except UnicodeEncodeError:
                    snack(t("save_encoding_failed", enc=enc))
                    return
                except OSError as ex:
                    snack(t("save_failed", ex=ex))
                    return
                index_abs(db, path)
                snack(t("saved"))
                show_detail(rec["id"])

            controls = [field]
            if truncated:
                controls.append(ft.Text(t("too_large_readonly"), size=12, color=GREY))
            else:
                controls.append(ft.ElevatedButton(t("save"), icon=ft.Icons.SAVE, on_click=save))
            return section(t("preview_edit"), *controls)
        if ext in OFFICE_TEXT:
            try:
                text = extract_office_text(path, ext)
            except Exception as ex:  # noqa: BLE001
                return section(t("preview"), ft.Text(t("preview_failed", ex=ex)))
            if not text:
                return section(t("preview"), ft.Text(t("no_text_preview")))
            return section(t("preview"), ft.Container(
                height=300, padding=8, border=card_border(), border_radius=8,
                content=ft.Column([ft.Text(text, selectable=True, size=13)], scroll=ft.ScrollMode.AUTO)))
        return section(t("preview"), ft.Text(t("no_preview"), color=GREY))

    def image_section(rec):
        path, ext = rec["path"], rec["ext"]
        overwrite = ft.Switch(label=t("overwrite_original"), value=False)
        max_px = ft.TextField(label=t("max_px"), value="1280", width=120)

        def run(op, **kw):
            tmp = None
            try:
                if overwrite.value:
                    tmp = path + ".tmp." + ext
                    apply_op(path, tmp, op, **kw)
                    os.replace(tmp, path)
                    result = path
                else:
                    base = os.path.splitext(path)[0]
                    result = unique_path(f"{base}_edited.{ext}")
                    apply_op(path, result, op, **kw)
            except Exception as ex:  # noqa: BLE001
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
                snack(t("op_failed", ex=ex))
                return
            fid = index_abs(db, result)
            snack(t("image_saved"))
            show_detail(fid or rec["id"])

        def run_resize(_):
            try:
                n = int(max_px.value or 0)
            except ValueError:
                snack(t("invalid_input"))
                return
            if n < 16:
                snack(t("invalid_input"))
                return
            run("resize", max_side=n)

        buttons = [ft.OutlinedButton(t("op_" + op), on_click=lambda _, o=op: run(o))
                   for op in ("rot_ccw", "rot_cw", "rot_180", "flip_h", "flip_v", "gray")]
        buttons.append(ft.OutlinedButton(t("op_resize"), on_click=run_resize))
        return section(t("image_edit"), ft.Row(buttons, wrap=True), ft.Row([max_px]), overwrite,
                       ft.Text(t("image_edit_note"), size=12, color=GREY))

    def archive_section(rec):
        path = rec["path"]

        def show_list(_):
            try:
                names = list_archive(path)
            except Exception as ex:  # noqa: BLE001 - rar 等はライブラリ固有の例外を出す
                snack(t("archive_failed", ex=ex))
                return
            items = [ft.Text(n, size=12, selectable=True) for n in names[:300]]
            if len(names) > 300:
                items.append(ft.Text(t("and_more", n=len(names) - 300), size=12, color=GREY))
            open_dialog(t("archive_contents"),
                        ft.Container(width=560, height=380,
                                     content=ft.Column(items, scroll=ft.ScrollMode.AUTO)),
                        [ft.TextButton(t("close"), on_click=close_dialog)])

        def extract(_):
            dest = unique_path(archive_base(path))

            def work():
                count = extract_archive(path, dest)
                found = db.find_location_for(dest)
                if found:
                    loc, _rel = found
                    scan_location(db, loc, make_scan_options(), threading.Event(), start=dest)
                return t("extracted", n=count)

            run_bg(work, t("extracting"))

        return section(t("archive"),
                       ft.Row([ft.OutlinedButton(t("archive_contents"), icon=ft.Icons.LIST, on_click=show_list),
                               ft.OutlinedButton(t("extract_here"), icon=ft.Icons.UNARCHIVE, on_click=extract)],
                              wrap=True))

    def media_section(rec, exists):
        fid, path, ext = rec["id"], rec["path"], rec["ext"]
        writable = exists and ext in WRITABLE_EXTS
        current = dict(rec["media"] or {})
        if not current and writable:
            current = read_tags(path)
        field_map = {}
        controls = []
        for key in MEDIA_FIELDS:
            tf = ft.TextField(label=t("field_" + key), value=str(current.get(key, "") or ""), width=240)
            field_map[key] = tf
            controls.append(tf)

        def save(_):
            data = {k: (tf.value or "").strip() for k, tf in field_map.items()}
            unsupported = []
            if writable:
                try:
                    unsupported = write_tags(path, data)
                    index_abs(db, path)
                except Exception as ex:  # noqa: BLE001
                    snack(t("media_write_failed", ex=ex))
                    return
            db.set_media(fid, data)
            if unsupported:
                names = ", ".join(t("field_" + k) for k in unsupported)
                snack(t("media_partial", fields=names))
            else:
                snack(t("saved"))
            show_detail(fid)

        note = t("media_write_note") if writable else t("media_db_note")
        return section(t("media_info"), ft.Row(controls, wrap=True, spacing=8),
                       ft.Text(note, size=12, color=GREY),
                       ft.ElevatedButton(t("save"), icon=ft.Icons.SAVE, on_click=save))

    def tags_section(rec):
        fid = rec["id"]

        def remove(tid):
            db.remove_tag(fid, tid)
            show_detail(fid)

        chips = [pill(tg["name"], on_x=lambda _, i=tg["id"]: remove(i)) for tg in db.tags_of(fid)]
        tag_in = ft.TextField(label=t("add_tag"), width=240)

        def add_now(_=None):
            name = (tag_in.value or "").strip()
            if name:
                db.add_tag(fid, name)
                show_detail(fid)

        tag_in.on_submit = add_now
        return section(t("tags"),
                       ft.Row(chips, wrap=True, spacing=6) if chips else ft.Text(t("no_tags"), color=GREY),
                       ft.Row([tag_in, ft.OutlinedButton(t("add"), on_click=add_now)]))

    def links_section(rec):
        fid = rec["id"]

        def unlink(other):
            db.unlink(fid, other)
            show_detail(fid)

        rows = [ft.Row([
            ft.TextButton(l["name"], on_click=lambda _, i=l["id"]: show_detail(i)),
            ft.IconButton(icon=ft.Icons.LINK_OFF, tooltip=t("remove_link"),
                          on_click=lambda _, i=l["id"]: unlink(i)),
        ], spacing=0) for l in db.linked_files(fid)]
        return section(t("links"),
                       *(rows or [ft.Text(t("no_links"), color=GREY)]),
                       ft.OutlinedButton(t("add_link"), icon=ft.Icons.ADD_LINK,
                                         on_click=lambda _: open_link_picker(fid)))

    def open_link_picker(fid):
        q = ft.TextField(label=t("keyword"), autofocus=True, expand=True)
        out = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, height=300)

        def pick(other):
            db.link(fid, other)
            close_dialog()
            show_detail(fid)

        def search(_=None):
            txt = (q.value or "").strip()
            rows = db.search({"text": txt, "include_missing": False, "sort": "name"}, limit=30) if txt else []
            out.controls = [
                ft.TextButton(f"{r['name']}  —  {r['location_name']} / {r['relpath']}",
                              on_click=lambda _, i=r["id"]: pick(i))
                for r in rows if r["id"] != fid
            ] or [ft.Text(t("no_results"))]
            page.update()

        q.on_submit = search
        open_dialog(t("add_link"),
                    ft.Container(width=560, content=ft.Column([q, out], tight=True)),
                    [ft.TextButton(t("close"), on_click=close_dialog)])

    def memo_section(rec):
        fid = rec["id"]
        memo = ft.TextField(value=rec["memo"], multiline=True, min_lines=2, max_lines=8)

        def save(_):
            db.set_memo(fid, memo.value or "")
            snack(t("saved"))

        return section(t("memo"), memo, ft.OutlinedButton(t("save"), icon=ft.Icons.SAVE, on_click=save))

    def rename_action(rec):
        def do(new_name):
            if any(c in new_name for c in '/\\') or new_name in (".", ".."):
                snack(t("name_invalid"))
                return
            new_path = os.path.join(os.path.dirname(rec["path"]), new_name)
            if os.path.exists(new_path):
                snack(t("already_exists"))
                return
            try:
                os.rename(rec["path"], new_path)
            except OSError as ex:
                snack(t("op_failed", ex=ex))
                return
            relocate_record(db, rec["id"], new_path)
            snack(t("renamed"))
            show_detail(rec["id"])

        ask_text(t("rename"), t("name"), rec["name"], do)

    def move_action(rec):
        def got(dest_dir):
            new_path = os.path.join(dest_dir, rec["name"])
            if os.path.exists(new_path):
                snack(t("already_exists"))
                return
            try:
                shutil.move(rec["path"], new_path)
            except OSError as ex:
                snack(t("op_failed", ex=ex))
                return
            kept = relocate_record(db, rec["id"], new_path)
            if kept is None:
                snack(t("moved_out_removed"))
                show_tabs()
                refresh_all()
            else:
                snack(t("moved"))
                show_detail(rec["id"])

        pick_dir(got)

    def delete_action(rec):
        def do(_):
            close_dialog()
            try:
                if cfg.use_trash and send2trash is not None:
                    send2trash(rec["path"])
                else:
                    os.remove(rec["path"])
            except Exception as ex:  # noqa: BLE001
                snack(t("delete_failed", ex=ex))
                return
            db.delete_file(rec["id"])
            selected.discard(rec["id"])
            show_tabs()
            refresh_all()
            snack(t("deleted"))

        open_dialog(t("confirm"), ft.Text(t("delete_confirm", name=rec["name"])), [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("delete"), on_click=do),
        ])

    def remove_from_index(rec):
        db.delete_file(rec["id"])
        selected.discard(rec["id"])
        show_tabs()
        refresh_all()
        snack(t("removed_from_index"))

    # ---------- スキャン・場所の共通処理 ----------
    def make_scan_options():
        return ScanOptions(exclude_names=set(cfg.exclude_names), include_hidden=cfg.include_hidden,
                           exclude_appdata=cfg.exclude_appdata, skip_paths=[ddir])

    def start_scan(loc_ids):
        if not loc_ids:
            snack(t("locations_empty"))
            return
        if scan_state["cancel"] is not None:
            snack(t("scan_running"))
            return
        cancel_ev = threading.Event()
        scan_state["cancel"] = cancel_ev
        status = ft.Text(t("scan_starting"))

        def cancel(_):
            cancel_ev.set()
            status.value = t("scan_cancelling")
            page.update()

        open_dialog(t("scanning"), ft.Column([status, ft.ProgressBar(width=420)], tight=True),
                    [ft.TextButton(t("cancel"), on_click=cancel)])
        opts = make_scan_options()

        def set_status(name, n):
            status.value = t("scan_progress", name=name, n=n)
            page.update()

        def worker():
            total, cancelled = 0, False
            for lid in loc_ids:
                loc = db.location(lid)
                if loc is None or loc["mode"] != "scan" or not os.path.isdir(loc["root"]):
                    continue
                last = [0.0]

                def progress(n, _current, name=loc["name"]):
                    now = time.time()
                    if now - last[0] < PROGRESS_INTERVAL:
                        return
                    last[0] = now
                    page.run_thread(lambda nm=name, c=n: set_status(nm, c))

                result = scan_location(db, loc, opts, cancel_ev, on_progress=progress)
                if result is None:
                    cancelled = True
                    break
                total += result
            scan_state["cancel"] = None

            def done():
                close_dialog()
                snack(t("scan_cancelled") if cancelled else t("scan_done", n=total))
                refresh_all()

            page.run_thread(done)

        threading.Thread(target=worker, daemon=True).start()

    def ensure_location(path, device_id, kind=None):
        """フォルダを走査対象の場所として登録する。既存の場所と重なる場合は登録せず None を返す。"""
        existing = db.find_location_by_root(path)
        if existing:
            return existing["id"]
        if not is_inside_home(path):
            snack(t("outside_home"))
            return None
        if db.find_overlap(path):
            snack(t("overlap"))
            return None
        name = os.path.basename(os.path.normpath(path)) or path
        return db.add_location(name, path, kind or detect_kind(path), device_id, "scan")

    def relink_location(lid):
        def got(path):
            if not is_inside_home(path):
                snack(t("outside_home"))
                return
            if db.find_overlap(path, exclude_id=lid):
                snack(t("overlap"))
                return
            db.update_location(lid, root=path)
            snack(t("relinked"))
            refresh_all()

        pick_dir(got)

    def rename_location(loc):
        ask_text(t("rename"), t("name"), loc["name"],
                 lambda name: (db.update_location(loc["id"], name=name), refresh_all()))

    def delete_location(lid):
        loc = db.location(lid)
        if loc is None:
            return

        def do(_):
            close_dialog()
            db.delete_location(lid)
            selected.clear()
            refresh_all()
            snack(t("location_deleted"))

        open_dialog(t("confirm"), ft.Text(t("delete_location_confirm", name=loc["name"])), [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("delete"), on_click=do),
        ])

    def add_manual_files_dialog(lid):
        files_tf = ft.TextField(label=t("manual_files_label"), hint_text=t("manual_files_hint"),
                                multiline=True, min_lines=6, max_lines=14, width=520)

        def ok(_):
            rows = parse_manual_lines(files_tf.value)
            close_dialog()
            if rows:
                db.upsert_files(lid, rows, time.time())
            snack(t("manual_added", n=len(rows)))
            refresh_all()

        open_dialog(t("add_files"), files_tf, [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("save"), on_click=ok),
        ])

    def loc_card(loc):
        manual = loc["mode"] == "manual"
        exists = manual or os.path.isdir(loc["root"])
        buttons = []
        if manual:
            buttons.append(ft.OutlinedButton(t("add_files"), icon=ft.Icons.PLAYLIST_ADD,
                                             on_click=lambda _, i=loc["id"]: add_manual_files_dialog(i)))
        else:
            buttons += [
                ft.OutlinedButton(t("scan"), icon=ft.Icons.REFRESH, on_click=lambda _, i=loc["id"]: start_scan([i])),
                ft.OutlinedButton(t("relink"), icon=ft.Icons.LINK, on_click=lambda _, i=loc["id"]: relink_location(i)),
            ]
        buttons += [
            ft.OutlinedButton(t("show_files"), icon=ft.Icons.SEARCH, on_click=lambda _, i=loc["id"]: search_location(i)),
            ft.OutlinedButton(t("rename"), icon=ft.Icons.EDIT, on_click=lambda _, l=loc: rename_location(l)),
            ft.OutlinedButton(t("delete"), icon=ft.Icons.DELETE_OUTLINE,
                              on_click=lambda _, i=loc["id"]: delete_location(i)),
        ]
        note = t("manual_entry") if manual else loc["root"]
        stats = t("loc_stats", n=loc["total"], m=loc["missing"])
        if not exists:
            stats += "  " + t("root_not_found")
        return ft.Container(padding=10, border_radius=8, border=card_border(), content=ft.Column(spacing=4, controls=[
            ft.Text(loc["name"], weight=ft.FontWeight.BOLD),
            ft.Text(note, size=12, selectable=True, color=None if exists else RED),
            ft.Text(stats, size=12, color=GREY),
            ft.Row(wrap=True, spacing=6, controls=buttons),
        ]))

    # ---------- デバイス ----------
    def device_form(title, name, account, dtype, type_editable, on_ok):
        name_tf = ft.TextField(label=t("device_name"), value=name, width=420)
        acc_tf = ft.TextField(label=t("account"), value=account, width=420)
        type_dd = ft.Dropdown(label=t("device_type"), value=dtype, width=420, disabled=not type_editable,
                              options=[ft.dropdown.Option(key=x, text=t("type_" + x)) for x in DEVICE_TYPES])

        def ok(_):
            if not (name_tf.value or "").strip():
                snack(t("invalid_input"))
                return
            close_dialog()
            on_ok((name_tf.value or "").strip(), (acc_tf.value or "").strip(), type_dd.value or "other")

        open_dialog(title, ft.Column([type_dd, name_tf, acc_tf], tight=True, width=440), [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("save"), on_click=ok),
        ])

    def new_device_dialog():
        def on_ok(name, account, dtype):
            db.add_device(name, dtype, account)
            refresh_all()

        device_form(t("add_device"), "", "", "windows", True, on_ok)

    def edit_device(d):
        def on_ok(name, account, _dtype):
            db.update_device(d["id"], name, account)
            refresh_all()

        device_form(t("edit_device"), d["name"], d["account"], d["dtype"], False, on_ok)

    def delete_device(d):
        if d["fingerprint"] == CUR_FP:
            snack(t("cannot_delete_current"))
            return

        def do(_):
            close_dialog()
            db.delete_device(d["id"])
            selected.clear()
            refresh_all()
            snack(t("device_deleted"))

        open_dialog(t("confirm"), ft.Text(t("delete_device_confirm", name=d["name"])), [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("delete"), on_click=do),
        ])

    # ---------- 登録画面 ----------
    reg_state = {"device": None, "sel": set(), "mode": "tree"}
    reg_host = ft.Column(spacing=8)

    def open_registration(defaults=False):
        reg_state["device"] = db.ensure_current_device(current_name(), current_type(), CUR_FP)
        reg_state["mode"] = "tree"
        if defaults:
            registered = {norm_key(l["root"]) for l in db.locations() if l["mode"] == "scan"}
            reg_state["sel"] = {d["path"] for d in detect_default_folders(home_dir())
                                if norm_key(d["path"]) not in registered}
        else:
            reg_state["sel"] = set()
        build_registration()
        show_screen(t("register"), [reg_host])

    def norm_key(path):
        return os.path.normcase(os.path.abspath(path))

    def build_registration():
        devs = db.devices()
        devs = sorted(devs, key=lambda d: d["fingerprint"] != CUR_FP)
        dev_id = reg_state["device"]
        dev = db.device(dev_id) if dev_id else None
        is_here = bool(dev and dev["fingerprint"] == CUR_FP)
        if not is_here:
            reg_state["mode"] = "manual"

        def on_dev(e):
            reg_state["device"] = int(e.control.value)
            build_registration()

        dropdown = ft.Dropdown(
            label=t("device"), width=520, value=str(dev_id) if dev else None, on_change=on_dev,
            options=[ft.dropdown.Option(key=str(d["id"]), text=device_title(
                d["name"], d["fingerprint"], d["account"], d["dtype"])) for d in devs])
        controls = [ft.Row([dropdown, ft.OutlinedButton(t("add_device"), icon=ft.Icons.ADD,
                                                         on_click=lambda _: new_device_dialog())], wrap=True)]
        if is_here:
            def set_mode(m):
                reg_state["mode"] = m
                build_registration()

            controls.append(ft.Row([
                ft.OutlinedButton(t("tree_mode"), icon=ft.Icons.ACCOUNT_TREE,
                                  on_click=lambda _: set_mode("tree")),
                ft.OutlinedButton(t("manual_mode"), icon=ft.Icons.EDIT_NOTE,
                                  on_click=lambda _: set_mode("manual")),
            ], wrap=True))
            if reg_state["mode"] == "tree":
                controls.append(tree_panel())
            else:
                controls.append(manual_panel(dev_id, True))
        else:
            controls.append(ft.Text(t("manual_note"), size=12, color=GREY))
            controls.append(manual_panel(dev_id, False))
        reg_host.controls = controls
        page.update()

    def tree_panel():
        opts = make_scan_options()
        count_text = ft.Text(t("selected_count", n=len(reg_state["sel"])))

        def changed():
            count_text.value = t("selected_count", n=len(reg_state["sel"]))
            page.update()

        tree = FolderTreeView(home_dir(), lambda p: list_child_dirs(p, opts), reg_state, changed,
                              empty_text=t("no_subfolders"), page=page)

        def hidden_changed(e):
            cfg.include_hidden = bool(e.control.value)
            cfg.save(cfg_path)
            build_registration()

        def appdata_changed(e):
            cfg.exclude_appdata = bool(e.control.value)
            cfg.save(cfg_path)
            build_registration()

        def register_tree(_):
            paths = minimal(reg_state["sel"])
            if not paths:
                snack(t("no_folder_selected"))
                return
            ids = []
            for p in paths:
                lid = ensure_location(p, reg_state["device"])
                if lid is not None:
                    ids.append(lid)
            reg_state["sel"] = set()
            show_tabs()
            refresh_all()
            start_scan(ids)

        return ft.Column([
            ft.Text(t("tree_help"), size=12, color=GREY),
            ft.Container(height=340, border=card_border(), border_radius=8, padding=6, content=tree.container),
            ft.Row([count_text,
                    ft.Switch(label=t("include_hidden"), value=cfg.include_hidden, on_change=hidden_changed),
                    ft.Switch(label=t("exclude_appdata"), value=cfg.exclude_appdata, on_change=appdata_changed)],
                   wrap=True),
            ft.ElevatedButton(t("register_selected"), icon=ft.Icons.CHECK, on_click=register_tree),
        ], spacing=8)

    def manual_panel(dev_id, optional):
        name_tf = ft.TextField(label=t("manual_location_name"), width=420)
        files_tf = ft.TextField(label=t("manual_files_label"), hint_text=t("manual_files_hint"),
                                multiline=True, min_lines=6, max_lines=14, width=520)

        def register(_):
            name = (name_tf.value or "").strip()
            if not name:
                snack(t("invalid_input"))
                return
            rows = parse_manual_lines(files_tf.value)
            loc = db.add_location(name, f"manual://{uuid.uuid4().hex}", "manual", dev_id, "manual")
            if rows:
                db.upsert_files(loc, rows, time.time())
            name_tf.value = ""
            files_tf.value = ""
            snack(t("manual_added", n=len(rows)))
            show_tabs()
            refresh_all()

        return ft.Column([
            ft.Text(t("manual_note_optional") if optional else t("manual_note"), size=12, color=GREY),
            name_tf, files_tf,
            ft.ElevatedButton(t("manual_register"), icon=ft.Icons.SAVE, on_click=register),
        ], spacing=8)

    # ---------- 場所の一覧 ----------
    loc_warn = ft.Text(t("relink_hint"), color=RED, visible=False)
    loc_list = ft.Column(spacing=10)

    def refresh_locations():
        devs = db.devices()
        locs = db.locations()
        blocks = []
        for d in sorted(devs, key=lambda x: x["fingerprint"] != CUR_FP):
            mine = [l for l in locs if l["device_id"] == d["id"]]
            header = ft.Row([
                ft.Icon(ft.Icons.COMPUTER if d["dtype"] in LOCAL_TYPES else ft.Icons.CLOUD),
                ft.Text(device_title(d["name"], d["fingerprint"], d["account"], d["dtype"]),
                        weight=ft.FontWeight.BOLD, expand=True),
                ft.IconButton(icon=ft.Icons.EDIT, tooltip=t("edit_device"),
                              on_click=lambda _, dd=d: edit_device(dd)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip=t("delete_device"),
                              on_click=lambda _, dd=d: delete_device(dd)),
            ])
            cards = [loc_card(l) for l in mine] or [ft.Text(t("no_locations_on_device"), size=12, color=GREY)]
            blocks.append(ft.Container(padding=10, border_radius=8, border=card_border(),
                                       content=ft.Column([header, *cards], spacing=8)))
        loc_list.controls = blocks or [ft.Text(t("locations_empty"))]
        loc_warn.visible = any(l["mode"] == "scan" and not os.path.isdir(l["root"]) for l in locs)

    locations_view = ft.Column(expand=True, spacing=8, controls=[
        ft.Row([
            ft.ElevatedButton(t("register"), icon=ft.Icons.ADD, on_click=lambda _: open_registration(False)),
            ft.OutlinedButton(t("add_device"), icon=ft.Icons.DEVICES, on_click=lambda _: new_device_dialog()),
            ft.OutlinedButton(t("rescan_all"), icon=ft.Icons.SYNC,
                              on_click=lambda _: start_scan([l["id"] for l in db.locations() if l["mode"] == "scan"])),
        ], wrap=True),
        ft.Text(t("location_help"), size=12, color=GREY),
        loc_warn,
        ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, controls=[loc_list]),
    ])

    # ---------- タグ ----------
    tags_col = ft.Column(spacing=4)

    def rename_tag(tg):
        def do(name):
            try:
                db.rename_tag(tg["id"], name)
            except sqlite3.IntegrityError:
                snack(t("tag_exists"))
                return
            refresh_all()

        ask_text(t("rename"), t("tag_name"), tg["name"], do)

    def delete_tag(tid):
        db.delete_tag(tid)
        refresh_all()

    def refresh_tags():
        rows = db.all_tags()
        tags_col.controls = [
            ft.Row([
                ft.Text(tg["name"], expand=True),
                ft.Text(t("n_files", n=tg["n"]), size=12, color=GREY),
                ft.IconButton(icon=ft.Icons.SEARCH, tooltip=t("search_tag"),
                              on_click=lambda _, i=tg["id"]: search_tag(i)),
                ft.IconButton(icon=ft.Icons.EDIT, tooltip=t("rename"),
                              on_click=lambda _, g=tg: rename_tag(g)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip=t("delete"),
                              on_click=lambda _, i=tg["id"]: delete_tag(i)),
            ]) for tg in rows
        ] or [ft.Text(t("no_tags"))]

    tags_view = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, controls=[
        ft.Text(t("tags_help"), size=12, color=GREY), tags_col,
    ])

    # ---------- 設定 ----------
    s_lang = ft.Dropdown(label=t("set_language"), value=cfg.language, width=200, options=[
        ft.dropdown.Option(key="en", text="English"), ft.dropdown.Option(key="ja", text="日本語")])
    s_preview = ft.TextField(label=t("set_preview_mb"), value=str(cfg.preview_mb), width=220)
    s_exclude = ft.TextField(label=t("set_exclude"), value=", ".join(cfg.exclude_names), width=560)
    s_hidden = ft.Switch(label=t("include_hidden"), value=cfg.include_hidden)
    s_appdata = ft.Switch(label=t("exclude_appdata"), value=cfg.exclude_appdata)
    s_trash = ft.Switch(label=t("use_trash"), value=cfg.use_trash and send2trash is not None,
                        disabled=send2trash is None)

    def save_settings(_):
        try:
            preview_mb = min(1024, max(1, int(s_preview.value or 100)))
        except ValueError:
            snack(t("invalid_input"))
            return
        lang_changed = (s_lang.value or "en") != cfg.language
        cfg.language = s_lang.value or "en"
        cfg.preview_mb = preview_mb
        cfg.exclude_names = [x.strip() for x in (s_exclude.value or "").split(",") if x.strip()]
        cfg.include_hidden = bool(s_hidden.value)
        cfg.exclude_appdata = bool(s_appdata.value)
        cfg.use_trash = bool(s_trash.value)
        cfg.save(cfg_path)
        snack(t("lang_restart") if lang_changed else t("saved"))

    def remove_missing(_):
        db.delete_missing()
        refresh_all()
        snack(t("saved"))

    def clear_index(_):
        def do(_):
            close_dialog()
            db.clear_index()
            selected.clear()
            refresh_all()
            snack(t("cleared"))

        open_dialog(t("confirm"), ft.Text(t("clear_index_confirm")), [
            ft.TextButton(t("cancel"), on_click=close_dialog),
            ft.ElevatedButton(t("clear_index"), on_click=do),
        ])

    update_status = ft.Text(t("version_now", v=__version__))
    latest_url = [""]
    check_btn = ft.OutlinedButton(text=t("check_update"))
    open_btn = ft.OutlinedButton(text=t("open_download"), visible=False,
                                 on_click=lambda _: page.launch_url(latest_url[0]))

    def check_update(_=None):
        check_btn.disabled = True
        update_status.value = t("checking")
        page.update()

        def worker():
            info = check_latest()

            def done():
                check_btn.disabled = False
                if info is None:
                    update_status.value = t("update_failed")
                    open_btn.visible = False
                elif info["newer"]:
                    latest_url[0] = info["url"]
                    update_status.value = t("update_available", v=info["version"], cur=__version__)
                    open_btn.visible = True
                else:
                    update_status.value = t("up_to_date", cur=__version__)
                    open_btn.visible = False
                page.update()

            page.run_thread(done)

        threading.Thread(target=worker, daemon=True).start()

    check_btn.on_click = check_update
    edition_label = t("edition_portable") if EDITION == "portable" else t("edition_single")

    settings_view = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=8, controls=[
        s_lang, s_preview, s_exclude, s_hidden, s_appdata, s_trash,
        ft.ElevatedButton(t("btn_save"), icon=ft.Icons.SAVE, on_click=save_settings),
        ft.Divider(),
        ft.Text(t("maintenance"), weight=ft.FontWeight.BOLD),
        ft.Row([
            ft.OutlinedButton(t("remove_missing"), icon=ft.Icons.DELETE_SWEEP, on_click=remove_missing),
            ft.OutlinedButton(t("clear_index"), icon=ft.Icons.CLEAR_ALL, on_click=clear_index),
        ], wrap=True),
        ft.Divider(),
        ft.Text(t("about"), weight=ft.FontWeight.BOLD),
        ft.Text(f"{t('edition')}: {edition_label}"),
        ft.Text(f"{t('data_folder')}: {ddir}", size=12, selectable=True, color=GREY),
        ft.Text(t("portable_note") if EDITION == "portable" else t("single_note"), size=12, color=GREY),
        update_status,
        ft.Row([check_btn, open_btn]),
        ft.TextButton(text=REPO_URL, on_click=lambda _: page.launch_url(REPO_URL)),
    ])

    # ---------- 全体の更新 ----------
    def refresh_all():
        refresh_locations()
        refresh_tags()
        update_filter_label()
        if results.controls:
            run_search()
        page.update()

    tabs = ft.Tabs(selected_index=0, expand=True, tabs=[
        ft.Tab(text=t("tab_search"), content=search_view),
        ft.Tab(text=t("tab_locations"), content=locations_view),
        ft.Tab(text=t("tab_tags"), content=tags_view),
        ft.Tab(text=t("tab_settings"), content=settings_view),
    ])
    body.content = tabs

    page.add(ft.Column(expand=True, controls=[
        ft.Row([ft.Text("File Hub", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(edition_label, size=12, color=GREY)]),
        body,
    ]))
    refresh_all()
    if not cfg.initial_scan_done:
        cfg.initial_scan_done = True
        cfg.save(cfg_path)
        open_registration(defaults=True)


if __name__ == "__main__":
    # 既に起動していれば、その画面を前面に出して終了する
    if not acquire_instance(data_dir(), wait_seconds=0):
        activate_existing_window()
        sys.exit(0)
    ft.app(target=main, assets_dir="assets")
