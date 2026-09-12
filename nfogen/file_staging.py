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

`manifest_dir` (retour utilisateur reel, 2026-09-12 : source sur un NAS
distant relie en WireGuard site-to-site -- montage reseau, donc TOUJOURS
en repli copie complete, jamais de hardlink direct possible avec la
source) : un simple renommage cosmetique du fichier de mise en scene
(ex. suite a un fix de convention de nommage) forcait jusque-la une
retransmission COMPLETE du fichier via le reseau distant, alors que son
contenu etait deja rapatrie sous un autre nom. Avec `manifest_dir`
renseigne (voir stage_file/stage_files), une petite table de
correspondance persistante (`.nfogen_staging_manifest.json`, cle = chemin
SOURCE, pas chemin de mise en scene) permet de retrouver une copie deja
en place et d'en faire un hardlink LOCAL (mise en scene -> mise en scene,
meme systeme de fichiers, donc instantane) au lieu de retoucher au
reseau. Note volontaire : jamais de symlink permanent vers la source --
un symlink rejouerait le cout reseau a CHAQUE lecture par un pair pendant
tout le seed, la ou une copie ponctuelle le paie une seule fois puis sert
depuis le disque local.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from .cancellation import OperationCancelled

_COPY_CHUNK_SIZE = 16 * 1024 * 1024  # 16 Mio
_MANIFEST_FILENAME = ".nfogen_staging_manifest.json"


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


def _manifest_path(manifest_dir: str) -> Path:
    return Path(manifest_dir) / _MANIFEST_FILENAME


def _load_manifest(manifest_dir: str) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_manifest_path(manifest_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _already_staged_copy(manifest_dir: str, source_path: str, source_size: int) -> Optional[str]:
    """Cherche, dans le manifest de mise en scene, une copie DEJA presente
    (sous n'importe quel nom, potentiellement un ancien nom de release
    perime) du MEME `source_path` -- permet un hardlink LOCAL (mise en
    scene -> mise en scene, meme systeme de fichiers) au lieu de
    retransferer depuis la source distante (voir docstring du module).
    Cle du manifest = chemin SOURCE (stable d'un essai a l'autre), jamais
    le nom de mise en scene (qui, lui, change a chaque fix de convention
    ou nouvelle tentative). Verifie que le fichier deja en scene existe
    TOUJOURS et fait TOUJOURS la meme taille que la source actuelle --
    `None` sinon (jamais bloquant, juste pas de raccourci pris)."""
    entry = _load_manifest(manifest_dir).get(source_path)
    if entry is None:
        return None
    staged_path = entry.get("staged_path")
    if not staged_path or entry.get("size") != source_size:
        return None
    try:
        if os.path.getsize(staged_path) != source_size:
            return None
    except OSError:
        return None
    return staged_path


def _remember_staged(manifest_dir: str, source_path: str, target_path: str, size: int) -> None:
    """Enregistre `target_path` comme mise en scene connue de
    `source_path`, pour qu'une FUTURE mise en scene du meme fichier source
    (sous un nom potentiellement different) puisse le retrouver via
    `_already_staged_copy` plutot que de retoucher au reseau. Best-effort
    : jamais bloquant si l'ecriture echoue (dossier en lecture seule,
    disque plein...) -- le manifest n'est qu'une optimisation, jamais une
    source de verite pour la mise en scene elle-meme."""
    manifest = _load_manifest(manifest_dir)
    manifest[source_path] = {"staged_path": target_path, "size": size}
    try:
        _manifest_path(manifest_dir).write_text(json.dumps(manifest), encoding="utf-8")
    except OSError:
        pass


def _link_or_copy(
    link_from: str,
    source_path: str,
    target_path: str,
    on_progress: Optional[Callable[[int, int], None]],
    cancel_event: Optional[threading.Event],
) -> None:
    """Tente un hardlink depuis `link_from` (soit `source_path` lui-meme,
    soit une copie deja en scene du meme contenu trouvee via le manifest
    -- voir `stage_file`). Si `link_from` differe de `source_path` et que
    le hardlink echoue de facon inattendue (jamais un EXDEV normal, meme
    dossier de mise en scene des deux cotes) : retente depuis
    `source_path` par securite avant d'abandonner. Copie complete par
    blocs en tout dernier recours seulement -- seul cas ou `on_progress`
    recoit plusieurs appels."""
    try:
        os.link(link_from, target_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        if link_from == source_path:
            _copy_with_progress(source_path, target_path, on_progress, cancel_event)
            return
        try:
            os.link(source_path, target_path)
        except OSError as exc2:
            if exc2.errno != errno.EXDEV:
                raise
            _copy_with_progress(source_path, target_path, on_progress, cancel_event)
            return
    if on_progress:
        size = os.path.getsize(target_path)
        on_progress(size, size)


def stage_file(
    source_path: str,
    target_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    overwrite: bool = False,
    manifest_dir: Optional[str] = None,
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
    Radarr/Sonarr n'est jamais touchee (voir docstring du module).

    `manifest_dir` (optionnel, voir docstring du module) : si fourni et
    qu'une copie de ce MEME `source_path` est deja connue en mise en
    scene (sous n'importe quel nom), un hardlink LOCAL la reutilise au
    lieu de retransferer depuis une source distante."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _sizes_match(source_path, target_path):
            size = target.stat().st_size
            if on_progress:
                on_progress(size, size)
            if manifest_dir:
                _remember_staged(manifest_dir, source_path, target_path, size)
            return target_path
        if overwrite:
            target.unlink()

    source_size = os.path.getsize(source_path)
    link_from = source_path
    if manifest_dir:
        reused = _already_staged_copy(manifest_dir, source_path, source_size)
        if reused is not None:
            link_from = reused

    _link_or_copy(link_from, source_path, target_path, on_progress, cancel_event)

    if manifest_dir:
        _remember_staged(manifest_dir, source_path, target_path, source_size)
    return target_path


def stage_files(
    source_paths: list[str],
    target_dir: str,
    names: list[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    overwrite: bool = False,
    manifest_dir: Optional[str] = None,
) -> list[str]:
    """Met en scene plusieurs fichiers d'un coup (ex. un pack de saison) --
    un nom de sortie par source, meme ordre. `on_progress`, si fourni,
    recoit une progression CUMULEE sur l'ensemble des fichiers (pas par
    fichier individuel) -- une seule barre pour tout le groupe. `overwrite`
    (voir stage_file(), applique a CHAQUE fichier du pack) ne concerne que
    les fichiers de taille DIFFERENTE de leur source -- un fichier deja
    present et de la bonne taille est toujours reutilise tel quel, avec ou
    sans `overwrite`. `manifest_dir` : voir stage_file(), transmis tel
    quel a chaque fichier du pack. Renvoie les chemins finaux, dans le
    meme ordre."""
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
                overwrite=overwrite, manifest_dir=manifest_dir,
            )
        )
        done_before += os.path.getsize(source)
    return results
