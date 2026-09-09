"""Verification physique du fichier video avant un upload DIRECT C411
(jamais un brouillon) -- AUTOMATION.md, sous-projet 7 (repris
2026-09-09). Complementaire (pas un doublon) des verifications de
conformite tracker deja existantes (name_proposal.py, groupe
GroupProposal.blocked) : ici on verifie que le fichier lui-meme est
reellement lisible de bout en bout, pas les regles de nommage/categorie.

Necessite ffmpeg + ffprobe sur le PATH (voir has_ffmpeg()) -- deja
utilise comme outil de TEST dans tests/test_c411.py (HAS_FFMPEG), promu
ici en dependance d'execution reelle (voir Dockerfile/README).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .cancellation import OperationCancelled
from .extract import VIDEO_EXTS

DURATION_TOLERANCE_SECONDS = 5.0
AV_SYNC_TOLERANCE_SECONDS = 0.5


@dataclass
class VideoIntegrityReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _probe_streams(path: str) -> dict:
    """Renvoie le JSON ffprobe (durees/offsets par piste + duree globale
    du conteneur). Leve RuntimeError si ffprobe echoue ou renvoie du
    JSON invalide -- jamais silencieux, appele uniquement apres
    has_ffmpeg() par integrity_job_runner.py."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration:stream=codec_type,start_time,duration",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ffprobe a échoué (code {proc.returncode}).")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"sortie ffprobe illisible : {exc}") from exc


def verify_video_file(
    path: str,
    *,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> VideoIntegrityReport:
    """Verifie UN fichier video : decode complet (corruption), duree
    reelle vs annoncee (troncature), desync audio/video au demarrage.
    `on_progress(percent)` (0-99 pendant le decodage, jamais 100 --
    reserve a l'appelant une fois le rapport final construit) est
    appele au fil du decodage via -progress pipe:1. `cancel_event` :
    si fourni et positionne, termine le sous-processus ffmpeg et leve
    OperationCancelled (meme mecanisme que commit_job_runner.py)."""
    try:
        probe = _probe_streams(path)
    except RuntimeError as exc:
        return VideoIntegrityReport(passed=False, errors=[f"Fichier illisible par ffprobe : {exc}"])

    total_duration = float(probe.get("format", {}).get("duration", 0.0) or 0.0)
    streams = probe.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    errors: list[str] = []
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-xerror", "-i", path, "-map", "0",
         "-f", "null", "-progress", "pipe:1", "-nostats", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    last_out_time_seconds = 0.0
    for line in proc.stdout:
        if cancel_event is not None and cancel_event.is_set():
            proc.terminate()
            proc.wait()
            raise OperationCancelled("Vérification annulée.")
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                last_out_time_seconds = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            if on_progress is not None and total_duration > 0:
                on_progress(min(99.0, 100.0 * last_out_time_seconds / total_duration))

    stderr_output = proc.stderr.read()
    returncode = proc.wait()

    if returncode != 0:
        stderr_lines = [line for line in stderr_output.splitlines() if line.strip()]
        if stderr_lines:
            errors.extend(f"Erreur de décodage : {line}" for line in stderr_lines)
        else:
            errors.append(f"Décodage interrompu (code {returncode}).")

    if total_duration > 0 and (total_duration - last_out_time_seconds) > DURATION_TOLERANCE_SECONDS:
        errors.append(
            f"Durée réelle ({last_out_time_seconds:.1f}s) très inférieure à la durée "
            f"annoncée ({total_duration:.1f}s) — fichier probablement tronqué."
        )

    if video_stream is not None and audio_stream is not None:
        video_start = float(video_stream.get("start_time", 0.0) or 0.0)
        audio_start = float(audio_stream.get("start_time", 0.0) or 0.0)
        gap = abs(video_start - audio_start)
        if gap > AV_SYNC_TOLERANCE_SECONDS:
            errors.append(f"Décalage audio/vidéo détecté ({gap:.2f}s) au démarrage.")

    return VideoIntegrityReport(passed=len(errors) == 0, errors=errors)


def verify_staged_media(
    staged_path: str,
    *,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> VideoIntegrityReport:
    """staged_path : UN fichier (film) ou UN dossier (serie / pack de
    saisons, voir upload_prep.CommitResult.staged_path). Enumere tous
    les fichiers video (extract.VIDEO_EXTS) recursivement et agrege un
    rapport par fichier en un seul VideoIntegrityReport -- erreurs/
    warnings prefixes du nom de fichier pour rester lisibles sur un pack
    multi-fichiers."""
    root = Path(staged_path)
    if root.is_file():
        files = [root]
    else:
        files = sorted(p for p in root.rglob("*") if p.suffix.lower() in VIDEO_EXTS)

    if not files:
        return VideoIntegrityReport(passed=False, errors=[f"Aucun fichier vidéo trouvé dans {staged_path}."])

    all_errors: list[str] = []
    all_warnings: list[str] = []
    for index, file in enumerate(files):
        def file_progress(percent: float, index: int = index) -> None:
            if on_progress is not None:
                on_progress(100.0 * (index + percent / 100.0) / len(files))

        report = verify_video_file(
            str(file), on_progress=file_progress if on_progress else None, cancel_event=cancel_event,
        )
        all_errors.extend(f"[{file.name}] {e}" for e in report.errors)
        all_warnings.extend(f"[{file.name}] {w}" for w in report.warnings)

    return VideoIntegrityReport(passed=len(all_errors) == 0, errors=all_errors, warnings=all_warnings)
