"""Execution en tache de fond du telechargement + verification d'une
correspondance de seed (AUTOMATION.md, retour utilisateur 2026-09-09) :
meme patron que integrity_job_runner.py (thread + job_id + polling,
etat en memoire uniquement).
"""
from __future__ import annotations

import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import torf

from .qbittorrent_client import QBittorrentClient, QBittorrentError
from .torznab_client import TorznabClient, TorznabError

_POLL_INTERVAL_SECONDS = 1.5
_CHECK_TIMEOUT_SECONDS = 300.0

# Etats qBittorrent consideres comme "verification terminee, fichier
# complet" -- NON VERIFIES CONTRE UNE INSTANCE REELLE (voir
# AUTOMATION.md, meme prudence que le N+1 Sonarr du 2026-09-09).
_VERIFIED_COMPLETE_STATES = {"pausedUP", "queuedUP", "checkedUP"}
_VERIFIED_MISMATCH_STATES = {"missingFiles", "error"}


class SeedMatchJobState(str, Enum):
    DOWNLOADING = "downloading"
    CHECKING = "checking"
    DONE = "done"
    MISMATCH = "mismatch"
    ERROR = "error"
    CANCELLED = "cancelled"


_TERMINAL_STATES = (
    SeedMatchJobState.DONE, SeedMatchJobState.MISMATCH,
    SeedMatchJobState.ERROR, SeedMatchJobState.CANCELLED,
)


@dataclass
class SeedMatchJobProgress:
    job_id: str
    state: SeedMatchJobState
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


_lock = threading.Lock()
_jobs: dict[str, SeedMatchJobProgress] = {}
_cancel_events: dict[str, threading.Event] = {}


def start(
    tracker_client: TorznabClient, qbittorrent_client: QBittorrentClient,
    guid: str, local_dir: str, release_name: str,
) -> str:
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job = SeedMatchJobProgress(job_id=job_id, state=SeedMatchJobState.DOWNLOADING)
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel_event

    thread = threading.Thread(
        target=_run,
        args=(job_id, tracker_client, qbittorrent_client, guid, local_dir, release_name, cancel_event),
        daemon=True,
    )
    thread.start()
    return job_id


def _set_state(job_id: str, state: SeedMatchJobState, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.state = state
        for key, value in fields.items():
            setattr(job, key, value)


def _run(
    job_id: str, tracker_client: TorznabClient, qbittorrent_client: QBittorrentClient,
    guid: str, local_dir: str, release_name: str, cancel_event: threading.Event,
) -> None:
    try:
        torrent_bytes = tracker_client.download(guid)
        if cancel_event.is_set():
            _set_state(job_id, SeedMatchJobState.CANCELLED, finished_at=time.time())
            return

        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
            tmp.write(torrent_bytes)
            tmp_path = tmp.name
        infohash = torf.Torrent.read(tmp_path).infohash
        Path(tmp_path).unlink(missing_ok=True)

        qbittorrent_client.add_torrent(
            torrent_bytes, local_dir, filename=f"{release_name}.torrent", paused=True, tags="NFOGEN",
        )
        _set_state(job_id, SeedMatchJobState.CHECKING)

        deadline = time.monotonic() + _CHECK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if cancel_event.is_set():
                _set_state(job_id, SeedMatchJobState.CANCELLED, finished_at=time.time())
                return
            entry = next(
                (t for t in qbittorrent_client.list_torrents() if t.get("hash") == infohash), None,
            )
            if entry is not None:
                state = entry.get("state")
                progress = entry.get("progress", 0.0)
                if state in _VERIFIED_COMPLETE_STATES and progress == 1.0:
                    qbittorrent_client.resume(infohash)
                    _set_state(
                        job_id, SeedMatchJobState.DONE, finished_at=time.time(),
                        result={"warning": None},
                    )
                    return
                incomplete = state in _VERIFIED_COMPLETE_STATES and progress < 1.0
                if state in _VERIFIED_MISMATCH_STATES or incomplete:
                    _set_state(
                        job_id, SeedMatchJobState.MISMATCH, finished_at=time.time(),
                        result={
                            "warning": "Le fichier téléchargé ne correspond pas exactement — "
                            "resté en pause dans qBittorrent, à vérifier/supprimer manuellement.",
                        },
                    )
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)

        _set_state(
            job_id, SeedMatchJobState.ERROR, finished_at=time.time(),
            error="Vérification qBittorrent trop longue — vérifie manuellement dans son interface.",
        )
    except (TorznabError, QBittorrentError) as exc:
        _set_state(job_id, SeedMatchJobState.ERROR, finished_at=time.time(), error=str(exc))
    except Exception as exc:  # noqa: BLE001 -- toute erreur -> etat "error", jamais un thread qui meurt en silence
        _set_state(job_id, SeedMatchJobState.ERROR, finished_at=time.time(), error=str(exc))


def _serialize(job: SeedMatchJobProgress) -> dict[str, Any]:
    return {
        "job_id": job.job_id, "state": job.state.value,
        "started_at": job.started_at, "finished_at": job.finished_at,
        "error": job.error, "result": job.result,
    }


def status(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return _serialize(job) if job is not None else None


def cancel(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.state in _TERMINAL_STATES:
            return False
        _cancel_events[job_id].set()
        return True
