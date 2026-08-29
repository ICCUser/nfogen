"""Execution en tache de fond d'un scan GapScan (`nfogen/gapscan.py`).

Etat en memoire (pas de base de donnees, coherent avec le reste de
nfogen -- cf. `_SESSIONS`/`_LOGIN_ATTEMPTS` dans `api.py`) : un seul scan a
la fois, resultats du dernier scan termine conserves jusqu'au prochain.

Persiste sur disque de facon optionnelle (`gapscan_results_store.py`,
NFOGEN_GAPSCAN_RESULTS_FILE) : sans ca, un redemarrage du processus (ex.
`scripts/update.sh`) faisait tout perdre, forcant a rescanner une
bibliotheque entiere depuis zero -- retour utilisateur, 2026-08-26.
Recharge au chargement du module (equivalent d'un demarrage de processus).

Les clients (C411/Radarr/Sonarr) sont fournis DEJA CONSTRUITS par
l'appelant (`api.py`, a partir des variables d'environnement) : ce module
ne connait ni les URLs ni les cles, seulement comment orchestrer un scan
en tache de fond et exposer sa progression.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from . import gapscan_results_store
from .gapscan import GapResult, genre_of, run_gapscan, sort_by_priority
from .radarr_client import RadarrClient
from .sonarr_client import SonarrClient
from .torznab_client import TorznabClient


class ScanState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class _Progress:
    state: ScanState = ScanState.IDLE
    total: int = 0
    processed: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None


_lock = threading.Lock()
_progress = _Progress()
_results: list[GapResult] = []


def _restore_persisted() -> None:
    """Recharge le dernier scan persiste (voir gapscan_results_store.py) au
    chargement du module -- sans ca, /gapscan/results renverrait une liste
    vide juste apres un redemarrage/une mise a jour, meme si un scan complet
    a deja ete fait. No-op si la persistance n'est pas configuree ou si rien
    n'a jamais ete sauvegarde."""
    global _results
    loaded = gapscan_results_store.load()
    if loaded is None:
        return
    restored, saved_at = loaded
    with _lock:
        _results = restored
        _progress.state = ScanState.DONE
        _progress.total = len(restored)
        _progress.processed = len(restored)
        _progress.finished_at = saved_at


_restore_persisted()


def status() -> dict[str, Any]:
    with _lock:
        p = _progress
        return {
            "state": p.state.value,
            "total": p.total,
            "processed": p.processed,
            "started_at": p.started_at,
            "finished_at": p.finished_at,
            "error": p.error,
        }


def results(
    status_filter: Optional[str] = None,
    media_type_filter: Optional[str] = None,
    genre_filter: Optional[str] = None,
    profile: str = "c411",
) -> list[GapResult]:
    """Resultats du dernier scan termine. `status_filter` : une valeur de
    `GapStatus` (ex. "absent"). `media_type_filter` : "movie" ou "series".
    `genre_filter` : "anime" ou "documentaire", evalue contre les
    categories Torznab DU PROFIL `profile` (voir `gapscan.genre_of` /
    `tracker_profile.torznab_categories`) -- un titre sans match C411 ne
    correspond jamais a un genre_filter."""
    with _lock:
        items = list(_results)
    if status_filter is not None:
        items = [r for r in items if r.status.value == status_filter]
    if media_type_filter is not None:
        items = [r for r in items if r.media_type == media_type_filter]
    if genre_filter is not None:
        items = [r for r in items if genre_of(r, profile) == genre_filter]
    return items


def _run(
    c411: TorznabClient,
    radarr: Optional[RadarrClient],
    sonarr: Optional[SonarrClient],
    previous_results: Optional[list[GapResult]],
    only: Optional[str],
    max_age_seconds: Optional[float],
    sonarr_path_mappings: Optional[dict[str, str]],
    radarr_path_mappings: Optional[dict[str, str]],
) -> None:
    global _results
    try:
        def on_progress(done: int, total: int) -> None:
            with _lock:
                _progress.processed = done
                _progress.total = total

        collected = run_gapscan(
            c411, radarr=radarr, sonarr=sonarr, on_progress=on_progress,
            previous_results=previous_results, only=only, max_age_seconds=max_age_seconds,
            sonarr_path_mappings=sonarr_path_mappings, radarr_path_mappings=radarr_path_mappings,
        )
        sorted_results = sort_by_priority(collected)
        # Persiste AVANT de signaler "termine" : incident CI reel
        # (2026-08-27) -- si l'ecriture disque survenait apres le passage a
        # DONE, un lecteur externe (redemarrage reel, ou reload en test)
        # pouvait observer DONE sans que le fichier existe encore.
        gapscan_results_store.save(sorted_results)
        with _lock:
            _results = sorted_results
            _progress.state = ScanState.DONE
            _progress.finished_at = time.time()
    except Exception as exc:  # noqa: BLE001 -- toute erreur client -> statut "error", jamais une exception non geree dans le thread
        with _lock:
            _progress.state = ScanState.ERROR
            _progress.error = str(exc)
            _progress.finished_at = time.time()
    finally:
        c411.close()
        if radarr is not None:
            radarr.close()
        if sonarr is not None:
            sonarr.close()


def start(
    c411: TorznabClient,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    incremental: bool = False,
    only: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
) -> bool:
    """Lance un scan en tache de fond avec des clients deja construits.
    `False` si un scan est deja en cours (un seul a la fois) -- les clients
    fournis restent alors a la charge de l'appelant (jamais fermes par ce
    module dans ce cas).

    `incremental` : reutilise les resultats du dernier scan (memoire ou
    persistes, voir _restore_persisted) pour les titres deja COVERED et
    dont la qualite locale n'a pas change -- evite de tout rescanner a
    chaque fois (retour utilisateur, 2026-08-26). `False` par defaut : scan
    complet, comportement historique. `max_age_seconds` : au-dela de cet
    age, un COVERED est reverifie meme en mode incremental (retour
    utilisateur, 2026-08-27 : C411 retire/ajoute des torrents assez
    souvent) -- ignore si `incremental` est faux.

    `only` ("movies"/"series"/None) : ne scanne qu'une des deux
    bibliotheques -- pour repartir la charge sur plusieurs sessions.

    `sonarr_path_mappings`/`radarr_path_mappings` : voir AUTOMATION.md,
    sous-projet 1."""
    with _lock:
        if _progress.state == ScanState.RUNNING:
            return False
        previous_results = list(_results) if incremental else None
        _progress.state = ScanState.RUNNING
        _progress.started_at = time.time()
        _progress.finished_at = None
        _progress.error = None
        _progress.total = 0
        _progress.processed = 0
    thread = threading.Thread(
        target=_run,
        args=(
            c411, radarr, sonarr, previous_results, only, max_age_seconds,
            sonarr_path_mappings, radarr_path_mappings,
        ),
        daemon=True,
    )
    thread.start()
    return True
