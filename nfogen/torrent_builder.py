"""Construction du fichier .torrent final (voir AUTOMATION.md, sous-projet
2) : tracker prive, une seule adresse d'annonce (celle du compte, jamais
journalisee/exposee -- voir gapscan_config_store.py), taille de piece
choisie selon le bareme fourni par l'appelant (voir tracker_profile.py --
ce module reste agnostique du tracker, aucune table en dur ici).

`on_progress`/`cancel_event` (AUTOMATION.md, sous-projet 4c) : relayes
directement au callback natif de torf (Torrent.generate), aucune
reimplementation du hachage necessaire.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

import torf

from .cancellation import OperationCancelled


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
    staged_path: str,
    announce_url: str,
    output_path: str,
    piece_sizes: list[dict[str, int]],
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    threads: Optional[int] = None,
) -> None:
    """Construit un .torrent prive a partir de `staged_path` (fichier ou
    dossier -- un dossier pour un pack multi-fichiers -- deja mis en scene
    par file_staging.py, jamais le fichier original) et l'ecrit dans
    `output_path`. Taille de piece choisie via `piece_size_for` a partir du
    bareme `piece_sizes` du profil (voir tracker_profile.torrent_piece_sizes).
    `cancel_event` positionne pendant le hachage -> OperationCancelled, le
    fichier .torrent n'est jamais ecrit (write() n'est appele qu'apres un
    generate() reussi) -- l'arret n'est pas instantane, torf peut avoir
    deja termine le hachage de tres petites pieces avant le premier appel
    du callback (voir tests). `threads` (avance, `None` = defaut torf, un
    thread par coeur) : expose surtout pour forcer `threads=1` dans les
    tests d'annulation deterministes, sans effet sur le comportement de
    production par defaut."""
    total_bytes = _total_size(staged_path)
    torrent = torf.Torrent(
        path=staged_path,
        trackers=[announce_url],
        private=True,
        piece_size=piece_size_for(total_bytes, piece_sizes),
    )

    callback = None
    if on_progress or cancel_event:

        def callback(_torrent: torf.Torrent, _filepath: str, pieces_done: int, pieces_total: int):
            if cancel_event is not None and cancel_event.is_set():
                return True  # torf : non-None => arrete le hachage
            if on_progress:
                on_progress(pieces_done, pieces_total)
            return None

    success = torrent.generate(threads=threads, callback=callback, interval=0)
    if not success:
        raise OperationCancelled(f"Génération du torrent annulée : {staged_path}")
    torrent.write(output_path)
