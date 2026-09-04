"""Execution en tache de fond de commit_upload() (AUTOMATION.md, sous-projet
4c) : contrairement a gapscan_runner.py (un seul scan a la fois), plusieurs
taches peuvent tourner en parallele -- un job_id par appel a start(). Etat
en memoire uniquement (pas de persistance disque : une tache interrompue
par un redemarrage du serveur est simplement perdue, comme un scan GapScan
en cours -- voir la spec, "Non-objectifs").
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from . import upload_prep
from .cancellation import OperationCancelled


class JobState(str, Enum):
    STAGING = "staging"
    GENERATING_NFO = "generating_nfo"
    BUILDING_TORRENT = "building_torrent"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


_TERMINAL_STATES = (JobState.DONE, JobState.ERROR, JobState.CANCELLED)


@dataclass
class JobProgress:
    job_id: str
    release_name: str
    state: JobState
    percent: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


_lock = threading.Lock()
_jobs: dict[str, JobProgress] = {}
_cancel_events: dict[str, threading.Event] = {}


def start(
    release_name: str, files: list[upload_prep.ProposedFile], profile: str = "c411"
) -> str:
    """Verifie d'abord la configuration (rapide, voir
    upload_prep.resolve_staging_config -- leve ValueError/RuntimeError
    IMMEDIATEMENT si mal configure, avant meme de creer une tache), puis
    demarre la mise en scene + generation en tache de fond et renvoie le
    `job_id` SANS ATTENDRE la fin."""
    upload_prep.resolve_staging_config(profile)

    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job = JobProgress(job_id=job_id, release_name=release_name, state=JobState.STAGING)
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel_event

    thread = threading.Thread(
        target=_run, args=(job_id, release_name, files, profile, cancel_event), daemon=True
    )
    thread.start()
    return job_id


def _run(
    job_id: str,
    release_name: str,
    files: list[upload_prep.ProposedFile],
    profile: str,
    cancel_event: threading.Event,
) -> None:
    def on_progress(step: str, percent: float) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.state = JobState(step)
                job.percent = percent

    try:
        result = upload_prep.commit_upload(
            release_name, files, profile, on_progress=on_progress, cancel_event=cancel_event
        )
        with _lock:
            job = _jobs[job_id]
            job.state = JobState.DONE
            job.percent = 100.0
            job.result = {
                "release_name": result.release_name, "staged_path": result.staged_path,
                "torrent_path": result.torrent_path, "nfo_path": result.nfo_path,
            }
            job.finished_at = time.time()
    except OperationCancelled:
        with _lock:
            job = _jobs[job_id]
            job.state = JobState.CANCELLED
            job.finished_at = time.time()
    except Exception as exc:  # noqa: BLE001 -- toute erreur -> etat "error", jamais un thread qui meurt en silence
        with _lock:
            job = _jobs[job_id]
            job.state = JobState.ERROR
            job.error = str(exc)
            job.finished_at = time.time()


def _serialize(job: JobProgress) -> dict[str, Any]:
    return {
        "job_id": job.job_id, "release_name": job.release_name, "state": job.state.value,
        "percent": job.percent, "started_at": job.started_at, "finished_at": job.finished_at,
        "error": job.error, "result": job.result,
    }


def status(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return _serialize(job) if job is not None else None


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        return [_serialize(job) for job in _jobs.values()]


def cancel(job_id: str) -> bool:
    """`True` si l'annulation a ete declenchee (la tache s'arretera
    "bientot", pas instantanement). `False` si `job_id` inconnu OU deja
    dans un etat terminal -- annuler une tache deja finie n'a pas de sens."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.state in _TERMINAL_STATES:
            return False
        _cancel_events[job_id].set()
        return True
