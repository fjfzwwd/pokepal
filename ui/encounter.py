# -*- coding: utf-8 -*-
"""野外相遇窗口。

原作里「削弱再抓」在桌宠场景下不合适（我们只有一只站在桌面上的同伴），
所以这里改成「投喂 + 投球」：树果让它放松，放松程度越高成功率越高，
但每次失手它都会更警惕，而且随时可能跑掉。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import List

from core import items
from core.encounter import MAX_TURNS, Encounter
from ui.widgets import ACCENT, BG, CARD, CN_FONT, Bar, place_centered, show_transient


class EncounterWindow(tk.Toplevel):
    def __init__(self, master, app, wild: dict):
        super().__init__(master)
        self.app = app
        self.store = app.store
        self.dex = app.store.dex
        self.wild = wild
        self.enc = Encounter(wild["species_id"], wild["level"], wild.get("shiny", False))
        self.known = wild["species_id"] in self.store.met
        self._ended = False

        self.title("野外相遇")
        self.geometry("440x600")
        self.resizable(False, True)
        self.configure(bg=BG)
        place_centered(self, 440, 600, 0.25)

        self._build()
        show_transient(self, master)
        self._say_initial()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(head, text="野生的宝可梦出现了！", font=(CN_FONT, 13, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        if self.wild.get("rare"):
            tk.Label(head, text="稀有！", font=(CN_FONT, 9, "bold"),
                     bg=BG, fg="#e8590c").pack(side="right")

        stage = tk.Frame(self, bg=CARD, padx=12, pady=10)
        stage.pack(fill="x", padx=14, pady=6)

        self.img = tk.Label(stage, bg=CARD, text="…", fg="#bbb", width=10, height=6)
        self.img.pack()
        self.app.sprites.load_thumb_async(
            self.wild["species_id"], bool(self.wild.get("shiny")) and
            bool(self.store.settings.get("shiny", False)),
            self.dex.en(self.wild["species_id"]), self._on_image, size=120)

        self.name_label = tk.Label(stage, text="", font=(CN_FONT, 14, "bold"), bg=CARD)
        self.name_label.pack(pady=(6, 0))
        self.meta_label = tk.Label(stage, text="", font=(CN_FONT, 9), bg=CARD, fg="#666")
        self.meta_label.pack()

        relax = tk.Frame(stage, bg=CARD)
        relax.pack(fill="x", pady=(8, 2))
        tk.Label(relax, text="放松程度", font=(CN_FONT, 9), bg=CARD).pack(side="left")
        self.relax_bar = Bar(relax, width=190, height=10)
        self.relax_bar.pack(side="right")
        self.relax_label = tk.Label(stage, text="", font=(CN_FONT, 9), bg=CARD, fg="#777")
        self.relax_label.pack(anchor="w")

        self.turn_label = tk.Label(stage, text="", font=(CN_FONT, 8), bg=CARD, fg="#999")
        self.turn_label.pack(anchor="w", pady=(2, 0))

        log_frame = tk.Frame(self, bg=CARD)
        log_frame.pack(fill="both", expand=True, padx=14, pady=6)
        self.log = tk.Text(log_frame, height=9, font=(CN_FONT, 9), relief="flat",
                           bg=CARD, fg="#333", wrap="word", spacing2=2)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set, state="disabled")
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        self.btn_bait = ttk.Button(bar, text="投喂树果", command=self._bait)
        self.btn_bait.pack(side="left")
        self.btn_throw = ttk.Button(bar, text="投出精灵球", command=self._throw)
        self.btn_throw.pack(side="left", padx=6)
        self.btn_flee = ttk.Button(bar, text="悄悄离开", command=self._leave)
        self.btn_flee.pack(side="right")
        self.action_buttons: List[ttk.Button] = [self.btn_bait, self.btn_throw, self.btn_flee]

        self._refresh()

    # ---------------------------------------------------------------- 显示
    def _on_image(self, image) -> None:
        if image is None or not self.img.winfo_exists():
            return
        self.img.configure(image=image, text="")
        self.img.image = image

    def _say_initial(self) -> None:
        self.write("沙沙……草丛里窜出来一只宝可梦！")
        if self.known:
            self.write(f"是{self.dex.name(self.wild['species_id'])}！它看起来很精神。")
        else:
            self.write("图鉴里没有这只的记录——是个新面孔。")
        if items.get("poke-ball"):
            balls = sum(self.store.item_count(i.id) for i in items.by_category("ball"))
            self.write(f"背包里还有 {balls} 个球。")

    def _refresh(self) -> None:
        sid = self.wild["species_id"]
        if self.known or self.enc.caught:
            name = f"{self.dex.name(sid)}　Lv.{self.enc.level}"
            meta = f"#{sid:04d}　{self.dex.types_zh(sid)}　" \
                   f"进化链第 {self.wild.get('stage', 0) + 1} 段"
        else:
            name = "？？？　Lv.?"
            meta = f"#{sid:04d}　未收录（收服后解锁图鉴）"
        self.name_label.configure(text=name)
        self.meta_label.configure(text=meta)

        ratio = self.enc.friendliness / 100.0
        self.relax_bar.set(ratio, "#845ef7" if ratio < 0.4 else "#37b24d")
        self.relax_label.configure(text=self.enc.relax_zh)
        self.turn_label.configure(
            text=f"回合 {self.enc.turns}/{MAX_TURNS}　还剩 "
                 f"{max(0, MAX_TURNS - self.enc.turns)} 次机会")

    def write(self, text: str) -> None:
        if not self.log.winfo_exists():
            return
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _disable_actions(self) -> None:
        for b in self.action_buttons:
            b.state(["disabled"])

    # ---------------------------------------------------------------- 行为
    def _bait(self) -> None:
        owned = [i for i in items.by_category("food") if self.store.item_count(i.id) > 0]
        if not owned:
            messagebox.showinfo("没有食物", "背包里没有可以喂的树果，去商店买一些吧。",
                                parent=self)
            return
        menu = tk.Menu(self, tearoff=0, font=(CN_FONT, 9))
        for it in owned:
            menu.add_command(label=f"{it.zh} ×{self.store.item_count(it.id)}",
                             command=lambda i=it: self._do_bait(i.id, i.zh))
        self._popup(menu)

    def _popup(self, menu: tk.Menu) -> None:
        x = self.winfo_rootx() + 40
        y = self.winfo_rooty() + self.winfo_height() - 120
        menu.tk_popup(x, y)

    def _do_bait(self, item_id: str, zh: str) -> None:
        if self._ended:
            return
        self.store.take_item(item_id, 1)
        self.write(f"你拿出了「{zh}」，放在地上慢慢退后。")
        self.write(self.enc.bait())
        self._end_turn()

    def _throw(self) -> None:
        owned = [i for i in items.by_category("ball") if self.store.item_count(i.id) > 0]
        if not owned:
            messagebox.showinfo("没有球", "背包里没有精灵球了，去商店补给一下吧。",
                                parent=self)
            return
        menu = tk.Menu(self, tearoff=0, font=(CN_FONT, 9))
        for it in owned:
            menu.add_command(
                label=f"{it.zh} ×{self.store.item_count(it.id)}",
                command=lambda i=it: self._do_throw(i.id, i.zh))
        self._popup(menu)

    def _do_throw(self, item_id: str, zh: str) -> None:
        if self._ended:
            return
        self.store.take_item(item_id, 1)
        power = items.ball_power(item_id)
        res = self.enc.throw(self.wild.get("entry") or {}, self.wild.get("stage", 0), power)
        self.write(f"丢出了{zh}！咔嗒——")
        if res["shakes"]:
            self.write("球摇晃了 " + "· " * res["shakes"])
        if res["success"]:
            self.write(f"咔——！成功了！捕获率 {res['rate'] * 100:.0f}%")
            self.known = True
            self._finish_catch()
            return
        self.write(f"啪！球被顶开了……（捕获率 {res['rate'] * 100:.0f}%）")
        self._end_turn()

    def _leave(self) -> None:
        if self._ended:
            return
        self._ended = True
        self.write("你悄悄后退，放它回到了草丛里。")
        self.store.add_explore_log("这一次，你选择了目送它离开。")
        self.app.pet_window.say("它跑掉了，不过相遇本身就很好啦", secs=4)
        self._disable_actions()
        self.app.save()

    # ---------------------------------------------------------------- 回合结束
    def _end_turn(self) -> None:
        flee = self.enc.maybe_flee()
        if flee:
            self._ended = True
            self.write(flee)
            self.store.add_explore_log(
                f"遇到了一只宝可梦，但它跑掉了（Lv.{self.enc.level}）。")
            self.app.pet_window.say("草丛沙沙响……它跑掉了", secs=4)
            self._disable_actions()
        elif self.enc.turns >= MAX_TURNS:
            self._ended = True
            self.write("它失去了兴趣，一溜烟跑远了。")
            self.store.add_explore_log("它等不及先走了，下次动作快一点。")
            self.app.pet_window.say("它的耐心用完啦，下次快点投球吧", secs=4.5)
            self._disable_actions()
        self.refresh_all()
        self.app.save()

    def _finish_catch(self) -> None:
        self._ended = True
        sid = self.wild["species_id"]
        pet, boxed = self.store.adopt(sid, "", how="捕捉", level=self.enc.level)
        name = self.dex.name(sid)
        self.store.add_explore_log(f"捕捉成功：{name}　Lv.{pet.level}")
        self.write(f"成功收服{name}！（Lv.{pet.level}）")
        if boxed:
            self.write(f"队伍满了，{name}先被送进了 BOX 仓库。")
        self.refresh_all()
        self.name_label.configure(text=f"{name}　Lv.{pet.level}")
        self.app.load_sprite()
        self.app.pet_window.say(f"收服了{name}！", secs=5)
        if not boxed:
            self.app.pet_window.play_activity("happy", 2.0)
        self.app.save()
        self._disable_actions()

    # ---------------------------------------------------------------- 收尾
    def refresh_all(self) -> None:
        self._refresh()
        if self.app.panel and self.app.panel.winfo_exists():
            self.app.panel.refresh_all()
        self.app.pet_window.refresh()
