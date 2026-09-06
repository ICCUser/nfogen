"""Tests de nfogen.c411_upload_client (AUTOMATION.md, sous-projet 5).
Client DELIBEREMENT specifique a C411 (pas de standard partage comme
Torznab, voir decision 4) -- verification anti-doublon dans cette tache,
creation/mise a jour de brouillon dans la Tache 10."""
from __future__ import annotations

import base64
import json

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


def test_create_draft_sends_flat_filename_and_data_fields():
    """Format confirme en conditions reelles (2026-09-06) : le corps
    ENVOYE utilise des champs plats `torrentFileName`/`torrentFileData`
    et `nfoFileName`/`nfoFileData` (chaine de nom + chaine base64
    separement, pas un objet imbrique) -- verifie en creant un vrai
    brouillon avec exactement ce format et en constatant `torrentFile`
    bien rempli a la relecture (`GET /api/user/drafts/{id}`, qui
    restructure ces champs plats en objet `{name, data}` -- asymetrie
    lecture/ecriture jamais documentee)."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/user/drafts"
        assert request.method == "POST"
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    result = client.create_draft(
        torrent_bytes=b"torrent-bytes",
        nfo_bytes=b"nfo-bytes",
        torrent_filename="Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM.torrent",
        nfo_filename="Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM.nfo",
        title="Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM",
        description="[h2]Synopsis[/h2]...",
        category_id=1,
        subcategory_id=6,
        options={"1": [4], "2": 10},
    )

    assert result == {"id": 555, "url": "https://c411.org/user/drafts/555"}
    body = captured["body"]
    assert body["name"] == "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM"
    assert body["title"] == "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM"
    assert body["categoryId"] == 1
    assert body["subcategoryId"] == 6
    assert body["options"] == {"1": [4], "2": 10}
    assert body["descriptionFormat"] == "standard"
    assert body["torrentFileName"] == "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM.torrent"
    assert base64.b64decode(body["torrentFileData"]) == b"torrent-bytes"
    assert body["nfoFileName"] == "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM.nfo"
    assert base64.b64decode(body["nfoFileData"]) == b"nfo-bytes"
    assert "torrent" not in body
    assert "nfo" not in body
    assert "torrentFile" not in body
    assert "nfoFile" not in body


def test_create_draft_includes_optional_fields_when_given():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    client.create_draft(
        torrent_bytes=b"t", nfo_bytes=b"n", torrent_filename="X.torrent", nfo_filename="X.nfo",
        title="X", description="X" * 20, category_id=1, subcategory_id=6, options={},
        uploader_note="Note test", tmdb_data={"id": 27205, "type": "movie"},
    )

    assert captured["body"]["uploaderNote"] == "Note test"
    assert captured["body"]["tmdbData"] == {"id": 27205, "type": "movie"}


def test_create_draft_raises_a_clear_message_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid token"})

    client = _client_with_handler(handler)
    with pytest.raises(C411UploadError, match="scope"):
        client.create_draft(
            torrent_bytes=b"t", nfo_bytes=b"n", torrent_filename="X.torrent", nfo_filename="X.nfo",
            title="X", description="X" * 20, category_id=1, subcategory_id=6, options={},
        )


def test_update_draft_patches_the_existing_draft():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/user/drafts/555"
        assert request.method == "PATCH"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    result = client.update_draft(
        555, torrent_bytes=b"t", nfo_bytes=b"n", torrent_filename="X.torrent", nfo_filename="X.nfo",
        title="X updated", description="X" * 20, category_id=1, subcategory_id=6, options={},
    )

    assert result == {"id": 555, "url": "https://c411.org/user/drafts/555"}
    assert captured["body"]["title"] == "X updated"
