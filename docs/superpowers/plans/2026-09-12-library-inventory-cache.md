# Cache local de l'inventaire Bibliothèque Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La page Bibliothèque (`GET /gapscan/library`) lit un inventaire persisté localement au lieu d'interroger Radarr/Sonarr à chaque requête, synchronisé en tâche de fond.

**Architecture:** Un nouveau store JSON (`library_inventory_store.py`, même patron que `gapscan_results_store.py`) persiste `list[LibraryItem]`. Un nouveau runner (`library_sync_runner.py`) recalcule cet inventaire via `gapscan_library.list_library()` (inchangé) et le persiste, déclenché par un intervalle fixe, le démarrage du service, ou un bouton "Rafraîchir". `GET /gapscan/library` lit le store ; l'ancien mécanisme de cache TTL/single-flight (`_cached_library_items`) est supprimé, remplacé entièrement par ce nouveau mécanisme.

**Tech Stack:** Python (FastAPI, dataclasses, `threading`), TypeScript/React (frontend existant).

**Spec:** [docs/superpowers/specs/2026-09-12-library-inventory-cache-design.md](../specs/2026-09-12-library-inventory-cache-design.md)

## Global Constraints

- Périmètre limité à l'AFFICHAGE de la Bibliothèque uniquement — aucune action (Préparer l'upload, Confirmer, envoi C411) ne doit changer de comportement ; elles restent toutes en direct.
- Persistance séparée de `gapscan_results_store.py` (pas de fusion des deux fichiers).
- Trois déclencheurs de synchro (intervalle fixe, démarrage, bouton manuel) partageant un seul chemin de code (`sync_now()`).
- Une synchro qui échoue ne doit jamais écraser une copie locale valide.
- Un déploiement qui n'a pas configuré `NFOGEN_LIBRARY_INVENTORY_FILE` doit continuer à fonctionner exactement comme aujourd'hui (fetch live à chaque requête), sans erreur ni régression — même philosophie "opt-in, jamais bloquant" que `gapscan_results_store.py`.

---

## Task 1: `library_inventory_store.py` — persistance de l'inventaire

**Files:**
- Create: `nfogen/library_inventory_store.py`
- Test: `tests/test_library_inventory_store.py`

**Interfaces:**
- Consumes: `nfogen.gapscan_library.LibraryItem` (dataclass existante), `nfogen.quality.ReleaseQuality` (dataclass existante).
- Produces: `is_configured() -> bool`, `save(items: list[LibraryItem], synced_at: float) -> None`, `load() -> Optional[tuple[list[LibraryItem], float]]` — consommés par Task 2 (`library_sync_runner.py`) et Task 3 (`api.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests de nfogen.library_inventory_store (persistance de l'inventaire
Bibliotheque -- meme patron que gapscan_results_store.py, mais un fichier
separe : voir docs/superpowers/specs/2026-09-12-library-inventory-cache-design.md)."""
from __future__ import annotations

from nfogen.gapscan_library import LibraryItem
from nfogen.quality import ReleaseQuality


def _sample_item() -> LibraryItem:
    return LibraryItem(
        media_type="movie", title="Inception", year=2010, season_number=None,
        imdb_id="tt1375666", tvdb_id=None, tmdb_id="27205",
        genres=["Science-Fiction"], added_at=1700000000.0,
        local_quality=ReleaseQuality(raw="x", resolution=1080, source="BluRay", codec="x264",
                                      languages=["fr"], multi=False, pure=False),
        radarr_movie_id=42, sonarr_series_id=None,
        already_processed=False, last_processed_at=None,
        key="[\"movie\", \"tt1375666\", \"27205\", \"Inception\", 2010]",
        status="covered", checked_at=1700000001.0,
        has_freeleech_alternative=False, has_double_upload_window=False, error=None,
        local_paths=["/media/Inception.mkv"], path_resolved=True, path_error=None,
        tracker_genre=None, team="TEAM", seed_match={"guid": "g1", "release_name": "Inception.2010.TEAM"},
        size_bytes=21474836480,
    )


def test_save_then_load_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "library_inventory.json"))
    from nfogen import library_inventory_store

    item = _sample_item()
    library_inventory_store.save([item], synced_at=1700000123.0)

    loaded = library_inventory_store.load()
    assert loaded is not None
    items, synced_at = loaded
    assert synced_at == 1700000123.0
    assert items == [item]


def test_is_configured_reflects_env_var(monkeypatch, tmp_path):
    from nfogen import library_inventory_store

    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    assert library_inventory_store.is_configured() is False

    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "x.json"))
    assert library_inventory_store.is_configured() is True


def test_load_returns_none_when_not_configured(monkeypatch):
    from nfogen import library_inventory_store

    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    assert library_inventory_store.load() is None


def test_load_returns_none_when_file_absent(monkeypatch, tmp_path):
    from nfogen import library_inventory_store

    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "does-not-exist.json"))
    assert library_inventory_store.load() is None


def test_load_returns_none_on_corrupted_json(monkeypatch, tmp_path):
    from nfogen import library_inventory_store

    path = tmp_path / "library_inventory.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(path))
    assert library_inventory_store.load() is None


def test_save_is_a_noop_when_not_configured(monkeypatch):
    from nfogen import library_inventory_store

    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    library_inventory_store.save([_sample_item()], synced_at=1700000000.0)  # ne doit pas lever
    assert library_inventory_store.load() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_library_inventory_store.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.library_inventory_store'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_library_inventory_store.py -v`
Expected: 6 PASS

- [ ] **Step 5: Ruff + commit**

```bash
ruff check nfogen/library_inventory_store.py tests/test_library_inventory_store.py
git add nfogen/library_inventory_store.py tests/test_library_inventory_store.py
git commit -m "feat: library_inventory_store -- persistance de l'inventaire Bibliotheque"
```

---

## Task 2: `library_sync_runner.py` — synchronisation en tâche de fond

**Files:**
- Create: `nfogen/library_sync_runner.py`
- Test: `tests/test_library_sync_runner.py`

**Interfaces:**
- Consumes: `library_inventory_store.save()` (Task 1) ; `gapscan_library.list_library()`, `gapscan_config_store.effective_sonarr()`/`effective_radarr()`, `gapscan_runner.results()`, `RadarrClient`/`RadarrError`, `SonarrClient`/`SonarrError` (tous existants, inchangés).
- Produces: `sync_now() -> Optional[list[LibraryItem]]` (la liste calculée en cas de succès, `None` si aucune synchro n'a pu tourner — verrou déjà pris, config absente, ou échec Radarr/Sonarr), `last_attempt() -> SyncState` (`SyncState.last_attempt_at: Optional[float]`, `SyncState.last_attempt_error: Optional[str]`), `start(interval_seconds: float) -> None`, `stop() -> None`. Consommés par Task 3 (`api.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests de nfogen.library_sync_runner (synchronisation en tache de fond
de l'inventaire Bibliotheque -- voir docs/superpowers/specs/
2026-09-12-library-inventory-cache-design.md)."""
from __future__ import annotations

import threading
import time

import pytest

from nfogen import gapscan_config_store, library_inventory_store, library_sync_runner
from nfogen.gapscan_library import LibraryItem
from nfogen.radarr_client import RadarrError, RadarrMovieFile


class _FakeRadarr:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def list_movie_files(self):
        return [RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)]

    def close(self):
        self.closed = True


class _FailingRadarr(_FakeRadarr):
    def list_movie_files(self):
        raise RadarrError("Radarr injoignable")


class _GatedRadarr(_FakeRadarr):
    gate: threading.Event = threading.Event()

    def list_movie_files(self):
        self.gate.wait(timeout=5)
        return super().list_movie_files()


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Isole chaque test : pas d'instance Sonarr/Radarr configuree par
    defaut, etat de synchro remis a zero."""
    monkeypatch.delenv("NFOGEN_RADARR_URL", raising=False)
    monkeypatch.delenv("NFOGEN_SONARR_URL", raising=False)
    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    library_sync_runner._state.last_attempt_at = None
    library_sync_runner._state.last_attempt_error = None
    yield
    library_sync_runner.stop()


def test_sync_now_returns_none_and_sets_error_without_any_config():
    result = library_sync_runner.sync_now()
    assert result is None
    assert library_sync_runner.last_attempt().last_attempt_error is not None


def test_sync_now_returns_items_and_saves_on_success(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_RADARR_URL", "http://radarr.local")
    monkeypatch.setenv("NFOGEN_RADARR_API_KEY", "y")
    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "inv.json"))
    monkeypatch.setattr(library_sync_runner, "RadarrClient", _FakeRadarr)

    result = library_sync_runner.sync_now()

    assert result is not None
    assert len(result) == 1
    assert result[0].title == "Matrix"
    assert library_sync_runner.last_attempt().last_attempt_error is None
    loaded = library_inventory_store.load()
    assert loaded is not None
    assert loaded[0] == result


def test_sync_now_does_not_overwrite_existing_cache_on_failure(monkeypatch, tmp_path):
    inventory_file = tmp_path / "inv.json"
    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(inventory_file))
    existing_item = LibraryItem(
        media_type="movie", title="Deja-la", year=2000, season_number=None,
        imdb_id=None, tvdb_id=None, tmdb_id=None, genres=[], added_at=None,
        local_quality=__import__("nfogen.quality", fromlist=["ReleaseQuality"]).ReleaseQuality(raw="x"),
        radarr_movie_id=1, sonarr_series_id=None, already_processed=False,
        last_processed_at=None, key="k",
    )
    library_inventory_store.save([existing_item], synced_at=1700000000.0)

    monkeypatch.setenv("NFOGEN_RADARR_URL", "http://radarr.local")
    monkeypatch.setenv("NFOGEN_RADARR_API_KEY", "y")
    monkeypatch.setattr(library_sync_runner, "RadarrClient", _FailingRadarr)

    result = library_sync_runner.sync_now()

    assert result is None
    assert "Radarr injoignable" in library_sync_runner.last_attempt().last_attempt_error
    loaded = library_inventory_store.load()
    assert loaded is not None
    assert loaded[0] == [existing_item]  # copie precedente intacte, non ecrasee


def test_sync_now_lock_prevents_concurrent_runs(monkeypatch):
    monkeypatch.setenv("NFOGEN_RADARR_URL", "http://radarr.local")
    monkeypatch.setenv("NFOGEN_RADARR_API_KEY", "y")
    monkeypatch.setattr(library_sync_runner, "RadarrClient", _GatedRadarr)
    _GatedRadarr.gate = threading.Event()

    results: list = []
    t = threading.Thread(target=lambda: results.append(library_sync_runner.sync_now()))
    t.start()
    time.sleep(0.1)  # laisse le thread entrer dans list_movie_files() et bloquer sur le gate

    second_result = library_sync_runner.sync_now()
    assert second_result is None  # verrou deja pris, jamais bloquant
    assert library_sync_runner.last_attempt().last_attempt_error == "Synchronisation déjà en cours."

    _GatedRadarr.gate.set()
    t.join(timeout=5)
    assert results[0] is not None  # le premier appel, lui, a bien fini par reussir


def test_start_syncs_immediately_then_periodically(monkeypatch):
    calls = []
    monkeypatch.setattr(library_sync_runner, "sync_now", lambda: calls.append(1) or None)

    library_sync_runner.start(interval_seconds=0.02)
    time.sleep(0.09)
    library_sync_runner.stop()

    assert len(calls) >= 2  # au moins l'appel immediat + un cycle periodique


def test_start_is_idempotent_while_already_running(monkeypatch):
    calls = []
    monkeypatch.setattr(library_sync_runner, "sync_now", lambda: calls.append(1) or None)

    library_sync_runner.start(interval_seconds=10)
    library_sync_runner.start(interval_seconds=10)  # ne relance pas un deuxieme thread
    time.sleep(0.05)
    library_sync_runner.stop()

    assert len(calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_library_sync_runner.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.library_sync_runner'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_library_sync_runner.py -v`
Expected: 7 PASS

- [ ] **Step 5: Ruff + commit**

```bash
ruff check nfogen/library_sync_runner.py tests/test_library_sync_runner.py
git add nfogen/library_sync_runner.py tests/test_library_sync_runner.py
git commit -m "feat: library_sync_runner -- synchro en tache de fond (intervalle + demarrage + manuel)"
```

---

## Task 3: Câbler dans `api.py` — remplacer l'ancien cache TTL, endpoints, déploiement

**Files:**
- Modify: `nfogen/api.py:57-69` (bloc d'imports optionnels)
- Modify: `nfogen/api.py:89-98` (constantes de config)
- Modify: `nfogen/api.py:690-696` (après `_require_gapscan_available`)
- Modify: `nfogen/api.py:950-1149` (suppression de l'ancien cache + nouvel endpoint + nouvel endpoint refresh)
- Modify: `tests/test_api.py` (suppression des tests de l'ancien mécanisme, ajout des nouveaux)
- Modify: `scripts/install.sh` (après la ligne `NFOGEN_GAPSCAN_RESULTS_FILE`)
- Modify: `GAPSCAN.md` (nouvelle section)

**Interfaces:**
- Consumes: `library_inventory_store.load()`/`is_configured()` (Task 1), `library_sync_runner.sync_now()`/`last_attempt()`/`start()` (Task 2).
- Produces: `GET /gapscan/library` (réponse enrichie de `synced_at`/`last_attempt_at`/`last_attempt_error`), `POST /gapscan/library/refresh` (nouveau).

- [ ] **Step 1: Ajouter les nouveaux modules à l'import optionnel**

Dans `nfogen/api.py`, le bloc `try: from . import (...)` (lignes 57-69) :

```python
try:
    from . import (
        commit_job_runner,
        gapscan,
        gapscan_config_store,
        gapscan_library,
        gapscan_runner,
        integrity_job_runner,
        library_inventory_store,
        library_sync_runner,
        seed_match_job_runner,
        tracker_profile,
        upload_history_store,
        upload_prep,
        upload_preview_job_runner,
    )
```

(uniquement l'ajout de `library_inventory_store,` et `library_sync_runner,`, en respectant l'ordre alphabétique déjà en place — reste du bloc inchangé)

- [ ] **Step 2: Nouvelle constante de config**

Toujours dans `nfogen/api.py`, près des autres constantes `NFOGEN_*` (lignes 89-98), ajouter :

```python
_LIBRARY_SYNC_INTERVAL_SECONDS = float(os.environ.get("NFOGEN_LIBRARY_SYNC_INTERVAL_SECONDS", "900"))
```

- [ ] **Step 3: Démarrage de la synchro au boot du service**

Juste après la définition de `_require_gapscan_available()` (ligne 696), ajouter :

```python
@app.on_event("startup")
def _start_library_sync() -> None:
    """Demarre la synchro en tache de fond de l'inventaire Bibliotheque
    UNIQUEMENT si NFOGEN_LIBRARY_INVENTORY_FILE est configuree -- sinon
    (deploiement qui n'a pas encore adopte cette option) rien ne change :
    GET /gapscan/library continue de fonctionner en direct, exactement
    comme avant (voir library_inventory_store.py, "opt-in, jamais
    bloquant"). Verifie empiriquement (2026-09-12) : TestClient(app) SANS
    `with` -- le patron utilise par toute la suite de tests existante --
    ne declenche PAS cet evenement, donc cet ajout n'affecte aucun test
    qui ne l'invoque pas explicitement."""
    if _GAPSCAN_AVAILABLE and library_inventory_store.is_configured():
        library_sync_runner.start(_LIBRARY_SYNC_INTERVAL_SECONDS)
```

- [ ] **Step 4: Supprimer l'ancien mécanisme de cache TTL/single-flight**

Supprimer entièrement, dans `nfogen/api.py`, le bloc de commentaires + constantes + fonction (lignes 950-1062, de `# Retour utilisateur, 2026-09-08 : "5 a 10 secondes"...` jusqu'à la fin de `_cached_library_items`) :

```python
# SUPPRIMER TOUT CE BLOC :
# _LIBRARY_CACHE_TTL_SECONDS = 30.0
# _library_cache: dict[...] = {}
# _library_fetch_lock = threading.Lock()
# _library_fetch_in_progress: dict[...] = {}
# def _cached_library_items(...): ...
```

- [ ] **Step 5: Remplacer le corps de `gapscan_library_endpoint` et ajouter `POST /gapscan/library/refresh`**

Remplacer l'implémentation de `gapscan_library_endpoint` (lignes 1065-1149) — la signature (paramètres `q`/`media_type`/.../`profile`) et la docstring gardent leur intention, seul le corps change :

```python
@app.get("/gapscan/library", dependencies=[Depends(require_token)])
def gapscan_library_endpoint(
    q: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    tracker_genre: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    added_since_days: Optional[float] = Query(None),
    processed: Optional[bool] = Query(None),
    sort: Optional[str] = Query(None),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    profile: str = Query("c411"),
) -> dict[str, Any]:
    """Inventaire local Radarr/Sonarr, lu depuis le cache persistant local
    (voir library_inventory_store.py/library_sync_runner.py, AUTOMATION.md
    sous-projet 8) -- ZERO appel Radarr/Sonarr en fonctionnement normal.
    Si le cache n'a encore jamais ete rempli (tout premier demarrage, ou
    NFOGEN_LIBRARY_INVENTORY_FILE non configuree) : un appel live
    exceptionnel amorce/remplace le cache pour cette requete. La reponse
    inclut `synced_at`/`last_attempt_at`/`last_attempt_error` pour afficher
    la fraicheur des donnees cote frontend. `q`/`media_type`/`genre`/
    `tracker_genre`/`status`/`added_since_days`/`processed`/`sort`/`order`/
    `page`/`page_size`/`profile` : voir docstring precedente, comportement
    de filtre/tri/pagination inchange."""
    _require_gapscan_available()
    cached = library_inventory_store.load()
    if cached is not None:
        items, synced_at = cached
    else:
        sonarr_config = gapscan_config_store.effective_sonarr()
        radarr_config = gapscan_config_store.effective_radarr()
        if sonarr_config is None and radarr_config is None:
            raise HTTPException(
                status_code=400,
                detail="Aucune instance Sonarr ni Radarr configuree "
                "(NFOGEN_SONARR_URL/_API_KEY et/ou NFOGEN_RADARR_URL/_API_KEY, ou PUT /gapscan/config).",
            )
        items = library_sync_runner.sync_now()
        if items is None:
            raise HTTPException(
                status_code=503,
                detail="Synchronisation de la Bibliothèque indisponible : "
                f"{library_sync_runner.last_attempt().last_attempt_error}",
            )
        synced_at = library_sync_runner.last_attempt().last_attempt_at

    # Calcule sur le resultat COMPLET (avant filtre q/pagination) : sinon un
    # filtre actif masquerait des saisons pourtant concernees par un pack
    # (retour utilisateur, 2026-09-08).
    season_packs = gapscan_library.detect_season_packs(items)

    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in i.title.lower()]
    if media_type is not None:
        items = [i for i in items if i.media_type == media_type]
    if genre is not None:
        items = [i for i in items if genre in i.genres]
    if tracker_genre is not None:
        items = [i for i in items if i.tracker_genre == tracker_genre]
    if status is not None:
        if status == "not_verified":
            items = [i for i in items if i.status is None]
        else:
            items = [i for i in items if i.status == status]
    if added_since_days is not None:
        cutoff = time.time() - added_since_days * 86400
        items = [i for i in items if i.added_at is not None and i.added_at >= cutoff]
    if processed is not None:
        items = [i for i in items if i.already_processed == processed]

    items = gapscan_library.sort_library_items(items, sort, order)

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    attempt = library_sync_runner.last_attempt()
    return {
        "items": [asdict(i) for i in page_items], "total": total,
        "season_packs": [asdict(p) for p in season_packs],
        "synced_at": synced_at,
        "last_attempt_at": attempt.last_attempt_at,
        "last_attempt_error": attempt.last_attempt_error,
    }


@app.post("/gapscan/library/refresh", dependencies=[Depends(require_token)])
def gapscan_library_refresh() -> dict[str, Any]:
    """Declenche une synchronisation immediate de l'inventaire Bibliotheque
    (bouton "Rafraichir" cote frontend) et attend sa fin -- un simple appel
    liste Radarr/Sonarr, pas un scan MediaInfo lourd (quelques secondes au
    plus). Voir library_sync_runner.sync_now()."""
    _require_gapscan_available()
    items = library_sync_runner.sync_now()
    attempt = library_sync_runner.last_attempt()
    if items is None:
        raise HTTPException(
            status_code=503,
            detail=attempt.last_attempt_error or "Synchronisation indisponible.",
        )
    return {"status": "ok", "synced_at": attempt.last_attempt_at, "total": len(items)}
```

- [ ] **Step 6: Supprimer les tests de l'ancien mécanisme, dans `tests/test_api.py`**

Supprimer entièrement les 4 tests et 2 classes suivants (ils vérifient un mécanisme qui n'existe plus) :
- `_CountingFakeGapscanRadarr` (classe)
- `test_gapscan_library_reuses_cached_result_within_ttl`
- `test_gapscan_library_refetches_after_ttl_expires`
- `test_gapscan_library_cache_invalidated_by_a_finished_scan`
- `_SlowCountingFakeGapscanRadarr` (classe)
- `test_gapscan_library_concurrent_requests_share_a_single_fetch`

- [ ] **Step 7: Ajouter les tests du nouveau mécanisme, dans `tests/test_api.py`**

```python
def test_gapscan_library_uses_persisted_cache_without_calling_radarr(reload_api, monkeypatch, tmp_path):
    """Le test le plus important de cette tache : une fois le cache
    rempli, AUCUN appel Radarr/Sonarr ne doit plus avoir lieu."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_LIBRARY_INVENTORY_FILE=str(tmp_path / "inv.json"),
    )

    class _ExplodingRadarr:
        def __init__(self, *a, **k):
            raise AssertionError("Radarr ne doit pas etre appele quand le cache est deja rempli")

    # Remplit le cache directement via le store (simule une synchro deja
    # passee), SANS jamais appeler RadarrClient.
    from nfogen.gapscan_library import LibraryItem
    from nfogen.quality import ReleaseQuality
    mod.library_inventory_store.save(
        [
            LibraryItem(
                media_type="movie", title="Matrix", year=1999, season_number=None,
                imdb_id="tt0133093", tvdb_id=None, tmdb_id="603", genres=[], added_at=None,
                local_quality=ReleaseQuality(raw="x"), radarr_movie_id=1, sonarr_series_id=None,
                already_processed=False, last_processed_at=None, key="k",
            )
        ],
        synced_at=1700000000.0,
    )
    monkeypatch.setattr(mod, "RadarrClient", _ExplodingRadarr)
    client = TestClient(mod.app)

    resp = client.get("/gapscan/library")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Matrix"
    assert body["synced_at"] == 1700000000.0


def test_gapscan_library_syncs_once_when_cache_is_empty(reload_api, monkeypatch, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_LIBRARY_INVENTORY_FILE=str(tmp_path / "inv.json"),
    )
    monkeypatch.setattr(mod, "RadarrClient", _FakeGapscanRadarr)
    client = TestClient(mod.app)

    resp = client.get("/gapscan/library")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["title"] == "Matrix"
    # La synchro a bien persiste le resultat -- une requete suivante n'aura
    # plus besoin de RadarrClient (couvert par le test precedent).
    assert mod.library_inventory_store.load() is not None


def test_gapscan_library_refresh_endpoint_triggers_a_sync(reload_api, monkeypatch, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_LIBRARY_INVENTORY_FILE=str(tmp_path / "inv.json"),
    )
    monkeypatch.setattr(mod, "RadarrClient", _FakeGapscanRadarr)
    client = TestClient(mod.app)

    resp = client.post("/gapscan/library/refresh")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["total"] == 1
    assert mod.library_inventory_store.load() is not None


def test_gapscan_library_refresh_endpoint_502_when_radarr_fails(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )

    class _FailingRadarr(_FakeGapscanRadarr):
        def list_movie_files(self):
            raise RadarrError("Radarr injoignable")

    monkeypatch.setattr(mod, "RadarrClient", _FailingRadarr)
    client = TestClient(mod.app)

    resp = client.post("/gapscan/library/refresh")

    assert resp.status_code == 503
    assert "Radarr injoignable" in resp.json()["detail"]
```

Les tests existants suivants restent inchangés et doivent continuer de passer TELS QUELS (aucun ne configure `NFOGEN_LIBRARY_INVENTORY_FILE`, donc le cache reste toujours vide → repli sur l'appel live à chaque requête, comportement identique à avant) : `test_gapscan_library_returns_items_from_radarr`, `test_gapscan_library_400_without_sonarr_or_radarr`, `test_gapscan_library_filters_by_media_type`, `test_gapscan_library_filters_by_text_search`, `test_gapscan_library_paginates`, `test_gapscan_library_status_is_not_verified_before_any_scan`, `test_gapscan_library_includes_known_tracker_status_after_a_scan`, `test_gapscan_library_filters_by_status_not_verified`, `test_gapscan_library_filters_by_status_after_a_scan`, `test_gapscan_library_filters_by_tracker_genre`, `test_gapscan_library_exposes_season_packs`, `test_gapscan_library_sort_by_title_ascending`, `test_gapscan_library_sort_by_title_descending`, `test_gapscan_library_sort_applies_before_pagination`.

- [ ] **Step 8: Défaut de déploiement — `scripts/install.sh`**

Juste après le bloc `NFOGEN_GAPSCAN_RESULTS_FILE` existant (voir contexte ci-dessus) :

```bash
# Cache local de l'inventaire Bibliotheque (voir GAPSCAN.md) : evite un
# appel Radarr/Sonarr a chaque chargement de /library, synchronise en
# tache de fond -- retour utilisateur, 2026-09-12.
if [[ -f "${ENV_FILE}" ]] && ! grep -q "^NFOGEN_LIBRARY_INVENTORY_FILE=" "${ENV_FILE}"; then
    echo "NFOGEN_LIBRARY_INVENTORY_FILE=${DATA_DIR}/library_inventory.json" >> "${ENV_FILE}"
fi
```

- [ ] **Step 9: Documentation — `GAPSCAN.md`**

Nouvelle section, à la suite de la section "Persistance des résultats + scan incrémental" existante :

```markdown
### Cache local de l'inventaire Bibliothèque (2026-09-12)

`GET /gapscan/library` ne fait plus d'appel Radarr/Sonarr à chaque
chargement de page — l'inventaire de base (titre/année/qualité/taille/
added_at) est synchronisé en tâche de fond (`nfogen/library_sync_runner.py`)
et persisté localement (`nfogen/library_inventory_store.py`, fichier
optionnel `NFOGEN_LIBRARY_INVENTORY_FILE`, ajouté par `scripts/install.sh`).
Trois déclencheurs pour cette synchro : au démarrage du service, à
intervalle fixe (`NFOGEN_LIBRARY_SYNC_INTERVAL_SECONDS`, défaut 900s/15min),
et via `POST /gapscan/library/refresh` (bouton "Rafraîchir" côté frontend).
Une synchro qui échoue (Radarr/Sonarr injoignables) ne touche jamais à la
copie précédente — la réponse de `GET /gapscan/library` inclut
`synced_at`/`last_attempt_at`/`last_attempt_error` pour connaître la
fraîcheur réelle des données affichées. Périmètre volontairement limité à
l'affichage : Préparer l'upload/Confirmer continuent d'aller chercher les
fichiers en direct, sans changement.
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k library`
Expected: PASS (tous les tests `*library*`, anciens et nouveaux)

Run: `pytest -q`
Expected: suite complète verte

- [ ] **Step 11: Ruff + commit**

```bash
ruff check nfogen/api.py tests/test_api.py
git add nfogen/api.py tests/test_api.py scripts/install.sh GAPSCAN.md
git commit -m "feat: GET /gapscan/library lit le cache local, ancien mecanisme TTL supprime"
```

---

## Task 4: Frontend — indicateur de synchro + bouton "Rafraîchir"

**Files:**
- Modify: `frontend/src/api/types.ts` (`LibraryResultsPage`)
- Modify: `frontend/src/api/client.ts` (nouvelle fonction `refreshLibrary`)
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Test: `frontend/src/pages/LibraryPage.test.tsx` (fichier existant, à étendre)

**Interfaces:**
- Consumes: `POST /gapscan/library/refresh`, `GET /gapscan/library` (champs `synced_at`/`last_attempt_at`/`last_attempt_error`, Task 3).
- Produces: rien de consommé par une tâche ultérieure — dernière tâche du plan.

- [ ] **Step 1: Étendre le type `LibraryResultsPage`**

Dans `frontend/src/api/types.ts` (ligne 301) :

```typescript
export interface LibraryResultsPage {
  items: LibraryItem[];
  total: number;
  season_packs: SeasonPackSuggestion[];
  synced_at: number | null;
  last_attempt_at: number | null;
  last_attempt_error: string | null;
}
```

- [ ] **Step 2: Ajouter `refreshLibrary()` dans `client.ts`**

Juste après la fonction `libraryResults` existante (ligne ~378) :

```typescript
/** POST /gapscan/library/refresh : declenche une synchronisation
 * immediate de l'inventaire Bibliotheque (bouton "Rafraichir"). */
export function refreshLibrary(): Promise<{ status: string; synced_at: number | null; total: number }> {
  return request<{ status: string; synced_at: number | null; total: number }>(
    "/gapscan/library/refresh",
    { method: "POST" },
  );
}
```

- [ ] **Step 3: Écrire le test du composant AVANT l'implémentation**

Dans `frontend/src/pages/LibraryPage.test.tsx`, ajouter :

```tsx
it("affiche la derniere synchro et rafraichit au clic", async () => {
  vi.mocked(libraryResults).mockResolvedValue({
    items: [], total: 0, season_packs: [],
    synced_at: Date.now() / 1000 - 120, last_attempt_at: Date.now() / 1000 - 120, last_attempt_error: null,
  });
  vi.mocked(refreshLibrary).mockResolvedValue({ status: "ok", synced_at: Date.now() / 1000, total: 0 });

  render(<LibraryPage />);

  expect(await screen.findByText(/Dernière synchro/i)).toBeInTheDocument();

  const button = screen.getByRole("button", { name: /Rafraîchir/i });
  await userEvent.click(button);

  expect(refreshLibrary).toHaveBeenCalledTimes(1);
});
```

(ajouter `refreshLibrary` aux imports mockés en haut du fichier, même patron que `libraryResults` déjà mocké)

- [ ] **Step 4: Run test to verify it fails**

Run: `npm --prefix frontend test -- LibraryPage`
Expected: FAIL (`refreshLibrary` non défini / bouton "Rafraîchir" introuvable)

- [ ] **Step 5: Implémenter dans `LibraryPage.tsx`**

Importer `refreshLibrary` (ligne 21, à côté de `libraryResults`). Ajouter un état :

```typescript
const [syncedAt, setSyncedAt] = useState<number | null>(null);
const [refreshing, setRefreshing] = useState(false);
```

Dans `load()`, après `setSeasonPacks(res.season_packs);` :

```typescript
setSyncedAt(res.synced_at);
```

Nouvelle fonction, à côté de `load()` :

```typescript
async function handleRefresh() {
  setRefreshing(true);
  try {
    await refreshLibrary();
    await load();
  } catch (e) {
    setError(e instanceof ApiError ? e.message : "Rafraîchissement impossible.");
  } finally {
    setRefreshing(false);
  }
}

function formatSyncedAt(ts: number | null): string {
  if (ts === null) return "jamais synchronisé";
  const minutes = Math.round((Date.now() / 1000 - ts) / 60);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  return `il y a ${Math.round(minutes / 60)} h`;
}
```

Dans le JSX, à côté du titre (ligne ~504, à l'intérieur du premier `<div>` du header) :

```tsx
<p className="text-xs text-ink-dim">Dernière synchro : {formatSyncedAt(syncedAt)}</p>
```

Et dans la barre de boutons (ligne ~510, avant le bouton d'export CSV existant) :

```tsx
<button
  type="button"
  onClick={handleRefresh}
  disabled={refreshing}
  className="rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink hover:bg-surface-hover disabled:opacity-50"
>
  {refreshing ? "Rafraîchissement…" : "Rafraîchir"}
</button>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm --prefix frontend test -- LibraryPage`
Expected: PASS

- [ ] **Step 7: Build + commit**

```bash
cd frontend && npm run build && cd ..
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat: indicateur de synchro + bouton Rafraichir sur la Bibliotheque"
```

---

## Self-Review

**Spec coverage :** persistance séparée (Task 1) ✅ ; trois déclencheurs unifiés dans `sync_now()` (Task 2) ✅ ; tolérance à la panne, ne jamais écraser une copie valide (Task 2, testé explicitement) ✅ ; premier démarrage → repli live exceptionnel (Task 3, `gapscan_library_endpoint`) ✅ ; indicateur de fraîcheur + bouton manuel (Task 4) ✅ ; périmètre limité à l'affichage — aucune tâche ne touche `upload_prep.py`/`file_staging.py` ✅.

**Placeholder scan :** aucun `TBD`/`TODO` ; chaque step contient du code réel exécutable, pas de description sans implémentation.

**Type consistency :** `sync_now() -> Optional[list[LibraryItem]]` (Task 2) utilisé identiquement dans `api.py` (Task 3, `items = library_sync_runner.sync_now()`) et dans les tests (Task 2 et Task 3). `SyncState.last_attempt_at`/`last_attempt_error` utilisés à l'identique dans `last_attempt()` (Task 2) et dans la réponse JSON de `gapscan_library_endpoint`/`gapscan_library_refresh` (Task 3). `library_inventory_store.save(items, synced_at)`/`load() -> Optional[tuple[list[LibraryItem], float]]` (Task 1) utilisés à l'identique dans `library_sync_runner.py` (Task 2) et `api.py` (Task 3).
