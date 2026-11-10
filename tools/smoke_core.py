# -*- coding: utf-8 -*-
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import items  # noqa: E402
from core.store import Store  # noqa: E402

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
home = os.path.join(tempfile.gettempdir(), "pokepal_core_smoke")
shutil.rmtree(home, ignore_errors=True)

store = Store(home=home, project_root=root)
store.load()
pet = store.pet
print("初始:", [p.display_name() for p in store.pets], "钱包", store.wallet, "背包", store.bag)
print("图鉴条目:", len(store.dex.entries), "| 皮卡丘:", store.dex.display(25))

# 离线 4 小时结算
pet.last_seen = time.time() - 4 * 3600
evs = pet.tick()
print("离线4小时后:", {k: round(v, 1) for k, v in pet.stats.items()}, "状态:", pet.status_key(), "事件:", evs)

feeding = items.get("oran")
print(pet.feed(feeding).message)
print("训练:", pet.train().message, "| 等级", pet.level, pet.exp, "/", pet.exp_max)
pet.sleep_toggle()
print("睡觉:", pet.activity, pet.sleep_toggle().message)
pet.last_seen = time.time() - 8 * 3600
print("睡8小时:", {k: round(v, 1) for k, v in pet.stats.items()}, pet.tick())

# 进化条件检查
store.adopt(1)
bulba = store.pet
bulba.level = 16
print("妙蛙种子可进化:", store.dex.evolution_options(1, 16, bulba.bond, lambda i: False))
print("伊布:", store.dex.evolution_options(133, 30, 80, lambda i: i == "water-stone"))
ops = [o for o in store.dex.evolution_options(133, 30, 80, lambda i: i == "water-stone") if o["ready"]]
bulba.species_id = 133
bulba.apply_evolution(134, "水之石")
print("进化结果:", bulba.species_id, store.dex.name(bulba.species_id), bulba.lineage)

print("打工:", store.pet.start_work(5).message)
print("零花钱:", store.buy("poffin", 1), store.wallet, store.bag.get("poffin"))
store.save()
print("存档:", os.path.getsize(store.save_path), "bytes")
