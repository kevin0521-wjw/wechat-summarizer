# -*- coding: utf-8 -*-
"""
从 icon.svg 的几何设计派生整套应用图标（PNG + maskable + ICO）
================================================================
设计真源：web/static/icon.svg（绿色圆角底 + 白色气泡 + 绿色闪电）
这里用 Pillow 按同一套坐标 4 倍超采样绘制，再 LANCZOS 缩小，
保证 16px 小尺寸下圆角不糊。

产物：
  web/static/icon-192.png / icon-512.png      普通（圆角外沿透明）
  web/static/icon-512-maskable.png            maskable（底色满幅，美术 0.72 居中）
  desktop/icon.ico                            多尺寸（16~256），Electron 打包用

用法：python tools/make-icons.py（需 Pillow）
"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "web", "static")
GREEN = (7, 193, 96, 255)
WHITE = (255, 255, 255, 255)

# 与 icon.svg 一致的设计坐标（512 基准）
BUBBLE = (152, 136, 358, 302)          # 气泡主体
BUBBLE_TAIL = [(224, 302), (162, 362), (162, 302)]
LIGHTNING = [(278, 170), (224, 252), (270, 252), (244, 300), (312, 204), (262, 204)]
CORNER = 112                           # 背景圆角半径（512 基准）


def _draw_art(d, off, size):
    """在 [off,off,off+size] 方块内画气泡 + 闪电"""
    def X(v):
        return off + int(size * v / 512)

    def Y(v):
        return off + int(size * v / 512)

    r = int(size * 30 / 512)
    d.rounded_rectangle([X(BUBBLE[0]), Y(BUBBLE[1]), X(BUBBLE[2]), Y(BUBBLE[3])],
                        radius=r, fill=WHITE)
    d.polygon([(X(p[0]), Y(p[1])) for p in BUBBLE_TAIL], fill=WHITE)
    d.polygon([(X(p[0]), Y(p[1])) for p in LIGHTNING], fill=GREEN)


def render(size, maskable=False):
    S = size * 4                      # 4 倍超采样
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if maskable:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=0, fill=GREEN)  # 底色满幅
        art = int(S * 0.72)
        _draw_art(d, (S - art) // 2, art)
    else:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * CORNER / 512), fill=GREEN)
        _draw_art(d, 0, S)

    return img.resize((size, size), Image.LANCZOS)


def main():
    for s in (192, 512):
        render(s).save(os.path.join(STATIC, f"icon-{s}.png"))
    render(512, maskable=True).save(os.path.join(STATIC, "icon-512-maskable.png"))

    # ICO：16~256 七档
    ico_path = os.path.join(ROOT, "desktop", "icon.ico")
    render(256).save(ico_path, format="ICO",
                     sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("图标已生成：")
    for f in ("icon-192.png", "icon-512.png", "icon-512-maskable.png"):
        print("  ", os.path.join("web/static", f))
    print("  ", "desktop/icon.ico")


if __name__ == "__main__":
    main()
