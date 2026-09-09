"""Execution en tache de fond de video_integrity.verify_staged_media()
(AUTOMATION.md, sous-projet 7 -- verification approfondie) : meme patron
que commit_job_runner.py (plusieurs taches en parallele, job_id par
appel a start(), etat en memoire uniquement -- une tache interrompue par
un redemarrage du serveur est simplement perdue).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from . import upload_prep, video_integrity
from .cancellation import OperationCancelled


class IntegrityJobState(str, Enum):
    VERIFYING = "verifying"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


_TERMINAL_STATES = (IntegrityJobState.DONE, IntegrityJobState.ERROR, IntegrityJobState.CANCELLED)


@dataclass
class IntegrityJobProgress:
    job_id: str
    state: IntegrityJobState
    percent: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


_lock = threading.Lock()
_jobs: dict[str, IntegrityJobProgress] = {}
_cancel_events: dict[str, threading.Event] = {}


def start(staged_path: str) -> str:
    """Leve RuntimeError IMMEDIATEMENT (avant meme de creer une tache) si
    ffmpeg/ffprobe sont absents du serveur -- jamais de tache qui echoue
    silencieusement plus tard pour cette seule raison. Leve ValueError si
    `staged_path` sort du dossier de mise en scene configure (voir
    upload_prep.validate_staged_path, audit securite 2026-09-09) --
    empeche un `staged_path` arbitraire de faire decoder n'importe quel
    fichier du serveur par ffmpeg."""
    upload_prep.validate_staged_path(staged_path)
    if not video_integrity.has_ffmpeg():
        raise RuntimeError("ffmpeg/ffprobe requis pour la vérification — non trouvés sur le serveur nfogen.")

    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job = IntegrityJobProgress(job_id=job_id, state=IntegrityJobState.VERIFYING)
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel_event

    thread = threading.Thread(target=_run, args=(job_id, staged_path, cancel_event), daemon=True)
    thread.start()
    return job_id


def _run(job_id: str, staged_path: str, cancel_event: threading.Event) -> None:
    def on_progress(percent: float) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.percent = percent

    try:
        report = video_integrity.verify_staged_media(
            staged_path, on_progress=on_progress, cancel_event=cancel_event,
        )
        with _lock:
            job = _jobs[job_id]
            job.state = IntegrityJobState.DONE
            job.percent = 100.0
            job.result = {"passed": report.passed, "errors": report.errors, "warnings": report.warnings}
            job.finished_at = time.time()
    except OperationCancelled:
        with _lock:
            job = _jobs[job_id]
            job.state = IntegrityJobState.CANCELLED
            job.finished_at = time.time()
    except Exception as exc:  # noqa: BLE001 -- toute erreur -> etat "error", jamais un thread qui meurt en silence
        with _lock:
            job = _jobs[job_id]
            job.state = IntegrityJobState.ERROR
            job.error = str(exc)
            job.finished_at = time.time()


def _serialize(job: IntegrityJobProgress) -> dict[str, Any]:
    return {
        "job_id": job.job_id, "state": job.state.value, "percent": job.percent,
        "started_at": job.started_at, "finished_at": job.finished_at,
        "error": job.error, "result": job.result,
    }


def status(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return _serialize(job) if job is not None else None


def cancel(job_id: str) -> bool:
    """`True` si l'annulation a ete declenchee. `False` si `job_id`
    inconnu OU deja dans un etat terminal."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.state in _TERMINAL_STATES:
            return False
        _cancel_events[job_id].set()
        return True
