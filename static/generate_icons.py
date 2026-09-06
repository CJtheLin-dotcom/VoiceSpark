import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ICONS_DIR = Path(__file__).resolve().parent / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

def create_icon(size: int, filename: str):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Rounded rectangle with rich dark purple/indigo gradient
    corner_radius = int(size * 0.22)
    
    # Gradient background
    for y in range(size):
        ratio = y / size
        # From #4f46e5 (indigo) to #7c3aed (violet) to #9333ea (purple)
        r = int(79 + ratio * (147 - 79))
        g = int(70 + ratio * (51 - 70))
        b = int(229 + ratio * (234 - 229))
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    # Mask for rounded corners
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, size, size], radius=corner_radius, fill=255)
    img.putalpha(mask)

    # Re-draw on RGBA to add iconography
    draw = ImageDraw.Draw(img)

    # Draw a stylized glowing spark / audio wave in center
    cx, cy = size // 2, size // 2
    
    # Soundwave bars
    bar_width = max(4, int(size * 0.05))
    gap = max(4, int(size * 0.035))
    heights = [0.25, 0.45, 0.70, 0.45, 0.25]
    total_w = len(heights) * bar_width + (len(heights) - 1) * gap
    start_x = cx - total_w // 2

    for i, h in enumerate(heights):
        bx = start_x + i * (bar_width + gap)
        bh = int(size * h)
        by = cy - bh // 2
        # Draw rounded pill bar
        draw.rounded_rectangle(
            [bx, by, bx + bar_width, by + bh],
            radius=bar_width // 2,
            fill=(255, 255, 255, 240)
        )

    # Small gold spark ✨ at top right
    spark_x = int(cx + size * 0.25)
    spark_y = int(cy - size * 0.22)
    s_r = int(size * 0.06)
    draw.ellipse([spark_x - s_r, spark_y - s_r, spark_x + s_r, spark_y + s_r], fill=(251, 191, 36, 255))

    img.save(ICONS_DIR / filename, "PNG")
    print(f"Generated {filename} ({size}x{size})")

if __name__ == "__main__":
    create_icon(192, "icon-192.png")
    create_icon(512, "icon-512.png")
    create_icon(180, "apple-touch-icon.png")
