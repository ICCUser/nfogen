"""Construction du fichier .torrent final, conforme aux regles C411 (voir
AUTOMATION.md, sous-projet 2) : bareme de taille de piece par poids
total, tracker prive, une seule adresse d'annonce (celle du compte,
jamais journalisee/exposee -- voir gapscan_config_store.py).
"""
from __future__ import annotations

from pathlib import Path

import torf

# Bareme C411 (voir AUTOMATION.md) : jamais "Auto", toujours une valeur
# explicite -- un .torrent de plus de 16 Mo risque d'etre rejete/mal gere.
_PIECE_SIZE_TABLE: list[tuple[int, int]] = [
    (1 * 1024**3, 1 * 1024**2),   # < 1 Go -> 1 Mo
    (2 * 1024**3, 2 * 1024**2),   # < 2 Go -> 2 Mo
    (3 * 1024**3, 4 * 1024**2),   # < 3 Go -> 4 Mo
    (8 * 1024**3, 8 * 1024**2),   # < 8 Go -> 8 Mo
]
_DEFAULT_PIECE_SIZE = 16 * 1024**2  # >= 8 Go -> 16 Mo


def piece_size_for(total_bytes: int) -> int:
    """Taille de piece (en octets) recommandee par C411 pour un contenu de
    `total_bytes`. Fonction pure, testable sans fichier reel."""
    for threshold, size in _PIECE_SIZE_TABLE:
        if total_bytes < threshold:
            return size
    return _DEFAULT_PIECE_SIZE


def _total_size(path: str) -> int:
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def build_torrent(staged_path: str, announce_url: str, output_path: str) -> None:
    """Construit un .torrent prive a partir de `staged_path` (fichier ou
    dossier -- un dossier pour un pack multi-fichiers -- deja mis en scene
    par file_staging.py, jamais le fichier original) et l'ecrit dans
    `output_path`. Taille de piece choisie selon le bareme C411 a partir
    du poids total du contenu."""
    total_bytes = _total_size(staged_path)
    torrent = torf.Torrent(
        path=staged_path,
        trackers=[announce_url],
        private=True,
        piece_size=piece_size_for(total_bytes),
    )
    torrent.generate()
    torrent.write(output_path)
