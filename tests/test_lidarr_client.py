from __future__ import annotations

import httpx
import pytest

from nfogen.lidarr_client import LidarrClient, LidarrError


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, responses: dict[str, object]):
        self._responses = responses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path_and_query = request.url.raw_path.decode()
        for path, body in self._responses.items():
            if path_and_query.startswith(path):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})


def _client(responses: dict[str, object]) -> LidarrClient:
    http_client = httpx.Client(transport=_FakeTransport(responses))
    return LidarrClient("http://lidarr.local:8686", "fake-key", http_client=http_client)


def test_list_album_files_skips_albums_without_local_tracks():
    responses = {
        "/api/v1/artist": [
            {"id": 1, "artistName": "Daft Punk", "foreignArtistId": "056e4f3e-d505-4dad-8ec1-d04f521cbb56"},
        ],
        "/api/v1/album": [
            {
                "id": 10, "artistId": 1, "title": "Random Access Memories",
                "releaseDate": "2013-05-17T00:00:00Z",
                "foreignAlbumId": "2c04a86b-3f75-4c50-9b7a-3f5e5e5e5e5e",
                "statistics": {"trackFileCount": 13, "sizeOnDisk": 987654321},
            },
            {
                "id": 11, "artistId": 1, "title": "Homework",
                "releaseDate": "1997-01-20T00:00:00Z",
                "foreignAlbumId": None,
                "statistics": {"trackFileCount": 0, "sizeOnDisk": 0},
            },
        ],
        "/api/v1/trackfile?albumId=10": [
            {"path": "/music/Daft Punk/RAM/01.flac", "size": 50000000, "dateAdded": "2024-01-01T00:00:00Z"},
        ],
    }
    client = _client(responses)
    try:
        albums = client.list_album_files()
    finally:
        client.close()

    assert len(albums) == 1  # "Homework" (0 fichier local) est ignore
    album = albums[0]
    assert album.album_id == 10
    assert album.artist_name == "Daft Punk"
    assert album.album_title == "Random Access Memories"
    assert album.release_year == 2013
    assert album.musicbrainz_album_id == "2c04a86b-3f75-4c50-9b7a-3f5e5e5e5e5e"
    assert album.musicbrainz_artist_id == "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
    assert album.remote_path == "/music/Daft Punk/RAM"
    assert album.size_bytes == 987654321
    assert album.track_count == 13


def test_missing_base_url_or_api_key_raises():
    with pytest.raises(LidarrError):
        LidarrClient("", "key")
    with pytest.raises(LidarrError):
        LidarrClient("http://lidarr.local", "")


def test_network_error_raises_lidarr_error():
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(_raise))
    client = LidarrClient("http://lidarr.local", "fake-key", http_client=http_client)
    try:
        with pytest.raises(LidarrError):
            client.list_album_files()
    finally:
        client.close()
