# -*- coding: utf-8 -*-
"""用缓存里的皮卡丘素材生成 assets/app.ico，作为快捷方式图标。

用法：
    python tools/make_icon.py
素材不存在时会自动从 PokéAPI 下载一张。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "assets", "app.ico")
CACHE = os.path.join(os.path.expanduser("~"), ".pokepal", "sprite_cache")
SOURCE_IDS = ("0025_front_n_genv.gif", "0025_front_n.png", "0025_front.gif")


def find_source() -> str | None:
    for name in SOURCE_IDS:
        path = os.path.join(CACHE, name)
        if os.path.exists(path):
            return path
    return None


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：python -m pip install Pillow")
        return 1

    src = find_source()
    if not src:
        print("本地没有 #25 素材，尝试下载 ...")
        try:
            import urllib.request

            url = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/25.png"
            os.makedirs(CACHE, exist_ok=True)
            src = os.path.join(CACHE, "0025_front_n.png")
            req = urllib.request.Request(url, headers={"User-Agent": "PokePal/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(src, "wb") as f:
                f.write(resp.read())
        except Exception as exc:  # noqa: BLE001
            print(f"下载失败: {exc}")
            return 1

    im = Image.open(src)
    try:
        im.seek(0)
    except Exception:  # noqa: BLE001
        pass
    frame = im.convert("RGBA")

    side = max(frame.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(frame, ((side - frame.width) // 2, (side - frame.height) // 2), frame)
    canvas = canvas.resize((256, 256), Image.LANCZOS)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    canvas.save(OUT, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                                          (32, 32), (16, 16)])
    print(f"图标已写入: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
