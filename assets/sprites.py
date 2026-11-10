# -*- coding: utf-8 -*-
"""精灵图管理：多镜像下载 -> 本地缓存 -> 逐帧拆解 -> 缩放。

设计要点
--------
1. 运行环境零第三方依赖也能跑：默认用标准库 tkinter.PhotoImage 逐帧读取 GIF；
   若检测到 Pillow 则用它做任意比例缩放（像素风用最近邻，避免糊）。
2. 三级素材回退：第五世代动画 GIF -> Showdown 动画 GIF -> 官方静态 PNG，
   任何一个下载成功就能显示，网络不稳时也能用。
3. 所有 PhotoImage 的创建都放在主线程进行（tkinter 不允许跨线程操作）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence

from assets.gifmeta import gif_frame_delays, gif_size

try:  # Pillow 是可选的：有它画质和缩放比例更好
    from PIL import Image, ImageSequence, ImageDraw, ImageTk

    HAVE_PIL = True
except Exception:  # noqa: BLE001
    HAVE_PIL = False

UA = {"User-Agent": "PokePal-DesktopPet/1.0 (+learning project)"}

ROOT_BASES = [
    os.environ.get("POKEPAL_SPRITE_MIRROR", "").strip(),
    "https://raw.githubusercontent.com/PokeAPI/sprites/master",
    "https://cdn.jsdelivr.net/gh/PokeAPI/sprites@master",
    "https://fastly.jsdelivr.net/gh/PokeAPI/sprites@master",
]
ROOT_BASES = [b for b in ROOT_BASES if b]
SHOWDOWN_BASE = "https://play.pokemonshowdown.com/sprites"

SIZE_PRESETS = {"小": 76, "中": 112, "大": 160, "特大": 220}


# --------------------------------------------------------------------------
# 素材地址构造
# --------------------------------------------------------------------------
def _poki_urls(dex_id: int, variant: str, shiny: bool) -> List[str]:
    """按优先级给出候选地址（variant: front / back）。"""
    back = "back/" if variant == "back" else ""
    shiny_dir = "shiny/" if shiny else ""
    return [
        f"{base}/sprites/pokemon/versions/generation-v/black-white/animated/"
        f"{back}{shiny_dir}{dex_id}.gif"
        for base in ROOT_BASES
    ]


def _png_urls(dex_id: int, variant: str, shiny: bool) -> List[str]:
    back = "back/" if variant == "back" else ""
    shiny_dir = "shiny/" if shiny else ""
    return [
        f"{base}/sprites/pokemon/{back}{shiny_dir}{dex_id}.png"
        for base in ROOT_BASES
    ]


def _showdown_urls(dex_id: int, variant: str, shiny: bool, en_name: str) -> List[str]:
    if not en_name:
        return []
    folder = "ani-back" if variant == "back" else "ani"
    if shiny:
        folder = "ani-shiny"
    return [f"{SHOWDOWN_BASE}/{folder}/{en_name}.gif"]


class _DaemonWorkers:
    """超轻量的守护线程池：专门跑下载这类 IO，退出时不会拖住解释器。"""

    def __init__(self, max_workers: int = 4):
        self._gate = threading.Semaphore(max_workers)

    def submit(self, fn: Callable[[], None]) -> None:
        def runner() -> None:
            with self._gate:
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    print(f"[后台任务异常] {exc}")

        threading.Thread(target=runner, daemon=True).start()


class SpriteSet:
    """一组已经可以直接扔进 canvas 的图像。"""

    def __init__(self, front: Sequence, back: Sequence, delays: Sequence[int],
                 w: int, h: int, source: str):
        self.front: List = list(front)
        self.back: List = list(back)
        self.delays: List[int] = list(delays) or [100]
        self.w = w
        self.h = h
        self.source = source

    def frames(self, facing: str) -> List:
        return self.back if (facing == "back" and self.back) else self.front

    @property
    def animated(self) -> bool:
        return len(self.front) > 1


class SpriteManager:
    def __init__(self, cache_dir: str, target_size: int = 112, root=None):
        self.cache_dir = cache_dir
        self.target_size = target_size
        self.root = root
        os.makedirs(cache_dir, exist_ok=True)
        # 用守护线程跑下载：ThreadPoolExecutor 的线程是非守护的，会让 GUI 退出后
        # 进程仍然吊在这儿不退出。
        self._pool = _DaemonWorkers(max_workers=4)
        self._meta_path = os.path.join(cache_dir, "manifest.json")
        self._manifest = self._load_manifest()

    # ---------------------------------------------------------------- manifest
    def _load_manifest(self) -> dict:
        if os.path.exists(self._meta_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _save_manifest(self) -> None:
        try:
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(self._manifest, f, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- download
    def _cache_file(self, dex_id: int, variant: str, shiny: bool, kind: str) -> str:
        ext = ".gif" if kind in ("genv", "sd") else ".png"
        tag = "back" if variant == "back" else "front"
        return os.path.join(
            self.cache_dir, f"{dex_id:04d}_{tag}_{'s' if shiny else 'n'}_{kind}{ext}"
        )

    def _entry_key(self, dex_id: int, shiny: bool) -> str:
        return f"{dex_id}_{'s' if shiny else 'n'}"

    def cached_paths(self, dex_id: int, shiny: bool = False) -> Optional[Dict[str, str]]:
        """若本地已有缓存（且文件完好）直接返回，不再联网。"""
        key = self._entry_key(dex_id, shiny)
        info = self._manifest.get(key)
        if not info:
            return None
        files = {k: v for k, v in info.get("files", {}).items() if os.path.exists(v)}
        if "front" not in files:
            return None
        return {"files": files, "source": info.get("source", "unknown")}

    @staticmethod
    def _try_download(urls: Sequence[str], dest: str, timeout: int = 20) -> bool:
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        continue
                    data = resp.read()
                if len(data) < 128:  # 空/占位文件
                    continue
                tmp = dest + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def ensure_files(self, dex_id: int, shiny: bool = False, en_name: str = "") -> Optional[Dict]:
        """联网并确保 front/back 素材落到本地（阻塞，请在线程里调用）。"""
        cached = self.cached_paths(dex_id, shiny)
        if cached:
            return cached

        files: Dict[str, str] = {}
        source = "static"
        for variant in ("front", "back"):
            dest = self._cache_file(dex_id, variant, shiny, "genv")
            if os.path.exists(dest) or self._try_download(_poki_urls(dex_id, variant, shiny), dest):
                files[variant] = dest
                source = "genV动画"
                continue
            dest = self._cache_file(dex_id, variant, shiny, "sd")
            if os.path.exists(dest) or self._try_download(_showdown_urls(dex_id, variant, shiny, en_name), dest):
                files[variant] = dest
                source = "Showdown动画"
                continue
            dest = self._cache_file(dex_id, variant, shiny, "png")
            if os.path.exists(dest) or self._try_download(_png_urls(dex_id, variant, shiny), dest):
                files[variant] = dest
                source = "官方静态图"

        if "front" not in files:
            return None

        if "back" not in files:  # 没有背面图就用正面图顶替
            files["back"] = files["front"]

        info = {"files": files, "source": source, "at": time.time()}
        self._manifest[self._entry_key(dex_id, shiny)] = info
        self._save_manifest()
        return info

    # ---------------------------------------------------------------- build
    def _scale_params(self, w: int, h: int) -> float:
        if h <= 0:
            return 1.0
        return max(0.5, min(6.0, self.target_size / h))

    def _load_frames_pil(self, path: str, scale: float):
        frames, delays = [], []
        im = Image.open(path)
        for frame in ImageSequence.Iterator(im):
            rgba = frame.convert("RGBA")
            if abs(scale - 1.0) > 0.01:
                rgba = rgba.resize(
                    (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                    Image.NEAREST,
                )
            frames.append(ImageTk.PhotoImage(rgba))
            delays.append(int(frame.info.get("duration", 100)))
        size = frames[0].width(), frames[0].height()
        return frames, delays, size

    def _load_frames_tk(self, path: str, scale: float):
        """无 Pillow 时的降级方案：整数倍 zoom/subsample。"""
        import tkinter as tk

        zoom = max(1, int(round(scale)))
        frames, delays = [], []
        with open(path, "rb") as f:
            raw = f.read()
        delays = gif_frame_delays(raw) if path.endswith(".gif") else [100]
        idx = 0
        while True:
            try:
                if path.endswith(".gif"):
                    img = tk.PhotoImage(master=self.root, file=path, format=f"gif -index {idx}")
                else:
                    img = tk.PhotoImage(master=self.root, file=path)
                    idx = 10 ** 9  # PNG 只有一帧，读完就退出
            except Exception:  # noqa: BLE001
                break
            if zoom != 1:
                img = img.zoom(zoom, zoom)
            frames.append(img)
            idx += 1
            if idx > 400:
                break
        if not frames:
            raise RuntimeError("无法读取素材")
        return frames, delays, (frames[0].width(), frames[0].height())

    def _load_frames(self, path: str, scale: float):
        if HAVE_PIL:
            return self._load_frames_pil(path, scale)
        return self._load_frames_tk(path, scale)

    def build(self, info: Dict) -> Optional[SpriteSet]:
        """把本地文件变成 SpriteSet。必须在主线程调用。"""
        files = info.get("files", {})
        front_path = files.get("front")
        if not front_path or not os.path.exists(front_path):
            return None

        base_w, base_h = self._probe_size(front_path)
        scale = self._scale_params(base_w, base_h)

        try:
            fronts, delays, (w, h) = self._load_frames(front_path, scale)
        except Exception:  # noqa: BLE001
            return None

        backs = fronts
        back_path = files.get("back")
        if back_path and back_path != front_path and os.path.exists(back_path):
            try:
                back_frames, back_delays, (bw, bh) = self._load_frames(back_path, scale)
                if back_frames:
                    backs = back_frames
            except Exception:  # noqa: BLE001
                pass

        while len(delays) < len(fronts):
            delays.append(100)
        # Showdown 的动画帧间隔可能低到 30ms（太快），这里统一夹到一个舒服的区间
        delays = [max(55, min(220, int(d))) for d in delays]
        return SpriteSet(fronts, backs, delays[: len(fronts)], w, h, info.get("source", ""))

    def _probe_size(self, path: str) -> tuple[int, int]:
        try:
            if HAVE_PIL:
                with Image.open(path) as im:
                    return im.size
            with open(path, "rb") as f:
                head = f.read(64)
            if head[:3] == b"GIF":
                return gif_size(head + b"\x00" * 10) if len(head) >= 10 else (0, 0)
        except Exception:  # noqa: BLE001
            pass
        return (0, 0)

    # ---------------------------------------------------------------- async
    def load_async(self, dex_id: int, shiny: bool, en_name: str,
                   on_ready: Callable[[Optional[SpriteSet]], None]) -> None:
        """后台下载 -> 主线程构建 -> 回调。下载失败时回调 None。"""

        def run() -> None:
            info = None
            try:
                info = self.ensure_files(dex_id, shiny=shiny, en_name=en_name)
            except Exception as exc:  # noqa: BLE001
                print(f"[素材下载失败] {exc}")

            def finish() -> None:
                sprite = None
                if info:
                    try:
                        sprite = self.build(info)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[素材构建失败] {exc}")
                try:
                    on_ready(sprite)
                except Exception as exc:  # noqa: BLE001
                    print(f"[素材回调异常] {exc}")

            if self.root is not None:
                self.root.after(0, finish)
            else:
                finish()

        self._pool.submit(run)

    def _safe_call(self, fn: Callable, arg) -> None:
        if self.root is None:
            fn(arg)
            return
        try:
            self.root.after(0, lambda: fn(arg))
        except Exception:  # noqa: BLE001
            fn(arg)

    def _safe_call(self, fn: Callable, arg) -> None:
        if self.root is None:
            fn(arg)
            return
        try:
            self.root.after(0, lambda: fn(arg))
        except Exception:  # noqa: BLE001
            fn(arg)

    # ---------------------------------------------------------------- misc
    def placeholder(self, text: str = "?"):
        """网络完全不可用时的占位形象：一颗手绘像素精灵球。"""
        size = self.target_size
        if not HAVE_PIL:
            return None
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        u = max(1, size // 24)
        cx, cy, r = size // 2, size // 2, size // 2 - u
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(232, 60, 60, 255),
                  outline=(30, 30, 30, 255), width=max(1, u))
        d.rectangle([cx - r, cy - max(u, 1), cx + r, cy + max(u, 1)], fill=(40, 40, 40, 255))
        d.ellipse([cx - r // 2 - u, cy - r // 2 - u, cx + r // 2 + u, cy + r // 2 + u],
                  fill=(245, 245, 245, 255), outline=(30, 30, 30, 255), width=max(1, u))
        d.ellipse([cx - max(u, 2), cy - max(u, 2), cx + max(u, 2), cy + max(u, 2)],
                  fill=(240, 240, 240, 255), outline=(30, 30, 30, 255), width=1)
        del text
        return ImageTk.PhotoImage(img)

    def load_thumb_async(self, dex_id: int, shiny: bool, en_name: str,
                         cb: Callable, size: int = 54) -> None:
        """给图鉴用的小缩略图（只要第一帧，失败回调 None）。"""

        def job():
            info = self.ensure_files(dex_id, shiny=shiny, en_name=en_name)
            if not info:
                return None
            path = info["files"].get("front")
            if not path or not os.path.exists(path):
                return None
            try:
                if HAVE_PIL:
                    with Image.open(path) as im:
                        frame = im.convert("RGBA")
                        frame.thumbnail((size, size), Image.NEAREST)
                        return ImageTk.PhotoImage(frame)
                import tkinter as tk

                if path.endswith(".gif"):
                    img = tk.PhotoImage(master=self.root, file=path, format="gif -index 0")
                else:
                    img = tk.PhotoImage(master=self.root, file=path)
                factor = max(1, int(round(img.height() / size)))
                return img.subsample(factor, factor)
            except Exception:  # noqa: BLE001
                return None

        def run() -> None:
            result = None
            try:
                result = job()
            except Exception:  # noqa: BLE001
                result = None
            self._safe_call(cb, result)

        self._pool.submit(run)

    # ---------------------------------------------------------------- cache
    def cache_size(self) -> int:
        total = 0
        for name in os.listdir(self.cache_dir):
            try:
                total += os.path.getsize(os.path.join(self.cache_dir, name))
            except OSError:
                pass
        return total

    def clear_cache(self) -> None:
        import shutil

        for name in os.listdir(self.cache_dir):
            p = os.path.join(self.cache_dir, name)
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
        self._manifest = {}
        self._save_manifest()
