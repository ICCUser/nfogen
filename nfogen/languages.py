"""Mapping code langue MediaInfo -> (nom affiche FR, code drapeau ISO
3166-1 alpha-2) -- utilise par upload_prep.py pour construire le tableau
BBCode audio/sous-titres (voir upload_description.j2). Couverture
volontairement restreinte aux langues courantes d'upload -- une langue
non reconnue est affichee telle quelle, sans drapeau (jamais une
supposition)."""
from __future__ import annotations

from typing import Optional

LANGUAGE_INFO: dict[str, tuple[str, str]] = {
    "fr": ("Français", "fr"), "fre": ("Français", "fr"), "fra": ("Français", "fr"),
    "french": ("Français", "fr"),
    "en": ("Anglais", "gb"), "eng": ("Anglais", "gb"), "english": ("Anglais", "gb"),
    "ja": ("Japonais", "jp"), "jpn": ("Japonais", "jp"), "japanese": ("Japonais", "jp"),
    "es": ("Espagnol", "es"), "spa": ("Espagnol", "es"), "spanish": ("Espagnol", "es"),
    "de": ("Allemand", "de"), "ger": ("Allemand", "de"), "deu": ("Allemand", "de"),
    "german": ("Allemand", "de"),
    "it": ("Italien", "it"), "ita": ("Italien", "it"), "italian": ("Italien", "it"),
    "pt": ("Portugais", "pt"), "por": ("Portugais", "pt"), "portuguese": ("Portugais", "pt"),
    "nl": ("Néerlandais", "nl"), "dut": ("Néerlandais", "nl"), "nld": ("Néerlandais", "nl"),
    "ru": ("Russe", "ru"), "rus": ("Russe", "ru"), "russian": ("Russe", "ru"),
    "ko": ("Coréen", "kr"), "kor": ("Coréen", "kr"), "korean": ("Coréen", "kr"),
    "zh": ("Chinois", "cn"), "chi": ("Chinois", "cn"), "zho": ("Chinois", "cn"),
}


def resolve_language(code: Optional[str]) -> tuple[str, Optional[str]]:
    """`(nom affiche, code drapeau)` -- code brut et `None` si la langue
    n'est pas reconnue (jamais de plantage, jamais de drapeau invente)."""
    if not code:
        return code or "", None
    info = LANGUAGE_INFO.get(code.strip().lower())
    return info if info else (code, None)


def flagcdn_url(flag_code: str) -> str:
    """URL du drapeau (service public flagcdn.com, meme taille/service que
    l'exemple de reference C411)."""
    return f"https://flagcdn.com/20x15/{flag_code}.png"
