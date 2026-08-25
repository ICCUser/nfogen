"""Execution en tache de fond d'un scan GapScan (`nfogen/gapscan.py`).

Etat en memoire (pas de base de donnees, coherent avec le reste de
nfogen -- cf. `_SESSIONS`/`_LOGIN_ATTEMPTS` dans `api.py`) : un seul scan a
la fois, resultats du dernier scan termine conserves jusqu'au prochain.
Perdu au redemarrage du processus, comme les sessions.

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

from .c411_client import C411Client
from .gapscan import GapResult, run_gapscan, sort_by_priority
from .radarr_client import RadarrClient
from .sonarr_client import SonarrClient


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


def results(status_filter: Optional[str] = None) -> list[GapResult]:
    """Resultats du dernier scan termine. `status_filter` : une valeur de
    `GapStatus` (ex. "absent") pour ne garder que ce statut."""
    with _lock:
        items = list(_results)
    if status_filter is not None:
        items = [r for r in items if r.status.value == status_filter]
    return items


def _run(c411: C411Client, radarr: Optional[RadarrClient], sonarr: Optional[SonarrClient]) -> None:
    global _results
    try:
        def on_progress(done: int, total: int) -> None:
            with _lock:
                _progress.processed = done
                _progress.total = total

        collected = run_gapscan(c411, radarr=radarr, sonarr=sonarr, on_progress=on_progress)
        with _lock:
            _results = sort_by_priority(collected)
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
    c411: C411Client,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
) -> bool:
    """Lance un scan en tache de fond avec des clients deja construits.
    `False` si un scan est deja en cours (un seul a la fois) -- les clients
    fournis restent alors a la charge de l'appelant (jamais fermes par ce
    module dans ce cas)."""
    with _lock:
        if _progress.state == ScanState.RUNNING:
            return False
        _progress.state = ScanState.RUNNING
        _progress.started_at = time.time()
        _progress.finished_at = None
        _progress.error = None
        _progress.total = 0
        _progress.processed = 0
    thread = threading.Thread(target=_run, args=(c411, radarr, sonarr), daemon=True)
    thread.start()
    return True
