# -*- coding: utf-8 -*-
"""存档与设置。

存档写在用户目录（%USERPROFILE%/.pokepal/），这样打包成 exe 之后也不会
因为程序目录只读而崩。第一次启动会自动创建初始队伍。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Dict, List, Optional

from core.dex import Dex
from core.farm import SilkWorm
from core.pet import Pet

APP_NAME = "PokePal"

DEFAULT_SETTINGS = {
    "size": "中",            # 精灵图尺寸档位
    "always_top": True,      # 窗口置顶
    "click_through": False,  # 鼠标穿透
    "walk": True,            # 是否自主走动
    "follow_mouse": False,   # 跟随鼠标
    "show_bubble": True,     # 显示气泡
    "show_stats": True,      # 显示状态条
    "shiny": False,          # 闪光形态
    "night_mode": True,      # 夜间自动睡觉
    "start_backend": False,  # 提示开机自启（仅记录意图）
}

DEFAULT_BAG = {
    "oran": 5, "sitrus": 2, "pecha": 2,
    "freshwater": 5, "moomoomilk": 2,
    "towel": 3, "brush": 2, "bathbomb": 1,
    "pokeball": 1, "jumprope": 1,
    "potion": 1,
    "poke-ball": 5,
}

TEAM_LIMIT = 6   # 同行队伍上限，超出的自动送进 BOX

START_WALLET = 1_000_000   # 新存档的初始零花钱
SAVE_VERSION = 3           # v2：零花钱 120 → 1000；v3：1000 → 1,000,000（老存档一次性补足）


def items_mod():
    from core import items

    return items.ITEMS


class Store:
    def __init__(self, home: Optional[str] = None, project_root: str = "."):
        self.home = home or os.path.join(os.path.expanduser("~"), f".{APP_NAME.lower()}")
        self.project_root = os.path.abspath(project_root)
        os.makedirs(self.home, exist_ok=True)
        self.save_path = os.path.join(self.home, "save.json")
        self.sprite_cache = os.path.join(self.home, "sprite_cache")
        self.dex = Dex(
            os.path.join(self.project_root, "data", "dex.json"),
            os.path.join(self.home, "extra_dex.json"),
        )

        self.pets: List[Pet] = []
        self.worms: List[SilkWorm] = []
        self.active_uid: str = ""
        self.wallet: int = START_WALLET
        self.bag: Dict[str, int] = {}
        self.met: List[int] = []          # 图鉴「已见过」
        self.caught: List[int] = []       # 图鉴「已收服」
        self.settings: Dict = dict(DEFAULT_SETTINGS)
        self.last_explore: float = 0.0    # 上次出发探索的时间（用于冷却）
        self.explore_log: List[str] = []
        self._loaded = False

    # ------------------------------------------------------------ 存档
    def load(self) -> None:
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                data = {}
        else:
            data = {}
        self.pets = [Pet.from_dict(d) for d in data.get("pets", [])]
        self.worms = [SilkWorm.from_dict(d) for d in data.get("worms", [])]
        self.active_uid = data.get("active_uid", "")
        self.wallet = int(data.get("wallet", START_WALLET))
        self.bag = dict(data.get("bag") or {})
        self.met = [int(x) for x in data.get("met", [])]
        self.caught = [int(x) for x in data.get("caught", [])]
        self.last_explore = float(data.get("last_explore", 0) or 0)
        self.explore_log = list(data.get("explore_log") or [])
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update(data.get("settings") or {})
        self._loaded = True

        for p in self.pets:
            if not p.species_name:
                p.species_name = self.dex.name(p.species_id)

        # 老存档迁移：补上「已收服」记录，保证探索里有球可用
        for p in self.pets:
            if p.species_id not in self.caught:
                self.caught.append(p.species_id)
        has_ball = any(i.cat == "ball" for i in items_mod().values()
                       if self.item_count(i.id) > 0)
        if not has_ball:
            self.bag["poke-ball"] = max(3, self.item_count("poke-ball"))

        # 老存档迁移：初始零花钱提到 START_WALLET，一次性补足（已有更多就不动）
        if int(data.get("version", 1) or 1) < SAVE_VERSION:
            self.wallet = max(self.wallet, START_WALLET)

        if not self.pets:
            starter = Pet(25, "", "", self.dex.name(25))
            self.pets.append(starter)
            self.met = [25]
            self.caught = [25]
            self.bag = dict(DEFAULT_BAG)
            self.active_uid = starter.uid

        # 迁移到新版本后立刻落盘，免得下次启动又按老版本号算一遍
        if int(data.get("version", 1) or 1) != SAVE_VERSION:
            self.save()

    def save(self) -> None:
        if not self._loaded:
            return
        payload = {
            "version": SAVE_VERSION,
            "active_uid": self.active_uid,
            "wallet": self.wallet,
            "bag": self.bag,
            "met": sorted(set(self.met)),
            "caught": sorted(set(self.caught)),
            "last_explore": self.last_explore,
            "explore_log": self.explore_log[-30:],
            "settings": self.settings,
            "pets": [p.to_dict() for p in self.pets],
            "worms": [w.to_dict() for w in self.worms],
        }
        tmp = self.save_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.save_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[存档失败] {exc}")

    # ------------------------------------------------------------ 宠物
    @property
    def pet(self) -> Optional[Pet]:
        for p in self.pets:
            if p.uid == self.active_uid and not p.in_box:
                return p
        team = self.team()
        return team[0] if team else None

    def find(self, uid: str) -> Optional[Pet]:
        for p in self.pets:
            if p.uid == uid:
                return p
        return None

    def set_active(self, uid: str) -> None:
        self.active_uid = uid
        self.save()

    # ------------------------------------------------------------ 队伍 / BOX
    def team(self) -> List[Pet]:
        """同行队伍（不含寄存在 BOX 里的）。"""
        return [p for p in self.pets if not p.in_box]

    def box(self) -> List[Pet]:
        """BOX 仓库里的宝可梦。"""
        return [p for p in self.pets if p.in_box]

    def team_full(self) -> bool:
        return len(self.team()) >= TEAM_LIMIT

    def to_box(self, uid: str) -> tuple[bool, str]:
        pet = self.find(uid)
        if not pet:
            return False, "找不到这位同伴"
        if pet.in_box:
            return False, "它已经在仓库里了"
        if len(self.team()) <= 1:
            return False, "至少要留一位在你身边呀"
        pet.in_box = True
        if self.active_uid == uid:
            rest = self.team()
            self.active_uid = rest[0].uid if rest else ""
        self.save()
        return True, f"{pet.display_name()}被送进了 BOX 仓库，随时可以接回来"

    def from_box(self, uid: str) -> tuple[bool, str]:
        pet = self.find(uid)
        if not pet:
            return False, "找不到这位同伴"
        if not pet.in_box:
            return False, "它就在你身边呀"
        if self.team_full():
            return False, f"队伍满了（最多 {TEAM_LIMIT} 位），先寄存一位吧"
        pet.in_box = False
        self.active_uid = pet.uid
        self.save()
        return True, f"{pet.display_name()}回到你身边了！"

    def adopt(self, species_id: int, nickname: str = "", how: str = "相遇",
              level: int = 1) -> tuple[Pet, bool]:
        """收服 / 相遇一只新宝可梦，返回 (宠物, 是否因队伍满而进了 BOX)。"""
        sid = int(species_id)
        self.dex.ensure_online(sid)
        pet = Pet(sid, nickname or "", uuid.uuid4().hex[:10], self.dex.name(sid))
        pet.met_by = how
        pet.level = max(1, int(level))
        pet.exp = 0
        boxed = False
        if self.team_full():
            pet.in_box = True
            boxed = True
        self.pets.append(pet)
        if sid not in self.met:
            self.met.append(sid)
        if how == "捕捉" and sid not in self.caught:
            self.caught.append(sid)
        self.met = sorted(set(self.met))
        self.caught = sorted(set(self.caught))
        if not boxed:
            self.active_uid = pet.uid
        self.save()
        return pet, boxed

    def release(self, uid: str) -> bool:
        """放生：队伍和 BOX 里都可以，只要不是最后一位。"""
        pet = self.find(uid)
        if not pet or len(self.pets) <= 1:
            return False
        self.pets.remove(pet)
        if self.active_uid == uid:
            rest = self.team()
            self.active_uid = rest[0].uid if rest else ""
        self.save()
        return True

    # ------------------------------------------------------------ 探索
    def explore_ready(self, cooldown: float = 75.0) -> tuple[bool, float]:
        """探索冷却：返回 (能否出发, 还需等待秒数)。"""
        left = self.last_explore + cooldown - time.time()
        return (left <= 0, max(0.0, left))

    def mark_explored(self) -> None:
        self.last_explore = time.time()
        self.save()

    def add_explore_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M")
        self.explore_log.append(f"{stamp} {text}")
        self.explore_log = self.explore_log[-30:]

    # ------------------------------------------------------------ 蚕室
    def tick_worms(self) -> List[dict]:
        events: List[dict] = []
        now = time.time()
        for worm in self.worms:
            try:
                events.extend(worm.tick(now))
            except Exception as exc:  # noqa: BLE001
                print(f"[蚕室结算异常] {exc}")
        if events:
            self.save()
        return events

    def add_silkworm(self) -> Optional[SilkWorm]:
        if len(self.worms) >= 8:
            return None
        worm = SilkWorm()
        self.worms.append(worm)
        self.save()
        return worm

    def remove_worm(self, wid: str) -> bool:
        worm = next((w for w in self.worms if w.id == wid), None)
        if not worm:
            return False
        self.worms.remove(worm)
        self.save()
        return True

    # ------------------------------------------------------------ 经济
    def add_coins(self, amount: int) -> None:
        self.wallet = max(0, int(self.wallet) + int(amount))

    def buy(self, item_id: str, qty: int = 1) -> tuple[bool, str]:
        from core import items

        item = items.get(item_id)
        if not item:
            return False, "没有这件商品"
        cost = item.price * qty
        if self.wallet < cost:
            return False, f"零花钱不够（需要 {cost}，现有 {self.wallet}）"
        self.wallet -= cost
        self.bag[item_id] = self.bag.get(item_id, 0) + qty
        self.save()
        return True, f"买下了 {item.zh} x{qty}，花了 {cost} 元"

    def sell(self, item_id: str, qty: int = 1) -> tuple[bool, str]:
        """卖出材料换零花钱（目前只有蚕丝这类产出物能卖）。"""
        from core import items

        item = items.get(item_id)
        if not item:
            return False, "没有这件东西"
        price = items.SILK_PRICE if item_id == "silk" else int(item.price * 0.5)
        if price <= 0:
            return False, "这个卖不掉"
        if self.item_count(item_id) < qty:
            return False, f"数量不够（只有 {self.item_count(item_id)} 个）"
        self.take_item(item_id, qty)
        self.add_coins(price * qty)
        self.save()
        return True, f"卖出了 {item.zh} x{qty}，收入 {price * qty} 元"

    def take_item(self, item_id: str, qty: int = 1) -> bool:
        have = self.bag.get(item_id, 0)
        if have < qty:
            return False
        self.bag[item_id] = have - qty
        if self.bag[item_id] <= 0:
            self.bag.pop(item_id, None)
        return True

    def item_count(self, item_id: str) -> int:
        return self.bag.get(item_id, 0)

    # ------------------------------------------------------------ 沙盒
    def unlock_everything(self, level: int = 100) -> tuple[int, int]:
        """一键全开：图鉴全部收录、每只宝可梦都收到身边（超员进 BOX）、等级拉满。

        返回 (新增伙伴数, 伙伴总数)。同行队伍仍然最多 6 位，其余自动寄存。
        """
        ids = [int(x) for x in self.dex.all_ids()]
        self.met = sorted(set(self.met) | set(ids))
        self.caught = sorted(set(self.caught) | set(ids))

        owned = {p.species_id for p in self.pets}
        added = 0
        for sid in ids:
            if sid in owned:
                continue
            self.dex.ensure_online(sid)
            pet = Pet(sid, "", uuid.uuid4().hex[:10], self.dex.name(sid))
            pet.met_by = "全开"
            pet.level = max(1, int(level))
            pet.exp = 0
            pet.bond = 60.0
            if self.team_full():
                pet.in_box = True
            self.pets.append(pet)
            added += 1

        for p in self.pets:          # 已有的也一起拉满
            p.level = max(1, int(level))
            p.exp = 0

        if not self.active_uid or not any(
                p.uid == self.active_uid and not p.in_box for p in self.pets):
            team = self.team()
            self.active_uid = team[0].uid if team else ""
        self.save()
        return added, len(self.pets)
