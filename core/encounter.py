# -*- coding: utf-8 -*-
"""野外相遇（encounter）实体。

又一个「万物皆实体」的例子：一次相遇不是函数调用，而是一个有状态的实体——
它会警惕、会被食物吸引、会因为一次失手而想逃跑，也有自己的等级与来历。

捕捉率参考原作手感做了简化：
    rate = f(种族捕获度, 等级, 进化阶段, 当前亲密度, 球的倍率)
由于桌宠里没有战斗，因此「削弱」这一步被替换成了**投喂树果**——
喂得越多它越放松，也就越好抓。
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence

MAX_TURNS = 8


def line_depth(dex, sid: int) -> int:
    """在进化链里的位置：蛋/初始形态 = 0，最终形态 = n。"""
    depth, cur = 0, int(sid)
    for _ in range(8):
        parent = dex.parents.get(cur)
        if parent is None:
            break
        cur = parent
        depth += 1
    return depth


def catch_rate(entry: dict, level: int, stage: int, friendliness: float,
               ball_power: float) -> float:
    """计算这一球的捕捉概率（0~1）。"""
    if ball_power >= 99:  # 大师球
        return 1.0
    base = float(entry.get("capture_rate") or 45) / 255.0
    base = max(0.06, min(1.0, base))
    level_factor = 1.0 - min(int(level), 100) / 145.0
    stage_factor = max(0.45, 1.0 - 0.13 * int(stage))
    friend_factor = 1.0 + float(friendliness) / 120.0
    rare_factor = 0.35 if (entry.get("is_legendary") or entry.get("is_mythical")) else 1.0
    rate = base * level_factor * stage_factor * friend_factor * rare_factor * ball_power
    return max(0.03, min(0.95, rate))


class Encounter:
    """一次正在进行的相遇。"""

    def __init__(self, species_id: int, level: int, shiny: bool = False):
        self.species_id = int(species_id)
        self.level = int(level)
        self.shiny = shiny
        self.friendliness = 18.0      # 放松程度，0~100
        self.turns = 0
        self.fled = False
        self.caught = False
        self.baits = 0

    # ------------------------------------------------------------ 属性
    @property
    def over(self) -> bool:
        return self.fled or self.caught or self.turns >= MAX_TURNS

    @property
    def relax_zh(self) -> str:
        v = self.friendliness
        if v >= 75:
            return "完全放松了"
        if v >= 50:
            return "放松了一些"
        if v >= 30:
            return "在警惕地打量你"
        return "非常警惕"

    # ------------------------------------------------------------ 行为
    def bait(self, gain: float = 22.0) -> str:
        self.friendliness = min(100.0, self.friendliness + gain)
        self.baits += 1
        self.turns += 1
        return random.choice([
            "它小心翼翼地凑过来，闻了闻……然后吃了下去！",
            "树果的香气飘过去，它咽了咽口水。",
            "它一边吃一边偷看你，尾巴放松下来了。",
        ])

    def throw(self, entry: dict, stage: int, ball_power: float) -> Dict:
        """投球。返回一个结果字典，包含成功与否、概率、摇动次数。"""
        self.turns += 1
        rate = catch_rate(entry, self.level, stage, self.friendliness, ball_power)
        success = random.random() < rate
        shakes = 0
        if success:
            shakes = 3
            self.caught = True
        else:
            if rate > 0.55:
                shakes = 2
            elif rate > 0.3:
                shakes = 1
            # 失手会让它更警觉一点
            self.friendliness = max(0.0, self.friendliness - 8)
        return {
            "success": success, "rate": rate, "shakes": shakes,
            "turn": self.turns, "max_turns": MAX_TURNS,
        }

    def maybe_flee(self) -> Optional[str]:
        """每个回合结束判定：它会不会跑掉。"""
        if self.over or self.caught:
            return None
        chance = 0.10 + max(0.0, 45 - self.friendliness) / 220.0
        if random.random() < chance:
            self.fled = True
            return random.choice([
                "它一转身钻进了草丛，不见了。",
                "它警惕地后退两步，然后跑掉了。",
                "风一吹，草丛沙沙响——它趁机溜走了。",
            ])
        return None


def roll_wild(dex, met: Sequence[int] = (), *, rng: Optional[random.Random] = None,
              pool: Optional[List[int]] = None) -> Optional[dict]:
    """按权重随机抽一只野生宝可梦。偏好：你已经收服过的进化链、初级形态。"""
    rng = rng or random
    ids = pool if pool is not None else dex.all_ids()
    if not ids:
        return None

    legendary = []
    weighted: List[tuple[int, float]] = []
    for sid in ids:
        entry = dex.get(sid)
        if not entry:
            continue
        rare = bool(entry.get("is_legendary") or entry.get("is_mythical"))
        if rare:
            legendary.append(sid)
            continue
        w = 1.0
        if sid in met:
            w += 1.2                       # 熟悉的地方更容易遇到
        depth = line_depth(dex, sid)
        w *= max(0.35, 1.0 - 0.22 * depth)  # 初级形态更常见
        if entry.get("is_baby"):
            w *= 0.5
        weighted.append((sid, max(0.05, w)))

    # 2% 概率撞见传说中的宝可梦
    if legendary and rng.random() < 0.02:
        sid = rng.choice(legendary)
        level = rng.randint(35, 55)
    else:
        if not weighted:
            return None
        total = sum(w for _, w in weighted)
        pick = rng.random() * total
        sid = weighted[-1][0]
        for cand, w in weighted:
            pick -= w
            if pick <= 0:
                sid = cand
                break
        level = max(2, int(rng.triangular(2, 24, 7)))

    entry = dex.get(sid) or {}
    return {
        "species_id": sid,
        "level": level,
        "stage": line_depth(dex, sid),
        "shiny": rng.random() < 0.012,
        "rare": bool(entry.get("is_legendary") or entry.get("is_mythical")),
        "entry": entry,
    }
