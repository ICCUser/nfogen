"""Execution en tache de fond de upload_prep.preview_upload() -- meme
patron que integrity_job_runner.py/commit_job_runner.py (plusieurs taches
en parallele, job_id par appel a start(), etat en memoire uniquement).

Retour utilisateur (2026-09-09) : "j'ai le film Bernie qui est ultra long
apres avoir cliqué sur préparer l'upload [...] juste Calcul de l'apercu
effectivement je me suis fait avoir sur la fonctionnalite que j'ai decide
de mettre en place" -- un fichier sans debit/frame rate video deja
embarques dans son conteneur force upload_prep.extract.extract_video_metadata
a faire une analyse MediaInfo COMPLETE (potentiellement tres longue sur un
gros fichier ou un montage NAS distant), jusqu'ici bloquant tout le
formulaire "Preparer l'upload" sans le moindre retour visuel. Desormais
une tache de fond, avec une vraie progression par fichier ET un message
qui explique POURQUOI c'est long (au lieu d'un simple "Calcul de
l'apercu…" muet).
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


class UploadPreviewJobState(str, Enum):
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


_TERMINAL_STATES = (UploadPreviewJobState.DONE, UploadPreviewJobState.ERROR, UploadPreviewJobState.CANCELLED)


@dataclass
class UploadPreviewJobProgress:
    job_id: str
    state: UploadPreviewJobState
    processed: int = 0
    total: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[list[dict[str, Any]]] = None


_lock = threading.Lock()
_jobs: dict[str, UploadPreviewJobProgress] = {}
_cancel_events: dict[str, threading.Event] = {}


def start(
    local_paths: list[str], profile: str = "c411", title_override: Optional[str] = None,
    season_pack: Optional[upload_prep.SeasonPackRequest] = None,
) -> str:
    """Cree la tache et la lance immediatement -- la validation des chemins
    (voir upload_prep._validate_known_source_paths) reste faite DANS
    preview_upload(), donc encore a l'interieur du thread de fond ; une
    erreur de validation devient un etat "error" du job, jamais une
    exception synchrone ici (coherent avec les autres job runners)."""
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job = UploadPreviewJobProgress(job_id=job_id, state=UploadPreviewJobState.ANALYZING)
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel_event

    args = (job_id, local_paths, profile, title_override, season_pack, cancel_event)
    thread = threading.Thread(target=_run, args=args, daemon=True)
    thread.start()
    return job_id


def _run(
    job_id: str, local_paths: list[str], profile: str, title_override: Optional[str],
    season_pack: Optional[upload_prep.SeasonPackRequest], cancel_event: threading.Event,
) -> None:
    def on_progress(processed: int, total: int) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.processed = processed
                job.total = total

    try:
        proposals = upload_prep.preview_upload(
            local_paths, profile=profile, title_override=title_override, season_pack=season_pack,
            on_progress=on_progress, cancel_event=cancel_event,
        )
        with _lock:
            job = _jobs[job_id]
            job.state = UploadPreviewJobState.DONE
            job.result = [_serialize_proposal(p) for p in proposals]
            job.finished_at = time.time()
    except OperationCancelled:
        with _lock:
            job = _jobs[job_id]
            job.state = UploadPreviewJobState.CANCELLED
            job.finished_at = time.time()
    except Exception as exc:  # noqa: BLE001 -- toute erreur -> etat "error", jamais un thread qui meurt en silence
        with _lock:
            job = _jobs[job_id]
            job.state = UploadPreviewJobState.ERROR
            job.error = str(exc)
            job.finished_at = time.time()


def _serialize_proposal(proposal: upload_prep.GroupProposal) -> dict[str, Any]:
    return {
        "release_name": proposal.release_name,
        "files": [{"source_path": f.source_path, "staged_name": f.staged_name} for f in proposal.files],
        "warnings": proposal.warnings,
        "blocked": proposal.blocked,
    }


def _serialize(job: UploadPreviewJobProgress) -> dict[str, Any]:
    return {
        "job_id": job.job_id, "state": job.state.value,
        "processed": job.processed, "total": job.total,
        "started_at": job.started_at, "finished_at": job.finished_at,
        "error": job.error, "result": job.result,
    }


def status(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return _serialize(job) if job is not None else None


def cancel(job_id: str) -> bool:
    """`True` si l'annulation a ete declenchee. `False` si `job_id`
    inconnu OU deja dans un etat terminal. Prend effet ENTRE deux
    fichiers seulement -- jamais au milieu de l'extraction d'un fichier
    en cours (voir upload_prep.preview_upload)."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.state in _TERMINAL_STATES:
            return False
        _cancel_events[job_id].set()
        return True
