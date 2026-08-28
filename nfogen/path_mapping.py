"""Resolution de chemins distants (Sonarr/Radarr) vers un chemin local que
nfogen peut ouvrir -- meme principe que les "Remote Path Mappings" de
Sonarr/Radarr eux-memes pour leur client de telechargement (voir
AUTOMATION.md, sous-projet 1). Sans mapping configure, le chemin distant
est utilise tel quel (deploiement a chemins identiques, ex. nfogen sur le
meme hote que Sonarr/Radarr).
"""
from __future__ import annotations

import os
from typing import Optional


def _matches_prefix(path: str, prefix: str) -> bool:
    """`True` si `path` est `prefix` lui-meme, ou est sous `prefix` (limite
    de repertoire respectee) -- un simple `str.startswith` confondrait a
    tort `/data/media2` avec le prefixe `/data/media`."""
    prefix = prefix.rstrip("/\\")
    if not prefix:
        return False
    return path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "\\")


def resolve_path(remote_path: str, mappings: dict[str, str]) -> str:
    """Substitue le prefixe distant le plus long de `mappings` qui
    correspond a `remote_path` par son equivalent local. Sans
    correspondance, `remote_path` est renvoye tel quel."""
    best_prefix: Optional[str] = None
    for remote_prefix in mappings:
        if _matches_prefix(remote_path, remote_prefix) and (
            best_prefix is None or len(remote_prefix) > len(best_prefix)
        ):
            best_prefix = remote_prefix
    if best_prefix is None:
        return remote_path
    local_prefix = mappings[best_prefix].rstrip("/\\")
    remainder = remote_path[len(best_prefix.rstrip("/\\")):]
    return local_prefix + remainder


def resolve_and_validate(
    remote_paths: list[str], mappings: dict[str, str]
) -> tuple[list[str], bool, Optional[str]]:
    """`(chemins_locaux, ok, erreur)`. `ok` est faux si `remote_paths` est
    vide (Sonarr/Radarr n'a fourni aucun chemin) ou si un des chemins
    resolus est introuvable/non lisible -- jamais d'exception levee, un
    probleme de chemin ne doit pas faire planter un scan complet (meme
    logique que les erreurs C411, voir gapscan.py)."""
    if not remote_paths:
        return [], False, "Aucun chemin connu pour ce fichier (Sonarr/Radarr ne l'a pas fourni)."
    resolved = [resolve_path(p, mappings) for p in remote_paths]
    for local_path in resolved:
        if not os.path.isfile(local_path):
            return resolved, False, f"Fichier introuvable apres resolution : {local_path}"
        if not os.access(local_path, os.R_OK):
            return resolved, False, f"Fichier non lisible : {local_path}"
    return resolved, True, None
