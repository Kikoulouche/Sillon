"""Génère le logo de Sillon (un vinyle stylisé, étiquette ambre) en PNG et ICO."""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ACCENT = (255, 122, 61)
ACCENT_2 = (255, 176, 92)
DISC = (24, 22, 30)
GROOVE = (52, 47, 62)
BG = (15, 14, 19)


def draw(size: int = 1024) -> Image.Image:
    s = 4  # suréchantillonnage pour l'anticrénelage
    W = size * s
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(W * 0.22)
    d.rounded_rectangle((0, 0, W - 1, W - 1), radius=r, fill=BG)

    c = W / 2
    R = W * 0.40
    d.ellipse((c - R, c - R, c + R, c + R), fill=DISC)
    # sillons
    for k in range(6):
        rr = R * (0.93 - k * 0.075)
        d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=GROOVE, width=max(1, int(W * 0.006)))
    # reflet ambre en quart de cercle
    rr = R * 0.97
    d.arc((c - rr, c - rr, c + rr, c + rr), start=-70, end=-20, fill=ACCENT, width=int(W * 0.022))
    # étiquette
    L = R * 0.38
    d.ellipse((c - L, c - L, c + L, c + L), fill=ACCENT)
    L2 = R * 0.26
    d.ellipse((c - L2, c - L2, c + L2, c + L2), fill=ACCENT_2)
    h = R * 0.06
    d.ellipse((c - h, c - h, c + h, c + h), fill=BG)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    big = draw(1024)
    big.save(ASSETS / "sillon.png")
    big.resize((256, 256), Image.LANCZOS).save(ASSETS / "sillon-256.png")
    big.save(ASSETS / "sillon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok", ASSETS)
