# -*- coding: utf-8 -*-
"""整机冒烟测试：跑一会儿真实 GUI，把检查结果写进文件后自动退出。

用法： python tools/smoke_run.py [seconds]
"""
import io
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

RUN_SECONDS = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SMOKE_SECONDS", "10"))
REPORT = os.path.join(ROOT, "tools", ".smoke_report.txt")
lines: list[str] = []
errors: list[str] = []


def log(text: str) -> None:
    lines.append(text)


def report():
    try:
        app = _app
        pw = app.pet_window
        log(f"pet={app.store.pet.display_name()} #{app.store.pet.species_id}")
        log(f"sprite={pw.sprite.source if pw.sprite else None} "
            f"frames={len(pw.sprite.front) if pw.sprite else 0} "
            f"size={pw.win_w}x{pw.win_h}")
        log(f"canvas_items={len(pw.canvas.find_all())} img={pw.img_item}")
        log("geometry=" + pw.geometry())
        log(f"panel={bool(app.panel and app.panel.winfo_exists())}")
        log(f"wallet={app.store.wallet} pets={len(app.store.pets)} "
            f"team={len(app.store.team())} box={len(app.store.box())}")
        log(f"encounter={bool(app.encounter_window and app.encounter_window.winfo_exists())} "
            f"caught={len(app.store.caught)} met={len(app.store.met)}")

        if app.panel and app.panel.winfo_exists():
            app.root.update_idletasks()
            log(f"panel_viewable={app.panel.winfo_viewable()} "
                f"panel_state={app.panel.state()} geom={app.panel.geometry()}")

        faces = set()
        for _ in range(60):
            pw.ai_until = 0.0
            pw._think()
            faces.add(pw.facing)
        log(f"facing={sorted(faces)}")
    except Exception:
        errors.append("report")
        lines.append(traceback.format_exc())


def finish():
    report()
    lines.append(f"errors={errors}")
    with io.open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    try:
        _app.root.destroy()
    except Exception:
        pass


try:
    from main import App

    def auto_catch():
        try:
            win = _app.encounter_window
            if not win or not win.winfo_exists():
                return
            before = len(_app.store.pets)
            _app.store.bag["master-ball"] = 1
            for _ in range(6):
                if win.enc.caught or win.enc.fled or win._ended:
                    break
                win._do_throw("master-ball", "大师球")
            lines.append(f"auto_catch pets {before} -> {len(_app.store.pets)} "
                         f"caught={win.enc.caught}")
        except Exception:
            lines.append(traceback.format_exc())
            errors.append("auto_catch")

    def explore():
        try:
            store = _app.store
            store.add_silkworm()
            # 塞两只伙伴进 BOX，让仓库页有内容
            for sid in store.dex.all_ids()[:14]:
                if len(store.pets) >= 3:
                    break
                store.adopt(sid, how="捕捉", level=7)
            extra = [p for p in store.pets if not p.in_box][1:]
            for pet in extra:
                store.to_box(pet.uid)
            store.bag["poke-ball"] = max(5, store.item_count("poke-ball"))
            store.last_explore = 0          # 跳过冷却，保证测试能触发相遇
            _app.explore()
            panel = _app.panel
            if panel:
                panel.refresh_all()
                for name in list(panel.TABS):
                    panel.select_tab(name)
                    panel._rebuild_tab(name)   # 显式重建，等价于切页签后的懒加载
                    panel.update()
                # 每个可滚动页签都该有内容；空的说明该页重建时抛异常了
                empty = [name for name, frame in panel.TABS.items()
                         if hasattr(frame, "inner") and not frame.inner.winfo_children()]
                lines.append(f"tabs empty={empty} dirty={sorted(panel._dirty)}")
                if empty:
                    errors.append("tab_empty")
        except Exception:
            lines.append(traceback.format_exc())
            errors.append("explore")

    def unlock():
        try:
            t0 = time.time()
            added, total = _app.unlock_all(confirm=False)
            cost = time.time() - t0
            levels = {p.level for p in _app.store.pets}
            species = {p.species_id for p in _app.store.pets}
            all_ids = set(int(x) for x in _app.store.dex.all_ids())
            missing = sorted(all_ids - species)
            lines.append(f"unlock added={added} total={total} caught={len(_app.store.caught)} "
                         f"team={len(_app.store.team())} box={len(_app.store.box())} "
                         f"levels={sorted(levels)} missing={len(missing)} cost={cost:.2f}s")
            # 注意：伙伴总数可能比图鉴条目多（同一物种抓到两只），按物种集合判断
            if missing or levels != {100} or len(_app.store.caught) < len(all_ids):
                errors.append("unlock")
            if len(_app.store.team()) > 6:
                errors.append("unlock_team_limit")
            panel = _app.panel
            if panel:
                panel.select_tab("图鉴")
                for _ in range(8):
                    _app.root.update()
                panel.select_tab("仓库")
                for _ in range(8):
                    _app.root.update()
        except Exception:
            lines.append(traceback.format_exc())
            errors.append("unlock")

    def dock_check():
        try:
            _app.open_dock()
            for _ in range(10):
                _app.root.update()
            dock = _app.dock
            if not dock or not dock.winfo_exists():
                errors.append("dock_open")
                lines.append("dock 没能打开")
                return
            lines.append(f"dock entries={len(dock.entries)} "
                         f"geom={dock.winfo_width()}x{dock.winfo_height()}")

            dock._invoke(0)          # 点「面板」
            for _ in range(12):
                _app.root.update()
            panel_ok = bool(_app.panel and _app.panel.winfo_exists())
            closed = _app.dock is None
            lines.append(f"dock->panel={panel_ok} dock_closed={closed}")
            if not panel_ok or not closed:
                errors.append("dock_action")

            _app.open_dock()         # 中键开关：再开一次然后 toggle 关掉
            for _ in range(6):
                _app.root.update()
            opened = bool(_app.dock and _app.dock.winfo_exists())
            _app.toggle_dock()
            for _ in range(4):
                _app.root.update()
            lines.append(f"dock reopen={opened} toggle_closed={_app.dock is None} "
                         f"dock={_app.dock!r}")
        except Exception:
            lines.append(traceback.format_exc())
            errors.append("dock")

    _app = App()
    _app.root.after(2500, lambda: _app.open_panel())
    _app.root.after(5000, explore)
    _app.root.after(7000, auto_catch)
    _app.root.after(9000, unlock)
    _app.root.after(10000, dock_check)
    _app.root.after(8000, lambda: _app.pet_window.say("冒烟测试：你好呀", secs=8))
    _app.root.after(int(RUN_SECONDS * 1000), finish)
    _app.root.mainloop()
    os._exit(0)
except Exception:
    errors.append("startup")
    lines.append(traceback.format_exc())
    with io.open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    sys.exit(1)
