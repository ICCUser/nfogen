"""Tests de nfogen.radarr_client (transport HTTP mocke, aucun reseau reel)."""
from __future__ import annotations

import httpx
import pytest

from nfogen.radarr_client import RadarrClient, RadarrError

MOVIES = [
    {
        "id": 1,
        "title": "Matrix",
        "year": 1999,
        "imdbId": "tt0133093",
        "tmdbId": 603,
        "hasFile": True,
        "movieFile": {
            "sceneName": "Matrix.1999.MULTI.VFF.2160p.BluRay.4KLight.HDR.DTS.5.1.x265-QTZ",
            "quality": {"quality": {"name": "Bluray-2160p", "resolution": 2160}},
            "languages": [{"name": "French"}],
        },
    },
    {
        "id": 2,
        "title": "Not Downloaded Yet",
        "year": 2024,
        "imdbId": "tt9999999",
        "tmdbId": 999,
        "hasFile": False,
        "movieFile": None,
    },
]


def _client(handler) -> RadarrClient:
    return RadarrClient(
        base_url="http://radarr.local:7878",
        api_key="radarr-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_list_movie_files_skips_movies_without_a_file():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "radarr-key"
        assert request.url.path == "/api/v3/movie"
        return httpx.Response(200, json=MOVIES)

    movies = _client(handler).list_movie_files()
    assert len(movies) == 1
    assert movies[0].title == "Matrix"
    assert movies[0].best_resolution == 2160
    assert movies[0].language_names == ["French"]


def test_requires_base_url_and_api_key():
    with pytest.raises(RadarrError):
        RadarrClient(base_url="", api_key="x")
    with pytest.raises(RadarrError):
        RadarrClient(base_url="http://x", api_key="")


def test_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(RadarrError, match="echoue"):
        _client(handler).list_movies()
