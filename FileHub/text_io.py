"""テキストの読み書きと、文書の中身の取り出し（プレビュー用）。

編集できるのはプレーンテキスト系のファイルだけ。Office・PDF・RTF は内容を読んで表示するのみ。
"""
import os
import re
import xml.etree.ElementTree as ET
import zipfile

MAX_PREVIEW_CHARS = 20000
BOM = b"\xef\xbb\xbf"


def decode_bytes(raw, truncated):
    """バイト列を文字列にする。戻り値は (文字列, 使った文字コード名)。

    UTF-8 を優先し、ダメなら日本語の Shift_JIS（cp932）や EUC-JP を試す。
    途中で切った場合は、末尾の不完全な文字を取り除いてから判定する。
    """
    if raw.startswith(BOM):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "cp932", "euc_jp"):
        if not truncated:
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError:
                continue
        for cut in range(4):
            try:
                return raw[:len(raw) - cut].decode(enc), enc
            except UnicodeDecodeError:
                continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def read_text(path, limit_bytes):
    """戻り値は (文字列, 文字コード, 途中で切ったかどうか)。"""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        raw = fh.read(limit_bytes)
    truncated = size > limit_bytes
    text, enc = decode_bytes(raw, truncated)
    return text, enc, truncated


def write_text(path, text, enc):
    """元の文字コードで書き戻す。変換できない文字がある場合は UnicodeEncodeError になる。"""
    data = text.encode(enc)
    with open(path, "wb") as fh:
        fh.write(data)


def _natural_key(name):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)]


def _xml_to_text(root, para_tags):
    parts = []

    def walk(el):
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail and child.tail.strip():
                parts.append(child.tail)
        if el.tag.rsplit("}", 1)[-1] in para_tags:
            parts.append("\n")

    walk(root)
    return re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()


def _zip_xml_text(path, name_pattern, para_tags):
    rx = re.compile(name_pattern)
    chunks = []
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if rx.fullmatch(n)), key=_natural_key)
        for name in names:
            chunks.append(_xml_to_text(ET.fromstring(z.read(name)), para_tags))
    return "\n\n".join(c for c in chunks if c)


def _ods_text(path, max_rows=200):
    """ODS（表計算）の中身をタブ区切りで取り出す。"""
    lines = []
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    for table in root.iter():
        if table.tag.rsplit("}", 1)[-1] != "table":
            continue
        name = next((v for k, v in table.attrib.items() if k.endswith("}name")), "")
        lines.append(f"[{name}]")
        rows = 0
        for row in table.iter():
            if row.tag.rsplit("}", 1)[-1] != "table-row":
                continue
            cells = []
            for cell in row:
                if cell.tag.rsplit("}", 1)[-1] in ("table-cell", "covered-table-cell"):
                    cells.append("".join(cell.itertext()))
            lines.append("\t".join(cells))
            rows += 1
            if rows >= max_rows:
                break
    return "\n".join(lines)


def _xlsx_text(path, max_rows=200):
    try:
        import openpyxl
    except ImportError as ex:
        raise RuntimeError("openpyxl is not installed") from ex
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    lines = []
    try:
        for ws in wb.worksheets[:5]:
            lines.append(f"[{ws.title}]")
            for row in ws.iter_rows(max_row=max_rows, values_only=True):
                lines.append("\t".join("" if v is None else str(v) for v in row))
    finally:
        wb.close()
    return "\n".join(lines)


def _pdf_text(path, max_pages=20):
    try:
        from pypdf import PdfReader
    except ImportError as ex:
        raise RuntimeError("pypdf is not installed") from ex
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


def _rtf_text(path):
    with open(path, "rb") as fh:
        s = fh.read().decode("latin-1")
    s = re.sub(r"\\'([0-9a-fA-F]{2})",
               lambda m: bytes.fromhex(m.group(1)).decode("cp932", errors="replace"), s)
    s = re.sub(r"\\par[d]?\b", "\n", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    s = re.sub(r"[{}]", "", s)
    return s.strip()


def extract_office_text(path, ext, limit=MAX_PREVIEW_CHARS):
    """文書の文章を取り出す。取り出せない形式なら None。"""
    ext = ext.lower()
    if ext == "docx":
        text = _zip_xml_text(path, r"word/document\.xml", {"p"})
    elif ext == "pptx":
        text = _zip_xml_text(path, r"ppt/slides/slide\d+\.xml", {"p"})
    elif ext in ("odt", "odp"):
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("content.xml"))
        text = _xml_to_text(root, {"p", "h"})
    elif ext == "ods":
        text = _ods_text(path)
    elif ext == "xlsx":
        text = _xlsx_text(path)
    elif ext == "pdf":
        text = _pdf_text(path)
    elif ext == "rtf":
        text = _rtf_text(path)
    else:
        return None
    return text[:limit] if text else None
