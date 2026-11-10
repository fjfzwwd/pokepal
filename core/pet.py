# -*- coding: utf-8 -*-
"""桌宠状态机：电子宠物式的五项数值 + QQ 宠物式的活动/打工/经济。

五项数值（0~100，随时间自然下降）
    fullness  饱食度   hydration 水分   clean 清洁度
    mood      心情     stamina  体力
羁绊 bond（0~100）单独作为「亲密度」，只通过照顾行为上升，冷落会缓慢下降。

活动 activity 是一个有限状态机：
    idle / eat / play / bath / train / sleep / work / evolve
前六种一段时间自动结束，sleep 需要手动唤醒，work 是后台计时（可离开画面）。
"""

from __future__ import annotations

import random
import time
import uuid
from typing import Dict, List, Optional, Tuple

STATS = ("fullness", "hydration", "clean", "mood", "stamina")

STAT_ZH = {
    "fullness": "饱食度", "hydration": "水分", "clean": "清洁度",
    "mood": "心情", "stamina": "体力", "bond": "羁绊",
}

# 每小时自然衰减
DECAY = {"fullness": 6.0, "hydration": 7.5, "clean": 4.5, "mood": 5.0, "stamina": 4.0}

ACT_ZH = {
    "idle": "发呆", "eat": "进食中", "play": "玩耍中", "bath": "洗澡中",
    "train": "训练中", "sleep": "睡觉中", "work": "打工中", "evolve": "进化中",
}


def exp_to_next(level: int) -> int:
    """升级所需经验：前期快、后期慢，100 级封顶。"""
    return max(20, 20 + 12 * int(level) + int(level ** 1.35))


class Result:
    __slots__ = ("ok", "message", "activity", "duration", "coins", "exp")

    def __init__(self, ok: bool, message: str, activity: str = "idle",
                 duration: float = 0.0, coins: int = 0, exp: int = 0):
        self.ok = ok
        self.message = message
        self.activity = activity
        self.duration = duration
        self.coins = coins
        self.exp = exp


class Pet:
    MAX = 100.0

    def __init__(self, species_id: int, nickname: str = "", uid: str = "",
                 species_name: str = ""):
        self.uid = uid or uuid.uuid4().hex[:10]
        self.species_id = int(species_id)
        self.nickname = nickname
        self.species_name = species_name  # 图鉴里的中文名，会随进化更新
        self.level = 1
        self.exp = 0
        self.bond = 30.0
        self.stats: Dict[str, float] = {
            "fullness": 82.0, "hydration": 82.0, "clean": 85.0,
            "mood": 80.0, "stamina": 85.0,
        }
        self.activity = "idle"
        self.activity_until = 0.0
        self.work_payload: Optional[dict] = None
        self.cooldowns: Dict[str, float] = {}
        self.last_care = time.time()      # 最近一次真实互动
        self.last_seen = time.time()
        self.met_at = time.time()
        self.total_care = 0
        self.evolve_count = 0
        self.shiny = False
        self.in_box = False           # True = 寄存在 BOX 仓库里（不属于同行队伍）
        self.met_by = "相遇"          # 获得途径：相遇 / 捕捉
        self.lineage: List[int] = [self.species_id]

    # ------------------------------------------------------------ 基础
    @property
    def exp_max(self) -> int:
        return exp_to_next(self.level)

    @property
    def exp_ratio(self) -> float:
        return min(1.0, self.exp / max(1, self.exp_max))

    @property
    def care_score(self) -> float:
        return sum(self.stats.values()) / len(self.stats)

    @property
    def activity_zh(self) -> str:
        return ACT_ZH.get(self.activity, "")

    def remaining(self, now: Optional[float] = None) -> float:
        return max(0.0, self.activity_until - (now or time.time()))

    def busy(self, now: Optional[float] = None) -> bool:
        return self.activity not in ("idle", "sleep", "work") and self.remaining(now) > 0

    def _clamp(self) -> None:
        for k in STATS:
            self.stats[k] = max(0.0, min(self.MAX, self.stats[k]))
        self.bond = max(0.0, min(self.MAX, self.bond))

    def apply_effects(self, effects: Dict[str, float]) -> None:
        for key, val in effects.items():
            if key in self.stats:
                self.stats[key] += float(val)
            elif key == "bond":
                self.bond += float(val)
            elif key == "exp":
                pass  # 经验由调用方统一结算
        self._clamp()

    # ------------------------------------------------------------ 数值衰减
    def tick(self, now: Optional[float] = None) -> List[dict]:
        """推进时间。返回这段时间里发生的事件列表。"""
        now = now or time.time()
        events: List[dict] = []
        dt_hours = max(0.0, (now - self.last_seen) / 3600.0)
        self.last_seen = now
        if dt_hours <= 0 or dt_hours > 24:
            dt_hours = min(dt_hours, 24.0)

        before_sick = self.status_key() == "sick"
        sleeping = self.activity == "sleep"
        working = self.activity == "work"

        rate = 1.0
        if sleeping:
            rate = 0.45
        elif working:
            rate = 1.35

        for key in ("fullness", "hydration", "clean", "mood", "stamina"):
            delta = DECAY[key] * dt_hours * rate
            if key == "stamina" and sleeping:
                self.stats["stamina"] += 24.0 * dt_hours          # 睡觉回体力
                self.stats["mood"] += 2.0 * dt_hours
                continue
            if key == "stamina" and working:
                delta *= 1.5
            self.stats[key] -= delta

        if self.care_score >= 70 and not before_sick:
            self.stats["mood"] += 2.0 * dt_hours
        if min(self.stats["fullness"], self.stats["hydration"], self.stats["clean"]) < 15:
            self.bond -= 1.5 * dt_hours
            self.stats["mood"] -= 2.0 * dt_hours

        self._clamp()

        # 活动结束结算
        if self.activity in ("eat", "play", "bath", "train", "evolve") and now >= self.activity_until:
            finished = self.activity
            self.activity = "idle"
            self.activity_until = 0.0
            events.append({"type": "activity_done", "activity": finished})
        if working and now >= self.activity_until:
            events.append({"type": "work_ready", "payload": self.work_payload})
        if sleeping and self.stats["stamina"] >= 95:
            self.activity = "idle"
            events.append({"type": "wake", "reason": "rested"})

        if not before_sick and self.status_key() == "sick":
            events.append({"type": "sick"})
        if before_sick and self.status_key() != "sick":
            events.append({"type": "recovered"})

        return events

    # ------------------------------------------------------------ 状态判定
    def status_key(self) -> str:
        if self.activity == "work":
            return "work"
        if self.activity == "sleep":
            return "sleep"
        if min(self.stats["fullness"], self.stats["hydration"], self.stats["clean"],
               self.stats["stamina"]) <= 8:
            return "sick"
        if self.stats["fullness"] < 25:
            return "hungry"
        if self.stats["hydration"] < 25:
            return "thirsty"
        if self.stats["clean"] < 25:
            return "dirty"
        if self.stats["stamina"] < 20:
            return "tired"
        if self.stats["mood"] < 35:
            return "upset"
        if self.care_score >= 75 and self.bond >= 60:
            return "happy"
        if self.care_score >= 55:
            return "normal"
        return "upset"

    def status_zh(self) -> str:
        return {
            "idle": "正在发呆", "sleep": "睡着了", "work": "出门打工了",
            "sick": "看起来不太好…", "hungry": "肚子饿了", "thirsty": "口渴了",
            "dirty": "身上脏兮兮", "tired": "累了", "upset": "不太开心",
            "normal": "心情一般", "happy": "心情很好",
        }.get(self.status_key(), "")

    def level_ratio(self) -> Tuple[int, int]:
        return self.exp, self.exp_max

    # ------------------------------------------------------------ 经验 / 升级
    def gain_exp(self, amount: int) -> List[int]:
        gained: List[int] = []
        if amount <= 0:
            return gained
        self.exp += int(amount)
        while self.level < 100 and self.exp >= self.exp_max:
            self.exp -= self.exp_max
            self.level += 1
            gained.append(self.level)
        if self.level >= 100:
            self.exp = 0
        return gained

    # ------------------------------------------------------------ 互动
    def touch(self, limit_sec: int = 45) -> Result:
        """抚摸/点击。短时间内重复点不会有收益，避免无限刷羁绊。"""
        now = time.time()
        if now - self.cooldowns.get("touch", 0) < limit_sec:
            return Result(False, f"{self.display_name()}把脸凑过来蹭了蹭")
        self.cooldowns["touch"] = now
        gain = 0.8 + random.random() * 0.7
        self.bond += gain
        self.stats["mood"] += 1.5
        self.total_care += 1
        self.last_care = now
        self._clamp()
        return Result(True, f"摸了摸{self.display_name()}，羁绊 +{gain:.1f}")

    def display_name(self) -> str:
        return self.nickname or self.species_name or f"#{self.species_id:04d}"

    def start_activity(self, activity: str, duration: float) -> None:
        self.activity = activity
        self.activity_until = time.time() + max(0.5, duration)

    def _begin(self, activity: str, duration: float) -> Optional[Result]:
        if self.activity in ("work", "sleep"):
            hint = "正在睡觉，先叫醒它吧" if self.activity == "sleep" else "还在外面打工呢"
            return Result(False, hint)
        if self.busy():
            return Result(False, f"{self.display_name()}正忙着：{self.activity_zh}")
        self.start_activity(activity, duration)
        return None

    # ------------------------------------------------------------ 各类行为
    def use_item(self, item) -> Result:
        """根据道具类别执行照顾动作。"""
        cat = item.cat
        if cat in ("food", "drink"):
            return self.feed(item)
        if cat == "care":
            return self.wash(item)
        if cat == "toy":
            return self.play(item)
        if cat == "medicine":
            return self.heal(item)
        return Result(False, "这个道具没法直接使用")

    def feed(self, item) -> Result:
        block = self._begin("eat", 4.0)
        if block:
            return block
        too_much = (
            "hydration" if getattr(item, "cat", "") == "drink" else "fullness"
        )
        if self.stats[too_much] > 96:
            self.activity, self.activity_until = "idle", 0.0
            tip = "喝不下了" if too_much == "hydration" else "吃不下了"
            return Result(False, f"{self.display_name()}摇摇头，实在{tip}")
        self.apply_effects(item.effects)
        exp = int(item.effects.get("exp", 0)) + 2
        self.total_care += 1
        self.last_care = time.time()
        self.gain_exp(exp)
        return Result(True, f"{self.display_name()}吃掉了「{item.zh}」", "eat", 4.0, exp=exp)

    def wash(self, item) -> Result:
        block = self._begin("bath", 5.0)
        if block:
            return block
        self.apply_effects(item.effects)
        self.total_care += 1
        self.last_care = time.time()
        self.gain_exp(int(item.effects.get("exp", 0)) + 1)
        return Result(True, f"用「{item.zh}」把{self.display_name()}洗得香喷喷", "bath", 5.0)

    def play(self, item) -> Result:
        block = self._begin("play", 5.0)
        if block:
            return block
        if self.stats["stamina"] < 15:
            self.activity, self.activity_until = "idle", 0.0
            return Result(False, f"{self.display_name()}太累了，需要先睡觉")
        self.apply_effects(item.effects)
        self.total_care += 1
        self.last_care = time.time()
        exp = int(item.effects.get("exp", 0)) + 3
        self.gain_exp(exp)
        return Result(True, f"和{self.display_name()}一起玩「{item.zh}」", "play", 5.0, exp=exp)

    def heal(self, item) -> Result:
        self.apply_effects(item.effects)
        self.apply_effects({"mood": 4.0, "bond": 1.0})
        self.total_care += 1
        if self.activity == "work":
            self.activity = "idle"
        return Result(True, f"给{self.display_name()}用了「{item.zh}」，气色好多了", "idle")

    def train(self) -> Result:
        now = time.time()
        if self.activity == "sleep":
            return Result(False, "嘘，它睡着了")
        if self.activity == "work":
            return Result(False, "还在外面打工呢")
        if now - self.cooldowns.get("train", 0) < 50:
            left = int(50 - (now - self.cooldowns["train"]))
            return Result(False, f"刚练完一组，稍等 {left} 秒")
        if self.stats["stamina"] < 20:
            return Result(False, "体力不够了，先吃点东西或睡一觉")
        self.cooldowns["train"] = now
        block = self._begin("train", 6.0)
        if block:
            return block
        cost = min(18.0, self.stats["stamina"] / 2)
        self.stats["stamina"] -= cost
        self.stats["fullness"] -= 6
        self.stats["hydration"] -= 8
        self.stats["clean"] -= 5
        exp = 12 + random.randint(0, 6) + self.level // 4
        self.gain_exp(exp)
        self.bond += 1.2
        self.total_care += 1
        coins = 6 + random.randint(0, 5)
        self._clamp()
        return Result(True, f"{self.display_name()}完成了一组特训！经验 +{exp}",
                      "train", 6.0, coins=coins, exp=exp)

    def sleep_toggle(self) -> Result:
        if self.activity == "sleep":
            self.activity = "idle"
            self.activity_until = 0.0
            return Result(True, f"{self.display_name()}醒来了，伸了个懒腰")
        if self.busy():
            return Result(False, f"{self.display_name()}正忙着：{self.activity_zh}")
        self.activity = "sleep"
        self.activity_until = 0.0
        return Result(True, f"{self.display_name()}蜷成一团睡着了…", "sleep")

    def start_work(self, minutes: int) -> Result:
        if self.activity == "work":
            left = int(self.remaining() // 60)
            return Result(False, f"打工还剩大约 {left} 分钟")
        if self.stats["stamina"] < 45 or self.stats["mood"] < 45:
            return Result(False, "状态不够好，休息一下再去打工吧")
        now = time.time()
        if now - self.cooldowns.get("work", 0) < 120:
            return Result(False, "刚打工回来，先在家里歇会儿")
        self.activity = "work"
        self.activity_until = now + minutes * 60
        self.work_payload = {
            "minutes": minutes,
            "coins": int(minutes * (4.2 + self.level * 0.12)),
            "exp": int(minutes * (2.2 + self.level * 0.05)),
        }
        self.last_care = now
        return Result(True, f"{self.display_name()}背起小包出门打工了（{minutes}分钟）", "work")

    def collect_work(self) -> Result:
        payload = self.work_payload or {"coins": 20, "exp": 10, "minutes": 5}
        self.activity = "idle"
        self.activity_until = 0.0
        self.cooldowns["work"] = time.time()
        self.work_payload = None
        self.stats["stamina"] -= min(25.0, 6 + payload["minutes"] * 0.8)
        self.stats["fullness"] -= min(20.0, 4 + payload["minutes"] * 0.6)
        self.stats["hydration"] -= min(22.0, 5 + payload["minutes"] * 0.7)
        self.stats["clean"] -= min(20.0, 3 + payload["minutes"] * 0.5)
        self.bond += 2
        self.gain_exp(payload["exp"])
        self._clamp()
        return Result(True, f"{self.display_name()}打工回来啦！挣了 {payload['coins']} 元零花钱",
                      "idle", coins=payload["coins"], exp=payload["exp"])

    def apply_evolution(self, target_id: int, source: str = "进化",
                        species_name: str = "") -> Result:
        """统一入口：等级进化、羁绊进化、道具进化都走这里。"""
        self.activity = "evolve"
        self.activity_until = time.time() + 3.2
        if self.species_id not in self.lineage:
            self.lineage.append(self.species_id)
        self.species_id = int(target_id)
        if species_name:
            self.species_name = species_name
        self.evolve_count += 1
        self.bond = min(self.MAX, self.bond + 6)
        self.gain_exp(15)
        return Result(True, f"{self.display_name()}沐浴在{source}的光芒中……", "evolve", 3.2)

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "species_id": self.species_id, "nickname": self.nickname,
            "species_name": self.species_name,
            "level": self.level, "exp": self.exp, "bond": self.bond, "stats": self.stats,
            "activity": self.activity, "activity_until": self.activity_until,
            "work_payload": self.work_payload, "cooldowns": self.cooldowns,
            "last_care": self.last_care, "last_seen": self.last_seen, "met_at": self.met_at,
            "total_care": self.total_care, "evolve_count": self.evolve_count,
            "shiny": self.shiny, "lineage": self.lineage,
            "in_box": self.in_box, "met_by": self.met_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pet":
        pet = cls(int(data.get("species_id", 25)), data.get("nickname", ""),
                  data.get("uid", ""), data.get("species_name", ""))
        pet.level = int(data.get("level", 1))
        pet.exp = int(data.get("exp", 0))
        pet.bond = float(data.get("bond", 30))
        pet.stats.update({k: float(v) for k, v in (data.get("stats") or {}).items() if k in STATS})
        pet.activity = data.get("activity", "idle")
        pet.activity_until = float(data.get("activity_until", 0) or 0)
        pet.work_payload = data.get("work_payload")
        pet.cooldowns = {k: float(v) for k, v in (data.get("cooldowns") or {}).items()}
        pet.last_care = float(data.get("last_care", time.time()))
        pet.last_seen = float(data.get("last_seen", time.time()))
        pet.met_at = float(data.get("met_at", time.time()))
        pet.total_care = int(data.get("total_care", 0))
        pet.evolve_count = int(data.get("evolve_count", 0))
        pet.shiny = bool(data.get("shiny", False))
        pet.lineage = [int(x) for x in (data.get("lineage") or [pet.species_id])]
        pet.in_box = bool(data.get("in_box", False))
        pet.met_by = data.get("met_by", "相遇")
        return pet
