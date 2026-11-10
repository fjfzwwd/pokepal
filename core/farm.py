# -*- coding: utf-8 -*-
"""实体化示例：蚕。

这条原因：任何有价值的东西都应该有自己的一圈 constituents——
状态、行为、UI。这里用一个小身的家蚕展示同一个模型：
它不是"一个道具"，而是一个独立的"生物样品"，有时间、有需求、有演化阶段。

生命周期：卵 -> 蚁蚕 -> 幼虫 -> 结茧 -> 蚕蛾
照料行为：投喂桑叶 / 清理蚕室 / 采收蚕丝
忽视后果：饥饿与脏污会让它停止生长，长期不管会死亡。
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

STAGE_NAMES = ["卵", "蚁蚕", "幼虫", "结茧", "蚕蛾"]
STAGE_HOURS = [6.0, 10.0, 14.0, 10.0, 24.0]
STAGE_EMOJI = ["🥚", "🐛", "🐛", "🕸️", "🦋"]

HUNGER_PER_HOUR = 9.0
DIRT_PER_HOUR = 5.0
DEATH_HOURS_NEGLECT = 30.0


def _stage_name(stage: int) -> str:
    return STAGE_NAMES[stage] if 0 <= stage < len(STAGE_NAMES) else "???"


class SilkWorm:
    """一只需要被照料的蚕。"""

    def __init__(self, wid: str = ""):
        self.id = wid or uuid.uuid4().hex[:8]
        self.stage = 0
        self.progress = 0.0            # 当前阶段的成长度 0~100
        self.hunger = 15.0             # 0 饱腹，100 饿到极限
        self.dirty = 10.0              # 0 干净，100 脏到极限
        self.alive = True
        self.silk_ready = False        # 结茧完成、等待采收
        self.silk_amount = 0
        self.neglect_hours = 0.0
        self.created_at = time.time()
        self.last_seen = time.time()

    # ------------------------------------------------------------ 属性
    @property
    def stage_name(self) -> str:
        return _stage_name(self.stage)

    @property
    def emoji(self) -> str:
        return STAGE_EMOJI[self.stage] if 0 <= self.stage < len(STAGE_EMOJI) else "🐛"

    @property
    def mature(self) -> bool:
        return self.stage >= len(STAGE_NAMES) - 1

    def status_key(self) -> str:
        if not self.alive:
            return "dead"
        if self.hunger >= 85 or self.dirty >= 85:
            return "sick"
        if self.hunger >= 60:
            return "hungry"
        if self.dirty >= 60:
            return "dirty"
        if self.silk_ready:
            return "harvest"
        if self.mature:
            return "moth"
        return "growing"

    def status_zh(self) -> str:
        return {
            "dead": "已经不在了…", "sick": "状态很差", "hungry": "饿得不行了",
            "dirty": "蚕室太脏了", "harvest": "可以收蚕丝了", "moth": "化蛾完成",
            "growing": "正在成长",
        }.get(self.status_key(), "???")

    # ------------------------------------------------------------ 时间
    def tick(self, now: Optional[float] = None) -> List[dict]:
        now = now or time.time()
        events: List[dict] = []
        dt = max(0.0, (now - self.last_seen) / 3600.0)
        self.last_seen = now
        if not self.alive or dt <= 0:
            return events
        dt = min(dt, 24.0)

        before = self.stage
        self.hunger = min(100.0, self.hunger + HUNGER_PER_HOUR * dt)
        self.dirty = min(100.0, self.dirty + DIRT_PER_HOUR * dt)

        if self.hunger >= 85 or self.dirty >= 85:
            self.neglect_hours += dt
            if self.neglect_hours > DEATH_HOURS_NEGLECT:
                self.alive = False
                events.append({"type": "worm_died", "id": self.id})
                return events
        else:
            self.neglect_hours = max(0.0, self.neglect_hours - dt * 0.5)
            if not self.mature:
                need = STAGE_HOURS[self.stage] if self.stage < len(STAGE_HOURS) else 24.0
                self.progress += 100.0 * dt / need
                while self.progress >= 100.0 and self.stage < len(STAGE_NAMES) - 1:
                    self.progress -= 100.0
                    self.stage += 1
                    events.append({"type": "worm_stage", "id": self.id,
                                   "stage": self.stage, "name": self.stage_name})
                if self.mature:
                    self.progress = 100.0
        if before != self.stage and self.stage == len(STAGE_NAMES) - 2:
            self.silk_ready = True
            self.silk_amount = 2
        return events

    # ------------------------------------------------------------ 行为
    def feed(self) -> bool:
        if not self.alive or self.stage == 0:
            return False
        if self.hunger <= 5:
            return False
        self.hunger = max(0.0, self.hunger - 45)
        self.progress = min(100.0, self.progress + 4)
        return True

    def clean(self) -> bool:
        if not self.alive:
            return False
        if self.dirty <= 5:
            return False
        self.dirty = max(0.0, self.dirty - 60)
        return True

    def harvest(self) -> int:
        if not self.alive or not self.silk_ready:
            return 0
        self.silk_ready = False
        got = max(1, int(self.silk_amount))
        self.silk_amount = 0
        return got

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict:
        return {
            "id": self.id, "stage": self.stage, "progress": self.progress,
            "hunger": self.hunger, "dirty": self.dirty, "alive": self.alive,
            "silk_ready": self.silk_ready, "silk_amount": self.silk_amount,
            "neglect_hours": self.neglect_hours, "created_at": self.created_at,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SilkWorm":
        worm = cls(data.get("id", ""))
        worm.stage = int(data.get("stage", 0))
        worm.progress = float(data.get("progress", 0))
        worm.hunger = float(data.get("hunger", 15))
        worm.dirty = float(data.get("dirty", 10))
        worm.alive = bool(data.get("alive", True))
        worm.silk_ready = bool(data.get("silk_ready", False))
        worm.silk_amount = int(data.get("silk_amount", 0))
        worm.neglect_hours = float(data.get("neglect_hours", 0))
        worm.created_at = float(data.get("created_at", time.time()))
        worm.last_seen = float(data.get("last_seen", time.time()))
        return worm
