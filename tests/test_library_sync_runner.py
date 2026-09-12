"""Tests de nfogen.library_sync_runner (synchronisation en tache de fond
de l'inventaire Bibliotheque -- voir docs/superpowers/specs/
2026-09-12-library-inventory-cache-design.md)."""
from __future__ import annotations

import threading
import time

import pytest

from nfogen import library_inventory_store, library_sync_runner
from nfogen.gapscan_library import LibraryItem
from nfogen.quality import ReleaseQuality
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
        local_quality=ReleaseQuality(raw="x"),
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
