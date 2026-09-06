"""Tests de nfogen.sonarr_client (transport HTTP mocke, aucun reseau reel)."""
from __future__ import annotations

import httpx
import pytest

from nfogen.sonarr_client import SonarrClient, SonarrError

SERIES = [{"id": 1, "title": "Breaking Bad", "year": 2008, "tvdbId": 81189, "imdbId": "tt0903747"}]

EPISODE_FILES = [
    {
        "seasonNumber": 1,
        "sceneName": "Breaking.Bad.S01.MULTI.VFF.2160p.WEBRip.EAC3.5.1.x265-SQUEEZE",
        "quality": {"quality": {"name": "WEBRip-2160p", "resolution": 2160}},
        "languages": [{"name": "French"}],
    },
    {
        "seasonNumber": 1,
        "sceneName": "Breaking.Bad.S01.MULTI.VFF.1080p.WEBRip.EAC3.5.1.x265-SQUEEZE",
        "quality": {"quality": {"name": "WEBRip-1080p", "resolution": 1080}},
        "languages": [{"name": "French"}],
    },
    {
        "seasonNumber": 2,
        "sceneName": "Breaking.Bad.S02.MULTI.VFF.1080p.WEBRip.EAC3.5.1.x265-SQUEEZE",
        "quality": {"quality": {"name": "WEBRip-1080p", "resolution": 1080}},
        "languages": [{"name": "French"}],
    },
]


def _client(handler) -> SonarrClient:
    return SonarrClient(
        base_url="http://sonarr.local:8989",
        api_key="sonarr-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_list_season_files_aggregates_by_season_and_keeps_best_resolution():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "sonarr-key"
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        assert request.url.path == "/api/v3/episodefile"
        assert request.url.params["seriesId"] == "1"
        return httpx.Response(200, json=EPISODE_FILES)

    seasons = _client(handler).list_season_files()
    assert len(seasons) == 2  # une entree par saison, pas par episode

    season1 = next(s for s in seasons if s.season_number == 1)
    assert season1.episode_file_count == 2
    assert season1.best_resolution == 2160  # le meilleur des deux fichiers de la saison
    assert season1.imdb_id == "tt0903747"

    season2 = next(s for s in seasons if s.season_number == 2)
    assert season2.episode_file_count == 1
    assert season2.best_resolution == 1080


def test_list_season_files_exposes_tmdb_id():
    """Sonarr identifie une serie par TVDB, mais expose AUSSI un `tmdbId`
    (cross-reference qu'il maintient lui-meme) -- confirme en conditions
    reelles le 2026-09-06 (retour utilisateur : la fiche Lucifer de son
    Sonarr contient bien `"tmdbId": 63174` a cote de `"tvdbId": 295685`).
    Jamais lu jusqu'ici, a tort : permet la meme verification anti-doublon
    C411 (TMDB-only) que pour un film, voir gapscan.py:scan_series_season."""
    series_with_tmdb = [{**SERIES[0], "tmdbId": 63174}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=series_with_tmdb)
        return httpx.Response(200, json=EPISODE_FILES)

    seasons = _client(handler).list_season_files()
    assert all(s.tmdb_id == 63174 for s in seasons)


def test_list_season_files_tmdb_id_none_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)  # SERIES n'a pas de tmdbId
        return httpx.Response(200, json=EPISODE_FILES)

    seasons = _client(handler).list_season_files()
    assert all(s.tmdb_id is None for s in seasons)


def test_season_zero_specials_are_excluded():
    """Incident reel (retour utilisateur) : 'Misfits S00' remontait dans les
    resultats GapScan. La saison 0 est la convention Sonarr pour les
    'Specials' (extras, bonus, hors-serie) -- pas une vraie saison
    diffusee, elle ne correspond a aucune convention de pack C411 standard
    et n'a rien a faire dans une comparaison de bibliotheque."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(
            200,
            json=[
                {
                    "seasonNumber": 0,
                    "sceneName": "Breaking.Bad.S00.Special.1080p.WEB-TEAM",
                    "quality": {"quality": {"name": "WEB-1080p", "resolution": 1080}},
                    "languages": [{"name": "French"}],
                },
                *EPISODE_FILES,
            ],
        )

    seasons = _client(handler).list_season_files()

    assert 0 not in {s.season_number for s in seasons}
    assert len(seasons) == 2  # S01/S02 uniquement, cf. test precedent


def test_list_season_files_exposes_alternate_titles():
    """C411 liste parfois une serie sous son titre de diffusion FR,
    different de l'original (ex. "White Collar" -> "FBI, duo tres special")
    -- utilise en repli par gapscan.py (retour utilisateur, 2026-08-27)."""
    series_with_alt = [
        {
            **SERIES[0],
            "alternateTitles": [{"title": "FBI, duo tres special"}, {"title": ""}, {"sceneOrigin": "x"}],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=series_with_alt)
        return httpx.Response(200, json=EPISODE_FILES)

    seasons = _client(handler).list_season_files()
    assert seasons[0].alternate_titles == ["FBI, duo tres special"]


def test_list_season_files_exposes_remote_paths_for_every_episode_in_the_season():
    files_with_paths = [
        {**EPISODE_FILES[0], "path": "/data/tv/Breaking Bad/Season 01/E01.mkv"},
        {**EPISODE_FILES[1], "path": "/data/tv/Breaking Bad/Season 01/E02.mkv"},
        {**EPISODE_FILES[2], "path": "/data/tv/Breaking Bad/Season 02/E01.mkv"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=files_with_paths)

    seasons = _client(handler).list_season_files()

    season1 = next(s for s in seasons if s.season_number == 1)
    assert season1.remote_paths == [
        "/data/tv/Breaking Bad/Season 01/E01.mkv",
        "/data/tv/Breaking Bad/Season 01/E02.mkv",
    ]
    season2 = next(s for s in seasons if s.season_number == 2)
    assert season2.remote_paths == ["/data/tv/Breaking Bad/Season 02/E01.mkv"]


def test_list_season_files_remote_paths_empty_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=EPISODE_FILES)  # pas de cle "path"

    seasons = _client(handler).list_season_files()
    assert seasons[0].remote_paths == []


def test_series_without_episode_files_produces_no_season():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=[])

    assert _client(handler).list_season_files() == []


def test_list_season_files_extracts_genres_from_series():
    """Le genre est un champ de la SERIE (pas du fichier episode) -- chaque
    saison de cette serie doit le recevoir."""
    series_with_genres = [{**SERIES[0], "genres": ["Drama"]}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=series_with_genres)
        return httpx.Response(200, json=EPISODE_FILES)

    seasons = _client(handler).list_season_files()
    assert all(s.genres == ["Drama"] for s in seasons)


def test_list_season_files_defaults_genres_to_empty_list_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)  # pas de cle "genres"
        return httpx.Response(200, json=EPISODE_FILES)

    seasons = _client(handler).list_season_files()
    assert seasons[0].genres == []


def test_list_season_files_added_at_uses_max_episode_date_in_that_season():
    """added_at d'une saison = la PLUS RECENTE dateAdded parmi SES fichiers
    episode -- jamais la date d'ajout de la serie entiere, qui ne
    distinguerait pas les saisons."""
    import datetime

    files_with_dates = [
        {**EPISODE_FILES[0], "dateAdded": "2024-01-01T00:00:00Z"},  # saison 1
        {**EPISODE_FILES[1], "dateAdded": "2024-06-01T00:00:00Z"},  # saison 1, plus recent
        {**EPISODE_FILES[2], "dateAdded": "2024-03-01T00:00:00Z"},  # saison 2
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=files_with_dates)

    seasons = _client(handler).list_season_files()

    season1 = next(s for s in seasons if s.season_number == 1)
    expected_season1 = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc).timestamp()
    assert season1.added_at == expected_season1

    season2 = next(s for s in seasons if s.season_number == 2)
    expected_season2 = datetime.datetime(2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp()
    assert season2.added_at == expected_season2


def test_list_season_files_added_at_none_when_no_episode_has_a_date():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=EPISODE_FILES)  # pas de cle "dateAdded"

    seasons = _client(handler).list_season_files()
    assert all(s.added_at is None for s in seasons)


def test_get_series_details_parses_overview_poster_genres():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/series/99"
        return httpx.Response(
            200,
            json={
                "id": 99,
                "overview": "Walter White, professeur de chimie...",
                "genres": ["Drama", "Crime"],
                "images": [
                    {"coverType": "banner", "remoteUrl": "https://image.tmdb.org/banner.jpg"},
                    {"coverType": "poster", "remoteUrl": "https://image.tmdb.org/poster.jpg"},
                ],
            },
        )

    details = _client(handler).get_series_details(99)

    assert details.overview == "Walter White, professeur de chimie..."
    assert details.genres == ["Drama", "Crime"]
    assert details.poster_url == "https://image.tmdb.org/poster.jpg"
    assert details.directors == []
    assert details.cast == []


def test_get_series_details_degrades_gracefully_when_fields_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 99})

    details = _client(handler).get_series_details(99)

    assert details.overview == ""
    assert details.poster_url is None
    assert details.genres == []


def test_requires_base_url_and_api_key():
    with pytest.raises(SonarrError):
        SonarrClient(base_url="", api_key="x")
    with pytest.raises(SonarrError):
        SonarrClient(base_url="http://x", api_key="")


def test_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(SonarrError, match="echoue"):
        _client(handler).list_series()
