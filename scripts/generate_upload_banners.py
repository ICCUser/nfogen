"""Genere les 4 bannieres de section du template d'upload nfogen
(voir nfogen/profiles/c411/templates/upload_description.j2) -- SCRIPT
DEV-ONLY, jamais execute au runtime nfogen. A relancer manuellement si la
charte graphique change ; le resultat (assets/banners/*.png) est commite
dans le repo et servi via raw.githubusercontent.com (voir
docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 640, 78
BG_COLOR = "#141d19"
ACCENT_COLOR = "#6bc9b3"
CREDIT_COLOR = "#4d5c53"
OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "banners"

BANNERS = [
    # Pas d'emoji : DejaVu Sans Bold (police utilisee, cf. _FONT_CANDIDATES)
    # ne porte pas de glyphes couleur -- un emoji s'affichait en tofu box
    # illisible plutot que l'icone attendue.
    ("informations", "INFORMATIONS"),
    ("synopsis", "SYNOPSIS"),
    ("details-techniques", "DÉTAILS TECHNIQUES"),
    ("telechargement", "TÉLÉCHARGEMENT"),
]

# Chemins de police testes dans l'ordre -- le premier qui existe est
# utilise. Evite un rendu illisible (ImageFont.load_default() degrade
# vers une police bitmap minuscule) si DejaVu Sans Bold (livree avec
# Pillow) n'est pas trouvee sur la machine d'execution.
_FONT_CANDIDATES = [
    "DejaVuSans-Bold.ttf",  # livree avec Pillow, resolue via son chemin interne
    "C:/Windows/Fonts/segoeuib.ttf",  # Windows
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    title_font = _font(30)
    credit_font = _font(13)
    for filename, label in BANNERS:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        # Lisere d'accent, coherent avec la maquette validee.
        draw.rectangle((0, 0, 6, HEIGHT), fill=ACCENT_COLOR)
        draw.text((30, 21), label, font=title_font, fill=ACCENT_COLOR)
        draw.text((WIDTH - 110, HEIGHT - 22), "nfogen.nfo", font=credit_font, fill=CREDIT_COLOR)
        path = OUT_DIR / f"{filename}.png"
        img.save(path, "PNG")
        print(f"Écrit : {path}")


if __name__ == "__main__":
    generate()
