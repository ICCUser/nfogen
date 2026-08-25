"""Tests de nfogen.gapscan_runner (execution en tache de fond de GapScan).

Clients doubles de test (pas de reseau reel) : seule l'orchestration
tache-de-fond/etat est visee ici -- `test_gapscan.py` couvre deja la
logique de scan elle-meme.
"""
from __future__ import annotations

import importlib
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import pytest

from nfogen import gapscan_runner
from nfogen.c411_client import C411Release
from nfogen.radarr_client import RadarrMovieFile


@pytest.fixture(autouse=True)
def _reset_runner():
    """Etat en memoire du module : repart de zero a chaque test (meme
    convention que `reload_api` dans test_api.py)."""
    importlib.reload(gapscan_runner)
    yield
    importlib.reload(gapscan_runner)


def _movie(title: str = "Matrix") -> RadarrMovieFile:
    return RadarrMovieFile(movie_id=1, title=title, year=1999, imdb_id="tt0133093", tmdb_id=603)


@dataclass
class FakeC411:
    movie_results: list[C411Release] = field(default_factory=list)
    tv_results: list[C411Release] = field(default_factory=list)
    closed: bool = False

    def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
        return self.movie_results

    def search_tv(self, query=None, imdb_id=None, tmdb_id=None, season=None, ep=None):
        return self.tv_results

    def close(self):
        self.closed = True


@dataclass
class FakeRadarr:
    movies: list[RadarrMovieFile]
    closed: bool = False
    gate: Optional[threading.Event] = None  # si pose, bloque jusqu'au signal (test de concurrence)

    def list_movie_files(self):
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return self.movies

    def close(self):
        self.closed = True


def _wait_until_not_running(timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while gapscan_runner.status()["state"] == "running":
        if time.monotonic() > deadline:
            raise TimeoutError("le scan de test ne s'est jamais termine")
        time.sleep(0.01)


# --------------------------------------------------------------------------- #
# Etat initial / cycle de vie normal
# --------------------------------------------------------------------------- #
def test_initial_state_is_idle():
    status = gapscan_runner.status()
    assert status["state"] == "idle"
    assert status["total"] == 0
    assert gapscan_runner.results() == []


def test_start_runs_scan_and_reports_done_with_results():
    c411 = FakeC411(movie_results=[])
    radarr = FakeRadarr(movies=[_movie()])

    started = gapscan_runner.start(c411, radarr=radarr)
    assert started is True
    _wait_until_not_running()

    status = gapscan_runner.status()
    assert status["state"] == "done"
    assert status["total"] == 1
    assert status["processed"] == 1
    assert status["started_at"] is not None
    assert status["finished_at"] is not None

    results = gapscan_runner.results()
    assert len(results) == 1
    assert results[0].media_type == "movie"


def test_start_closes_clients_after_completion():
    c411 = FakeC411()
    radarr = FakeRadarr(movies=[_movie()])

    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()

    assert c411.closed is True
    assert radarr.closed is True


def test_results_filterable_by_status():
    c411 = FakeC411(movie_results=[])  # aucun match -> ABSENT pour tous
    radarr = FakeRadarr(movies=[_movie("A"), _movie("B")])

    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()

    assert len(gapscan_runner.results(status_filter="absent")) == 2
    assert gapscan_runner.results(status_filter="covered") == []


# --------------------------------------------------------------------------- #
# Un seul scan a la fois
# --------------------------------------------------------------------------- #
def test_start_refuses_a_second_scan_while_one_is_running():
    gate = threading.Event()
    c411 = FakeC411()
    radarr = FakeRadarr(movies=[_movie()], gate=gate)

    first = gapscan_runner.start(c411, radarr=radarr)
    assert first is True
    assert gapscan_runner.status()["state"] == "running"

    second = gapscan_runner.start(FakeC411(), radarr=FakeRadarr(movies=[_movie()]))
    assert second is False  # refuse : un scan est deja en cours

    gate.set()  # laisse le premier scan se terminer, sinon le thread reste accroche
    _wait_until_not_running()


# --------------------------------------------------------------------------- #
# Erreurs (client injoignable, etc.)
# --------------------------------------------------------------------------- #
def test_scan_error_is_reported_in_status_not_raised():
    class BrokenRadarr:
        def list_movie_files(self):
            raise RuntimeError("Radarr injoignable")

        def close(self):
            pass

    gapscan_runner.start(FakeC411(), radarr=BrokenRadarr())
    _wait_until_not_running()

    status = gapscan_runner.status()
    assert status["state"] == "error"
    assert "Radarr injoignable" in status["error"]
