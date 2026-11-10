# -*- coding: utf-8 -*-
"""功能图标台：把藏在右键菜单里的功能摊成一排图标（像系统托盘的溢出小框）。

设计要点
--------
- 无边框 + `-transparentcolor`：只有圆角卡片那一块是实心的，四周透明且不吃鼠标。
- 单个 Canvas 画所有图标，每个格子打一个 tag，用 tag 绑定做悬停高亮与点击。
- 图标是「彩色圆角方块 + 一个汉字」，不依赖任何图片素材，任何 DPI 下都清晰。
- 从桌宠旁边弹出；鼠标移开 0.9 秒后自动收起，Esc 也能关。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Sequence, Tuple

TRANSPARENT = "#FF00FF"
CARD = "#fbfbfd"
EDGE = "#d5d5df"
HOVER = "#eef0f5"
TEXT = "#3c3f45"
SUB = "#8b8f97"
CN_FONT = "Microsoft YaHei UI"

Entry = Tuple[str, str, str, Callable[[], None]]   # (文字, 图标汉字, 底色, 回调)


def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                r: float = 10, **kw) -> int:
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class DockWindow(tk.Toplevel):
    COLS = 6
    CELL_W = 64
    CELL_H = 74
    PAD = 10
    HIDE_DELAY = 900

    def __init__(self, master: tk.Tk, app, entries: Sequence[Entry]):
        super().__init__(master)
        self.app = app
        self.entries: List[Entry] = list(entries)
        rows = max(1, (len(self.entries) + self.COLS - 1) // self.COLS)
        self.w = self.PAD * 2 + self.COLS * self.CELL_W
        self.h = self.PAD * 2 + rows * self.CELL_H

        self.overrideredirect(True)
        self.configure(bg=TRANSPARENT)
        try:
            self.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.attributes("-topmost", True)

        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=TRANSPARENT,
                                highlightthickness=0, bd=0, cursor="arrow")
        self.canvas.pack()

        self._hover_ids: List[int] = []
        self._hide_job = None
        self._drag_off = None

        self._draw()
        self._place_near_pet()

        self.bind("<Enter>", lambda _e: self._cancel_hide())
        self.bind("<Leave>", lambda _e: self._schedule_hide())
        self.bind("<Escape>", lambda _e: self.close())
        self.after(80, self._grab_focus)

    # ---------------------------------------------------------------- 绘制
    def _draw(self) -> None:
        c = self.canvas
        _round_rect(c, 1, 1, self.w - 1, self.h - 1, r=14,
                    fill=CARD, outline=EDGE, width=1, tags="card")

        for i, (label, glyph, color, _cmd) in enumerate(self.entries):
            row, col = divmod(i, self.COLS)
            x0 = self.PAD + col * self.CELL_W
            y0 = self.PAD + row * self.CELL_H
            tag = f"cell{i}"

            bg = _round_rect(c, x0 + 2, y0 + 2, x0 + self.CELL_W - 2,
                             y0 + self.CELL_H - 4, r=10,
                             fill=CARD, outline="", tags=tag)
            self._hover_ids.append(bg)

            cx = x0 + self.CELL_W / 2
            _round_rect(c, cx - 16, y0 + 10, cx + 16, y0 + 42, r=9,
                        fill=color, outline="", tags=tag)
            c.create_text(cx, y0 + 26, text=glyph, fill="#ffffff",
                          font=(CN_FONT, 12, "bold"), tags=tag)
            c.create_text(cx, y0 + 46, text=label, fill=SUB,
                          font=(CN_FONT, 8), anchor="n", tags=tag)

            c.tag_bind(tag, "<Enter>", lambda _e, k=i: self._hover(k, True))
            c.tag_bind(tag, "<Leave>", lambda _e, k=i: self._hover(k, False))
            c.tag_bind(tag, "<Button-1>", lambda _e, k=i: self._invoke(k))

        # 拖动：按住卡片空白处
        c.tag_bind("card", "<ButtonPress-1>", self._drag_start)
        c.tag_bind("card", "<B1-Motion>", self._drag_move)
        c.tag_bind("card", "<ButtonRelease-1>", lambda _e: setattr(self, "_drag_off", None))

    def _hover(self, index: int, on: bool) -> None:
        try:
            self.canvas.itemconfigure(self._hover_ids[index], fill=HOVER if on else CARD)
            self.canvas.configure(cursor="hand2" if on else "arrow")
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- 交互
    def _invoke(self, index: int) -> None:
        cmd = self.entries[index][3]
        self.close()
        # 同步执行：之前用 after(1) 会留下一个「迟到的回调」，
        # 若期间又打开了图标台，那次 open_panel 里的 close_dock 会把新窗口关掉。
        try:
            cmd()
        except Exception:  # noqa: BLE001
            import traceback

            traceback.print_exc()

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_off = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())
        self._cancel_hide()

    def _drag_move(self, event: tk.Event) -> None:
        if not self._drag_off:
            return
        dx, dy = self._drag_off
        self.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _grab_focus(self) -> None:
        try:
            self.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def _cancel_hide(self) -> None:
        if self._hide_job:
            try:
                self.after_cancel(self._hide_job)
            except Exception:  # noqa: BLE001
                pass
            self._hide_job = None

    def _schedule_hide(self) -> None:
        self._cancel_hide()
        if self._drag_off:
            return
        try:
            self._hide_job = self.after(self.HIDE_DELAY, self.close)
        except Exception:  # noqa: BLE001
            self._hide_job = None

    # ---------------------------------------------------------------- 定位
    def _place_near_pet(self) -> None:
        pw = getattr(self.app, "pet_window", None)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if pw is not None and pw.winfo_exists():
            px, py = pw.winfo_rootx(), pw.winfo_rooty()
            pw_w, pw_h = pw.winfo_width(), pw.winfo_height()
        else:
            px = py = 200
            pw_w = pw_h = 160
        x = px + pw_w // 2 - self.w // 2
        y = py - self.h - 10                       # 优先在头顶
        if y < 8:                                  # 上面放不下就放下面
            y = py + pw_h + 10
        x = max(8, min(x, sw - self.w - 8))
        y = max(8, min(y, sh - self.h - 60))
        self.geometry(f"{self.w}x{self.h}+{int(x)}+{int(y)}")

    # ---------------------------------------------------------------- 关闭
    def close(self) -> None:
        self._cancel_hide()
        app = self.app
        try:
            self.destroy()
        finally:
            notify = getattr(app, "on_dock_closed", None)
            if notify:
                try:
                    notify(self)
                except TypeError:
                    notify()
