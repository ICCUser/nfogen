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

import errno
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
    overwrite: bool = False,
    source: Optional[str] = None,
    backup_announce_url: Optional[str] = None,
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
    production par defaut.

    `overwrite` (AUTOMATION.md, sous-projet 8 -- incident reel, 2026-09-06 :
    refaire "Confirmer" pour un titre deja mis en scene faisait planter la
    generation du .torrent avec un message brut et incomprehensible) :
    `False` par defaut, comme `file_staging.stage_file` -- torf refuse
    nativement d'ecraser un `.torrent` deja present (`torf.WriteError`,
    errno EEXIST) ; traduit ici en `FileExistsError` standard, pour que
    l'appelant (upload_prep.commit_upload) le traite exactement comme la
    meme situation cote fichier mis en scene.

    `source` (retour C411, 2026-09-07 -- voir tracker_profile.torrent_source) :
    tag `source` inscrit dans le .torrent, modifie son hash. C'est le
    mecanisme utilise par la plupart des trackers prives pour reconnaitre
    un torrent comme le leur -- une fois ce tag correct, plus besoin de
    telecharger un .torrent re-signe apres moderation pour le mettre en
    seed (voir AUTOMATION.md, sous-projet 6). `None` par defaut : aucun
    tag ajoute, comportement inchange pour un profil qui n'en declare pas."""
    total_bytes = _total_size(staged_path)
    # `backup_announce_url` (page d'aide "Integrations API" C411, 2026-09-13) :
    # adresse de secours (`tk.c411.tw`, meme passkey), a ajouter au MEME
    # niveau (tier BEP12) que l'adresse principale -- "sur une nouvelle
    # ligne, juste sous l'adresse existante et sans ligne vide entre les
    # deux", pour que le client bascule seul dessus si la principale devient
    # injoignable, plutot que de l'interroger EN PLUS (ce qu'un second tier,
    # cree par une ligne vide, ferait). torf construit un tier separe pour
    # CHAQUE element d'une liste plate passee a `trackers=` -- un seul tier
    # avec les deux adresses exige donc de les regrouper dans une sous-liste.
    if backup_announce_url:
        trackers: list = [[announce_url, backup_announce_url]]
    else:
        trackers = [announce_url]
    torrent = torf.Torrent(
        path=staged_path,
        trackers=trackers,
        private=True,
        piece_size=piece_size_for(total_bytes, piece_sizes),
        source=source,
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
    try:
        torrent.write(output_path, overwrite=overwrite)
    except torf.WriteError as exc:
        if exc.errno == errno.EEXIST:
            raise FileExistsError(errno.EEXIST, "Fichier déjà existant", output_path) from exc
        raise
