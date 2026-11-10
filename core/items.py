# -*- coding: utf-8 -*-
"""道具表与背包。

经济模型参考 QQ 宠物：桌宠会消耗零花钱买吃的用的，钱靠「打工 / 训练 / 任务」赚。
道具分成五类：
    food 食物（涨饱食度）  drink 饮品（涨水分）  care 清洁用品
    toy  玩具（涨心情/羁绊） stone 进化石（触发道具进化）
"""

from __future__ import annotations

from typing import Dict, List

CAT_ZH = {
    "food": "食物", "drink": "饮品", "care": "清洁",
    "toy": "玩具", "stone": "进化石", "medicine": "药品",
    "ball": "精灵球", "supply": "经营补给", "material": "材料",
}

# 精灵球的捕捉倍率（对应原作的大致手感）
BALL_POWER = {
    "poke-ball": 1.0, "great-ball": 1.5, "ultra-ball": 2.0, "master-ball": 99.0,
}


def ball_power(item_id: str) -> float:
    return BALL_POWER.get(item_id, 0.0)


def is_ball(item_id: str) -> bool:
    return item_id in BALL_POWER


class Item:
    __slots__ = ("id", "zh", "cat", "price", "desc", "effects", "cooldown")

    def __init__(self, id: str, zh: str, cat: str, price: int, desc: str,
                 effects: Dict[str, float], cooldown: int = 0):
        self.id = id
        self.zh = zh
        self.cat = cat
        self.price = price
        self.desc = desc
        self.effects = effects
        self.cooldown = cooldown

    @property
    def cat_zh(self) -> str:
        return CAT_ZH.get(self.cat, self.cat)

    def to_dict(self) -> dict:
        return {"id": self.id, "zh": self.zh, "cat": self.cat, "price": self.price,
                "desc": self.desc, "effects": self.effects, "cooldown": self.cooldown}


def _item(*args) -> Item:
    return Item(*args)


ITEMS: Dict[str, Item] = {}


def _register(items: List[Item]) -> None:
    for it in items:
        ITEMS[it.id] = it


_register([
    # ---------------------------------------------------------------- 食物
    _item("oran", "橙橙果", "food", 12, "树上的酸甜果子，恢复少量体力。",
          {"fullness": 22, "hydration": 8, "mood": 2, "exp": 1}),
    _item("pecha", "桃桃果", "food", 14, "香甜的桃子味，宝可梦很喜欢。",
          {"fullness": 26, "hydration": 10, "mood": 3, "exp": 1}),
    _item("sitrus", "文柚果", "food", 22, "水当当的柑橘，解饿又解渴。",
          {"fullness": 30, "hydration": 22, "mood": 3, "exp": 2}),
    _item("lum", "木子果", "food", 30, "略苦，但吃下去精神会变好。",
          {"fullness": 24, "stamina": 18, "mood": 2}),
    _item("poffin", "宝芬", "food", 45, "自己烤的松饼，香气会让人心情变好。",
          {"fullness": 42, "mood": 10, "bond": 4, "exp": 3}),
    _item("pokebean", "精灵豆豆", "food", 60, "训练师手工点心，加餐首选。",
          {"fullness": 55, "mood": 8, "bond": 5, "exp": 4}),
    _item("bigmalasada", "巨大马拉萨达", "food", 88, "阿罗拉名产，甜到发光。",
          {"fullness": 70, "mood": 14, "bond": 6, "exp": 6, "stamina": 6}),
    # ---------------------------------------------------------------- 饮品
    _item("freshwater", "矿泉水", "drink", 8, "最朴素也最解渴。",
          {"hydration": 30}),
    _item("moomoomilk", "哞哞牛奶", "drink", 25, "大奶罐牧场的招牌牛奶。",
          {"hydration": 45, "fullness": 8, "mood": 4, "stamina": 5, "exp": 2}),
    _item("lemonade", "柠檬水", "drink", 20, "酸甜冰凉，夏天最爱。",
          {"hydration": 42, "mood": 6}),
    _item("berryjuice", "树果汁", "drink", 35, "多种树果榨成，营养均衡。",
          {"hydration": 38, "fullness": 18, "stamina": 8, "mood": 3, "exp": 2}),
    # ---------------------------------------------------------------- 清洁
    _item("towel", "柔软毛巾", "care", 10, "擦一擦，精神一百倍。",
          {"clean": 35, "mood": 2}),
    _item("bathbomb", "泡泡浴球", "care", 30, "一朵云似的泡泡，洗得干干净净。",
          {"clean": 65, "mood": 8, "bond": 2}),
    _item("brush", "梳理毛刷", "care", 18, "顺毛专用，梳完全身都亮。",
          {"clean": 45, "mood": 5, "bond": 3}),
    _item("shampoo", "温和沐浴露", "care", 42, "洗完香喷喷，蓬松度 +100。",
          {"clean": 85, "mood": 10, "bond": 3, "stamina": -2}),
    # ---------------------------------------------------------------- 玩具
    _item("pokeball", "弹力球", "toy", 40, "经典的抛接游戏，最能吸引它的注意力。",
          {"mood": 16, "bond": 5, "stamina": -8, "exp": 5}),
    _item("pokeflute", "宝可梦之笛", "toy", 55, "吹起来它会跟着哼。",
          {"mood": 20, "bond": 6, "stamina": -3, "exp": 4}),
    _item("jumprope", "跳绳", "toy", 50, "一起跳，练体力也练默契。",
          {"mood": 14, "bond": 5, "stamina": -14, "exp": 9}),
    # ---------------------------------------------------------------- 药品
    _item("potion", "伤药", "medicine", 40, "治好虚弱状态，恢复气色。",
          {"stamina": 30, "mood": 6, "cure": 1}),
    _item("revival_herb", "元气草", "medicine", 70, "味道很糟，但很提神。",
          {"stamina": 45, "fullness": 10, "cure": 1, "mood": -2}),
    # ---------------------------------------------------------------- 进化石
    _item("thunder-stone", "雷之石", "stone", 220, "让电气系宝可梦进化的石头。", {}),
    _item("water-stone", "水之石", "stone", 220, "让水系宝可梦进化的石头。", {}),
    _item("fire-stone", "火之石", "stone", 220, "让火系宝可梦进化的石头。", {}),
    _item("leaf-stone", "叶之石", "stone", 220, "让草系宝可梦进化的石头。", {}),
    _item("ice-stone", "冰之石", "stone", 220, "让冰系宝可梦进化的石头。", {}),
    _item("moon-stone", "月之石", "stone", 240, "夜里会发光的圆石。", {}),
    _item("sun-stone", "日之石", "stone", 240, "闪闪发烫的红色石头。", {}),
    _item("shiny-stone", "光之石", "stone", 240, "像星星那样闪。", {}),
    _item("dusk-stone", "暗之石", "stone", 240, "散发着暗暗的光。", {}),
    _item("dawn-stone", "觉醒石", "stone", 240, "晶莹剔透，照出本性。", {}),
    # ---------------------------------------------------------------- 精灵球
    _item("poke-ball", "精灵球", "ball", 200, "最基础的捕捉道具，什么都抓得住一点点。", {}),
    _item("great-ball", "超级球", "ball", 600, "比精灵球更好抓，野外探索的常备品。", {}),
    _item("ultra-ball", "高级球", "ball", 1200, "抓稀有的宝可梦就靠它。", {}),
    _item("master-ball", "大师球", "ball", 20000, "必定成功。传说中只做了一颗的那种。", {}),
    # ---------------------------------------------------------------- 经营补给
    _item("mulberry", "桑叶", "supply", 6, "蚕宝宝的唯一口粮，要新鲜。", {}),
    _item("worm_egg", "蚕卵", "supply", 60, "放在蚕室里，过几小时就会孵化。", {}),
    # ---------------------------------------------------------------- 材料
    _item("silk", "蚕丝", "material", 0, "收自蚕茧，卖给行商能换零花钱。", {}),
])

SHOP_ORDER = ["food", "drink", "care", "toy", "medicine", "ball", "supply", "stone"]

SILK_PRICE = 45  # 蚕丝的收购价


def get(item_id: str) -> Item | None:
    return ITEMS.get(item_id)


def by_category(cat: str) -> List[Item]:
    return [i for i in ITEMS.values() if i.cat == cat]


def usable_items() -> List[Item]:
    """可在「喂食 / 清洁 / 玩耍 / 治疗」里直接使用的道具。"""
    return [i for i in ITEMS.values() if i.cat in ("food", "drink", "care", "toy", "medicine")]
