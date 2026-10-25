from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Hashable, Sequence
from typing import TypeVar
from tkinter import ttk

YES = "✓"
NO = "☐"

T = TypeVar("T", bound=Hashable)


def sticky_click(
    selected: set[T],
    anchor: T,
    target: T,
    order: Sequence[T],
    *,
    shift: bool = False,
    ctrl: bool = False,
) -> tuple[set[T], T]:
    """Explorer mouse selection. Clicking inside the current selection keeps it."""
    if not order:
        return set(), anchor
    items = list(order)
    if target not in items:
        return set(selected), anchor
    if shift:
        if anchor not in items:
            anchor = target
        start = items.index(anchor)
        end = items.index(target)
        low, high = (start, end) if start <= end else (end, start)
        return set(items[low : high + 1]), anchor
    if ctrl:
        nxt = set(selected)
        if target in nxt:
            if len(nxt) > 1:
                nxt.remove(target)
        else:
            nxt.add(target)
        if not nxt:
            nxt = {target}
        return nxt, anchor
    if target in selected:
        return set(selected), anchor
    return {target}, target


def sticky_extend(selected: set[T], *indices: T) -> set[T]:
    nxt = set(selected)
    nxt.update(indices)
    return nxt


class CheckedTree(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        columns: tuple[str, ...],
        headings: dict[str, str],
        widths: dict[str, int],
        on_change=None,
        modes: tuple[str, ...] | None = None,
    ):
        super().__init__(parent)
        self.on_change = on_change
        self.modes = modes
        names = ("pick",) + columns
        self.tree = ttk.Treeview(
            self, columns=names, show="tree headings", height=16, selectmode="extended", takefocus=True
        )
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=0, stretch=False)
        pick_w = 88 if modes else 52
        try:
            from common.ui import pick_column_width

            if not modes:
                pick_w = pick_column_width()
        except Exception:
            pass
        self.tree.heading("pick", text="Modus" if modes else "An")
        self.tree.column("pick", width=pick_w, stretch=False)
        narrow = {"kind", "status", "when", "origin", "year", "files", "html", "state", "pick"}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=widths[name], stretch=name not in narrow)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._anchor = ""
        self._press_iid = ""
        self._press_pick = False
        self._dragged = False
        self._press_y = 0
        self._repeat_at = 0.0
        self._repeat_n = 1
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<B1-Motion>", self._on_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_release)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Control-i>", lambda _event: self.invert() or "break")
        self.tree.bind("<Control-a>", self._select_all)
        self.tree.bind("<Control-A>", self._select_all)
        self.tree.bind("<KeyPress>", self._on_keypress)

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._anchor = ""
        self._press_iid = ""

    def add(
        self,
        values: tuple[str, ...],
        *,
        iid: str,
        parent: str = "",
        checked: bool = True,
        open_: bool = True,
        mode: str | None = None,
        text: str = "",
    ) -> None:
        if self.modes:
            pick = mode if mode in self.modes else self.modes[-1]
        else:
            pick = YES if checked else NO
        try:
            self.tree.insert(parent, "end", iid=iid, text=text, values=(pick, *values), open=open_)
        except tk.TclError:
            self.tree.insert("", "end", iid=iid, text=text, values=(pick, *values), open=open_)

    def pick_values(self) -> dict[str, str]:
        return {iid: str(self.tree.set(iid, "pick")) for iid in self._walk()}

    def set_all_mode(self, mode: str) -> None:
        if self.modes is None or mode not in self.modes:
            return
        for iid in self._walk():
            self.tree.set(iid, "pick", mode)
        self._notify()

    def set_selected_mode(self, mode: str) -> None:
        self._set_selected_mode(mode)

    def checked_ids(self) -> list[str]:
        found: list[str] = []
        for iid in self._walk():
            if self.tree.set(iid, "pick") == YES:
                found.append(iid)
        return found

    def invert(self) -> None:
        if self.modes:
            for iid in self._walk():
                self._cycle(iid)
            self._notify()
            return
        for iid in self._walk():
            now = self.tree.set(iid, "pick") != YES
            self.tree.set(iid, "pick", YES if now else NO)
        for iid in self.tree.get_children(""):
            if self.tree.get_children(iid):
                self._sync_parent(iid)
        self._notify()

    def set_all(self, checked: bool) -> None:
        value = YES if checked else NO
        for iid in self._walk():
            self.tree.set(iid, "pick", value)
        self._notify()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def _walk(self) -> list[str]:
        items: list[str] = []

        def walk(parent: str) -> None:
            for iid in self.tree.get_children(parent):
                items.append(iid)
                walk(iid)

        walk("")
        return items

    def _targets(self) -> list[str]:
        iids = [iid for iid in self.tree.selection() if self.tree.exists(iid)]
        focus = self.tree.focus()
        if focus and focus not in iids and self.tree.exists(focus):
            iids.append(focus)
        return iids

    def _visible_order(self) -> list[str]:
        items: list[str] = []

        def walk(parent: str) -> None:
            for iid in self.tree.get_children(parent):
                items.append(iid)
                if self.tree.item(iid, "open"):
                    walk(iid)

        walk("")
        return items

    def _select_all(self, _event: tk.Event | None = None) -> str:
        items = self._walk()
        if items:
            self.tree.selection_set(items)
            if not self._anchor:
                self._anchor = items[0]
        return "break"

    def _repeat_stride(self) -> int:
        now = time.monotonic()
        if now - self._repeat_at < 0.09:
            self._repeat_n = min(12, self._repeat_n + 1)
        else:
            self._repeat_n = 1
        self._repeat_at = now
        return self._repeat_n

    def _neighbor(self, delta: int) -> str | None:
        order = self._visible_order()
        if not order:
            return None
        focus = self.tree.focus()
        if focus in order:
            index = max(0, min(len(order) - 1, order.index(focus) + delta))
        else:
            index = 0 if delta > 0 else len(order) - 1
        return order[index]

    def _focus_row(self, iid: str) -> None:
        self.tree.focus(iid)
        self.tree.see(iid)
        self.tree.focus_set()

    def _apply_selection(self, items: set[str], anchor: str, focus: str) -> None:
        ordered = [iid for iid in self._visible_order() if iid in items]
        if not ordered:
            ordered = [iid for iid in items if self.tree.exists(iid)]
        if ordered:
            self.tree.selection_set(ordered)
        if anchor and self.tree.exists(anchor):
            self._anchor = anchor
        if focus and self.tree.exists(focus):
            self._focus_row(focus)

    def _move_only(self, delta: int) -> str:
        iid = self._neighbor(delta)
        if iid:
            self.tree.selection_set(iid)
            self._anchor = iid
            self._focus_row(iid)
        return "break"

    def _extend(self, delta: int) -> str:
        step = delta * self._repeat_stride()
        iid = self._neighbor(step)
        if not iid:
            return "break"
        focus = self.tree.focus()
        items = sticky_extend(set(self.tree.selection()), focus, iid)
        self._apply_selection(items, self._anchor or focus or iid, iid)
        return "break"

    def _range_move(self, delta: int) -> str:
        iid = self._neighbor(delta)
        if not iid:
            return "break"
        order = self._visible_order()
        items, anchor = sticky_click(set(self.tree.selection()), self._anchor, iid, order, shift=True)
        self._apply_selection(items, anchor, iid)
        return "break"

    def _select_range_to(self, iid: str) -> None:
        order = self._visible_order()
        items, anchor = sticky_click(set(self.tree.selection()), self._anchor, iid, order, shift=True)
        self._apply_selection(items, anchor, iid)

    def _set_selected_mode(self, mode: str) -> str:
        if self.modes is None or mode not in self.modes:
            return "break"
        iids = self._targets()
        if not iids:
            return "break"
        for iid in iids:
            self._set_pick(iid, mode)
        self._notify()
        return "break"

    def _on_keypress(self, event: tk.Event) -> str | None:
        key = event.keysym
        if key.startswith("KP_") and key[3:] in {"Up", "Down", "Left", "Right"}:
            key = key[3:]
        if key in {"Up", "Down", "Left", "Right"}:
            delta = -1 if key in {"Up", "Left"} else 1
            if event.state & 0x0004:
                return self._extend(delta)
            if event.state & 0x0001:
                return self._range_move(delta)
            if key in {"Up", "Down"}:
                return self._move_only(delta)
            return None
        if self.modes and event.char in {str(index) for index in range(1, len(self.modes) + 1)}:
            return self._set_selected_mode(self.modes[int(event.char) - 1])
        return None

    def _on_space(self, _event: tk.Event) -> str:
        self._apply_pick_to_selection()
        return "break"

    def _is_pick_column(self, event: tk.Event) -> bool:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return False
        return self.tree.identify_column(event.x) == "#1"

    def _on_click(self, event: tk.Event) -> str | None:
        self.tree.focus_set()
        region = self.tree.identify_region(event.x, event.y)
        if region in {"heading", "separator", "nothing"}:
            return None
        element = (self.tree.identify_element(event.x, event.y) or "").casefold()
        if "indicator" in element:
            return None
        iid = self.tree.identify_row(event.y)
        if not iid:
            return "break"
        shift = bool(event.state & 0x0001)
        ctrl = bool(event.state & 0x0004)
        order = self._visible_order()
        items, anchor = sticky_click(set(self.tree.selection()), self._anchor, iid, order, shift=shift, ctrl=ctrl)
        self._apply_selection(items, anchor, iid)
        self._press_iid = iid
        self._press_pick = self._is_pick_column(event)
        self._press_y = event.y
        self._dragged = False
        return "break"

    def _on_drag(self, event: tk.Event) -> str:
        if not self._press_iid:
            return "break"
        if abs(event.y - self._press_y) < 4:
            return "break"
        iid = self.tree.identify_row(event.y)
        if not iid:
            return "break"
        self._dragged = True
        if not self._anchor:
            self._anchor = self._press_iid
        self._select_range_to(iid)
        return "break"

    def _on_release(self, _event: tk.Event) -> str:
        if self._press_pick and not self._dragged:
            self._apply_pick_to_selection(self._press_iid)
        self._press_iid = ""
        self._press_pick = False
        self._dragged = False
        return "break"

    def _apply_pick_to_selection(self, clicked: str = "") -> None:
        iids = self._targets()
        if not iids:
            return
        source = clicked if clicked in iids else iids[0]
        if self.modes:
            nxt = self._next_pick(self.tree.set(source, "pick"))
            for iid in iids:
                self._set_pick(iid, nxt)
        else:
            nxt = self._next_pick(self.tree.set(source, "pick"))
            for iid in iids:
                self._set_pick(iid, nxt)
                parent = self.tree.parent(iid)
                if parent:
                    self._sync_parent(parent)
        self._notify()

    def _next_pick(self, current: str) -> str:
        if self.modes:
            try:
                index = self.modes.index(current)
            except ValueError:
                index = -1
            return self.modes[(index + 1) % len(self.modes)]
        return YES if current != YES else NO

    def _cycle(self, iid: str) -> None:
        self._set_pick(iid, self._next_pick(self.tree.set(iid, "pick")))

    def _set_pick(self, iid: str, value: str) -> None:
        self.tree.set(iid, "pick", value)
        if self.modes:
            return
        for child in self.tree.get_children(iid):
            self._set_pick(child, value)

    def _set_branch(self, iid: str, checked: bool) -> None:
        self._set_pick(iid, YES if checked else NO)

    def _sync_parent(self, iid: str) -> None:
        if self.modes:
            return
        children = self.tree.get_children(iid)
        if not children:
            return
        any_checked = any(self.tree.set(child, "pick") == YES for child in children)
        self.tree.set(iid, "pick", YES if any_checked else NO)
        parent = self.tree.parent(iid)
        if parent:
            self._sync_parent(parent)
