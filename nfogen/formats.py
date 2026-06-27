"""Fonctions de formatage reutilisables (tailles, durees, alignement).

Volontairement sans dependance : utilisables aussi bien par les extracteurs
que par les templates Jinja (exposees comme filtres dans render.py).
"""
from __future__ import annotations

# Unites binaires, comme MediaInfo (KiB / MiB / GiB ...).
_BIN_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
# Unites decimales "a la francaise" (o / Ko / Mo / Go ...).
_DEC_UNITS = ["o", "Ko", "Mo", "Go", "To"]


def human_size_bin(num_bytes: float, decimals: int = 2) -> str:
    """Taille lisible en unites binaires (1024), ex. '3.97 GiB'."""
    size = float(num_bytes)
    for unit in _BIN_UNITS:
        if size < 1024 or unit == _BIN_UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.{decimals}f} {unit}"
        size /= 1024
    return f"{size:.{decimals}f} {_BIN_UNITS[-1]}"


def human_size_dec(num_bytes: float, decimals: int = 2) -> str:
    """Taille lisible en unites decimales (1000), ex. '31.44 Go'."""
    size = float(num_bytes)
    for unit in _DEC_UNITS:
        if size < 1000 or unit == _DEC_UNITS[-1]:
            if unit == "o":
                return f"{int(size)} {unit}"
            return f"{size:.{decimals}f} {unit}"
        size /= 1000
    return f"{size:.{decimals}f} {_DEC_UNITS[-1]}"


def mmss(seconds: float) -> str:
    """Duree au format mm:ss (ou h:mm:ss au-dela d'une heure)."""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def dotpad(label: str, value: str, width: int = 35, fill: str = ".") -> str:
    """Ligne 'label.....: value' (style generateur FervexPrez)."""
    label = str(label)
    if len(label) >= width:
        padded = label
    else:
        padded = label + fill * (width - len(label))
    return f"{padded}: {value}"


def colonpad(label: str, value: str, width: int = 41) -> str:
    """Ligne 'label    : value' alignee a la MediaInfo (espaces)."""
    return f"{str(label):<{width}}: {value}"


def banner(title: str, char: str = "\u2501", width: int = 44) -> str:
    """Banniere centree entre deux lignes de separation (style C411 audio)."""
    line = char * width
    return f"{line}\n{title.center(width)}\n{line}"
