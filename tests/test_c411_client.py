"""Tests de nfogen.c411_client.

Les fixtures `tests/fixtures/c411_*.xml` sont des reponses Torznab reelles
de C411 (capturees le 2026-08-25 avec le scope "Torznab/RSS (lecture)"),
tronquees a 3 items et avec la cle API redigee (`apikey=FAKE_KEY`).
Aucun appel reseau reel dans ces tests.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from nfogen.c411_client import C411Client, C411Error, parse_torznab_response

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Parsing pur (pas de reseau)
# --------------------------------------------------------------------------- #
def test_parse_movie_search_fixture():
    releases = parse_torznab_response(_read("c411_movie_search.xml"))
    assert len(releases) == 3
    first = releases[0]
    assert first.title.startswith("Matrix.COLLECTION")
    assert first.category == "2030"
    assert first.seeders == 147
    assert first.download_volume_factor == 1.0
    assert first.upload_volume_factor == 1.0


def test_parse_movie_search_extracts_ids_when_present():
    releases = parse_torznab_response(_read("c411_movie_search.xml"))
    resurrections = next(r for r in releases if "Resurrections" in r.title)
    assert resurrections.imdb_id == "tt10838180"
    assert resurrections.tmdb_id == "624860"


def test_parse_movie_search_ids_absent_is_not_an_error():
    releases = parse_torznab_response(_read("c411_movie_search.xml"))
    collection = next(r for r in releases if "COLLECTION" in r.title)
    assert collection.imdb_id is None
    assert collection.tmdb_id is None


def test_release_quality_is_derived_from_title():
    releases = parse_torznab_response(_read("c411_movie_search.xml"))
    matrix_1999 = next(r for r in releases if r.title.startswith("Matrix.1999"))
    assert matrix_1999.quality.resolution == 2160
    assert matrix_1999.quality.source == "BLURAY"
    assert matrix_1999.quality.languages == ["VFF"]


def test_parse_tvsearch_fixture():
    releases = parse_torznab_response(_read("c411_tvsearch.xml"))
    assert len(releases) == 3
    assert all(r.category == "5000" for r in releases)


def test_freeleech_flags_default_to_normal():
    releases = parse_torznab_response(_read("c411_movie_search.xml"))
    assert all(not r.is_freeleech and not r.is_half_leech and not r.is_double_upload for r in releases)


def test_parse_torznab_response_rejects_invalid_xml():
    with pytest.raises(C411Error, match="illisible"):
        parse_torznab_response("<not-xml")


def test_parse_torznab_response_empty_channel_returns_empty_list():
    header = _read("c411_movie_search.xml").split("<item>")[0]
    assert parse_torznab_response(header + "</channel></rss>") == []


# --------------------------------------------------------------------------- #
# Client HTTP (transport mocke, aucun reseau)
# --------------------------------------------------------------------------- #
def _client_with_fixture(fixture_name: str, expected_params: dict[str, str] | None = None) -> C411Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if expected_params is not None:
            for key, value in expected_params.items():
                assert request.url.params.get(key) == value
        assert request.url.params.get("apikey") == "test-key"
        return httpx.Response(200, text=_read(fixture_name))

    transport = httpx.MockTransport(handler)
    return C411Client(api_key="test-key", http_client=httpx.Client(transport=transport))


def test_search_movie_passes_ids_and_parses_results():
    client = _client_with_fixture(
        "c411_movie_search.xml", expected_params={"t": "movie", "imdbid": "tt0133093"}
    )
    releases = client.search_movie(imdb_id="tt0133093")
    assert len(releases) == 3


def test_search_tv_passes_season():
    client = _client_with_fixture("c411_tvsearch.xml", expected_params={"t": "tvsearch", "season": "1"})
    releases = client.search_tv(query="Breaking Bad", season=1)
    assert len(releases) == 3


def test_client_requires_api_key():
    with pytest.raises(C411Error, match="[Cc]l[eé]"):
        C411Client(api_key="")


def test_client_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = C411Client(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(C411Error, match="echoue"):
        client.search_movie(query="x")
