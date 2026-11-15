"""Génère le logo de Sillon : un vinyle noir sur fond ambre.

Fond orange pour rester lisible sur une barre des tâches claire comme sombre ; les petites tailles
(≤ 32 px) sont dessinées à part, sans sillons fins qui deviendraient de la bouillie.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TOP = (255, 150, 92)
BOTTOM = (255, 104, 45)
DISC = (20, 18, 24)
GROOVE = (62, 56, 72)
LABEL = (255, 122, 61)
LABEL_2 = (255, 176, 92)
SHINE = (255, 255, 255, 70)


def draw(size: int) -> Image.Image:
    small = size <= 32
    s = 8 if size < 64 else 4  # suréchantillonnage pour l'anticrénelage
    W = size * s
    c = W / 2

    # fond : carré arrondi en dégradé ambre
    grad = Image.new("RGBA", (W, W))
    gd = ImageDraw.Draw(grad)
    for y in range(W):
        t = y / (W - 1)
        gd.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM, strict=True)) + (255,))
    mask = Image.new("L", (W, W), 0)
    margin = 0 if small else W * 0.02
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, W - 1 - margin, W - 1 - margin),
                                           radius=W * 0.23, fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img, "RGBA")

    # disque
    R = W * (0.40 if small else 0.38)
    d.ellipse((c - R, c - R, c + R, c + R), fill=DISC)
    if not small:
        for k in range(4):
            rr = R * (0.90 - k * 0.11)
            d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=GROOVE, width=max(1, int(W * 0.007)))
    # reflet
    rr = R * 0.80
    d.arc((c - rr, c - rr, c + rr, c + rr), start=200, end=250, fill=SHINE, width=int(W * (0.05 if small else 0.03)))

    # étiquette
    L = R * (0.46 if small else 0.40)
    d.ellipse((c - L, c - L, c + L, c + L), fill=LABEL)
    if not small:
        L2 = R * 0.27
        d.ellipse((c - L2, c - L2, c + L2, c + L2), fill=LABEL_2)
    h = R * (0.11 if small else 0.07)
    d.ellipse((c - h, c - h, c + h, c + h), fill=DISC)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    draw(1024).save(ASSETS / "sillon.png")
    draw(256).save(ASSETS / "sillon-256.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [draw(n) for n in sizes]
    frames[-1].save(ASSETS / "sillon.ico", sizes=[(n, n) for n in sizes], append_images=frames[:-1])
    print("ok", ASSETS)
