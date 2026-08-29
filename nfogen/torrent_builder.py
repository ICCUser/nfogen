"""Construction du fichier .torrent final (voir AUTOMATION.md, sous-projet
2) : tracker prive, une seule adresse d'annonce (celle du compte, jamais
journalisee/exposee -- voir gapscan_config_store.py), taille de piece
choisie selon le bareme fourni par l'appelant (voir tracker_profile.py --
ce module reste agnostique du tracker, aucune table en dur ici).
"""
from __future__ import annotations

from pathlib import Path

import torf


def piece_size_for(total_bytes: int, piece_sizes: list[dict[str, int]]) -> int:
    """Taille de piece (en octets) pour un contenu de `total_bytes`, d'apres
    le bareme `piece_sizes` du profil (rules.json -> tracker.torrent_piece_sizes,
    voir tracker_profile.py) -- plus aucune valeur specifique a un tracker
    en dur ici. Chaque entree : `{"max_bytes": N, "piece_size": P}` (piece
    P pour tout contenu < N octets), sauf la DERNIERE entree qui peut
    omettre `max_bytes` (piece par defaut au-dela de tous les seuils).
    Fonction pure, testable sans I/O."""
    for entry in piece_sizes:
        max_bytes = entry.get("max_bytes")
        if max_bytes is None or total_bytes < max_bytes:
            return entry["piece_size"]
    raise ValueError(
        "Barème de taille de pièce vide ou mal terminé (attendu : une dernière "
        "entrée sans 'max_bytes', voir rules.json -> tracker.torrent_piece_sizes)."
    )


def _total_size(path: str) -> int:
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def build_torrent(
    staged_path: str, announce_url: str, output_path: str, piece_sizes: list[dict[str, int]]
) -> None:
    """Construit un .torrent prive a partir de `staged_path` (fichier ou
    dossier -- un dossier pour un pack multi-fichiers -- deja mis en scene
    par file_staging.py, jamais le fichier original) et l'ecrit dans
    `output_path`. Taille de piece choisie via `piece_size_for` a partir du
    bareme `piece_sizes` du profil (voir tracker_profile.torrent_piece_sizes)."""
    total_bytes = _total_size(staged_path)
    torrent = torf.Torrent(
        path=staged_path,
        trackers=[announce_url],
        private=True,
        piece_size=piece_size_for(total_bytes, piece_sizes),
    )
    torrent.generate()
    torrent.write(output_path)
