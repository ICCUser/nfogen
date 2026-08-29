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
from nfogen.radarr_client import RadarrMovieFile
from nfogen.sonarr_client import SonarrSeasonFile
from nfogen.torznab_client import TorznabRelease


@pytest.fixture(autouse=True)
def _reset_runner():
    """Etat en memoire du module : repart de zero a chaque test (meme
    convention que `reload_api` dans test_api.py)."""
    importlib.reload(gapscan_runner)
    yield
    importlib.reload(gapscan_runner)


def _movie(title: str = "Matrix") -> RadarrMovieFile:
    return RadarrMovieFile(movie_id=1, title=title, year=1999, imdb_id="tt0133093", tmdb_id=603)


def _season(title: str = "Severance", season_number: int = 1) -> SonarrSeasonFile:
    return SonarrSeasonFile(
        series_id=1, title=title, year=2020, tvdb_id=1, imdb_id=None,
        season_number=season_number, episode_file_count=1,
    )


@dataclass
class FakeC411:
    movie_results: list[TorznabRelease] = field(default_factory=list)
    tv_results: list[TorznabRelease] = field(default_factory=list)
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
    called: bool = False

    def list_movie_files(self):
        self.called = True
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return self.movies

    def close(self):
        self.closed = True


@dataclass
class FakeSonarr:
    seasons: list[SonarrSeasonFile]
    closed: bool = False
    called: bool = False

    def list_season_files(self):
        self.called = True
        return self.seasons

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


def test_persists_to_disk_before_the_state_becomes_visible_as_done(tmp_path, monkeypatch):
    """Course reelle trouvee en CI (2026-08-27) : si l'ecriture disque du
    persist se produit APRES le passage a l'etat 'done', un lecteur externe
    (ex. un redemarrage reel juste apres la fin d'un scan, ou -- comme en
    CI -- un `importlib.reload` en test) peut observer 'done' sans que le
    fichier existe encore : resultats perdus au redemarrage suivant malgre
    un scan reussi. save() doit toujours avoir termine AVANT que l'etat
    devienne visible comme 'done'."""
    monkeypatch.setenv("NFOGEN_GAPSCAN_RESULTS_FILE", str(tmp_path / "results.json"))
    importlib.reload(gapscan_runner)

    order: list[str] = []
    real_save = gapscan_runner.gapscan_results_store.save

    def spy_save(results):
        assert gapscan_runner.status()["state"] != "done"  # pas encore visible comme termine
        order.append("save")
        real_save(results)

    monkeypatch.setattr(gapscan_runner.gapscan_results_store, "save", spy_save)

    c411 = FakeC411(movie_results=[])
    radarr = FakeRadarr(movies=[_movie()])
    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()

    assert order == ["save"]


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


# --------------------------------------------------------------------------- #
# Persistance sur disque (survit a un redemarrage du processus) + mode
# incremental -- retour utilisateur, 2026-08-26 : "a chaque MAJ je vais
# devoir refaire un scan ? ... je vais pas tout rescanner c'est pas fou".
# --------------------------------------------------------------------------- #
def test_results_are_lost_on_reload_when_persistence_not_configured():
    """Comportement historique inchange par defaut : pas de fichier
    configure, rien ne survit a un 'redemarrage' (reload)."""
    c411 = FakeC411(movie_results=[])
    radarr = FakeRadarr(movies=[_movie()])
    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()
    assert len(gapscan_runner.results()) == 1

    importlib.reload(gapscan_runner)

    assert gapscan_runner.results() == []
    assert gapscan_runner.status()["state"] == "idle"


def test_results_persist_across_a_process_restart_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_RESULTS_FILE", str(tmp_path / "results.json"))
    importlib.reload(gapscan_runner)  # applique le nouvel env var (charge au module-level)

    c411 = FakeC411(movie_results=[])
    radarr = FakeRadarr(movies=[_movie()])
    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()
    assert len(gapscan_runner.results()) == 1

    importlib.reload(gapscan_runner)  # simule un redemarrage du processus (ex. update.sh)

    results = gapscan_runner.results()
    assert len(results) == 1
    assert results[0].media_type == "movie"
    status = gapscan_runner.status()
    assert status["state"] == "done"  # pas "idle" : un scan est bien deja disponible
    assert status["finished_at"] is not None


def test_start_with_incremental_reuses_covered_results_from_last_scan():
    """Un titre COVERED au dernier scan, dont la qualite locale n'a pas
    change, n'est pas reinterroge sur C411 -- coeur du correctif."""
    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
    )
    c411_first = FakeC411(
        movie_results=[
            TorznabRelease(title="Matrix", guid="g", link="https://c411.org/x", imdb_id="tt0133093")
        ]
    )
    gapscan_runner.start(c411_first, radarr=FakeRadarr(movies=[movie]))
    _wait_until_not_running()
    assert gapscan_runner.results()[0].status.value == "covered"

    # Si reinterroge a tort, ce second client renverrait ABSENT (revelateur).
    c411_second = FakeC411(movie_results=[])
    gapscan_runner.start(c411_second, radarr=FakeRadarr(movies=[movie]), incremental=True)
    _wait_until_not_running()

    assert gapscan_runner.results()[0].status.value == "covered"


def test_start_with_only_movies_skips_sonarr_entirely():
    """`only=` (retour utilisateur, 2026-08-27) : permet de scanner Radarr et
    Sonarr separement, meme quand les deux sont configures."""
    radarr = FakeRadarr(movies=[_movie()])
    sonarr = FakeSonarr(seasons=[])

    gapscan_runner.start(FakeC411(), radarr=radarr, sonarr=sonarr, only="movies")
    _wait_until_not_running()

    assert radarr.called is True
    assert sonarr.called is False
    assert sonarr.closed is True  # ferme quand meme, meme si jamais interroge


def test_start_with_only_series_skips_radarr_entirely():
    radarr = FakeRadarr(movies=[_movie()])
    sonarr = FakeSonarr(seasons=[])

    gapscan_runner.start(FakeC411(), radarr=radarr, sonarr=sonarr, only="series")
    _wait_until_not_running()

    assert radarr.called is False
    assert sonarr.called is True


def test_start_without_incremental_rescans_everything():
    """Vaut confirmation que `incremental` est bien un opt-in explicite (le
    scan complet, par defaut, reste le comportement historique)."""
    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
    )
    c411_first = FakeC411(
        movie_results=[
            TorznabRelease(title="Matrix", guid="g", link="https://c411.org/x", imdb_id="tt0133093")
        ]
    )
    gapscan_runner.start(c411_first, radarr=FakeRadarr(movies=[movie]))
    _wait_until_not_running()
    assert gapscan_runner.results()[0].status.value == "covered"

    c411_second = FakeC411(movie_results=[])
    gapscan_runner.start(c411_second, radarr=FakeRadarr(movies=[movie]))  # incremental=False (defaut)
    _wait_until_not_running()

    assert gapscan_runner.results()[0].status.value == "absent"


def test_start_with_incremental_and_max_age_reverifies_a_stale_covered_result():
    """`max_age_seconds` (retour utilisateur, 2026-08-27 : C411 retire et
    ajoute des torrents assez souvent) atteint via start() -- bout en bout."""
    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
    )
    c411_first = FakeC411(
        movie_results=[
            TorznabRelease(title="Matrix", guid="g", link="https://c411.org/x", imdb_id="tt0133093")
        ]
    )
    gapscan_runner.start(c411_first, radarr=FakeRadarr(movies=[movie]))
    _wait_until_not_running()
    assert gapscan_runner.results()[0].status.value == "covered"

    c411_second = FakeC411(movie_results=[])
    gapscan_runner.start(
        c411_second, radarr=FakeRadarr(movies=[movie]), incremental=True, max_age_seconds=0.0
    )
    _wait_until_not_running()

    assert gapscan_runner.results()[0].status.value == "absent"  # reverifie, plus repris tel quel


def test_start_passes_path_mappings_through(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        remote_path="/remote/Matrix.mkv",
    )
    c411 = FakeC411(movie_results=[])

    gapscan_runner.start(
        c411, radarr=FakeRadarr(movies=[movie]),
        radarr_path_mappings={"/remote": str(tmp_path)},
    )
    _wait_until_not_running()

    assert gapscan_runner.results()[0].path_resolved is True


def test_results_filterable_by_media_type():
    c411 = FakeC411(movie_results=[], tv_results=[])
    radarr = FakeRadarr(movies=[_movie("A")])
    sonarr = FakeSonarr(seasons=[_season("B")])

    gapscan_runner.start(c411, radarr=radarr, sonarr=sonarr)
    _wait_until_not_running()

    movies = gapscan_runner.results(media_type_filter="movie")
    assert len(movies) == 1 and movies[0].title == "A"
    series = gapscan_runner.results(media_type_filter="series")
    assert len(series) == 1 and series[0].title == "B"


def test_results_filterable_by_genre():
    anime_release = TorznabRelease(title="A", guid="A", link="https://c411.org/x", category="2060")
    c411 = FakeC411(movie_results=[anime_release])
    radarr = FakeRadarr(movies=[_movie("A")])

    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()

    assert len(gapscan_runner.results(genre_filter="anime")) == 1
    assert gapscan_runner.results(genre_filter="documentaire") == []


def test_results_genre_filter_uses_the_given_profile(monkeypatch):
    from nfogen import tracker_profile

    monkeypatch.setattr(
        tracker_profile, "torznab_categories",
        lambda profile: {"anime": ["9999"]} if profile == "other" else {},
    )
    release = TorznabRelease(title="A", guid="A", link="https://c411.org/x", category="9999")
    c411 = FakeC411(movie_results=[release])
    radarr = FakeRadarr(movies=[_movie("A")])

    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()

    assert len(gapscan_runner.results(genre_filter="anime", profile="other")) == 1
    assert gapscan_runner.results(genre_filter="anime", profile="c411") == []
