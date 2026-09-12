"""Persistance sur disque de l'inventaire de base Bibliotheque (titre/
annee/qualite/taille/added_at, PAS le statut C411 -- voir
gapscan_results_store.py pour celui-ci, delibere ment separe : voir
docs/superpowers/specs/2026-09-12-library-inventory-cache-design.md).

Meme patron que gapscan_results_store.py : fichier JSON optionnel
(NFOGEN_LIBRARY_INVENTORY_FILE), jamais bloquant si absent/corrompu -- la
persistance est une commodite, jamais un motif d'echec pour le reste de
nfogen. Un deploiement qui n'a pas configure cette variable continue de
fonctionner exactement comme avant (voir nfogen/api.py:GET /gapscan/library) :
`load()` renvoie toujours None, `save()` est un no-op silencieux.

Alimente par library_sync_runner.py (jamais ecrit ailleurs) ; lu par
GET /gapscan/library (nfogen/api.py) pour un affichage instantane, sans
appel Radarr/Sonarr en fonctionnement normal.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .gapscan_library import LibraryItem
from .quality import ReleaseQuality


def is_configured() -> bool:
    return bool(os.environ.get("NFOGEN_LIBRARY_INVENTORY_FILE"))


def _path() -> Optional[Path]:
    root = os.environ.get("NFOGEN_LIBRARY_INVENTORY_FILE")
    return Path(root) if root else None


def save(items: list[LibraryItem], synced_at: float) -> None:
    """Ecrit l'inventaire sur disque (remplace le contenu precedent).
    No-op silencieux si NFOGEN_LIBRARY_INVENTORY_FILE n'est pas configuree,
    ou si l'ecriture echoue (I/O) : la persistance est une commodite,
    jamais un motif d'echec d'une synchro par ailleurs reussie."""
    path = _path()
    if path is None:
        return
    payload = {"synced_at": synced_at, "items": [asdict(i) for i in items]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        # Contient des titres/metadonnees de bibliotheque (pas des secrets),
        # meme prudence par defaut que gapscan_results_store.py. No-op
        # inoffensif sur Windows.
        os.chmod(path, 0o600)
    except OSError:
        pass


def _quality_from_dict(d: dict[str, Any]) -> ReleaseQuality:
    return ReleaseQuality(**d)


def _item_from_dict(d: dict[str, Any]) -> LibraryItem:
    d = dict(d)
    d["local_quality"] = _quality_from_dict(d["local_quality"])
    return LibraryItem(**d)


def load() -> Optional[tuple[list[LibraryItem], float]]:
    """`(items, synced_at)` de la derniere synchro reussie, ou `None` si
    non configure / jamais synchronise / fichier corrompu (best-effort,
    jamais d'exception : un fichier illisible ne doit pas empecher nfogen
    de demarrer -- il ne fait alors que perdre le cache, pas planter)."""
    path = _path()
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = [_item_from_dict(i) for i in payload["items"]]
        return items, float(payload["synced_at"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        return None
