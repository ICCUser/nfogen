"""Tests de nfogen.c411_upload_client (AUTOMATION.md, sous-projet 5).
Client DELIBEREMENT specifique a C411 (pas de standard partage comme
Torznab, voir decision 4) -- verification anti-doublon dans cette tache,
creation/mise a jour de brouillon dans la Tache 10."""
from __future__ import annotations

import httpx
import pytest

from nfogen.c411_upload_client import C411UploadClient, C411UploadError


def _client_with_handler(handler) -> C411UploadClient:
    return C411UploadClient(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_check_duplicates_returns_existing_releases():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/torrents/by-tmdb"
        assert request.url.params.get("tmdbId") == "27205"
        assert request.url.params.get("tmdbType") == "movie"
        assert request.headers.get("authorization") == "Bearer test-key"
        return httpx.Response(200, json={
            "tmdbId": 27205, "tmdbType": "movie", "count": 1,
            "releases": [{"id": 48213, "name": "Inception", "infoHash": "abc123"}],
        })

    client = _client_with_handler(handler)
    releases = client.check_duplicates(27205, "movie")

    assert len(releases) == 1
    assert releases[0]["name"] == "Inception"


def test_check_duplicates_empty_when_no_release_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tmdbId": 1, "tmdbType": "tv", "count": 0, "releases": []})

    client = _client_with_handler(handler)
    assert client.check_duplicates(1, "tv") == []


def test_check_duplicates_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client_with_handler(handler)
    with pytest.raises(C411UploadError, match="[Dd]oublon"):
        client.check_duplicates(1, "movie")


def test_error_message_never_contains_the_api_key():
    secret_key = "25a31a6e545d4f8bf244ce44f717aac2064bfa26895297df1e5e430bf9b1c203"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(520, text="")

    client = C411UploadClient(
        api_key=secret_key, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(C411UploadError) as excinfo:
        client.check_duplicates(1, "movie")

    assert secret_key not in str(excinfo.value)


def test_client_requires_api_key():
    with pytest.raises(C411UploadError, match="[Cc]l[eé]"):
        C411UploadClient(api_key="")
