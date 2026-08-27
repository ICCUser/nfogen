"""Persistance sur disque du dernier scan GapScan termine.

Sans ceci, `gapscan_runner.py` ne conserve les resultats qu'en memoire
(comme `_SESSIONS`/`_LOGIN_ATTEMPTS` dans `api.py`) : un redemarrage du
processus -- notamment `scripts/update.sh`, qui redemarre le service --
faisait tout perdre, forcant a rescanner une bibliotheque entiere depuis
zero. Incident/retour utilisateur reel (2026-08-26) : "a chaque MAJ je vais
devoir refaire un scan ? ... je vais pas tout rescanner c'est pas fou".

Fichier optionnel (NFOGEN_GAPSCAN_RESULTS_FILE, meme convention que
NFOGEN_GAPSCAN_CONFIG_FILE) : si absent, la persistance est simplement
desactivee (comportement historique, tout en memoire) -- jamais une erreur
fatale, ni pour le demarrage de nfogen ni pour un scan par ailleurs reussi.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .c411_client import C411Release
from .gapscan import GapResult, GapStatus
from .quality import ReleaseQuality


def is_configured() -> bool:
    return bool(os.environ.get("NFOGEN_GAPSCAN_RESULTS_FILE"))


def _path() -> Optional[Path]:
    root = os.environ.get("NFOGEN_GAPSCAN_RESULTS_FILE")
    return Path(root) if root else None


def save(results: list[GapResult]) -> None:
    """Ecrit les resultats sur disque (remplace le contenu precedent).
    No-op silencieux si NFOGEN_GAPSCAN_RESULTS_FILE n'est pas configuree, ou
    si l'ecriture echoue (I/O) : la persistance est une commodite, jamais un
    motif d'echec d'un scan par ailleurs reussi."""
    path = _path()
    if path is None:
        return
    payload = {"saved_at": time.time(), "results": [asdict(r) for r in results]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        # Contient des titres/metadonnees de bibliotheque (pas des secrets),
        # meme prudence par defaut que gapscan_config_store.py. No-op
        # inoffensif sur Windows.
        os.chmod(path, 0o600)
    except OSError:
        pass


def _quality_from_dict(d: dict[str, Any]) -> ReleaseQuality:
    return ReleaseQuality(**d)


def _release_from_dict(d: dict[str, Any]) -> C411Release:
    d = dict(d)
    d.pop("quality", None)  # champ derive (__post_init__ la recalcule depuis `title`)
    return C411Release(**d)


def _result_from_dict(d: dict[str, Any]) -> GapResult:
    d = dict(d)
    d["status"] = GapStatus(d["status"])
    d["local_quality"] = _quality_from_dict(d["local_quality"])
    d["c411_matches"] = [_release_from_dict(m) for m in d.get("c411_matches", [])]
    return GapResult(**d)


def load() -> Optional[tuple[list[GapResult], float]]:
    """`(resultats, horodatage_sauvegarde)` du dernier scan persiste, ou
    `None` si non configure / jamais sauvegarde / fichier corrompu
    (best-effort, jamais d'exception : un fichier illisible ne doit pas
    empecher nfogen de demarrer -- il ne fait alors que perdre l'historique,
    pas planter)."""
    path = _path()
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        results = [_result_from_dict(r) for r in payload["results"]]
        return results, float(payload["saved_at"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
        return None
