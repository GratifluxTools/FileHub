"""チェックボックス付きフォルダツリー。

選択の決まり（画面で使う）:
- フォルダにチェックを入れると、そのフォルダ以下すべてが対象になる。
- チェックを外すと、そのフォルダ以下すべてが対象外になる。
- 上位が対象のまま、下位だけ外した場合は、上位を兄弟フォルダの集まりに分解して残す。

選択はフォルダのパスの集合で持つ（最小の集合になるように保つ）。
"""
import os

import flet as ft

from paths import is_within, norm


def covered(path, selected):
    """path が選択（自身か上位）に含まれるか。"""
    return any(is_within(path, s) for s in selected)


def check(path, selected):
    """path を対象に加える。下位の選択は path に吸収される。"""
    if covered(path, selected):
        return set(selected)
    out = {s for s in selected if not is_within(s, path)}
    out.add(path)
    return out


def uncheck(path, selected, list_dirs):
    """path を対象から外す。上位が対象なら、上位を分解して path 以外を残す。"""
    out = set(selected)
    for anc in [s for s in out if is_within(path, s) and norm(s) != norm(path)]:
        out.discard(anc)
        out |= _split(anc, path, list_dirs)
    return {s for s in out if not is_within(s, path)}


def _split(anc, target, list_dirs):
    """anc の子フォルダのうち、target（とその下）を除いたものを返す。"""
    result = set()
    for child in list_dirs(anc):
        if norm(child) == norm(target):
            continue
        if is_within(target, child):
            result |= _split(child, target, list_dirs)
        else:
            result.add(child)
    return result


def minimal(selected):
    """選択のうち、上位に含まれているものを除く（登録する場所の一覧に使う）。"""
    sel = sorted(set(selected), key=lambda p: len(norm(p)))
    out = []
    for p in sel:
        if not any(is_within(p, q) for q in out):
            out.append(p)
    return out


class FolderTreeView:
    """フォルダを遅延読み込みで開閉できるツリー。チェックの状態は state["sel"] に保存する。"""

    def __init__(self, roots, list_dirs, state, on_change, empty_text="", page=None):
        # roots: 一番上に並べるフォルダの根（1つでも一覧でもよい）
        roots = [roots] if isinstance(roots, str) else list(roots)
        self.roots = roots
        self.list_dirs = list_dirs
        self.state = state
        self.on_change = on_change
        self.empty_text = empty_text
        self.page = page
        self.rendered = []  # (path, Checkbox)
        self.container = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
        self.container.controls = [self._node(r, 0, expanded=True) for r in roots]

    def _node(self, path, depth, expanded=False):
        children = ft.Column(spacing=0, visible=False, tight=True)
        arrow = ft.IconButton(icon=ft.Icons.KEYBOARD_ARROW_RIGHT, icon_size=18)
        cb = ft.Checkbox(value=covered(path, self.state["sel"]),
                         on_change=lambda e, p=path: self._toggle(p, e.control.value))
        arrow.on_click = lambda _, p=path, d=depth, c=children, a=arrow: self._expand(p, d, c, a)
        label = os.path.basename(os.path.normpath(path)) or path  # ドライブの根は「D:\\」のまま
        row = ft.Row([ft.Container(width=depth * 22), arrow, cb,
                      ft.Icon(ft.Icons.FOLDER, size=18), ft.Text(label)],
                     spacing=2, tight=True)
        self.rendered.append((path, cb))
        node = ft.Column([row, children], spacing=0, tight=True)
        if expanded:
            self._expand(path, depth, children, arrow)
        return node

    def _expand(self, path, depth, children, arrow):
        if children.visible:
            children.visible = False
            arrow.icon = ft.Icons.KEYBOARD_ARROW_RIGHT
        else:
            if not children.controls:
                kids = self.list_dirs(path)
                children.controls = [self._node(k, depth + 1) for k in kids] or [
                    ft.Text(self.empty_text, size=12, color=ft.Colors.GREY)]
            children.visible = True
            arrow.icon = ft.Icons.KEYBOARD_ARROW_DOWN
        self._update()

    def _toggle(self, path, checked):
        sel = self.state["sel"]
        self.state["sel"] = check(path, sel) if checked else uncheck(path, sel, self.list_dirs)
        for p, cb in self.rendered:
            cb.value = covered(p, self.state["sel"])
        self.on_change()
        self._update()

    def _update(self):
        if self.page is not None:
            self.page.update()
