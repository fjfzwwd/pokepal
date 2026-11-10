# -*- coding: utf-8 -*-
"""PokePal · 宝可梦桌宠 —— 程序入口。

用法：
    python main.py

右键桌宠可以打开功能菜单，双击桌宠打开主控面板。
"""

from __future__ import annotations

import os
import random
import sys
import time
import tkinter as tk
from tkinter import messagebox
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from assets.sprites import SIZE_PRESETS, SpriteManager, SpriteSet  # noqa: E402
from core import items  # noqa: E402
from core.encounter import roll_wild  # noqa: E402
from core.pet import Pet  # noqa: E402
from core.store import Store  # noqa: E402
from ui import phrases  # noqa: E402
from ui.encounter import EncounterWindow  # noqa: E402
from ui.panel import PanelWindow  # noqa: E402
from ui.window import PetWindow  # noqa: E402

CN_FONT = "Microsoft YaHei UI"


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("PokePal")
        self.root.withdraw()

        self.store = Store(project_root=ROOT)
        self.store.load()
        self.setting = self.store.settings

        self.sprites = SpriteManager(
            self.store.sprite_cache,
            SIZE_PRESETS.get(self.setting.get("size", "中"), 112),
            root=self.root,
        )
        self.pet_window = PetWindow(self.root, self)
        self.panel: Optional[PanelWindow] = None
        self.encounter_window = None
        self.dock = None                 # 功能图标台（小框）
        self._menu = None
        self._last_talk = time.time()
        self._talk_gap = random.uniform(28, 55)
        self._last_card = 0.0

        self.load_sprite()
        self._greet()
        self.root.after(1000, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    # ------------------------------------------------------------ 素材
    def load_sprite(self, species_id: Optional[int] = None) -> None:
        pet = self.store.pet
        if pet is None:
            return
        sid = species_id or pet.species_id
        shiny = bool(self.setting.get("shiny", False))
        self.sprites.target_size = SIZE_PRESETS.get(self.setting.get("size", "中"), 112)

        def on_ready(sprite: Optional[SpriteSet]) -> None:
            if sprite is None:
                self.pet_window.set_sprite(None)
                self.pet_window.say("素材下载失败…检查网络后再试一次", secs=6)
                return
            self.pet_window.set_sprite(sprite)
            self.pet_window.refresh()

        cached = self.sprites.cached_paths(sid, shiny)
        if cached:
            try:
                on_ready(self.sprites.build(cached))
            except Exception as exc:  # noqa: BLE001
                print(f"[素材构建失败] {exc}")
        else:
            self.pet_window.say("正在下载素材…", secs=4)
        self.sprites.load_async(sid, shiny, self.store.dex.en(sid), on_ready)

    # ------------------------------------------------------------ 主循环
    def _greet(self) -> None:
        pet = self.store.pet
        if not pet:
            return
        away = pet.last_seen and (time.time() - pet.last_seen)
        if away and away > 6 * 3600:
            self.pet_window.say(f"你终于回来啦！它等了你 {int(away // 3600)} 小时", secs=5)
        elif away and away > 1800:
            self.pet_window.say("欢迎回来～", secs=3)
        else:
            self.pet_window.say(f"{pet.display_name()}很高兴见到你", secs=3)

    def _tick(self) -> None:
        try:
            self._tick_inner()
        except Exception as exc:  # noqa: BLE001
            print(f"[主循环异常] {exc}")
        self.root.after(1000, self._tick)

    def _tick_inner(self) -> None:
        now = time.time()
        pet = self.store.pet
        if pet:
            for ev in pet.tick():
                self._handle_pet_event(pet, ev)
            self._check_life_cycle(pet)
            self._maybe_idle_talk(pet, now)

        if self.pet_window.activity_kind not in ("sleep", "work") and pet:
            want = pet.activity if pet.activity != "idle" else None
            if want and want != self.pet_window.activity_kind:
                self.pet_window.play_activity(want, max(1.0, pet.remaining()))

        if now - self._last_card > 4:
            self._last_card = now
            for ev in self.store.tick_worms():
                self._handle_farm_event(ev)
            self.pet_window.refresh()
            if self.panel and self.panel.winfo_exists():
                self.panel.refresh_data()

        if int(now) % 20 == 0:
            self.save()

    def _handle_pet_event(self, pet: Pet, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "work_ready":
            result = pet.collect_work()
            self.store.add_coins(result.coins)
            self.pet_window.play_activity("idle")
            self.pet_window.say(f"{result.message}（经验 +{result.exp}）", secs=5)
            self.pet_window.auto_speak("normal")
        elif kind == "sick":
            self.pet_window.play_activity("sick", 6)
            self.pet_window.say(f"{pet.display_name()}好像不舒服，给它用点药吧", secs=5)
        elif kind == "recovered":
            self.pet_window.say("终于恢复精神啦", secs=3)
        elif kind == "wake":
            self.pet_window.say("睡饱了！伸个懒腰～", secs=3)
        elif kind == "activity_done":
            self.pet_window.activity_kind = "idle"
        self.pet_window.refresh()

    def _maybe_idle_talk(self, pet: Pet, now: float) -> None:
        if not self.setting.get("show_bubble", True):
            return
        if now - self._last_talk < self._talk_gap:
            return
        self._last_talk = now
        self._talk_gap = random.uniform(30, 70)
        if pet.activity == "sleep":
            return
        if pet.status_key() in ("hungry", "thirsty", "dirty", "tired", "sick", "upset"):
            self.pet_window.auto_speak(pet.status_key())
        elif random.random() < 0.55:
            self.pet_window.auto_speak(pet.status_key())

    def _handle_farm_event(self, ev: dict) -> None:
        """蚕室里发生的事，由桌宠来转告。"""
        kind = ev.get("type")
        if kind == "worm_stage":
            self.pet_window.say(f"蚕室：{ev['name']}阶段到了！（{int(ev['stage'])}/4）", secs=4.5)
        elif kind == "worm_died":
            self.pet_window.say("蚕室：有一只蚕没能撑过去……", secs=5)
        if self.panel and self.panel.winfo_exists():
            self.panel.refresh_all()

    def _check_life_cycle(self, pet: Pet) -> None:
        """检查等级进化（自动）+ 一天一次的夜间自动睡眠。"""
        options = self.store.dex.evolution_options(
            pet.species_id, pet.level, int(pet.bond),
            lambda i: self.store.item_count(i) > 0)
        ready = [o for o in options if o["ready"] and not o["item"]]
        if len(ready) == 1:
            target = ready[0]["to"]
            name = self.store.dex.name(target)
            pet.apply_evolution(target, "进化之光", name)
            self.pet_window.play_activity("evolve", 3.2)
            self.pet_window.say(random.choice(phrases.EVOLVED), secs=5)
            self.load_sprite()
        elif len(ready) > 1:
            self.pet_window.say(random.choice(phrases.EVOLVE_READY), secs=4)

        if self.setting.get("night_mode", True) and pet.activity == "idle":
            hour = time.localtime().tm_hour
            today = time.strftime("%Y-%m-%d")
            flag = self.setting.get("_sleep_date")
            if (hour >= 23 or hour < 7) and flag != today:
                self.setting["_sleep_date"] = today
                pet.activity = "sleep"
                self.pet_window.play_activity("sleep", 8)
                self.pet_window.say("困了……我先睡一会儿哦", secs=4)

    # ------------------------------------------------------------ 交互
    def on_pet_click(self) -> None:
        pet = self.store.pet
        if not pet:
            return
        result = pet.touch()
        self.pet_window.say(result.message if result.ok else random.choice(phrases.TOUCHED), secs=2.6)
        self.pet_window.play_activity("happy" if result.ok else "idle", 1.6)
        if result.ok:
            self.pet_window._spawn_fx("♥", 3, mode="rise")
        self._after_change()

    def do_item(self, item_id: str) -> None:
        pet = self.store.pet
        item = items.get(item_id)
        if not pet or not item:
            return
        if self.store.item_count(item_id) <= 0:
            if not messagebox.askyesno(
                    "道具不足",
                    f"「{item.zh}」用完了，要花 {item.price} 元零花钱去买一个吗？\n（当前零花钱 {self.store.wallet} 元）",
                    parent=self._dialog_parent()):
                return
            ok, msg = self.store.buy(item_id, 1)
            if not ok:
                self.pet_window.say(msg, secs=4)
                return
        self.store.take_item(item_id, 1)
        result = pet.use_item(item)
        self.pet_window.say(result.message, secs=3.4)
        if result.ok:
            mapping = {"food": "eat", "drink": "eat", "care": "bath", "toy": "play"}
            self.pet_window.play_activity(mapping.get(item.cat, "idle"), result.duration or 4.0)
        self._after_change()

    def action(self, name: str, **kw) -> None:
        pet = self.store.pet
        if not pet:
            return
        handler = {
            "train": lambda: pet.train(),
            "sleep": lambda: pet.sleep_toggle(),
            "work": lambda: pet.start_work(int(kw.get("minutes", 5))),
        }.get(name)
        if handler is None:
            return
        result = handler()
        self.pet_window.say(result.message, secs=3.4)
        if not result.ok:
            self._after_change()
            return
        if result.coins:
            self.store.add_coins(result.coins)
        if name == "sleep":
            self.pet_window.play_activity(
                "sleep" if pet.activity == "sleep" else "idle", 8)
        elif result.activity:
            self.pet_window.play_activity(result.activity, result.duration or 4.0)
        self._after_change()

    def evolve_to(self, target: int, source: str = "进化") -> None:
        pet = self.store.pet
        if not pet:
            return
        pet.apply_evolution(target, source, self.store.dex.name(target))
        self.pet_window.play_activity("evolve", 3.2)
        self.pet_window.say(random.choice(phrases.EVOLVED), secs=5)
        self.load_sprite()
        self._after_change()

    # ------------------------------------------------------------ 探索 / 捕捉
    def explore(self) -> None:
        """去草丛里走走，看看能不能遇到野生宝可梦。"""
        balls = sum(self.store.item_count(i.id) for i in items.by_category("ball"))
        if balls <= 0:
            self.pet_window.say("背包里没有精灵球了，先去商店买一些吧", secs=5)
            return
        ready, left = self.store.explore_ready()
        if not ready:
            self.pet_window.say(f"刚回来，脚还没歇够……再等 {int(left)} 秒", secs=4)
            return
        if self.encounter_window and self.encounter_window.winfo_exists():
            self.encounter_window.lift()
            return
        self.store.mark_explored()
        self.pet_window.play_activity("walk", 2.0)
        wild = roll_wild(self.store.dex, self.store.met)
        if not wild:
            self.pet_window.say("四周静悄悄的，什么都没遇见…", secs=4)
            return
        self.store.add_explore_log(
            f"草丛里有动静！出现了 Lv.{wild['level']} 的宝可梦")
        self.store.save()
        self.encounter_window = EncounterWindow(self.root, self, wild)
        self.pet_window.say("嘘——草丛里有东西在动！", secs=4)

    def use_stone(self, item_id: str, target: int) -> None:
        if self.store.item_count(item_id) <= 0:
            self.pet_window.say("没有这块进化石…去商店买一块吧", secs=4)
            return
        self.store.take_item(item_id, 1)
        self.evolve_to(target, items.get(item_id).zh)

    def unlock_all(self, confirm: bool = True) -> tuple[int, int]:
        """沙盒：点亮全部图鉴，每只宝可梦都以满级入队。返回 (新增, 总数)。"""
        total_species = len(self.store.dex.entries)
        if confirm and not messagebox.askyesno(
                "一键全开",
                f"把全部 {total_species} 条图鉴都点亮，并让每一只宝可梦都以 Lv.100 "
                f"成为你的伙伴？\n\n这会直接改写当前存档。",
                parent=self._dialog_parent()):
            return 0, len(self.store.pets)
        added, total = self.store.unlock_everything()
        self.load_sprite()
        self.pet_window.say(f"全开啦！新增 {added} 位同伴，一共 {total} 位", secs=4.5)
        self._after_change()
        return added, total

    def _after_change(self) -> None:
        pet = self.store.pet
        if pet:
            self.pet_window.refresh()
        if self.panel and self.panel.winfo_exists():
            self.panel.refresh_all()
        self.save()

    def _dialog_parent(self):
        if self.panel and self.panel.winfo_exists():
            return self.panel
        self.root.deiconify()
        self.root.withdraw()
        return self.root

    # ------------------------------------------------------------ 菜单
    def show_menu(self, x: int, y: int) -> None:
        pet = self.store.pet
        if pet is None:
            return
        menu = tk.Menu(self.root, tearoff=0, font=(CN_FONT, 9), activeborderwidth=0)
        menu.add_command(label=f"{pet.display_name()}　Lv.{pet.level}", state="disabled")
        menu.add_command(label="功能小框（图标台 · 中键呼出）", command=self.toggle_dock)
        menu.add_separator()

        for cat, label in (("food", "喂食"), ("drink", "喝水"),
                           ("care", "清洁"), ("toy", "玩耍")):
            owned = [i for i in items.by_category(cat) if self.store.item_count(i.id) > 0]
            if not owned:
                continue
            sub = tk.Menu(menu, tearoff=0, font=(CN_FONT, 9))
            for it in owned:
                sub.add_command(
                    label=f"{it.zh} ×{self.store.item_count(it.id)}　{it.price}元",
                    command=lambda i=it.id: self.do_item(i))
            menu.add_cascade(label=label, menu=sub)

        owned_med = [i for i in items.by_category("medicine") if self.store.item_count(i.id) > 0]
        if owned_med:
            sub = tk.Menu(menu, tearoff=0, font=(CN_FONT, 9))
            for it in owned_med:
                sub.add_command(label=f"{it.zh} ×{self.store.item_count(it.id)}",
                                command=lambda i=it.id: self.do_item(i))
            menu.add_cascade(label="药品", menu=sub)

        menu.add_separator()
        menu.add_command(label="训练一下", command=lambda: self.action("train"))
        menu.add_command(label="睡觉 / 叫醒", command=lambda: self.action("sleep"))
        work_menu = tk.Menu(menu, tearoff=0, font=(CN_FONT, 9))
        for mins in (5, 15, 30):
            work_menu.add_command(label=f"去打工 {mins} 分钟",
                                  command=lambda m=mins: self.action("work", minutes=m))
        menu.add_cascade(label="打工赚钱", menu=work_menu)

        if pet.activity == "work" and pet.remaining() <= 0:
            menu.add_command(label="领取打工报酬", command=self._collect_work)

        evo = self.store.dex.evolution_options(
            pet.species_id, pet.level, int(pet.bond),
            lambda i: self.store.item_count(i) > 0)
        if evo:
            evo_menu = tk.Menu(menu, tearoff=0, font=(CN_FONT, 9))
            for opt in evo:
                name = self.store.dex.name(opt["to"])
                if opt["item"]:
                    label = f"{name}（{opt['how']}）"
                    if opt["ready"]:
                        evo_menu.add_command(label=label + " ✔",
                                              command=lambda o=opt: self.use_stone(o["item"], o["to"]))
                    else:
                        evo_menu.add_command(label=label + "（缺道具）", state="disabled")
                else:
                    state = "normal" if opt["ready"] else "disabled"
                    evo_menu.add_command(
                        label=f"{name}（{opt['how']}）", state=state,
                        command=lambda o=opt: self.evolve_to(o["to"]))
            menu.add_cascade(label="进化", menu=evo_menu)

        menu.add_separator()
        menu.add_command(label="去草丛探险（可能遇到宝可梦）", command=self.explore)
        menu.add_command(label="图鉴 · 认识新伙伴", command=lambda: self.open_panel("图鉴"))
        menu.add_command(label="一键全开（沙盒：全图鉴 + 满级）", command=self.unlock_all)

        box = self.store.box()
        team = self.store.team()
        switch = tk.Menu(menu, tearoff=0, font=(CN_FONT, 9))
        for p in team:
            tag = " ● 同行" if p.uid == pet.uid else ""
            switch.add_command(
                label=f"{p.display_name()}　Lv.{p.level}{tag}",
                command=lambda uid=p.uid: self.switch_pet(uid))
        if box:
            switch.add_separator()
            for p in box:
                switch.add_command(
                    label=f"{p.display_name()}　Lv.{p.level}（BOX）",
                    command=lambda uid=p.uid: self.take_from_box(uid))
        if len(self.store.pets) <= 1:
            switch.add_separator()
            switch.add_command(
                label="还没有别的同伴：去「图鉴」或「探索」认识它", state="disabled")
        menu.add_cascade(label=f"更换宝可梦（{len(team)}/{len(self.store.pets)}）", menu=switch)

        menu.add_separator()
        menu.add_command(label="打开主控面板", command=self.open_panel)
        menu.add_command(label="窗口置顶：开" if self.setting.get("always_top", True) else "窗口置顶：关",
                         command=self.toggle_top)
        menu.add_command(label="隐藏一小会儿", command=self.hide_temporarily)
        menu.add_separator()
        menu.add_command(label="退出", command=self.quit)

        menu.tk_popup(x, y)
        self._menu = menu

    def _collect_work(self) -> None:
        pet = self.store.pet
        if not pet:
            return
        result = pet.collect_work()
        self.store.add_coins(result.coins)
        self.pet_window.say(result.message, secs=4)
        self._after_change()

    def toggle_top(self) -> None:
        cur = bool(self.setting.get("always_top", True))
        self.setting["always_top"] = not cur
        self.pet_window.apply_settings()
        self.save()

    def hide_temporarily(self) -> None:
        self.pet_window.withdraw()
        self.root.after(60 * 1000, self.pet_window.deiconify)

    def take_from_box(self, uid: str) -> None:
        ok, msg = self.store.from_box(uid)
        if not ok:
            messagebox.showinfo("没法取出来", msg, parent=self._dialog_parent())
            return
        self.load_sprite()
        self.pet_window.say(msg, secs=4)
        self._after_change()

    def send_to_box(self, uid: str) -> None:
        ok, msg = self.store.to_box(uid)
        if not ok:
            messagebox.showinfo("没法寄存", msg, parent=self._dialog_parent())
            return
        self.load_sprite()
        self.pet_window.say(msg, secs=4)
        self._after_change()

    def switch_pet(self, uid: str) -> None:
        self.store.set_active(uid)
        pet = self.store.pet
        self.load_sprite()
        if pet:
            self.pet_window.say(f"换成了{pet.display_name()}", secs=3)
        self.pet_window.refresh()
        self.save()

    # ------------------------------------------------------------ 面板
    def open_panel(self, tab: str = "") -> None:
        """打开主控面板；传 tab 可以直接落到某个页签（"图鉴" / "探索" / "仓库" ...）。"""
        self.close_dock()
        fresh = False
        if self.panel and self.panel.winfo_exists():
            self.panel.deiconify()
            self.panel.lift()
            self.panel.refresh_all()
        else:
            self.panel = PanelWindow(self.root, self)
            self.panel.refresh_all()
            fresh = True
        if tab:
            self.panel.select_tab(tab)
        elif fresh:
            self.panel.select_tab("状态")

    def on_panel_closed(self) -> None:
        self.panel = None

    # ------------------------------------------------------------ 功能图标台
    def dock_entries(self) -> list:
        """图标台里的功能：把右键菜单的常用项摊成图标。"""
        return [
            ("面板", "宠", "#4c6ef5", lambda: self.open_panel("状态")),
            ("喂食", "食", "#37b24d", lambda: self.quick_item("food")),
            ("喝水", "水", "#1c7ed6", lambda: self.quick_item("drink")),
            ("玩耍", "玩", "#f59f00", lambda: self.quick_item("toy")),
            ("训练", "练", "#7048e8", lambda: self.action("train")),
            ("睡觉", "睡", "#495057", lambda: self.action("sleep")),
            ("打工", "工", "#b06a2c", lambda: self.action("work", minutes=15)),
            ("探险", "探", "#0ca678", self.explore),
            ("图鉴", "鉴", "#e03131", lambda: self.open_panel("图鉴")),
            ("仓库", "仓", "#868e96", lambda: self.open_panel("仓库")),
            ("蚕室", "蚕", "#74b816", lambda: self.open_panel("蚕室")),
            ("设置", "设", "#343a40", lambda: self.open_panel("设置")),
        ]

    def open_dock(self) -> None:
        dock = self.dock
        if dock is not None:
            try:
                if dock.winfo_exists():
                    dock.lift()
                    return
            except Exception:  # noqa: BLE001
                pass
            self.dock = None
        from ui.dock import DockWindow

        self.dock = DockWindow(self.root, self, self.dock_entries())

    def close_dock(self) -> None:
        dock = self.dock
        self.dock = None
        if dock is not None:
            try:
                if dock.winfo_exists():
                    dock.close()
            except Exception:  # noqa: BLE001
                pass

    def toggle_dock(self) -> None:
        dock = self.dock
        alive = False
        if dock is not None:
            try:
                alive = bool(dock.winfo_exists())
            except Exception:  # noqa: BLE001
                alive = False
        if alive:
            self.close_dock()
        else:
            self.open_dock()

    def on_dock_closed(self, dock=None) -> None:
        # 只清理「自己这个」实例，避免旧窗口的延迟回调把新开的图标台踢掉
        if dock is None or self.dock is dock:
            self.dock = None

    def quick_item(self, category: str) -> None:
        """图标台用：直接用背包里最好的现成道具，不弹子菜单。"""
        owned = [i for i in items.by_category(category)
                 if self.store.item_count(i.id) > 0]
        if not owned:
            name = {"food": "吃的", "drink": "喝的", "toy": "玩具",
                    "care": "清洁用品"}.get(category, "道具")
            self.pet_window.say(f"背包里没有{name}了，去商店补一点吧", secs=4)
            return
        self.do_item(max(owned, key=lambda i: i.price).id)

    # ------------------------------------------------------------ 退出
    def request_save(self) -> None:
        self.save()

    def save(self) -> None:
        self.setting["pos"] = [int(self.pet_window.x), int(self.pet_window.y)]
        self.store.save()

    def quit(self) -> None:  # noqa: A003
        self.save()
        try:
            self.pet_window.running = False
            self.pet_window.destroy()
        except Exception:  # noqa: BLE001
            pass
        self.root.quit()


def main() -> int:
    try:
        app = App()
        app.root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
