# -*- coding: utf-8 -*-
"""桌宠窗口。

一个 frameless + transparentcolor + always-on-top 的 Tk 窗口，
上面叠三块内容（从上到下）：状态卡、气泡对话、精灵本体。

物理：被拖起来松手后会抛物线下落 + 触地反弹衰减（参考各类桌宠的手感）。
AI：地面上会自己散步 / 发呆 / 回头看，累了会自动睡觉。
"""

from __future__ import annotations

import math
import random
import time
from typing import List, Optional

import tkinter as tk

from assets.sprites import SpriteSet
from ui import phrases

TRANSPARENT = "#FF00FF"
CN_FONT = "Microsoft YaHei UI"
EMOJI_FONT = "Segoe UI Emoji"

GRAVITY = 1.1
LOOP_MS = 28
TASKBAR_MARGIN = 56
BOUNCE = 0.42


def _rounded(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
             r: float = 10, **kw) -> int:
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class PetWindow(tk.Toplevel):
    def __init__(self, master: tk.Tk, app):
        super().__init__(master)
        self.app = app
        self.setting = app.store.settings

        self.sprite: Optional[SpriteSet] = None
        self.frame_idx = 0
        self.facing = "front"
        self.running = True

        self.reserve = 0
        self.win_w = 160
        self.win_h = 160
        self.x = 100
        self.y = 100
        self.vx = 0.0
        self.vy = 0.0
        self.state = "fall"          # fall / ground
        self.ai = "idle"
        self.ai_until = 0.0
        self.walk_dir = 1
        self.dragging = False
        self._press_xy = (0, 0)
        self._off = (0, 0)
        self._moved = False
        self._samples: List[tuple] = []
        self.bubble_until = 0.0
        self.bubble_text = ""
        self.fx: List[dict] = []
        self.activity_until = 0.0
        self.activity_kind = "idle"
        self._bob = 0.0
        self._font_cache = None

        self._build_window()
        self._build_canvas()
        self._bind_events()
        self._restore_position()
        self.after(LOOP_MS, self._loop)
        self.after(120, self._anim_loop)

    # ---------------------------------------------------------------- 初始化
    def _build_window(self) -> None:
        self.configure(bg=TRANSPARENT)
        self.overrideredirect(True)
        try:
            self.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.attributes("-topmost", bool(self.setting.get("always_top", True)))
        self.resizable(False, False)

    def _build_canvas(self) -> None:
        self.canvas = tk.Canvas(self, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.img_item = None
        self.card_items: List[int] = []
        self.bubble_items: List[int] = []

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.app.open_panel())
        self.canvas.bind("<ButtonPress-3>", self._on_right)
        self.canvas.bind("<ButtonPress-2>", lambda e: self.app.toggle_dock())   # 中键 → 图标台
        self.bind("<Destroy>", lambda e: setattr(self, "running", False))

    # ---------------------------------------------------------------- 尺寸
    def _restore_position(self) -> None:
        pos = self.setting.get("pos")
        sw, sh = self.screen_size()
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self.x = max(0, min(int(pos[0]), sw - 60))
            self.y = max(0, min(int(pos[1]), sh - 60))
        else:
            self.x = sw - self.win_w - 40
            self.y = self.floor_y() - self.win_h
        self.state = "ground"
        self.ai_until = time.time() + 1.0

    def screen_size(self) -> tuple[int, int]:
        try:
            return (self.winfo_screenwidth(), self.winfo_screenheight())
        except Exception:  # noqa: BLE001
            return (1280, 720)

    def floor_y(self) -> int:
        return self.screen_size()[1] - TASKBAR_MARGIN

    def _resize_for_sprite(self) -> None:
        """根据精灵图 + 设置重算窗口与画布尺寸。

        预留高度按**字体实际行高**算，而不是写死 34/48：125% / 150% 缩放下
        8pt 的一行就有 16px，写死的数字会让状态卡和气泡互相压住。
        """
        w = self.sprite.w if self.sprite else 112
        h = self.sprite.h if self.sprite else 112
        reserve = 4
        if self.setting.get("show_stats", True):
            reserve += self._card_h()
        if self.setting.get("show_bubble", True):
            line_h = self._fonts()["bubble"].metrics("linespace") + 1
            reserve += max(46, 2 * line_h + 14)
        self.reserve = reserve
        # 窗口至少和状态卡一样宽，否则数值只能挤成「饱23水44」这种没法读的样子
        self.win_w = max(140, int(w) + 24, self._card_min_w() + 8)
        self.win_h = int(h) + reserve
        self.canvas.configure(width=self.win_w, height=self.win_h)
        if self.img_item is None:
            self.img_item = self.canvas.create_image(self.win_w // 2, self.win_h, anchor="s")
        else:
            self.canvas.coords(self.img_item, self.win_w // 2, self.win_h)
        self._draw_card()
        if self.bubble_text:
            self._draw_bubble()          # 卡片尺寸变了，气泡跟着挪
        self._clamp_to_floor()

    def set_sprite(self, sprite: Optional[SpriteSet]) -> None:
        self.sprite = sprite
        self.frame_idx = 0
        self._resize_for_sprite()
        if self.img_item is not None:
            if sprite is None:
                self.canvas.itemconfig(self.img_item, image="")
            else:
                self.canvas.itemconfig(self.img_item, image=sprite.frames(self.facing)[0])
        self.canvas.delete("fx")
        self.fx.clear()
        if self.img_item is not None:
            self.canvas.lift(self.img_item)

    # ---------------------------------------------------------------- 主循环
    def _loop(self) -> None:
        if not self.running:
            return
        try:
            self._think()
            self._physics()
            self._place()
            self._update_fx()
            self._update_bubble()
        except Exception as exc:  # noqa: BLE001
            print(f"[窗口循环异常] {exc}")
        self.after(LOOP_MS, self._loop)

    def _anim_loop(self) -> None:
        if not self.running:
            return
        delay = 120
        try:
            if self.sprite:
                frames = self.sprite.frames(self.facing)
                if frames:
                    self.frame_idx = (self.frame_idx + 1) % len(frames)
                    if self.img_item is not None:
                        self.canvas.itemconfig(self.img_item, image=frames[self.frame_idx])
                    idx = self.frame_idx % len(self.sprite.delays)
                    delay = self.sprite.delays[idx]
                    delay = max(40, int(delay / self._speed_factor()))
        except Exception as exc:  # noqa: BLE001
            print(f"[动画异常] {exc}")
        self.after(delay, self._anim_loop)

    def _speed_factor(self) -> float:
        if self.activity_kind == "sleep":
            return 0.35
        if self.activity_kind in ("work", "sick"):
            return 0.7
        if self.ai == "walk":
            return 1.35
        return 1.0

    # ---------------------------------------------------------------- AI
    def _think(self) -> None:
        now = time.time()
        pet = self.app.store.pet
        if pet is None or self.dragging or self.state != "ground":
            return
        if now < self.ai_until:
            return

        if not self.setting.get("walk", True) or pet.activity in ("sleep", "work"):
            self.ai = "idle"
            self.ai_until = now + 1.5
            return

        if self.setting.get("follow_mouse", False):
            try:
                mx = self.winfo_pointerx()
            except Exception:  # noqa: BLE001
                mx = None
            center = self.x + self.win_w // 2
            if mx is not None and abs(mx - center) > 60:
                self.ai = "walk"
                self.walk_dir = 1 if mx > center else -1
                self.ai_until = now + 0.6
                return

        roll = random.random()
        if roll < 0.45:
            self.ai = "walk"
            self.walk_dir = random.choice((-1, 1))
            self.ai_until = now + random.uniform(1.2, 3.4)
        else:
            self.ai = "idle"
            self.ai_until = now + random.uniform(2.0, 6.0)
            # 桌宠始终面向用户：不再随机切到背面素材（背面只留给素材层兜底用）
            self.facing = "front"

    # ---------------------------------------------------------------- 物理
    def _physics(self) -> None:
        now = time.time()
        if self.dragging:
            self.activity_until = max(self.activity_until, now + 0.2)
            return

        sw, _ = self.screen_size()
        floor_y = self.floor_y()

        if self.state == "fall":
            self.vy += GRAVITY
            self.y += int(self.vy)
            self.x += int(self.vx)
            bottom = self.y + self.win_h
            if bottom >= floor_y:
                self.y = floor_y - self.win_h
                if self.vy > 4.5:
                    self.vy = -self.vy * BOUNCE
                    self.vx *= 0.72
                    self.say_once(phrases.LAND)
                else:
                    self.vy = 0.0
                    self.vx = 0.0
                    self.state = "ground"
                    self.ai_until = now + 0.6
        else:
            if self.ai == "walk" and self.activity_kind not in ("sleep", "work"):
                speed = 1.4
                self.x += int(self.walk_dir * speed * 2)
                if self.x <= 0:
                    self.x = 0
                    self.walk_dir = 1
                elif self.x >= sw - self.win_w:
                    self.x = sw - self.win_w
                    self.walk_dir = -1
        self.y = min(self.y, floor_y - self.win_h)
        self.x = max(0, min(self.x, sw - self.win_w))

    def _place(self) -> None:
        self.geometry(f"{self.win_w}x{self.win_h}+{int(self.x)}+{int(self.y)}")

    def _clamp_to_floor(self) -> None:
        sw, _ = self.screen_size()
        self.y = min(self.y, self.floor_y() - self.win_h)
        self.x = max(0, min(self.x, sw - self.win_w))

    # ---------------------------------------------------------------- 拖拽
    def _on_press(self, event: tk.Event) -> None:
        self.app.close_dock()          # 点桌面宠物时顺手收起图标台
        self.dragging = True
        self._moved = False
        self._press_xy = (event.x_root, event.y_root)
        self._off = (event.x_root - self.x, event.y_root - self.y)
        self._samples = [(time.time(), event.x_root, event.y_root)]
        self.ai_until = time.time() + 0.4
        self.state = "ground"
        self.vx = self.vy = 0.0

    def _on_motion(self, event: tk.Event) -> None:
        if not self.dragging:
            return
        nx = event.x_root - self._off[0]
        ny = event.x_root - self._off[1]
        if abs(nx - self._press_xy[0]) + abs(ny - self._press_xy[1]) > 6:
            if not self._moved:
                self.say_once(phrases.DRAG)
            self._moved = True
        self.x = nx
        self.y = ny
        self._samples.append((time.time(), event.x_root, event.y_root))
        self._samples = self._samples[-6:]

    def _on_release(self, event: tk.Event) -> None:  # noqa: ARG002
        if not self.dragging:
            return
        self.dragging = False
        if not self._moved:
            self.app.on_pet_click()
            self.state = "ground"
            return
        # 计算抛投速度
        vx, vy = 0.0, 0.0
        if len(self._samples) >= 2:
            t0, x0, y0 = self._samples[0]
            t1, x1, y1 = self._samples[-1]
            dt = max(0.05, t1 - t0)
            vx = max(-26.0, min(26.0, (x1 - x0) / dt / 34.0))
            vy = max(-18.0, min(14.0, (y1 - y0) / dt / 34.0))
        self.vx, self.vy = vx, vy
        self.state = "fall"
        self.ai_until = time.time() + 1.2
        self.setting["pos"] = [int(self.x), int(self.y)]
        self.app.request_save()

    def _on_right(self, event: tk.Event) -> None:
        self.app.show_menu(event.x_root, event.y_root)

    # ---------------------------------------------------------------- 特效
    def play_activity(self, kind: str, duration: float = 3.0) -> None:
        """根据当前行为生成对应的小特效（不用额外素材）。"""
        self.activity_kind = kind
        self.activity_until = time.time() + max(0.5, duration)
        self.canvas.delete("fx")
        self.fx.clear()
        if kind == "eat":
            self._spawn_fx("🍎", 6, mode="to_center")
        elif kind == "play":
            self._spawn_fx("♥", 6, mode="rise")
        elif kind == "bath":
            self._spawn_fx("🫧", 10, mode="rise")
        elif kind == "train":
            self._spawn_fx("💪", 3, mode="shake")
            self._spawn_fx("💧", 5, mode="fall")
        elif kind == "sleep":
            self._spawn_fx("💤", 3, mode="rise")
        elif kind == "work":
            self._spawn_fx("💼", 2, mode="shake")
        elif kind == "evolve":
            self._spawn_fx("✨", 12, mode="orbit")
        elif kind == "sick":
            self._spawn_fx("💫", 3, mode="orbit")
        elif kind == "levelup":
            self._spawn_fx("⭐", 8, mode="rise")

    def _spawn_fx(self, glyph: str, count: int, mode: str) -> None:
        for i in range(count):
            x = random.uniform(0.2, 0.8) * self.win_w
            y = self.reserve + random.uniform(0.15, 0.6) * (self.win_h - self.reserve)
            item = self.canvas.create_text(
                x, y, text=glyph, font=(EMOJI_FONT, 11),
                fill="#ffffff", tags="fx")
            self.fx.append({
                "item": item, "mode": mode, "life": random.uniform(1.0, 2.4),
                "phase": i / max(1, count) * math.tau,
                "vx": random.uniform(-0.6, 0.6), "vy": random.uniform(-1.2, -0.5),
                "target": (self.win_w // 2, self.reserve + (self.win_h - self.reserve) * 0.55),
            })

    def _update_fx(self) -> None:
        if not self.fx:
            return
        for spec in list(self.fx):
            spec["life"] -= LOOP_MS / 1000.0
            if spec["life"] <= 0:
                self.canvas.delete(spec["item"])
                self.fx.remove(spec)
                continue
            try:
                x, y = self.canvas.coords(spec["item"])
            except Exception:  # noqa: BLE001
                self.fx.remove(spec)
                continue
            mode = spec["mode"]
            if mode == "rise":
                self.canvas.coords(spec["item"], x + spec["vx"], y + spec["vy"] * 2)
            elif mode == "fall":
                self.canvas.coords(spec["item"], x + spec["vx"] * 0.4, y + 1.6)
            elif mode == "shake":
                self.canvas.coords(spec["item"], x + math.sin(spec["life"] * 12) * 1.6, y)
            elif mode == "orbit":
                spec["phase"] += 0.22
                cx, cy = self.win_w // 2, self.reserve + (self.win_h - self.reserve) * 0.5
                r = 0.32 * min(self.win_w, self.win_h - self.reserve)
                self.canvas.coords(spec["item"],
                                   cx + math.cos(spec["phase"]) * r,
                                   cy + math.sin(spec["phase"]) * r * 0.6)
            elif mode == "to_center":
                tx, ty = spec["target"]
                dx, dy = tx - x, ty - y
                if abs(dx) + abs(dy) < 6:
                    spec["life"] = min(spec["life"], 0.15)
                self.canvas.coords(spec["item"], x + dx * 0.18, y + dy * 0.18)
            alpha = max(0.35, min(1.0, spec["life"] / 1.6))
            self.canvas.itemconfig(spec["item"], fill="#ffffff" if alpha > 0.6 else "#dddddd")
        if time.time() > self.activity_until and self.activity_kind not in ("sleep", "work"):
            self.activity_kind = "idle"

    # ---------------------------------------------------------------- 气泡
    def say(self, text: str, secs: float = 3.4) -> None:
        self.bubble_text = text
        self.bubble_until = time.time() + secs
        self._draw_bubble(force=True)

    def say_once(self, pool) -> None:
        self.say(random.choice(pool), secs=2.4)

    def _update_bubble(self) -> None:
        if self.bubble_text and time.time() > self.bubble_until:
            self.bubble_text = ""
            self.canvas.delete("bubble")

    # ---------------------------------------------------------------- 字体
    def _fonts(self) -> dict:
        """缓存字体对象：要按真实像素量宽度，不能靠字符数猜。"""
        if getattr(self, "_font_cache", None) is None:
            from tkinter import font as tkfont

            self._font_cache = {
                "name": tkfont.Font(font=(CN_FONT, 9, "bold")),
                "stat": tkfont.Font(font=(CN_FONT, 8)),
                "tiny": tkfont.Font(font=(CN_FONT, 7)),
                "bubble": tkfont.Font(font=(CN_FONT, 9)),
            }
        return self._font_cache

    def _card_h(self) -> int:
        """状态卡总高：标题一行 + 数值一行 + 上下留白。"""
        if not self.setting.get("show_stats", True):
            return 0
        f = self._fonts()
        return int(f["name"].metrics("linespace") + f["stat"].metrics("linespace") + 12)

    @staticmethod
    def _stats_text(pet, font, max_px: int) -> str:
        short = {"fullness": "饱", "hydration": "水", "clean": "洁",
                 "mood": "心", "stamina": "体"}
        items = [f"{short[k]}{int(pet.stats[k])}" for k in short]
        for sep in (" ", ""):
            text = sep.join(items)
            if font.measure(text) <= max_px:
                return text
        return "".join(items)

    def _card_min_w(self) -> int:
        """状态卡「不挤成一坨」所需的宽度（带空格、8pt）。"""
        pet = self.app.store.pet
        if pet is None or not self.setting.get("show_stats", True):
            return 0
        f = self._fonts()
        title = f"Lv.{pet.level} {pet.display_name()}"
        bond = f"♥{int(pet.bond)}"
        stats = self._stats_text(pet, f["stat"], 100000)
        return int(max(f["name"].measure(title) + 8 + f["stat"].measure(bond),
                       f["stat"].measure(stats)) + 16)

    def _draw_card(self) -> None:
        self.canvas.delete("card")
        self._card_bottom = 2
        pet = self.app.store.pet
        if pet is None or not self.setting.get("show_stats", True):
            return
        f = self._fonts()
        pad_x, pad_y = 8, 5
        w_max = max(120, self.win_w - 6)
        inner = w_max - pad_x * 2

        title = f"Lv.{pet.level} {pet.display_name()}"
        bond = f"♥{int(pet.bond)}"
        bond_w = f["stat"].measure(bond)
        if f["name"].measure(title) + 6 + bond_w > inner:      # 名字太长就截断加省略号
            name = pet.display_name()
            while name and f["name"].measure(f"Lv.{pet.level} {name}…") + 6 + bond_w > inner:
                name = name[:-1]
            title = f"Lv.{pet.level} {name}…"
        stat_font = f["stat"]
        stats = self._stats_text(pet, stat_font, inner)
        if stat_font.measure(stats) > inner:                   # 还是塞不下就换 7pt
            stat_font = f["tiny"]
            stats = self._stats_text(pet, stat_font, inner)

        w = min(w_max, max(f["name"].measure(title) + 8 + bond_w,
                           stat_font.measure(stats)) + pad_x * 2)
        h = self._card_h()
        y0 = 2
        self._card_bottom = y0 + h          # 气泡从这条线往下排
        x1 = (self.win_w - w) / 2
        _rounded(self.canvas, x1, y0, x1 + w, y0 + h, 8,
                 fill="#ffffff", outline="#ffd166", width=1, tags="card")

        name_ls = f["name"].metrics("linespace")
        stat_ls = stat_font.metrics("linespace")
        self.canvas.create_text(x1 + pad_x, y0 + pad_y, anchor="nw", tags="card",
                                text=title, font=f["name"], fill="#2b2b2b")
        self.canvas.create_text(x1 + w - pad_x, y0 + pad_y + (name_ls - stat_ls) // 2,
                                anchor="ne", tags="card", text=bond,
                                font=stat_font, fill="#8a8a8a")
        self.canvas.create_text(x1 + pad_x, y0 + pad_y + name_ls, anchor="nw",
                                tags="card", text=stats, font=stat_font, fill="#555555")

    @staticmethod
    def _wrap(text: str, font, max_px: int) -> List[str]:
        """按像素宽度断行（中英文混排时按字符数断会溢出）。"""
        lines: List[str] = []
        cur = ""
        for ch in text:
            if cur and font.measure(cur + ch) > max_px:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines

    def _draw_bubble(self, force: bool = False) -> None:
        self.canvas.delete("bubble")
        if not self.setting.get("show_bubble", True) or not self.bubble_text:
            return
        f = self._fonts()["bubble"]
        max_text_w = max(80, self.win_w - 26)
        lines = self._wrap(self.bubble_text, f, max_text_w)[:3]
        line_h = f.metrics("linespace") + 1
        h = len(lines) * line_h + 10
        y_top = getattr(self, "_card_bottom", 2) + 6
        widest = max(f.measure(s) for s in lines)
        w = min(self.win_w - 6, max(widest + 18, 70))
        x1 = (self.win_w - w) / 2
        _rounded(self.canvas, x1, y_top, x1 + w, y_top + h, 9,
                 fill="#ffffff", outline="#adb5bd", width=1, tags="bubble")
        self.canvas.create_polygon(
            [self.win_w / 2 - 5, y_top + h, self.win_w / 2 + 5, y_top + h,
             self.win_w / 2, y_top + h + 7],
            fill="#ffffff", outline="#ffffff", tags="bubble")
        for i, line in enumerate(lines):
            self.canvas.create_text(
                x1 + w / 2, y_top + 5 + i * line_h, anchor="n", tags="bubble",
                text=line, font=f, fill="#222222")

    def refresh(self) -> None:
        """外部状态变化后重绘信息层。"""
        self._draw_card()

    def apply_settings(self) -> None:
        self.attributes("-topmost", bool(self.setting.get("always_top", True)))
        self._resize_for_sprite()
        self.refresh()

    def auto_speak(self, key: str) -> None:
        self.say(phrases.random_line(key), secs=3.6)
