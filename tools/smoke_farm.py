# -*- coding: utf-8 -*-
"""蚕室子系统冒烟测试（纯逻辑，不开 GUI）。"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.store import Store  # noqa: E402

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
home = os.path.join(tempfile.gettempdir(), "pokepal_farm_smoke")
shutil.rmtree(home, ignore_errors=True)

store = Store(home=home, project_root=root)
store.load()

ok, msg = store.buy("mulberry", 5)
print("买桑叶:", ok, msg, "| 持有:", store.item_count("mulberry"))

worm = store.add_silkworm()
print("新蚕:", worm.emoji, worm.stage_name, worm.status_zh())

# 推进 30 小时：蚕会经历多个阶段，中途不照料会饿
now = time.time()
stage_log = []
for step in range(30):
    now += 3600
    for ev in worm.tick(now):
        stage_log.append((step, ev.get("type"), ev.get("name", "")))
    if step % 8 == 0:
        print(f"  {step:2d}h 后: {worm.emoji}{worm.stage_name} "
              f"成长{worm.progress:.0f}% 饥饿{worm.hunger:.0f} 脏{worm.dirty:.0f} "
              f"{worm.status_zh()}")

print("过程中的事件:", stage_log[:8])
print("最终:", worm.stage_name, worm.status_zh(), "可收丝:", worm.silk_ready)
print("投喂:", worm.feed(), "-> 饥饿", round(worm.hunger, 1))
print("清扫:", worm.clean(), "-> 脏污", round(worm.dirty, 1))

# 让蚕健康走完到结茧
w2 = store.add_silkworm()
now = time.time()
for step in range(60):
    now += 3600
    w2.tick(now)
    if int(w2.hunger) > 50:
        w2.feed()
    if int(w2.dirty) > 50:
        w2.clean()
print("持续照料下:", w2.stage_name, "成长", round(w2.progress, 1),
      "可收丝:", w2.silk_ready, "存活:", w2.alive)
got = w2.harvest()
print("采收蚕丝:", got)

store.save()
store2 = Store(home=home, project_root=root)
store2.load()
print("存档回读:", len(store2.worms), "只蚕，阶段:",
      [(w.stage_name, round(w.progress, 1)) for w in store2.worms])
