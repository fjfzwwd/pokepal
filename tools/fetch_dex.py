# -*- coding: utf-8 -*-
"""图鉴数据生成工具（仅开发期使用）

从 PokéAPI 拉取指定进化链的完整数据：
    - 简体中文名 / 英文名 / 编号
    - 进化条件（最低等级、道具、亲密度、特殊）
    - 属性组合

产出 data/dex.json，运行时只需要读本地文件，无需联网。

用法：
    python tools/fetch_dex.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://pokeapi.co/api/v2"
UA = {"User-Agent": "PokePal-DesktopPet/1.0 (+https://github.com/)"}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "dex.json")

# 默认精选的进化链（按起始形态编号填写），覆盖各世代人气御三家与经典宝可梦
BASE_SPECIES = [
    1, 4, 7,        # 初代御三家
    172,            # 皮丘 -> 皮卡丘 -> 雷丘
    133,            # 伊布（多分支进化）
    52, 92, 129, 143,
    155, 158, 175, 179,   # 二代：火球鼠、小锯鳄、波克比、咩利羊
    252, 255, 258, 263, 280,   # 三代：木守宫、火稚鸡、水跃鱼、蛇纹熊、拉鲁拉丝
    387, 393, 447,  # 四代：草苗龟、波加曼、利欧路
    501, 570,       # 五代：水水獭、索罗亚
    656, 700,       # 六代：呱呱泡蛙、绵绵泡芙
    722, 728,       # 七代：火斑喵、球球海狮
    810, 912,       # 八代/九代：敲音猴、呆火鳄（若不存在会自动跳过）
]

# 传说 / 幻之宝可梦：大多没有进化链，但野外探索时有 2% 的极小概率撞见，
# 也作为图鉴里的收集目标（可以按编号直接查）。
EXTRA_SPECIES = [
    144, 145, 146, 150, 151,          # 三圣鸟、超梦、梦幻
    243, 244, 245, 249, 250,          # 雷公/炎帝/水君、洛奇亚、凤王
    380, 381, 382, 383, 384, 385,     # 拉帝亚斯兄妹、丰缘三神、基拉祈
    491, 493,                         # 达克莱伊、阿尔宙斯
]

_cache: dict[str, dict] = {}


def get_json(url: str, retries: int = 3) -> dict:
    if url in _cache:
        return _cache[url]
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                _cache[url] = data
                return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"请求失败: {url} ({last})")


def species_id(url_or_name: str) -> int:
    tail = url_or_name.rstrip("/").split("/")[-1]
    try:
        return int(tail)
    except ValueError:
        return -1


def zh_name(names: list[dict]) -> str:
    # 注意：PokéAPI 返回的 language.name 是小写 kebab 形式，如 "zh-Hans"
    for lang_code in ("zh-hans", "zh-hant"):
        for item in names:
            if item.get("language", {}).get("name", "").lower() == lang_code:
                return item.get("name", "")
    return ""


def build_entry(sid: int) -> dict | None:
    try:
        sp = get_json(f"{API}/pokemon-species/{sid}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 跳过 {sid}: {exc}")
        return None
    names = sp.get("names", [])
    entry = {
        "id": sid,
        "en": sp.get("name", ""),
        "zh": zh_name(names),
        "color": sp.get("color", {}).get("name", ""),
        "habitat": (sp.get("habitat") or {}).get("name", ""),
        "is_legendary": sp.get("is_legendary", False),
        "is_baby": sp.get("is_baby", False),
        "capture_rate": sp.get("capture_rate", 0),
        "growth_rate": (sp.get("growth_rate") or {}).get("name", ""),
        "flavor": "",
        "types": [],
    }
    for lang_code in ("zh-hans", "zh-hant"):
        for fl in sp.get("flavor_text_entries", []):
            text = " ".join(fl.get("flavor_text", "").split())
            if fl.get("language", {}).get("name", "").lower() == lang_code and text:
                entry["flavor"] = text
                break
        if entry["flavor"]:
            break
    try:
        pk = get_json(f"{API}/pokemon/{sid}")
        entry["types"] = [t["type"]["name"] for t in pk.get("types", [])]
    except Exception:  # noqa: BLE001
        pass
    return entry


def walk_chain(node: dict, out: list[dict], parent: int | None = None) -> None:
    sid = species_id(node.get("species", {}).get("url", ""))
    if sid <= 0:
        return
    evo = []
    for nxt in node.get("evolves_to", []):
        target = species_id(nxt.get("species", {}).get("url", ""))
        details = []
        for d in nxt.get("evolution_details", []) or [{}]:
            details.append(
                {
                    "trigger": (d.get("trigger") or {}).get("name", "level-up"),
                    "min_level": d.get("min_level"),
                    "min_happiness": d.get("min_happiness"),
                    "item": (d.get("item") or {}).get("name"),
                    "time_of_day": d.get("time_of_day") or "",
                }
            )
        evo.append({"to": target, "conditions": details})
        walk_chain(nxt, out, sid)
    out.append({"id": sid, "parent": parent, "evolves_to": evo})


def fetch_line(base: int) -> list[dict] | None:
    try:
        sp = get_json(f"{API}/pokemon-species/{base}")
        chain_url = (sp.get("evolution_chain") or {}).get("url")
        if not chain_url:
            return None
        chain = get_json(chain_url)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 进化链 {base} 失败: {exc}")
        return None
    nodes: list[dict] = []
    walk_chain(chain.get("chain", {}), nodes, None)
    return nodes


def main() -> int:
    print("== PokePal 图鉴数据生成 ==")
    lines: list[list[dict]] = []
    targets = list(BASE_SPECIES) + [s for s in EXTRA_SPECIES if s not in BASE_SPECIES]
    print(f"拉取 {len(targets)} 条进化链 ...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(fetch_line, targets):
            if res:
                lines.append(res)

    ids: list[int] = []
    seen: set[int] = set()
    for nodes in lines:
        for n in nodes:
            if n["id"] not in seen:
                seen.add(n["id"])
                ids.append(n["id"])
    ids.sort()
    print(f"共 {len(ids)} 只宝可梦，拉取详情 ...")

    entries: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for entry in ex.map(build_entry, ids):
            if entry:
                entries[str(entry["id"])] = entry

    evo_map: dict[str, list] = {}
    parent_map: dict[str, int | None] = {}
    for nodes in lines:
        for n in nodes:
            key = str(n["id"])
            if key in entries:
                evo_map[key] = n["evolves_to"]
                parent_map[key] = n["parent"]

    roots = sorted(
        {
            str(n["id"])
            for nodes in lines
            for n in nodes
            if n["parent"] is None and str(n["id"]) in entries
        },
        key=lambda k: int(k),
    )

    payload = {
        "version": 1,
        "source": "pokeapi.co",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "roots": roots,
        "entries": entries,
        "evolution": evo_map,
        "parents": {k: v for k, v in parent_map.items()},
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    total_missing = sum(1 for e in entries.values() if not e["zh"])
    print(f"写入 {OUT}")
    print(f"  物种数: {len(entries)}  缺中文名: {total_missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
