"""Tests de nfogen.tmdb_client (transport HTTP mocke, aucun reseau reel) --
enrichissement best-effort du template d'upload (Pays/Createur(s)/Note),
voir docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md."""
from __future__ import annotations

import httpx
import pytest

from nfogen.tmdb_client import TMDBClient, TMDBError


def _client(handler) -> TMDBClient:
    return TMDBClient(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


MOVIE_RESPONSE = {
    "production_countries": [{"name": "United States of America"}],
    "vote_average": 8.365,
    "created_by": [],
}

SERIES_RESPONSE = {
    "production_countries": [{"name": "United States of America"}],
    "vote_average": 8.4,
    "created_by": [{"name": "Tom Kapinos"}],
}


def test_get_movie_extra_parses_country_and_rating():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/movie/603"
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json=MOVIE_RESPONSE)

    client = _client(handler)
    extra = client.get_movie_extra(603)
    assert extra.country == "United States of America"
    assert extra.vote_average == 8.4  # arrondi a 1 decimale
    assert extra.creators == []


def test_get_series_extra_parses_creators():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/tv/63174"
        return httpx.Response(200, json=SERIES_RESPONSE)

    client = _client(handler)
    extra = client.get_series_extra(63174)
    assert extra.creators == ["Tom Kapinos"]
    assert extra.country == "United States of America"


def test_missing_production_countries_leaves_country_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"production_countries": [], "vote_average": 0})

    client = _client(handler)
    extra = client.get_movie_extra(1)
    assert extra.country is None
    assert extra.vote_average is None  # 0 traite comme "jamais note" -> absent


def test_http_error_raises_tmdb_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status_message": "Invalid API key"})

    client = _client(handler)
    with pytest.raises(TMDBError):
        client.get_movie_extra(1)


def test_network_error_raises_tmdb_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(TMDBError):
        client.get_series_extra(1)


def test_requires_api_key():
    with pytest.raises(TMDBError):
        TMDBClient(api_key="")


def test_get_movie_extra_fetches_french_overview_separately():
    """Retour reel de moderation C411 (2026-09-13) : "Le synopsis est en
    anglais" -- Radarr/Sonarr renvoient l'overview dans la langue de LEUR
    propre config metadata (souvent l'anglais par defaut), jamais controle
    par nfogen. TMDB, lui, sait renvoyer une version localisee via le
    parametre `language` -- un second appel dedie (`language=fr-FR`) recupere
    le synopsis francais, sans toucher au reste (pays/note/createurs)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if request.url.params.get("language") == "fr-FR":
            return httpx.Response(200, json={"overview": "Synopsis en français."})
        return httpx.Response(200, json=MOVIE_RESPONSE)

    client = _client(handler)
    extra = client.get_movie_extra(603)

    assert extra.overview_fr == "Synopsis en français."
    assert extra.country == "United States of America"  # inchange, vient du 1er appel
    assert len(calls) == 2


def test_get_series_extra_fetches_french_overview_separately():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("language") == "fr-FR":
            return httpx.Response(200, json={"overview": "Résumé en français."})
        return httpx.Response(200, json=SERIES_RESPONSE)

    client = _client(handler)
    extra = client.get_series_extra(63174)

    assert extra.overview_fr == "Résumé en français."
    assert extra.creators == ["Tom Kapinos"]  # inchange


def test_overview_fr_none_when_tmdb_has_no_french_overview():
    """TMDB renvoie parfois une chaine vide si aucune traduction francaise
    n'existe -- jamais une chaine vide affichee a la place d'un vrai
    synopsis, `None` pour laisser le repli existant (overview Radarr/Sonarr)
    prendre le relais (voir upload_prep.py)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("language") == "fr-FR":
            return httpx.Response(200, json={"overview": ""})
        return httpx.Response(200, json=MOVIE_RESPONSE)

    client = _client(handler)
    extra = client.get_movie_extra(603)

    assert extra.overview_fr is None
