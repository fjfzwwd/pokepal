# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assets.sprites import SIZE_PRESETS, SpriteManager, HAVE_PIL  # noqa: E402

root = tk.Tk()
root.withdraw()
print("PIL:", HAVE_PIL, "| Tk:", root.tk.call("info", "patchlevel"))

mgr = SpriteManager(os.path.join(tempfile.gettempdir(), "pokepal_sprite_smoke"),
                    target_size=SIZE_PRESETS["中"], root=root)

for dex_id, en in ((25, "pikachu"), (912, "quaxly"), (6, "charizard")):
    t0 = time.time()
    info = mgr.ensure_files(dex_id, False, en)
    dt = time.time() - t0
    if not info:
        print(f"#{dex_id} FAIL download ({dt:.1f}s)")
        continue
    s = mgr.build(info)
    if not s:
        print(f"#{dex_id} FAIL build")
        continue
    print(f"#{dex_id} {s.source:12s} {len(s.front):3d}帧 {s.w}x{s.h} "
          f"delay={s.delays[:5]} 缓存={os.path.basename(info['files']['front'])} ({dt:.1f}s)")

ph = mgr.placeholder()
print("placeholder:", ph)
print("cache bytes:", mgr.cache_size())
