"""Mise en scene de fichiers avant creation d'un .torrent -- jamais le
fichier original (voir AUTOMATION.md, sous-projet 2) : cree un hardlink
sous le nom voulu (0 octet supplementaire), avec repli automatique sur
une copie complete si la cible n'est pas sur le meme systeme de fichiers
(EXDEV) -- meme detection que celle deja utilisee ailleurs dans le
projet pour ce cas.

Important pour les consommateurs de ce module (ex. torrent_builder.py) :
un hardlink partage le meme contenu que l'original -- n'ECRIRE JAMAIS
dans un chemin mis en scene, seulement le lire.

`on_progress`/`cancel_event` (AUTOMATION.md, sous-projet 4c) : optionnels,
utilises par commit_job_runner.py pour suivre/annuler une mise en scene
en tache de fond. Le chemin hardlink est instantane (un seul appel
on_progress) ; seul le repli copie est effectivement decoupe en blocs.
"""
from __future__ import annotations

import errno
import os
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

from .cancellation import OperationCancelled

_COPY_CHUNK_SIZE = 16 * 1024 * 1024  # 16 Mio


def _copy_with_progress(
    source_path: str,
    target_path: str,
    on_progress: Optional[Callable[[int, int], None]],
    cancel_event: Optional[threading.Event],
) -> None:
    total = os.path.getsize(source_path)
    done = 0
    try:
        with open(source_path, "rb") as src, open(target_path, "wb") as dst:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelled(f"Copie annulée : {source_path} -> {target_path}")
                chunk = src.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        shutil.copystat(source_path, target_path)
    except OperationCancelled:
        Path(target_path).unlink(missing_ok=True)
        raise
    if on_progress and total == 0:
        # Fichier vide : la boucle ne rentre jamais dans son corps (le
        # premier read() renvoie deja b"" avant tout appel a on_progress) --
        # signale quand meme l'achevement, jamais silencieux.
        on_progress(0, 0)


def _sizes_match(source_path: str, target_path: str) -> bool:
    """Verification RAPIDE (taille seule, pas de hash) qu'une cible deja
    presente correspond probablement deja a la source -- evite un
    hardlink/une copie inutile d'un fichier deja entierement mis en scene
    par un essai precedent. Incident reel (2026-09-06) : source et dossier
    de mise en scene sur des montages differents (hardlink impossible,
    repli copie complete) -- un pack de plusieurs Go deja correctement
    copie se faisait integralement re-copier a chaque nouvelle tentative
    de "Confirmer", vecu comme un re-telechargement par l'utilisateur."""
    try:
        return os.path.getsize(target_path) == os.path.getsize(source_path)
    except OSError:
        return False


def stage_file(
    source_path: str,
    target_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    overwrite: bool = False,
) -> str:
    """Met `source_path` a disposition sous `target_path` : hardlink si
    possible, copie complete par blocs en repli (systemes de fichiers
    differents). Cree les dossiers parents de `target_path` si besoin.
    Renvoie `target_path`.

    Si `target_path` existe DEJA et a la MEME TAILLE que `source_path` :
    considere deja en place, RIEN N'EST REFAIT (ni hardlink ni copie) --
    voir `_sizes_match`. Sinon (taille differente, dechet partiel/corrompu
    d'un essai precedent) : `FileExistsError` par defaut (deja ce que
    `os.link` leve nativement pour EEXIST -- incident reel, 2026-09-06,
    "[Errno 17] File exists"). `overwrite=True` (AUTOMATION.md, sous-projet
    8 -- decide par l'appelant selon l'historique "deja traite") : supprime
    alors la cible avant de refaire le hardlink/la copie, TOUJOURS depuis
    `source_path` en local -- jamais un nouveau telechargement, la source
    Radarr/Sonarr n'est jamais touchee (voir docstring du module)."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _sizes_match(source_path, target_path):
            size = target.stat().st_size
            if on_progress:
                on_progress(size, size)
            return target_path
        if overwrite:
            target.unlink()
    try:
        os.link(source_path, target_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        _copy_with_progress(source_path, target_path, on_progress, cancel_event)
        return target_path
    if on_progress:
        size = target.stat().st_size
        on_progress(size, size)
    return target_path


def stage_files(
    source_paths: list[str],
    target_dir: str,
    names: list[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    overwrite: bool = False,
) -> list[str]:
    """Met en scene plusieurs fichiers d'un coup (ex. un pack de saison) --
    un nom de sortie par source, meme ordre. `on_progress`, si fourni,
    recoit une progression CUMULEE sur l'ensemble des fichiers (pas par
    fichier individuel) -- une seule barre pour tout le groupe. `overwrite`
    (voir stage_file(), applique a CHAQUE fichier du pack) ne concerne que
    les fichiers de taille DIFFERENTE de leur source -- un fichier deja
    present et de la bonne taille est toujours reutilise tel quel, avec ou
    sans `overwrite`. Renvoie les chemins finaux, dans le meme ordre."""
    grand_total = sum(os.path.getsize(p) for p in source_paths)
    done_before = 0
    results: list[str] = []
    for source, name in zip(source_paths, names):
        target_path = str(Path(target_dir) / name)

        def _relay(done: int, total: int, _done_before: int = done_before) -> None:
            if on_progress:
                on_progress(_done_before + done, grand_total)

        results.append(
            stage_file(
                source, target_path,
                on_progress=_relay if on_progress else None, cancel_event=cancel_event,
                overwrite=overwrite,
            )
        )
        done_before += os.path.getsize(source)
    return results
