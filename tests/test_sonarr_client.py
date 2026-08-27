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


def test_series_without_episode_files_produces_no_season():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=[])

    assert _client(handler).list_season_files() == []


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
