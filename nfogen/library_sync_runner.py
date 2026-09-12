"""Synchronisation en tache de fond de l'inventaire Bibliotheque (voir
docs/superpowers/specs/2026-09-12-library-inventory-cache-design.md) :
recalcule gapscan_library.list_library() et persiste le resultat via
library_inventory_store, pour que GET /gapscan/library (nfogen/api.py)
n'ait plus jamais a interroger Radarr/Sonarr en fonctionnement normal.

Trois declencheurs, un seul chemin de code (sync_now()) : demarrage du
service, intervalle fixe (boucle de start()), et bouton "Rafraichir"
manuel (appel direct a sync_now() depuis l'API, voir nfogen/api.py).

Regle centrale (gestion d'erreur) : une synchro qui echoue ne doit JAMAIS
ecraser une copie locale valide -- le nouvel inventaire est calcule
entierement en memoire ; library_inventory_store.save() n'est appele
qu'apres succes complet.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import gapscan_config_store, gapscan_library, gapscan_runner, library_inventory_store
from .gapscan_library import LibraryItem
from .radarr_client import RadarrClient, RadarrError
from .sonarr_client import SonarrClient, SonarrError

logger = logging.getLogger("nfogen.library_sync_runner")

# Seul profil bundle actuellement (voir nfogen/profiles/c411/rules.json) --
# pas de multi-profil ici, le statut tracker par profil reste gere par
# gapscan_runner.results()/genre_of ailleurs (YAGNI, non demande).
_PROFILE = "c411"

_lock = threading.Lock()
_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None


@dataclass
class SyncState:
    last_attempt_at: Optional[float] = None
    last_attempt_error: Optional[str] = None


_state = SyncState()


def last_attempt() -> SyncState:
    return _state


def sync_now() -> Optional[list[LibraryItem]]:
    """Une synchro immediate. Renvoie la liste calculee en cas de succes
    (deja persistee via library_inventory_store.save()), `None` si aucune
    synchro n'a pu avoir lieu maintenant (verrou deja pris par une autre
    synchro en cours -- jamais bloquant), si aucune instance Sonarr/Radarr
    n'est configuree, ou si Radarr/Sonarr ont leve une erreur. Ne leve
    jamais elle-meme -- voir `last_attempt()` pour le detail de l'echec."""
    if not _lock.acquire(blocking=False):
        _state.last_attempt_error = "Synchronisation déjà en cours."
        logger.info("library_sync_runner: synchro deja en cours, declenchement ignore")
        return None
    try:
        _state.last_attempt_at = time.time()
        sonarr_config = gapscan_config_store.effective_sonarr()
        radarr_config = gapscan_config_store.effective_radarr()
        if sonarr_config is None and radarr_config is None:
            _state.last_attempt_error = "Aucune instance Sonarr ni Radarr configurée."
            logger.info("library_sync_runner: %s", _state.last_attempt_error)
            return None
        sonarr = SonarrClient(*sonarr_config) if sonarr_config else None
        radarr = RadarrClient(*radarr_config) if radarr_config else None
        try:
            items = gapscan_library.list_library(
                radarr=radarr, sonarr=sonarr,
                previous_results=gapscan_runner.results(), profile=_PROFILE,
            )
        finally:
            if sonarr is not None:
                sonarr.close()
            if radarr is not None:
                radarr.close()
    except (RadarrError, SonarrError) as exc:
        _state.last_attempt_error = str(exc)
        logger.warning("library_sync_runner: synchro echouee : %s", exc)
        return None
    else:
        library_inventory_store.save(items, _state.last_attempt_at)
        _state.last_attempt_error = None
        logger.info("library_sync_runner: synchro reussie (%d items)", len(items))
        return items
    finally:
        _lock.release()


def start(interval_seconds: float) -> None:
    """Lance le thread de synchro en tache de fond (idempotent -- un appel
    alors qu'un thread tourne deja ne fait rien de plus). Premiere synchro
    immediate, puis boucle toutes les `interval_seconds`."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()

    def _loop() -> None:
        while not _stop_event.is_set():
            sync_now()
            _stop_event.wait(interval_seconds)

    _thread = threading.Thread(target=_loop, daemon=True, name="library-sync")
    _thread.start()


def stop() -> None:
    """Arrete le thread de synchro (tests uniquement -- le processus nfogen
    ne s'arrete jamais autrement qu'en tuant le service)."""
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5)
