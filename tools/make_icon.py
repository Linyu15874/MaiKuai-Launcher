#!/usr/bin/env python3
"""生成 Windows 可执行文件的图标（resources/app.ico / app.png）。

纯 PIL 绘制像素风「草方块」，不依赖任何外部素材。
用法：python3 tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "launcher" / "resources"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 512
BG_TOP = (74, 140, 247)      # 主色蓝
BG_BOTTOM = (40, 92, 196)
GRASS = "#5FBF3F"
GRASS_LIGHT = "#7ED256"
GRASS_DARK = "#46962D"
DIRT = "#8A5A32"
DIRT_LIGHT = "#9C6A3C"
DIRT_DARK = "#6F4526"

# 16x16 像素草方块（g=草, G=亮草, d=深草, s=土, S=亮土, D=深土, .=透明）
MAP = [
    "ggGGgGgGggGgGGgg",
    "GgGGgGgGGgGgGGgG",
    "ggGgGGgGgGggGgGG",
    "dGdgdGGdGdGdGGdG",
    "sSsSDsSsDSsSsSDs",
    "SDsSsDSsSsSDsSsD",
    "sDsSDsSsDsSsSDsS",
    "SsSDsDsSsSDsDsSD",
    "sSsSDsSsDsSDsSsD",
    "SDsSsDSsSsSDsSsD",
    "sDsSDsSsDsSsSDsS",
    "SsSDsDsSsSDsDsSD",
    "sSsSDsSsDsSDsSsD",
    "SDsSsDSsSsSDsSsD",
    "sDsSDsSsDsSsSDsS",
    "DDDDDDDDDDDDDDDD",
]

COLOR = {
    "g": GRASS, "G": GRASS_LIGHT, "d": GRASS_DARK,
    "s": DIRT, "S": DIRT_LIGHT, "D": DIRT_DARK,
}


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * 4 - 1, size * 4 - 1], radius=radius * 4, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        img.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img.resize((size, size))


def draw_block(size: int) -> Image.Image:
    """按 16x16 像素图绘制方块，返回透明底图。"""
    px = size / 16.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y, row in enumerate(MAP):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            x0, y0 = int(x * px), int(y * px)
            x1, y1 = int((x + 1) * px), int((y + 1) * px)
            d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=COLOR[ch])
    return img


def build(size: int = SIZE) -> Image.Image:
    bg = gradient(size, BG_TOP, BG_BOTTOM).convert("RGBA")
    mask = rounded_mask(size, int(size * 0.22))
    bg.putalpha(mask)

    block_size = int(size * 0.66)
    block = draw_block(block_size)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    off = (size - block_size) // 2
    canvas.paste(block, (off, off), block)
    out = Image.alpha_composite(bg, canvas)
    return out


def main() -> int:
    img = build()
    png = OUT_DIR / "app.png"
    img.save(png)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico = OUT_DIR / "app.ico"
    img.save(ico, sizes=sizes)
    print("icon:", png, png.stat().st_size)
    print("icon:", ico, ico.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
