"""Tests de nfogen.commit_job_runner (execution en tache de fond de
commit_upload(), AUTOMATION.md sous-projet 4c). Contrairement a
gapscan_runner (un seul scan a la fois), plusieurs taches en parallele --
indexees par job_id. Double de test pour upload_prep.commit_upload (pas
d'I/O reelle ici -- deja couverte par test_upload_prep.py/test_file_staging.py/
test_torrent_builder.py)."""
from __future__ import annotations

import importlib
import threading
import time

import pytest

from nfogen import commit_job_runner, upload_history_store
from nfogen.cancellation import OperationCancelled
from nfogen.upload_prep import CommitResult, ProposedFile


@pytest.fixture(autouse=True)
def _reset_runner():
    """Etat en memoire du module : repart de zero a chaque test (meme
    convention que test_gapscan_runner.py)."""
    importlib.reload(commit_job_runner)
    yield
    importlib.reload(commit_job_runner)


FILES = [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")]


def _wait_until_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = commit_job_runner.status(job_id)
        if status is not None and status["state"] in ("done", "error", "cancelled"):
            return status
        if time.monotonic() > deadline:
            raise TimeoutError("la tâche de test ne s'est jamais terminée")
        time.sleep(0.01)


def _stub_resolve_staging_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "nfogen.commit_job_runner.upload_prep.resolve_staging_config",
        lambda profile: ("/staging", "https://announce"),
    )


# --------------------------------------------------------------------------- #
# start() : verification synchrone AVANT de demarrer une tache
# --------------------------------------------------------------------------- #
def test_start_raises_synchronously_when_staging_not_configured(monkeypatch):
    monkeypatch.setattr(
        "nfogen.commit_job_runner.upload_prep.resolve_staging_config",
        lambda profile: (_ for _ in ()).throw(ValueError("Dossier de mise en scène non configuré.")),
    )
    with pytest.raises(ValueError, match="scène"):
        commit_job_runner.start("X", FILES)


def test_start_returns_a_job_id_immediately_without_waiting(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)
    release_gate = threading.Event()

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        release_gate.wait(timeout=5)
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start("X", FILES)
    assert job_id  # renvoye sans attendre fake_commit_upload (bloque sur release_gate)
    assert commit_job_runner.status(job_id)["state"] == "staging"

    release_gate.set()
    status = _wait_until_terminal(job_id)
    assert status["state"] == "done"
    assert status["result"]["staged_path"] == "p"


# --------------------------------------------------------------------------- #
# Progression
# --------------------------------------------------------------------------- #
def test_on_progress_updates_job_state_and_percent(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)
    reached_50 = threading.Event()
    release_gate = threading.Event()

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        on_progress("staging", 50.0)
        reached_50.set()
        release_gate.wait(timeout=5)
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start("X", FILES)
    assert reached_50.wait(timeout=5)
    status = commit_job_runner.status(job_id)
    assert status["state"] == "staging"
    assert status["percent"] == 50.0

    release_gate.set()
    final = _wait_until_terminal(job_id)
    assert final["state"] == "done"


# --------------------------------------------------------------------------- #
# Annulation
# --------------------------------------------------------------------------- #
def test_cancel_sets_the_event_and_job_reaches_cancelled_state(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)
    started = threading.Event()

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        raise OperationCancelled("annulé")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start("X", FILES)
    assert started.wait(timeout=5)
    assert commit_job_runner.cancel(job_id) is True

    status = _wait_until_terminal(job_id)
    assert status["state"] == "cancelled"


def test_cancel_unknown_job_returns_false():
    assert commit_job_runner.cancel("does-not-exist") is False


def test_cancel_already_finished_job_returns_false(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)
    job_id = commit_job_runner.start("X", FILES)
    _wait_until_terminal(job_id)

    assert commit_job_runner.cancel(job_id) is False


# --------------------------------------------------------------------------- #
# Erreurs
# --------------------------------------------------------------------------- #
def test_error_during_commit_sets_error_state_with_message(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        raise RuntimeError("NAS déconnecté")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)
    job_id = commit_job_runner.start("X", FILES)

    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "NAS déconnecté" in status["error"]


# --------------------------------------------------------------------------- #
# Historique "deja traite" (AUTOMATION.md, sous-projet 8)
# --------------------------------------------------------------------------- #
def test_start_records_history_on_done(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start("R", FILES, media_type="movie", radarr_movie_id=42)
    _wait_until_terminal(job_id)

    key = upload_history_store.processed_key("movie", 42, None)
    assert upload_history_store.is_processed(key)


def test_start_relays_identifiers_to_commit_upload(monkeypatch, tmp_path):
    """Necessaire pour que commit_upload() puisse decider si un fichier de
    mise en scene deja present est un dechet regenerable ou un titre deja
    traite (incident reel, 2026-09-06 : '[Errno 17] File exists')."""
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    _stub_resolve_staging_config(monkeypatch)
    captured: dict = {}

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        captured.update(kwargs)
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start(
        "R", FILES, media_type="series", sonarr_series_id=7, season_number=2,
    )
    _wait_until_terminal(job_id)

    assert captured["media_type"] == "series"
    assert captured["sonarr_series_id"] == 7
    assert captured["season_number"] == 2


def test_start_without_identifiers_does_not_record_history(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start("R", FILES)  # aucun identifiant fourni
    _wait_until_terminal(job_id)

    assert not upload_history_store.is_processed(("movie", 42))


# --------------------------------------------------------------------------- #
# Registre / liste
# --------------------------------------------------------------------------- #
def test_status_of_unknown_job_is_none():
    assert commit_job_runner.status("does-not-exist") is None


def test_list_jobs_includes_multiple_concurrent_and_finished_jobs(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)
    job_id_1 = commit_job_runner.start("A", FILES)
    job_id_2 = commit_job_runner.start("B", FILES)
    _wait_until_terminal(job_id_1)
    _wait_until_terminal(job_id_2)

    ids = {j["job_id"] for j in commit_job_runner.list_jobs()}
    assert {job_id_1, job_id_2} <= ids
