# -*- coding: utf-8 -*-
"""生成应用图标 assets/icon.ico：蓝底圆角 + 白色「舞」字 + 音符。"""
import os
from PIL import Image, ImageDraw, ImageFont

os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets"), exist_ok=True)

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角蓝底
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=48, fill="#2f80ed")

# 白色「舞」字
font_path = None
for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
          r"C:\Windows\Fonts\msyhl.ttc", "/System/Library/Fonts/PingFang.ttc",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
    if os.path.exists(p):
        font_path = p
        break
font = ImageFont.truetype(font_path, 170) if font_path else ImageFont.load_default()
bbox = d.textbbox((0, 0), "舞", font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((SIZE - w) / 2 - bbox[0], (SIZE - h) / 2 - bbox[1] - 18), "舞", font=font, fill="#ffffff")

# 底部小音符
def note(cx, cy, s, color):
    r = s * 0.42
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    d.rounded_rectangle([cx + r * 0.5, cy - s, cx + r * 1.15, cy + s * 0.6], radius=s * 0.08, fill=color)
    d.line([cx + r * 1.15, cy - s, cx + r * 1.15, cy + s * 0.6], fill=color, width=max(1, int(s * 0.12)))
    d.rounded_rectangle([cx + r * 0.5, cy + s * 0.1, cx + r * 1.15, cy + s * 0.6], radius=s * 0.08, fill=color)

note(SIZE * 0.30, SIZE * 0.80, SIZE * 0.16, "#ffffff")
note(SIZE * 0.62, SIZE * 0.80, SIZE * 0.16, "#ffffff")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icon.ico")
img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon saved:", out, os.path.getsize(out), "bytes")
