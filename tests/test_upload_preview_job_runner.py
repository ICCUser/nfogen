"""Tests de nfogen.upload_preview_job_runner. Meme convention que
test_integrity_job_runner.py/test_commit_job_runner.py."""
from __future__ import annotations

import importlib
import threading
import time
from unittest.mock import patch

import pytest

from nfogen import upload_preview_job_runner


@pytest.fixture(autouse=True)
def _reset_runner():
    importlib.reload(upload_preview_job_runner)
    yield
    importlib.reload(upload_preview_job_runner)


@pytest.fixture(autouse=True)
def _allow_all_paths_by_default(monkeypatch):
    """Meme neutralisation que test_upload_prep.py -- ce fichier teste le
    COMPORTEMENT du job (progression/annulation/etats), pas le controle
    source_path lui-meme, deja teste dans test_upload_prep.py."""
    monkeypatch.setattr("nfogen.upload_prep._validate_known_source_paths", lambda paths: None)


def _wait_until_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = upload_preview_job_runner.status(job_id)
        if status is not None and status["state"] in ("done", "error", "cancelled"):
            return status
        if time.monotonic() > deadline:
            raise TimeoutError("la tâche de test ne s'est jamais terminée")
        time.sleep(0.01)


def _fake_metadata():
    return {
        "video_height": 1080, "video_width": 1920, "video_format": "AVC", "video_bit_rate": 5_000_000,
        "frame_rate": 24.0, "audio_languages": [], "subtitle_languages": [], "general_title": None,
        "container": "MKV", "hdr_format": None,
    }


def test_start_returns_job_id_immediately_and_reaches_done():
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        job_id = upload_preview_job_runner.start(["/media/a.mkv"], profile="c411")
        assert job_id
        status = _wait_until_terminal(job_id)

    assert status["state"] == "done"
    assert status["result"] is not None
    assert status["total"] == 1
    assert status["processed"] == 1


def test_status_reports_progress_while_running():
    release_gate = threading.Event()
    started = threading.Event()

    def fake_extract(path):
        started.set()
        release_gate.wait(timeout=5)
        return _fake_metadata()

    with patch("nfogen.upload_prep.extract.extract_video_metadata", side_effect=fake_extract):
        job_id = upload_preview_job_runner.start(["/media/a.mkv", "/media/b.mkv"], profile="c411")
        assert started.wait(timeout=5)

        mid_status = upload_preview_job_runner.status(job_id)
        assert mid_status["state"] == "analyzing"

        release_gate.set()
        status = _wait_until_terminal(job_id)

    assert status["state"] == "done"
    assert status["total"] == 2


def test_cancel_stops_the_job_before_the_next_file():
    release_gate = threading.Event()
    started = threading.Event()

    def fake_extract(path):
        started.set()
        release_gate.wait(timeout=5)
        return _fake_metadata()

    with patch("nfogen.upload_prep.extract.extract_video_metadata", side_effect=fake_extract):
        job_id = upload_preview_job_runner.start(["/media/a.mkv", "/media/b.mkv"], profile="c411")
        assert started.wait(timeout=5)

        assert upload_preview_job_runner.cancel(job_id) is True
        release_gate.set()
        status = _wait_until_terminal(job_id)

    assert status["state"] == "cancelled"


def test_cancel_returns_false_for_unknown_job():
    assert upload_preview_job_runner.cancel("does-not-exist") is False


def test_cancel_returns_false_once_already_terminal():
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        job_id = upload_preview_job_runner.start(["/media/a.mkv"], profile="c411")
        _wait_until_terminal(job_id)

    assert upload_preview_job_runner.cancel(job_id) is False


def test_status_returns_none_for_unknown_job():
    assert upload_preview_job_runner.status("does-not-exist") is None


def test_error_from_preview_upload_becomes_an_error_state():
    # extract_video_metadata qui leve devient un avertissement best-effort
    # DANS preview_upload (jamais une exception propagee pour une simple
    # extraction ratee) -- ce test simule donc une erreur AILLEURS dans
    # preview_upload (ex. profil introuvable) pour prouver la propagation
    # correcte en etat "error" du job.
    with patch(
        "nfogen.upload_preview_job_runner.upload_prep.preview_upload",
        side_effect=RuntimeError("profil introuvable"),
    ):
        job_id = upload_preview_job_runner.start(["/media/a.mkv"], profile="does-not-exist")
        status = _wait_until_terminal(job_id)

    assert status["state"] == "error"
    assert "profil introuvable" in status["error"]
