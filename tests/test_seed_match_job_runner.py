"""Tests de nfogen.seed_match_job_runner. Meme convention que
test_integrity_job_runner.py."""
from __future__ import annotations

import importlib
import threading
import time

import pytest

from nfogen import seed_match_job_runner
from nfogen.qbittorrent_client import QBittorrentError
from nfogen.torznab_client import TorznabError


@pytest.fixture(autouse=True)
def _reset_runner():
    importlib.reload(seed_match_job_runner)
    yield
    importlib.reload(seed_match_job_runner)


def _wait_until_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = seed_match_job_runner.status(job_id)
        if status is not None and status["state"] in ("done", "mismatch", "error", "cancelled"):
            return status
        if time.monotonic() > deadline:
            raise TimeoutError("la tâche de test ne s'est jamais terminée")
        time.sleep(0.01)


class _FakeTorf:
    infohash = "abc123"


def _fake_torf_read(path):
    return _FakeTorf()


class FakeTracker:
    def __init__(self, torrent_bytes=b"d8:announce..."):
        self._torrent_bytes = torrent_bytes

    def download(self, guid):
        return self._torrent_bytes


class FakeQBittorrent:
    def __init__(self, list_results):
        self._added = None
        self._resumed = None
        self._list_results = list_results

    def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
        self._added = {"torrent_bytes": torrent_bytes, "save_path": save_path, "kwargs": kwargs}

    def list_torrents(self):
        return self._list_results

    def resume(self, torrent_hash):
        self._resumed = torrent_hash


def test_start_returns_job_id_immediately_and_reaches_done(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    tracker = FakeTracker()
    qb = FakeQBittorrent([{"hash": "abc123", "progress": 1.0, "state": "pausedUP"}])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id)

    assert status["state"] == "done"
    assert qb._added["kwargs"]["paused"] is True
    assert qb._added["kwargs"]["tags"] == "NFOGEN"
    assert qb._resumed == "abc123"


def test_start_reaches_mismatch_when_progress_incomplete(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    tracker = FakeTracker()
    qb = FakeQBittorrent([{"hash": "abc123", "progress": 0.5, "state": "pausedUP"}])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id)

    assert status["state"] == "mismatch"
    assert qb._resumed is None
    assert status["result"]["warning"]


def test_start_reaches_mismatch_on_missing_files(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    tracker = FakeTracker()
    qb = FakeQBittorrent([{"hash": "abc123", "progress": 0.0, "state": "missingFiles"}])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id)

    assert status["state"] == "mismatch"
    assert qb._resumed is None


def test_start_reaches_error_when_download_fails(monkeypatch):
    class FailingTracker:
        def download(self, guid):
            raise TorznabError("panne réseau")

    job_id = seed_match_job_runner.start(
        FailingTracker(), FakeQBittorrent([]), "guid-1", "/staging/Movie", "Movie.2020-TEAM",
    )
    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "panne réseau" in status["error"]


def test_start_reaches_error_when_qbittorrent_add_fails(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))

    class FailingQBittorrent(FakeQBittorrent):
        def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
            raise QBittorrentError("connexion échouée")

    job_id = seed_match_job_runner.start(
        FakeTracker(), FailingQBittorrent([]), "guid-1", "/staging/Movie", "Movie.2020-TEAM",
    )
    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "connexion échouée" in status["error"]


def test_start_reaches_error_on_verification_timeout(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr("nfogen.seed_match_job_runner._CHECK_TIMEOUT_SECONDS", 0.03)
    tracker = FakeTracker()
    # hash absent de list_torrents() -> jamais trouve, doit finir par un timeout
    qb = FakeQBittorrent([])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id, timeout=2.0)
    assert status["state"] == "error"
    assert "trop longue" in status["error"] or "qBittorrent" in status["error"]


def test_cancel_before_add_never_calls_add_torrent(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    started = threading.Event()
    added_called = threading.Event()

    class SlowTracker:
        def download(self, guid):
            started.set()
            time.sleep(0.2)
            return b"torrent-bytes"

    class TrackedQBittorrent(FakeQBittorrent):
        def add_torrent(self, *args, **kwargs):
            added_called.set()
            super().add_torrent(*args, **kwargs)

    job_id = seed_match_job_runner.start(
        SlowTracker(), TrackedQBittorrent([]), "guid-1", "/staging/Movie", "Movie.2020-TEAM",
    )
    assert started.wait(timeout=5)
    assert seed_match_job_runner.cancel(job_id) is True
    status = _wait_until_terminal(job_id)
    assert status["state"] == "cancelled"
    assert not added_called.is_set()


def test_status_of_unknown_job_is_none():
    assert seed_match_job_runner.status("does-not-exist") is None


def test_cancel_unknown_job_returns_false():
    assert seed_match_job_runner.cancel("does-not-exist") is False
