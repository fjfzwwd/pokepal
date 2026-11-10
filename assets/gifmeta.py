# -*- coding: utf-8 -*-
"""零依赖 GIF 元数据解析。

标准库的 tkinter.PhotoImage 无法告诉我们 GIF 有多少帧、每帧停留多久，
这里直接用二进制解析获得这些信息，避免为了这点小事引入 Pillow。

仅支持我们真正需要的部分：
    - 逐帧延时（百分之一秒 -> 毫秒）
    - 帧数量
"""

from __future__ import annotations

from typing import List


def gif_frame_delays(data: bytes, default_ms: int = 100) -> List[int]:
    """返回 GIF 每一帧的延时（毫秒）。解析失败时返回空列表。"""
    if len(data) < 13 or data[:3] not in (b"GIF87a", b"GIF89a"):
        return []

    pos = 6
    width = int.from_bytes(data[pos:pos + 2], "little")
    height = int.from_bytes(data[pos + 2:pos + 4], "little")
    packed = data[pos + 4]
    pos += 7
    if packed & 0x80:  # 全局颜色表
        pos += 3 * (2 ** ((packed & 0x07) + 1))

    delays: List[int] = []
    pending = default_ms

    def read_sub_blocks(p: int) -> int:
        while p < len(data):
            size = data[p]
            if size == 0:
                return p + 1
            p += 1 + size
        return len(data)

    while pos < len(data):
        block = data[pos]
        if block == 0x21:  # 扩展块
            label = data[pos + 1]
            p = pos + 2
            if label == 0xF9:  # Graphic Control Extension
                size = data[p]
                payload = data[p + 1:p + 1 + size]
                p = read_sub_blocks(p)
                if len(payload) >= 3:
                    centis = int.from_bytes(payload[1:3], "little")
                    pending = centis * 10 if centis > 1 else default_ms
            else:
                p = read_sub_blocks(p)
            pos = p
        elif block == 0x2C:  # 图像描述符 == 一帧
            delays.append(pending)
            pending = default_ms
            packed = data[pos + 9]
            pos += 10
            if packed & 0x80:  # 局部颜色表
                pos += 3 * (2 ** ((packed & 0x07) + 1))
            pos += 1  # LZW 最小码长
            pos = read_sub_blocks(pos)
        elif block == 0x3B:  # 文件结束
            break
        else:
            break

    return delays


def gif_size(data: bytes) -> tuple[int, int]:
    """读取 GIF 的逻辑画布尺寸。"""
    if len(data) < 10 or data[:3] not in (b"GIF87a", b"GIF89a"):
        return (0, 0)
    return (
        int.from_bytes(data[6:8], "little"),
        int.from_bytes(data[8:10], "little"),
    )


if __name__ == "__main__":
    import sys
    import urllib.request

    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/"
        "pokemon/versions/generation-v/black-white/animated/25.gif"
    )
    raw = urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "PokePal/1.0"}), timeout=20
    ).read()
    ds = gif_frame_delays(raw)
    print("size:", gif_size(raw), "frames:", len(ds), "delays[:8]:", ds[:8])
