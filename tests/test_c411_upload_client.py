"""Tests de nfogen.c411_upload_client (AUTOMATION.md, sous-projet 5).
Client DELIBEREMENT specifique a C411 (pas de standard partage comme
Torznab, voir decision 4) -- verification anti-doublon dans cette tache,
creation/mise a jour de brouillon dans la Tache 10.

`torrent`/`nfo` envoyes en multipart/form-data (voir note en tete de
c411_upload_client.py) -- `_parse_multipart` decode le corps de requete
capture par MockTransport avec le module standard `email`, plutot qu'une
dependance de test supplementaire."""
from __future__ import annotations

import email
import json
from email.message import Message

import httpx
import pytest

from nfogen.c411_upload_client import C411UploadClient, C411UploadError


def _client_with_handler(handler) -> C411UploadClient:
    return C411UploadClient(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _parse_multipart(request: httpx.Request) -> dict[str, Message]:
    """Decode un corps multipart/form-data en {nom_du_champ: Message}
    (`.get_payload(decode=True)` donne les octets bruts du champ, fichier
    ou non)."""
    header_bytes = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode("ascii")
    parsed = email.message_from_bytes(header_bytes + request.read())
    return {part.get_param("name", header="content-disposition"): part for part in parsed.get_payload()}


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


def test_create_draft_sends_real_files_in_multipart_and_returns_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/user/drafts"
        assert request.method == "POST"
        assert request.headers["content-type"].startswith("multipart/form-data")
        captured["parts"] = _parse_multipart(request)
        return httpx.Response(201, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    result = client.create_draft(
        torrent_bytes=b"torrent-bytes",
        nfo_bytes=b"nfo-bytes",
        title="Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM",
        description="[h2]Synopsis[/h2]...",
        category_id=1,
        subcategory_id=6,
        options={"1": [4], "2": 10},
    )

    assert result == {"id": 555, "url": "https://c411.org/user/drafts/555"}
    parts = captured["parts"]
    assert parts["title"].get_payload(decode=True) == b"Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM"
    assert parts["categoryId"].get_payload(decode=True) == b"1"
    assert parts["subcategoryId"].get_payload(decode=True) == b"6"
    assert json.loads(parts["options"].get_payload(decode=True)) == {"1": [4], "2": 10}
    assert parts["descriptionFormat"].get_payload(decode=True) == b"standard"
    # Fichiers reels (filename + Content-Type), pas des champs texte base64.
    assert parts["torrent"].get_filename() is not None
    assert parts["torrent"].get_payload(decode=True) == b"torrent-bytes"
    assert parts["nfo"].get_filename() is not None
    assert parts["nfo"].get_payload(decode=True) == b"nfo-bytes"


def test_create_draft_includes_optional_fields_when_given():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["parts"] = _parse_multipart(request)
        return httpx.Response(201, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    client.create_draft(
        torrent_bytes=b"t", nfo_bytes=b"n", title="X", description="X" * 20,
        category_id=1, subcategory_id=6, options={},
        uploader_note="Note test", tmdb_data={"id": 27205, "type": "movie"},
    )

    parts = captured["parts"]
    assert parts["uploaderNote"].get_payload(decode=True) == b"Note test"
    assert json.loads(parts["tmdbData"].get_payload(decode=True)) == {"id": 27205, "type": "movie"}


def test_create_draft_raises_a_clear_message_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid token"})

    client = _client_with_handler(handler)
    with pytest.raises(C411UploadError, match="scope"):
        client.create_draft(
            torrent_bytes=b"t", nfo_bytes=b"n", title="X", description="X" * 20,
            category_id=1, subcategory_id=6, options={},
        )


def test_update_draft_patches_the_existing_draft():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/user/drafts/555"
        assert request.method == "PATCH"
        assert request.headers["content-type"].startswith("multipart/form-data")
        captured["parts"] = _parse_multipart(request)
        return httpx.Response(200, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    result = client.update_draft(
        555, torrent_bytes=b"t", nfo_bytes=b"n", title="X updated", description="X" * 20,
        category_id=1, subcategory_id=6, options={},
    )

    assert result == {"id": 555, "url": "https://c411.org/user/drafts/555"}
    assert captured["parts"]["title"].get_payload(decode=True) == b"X updated"
