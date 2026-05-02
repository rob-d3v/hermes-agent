"""
Generate logo.png and icon.ico for avatar_voice.
Run: python generate_assets.py
Requires: pip install Pillow
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
ASSETS.mkdir(exist_ok=True)

# Catppuccin Mocha palette
BASE    = (30, 30, 46)
SURFACE = (24, 24, 37)
BLUE    = (137, 180, 250)
MAUVE   = (203, 166, 247)
TEAL    = (148, 226, 213)
GREEN   = (166, 227, 161)
TEXT    = (205, 214, 244)


def draw_logo(size=512):
    """Create a circular avatar_voice logo."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    r = size // 2 - 4

    # Outer glow ring (teal)
    for i in range(8):
        offset = i * 2
        alpha = int(255 * (1 - i / 8) * 0.3)
        draw.ellipse(
            [cx - r - offset, cy - r - offset, cx + r + offset, cy + r + offset],
            outline=(*TEAL, alpha), width=2
        )

    # Main circle background
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BASE)

    # Inner ring (blue gradient effect)
    inner_r = int(r * 0.88)
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        outline=BLUE, width=3
    )

    # Sound wave arcs (represents voice)
    wave_center_x = cx - 20
    wave_center_y = cy
    for i, radius in enumerate([60, 95, 130]):
        scaled_r = int(radius * size / 512)
        alpha = int(255 * (1 - i * 0.25))
        color = (*MAUVE[:2], MAUVE[2], alpha) if i % 2 == 0 else (*TEAL[:2], TEAL[2], alpha)
        bbox = [
            wave_center_x - scaled_r, wave_center_y - scaled_r,
            wave_center_x + scaled_r, wave_center_y + scaled_r
        ]
        draw.arc(bbox, start=-40, end=40, fill=color, width=max(4, size // 100))

    # Central dot (microphone indicator)
    dot_r = int(size * 0.06)
    draw.ellipse(
        [cx - dot_r - 20, cy - dot_r, cx + dot_r - 20, cy + dot_r],
        fill=GREEN
    )

    # "AV" text
    try:
        font = ImageFont.truetype("consola.ttf", size // 5)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", size // 5)
        except OSError:
            font = ImageFont.load_default()

    text = "AV"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw // 2 + 10
    ty = cy - th // 2 + int(size * 0.18)
    draw.text((tx, ty), text, fill=TEXT, font=font)

    return img


def create_icon(logo: Image.Image):
    """Create multi-size .ico from logo."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icons = []
    for s in sizes:
        resized = logo.resize((s, s), Image.LANCZOS)
        icons.append(resized)
    return icons


def main():
    print("Generating logo...")
    logo = draw_logo(512)
    logo.save(ASSETS / "logo.png")
    print(f"  -> {ASSETS / 'logo.png'}")

    # Smaller version for the app header
    logo_small = logo.resize((64, 64), Image.LANCZOS)
    logo_small.save(ASSETS / "logo_64.png")
    print(f"  -> {ASSETS / 'logo_64.png'}")

    print("Generating icon...")
    icons = create_icon(logo)
    icons[0].save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in [16, 24, 32, 48, 64, 128, 256]],
        append_images=icons[1:]
    )
    print(f"  -> {ASSETS / 'icon.ico'}")

    print("Done!")


if __name__ == "__main__":
    main()
