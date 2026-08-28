"""Mise en scene de fichiers avant creation d'un .torrent -- jamais le
fichier original (voir AUTOMATION.md, sous-projet 2) : cree un hardlink
sous le nom voulu (0 octet supplementaire), avec repli automatique sur
une copie complete si la cible n'est pas sur le meme systeme de fichiers
(EXDEV) -- meme detection que celle deja utilisee ailleurs dans le
projet pour ce cas.

Important pour les consommateurs de ce module (ex. torrent_builder.py) :
un hardlink partage le meme contenu que l'original -- n'ECRIRE JAMAIS
dans un chemin mis en scene, seulement le lire.
"""
from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path


def stage_file(source_path: str, target_path: str) -> str:
    """Met `source_path` a disposition sous `target_path` : hardlink si
    possible, copie complete en repli (systemes de fichiers differents).
    Cree les dossiers parents de `target_path` si besoin. Renvoie
    `target_path`."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source_path, target_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copy2(source_path, target_path)
    return target_path


def stage_files(source_paths: list[str], target_dir: str, names: list[str]) -> list[str]:
    """Met en scene plusieurs fichiers d'un coup (ex. un pack de saison) --
    un nom de sortie par source, meme ordre. Renvoie les chemins finaux,
    dans le meme ordre."""
    return [
        stage_file(source, str(Path(target_dir) / name))
        for source, name in zip(source_paths, names)
    ]
