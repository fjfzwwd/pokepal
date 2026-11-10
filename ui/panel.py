# -*- coding: utf-8 -*-
"""主控面板：状态 / 养育 / 商店 / 图鉴 / 设置。

信息架构参考电子宠物掌机 + QQ 宠物面板：
    状态  —— 数值可视化，一眼看懂它现在过得好不好
    养育  —— 高频操作（喂食 / 清洁 / 玩耍 / 训练 / 打工）
    商店  —— 经济循环，用打工赚来的零花钱买道具
    图鉴  —— 已相遇/未相遇的收集册，可以在这里「相遇」新伙伴
    设置  —— 桌宠外观与行为
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Dict, List, Optional

from assets.sprites import SIZE_PRESETS
from core import items
from core.pet import STAT_ZH
from core.store import TEAM_LIMIT
from ui.widgets import (ACCENT, BG, CARD, CN_FONT, Bar, ScrollFrame, place_centered,
                        show_transient, stat_color)


class PanelWindow(tk.Toplevel):
    DEX_HINT = ("悬停卡片看详情：绿框=已收服　蓝框=只是见过　灰框=还没发现\n"
                "点击卡片：召唤同伴 / 从仓库接回来 / 结识新伙伴")

    def __init__(self, master: tk.Tk, app):
        super().__init__(master)
        self.app = app
        self.store = app.store
        self.title("PokePal · 主控面板")
        self.geometry("820x600")
        self.minsize(760, 520)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.thumbs: Dict[int, Optional[tk.PhotoImage]] = {}
        self._stat_bars: Dict[str, Bar] = {}
        self._stat_values: Dict[str, tk.Label] = {}
        self._dynamic: List[tk.Label] = []

        self._build_header()
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.notebook = notebook
        # 内容多的页签一律用可滚动容器：商店有 8 个分类 36 件商品，
        # 不滚动的话「精灵球」「进化石」永远在窗口外面看不见。
        self.tab_status = tk.Frame(notebook, bg=BG)
        self.tab_care = ScrollFrame(notebook)
        self.tab_shop = ScrollFrame(notebook)
        self.tab_dex = ScrollFrame(notebook)
        self.tab_explore = ScrollFrame(notebook)
        self.tab_box = ScrollFrame(notebook)
        self.tab_farm = ScrollFrame(notebook)
        self.tab_settings = ScrollFrame(notebook)
        self.TABS = {"状态": self.tab_status, "养育": self.tab_care,
                     "商店": self.tab_shop, "图鉴": self.tab_dex,
                     "探索": self.tab_explore, "仓库": self.tab_box,
                     "蚕室": self.tab_farm, "设置": self.tab_settings}
        for name, frame in self.TABS.items():
            notebook.add(frame, text=name)

        # 每个页签的重建函数：全开图鉴后有 100+ 位伙伴，一次重建八页要两秒，
        # 所以改成「只重建当前可见页」，其余标脏、切过去时再建。
        self.BUILDERS = {
            "状态": self._rebuild_status, "养育": self._rebuild_care,
            "商店": self._rebuild_shop, "图鉴": self._rebuild_dex,
            "探索": self._rebuild_explore, "仓库": self._rebuild_box,
            "蚕室": self._rebuild_farm, "设置": self._rebuild_settings,
        }
        self._dirty = set(self.BUILDERS)
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        place_centered(self, 820, 600)
        show_transient(self, master)

        self._last_width = 0
        self._dex_job = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event: tk.Event) -> None:
        """窗口宽度变了就重排图鉴（列数跟着宽度走），带防抖。"""
        if event.widget is not self:
            return
        if abs(event.width - self._last_width) < 60:
            return
        self._last_width = event.width
        if self._dex_job:
            try:
                self.after_cancel(self._dex_job)
            except Exception:  # noqa: BLE001
                pass
            self._dex_job = None
        self._schedule_reflow()

    def _reflow_dex(self) -> None:
        self._dex_job = None
        if not (hasattr(self, "dex_grid") and self.dex_grid.winfo_exists()):
            return
        if self.dex_grid.winfo_width() <= 1:      # 还没排版，等真正显示时再说
            return
        self._render_dex()

    def _schedule_reflow(self) -> None:
        if self._dex_job:
            return
        try:
            self._dex_job = self.after(80, self._reflow_dex)
        except Exception:  # noqa: BLE001
            self._dex_job = None

    # ---------------------------------------------------------------- 头部
    def _build_header(self) -> None:
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(head, text="PokePal", font=(CN_FONT, 15, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        self.wallet_label = tk.Label(head, text="", font=(CN_FONT, 10), bg=BG, fg="#555")
        self.wallet_label.pack(side="right")

    # ---------------------------------------------------------------- 刷新
    def select_tab(self, name: str) -> bool:
        """按页签名选中（比写死下标稳）。"""
        for tab_id in self.notebook.tabs():
            if self.notebook.tab(tab_id, "text") == name:
                self.notebook.select(tab_id)
                return True
        return False

    def close(self) -> None:
        self.app.on_panel_closed()
        self.destroy()

    def _visible_tab(self) -> str:
        try:
            return self.notebook.tab("current", "text")
        except Exception:  # noqa: BLE001
            return ""

    def _on_tab_changed(self, _event=None) -> None:
        name = self._visible_tab()
        if name in self._dirty:
            self._rebuild_tab(name)
        frame = self.TABS.get(name)
        if frame is not None and hasattr(frame, "scroll_top"):
            frame.scroll_top()          # 切页签回到顶部

    def _rebuild_tab(self, name: str) -> None:
        builder = self.BUILDERS.get(name)
        if not builder:
            return
        frame = self.TABS.get(name)
        pos = None
        if frame is not None and hasattr(frame, "canvas"):
            try:
                pos = frame.canvas.yview()[0]      # 记住位置，买完东西别跳回顶部
            except Exception:  # noqa: BLE001
                pos = None
        try:
            builder()
        except Exception:  # noqa: BLE001
            import traceback

            traceback.print_exc()
        if pos:
            try:
                frame.canvas.yview_moveto(pos)
                self.after_idle(lambda f=frame, p=pos: f.canvas.yview_moveto(p))
            except Exception:  # noqa: BLE001
                pass
        self._dirty.discard(name)

    def _wallet_text(self) -> str:
        # 百万级数字加千分位，不然 1000000 看起来像打错了
        return f"零花钱 {self.store.wallet:,} 元"

    def refresh_all(self) -> None:
        pet = self.store.pet
        self.wallet_label.configure(text=self._wallet_text())
        if not pet:
            return
        name = self._visible_tab()
        self._dirty = set(self.BUILDERS) - {name}
        self._rebuild_tab(name)

    def refresh_data(self) -> None:
        """只更新数值类内容（每几秒调用一次，不重建结构）。"""
        pet = self.store.pet
        if not pet:
            return
        self.wallet_label.configure(text=self._wallet_text())
        for key, bar in self._stat_bars.items():
            if key == "exp":
                bar.set(pet.exp_ratio, "#4c6ef5")
            elif key == "bond":
                bar.set(pet.bond / 100, "#ae3ec9")
            else:
                bar.set(pet.stats[key] / 100, stat_color(pet.stats[key]))
        for key, label in self._stat_values.items():
            if key == "exp":
                label.configure(text=f"{pet.exp}/{pet.exp_max}")
            elif key == "bond":
                label.configure(text=f"{int(pet.bond)}")
            else:
                label.configure(text=f"{int(pet.stats[key])}")
        if hasattr(self, "_summary_label") and self._summary_label.winfo_exists():
            self._summary_label.configure(
                text=f"Lv.{pet.level}　{self.store.dex.types_zh(pet.species_id)}　"
                     f"状态：{pet.status_zh()}")

    # ---------------------------------------------------------------- 状态页
    def _rebuild_status(self) -> None:
        for child in list(self.tab_status.winfo_children()):
            child.destroy()
        self._stat_bars.clear()
        self._stat_values.clear()
        pet = self.store.pet
        dex = self.store.dex

        hero = tk.Frame(self.tab_status, bg=CARD, padx=14, pady=12)
        hero.pack(fill="x", padx=12, pady=10)
        tk.Label(hero, text=f"{pet.display_name()}", font=(CN_FONT, 16, "bold"),
                 bg=CARD).grid(row=0, column=0, sticky="w")
        tk.Label(hero, text=f"#{pet.species_id:04d}　{dex.types_zh(pet.species_id)}",
                 font=(CN_FONT, 9), bg=CARD, fg="#777").grid(row=1, column=0, sticky="w")
        self._summary_label = tk.Label(hero, text="", font=(CN_FONT, 9), bg=CARD, fg="#555")
        self._summary_label.grid(row=2, column=0, sticky="w", pady=(4, 0))

        met = time.strftime("%Y-%m-%d", time.localtime(pet.met_at))
        tk.Label(hero, text=f"相遇于 {met}\n照顾了 {pet.total_care} 次　进化 {pet.evolve_count} 次",
                 font=(CN_FONT, 9), bg=CARD, fg="#888", justify="right").grid(
            row=0, column=2, rowspan=3, sticky="e")
        hero.columnconfigure(1, weight=1)

        box = tk.Frame(self.tab_status, bg=CARD, padx=14, pady=10)
        box.pack(fill="x", padx=12, pady=(0, 10))

        self._add_bar(box, "经验", "exp", 0)
        for key in ("fullness", "hydration", "clean", "mood", "stamina"):
            self._add_bar(box, STAT_ZH[key], key, list(STAT_ZH).index(key) + 1)
        self._add_bar(box, "羁绊", "bond", 6)

        actions = tk.Frame(self.tab_status, bg=BG)
        actions.pack(fill="x", padx=12)
        ttk.Button(actions, text="修改昵称",
                   command=self._rename).pack(side="left")
        ttk.Button(actions, text="调整为桌面右下",
                   command=self._reset_position).pack(side="left", padx=6)
        if len(self.store.team()) > 1:
            ttk.Button(actions, text="寄存到 BOX 仓库",
                       command=lambda: self._box_in(self.store.pet.uid)).pack(side="right", padx=6)
        if len(self.store.pets) > 1:
            ttk.Button(actions, text="放生（移除）",
                       command=self._release).pack(side="right")
        self.refresh_data()

    def _add_bar(self, master: tk.Frame, label: str, key: str, row: int) -> None:
        tk.Label(master, text=label, font=(CN_FONT, 9), bg=CARD,
                 width=6, anchor="w").grid(row=row, column=0, sticky="w", pady=3)
        bar = Bar(master)
        bar.grid(row=row, column=1, sticky="w", padx=6)
        val = tk.Label(master, text="0", font=(CN_FONT, 9), bg=CARD, width=8, anchor="w")
        val.grid(row=row, column=2, sticky="w")
        self._stat_bars[key] = bar
        self._stat_values[key] = val

    def _rename(self) -> None:
        pet = self.store.pet
        name = simpledialog.askstring("昵称", f"给{pet.display_name()}起个名字：", parent=self)
        if name is not None:
            pet.nickname = name.strip()[:12]
            self.app.pet_window.refresh()
            self.refresh_all()

    def _release(self) -> None:
        pet = self.store.pet
        if not messagebox.askyesno("放生", f"确定和{pet.display_name()}说再见吗？", parent=self):
            return
        self.store.release(pet.uid)
        self.app.load_sprite()
        self.refresh_all()

    def _reset_position(self) -> None:
        sw, _ = self.app.pet_window.screen_size()
        self.app.pet_window.x = sw - self.app.pet_window.win_w - 30
        self.app.pet_window.y = self.app.pet_window.floor_y() - self.app.pet_window.win_h
        self.app.save()

    # ---------------------------------------------------------------- 养育页
    def _rebuild_care(self) -> None:
        self.tab_care.clear()
        host = self.tab_care.inner
        pet = self.store.pet

        info = tk.Frame(host, bg=CARD, padx=12, pady=10)
        info.pack(fill="x", padx=12, pady=10)
        left = pet.remaining()
        hint = pet.activity_zh if pet.activity != "idle" else "闲着没事"
        tk.Label(info, text=f"{hint}" + (f"（还剩 {int(left // 60)} 分 {int(left % 60)} 秒）"
                                         if pet.activity == "work" else ""),
                 font=(CN_FONT, 10), bg=CARD).pack(side="left")
        for text, cmd in (("训练一下", lambda: self.app.action("train")),
                          ("睡觉 / 叫醒", lambda: self.app.action("sleep"))):
            ttk.Button(info, text=text, command=cmd).pack(side="right", padx=4)
        for mins in (5, 15, 30):
            ttk.Button(info, text=f"打工 {mins} 分",
                       command=lambda m=mins: self.app.action("work", minutes=m)).pack(
                side="right", padx=2)

        groups = (("食物", "food"), ("饮品", "drink"), ("清洁", "care"), ("玩具", "toy"),
                  ("药品", "medicine"))
        per_row = 4          # 一行四个按钮，窄窗口/高 DPI 下也不会挤出卡片
        for title, cat in groups:
            frame = tk.LabelFrame(host, text=title, bg=CARD, padx=10, pady=8,
                                  font=(CN_FONT, 9), fg="#444")
            frame.pack(fill="x", padx=12, pady=4)
            for i, item in enumerate(items.by_category(cat)):
                count = self.store.item_count(item.id)
                text = f"{item.zh} ×{count}"
                btn = ttk.Button(frame, text=text, width=16,
                                 command=lambda i=item.id: self.app.do_item(i))
                btn.grid(row=i // per_row, column=i % per_row,
                         sticky="w", padx=3, pady=2)
                if count == 0:
                    btn.state(["disabled"])

    # ---------------------------------------------------------------- 商店页
    def _rebuild_shop(self) -> None:
        self.tab_shop.clear()
        host = self.tab_shop.inner
        from core.items import SHOP_ORDER

        head = tk.Frame(host, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text=self._wallet_text(), font=(CN_FONT, 11, "bold"),
                 bg=BG, fg="#e8590c").pack(side="left")
        tk.Label(head, text="滚轮翻页 · 打工可以赚零花钱（右键桌宠 → 打工赚钱）",
                 font=(CN_FONT, 9), bg=BG, fg="#777").pack(side="right")

        for cat in SHOP_ORDER:
            frame = tk.LabelFrame(host, text=items.CAT_ZH.get(cat, cat),
                                  bg=CARD, padx=10, pady=6, font=(CN_FONT, 9), fg="#444")
            frame.pack(fill="x", padx=12, pady=4)
            for item in items.by_category(cat):
                row = tk.Frame(frame, bg=CARD)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=item.zh, font=(CN_FONT, 9), bg=CARD,
                         width=12, anchor="w").pack(side="left")
                tk.Label(row, text=item.desc, font=(CN_FONT, 8), bg=CARD,
                         fg="#888", anchor="w").pack(side="left", fill="x", expand=True)
                tk.Label(row, text=f"{item.price}元", font=(CN_FONT, 9), bg=CARD,
                         width=6, anchor="e").pack(side="left")
                ttk.Button(row, text="买1", width=4,
                           command=lambda i=item.id: self._buy(i, 1)).pack(side="right")
                ttk.Button(row, text="买5", width=4,
                           command=lambda i=item.id: self._buy(i, 5)).pack(side="right", padx=2)
                tk.Label(row, text=f"持有 {self.store.item_count(item.id)}",
                         font=(CN_FONT, 8), bg=CARD, fg="#666", width=7,
                         anchor="e").pack(side="right")

    def _buy(self, item_id: str, qty: int) -> None:
        ok, msg = self.store.buy(item_id, qty)
        if ok:
            self.app.pet_window.say(msg, secs=3)
        else:
            messagebox.showinfo("买不了", msg, parent=self)
        self.refresh_all()

    # ---------------------------------------------------------------- 图鉴页
    def _rebuild_dex(self) -> None:
        self.tab_dex.clear()
        dex = self.store.dex

        top = tk.Frame(self.tab_dex.inner, bg=BG)
        top.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(top, text="宝可梦图鉴", font=(CN_FONT, 12, "bold"), bg=BG).pack(side="left")
        self.dex_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.dex_var, width=14)
        entry.pack(side="right")
        entry.bind("<Return>", lambda e: self._search_dex())
        ttk.Button(top, text="查找/添加", command=self._search_dex).pack(side="right", padx=4)

        total = len(dex.entries) or 1
        seen = len([s for s in self.store.met if dex.has(s)])
        got = len([s for s in self.store.caught if dex.has(s)])
        stat = tk.Frame(self.tab_dex.inner, bg=BG)
        stat.pack(fill="x", padx=8)
        self.dex_stat = tk.Label(stat, text="", font=(CN_FONT, 9), bg=BG, fg="#555")
        self.dex_stat.pack(side="left")
        self.dex_progress = Bar(stat, width=200, height=10, bg_color=BG)
        self.dex_progress.pack(side="right")
        self.dex_progress.set(got / total, "#37b24d")
        self.dex_stat.configure(
            text=f"完成度 {got}/{total}（{got / total * 100:.0f}%）　"
                 f"已收服 {got}　见过未见 {seen}　未发现 {total - seen}")

        # 固定高度 + 自动换行：悬停切换详情时不会把下面的卡片顶来顶去，
        # 也不会因为字体变大而溢出（Tk 的 Frame 不裁剪子控件）。
        self.dex_tip = tk.Label(self.tab_dex.inner, bg=CARD, fg="#666", relief="flat",
                                font=(CN_FONT, 9), justify="left", anchor="nw", padx=8, pady=6,
                                height=3, wraplength=690,
                                text=self.DEX_HINT)
        self.dex_tip.pack(fill="x", padx=8, pady=(4, 6))

        self.dex_grid = tk.Frame(self.tab_dex.inner, bg=BG)
        self.dex_grid.pack(fill="both", expand=True, padx=6)
        self.dex_filter: Optional[List[int]] = None
        self._render_dex()

    def _search_dex(self) -> None:
        kw = self.dex_var.get().strip()
        dex = self.store.dex
        if not kw:
            self.dex_filter = None
            self._render_dex()
            return
        if kw.isdigit():
            sid = int(kw)
            if not dex.has(sid):
                self.app.pet_window.say("正在从 PokéAPI 查询这只宝可梦…", secs=4)
                self.after(50, lambda: self._lookup_online(sid))
                return
            self.dex_filter = dex.line_members(sid)
        else:
            hits = dex.search(kw)
            if not hits:
                messagebox.showinfo("没有找到", "试试更容易的关键字，或直接输入编号", parent=self)
                return
            members: List[int] = []
            for sid in hits:
                for m in dex.line_members(sid):
                    if m not in members:
                        members.append(m)
            self.dex_filter = sorted(members)
        self._render_dex()

    def _lookup_online(self, sid: int) -> None:
        if self.store.dex.ensure_online(sid):
            self.dex_filter = self.store.dex.line_members(sid)
            self._render_dex()
        else:
            messagebox.showinfo("查询失败", "联网查询失败，请检查网络后再试", parent=self)

    def _render_dex(self) -> None:
        for child in list(self.dex_grid.winfo_children()):
            child.destroy()
        dex = self.store.dex
        ids = self.dex_filter if self.dex_filter is not None else dex.all_ids()
        owned = {}
        for p in self.store.pets:
            owned.setdefault(p.species_id, p)
        # 列数跟着可用宽度和字体大小走：高 DPI / 放大字体时自动减少列数，
        # 否则四列挤在一起会把卡片内容压到相邻格子里。
        THUMB = 58
        try:
            from tkinter import font as tkfont

            f8 = tkfont.Font(font=(CN_FONT, 8))
            # 用最短的一行做基准就够了：文字全部带 wraplength，会自动换行
            need = THUMB + 16 + f8.measure("#0000　电") + 26
        except Exception:  # noqa: BLE001
            need = 190
        real_width = self.dex_grid.winfo_width()
        avail = real_width if real_width > 1 else max(560, self.winfo_width() - 40)
        columns = max(2, min(5, int(avail // max(165, need))))
        text_w = max(74, int(avail // columns - THUMB - 34))   # 文字栏宽度，超出就换行
        self._dex_layout = (int(avail), int(need), columns, int(text_w))

        if real_width <= 1:
            # 窗口还没真正排版：先按估算画一版，首帧结束后再用真实宽度重排
            self._schedule_reflow()

        for col in range(6):
            self.dex_grid.columnconfigure(col, weight=0, minsize=0)
        for col in range(columns):
            self.dex_grid.columnconfigure(col, weight=1, uniform="dex", minsize=150)

        for i, sid in enumerate(ids):
            entry = dex.get(sid)
            if not entry:
                continue
            met = sid in self.store.met
            caught = sid in self.store.caught
            border = "#37b24d" if caught else (ACCENT if met else "#e0e0e0")
            # 不锁死宽高：让卡片跟着字体走。锁死高度时，字体一放大内容就会
            # 溢出到相邻卡片上（Tk 的 Frame 不裁剪子控件），看起来像「乱码」。
            card = tk.Frame(self.dex_grid, bg=CARD, highlightthickness=1,
                            highlightbackground=border, padx=8, pady=6)
            card.grid(row=i // columns, column=i % columns, padx=5, pady=5, sticky="nsew")

            self._thumb_label(card, sid, bool(met)).pack(side="left", padx=(0, 8))
            info = tk.Frame(card, bg=CARD)
            info.pack(side="left", fill="both", expand=True)
            name = dex.name(sid) if met else "？？？"
            tk.Label(info, text=name, font=(CN_FONT, 10, "bold"), bg=CARD,
                     fg="#222" if met else "#999", wraplength=text_w,
                     justify="left", anchor="w").pack(anchor="w")
            tk.Label(info, text=f"#{sid:04d}　{dex.types_zh(sid)}", font=(CN_FONT, 8),
                     bg=CARD, fg="#777", wraplength=text_w, justify="left",
                     anchor="w").pack(anchor="w")

            owner = owned.get(sid)
            if owner:
                where = "BOX 仓库" if owner.in_box else "同行中"
                tip, color = f"Lv.{owner.level} · {where}", ACCENT
            elif caught:
                tip, color = "已收服过", "#37b24d"
            elif met:
                tip, color = "见过一面", "#4c6ef5"
            else:
                tip, color = "未相遇", "#aaa"
            tk.Label(info, text=tip, font=(CN_FONT, 8), bg=CARD, fg=color,
                     wraplength=text_w, justify="left", anchor="w").pack(
                anchor="w", pady=(6, 0))
            self._bind_tooltip(card, dex, sid, met, caught)
            card.bind("<Button-1>", lambda e, s=sid: self._dex_click(s))
            for w in card.winfo_children():
                w.bind("<Button-1>", lambda e, s=sid: self._dex_click(s))
                for sub in w.winfo_children():
                    sub.bind("<Button-1>", lambda e, s=sid: self._dex_click(s))

    def _bind_tooltip(self, card: tk.Frame, dex, sid: int, met: bool, caught: bool) -> None:
        """把详细信息挂到悬停上：未相遇的不会剧透图鉴说明。"""
        state = "已收服" if caught else ("见过一面" if met else "未相遇")
        lines = [f"{dex.name(sid) if met else '未收录'}　#{sid:04d}",
                 f"属性 {dex.types_zh(sid)}　·　状态 {state}"]
        evos = dex.evolutions_of(sid)
        if evos:
            names = [dex.name(int(e["to"])) for e in evos]
            if len(names) > 4:      # 伊布这种分支多的，别把提示区撑爆
                shown = "、".join(names[:4])
                lines.append(f"可进化为：{shown} 等 {len(names)} 种")
            else:
                lines.append(f"可进化为：{'、'.join(names)}")
        else:
            lines.append("进化：已是最终形态")
        text = "\n".join(lines)

        def show(_e: tk.Event) -> None:
            self.dex_tip.configure(text=text)

        def hide(_e: tk.Event) -> None:
            self.dex_tip.configure(text=self.DEX_HINT)

        for widget in (card,) + tuple(card.winfo_children()):
            widget.bind("<Enter>", show)
            widget.bind("<Leave>", hide)
            for sub in widget.winfo_children():
                sub.bind("<Enter>", show)
                sub.bind("<Leave>", hide)

    def _thumb_label(self, master: tk.Frame, sid: int, met: bool) -> tk.Label:
        # 未相遇的条目不下载真实素材，既保护悬念也省流量
        if not met:
            return tk.Label(master, bg="#ececec", text="？", width=3, height=2,
                            fg="#9aa0a6", font=(CN_FONT, 13, "bold"))
        label = tk.Label(master, bg=CARD, text="…", fg="#bbb", width=3, height=2)

        def apply(img) -> None:
            # 关键：清掉 width/height，否则标签按「字符数」算出的宽度比 54px 的
            # 缩略图还窄，图片会被裁成一条竖条（看起来像只显示了一半）。
            label.configure(image=img, text="", width=0, height=0)
            label.image = img

        if sid in self.thumbs:
            img = self.thumbs[sid]
            if img is not None:
                apply(img)
            return label

        def on_ready(img) -> None:
            self.thumbs[sid] = img
            if img is not None and label.winfo_exists():
                apply(img)

        self.app.sprites.load_thumb_async(sid, False, self.store.dex.en(sid), on_ready, size=54)
        return label

    def _dex_click(self, sid: int) -> None:
        pets = [p for p in self.store.pets if p.species_id == sid]
        owner = pets[0] if pets else None
        if owner:
            if owner.in_box:
                ok, msg = self.store.from_box(owner.uid)
                if not ok:
                    messagebox.showinfo("取不出来", msg, parent=self)
                    return
                self.app.pet_window.say(msg, secs=3.5)
            else:
                self.store.set_active(owner.uid)
                self.app.pet_window.say(f"换成了{owner.display_name()}", secs=3)
            self.app.load_sprite()
            self.refresh_all()
            return
        answer = messagebox.askyesno(
            "相遇新伙伴", f"要和{self.store.dex.name(sid)}成为伙伴吗？\n"
                        f"（它会以 Lv.1 加入你的队伍）", parent=self)
        if not answer:
            return
        pet, boxed = self.store.adopt(sid, how="相遇")
        self.app.load_sprite()
        tail = "" if not boxed else "（队伍满了，先放进了 BOX 仓库）"
        self.app.pet_window.say(f"遇到了{pet.display_name()}！{tail}", secs=4)
        self.refresh_all()

    # ---------------------------------------------------------------- 探索页
    def _rebuild_explore(self) -> None:
        self.tab_explore.clear()
        host = self.tab_explore.inner

        head = tk.Frame(host, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text="去探险", font=(CN_FONT, 12, "bold"), bg=BG).pack(side="left")
        balls = sum(self.store.item_count(i.id) for i in items.by_category("ball"))
        foods = sum(self.store.item_count(i.id) for i in items.by_category("food"))
        tk.Label(head, text=f"精灵球 {balls} 个　树果类食物 {foods} 份",
                 font=(CN_FONT, 9), bg=BG, fg="#777").pack(side="left", padx=8)

        card = tk.Frame(host, bg=CARD, padx=12, pady=10)
        card.pack(fill="x", padx=12, pady=6)
        ready, left = self.store.explore_ready()
        if balls <= 0:
            tip = "背包里没有精灵球了，先去商店买一些，再出发吧。"
        elif ready:
            tip = "附近的草丛里有动静。出发去看看会遇到谁吧！"
        else:
            tip = f"还在回来的路上……再等 {int(left)} 秒才能再出发。"
        tk.Label(card, text=tip, font=(CN_FONT, 10), bg=CARD, fg="#555",
                 justify="left", wraplength=520).pack(anchor="w")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="出发去草丛", command=self._explore).pack(side="left")
        ttk.Button(row, text="去商店补货", command=lambda: self.notebook.select(2)).pack(
            side="left", padx=6)

        box = tk.LabelFrame(host, text="玩法说明", bg=CARD, padx=10, pady=8,
                            font=(CN_FONT, 9), fg="#444")
        box.pack(fill="x", padx=12, pady=6)
        tk.Label(box, justify="left", bg=CARD, font=(CN_FONT, 9), fg="#555", text=(
            "· 每次探险可能遇到一只野生宝可梦，等级随机，也可能稀有的那种\n"
            "· 先「投喂树果」让它放松，放松程度越高，捕捉成功率越高\n"
            "· 每种球的成功率不同：精灵球 < 超级球 < 高级球 << 大师球\n"
            "· 每次失手它都会更警觉，最多 8 个回合，之后它就会跑掉"),
        ).pack(anchor="w")

        log_box = tk.LabelFrame(host, text="最近探险记录", bg=CARD,
                                padx=10, pady=8, font=(CN_FONT, 9), fg="#444")
        log_box.pack(fill="x", padx=12, pady=6)
        logs = list(reversed(self.store.explore_log)) or ["（还没有出去走过）"]
        for line in logs[:10]:
            tk.Label(log_box, text=line, font=(CN_FONT, 9), bg=CARD, fg="#555",
                     anchor="w").pack(fill="x")

    def _explore(self) -> None:
        self.app.explore()
        self.after(300, self.refresh_all)

    # ---------------------------------------------------------------- 仓库页
    def _rebuild_box(self) -> None:
        self.tab_box.clear()
        team = self.store.team()
        boxed = self.store.box()
        inner = self.tab_box.inner

        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(head, text="同伴仓库", font=(CN_FONT, 12, "bold"), bg=BG).pack(side="left")
        tk.Label(head, text=f"同行 {len(team)}/{TEAM_LIMIT}　仓库 {len(boxed)}　总计 {len(self.store.pets)}",
                 font=(CN_FONT, 9), bg=BG, fg="#777").pack(side="left", padx=8)

        tk.Label(inner, text="同行队伍", font=(CN_FONT, 10, "bold"), bg=BG,
                 fg="#444").pack(anchor="w", padx=12, pady=(6, 2))
        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill="x", padx=10)
        for col in range(2):
            grid.columnconfigure(col, weight=1, uniform="team")
        text_w = max(120, (self.winfo_width() or 820) // 2 - 150)
        for i, pet in enumerate(team):
            self._pet_card(grid, pet, False, text_w).grid(
                row=i // 2, column=i % 2, padx=5, pady=5, sticky="nsew")

        tk.Label(inner, text="BOX 仓库", font=(CN_FONT, 10, "bold"), bg=BG,
                 fg="#444").pack(anchor="w", padx=12, pady=(12, 2))
        if not boxed:
            tk.Label(inner, text="仓库是空的。队伍最多带 6 位，多余的伙伴会自动寄存到这里。",
                     font=(CN_FONT, 9), bg=BG, fg="#888", anchor="w").pack(
                fill="x", padx=12, pady=4)
            return
        grid2 = tk.Frame(inner, bg=BG)
        grid2.pack(fill="x", padx=10)
        for col in range(2):
            grid2.columnconfigure(col, weight=1, uniform="team")
        for i, pet in enumerate(boxed):
            self._pet_card(grid2, pet, True, text_w).grid(
                row=i // 2, column=i % 2, padx=5, pady=5, sticky="nsew")

    def _pet_card(self, parent: tk.Frame, pet, in_box: bool, text_w: int = 220) -> tk.Frame:
        """一张「实体卡片」：把这只宝可梦的状态与可施加的行为都摆出来。"""
        dex = self.store.dex
        active = (not in_box) and pet.uid == self.store.active_uid
        border = ACCENT if active else "#e0e0e0"
        card = tk.Frame(parent, bg=CARD, padx=10, pady=8, highlightthickness=1,
                        highlightbackground=border)
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        self._thumb_label(top, pet.species_id, True).pack(side="left")

        info = tk.Frame(top, bg=CARD)
        info.pack(side="left", fill="both", expand=True, padx=8)
        tag = " ●同行" if active else ("（BOX）" if in_box else "")
        tk.Label(info, text=f"{pet.display_name()}{tag}", font=(CN_FONT, 11, "bold"),
                 bg=CARD, wraplength=text_w, justify="left", anchor="w").pack(anchor="w")
        tk.Label(info, text=f"Lv.{pet.level}　{dex.types_zh(pet.species_id)}",
                 font=(CN_FONT, 9), bg=CARD, fg="#666", wraplength=text_w,
                 justify="left", anchor="w").pack(anchor="w")
        evo = dex.evolutions_of(pet.species_id)
        evo_text = ("可进化：" + "、".join(dex.name(int(e["to"])) for e in evo)) if evo \
            else "已是最终形态"
        tk.Label(info, text=f"{evo_text}　羁绊{int(pet.bond)}",
                 font=(CN_FONT, 8), bg=CARD, fg="#888", wraplength=text_w,
                 justify="left", anchor="w").pack(anchor="w")
        tk.Label(info, text=f"获得途径：{pet.met_by}　照顾 {pet.total_care} 次",
                 font=(CN_FONT, 8), bg=CARD, fg="#999", wraplength=text_w,
                 justify="left", anchor="w").pack(anchor="w")

        # 按钮分两行：高 DPI 下一个卡片放不下四个带文字的按钮，挤出去会盖到
        # 相邻卡片上（Tk 不会裁剪溢出的子控件）。
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        if in_box:
            ttk.Button(row, text="带到身边",
                       command=lambda uid=pet.uid: self._box_out(uid)).pack(side="left")
        elif not active:
            ttk.Button(row, text="设为同行",
                       command=lambda uid=pet.uid: self._switch(uid)).pack(side="left")
        if not in_box and len(self.store.team()) > 1:
            ttk.Button(row, text="寄存到 BOX",
                       command=lambda uid=pet.uid: self._box_in(uid)).pack(side="left", padx=4)

        row2 = tk.Frame(card, bg=CARD)
        row2.pack(fill="x", pady=(4, 0))
        ttk.Button(row2, text="改名",
                   command=lambda uid=pet.uid: self._rename_uid(uid)).pack(side="left")
        if len(self.store.pets) > 1:
            ttk.Button(row2, text="放生",
                       command=lambda uid=pet.uid: self._release_uid(uid)).pack(side="left", padx=4)
        return card

    def _switch(self, uid: str) -> None:
        self.app.switch_pet(uid)
        self.refresh_all()

    def _box_in(self, uid: str) -> None:
        self.app.send_to_box(uid)
        self.refresh_all()

    def _box_out(self, uid: str) -> None:
        self.app.take_from_box(uid)
        self.refresh_all()

    def _rename_uid(self, uid: str) -> None:
        pet = self.store.find(uid)
        if not pet:
            return
        name = simpledialog.askstring("昵称", f"给{pet.display_name()}起个名字：", parent=self)
        if name is None:
            return
        pet.nickname = name.strip()[:12]
        self.store.save()
        self.refresh_all()

    def _release_uid(self, uid: str) -> None:
        pet = self.store.find(uid)
        if not pet:
            return
        if not messagebox.askyesno("放生", f"确定和{pet.display_name()}说再见吗？", parent=self):
            return
        self.store.release(uid)
        self.app.load_sprite()
        self.refresh_all()

    # ---------------------------------------------------------------- 蚕室页
    def _rebuild_farm(self) -> None:
        self.tab_farm.clear()
        host = self.tab_farm.inner
        worms = self.store.worms

        head = tk.Frame(host, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text="蚕室", font=(CN_FONT, 12, "bold"), bg=BG).pack(side="left")
        tk.Label(head, text=f"蚕 {len(worms)} 只　桑叶 {self.store.item_count('mulberry')} 片　"
                            f"蚕丝 {self.store.item_count('silk')} 个",
                 font=(CN_FONT, 9), bg=BG, fg="#777").pack(side="left", padx=8)
        ttk.Button(head, text="买蚕卵（60元）", command=self._buy_worm).pack(side="right")

        if not worms:
            tk.Label(host, text="蚕室空空的。买一枚蚕卵开始吧——"
                                "它是会随时间自己成长的独立小生命。",
                     font=(CN_FONT, 10), bg=BG, fg="#888", pady=40).pack()
        grid = tk.Frame(host, bg=BG)
        grid.pack(fill="x", padx=10, pady=6)

        for i, worm in enumerate(worms):
            card = tk.Frame(grid, bg=CARD, padx=10, pady=8, highlightthickness=1,
                            highlightbackground="#dcdcdc")
            card.grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="nsew")
            grid.columnconfigure(i % 2, weight=1)

            alive = worm.alive
            color = "#222" if alive else "#999"
            tk.Label(card, text=f"{worm.emoji} {worm.stage_name if alive else '空空的茧'}",
                     font=(CN_FONT, 13, "bold"), bg=CARD, fg=color).pack(anchor="w")
            tk.Label(card, text=worm.status_zh(), font=(CN_FONT, 9), bg=CARD,
                     fg="#777").pack(anchor="w")

            if alive and not worm.mature:
                bar = Bar(card, width=190, height=9)
                bar.pack(anchor="w", pady=4)
                bar.set(worm.progress / 100.0, "#74c0fc")
                tk.Label(card, text=f"成长 {int(worm.progress)}%", font=(CN_FONT, 8),
                         bg=CARD, fg="#666").pack(anchor="w")

            needs = tk.Frame(card, bg=CARD)
            needs.pack(anchor="w", pady=(4, 0))
            for label, value in (("饥饿", worm.hunger), ("脏污", worm.dirty)):
                tk.Label(needs, text=f"{label} {int(value)}%", font=(CN_FONT, 8),
                         bg=CARD, fg=stat_color(100 - value), width=9,
                         anchor="w").pack(side="left")

            row = tk.Frame(card, bg=CARD)
            row.pack(anchor="w", pady=(6, 0))
            if alive:
                ttk.Button(row, text="投喂桑叶",
                           command=lambda w=worm: self._worm_feed(w)).pack(side="left")
                ttk.Button(row, text="清扫蚕室",
                           command=lambda w=worm: self._worm_clean(w)).pack(side="left", padx=4)
                if worm.silk_ready:
                    ttk.Button(row, text="采收蚕丝",
                               command=lambda w=worm: self._worm_harvest(w)).pack(side="left")
            else:
                ttk.Button(row, text="清理掉",
                           command=lambda w=worm: self._worm_remove(w)).pack(side="left")

        if self.store.item_count("silk") > 0:
            sell = tk.Frame(host, bg=BG)
            sell.pack(fill="x", padx=12, pady=6)
            ttk.Button(sell, text=f"把蚕丝卖给行商（{items.SILK_PRICE}元/个）",
                       command=self._sell_silk).pack(side="right")

    def _buy_worm(self) -> None:
        ok, msg = self.store.buy("worm_egg", 1)
        if not ok:
            messagebox.showinfo("买不了", msg, parent=self)
            return
        worm = self.store.add_silkworm()
        if worm is None:  # 蚕室满了：把这一笔退回去
            self.store.take_item("worm_egg", 1)
            self.store.add_coins(items.get("worm_egg").price)
            self.store.save()
            messagebox.showinfo("蚕室满了", "最多同时养 8 只蚕", parent=self)
            return
        self.app.pet_window.say("蚕室里多了一枚蚕卵…", secs=4)
        self.refresh_all()

    def _need_mulberry(self) -> bool:
        if self.store.item_count("mulberry") > 0:
            return True
        ok, msg = self.store.buy("mulberry", 1)
        if ok:
            return True
        messagebox.showinfo("没有桑叶", f"{msg}\n去商店买些桑叶再来喂蚕吧。", parent=self)
        return False

    def _worm_feed(self, worm) -> None:
        if not self._need_mulberry():
            return
        if not worm.feed():
            self.app.pet_window.say("它现在吃不下桑叶", secs=2.5)
            return
        self.store.take_item("mulberry", 1)
        self.app.pet_window.say("沙沙沙…蚕在吃桑叶", secs=2.6)
        self.refresh_all()

    def _worm_clean(self, worm) -> None:
        if not worm.clean():
            self.app.pet_window.say("蚕室还挺干净的", secs=2.2)
            return
        self.app.pet_window.say("蚕室打扫干净了，舒服～", secs=2.6)
        self.refresh_all()

    def _worm_harvest(self, worm) -> None:
        got = worm.harvest()
        if got <= 0:
            return
        self.store.bag["silk"] = self.store.item_count("silk") + got
        self.app.pet_window.say(f"收获了 {got} 个蚕丝！", secs=3.4)
        self.refresh_all()

    def _worm_remove(self, worm) -> None:
        self.store.remove_worm(worm.id)
        self.refresh_all()

    def _sell_silk(self) -> None:
        count = self.store.item_count("silk")
        ok, msg = self.store.sell("silk", count)
        if not ok:
            messagebox.showinfo("卖不了", msg, parent=self)
            return
        self.app.pet_window.say(msg, secs=3.4)
        self.refresh_all()

    # ---------------------------------------------------------------- 设置页
    def _rebuild_settings(self) -> None:
        self.tab_settings.clear()
        host = self.tab_settings.inner       # 设置项变多了，整页可滚动
        setting = self.store.settings

        frame = tk.LabelFrame(host, text="桌宠外观与行为", bg=CARD,
                              padx=12, pady=10, font=(CN_FONT, 9), fg="#444")
        frame.pack(fill="x", padx=12, pady=10)

        row = tk.Frame(frame, bg=CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="精灵大小", font=(CN_FONT, 9), bg=CARD, width=10,
                 anchor="w").pack(side="left")
        self.size_var = tk.StringVar(value=setting.get("size", "中"))
        box = ttk.Combobox(row, textvariable=self.size_var, width=6,
                           values=list(SIZE_PRESETS.keys()), state="readonly")
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", self._on_size_change)

        flags = (
            ("always_top", "窗口总是置顶"), ("walk", "允许自主走动"),
            ("follow_mouse", "跟随鼠标"), ("show_bubble", "显示气泡对话"),
            ("show_stats", "显示状态卡"), ("shiny", "闪光形态"),
            ("night_mode", "夜间自动睡觉"),
        )
        for key, text in flags:
            var = tk.BooleanVar(value=bool(setting.get(key, False)))
            cb = tk.Checkbutton(frame, text=text, variable=var, font=(CN_FONT, 9), bg=CARD,
                                anchor="w",
                                command=lambda k=key, v=var: self._on_flag(k, v.get()))
            cb.pack(fill="x", pady=1)

        utils = tk.Frame(host, bg=BG)
        utils.pack(fill="x", padx=12, pady=6)
        cache_mb = self.app.sprites.cache_size() / 1024 / 1024
        tk.Label(utils, text=f"素材缓存 {cache_mb:.1f} MB", font=(CN_FONT, 9),
                 bg=BG).pack(side="left")
        ttk.Button(utils, text="清理缓存", command=self._clear_cache).pack(side="left", padx=6)
        ttk.Button(utils, text="打开存档目录", command=self._open_home).pack(side="left")

        sandbox = tk.LabelFrame(host, text="沙盒", bg=CARD, padx=12, pady=10,
                                font=(CN_FONT, 9), fg="#444")
        sandbox.pack(fill="x", padx=12, pady=(0, 6))
        dex = self.store.dex
        tk.Label(sandbox, bg=CARD, font=(CN_FONT, 9), fg="#555", anchor="w",
                 text=f"图鉴 {len(self.store.caught)}/{len(dex.entries)}　"
                      f"同伴 {len(self.store.pets)} 位（同行 {len(self.store.team())}，"
                      f"仓库 {len(self.store.box())}）").pack(anchor="w")
        row = tk.Frame(sandbox, bg=CARD)
        row.pack(fill="x", pady=(6, 2))
        ttk.Button(row, text="一键全开（图鉴 + 全体满级）",
                   command=self._unlock_all).pack(side="left")
        tk.Label(sandbox, bg=CARD, font=(CN_FONT, 8), fg="#999", anchor="w",
                 text="把全部图鉴点亮，每只宝可梦都以 Lv.100 加入；同行最多 6 位，"
                      "其余自动进 BOX。").pack(anchor="w")

        about = tk.Frame(host, bg=BG)
        about.pack(fill="both", expand=True, padx=12, pady=10)
        tk.Label(about, justify="left", bg=BG, font=(CN_FONT, 9), fg="#666", text=(
            "玩法提示\n"
            "· 拖动可以把宠物拎起来，松手会掉回桌面（会反弹哦）\n"
            "· 单击抚摸、双击打开这个面板、右键打开快捷菜单\n"
            "· 数值会随时间下降，离开电脑时它也在慢慢变饿\n"
            "· 训练 / 玩耍 / 打工都会给经验，等级到了就能进化\n"
            "· 有些宝可梦需要「进化石」才能进化，去商店买一块\n"
            "\n素材来源：PokeAPI / Pokémon Showdown 公开图库，仅用于个人学习。\n"
            "宝可梦是 Nintendo/Creatures/GAME FREAK 的商标。"),
        ).pack(anchor="w")

    def _unlock_all(self) -> None:
        """沙盒：图鉴全开 + 全部宝可梦满级入队（弹窗与执行在 App 里统一）。"""
        before = len(self.store.caught)
        added, _total = self.app.unlock_all()
        if added <= 0 and len(self.store.caught) == before:
            return                   # 用户取消了
        self.refresh_all()
        self.select_tab("图鉴")

    def _on_size_change(self, _event=None) -> None:
        self.store.settings["size"] = self.size_var.get()
        self.app.store.save()
        self.app.load_sprite()
        self.app.pet_window.apply_settings()

    def _on_flag(self, key: str, value: bool) -> None:
        self.store.settings[key] = value
        self.app.pet_window.apply_settings()
        self.store.save()
        if key == "shiny":
            self.app.load_sprite()

    def _clear_cache(self) -> None:
        self.app.sprites.clear_cache()
        self.thumbs.clear()
        messagebox.showinfo("完成", "素材缓存已清理，下次显示时会重新下载", parent=self)

    def _open_home(self) -> None:
        path = self.store.home
        try:
            if platform.system() == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo("提示", f"无法打开：{exc}\n路径：{path}", parent=self)
