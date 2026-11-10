# -*- coding: utf-8 -*-
"""面板共用的小组件与配色，避免每个页面各写一份。"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Optional

CN_FONT = "Microsoft YaHei UI"
BG = "#f6f7fb"
CARD = "#ffffff"
ACCENT = "#4c6ef5"

STAT_COLOR = {"high": "#37b24d", "mid": "#f59f00", "low": "#e03131"}


class Bar(tk.Canvas):
    """一条数值条。"""

    def __init__(self, master, width: int = 210, height: int = 12,
                 bg_color: Optional[str] = None):
        super().__init__(master, width=width, height=height, bg=bg_color or CARD,
                         highlightthickness=0)
        self.total = max(10, width)
        self.h = height
        self.create_rectangle(0, 0, self.total, height, fill="#e9ecef", outline="")
        self.fill_rect = self.create_rectangle(0, 0, 0, height, fill="#37b24d", outline="")

    def set(self, ratio: float, color: Optional[str] = None) -> None:
        ratio = max(0.0, min(1.0, ratio))
        self.coords(self.fill_rect, 0, 0, ratio * self.total, self.h)
        self.itemconfig(self.fill_rect, fill=color or STAT_COLOR["high"])


def stat_color(v: float) -> str:
    return STAT_COLOR["high"] if v >= 60 else (STAT_COLOR["mid"] if v >= 30 else STAT_COLOR["low"])


def place_centered(win: tk.Toplevel, w: int, h: int, y_ratio: float = 0.3) -> None:
    """把窗口摆到屏幕中间偏上，避免默认 1x1+0+0 或者落在屏幕外。"""
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, int((sh - h) * y_ratio))
    win.geometry(f"{w}x{h}+{x}+{y}")


def show_transient(win: tk.Toplevel, master: tk.Misc | None = None) -> None:
    """把子窗口显示出来，但不在任务栏占位。

    坑：App 的根窗口是 withdrawn 的（桌宠不需要主窗口），而 Tcl/Tk 规定
    transient 子窗口会被 withdrawn 的 master 一起藏起来——面板就再也看不见了。
    所以这里**不用 transient**，Windows 上改用 -toolwindow（同样不进任务栏，
    但不依赖 master 的显示状态），其他平台退回到 transient。
    """
    if sys.platform.startswith("win"):
        try:
            win.attributes("-toolwindow", True)
        except Exception:  # noqa: BLE001
            pass
    elif master is not None:
        try:
            win.transient(master)
        except Exception:  # noqa: BLE001
            pass
    win.deiconify()
    win.after_idle(win.deiconify)
    win.lift()


class ScrollFrame(tk.Frame):
    """带竖向滚动条的容器，内容往 `self.inner` 里放。

    滚轮坑：`bind_all("<MouseWheel>", ...)` 是「覆盖式」绑定，面板里有多个
    ScrollFrame 时只有最后建的那个能响应滚轮（其余页面滚不动）。所以这里
    只绑定一次全局分发器，再按鼠标位置找到真正该滚的那个实例。
    """

    _wheel_bound = False

    def __init__(self, master, **kw):
        super().__init__(master, bg=BG, **kw)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.vsb.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        # 让内容宽度跟着画布走，否则表格只占左边一小块、右边留白
        self.canvas.bind("<Configure>", self._on_canvas)

        if not ScrollFrame._wheel_bound:
            ScrollFrame._wheel_bound = True
            self.bind_all("<MouseWheel>", ScrollFrame._dispatch_wheel, add="+")

    def _on_canvas(self, event: tk.Event) -> None:
        try:
            self.canvas.itemconfigure(self._win, width=event.width)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _dispatch_wheel(event: tk.Event) -> None:
        widget = getattr(event, "widget", None)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget._wheel(event)
                return
            widget = getattr(widget, "master", None)

    def _wheel(self, event: tk.Event) -> None:
        try:
            first, last = self.canvas.yview()
            if first <= 0.0 and last >= 1.0:      # 内容没超出，不用滚
                return
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:  # noqa: BLE001
            pass

    def scroll_top(self) -> None:
        try:
            self.canvas.yview_moveto(0.0)
        except Exception:  # noqa: BLE001
            pass

    def clear(self) -> None:
        for child in list(self.inner.winfo_children()):
            child.destroy()
