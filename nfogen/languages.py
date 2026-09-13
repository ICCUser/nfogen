"""Mapping code langue MediaInfo -> (nom affiche FR, code drapeau ISO
3166-1 alpha-2) -- utilise par upload_prep.py pour construire le tableau
BBCode audio/sous-titres (voir upload_description.j2). Couverture
volontairement restreinte aux langues courantes d'upload -- une langue
non reconnue est affichee telle quelle, sans drapeau (jamais une
supposition)."""
from __future__ import annotations

import re
from typing import Optional

# Cles LONGUES uniquement (nom anglais complet, jamais un code 2-3
# lettres) pour la recherche par mot entier dans le `title` libre d'une
# piste (voir resolve_language ci-dessous) -- un code court comme "en"
# donnerait de faux positifs sur un mot ordinaire du titre.
_TITLE_HINT_KEYS = [k for k in ["french", "english", "japanese", "spanish", "german",
                                "italian", "portuguese", "dutch", "russian", "korean", "chinese"]]

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


def resolve_language(code: Optional[str], title: Optional[str] = None) -> tuple[str, Optional[str]]:
    """`(nom affiche, code drapeau)` -- code brut et `None` si la langue
    n'est pas reconnue (jamais de plantage, jamais de drapeau invente).

    `title` (optionnel) : repli si `code` est absent -- cas reel confirme
    (2026-09-13, dump MediaInfo reel) : certains fichiers (mkvmerge) ne
    renseignent JAMAIS le champ Language formel d'une piste de
    sous-titres, seul son `Title` libre porte la langue (ex. "French
    forced", "English SDH"). Recherche par MOT ENTIER sur le nom anglais
    complet de la langue (jamais un code court de 2-3 lettres, qui
    donnerait de faux positifs sur un mot ordinaire du titre) -- toujours
    en dernier recours, jamais si `code` est deja exploitable."""
    if code:
        info = LANGUAGE_INFO.get(code.strip().lower())
        return info if info else (code, None)
    if title:
        lowered = title.lower()
        for key in _TITLE_HINT_KEYS:
            if re.search(rf"\b{key}\b", lowered):
                return LANGUAGE_INFO[key]
    return code or "", None


def flagcdn_url(flag_code: str) -> str:
    """URL du drapeau (service public flagcdn.com, meme taille/service que
    l'exemple de reference C411)."""
    return f"https://flagcdn.com/20x15/{flag_code}.png"
