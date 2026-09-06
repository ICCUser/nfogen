"""Tests de nfogen.gapscan_library (AUTOMATION.md, sous-projet 8) --
inventaire local, ZERO appel tracker."""
from __future__ import annotations

import pytest

from nfogen import gapscan_library, upload_history_store
from nfogen.gapscan import GapResult, GapStatus, movie_key, series_key
from nfogen.quality import ReleaseQuality
from nfogen.radarr_client import RadarrMovieFile
from nfogen.sonarr_client import SonarrSeasonFile


class _FakeRadarr:
    def __init__(self, movies):
        self._movies = movies
        self.list_movie_files_called = 0

    def list_movie_files(self):
        self.list_movie_files_called += 1
        return self._movies


class _FakeSonarr:
    def __init__(self, seasons):
        self._seasons = seasons

    def list_season_files(self):
        return self._seasons


@pytest.fixture(autouse=True)
def history_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))


def test_list_library_never_touches_c411():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    radarr = _FakeRadarr([movie])
    items = gapscan_library.list_library(radarr=radarr, sonarr=None)
    assert len(items) == 1
    assert radarr.list_movie_files_called == 1


def test_list_library_builds_movie_item_with_selection_key():
    movie = RadarrMovieFile(
        movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1,
        genres=["Action"],
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    item = items[0]
    assert item.media_type == "movie"
    assert item.title == "Movie"
    assert item.genres == ["Action"]
    assert item.radarr_movie_id == 1
    assert item.key == upload_history_store.key_str(movie_key("tt001", "1", "Movie", 2020))


def test_list_library_marks_already_processed_movie():
    movie = RadarrMovieFile(movie_id=42, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    upload_history_store.record(
        upload_history_store.processed_key("movie", 42, None), kind="committed", release_name="r",
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].already_processed is True
    assert items[0].last_processed_at is not None


def test_list_library_marks_series_season_not_processed_by_default():
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    items = gapscan_library.list_library(radarr=None, sonarr=_FakeSonarr([season]))
    assert items[0].already_processed is False
    assert items[0].last_processed_at is None
    assert items[0].key == upload_history_store.key_str(series_key(99, None, "Show", 1))


def test_list_library_exposes_tmdb_id_for_series():
    """Sonarr expose un `tmdbId` par cross-reference (confirme en
    conditions reelles, 2026-09-06) : `tmdb_id=None` etait cable en dur
    ici a tort pour toute serie."""
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10, tmdb_id=63174,
    )
    items = gapscan_library.list_library(radarr=None, sonarr=_FakeSonarr([season]))
    assert items[0].tmdb_id == "63174"


def test_list_library_combines_movies_and_series():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=_FakeSonarr([season]))
    assert len(items) == 2
    assert {i.media_type for i in items} == {"movie", "series"}


def test_list_library_empty_without_any_client():
    assert gapscan_library.list_library(radarr=None, sonarr=None) == []


# --------------------------------------------------------------------------- #
# Fusion Bibliotheque/Scan (AUTOMATION.md, sous-projet 8 -- retour utilisateur
# 2026-09-06 : les deux pages faisaient doublon) -- previous_results enrichit
# chaque item du statut tracker DEJA CONNU, sans jamais reinterroger C411 ici.
# --------------------------------------------------------------------------- #
def test_list_library_enriches_movie_with_known_tracker_status():
    movie = RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)
    previous = GapResult(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt0133093", tmdb_id="603", tvdb_id=None, status=GapStatus.ABSENT,
        local_quality=ReleaseQuality(raw=""), checked_at=1700000000.0,
        has_freeleech_alternative=True, has_double_upload_window=False,
        local_paths=["/media/matrix.mkv"], path_resolved=True,
    )

    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].status == "absent"
    assert items[0].checked_at == 1700000000.0
    assert items[0].has_freeleech_alternative is True
    assert items[0].local_paths == ["/media/matrix.mkv"]
    assert items[0].path_resolved is True


def test_list_library_status_is_none_when_never_scanned():
    movie = RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].status is None
    assert items[0].checked_at is None
    assert items[0].has_freeleech_alternative is False
    assert items[0].local_paths == []
    assert items[0].path_resolved is False


def test_list_library_does_not_match_previous_result_of_a_different_title():
    movie = RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)
    previous = GapResult(
        media_type="movie", title="Inception", year=2010, season_number=None,
        imdb_id="tt1375666", tmdb_id="27205", tvdb_id=None, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(raw=""),
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )
    assert items[0].status is None


def test_list_library_enriches_series_season_with_known_tracker_status():
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    previous = GapResult(
        media_type="series", title="Show", year=2019, season_number=1,
        imdb_id=None, tmdb_id=None, tvdb_id=99, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(raw=""),
    )
    items = gapscan_library.list_library(
        radarr=None, sonarr=_FakeSonarr([season]), previous_results=[previous],
    )
    assert items[0].status == "covered"


def test_list_library_computes_tracker_genre_from_matched_result(monkeypatch):
    """`tracker_genre` (categorie C411 du match trouve) est DISTINCT de
    `genres` (Radarr/Sonarr) -- les deux classifications restent
    independantes (voir la spec du sous-projet 8)."""
    from nfogen.torznab_client import TorznabRelease

    movie = RadarrMovieFile(movie_id=1, title="Naruto", year=2002, imdb_id="tt0409591", tmdb_id=46260)
    previous = GapResult(
        media_type="movie", title="Naruto", year=2002, season_number=None,
        imdb_id="tt0409591", tmdb_id="46260", tvdb_id=None, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(raw=""),
        c411_matches=[
            TorznabRelease(title="Naruto", guid="g", link="https://c411.org/x", category="anime-movie"),
        ],
    )
    monkeypatch.setattr(
        "nfogen.tracker_profile.torznab_categories",
        lambda profile: {"anime": ["anime-movie"], "documentaire": []},
    )

    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous], profile="c411",
    )

    assert items[0].tracker_genre == "anime"
