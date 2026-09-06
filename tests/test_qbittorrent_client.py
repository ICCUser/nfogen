"""Tests de nfogen.qbittorrent_client (transport HTTP mocke, aucun reseau
reel). L'API qBittorrent v2 renvoie le texte brut "Ok." sur succes (login
et add_torrent) -- jamais verifie par ce projet avant ce sous-projet,
voir la spec, "Points a verifier"."""
from __future__ import annotations

import httpx
import pytest

from nfogen.qbittorrent_client import QBittorrentClient, QBittorrentError


def _client(handler) -> QBittorrentClient:
    return QBittorrentClient(
        base_url="http://qbittorrent.local:8080",
        username="admin",
        password="adminadmin",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_add_torrent_logs_in_then_adds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/auth/login":
            assert b"username=admin" in request.content
            assert b"password=adminadmin" in request.content
            return httpx.Response(200, text="Ok.")
        assert request.url.path == "/api/v2/torrents/add"
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.add_torrent(b"torrent bytes", "/data/staging", filename="Release.torrent")

    assert calls == ["/api/v2/auth/login", "/api/v2/torrents/add"]


def test_add_torrent_sends_savepath_and_file_content():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        captured["content"] = request.content
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.add_torrent(b"torrent bytes", "/data/staging", filename="Release.torrent")

    assert b"/data/staging" in captured["content"]
    assert b"torrent bytes" in captured["content"]
    assert b"Release.torrent" in captured["content"]


def test_login_failure_raises_qbittorrent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Fails.")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[Aa]uthentification"):
        client.add_torrent(b"x", "/data/staging")


def test_add_failure_raises_qbittorrent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, text="Fails.")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="refus"):
        client.add_torrent(b"x", "/data/staging")


def test_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[ée]chou"):
        client.add_torrent(b"x", "/data/staging")


def test_requires_base_url_username_and_password():
    with pytest.raises(QBittorrentError):
        QBittorrentClient(base_url="", username="a", password="b")
    with pytest.raises(QBittorrentError):
        QBittorrentClient(base_url="http://x", username="", password="b")
    with pytest.raises(QBittorrentError):
        QBittorrentClient(base_url="http://x", username="a", password="")


# --------------------------------------------------------------------------- #
# list_torrents (retour utilisateur, 2026-09-06 : voir ce qui est
# actuellement en seed via qBittorrent).
# --------------------------------------------------------------------------- #
TORRENTS_INFO = [
    {
        "name": "Movie.2020.1080p.x264-TEAM", "size": 4294967296, "progress": 1.0,
        "ratio": 1.42, "state": "uploading", "upspeed": 512000, "added_on": 1700000000,
    },
]


def test_list_torrents_logs_in_then_lists():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        assert request.url.path == "/api/v2/torrents/info"
        return httpx.Response(200, json=TORRENTS_INFO)

    client = _client(handler)
    torrents = client.list_torrents()

    assert calls == ["/api/v2/auth/login", "/api/v2/torrents/info"]
    assert torrents == TORRENTS_INFO


def test_list_torrents_login_failure_raises_qbittorrent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Fails.")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[Aa]uthentification"):
        client.list_torrents()


def test_list_torrents_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(503, text="down")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[ée]chou"):
        client.list_torrents()
