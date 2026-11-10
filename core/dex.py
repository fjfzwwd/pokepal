# -*- coding: utf-8 -*-
"""图鉴（dex）数据访问。

本地 data/dex.json 由 tools/fetch_dex.py 从 PokéAPI 生成，包含：
    entries   : 编号 -> {zh, en, types, flavor, ...}
    evolution : 编号 -> [{to, conditions:[{trigger,min_level,min_happiness,item,...}]}]
    parents   : 编号 -> 父编号
    roots     : 每条进化链最初级的那只

除此之外支持「临时查询任意编号」——玩家在图鉴里输入 493 这种本地没有的
编号时，联网把这一条拉下来并写进用户目录的小表，下次离线也能显示。
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict, List, Optional

API = "https://pokeapi.co/api/v2"
UA = {"User-Agent": "PokePal-DesktopPet/1.0 (+learning project)"}

STONE_NAMES = {
    "thunder-stone": "雷之石", "water-stone": "水之石", "fire-stone": "火之石",
    "leaf-stone": "叶之石", "ice-stone": "冰之石", "moon-stone": "月之石",
    "sun-stone": "日之石", "shiny-stone": "光之石", "dusk-stone": "暗之石",
    "dawn-stone": "觉醒石", "oval-stone": "圆之石", "black-augurite": "黑奇石",
    "deep-sea-tooth": "深海牙", "deep-sea-scale": "深海鳞",
    "metal-coat": "金属膜", "kings-rock": "王者之证", "dragon-scale": "龙之鳞片",
    "upgrade": "升级装置", "razor-claw": "锐利爪", "razor-fang": "锐利牙",
    "protector": "护身甲", "electirizer": "电力增幅器", "magmarizer": "熔岩增幅器",
    "reaper-cloth": "暗之石 cloth", "prism-scale": "棱镜鳞片", "sachet": "香包",
    "whipped-dream": "奶油泡芙", "black-augurite": "黑奇石", "galarica-cuff": "伽勒尔豆蔻手环",
    "sun-stone": "日之石", "linking-cord": "结缘绳", "sweet-apple": "甜蜜球果",
    "tart-apple": "酸涩球果", "cracked-pot": "破碎的壶", "chipped-pot": "破损的壶",
    "galarica-wreath": "伽勒尔豆蔻花圈", "auspicious-armor": "吉祥之铠",
    "malicious-armor": "诅咒之铠", "gimmighoul-coin": "来悲茶的硬币",
}

TYPE_ZH = {
    "normal": "一般", "fire": "火", "water": "水", "electric": "电", "grass": "草",
    "ice": "冰", "fighting": "格斗", "poison": "毒", "ground": "地面", "flying": "飞行",
    "psychic": "超能力", "bug": "虫", "rock": "岩石", "ghost": "幽灵", "dragon": "龙",
    "dark": "恶", "steel": "钢", "fairy": "妖精", "stellar": "太晶", "unknown": "???",
}

TRIGGER_ZH = {
    "level-up": "等级提升", "use-item": "使用道具", "trade": "心灵相通",
    "shed": "蜕皮", "spin": "旋转", "take-damage": "受伤", "other": "特殊",
    "tower-of-darkness": "暗之塔", "tower-of-waters": "水之塔",
}


def _zh_name(names: List[dict]) -> str:
    for code in ("zh-hans", "zh-hant"):
        for item in names:
            if item.get("language", {}).get("name", "").lower() == code:
                return item.get("name", "")
    return ""


def _now_is_day() -> bool:
    """白天 = 6:00~18:00，和游戏里的「白天/夜晚」分化对应。"""
    import datetime

    return 6 <= datetime.datetime.now().hour < 18


def _types_zh(types: List[str]) -> str:
    return "/".join(TYPE_ZH.get(t, t) for t in types) or "???"


class Dex:
    def __init__(self, data_path: str, extra_path: str):
        self.data_path = data_path
        self.extra_path = extra_path
        self.entries: Dict[int, dict] = {}
        self.evolution: Dict[int, List[dict]] = {}
        self.parents: Dict[int, Optional[int]] = {}
        self.roots: List[int] = []
        self._load_local()
        self._load_extra()

    # ------------------------------------------------------------- 载入
    def _load_local(self) -> None:
        if not os.path.exists(self.data_path):
            return
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            return
        for k, v in data.get("entries", {}).items():
            self.entries[int(k)] = v
        for k, v in data.get("evolution", {}).items():
            self.evolution[int(k)] = v
        for k, v in data.get("parents", {}).items():
            try:
                self.parents[int(k)] = int(v) if v is not None else None
            except (TypeError, ValueError):
                self.parents[int(k)] = None
        self.roots = [int(r) for r in data.get("roots", [])]

    def _load_extra(self) -> None:
        if not os.path.exists(self.extra_path):
            return
        try:
            with open(self.extra_path, "r", encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    self.entries.setdefault(int(k), v)
        except Exception:  # noqa: BLE001
            pass

    def _save_extra(self, sid: int, entry: dict) -> None:
        self.entries[sid] = entry
        data = {}
        if os.path.exists(self.extra_path):
            try:
                with open(self.extra_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                data = {}
        data[str(sid)] = entry
        os.makedirs(os.path.dirname(self.extra_path), exist_ok=True)
        with open(self.extra_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------- 查询
    def has(self, sid: int) -> bool:
        return sid in self.entries

    def get(self, sid: int) -> Optional[dict]:
        return self.entries.get(int(sid))

    def name(self, sid: int) -> str:
        e = self.entries.get(int(sid))
        if not e:
            return f"#{sid:04d}"
        return e.get("zh") or e.get("en") or f"#{sid:04d}"

    def en(self, sid: int) -> str:
        e = self.entries.get(int(sid))
        return (e or {}).get("en", "")

    def types_zh(self, sid: int) -> str:
        e = self.entries.get(int(sid))
        return _types_zh((e or {}).get("types", []))

    def display(self, sid: int) -> str:
        return f"{self.name(sid)}　#{sid:04d}　{self.types_zh(sid)}"

    def all_ids(self) -> List[int]:
        return sorted(self.entries.keys())

    def line_root(self, sid: int) -> int:
        cur = int(sid)
        for _ in range(12):
            parent = self.parents.get(cur)
            if parent is None:
                return cur
            cur = parent
        return cur

    def line_members(self, sid: int) -> List[int]:
        """返回同一条进化链上的全部成员（含自己）。"""
        root = self.line_root(sid)
        seen: List[int] = []

        def walk(cur: int) -> None:
            if cur in seen or cur not in self.entries:
                return
            seen.append(cur)
            for evo in self.evolution.get(cur, []):
                walk(int(evo["to"]))

        walk(root)
        return sorted(seen)

    def evolutions_of(self, sid: int) -> List[dict]:
        return self.evolution.get(int(sid), [])

    def next_form(self, sid: int) -> Optional[int]:
        evos = self.evolution.get(int(sid), [])
        return int(evos[0]["to"]) if evos else None

    def describe_condition(self, cond: dict) -> str:
        trigger = cond.get("trigger") or "level-up"
        item = cond.get("item")
        level = cond.get("min_level")
        happy = cond.get("min_happiness")
        tod = cond.get("time_of_day") or ""
        parts = []
        if trigger == "use-item":
            parts.append(f"使用{STONE_NAMES.get(item, item or '道具')}")
        elif trigger == "trade":
            parts.append("羁绊满值（替代通讯交换）")
        else:
            if level:
                parts.append(f"等级达到 {level}")
            if happy:
                parts.append(f"羁绊达到 {round(happy / 2.55)}")
            if tod == "day":
                parts.append("白天")
            elif tod == "night":
                parts.append("夜晚")
            if item:
                parts.append(f"携带{STONE_NAMES.get(item, item)}")
            if not parts:
                parts.append(TRIGGER_ZH.get(trigger, "特殊条件"))
        return " · ".join(parts)

    def evolution_options(self, sid: int, level: int, bond: int,
                          has_item: Optional[callable] = None) -> List[dict]:
        """列出该宝可梦的所有进化去向，并标注当前是否可以进化。"""
        out: List[dict] = []
        for evo in self.evolutions_of(sid):
            target = int(evo["to"])
            if target not in self.entries:
                continue
            ready, how, needs_item = False, "未知条件", None
            for cond in evo.get("conditions") or [{}]:
                trigger = cond.get("trigger") or "level-up"
                item = cond.get("item")
                level_ok = not cond.get("min_level") or level >= int(cond["min_level"])
                happy_need = cond.get("min_happiness")
                happy_ok = not happy_need or bond * 2.55 >= int(happy_need)
                tod = cond.get("time_of_day") or ""
                tod_ok = True
                if tod in ("day", "night"):
                    tod_ok = (_now_is_day() if tod == "day" else not _now_is_day())
                how = self.describe_condition(cond)

                if trigger == "use-item":
                    needs_item = item
                    ready = bool(has_item and has_item(item)) and level_ok
                elif trigger == "trade":
                    ready = bond >= 100 and level >= 30
                    how = "羁绊满值·心灵相通（替代通讯交换）"
                elif trigger == "level-up":
                    constrained = any(
                        (cond.get(k) for k in ("min_level", "min_happiness", "item",
                                               "time_of_day", "gender", "held_item",
                                               "relative_physical_stats", "known_move",
                                               "location", "party_species"))
                    )
                    if item and not constrained:
                        constrained = True
                    if not constrained:
                        ready = False
                        how = "特殊条件（游戏中另有隐藏要求）"
                    else:
                        ready = level_ok and happy_ok and tod_ok
                        if item and not (has_item and has_item(item)):
                            ready = False
                            needs_item = item
                        how = self.describe_condition(cond)
                else:
                    ready = False
                    how = TRIGGER_ZH.get(trigger, "特殊条件")
                if ready:
                    break
            out.append({"to": target, "how": how, "ready": ready, "item": needs_item})
        return out

    # ------------------------------------------------------------- 在线
    def ensure_online(self, sid: int, timeout: int = 12) -> bool:
        """联网补充一只本地没有的宝可梦。成功返回 True。"""
        if sid in self.entries:
            return True
        try:
            req = urllib.request.Request(f"{API}/pokemon-species/{sid}", headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                sp = json.loads(r.read().decode("utf-8"))
            types: List[str] = []
            try:
                req = urllib.request.Request(f"{API}/pokemon/{sid}", headers=UA)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    types = [t["type"]["name"] for t in json.loads(r.read().decode("utf-8")).get("types", [])]
            except Exception:  # noqa: BLE001
                pass
            entry = {
                "id": sid,
                "en": sp.get("name", ""),
                "zh": _zh_name(sp.get("names", [])),
                "color": (sp.get("color") or {}).get("name", ""),
                "habitat": (sp.get("habitat") or {}).get("name", ""),
                "is_legendary": sp.get("is_legendary", False),
                "is_baby": sp.get("is_baby", False),
                "capture_rate": sp.get("capture_rate", 0),
                "growth_rate": (sp.get("growth_rate") or {}).get("name", ""),
                "flavor": "",
                "types": types,
            }
            self._save_extra(sid, entry)
            return True
        except Exception:  # noqa: BLE001
            return False

    def search(self, keyword: str) -> List[int]:
        kw = keyword.strip().lower()
        if not kw:
            return []
        if kw.isdigit():
            sid = int(kw)
            return [sid] if sid in self.entries else []
        hits = []
        for sid, e in sorted(self.entries.items()):
            if kw in (e.get("zh", "") + e.get("en", "")).lower():
                hits.append(sid)
        return hits[:60]
