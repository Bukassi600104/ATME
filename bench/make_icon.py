"""Generate the app icon set from the ATME mark (paper disc, ink ring, marker-orange stroke)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("app/src-tauri/icons")
PAPER = (250, 249, 245, 255)
INK = (25, 25, 23, 255)
ACCENT = (232, 89, 12, 255)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), PAPER)
    d = ImageDraw.Draw(img)
    m = max(2, size // 16)                     # margin
    lw = max(2, size // 10)                    # ring width
    d.ellipse([m, m, size - m, size - m], outline=INK, width=lw)
    # accent arc: lower-right quarter, drawn as thicker stroke on same center
    m2 = m + lw // 2
    d.arc([m2, m2, size - m2, size - m2], start=20, end=110,
          fill=ACCENT, width=max(2, size // 8))
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = make(256)
    base.save(OUT / "icon.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256)]
    base.save(OUT / "icon.ico", format="ICO", sizes=sizes)
    print("wrote", OUT / "icon.png", "and", OUT / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
