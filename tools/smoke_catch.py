# -*- coding: utf-8 -*-
"""捕捉 / BOX 仓库 子系统冒烟测试（纯逻辑，不开 GUI）。"""
import os
import random
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import items  # noqa: E402
from core.encounter import catch_rate, line_depth, roll_wild  # noqa: E402
from core.store import TEAM_LIMIT, Store  # noqa: E402

home = os.path.join(tempfile.gettempdir(), "pokepal_catch_smoke")
shutil.rmtree(home, ignore_errors=True)
store = Store(home=home, project_root=ROOT)
store.load()
dex = store.dex

print("== 道具 ==")
print("球类:", [(i.id, i.zh, items.ball_power(i.id)) for i in items.by_category("ball")])
print("玩具弹力球仍在:", items.get("pokeball").zh)

print("\n== 遇怪抽样（1000 次）==")
rng = random.Random(7)
counter = {}
rare = 0
for _ in range(1000):
    w = roll_wild(dex, store.met, rng=rng)
    if not w:
        continue
    counter[dex.name(w["species_id"])] = counter.get(dex.name(w["species_id"]), 0) + 1
    rare += 1 if w["rare"] else 0
top = sorted(counter.items(), key=lambda kv: -kv[1])[:8]
print("出现次数 Top8:", top)
print("稀有出现次数:", rare, "共涉及物种:", len(counter))

print("\n== 捕捉率 ==")
for sid in sorted(dex.all_ids())[:6]:
    entry = dex.get(sid)
    depth = line_depth(dex, sid)
    rate = catch_rate(entry, 8, depth, 18.0, items.ball_power("poke-ball"))
    rate2 = catch_rate(entry, 8, depth, 80.0, items.ball_power("ultra-ball"))
    print(f"  {dex.name(sid):<8} 阶段{depth} 低亲密精灵球 {rate*100:5.1f}%  "
          f"喂饱后高级球 {rate2*100:5.1f}%")

print("\n== 单次相遇流程（带投喂）==")
wins = 0
for seed in range(200):
    rng = random.Random(seed)
    w = roll_wild(dex, store.met, rng=rng)
    from core.encounter import Encounter

    enc = Encounter(w["species_id"], w["level"])
    for _ in range(3):
        enc.bait()
    for _ in range(8):
        if enc.over:
            break
        res = enc.throw(w["entry"], w["stage"], items.ball_power("great-ball"))
        if res["success"]:
            wins += 1
            break
print(f"投喂3次后用超级球：200 次里成功 {wins} 次（{wins/2:.0f}%）")

print("\n== BOX 仓库 ==")
for sid in sorted(dex.all_ids())[:8]:
    pet, boxed = store.adopt(sid, how="捕捉", level=5)
    dst = "BOX" if boxed else "队伍"
    print(f"  收服 {dex.name(sid):<8} -> {dst}（队伍 {len(store.team())}/{TEAM_LIMIT}）")
print("队伍:", [p.display_name() for p in store.team()])
print("仓库:", [p.display_name() for p in store.box()])
victim = store.team()[0]
print("寄存:", store.to_box(victim.uid))
print("取出:", store.from_box(victim.uid))
print("再寄存一位:", store.to_box(store.team()[-1].uid)[1])
full = store.box()[0]
if store.team_full():
    print("队伍已满时取出:", store.from_box(full.uid))
print("已收服记录:", len(store.caught), "| 已见过:", len(store.met))

store.save()
reload_store = Store(home=home, project_root=ROOT)
reload_store.load()
print("存档回读: 总计", len(reload_store.pets), "队伍", len(reload_store.team()),
      "仓库", len(reload_store.box()), "收服", len(reload_store.caught))
print("宝可梦是否在仓库中正确持久化:",
      sorted(p.in_box for p in reload_store.pets))
