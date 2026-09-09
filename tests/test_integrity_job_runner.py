"""Tests de nfogen.integrity_job_runner (AUTOMATION.md, sous-projet 7).
Meme convention que test_commit_job_runner.py."""
from __future__ import annotations

import importlib
import threading
import time

import pytest

from nfogen import integrity_job_runner
from nfogen.cancellation import OperationCancelled


@pytest.fixture(autouse=True)
def _reset_runner():
    importlib.reload(integrity_job_runner)
    yield
    importlib.reload(integrity_job_runner)


def _wait_until_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = integrity_job_runner.status(job_id)
        if status is not None and status["state"] in ("done", "error", "cancelled"):
            return status
        if time.monotonic() > deadline:
            raise TimeoutError("la tâche de test ne s'est jamais terminée")
        time.sleep(0.01)


class _Report:
    def __init__(self, passed, errors, warnings):
        self.passed = passed
        self.errors = errors
        self.warnings = warnings


def test_start_raises_immediately_when_ffmpeg_absent(monkeypatch):
    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.has_ffmpeg", lambda: False)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        integrity_job_runner.start("/staged/movie.mkv")


def test_start_returns_job_id_immediately_and_reaches_done(monkeypatch):
    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.has_ffmpeg", lambda: True)
    release_gate = threading.Event()

    def fake_verify(staged_path, *, on_progress=None, cancel_event=None):
        release_gate.wait(timeout=5)
        return _Report(passed=True, errors=[], warnings=[])

    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.verify_staged_media", fake_verify)

    job_id = integrity_job_runner.start("/staged/movie.mkv")
    assert job_id
    assert integrity_job_runner.status(job_id)["state"] == "verifying"

    release_gate.set()
    status = _wait_until_terminal(job_id)
    assert status["state"] == "done"
    assert status["result"] == {"passed": True, "errors": [], "warnings": []}
    assert status["percent"] == 100.0


def test_start_reaches_done_with_passed_false_when_report_fails(monkeypatch):
    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.has_ffmpeg", lambda: True)

    def fake_verify(staged_path, *, on_progress=None, cancel_event=None):
        return _Report(passed=False, errors=["corrompu"], warnings=[])

    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.verify_staged_media", fake_verify)

    job_id = integrity_job_runner.start("/staged/movie.mkv")
    status = _wait_until_terminal(job_id)
    # "done" est atteint meme si le RAPPORT est negatif -- c'est le job
    # qui a reussi a produire un resultat, pas une erreur d'execution.
    assert status["state"] == "done"
    assert status["result"]["passed"] is False
    assert status["result"]["errors"] == ["corrompu"]


def test_on_progress_updates_job_percent(monkeypatch):
    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.has_ffmpeg", lambda: True)
    reached_50 = threading.Event()
    release_gate = threading.Event()

    def fake_verify(staged_path, *, on_progress=None, cancel_event=None):
        on_progress(50.0)
        reached_50.set()
        release_gate.wait(timeout=5)
        return _Report(passed=True, errors=[], warnings=[])

    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.verify_staged_media", fake_verify)

    job_id = integrity_job_runner.start("/staged/movie.mkv")
    assert reached_50.wait(timeout=5)
    assert integrity_job_runner.status(job_id)["percent"] == 50.0

    release_gate.set()
    _wait_until_terminal(job_id)


def test_cancel_sets_the_event_and_job_reaches_cancelled(monkeypatch):
    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.has_ffmpeg", lambda: True)
    started = threading.Event()

    def fake_verify(staged_path, *, on_progress=None, cancel_event=None):
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        raise OperationCancelled("annulé")

    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.verify_staged_media", fake_verify)

    job_id = integrity_job_runner.start("/staged/movie.mkv")
    assert started.wait(timeout=5)
    assert integrity_job_runner.cancel(job_id) is True

    status = _wait_until_terminal(job_id)
    assert status["state"] == "cancelled"


def test_cancel_unknown_job_returns_false():
    assert integrity_job_runner.cancel("does-not-exist") is False


def test_error_during_verification_sets_error_state(monkeypatch):
    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.has_ffmpeg", lambda: True)

    def fake_verify(staged_path, *, on_progress=None, cancel_event=None):
        raise RuntimeError("NAS déconnecté")

    monkeypatch.setattr("nfogen.integrity_job_runner.video_integrity.verify_staged_media", fake_verify)

    job_id = integrity_job_runner.start("/staged/movie.mkv")
    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "NAS déconnecté" in status["error"]


def test_status_of_unknown_job_is_none():
    assert integrity_job_runner.status("does-not-exist") is None
