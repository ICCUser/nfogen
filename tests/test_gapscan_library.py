"""Tests de nfogen.gapscan_library (AUTOMATION.md, sous-projet 8) --
inventaire local, ZERO appel tracker."""
from __future__ import annotations

import pytest

from nfogen import gapscan_library, upload_history_store
from nfogen.gapscan import movie_key, series_key
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
