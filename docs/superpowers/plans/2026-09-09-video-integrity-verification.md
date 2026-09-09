# Vérification approfondie du fichier vidéo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avant tout upload DIRECT C411 (manuel aujourd'hui, prérequis
pour l'automatisation à venir), vérifier que le fichier vidéo est
réellement lisible de bout en bout (décodage réel, pas juste les
en-têtes du conteneur), que sa durée réelle correspond à celle
annoncée, et que ses pistes audio/vidéo restent synchronisées.

**Architecture:** Nouveau module pur `nfogen/video_integrity.py`
(ffprobe pour les métadonnées par piste, `ffmpeg -v error -f null -`
pour un décodage réel détectant la corruption) ; nouveau job de fond
`nfogen/integrity_job_runner.py` (même patron que
`commit_job_runner.py`, thread + `job_id` + polling) ; 3 nouveaux
endpoints HTTP ; intégration dans `UploadPrepPanel.tsx` uniquement sur
le clic "Uploader directement" (jamais "Créer un brouillon").

**Tech Stack:** Python (subprocess vers `ffmpeg`/`ffprobe`, aucune
nouvelle dépendance pip — stdlib uniquement), FastAPI, React/TypeScript.

**Spec:** [docs/superpowers/specs/2026-09-09-video-integrity-verification-design.md](../specs/2026-09-09-video-integrity-verification-design.md)

## Global Constraints

- Seuil de troncature : durée annoncée − durée réellement décodée **> 5.0 secondes** ⇒ erreur bloquante.
- Seuil de désync A/V : écart entre `start_time` vidéo et `start_time` audio **> 0.5 seconde** ⇒ erreur bloquante.
- Toute `errors` non vide ⇒ `VideoIntegrityReport.passed = False` — jamais de dégradation en brouillon, jamais d'upload malgré une erreur : bloqué complètement, signalé pour action manuelle.
- Cette vérification ne s'applique **jamais** au bouton "Créer un brouillon" — uniquement à "Uploader directement".
- `ffmpeg`/`ffprobe` absents du serveur ⇒ `RuntimeError` explicite depuis `integrity_job_runner.start()`, jamais un job qui échoue en silence.
- Aucune nouvelle dépendance pip : `subprocess` (stdlib) uniquement, comme le reste du projet appelle des outils externes.

---

## Task 1 : `video_integrity.py` — structures de données et détection ffmpeg

**Files:**
- Create: `nfogen/video_integrity.py`
- Test: `tests/test_video_integrity.py`

**Interfaces:**
- Produces: `VideoIntegrityReport(passed: bool, errors: list[str] = [], warnings: list[str] = [])` (dataclass), `has_ffmpeg() -> bool`, constantes `DURATION_TOLERANCE_SECONDS = 5.0`, `AV_SYNC_TOLERANCE_SECONDS = 0.5`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests de nfogen.video_integrity (AUTOMATION.md, sous-projet 7 --
verification approfondie du fichier video). Meme convention que
tests/test_c411.py pour les tests necessitant un vrai ffmpeg."""
from __future__ import annotations

import shutil

import pytest

from nfogen import video_integrity

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_video_integrity_report_defaults_to_empty_lists():
    report = video_integrity.VideoIntegrityReport(passed=True)
    assert report.errors == []
    assert report.warnings == []


def test_has_ffmpeg_reflects_environment():
    assert video_integrity.has_ffmpeg() == HAS_FFMPEG
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_integrity.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.video_integrity'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Verification physique du fichier video avant un upload DIRECT C411
(jamais un brouillon) -- AUTOMATION.md, sous-projet 7 (repris
2026-09-09). Complementaire (pas un doublon) des verifications de
conformite tracker deja existantes (name_proposal.py, groupe
GroupProposal.blocked) : ici on verifie que le fichier lui-meme est
reellement lisible de bout en bout, pas les regles de nommage/categorie.

Necessite ffmpeg + ffprobe sur le PATH (voir has_ffmpeg()) -- deja
utilise comme outil de TEST dans tests/test_c411.py (HAS_FFMPEG), promu
ici en dependance d'execution reelle (voir Dockerfile/README)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field

DURATION_TOLERANCE_SECONDS = 5.0
AV_SYNC_TOLERANCE_SECONDS = 0.5


@dataclass
class VideoIntegrityReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_video_integrity.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add nfogen/video_integrity.py tests/test_video_integrity.py
git commit -m "feat: video_integrity.py -- structures de base + has_ffmpeg()"
```

---

## Task 2 : `video_integrity.py` — `verify_video_file()` (décodage réel, durée, désync)

**Files:**
- Modify: `nfogen/video_integrity.py`
- Modify: `tests/test_video_integrity.py`

**Interfaces:**
- Consumes: `VideoIntegrityReport`, `DURATION_TOLERANCE_SECONDS`, `AV_SYNC_TOLERANCE_SECONDS` (Task 1), `nfogen.cancellation.OperationCancelled` (déjà dans le repo, `nfogen/cancellation.py`).
- Produces: `verify_video_file(path: str, *, on_progress: Optional[Callable[[float], None]] = None, cancel_event: Optional[threading.Event] = None) -> VideoIntegrityReport`.

- [ ] **Step 1: Write the failing tests (logique mockée)**

Ajouter à `tests/test_video_integrity.py` :

```python
import subprocess
import threading

from nfogen.cancellation import OperationCancelled


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_ffprobe_json(duration="10.000000", video_start="0.000000", audio_start="0.000000"):
    import json

    return json.dumps({
        "streams": [
            {"codec_type": "video", "start_time": video_start, "duration": duration},
            {"codec_type": "audio", "start_time": audio_start, "duration": duration},
        ],
        "format": {"duration": duration},
    })


class _FakePopen:
    """Simule subprocess.Popen pour l'appel ffmpeg -- stdout produit des
    lignes 'out_time_ms=' comme -progress pipe:1, stderr/returncode
    configurables par test."""

    def __init__(self, out_time_ms_lines, returncode=0, stderr=""):
        self.stdout = iter([f"out_time_ms={v}\n" for v in out_time_ms_lines])
        self._stderr_text = stderr
        self._returncode = returncode
        self.terminated = False

    class _Stderr:
        def __init__(self, text):
            self._text = text

        def read(self):
            return self._text

    @property
    def stderr(self):
        return self._Stderr(self._stderr_text)

    @stderr.setter
    def stderr(self, value):
        pass

    def wait(self):
        return self._returncode

    def terminate(self):
        self.terminated = True


def test_verify_video_file_passes_when_decode_is_clean(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: __import__("json").loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[5_000_000, 10_000_000], returncode=0),
    )

    report = video_integrity.verify_video_file("clean.mkv")
    assert report.passed is True
    assert report.errors == []


def test_verify_video_file_fails_when_ffprobe_cannot_read_file(monkeypatch):
    def _raise(path):
        raise RuntimeError("moov atom not found")

    monkeypatch.setattr("nfogen.video_integrity._probe_streams", _raise)

    report = video_integrity.verify_video_file("broken.mkv")
    assert report.passed is False
    assert "ffprobe" in report.errors[0]
    assert "moov atom not found" in report.errors[0]


def test_verify_video_file_fails_on_decode_error_stderr(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: __import__("json").loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(
            out_time_ms_lines=[10_000_000], returncode=1,
            stderr="Error while decoding stream #0:0\n",
        ),
    )

    report = video_integrity.verify_video_file("corrupt.mkv")
    assert report.passed is False
    assert any("Error while decoding" in e for e in report.errors)


def test_verify_video_file_fails_when_truncated(monkeypatch):
    # Duree annoncee 10s, mais le decodage s'arrete a 3s -- ecart > 5s (tolerance).
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: __import__("json").loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[3_000_000], returncode=0),
    )

    report = video_integrity.verify_video_file("truncated.mkv")
    assert report.passed is False
    assert any("tronqué" in e for e in report.errors)


def test_verify_video_file_fails_when_av_desync(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: __import__("json").loads(
            _fake_ffprobe_json(duration="10.000000", video_start="0.000000", audio_start="1.200000")
        ),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[10_000_000], returncode=0),
    )

    report = video_integrity.verify_video_file("desync.mkv")
    assert report.passed is False
    assert any("Décalage audio/vidéo" in e for e in report.errors)


def test_verify_video_file_reports_progress(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: __import__("json").loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[5_000_000, 10_000_000], returncode=0),
    )
    seen: list[float] = []

    video_integrity.verify_video_file("clean.mkv", on_progress=seen.append)
    assert seen == [50.0, 99.0]


def test_verify_video_file_cancellation_terminates_process(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: __import__("json").loads(_fake_ffprobe_json(duration="10.000000")),
    )
    fake_proc = _FakePopen(out_time_ms_lines=[1_000_000, 2_000_000, 3_000_000], returncode=0)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: fake_proc)

    cancel_event = threading.Event()
    cancel_event.set()  # deja annule avant meme de lire la premiere ligne

    with pytest.raises(OperationCancelled):
        video_integrity.verify_video_file("clean.mkv", cancel_event=cancel_event)
    assert fake_proc.terminated is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_video_integrity.py -v`
Expected: FAIL — `AttributeError: module 'nfogen.video_integrity' has no attribute '_probe_streams'` (et `verify_video_file` inconnu)

- [ ] **Step 3: Write the implementation**

Ajouter à `nfogen/video_integrity.py` :

```python
import json
import subprocess
import threading
from typing import Callable, Optional

from .cancellation import OperationCancelled


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_video_integrity.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Write real-ffmpeg integration tests**

Ajouter à `tests/test_video_integrity.py` (clip synthétique, même patron
que `tests/test_c411.py`) :

```python
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe requis")
def test_verify_video_file_real_clean_clip_passes(tmp_path):
    clip = tmp_path / "clean.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
        check=True,
    )
    report = video_integrity.verify_video_file(str(clip))
    assert report.passed is True


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe requis")
def test_verify_video_file_real_truncated_clip_fails(tmp_path):
    clip = tmp_path / "truncated.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
        check=True,
    )
    # Coupe le fichier a la moitie de ses octets -- simule un
    # telechargement incomplet (le conteneur annonce toujours 3s).
    data = clip.read_bytes()
    clip.write_bytes(data[: len(data) // 2])

    report = video_integrity.verify_video_file(str(clip))
    assert report.passed is False
```

- [ ] **Step 6: Run the real-ffmpeg tests**

Run: `pytest tests/test_video_integrity.py -v -k real`
Expected: PASS (2 tests) si `ffmpeg`/`ffprobe` sont installés localement,
SKIPPED sinon.

- [ ] **Step 7: Commit**

```bash
git add nfogen/video_integrity.py tests/test_video_integrity.py
git commit -m "feat: video_integrity.verify_video_file -- decode reel, duree, desync A/V"
```

---

## Task 3 : `video_integrity.py` — `verify_staged_media()` (agrégation multi-fichiers)

**Files:**
- Modify: `nfogen/video_integrity.py`
- Modify: `tests/test_video_integrity.py`

**Interfaces:**
- Consumes: `verify_video_file()` (Task 2), `extract.VIDEO_EXTS` (déjà dans `nfogen/extract.py`).
- Produces: `verify_staged_media(staged_path: str, *, on_progress: Optional[Callable[[float], None]] = None, cancel_event: Optional[threading.Event] = None) -> VideoIntegrityReport`.

- [ ] **Step 1: Write the failing tests**

```python
def test_verify_staged_media_single_file_delegates_to_verify_video_file(monkeypatch, tmp_path):
    movie = tmp_path / "Movie.mkv"
    movie.write_bytes(b"x")
    captured = {}

    def fake_verify(path, *, on_progress=None, cancel_event=None):
        captured["path"] = path
        return video_integrity.VideoIntegrityReport(passed=True)

    monkeypatch.setattr("nfogen.video_integrity.verify_video_file", fake_verify)

    report = video_integrity.verify_staged_media(str(movie))
    assert report.passed is True
    assert captured["path"] == str(movie)


def test_verify_staged_media_directory_aggregates_all_video_files(monkeypatch, tmp_path):
    (tmp_path / "S05").mkdir()
    ep1 = tmp_path / "S05" / "ep01.mkv"
    ep2 = tmp_path / "S05" / "ep02.mkv"
    ep1.write_bytes(b"x")
    ep2.write_bytes(b"x")
    (tmp_path / "S05" / "readme.txt").write_text("pas une video")

    def fake_verify(path, *, on_progress=None, cancel_event=None):
        if path.endswith("ep02.mkv"):
            return video_integrity.VideoIntegrityReport(passed=False, errors=["corrompu"])
        return video_integrity.VideoIntegrityReport(passed=True)

    monkeypatch.setattr("nfogen.video_integrity.verify_video_file", fake_verify)

    report = video_integrity.verify_staged_media(str(tmp_path))
    assert report.passed is False
    assert any("ep02.mkv" in e and "corrompu" in e for e in report.errors)


def test_verify_staged_media_no_video_files_found(tmp_path):
    (tmp_path / "notes.txt").write_text("rien a voir")
    report = video_integrity.verify_staged_media(str(tmp_path))
    assert report.passed is False
    assert "Aucun fichier vidéo trouvé" in report.errors[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_video_integrity.py -v -k staged_media`
Expected: FAIL — `AttributeError: ... has no attribute 'verify_staged_media'`

- [ ] **Step 3: Write the implementation**

Ajouter à `nfogen/video_integrity.py` :

```python
from pathlib import Path

from .extract import VIDEO_EXTS


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_video_integrity.py -v`
Expected: PASS (toutes)

- [ ] **Step 5: Commit**

```bash
git add nfogen/video_integrity.py tests/test_video_integrity.py
git commit -m "feat: video_integrity.verify_staged_media -- agregation fichier/dossier"
```

---

## Task 4 : `nfogen/integrity_job_runner.py`

**Files:**
- Create: `nfogen/integrity_job_runner.py`
- Test: `tests/test_integrity_job_runner.py`

**Interfaces:**
- Consumes: `video_integrity.has_ffmpeg()`, `video_integrity.verify_staged_media()` (Task 3), `nfogen.cancellation.OperationCancelled`.
- Produces: `start(staged_path: str) -> str` (job_id, lève `RuntimeError` si `has_ffmpeg()` est faux), `status(job_id: str) -> Optional[dict]`, `cancel(job_id: str) -> bool`. Dict de statut : `{"job_id", "state", "percent", "started_at", "finished_at", "error", "result"}` — `state` ∈ `"verifying"|"done"|"error"|"cancelled"`, `result` = `{"passed", "errors", "warnings"}` ou `None`.

- [ ] **Step 1: Write the failing tests**

```python
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


class _Report:
    def __init__(self, passed, errors, warnings):
        self.passed = passed
        self.errors = errors
        self.warnings = warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_integrity_job_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.integrity_job_runner'`

- [ ] **Step 3: Write the implementation**

```python
"""Execution en tache de fond de video_integrity.verify_staged_media()
(AUTOMATION.md, sous-projet 7 -- verification approfondie) : meme patron
que commit_job_runner.py (plusieurs taches en parallele, job_id par
appel a start(), etat en memoire uniquement -- une tache interrompue par
un redemarrage du serveur est simplement perdue)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from . import video_integrity
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
    silencieusement plus tard pour cette seule raison."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_integrity_job_runner.py -v`
Expected: PASS (toutes)

- [ ] **Step 5: Commit**

```bash
git add nfogen/integrity_job_runner.py tests/test_integrity_job_runner.py
git commit -m "feat: integrity_job_runner.py -- verification en tache de fond"
```

---

## Task 5 : Endpoints HTTP (`nfogen/api.py`)

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `integrity_job_runner.start()/status()/cancel()` (Task 4), `_require_gapscan_available()` (existant, `nfogen/api.py:687`).
- Produces: `POST /gapscan/verify-integrity` → `{"job_id": str}` (400 si `RuntimeError`, via `_run_upload_prep`) ; `GET /gapscan/integrity-jobs/{job_id}` → dict de statut (404 si inconnu) ; `POST /gapscan/integrity-jobs/{job_id}/cancel` → `{"status": "cancelling"}` (404 si inconnu, 409 si déjà terminé).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_api.py` (à la suite des tests `commit-jobs`
existants) :

```python
def test_verify_integrity_returns_job_id(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod.integrity_job_runner, "start", lambda staged_path: "job-1")
    client = TestClient(mod.app)

    resp = client.post("/gapscan/verify-integrity", json={"staged_path": "/staging/movie.mkv"})
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-1"}


def test_verify_integrity_400_when_ffmpeg_absent(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)

    def fake_start(staged_path):
        raise RuntimeError("ffmpeg/ffprobe requis pour la vérification — non trouvés sur le serveur nfogen.")

    monkeypatch.setattr(mod.integrity_job_runner, "start", fake_start)
    client = TestClient(mod.app)

    resp = client.post("/gapscan/verify-integrity", json={"staged_path": "/staging/movie.mkv"})
    assert resp.status_code == 400
    assert "ffmpeg" in resp.json()["detail"]


def test_integrity_job_status_404_for_unknown_job(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/integrity-jobs/does-not-exist")
    assert resp.status_code == 404


def test_integrity_job_status_returns_job(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    fake_status = {
        "job_id": "job-1", "state": "done", "percent": 100.0,
        "started_at": 1.0, "finished_at": 2.0, "error": None,
        "result": {"passed": True, "errors": [], "warnings": []},
    }
    monkeypatch.setattr(mod.integrity_job_runner, "status", lambda job_id: fake_status)
    client = TestClient(mod.app)

    resp = client.get("/gapscan/integrity-jobs/job-1")
    assert resp.status_code == 200
    assert resp.json() == fake_status


def test_cancel_integrity_job_unknown_is_404(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/integrity-jobs/does-not-exist/cancel")
    assert resp.status_code == 404


def test_cancel_integrity_job_already_finished_is_409(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(
        mod.integrity_job_runner, "status",
        lambda job_id: {"job_id": job_id, "state": "done", "percent": 100.0,
                         "started_at": 1.0, "finished_at": 2.0, "error": None, "result": None},
    )
    client = TestClient(mod.app)

    resp = client.post("/gapscan/integrity-jobs/job-1/cancel")
    assert resp.status_code == 409


def test_cancel_integrity_job_cancels(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(
        mod.integrity_job_runner, "status",
        lambda job_id: {"job_id": job_id, "state": "verifying", "percent": 10.0,
                         "started_at": 1.0, "finished_at": None, "error": None, "result": None},
    )
    cancelled = []
    monkeypatch.setattr(mod.integrity_job_runner, "cancel", lambda job_id: cancelled.append(job_id) or True)
    client = TestClient(mod.app)

    resp = client.post("/gapscan/integrity-jobs/job-1/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelling"}
    assert cancelled == ["job-1"]


def test_verify_integrity_endpoints_501_without_gapscan_extra(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)

    assert client.post("/gapscan/verify-integrity", json={"staged_path": "x"}).status_code == 501
    assert client.get("/gapscan/integrity-jobs/x").status_code == 501
    assert client.post("/gapscan/integrity-jobs/x/cancel").status_code == 501


def test_verify_integrity_endpoints_401_without_token(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret")
    client = TestClient(mod.app)

    assert client.post("/gapscan/verify-integrity", json={"staged_path": "x"}).status_code == 401
    assert client.get("/gapscan/integrity-jobs/x").status_code == 401
    assert client.post("/gapscan/integrity-jobs/x/cancel").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k integrity`
Expected: FAIL — `AttributeError: module 'nfogen.api' has no attribute 'integrity_job_runner'` (404 partout, endpoints inconnus)

- [ ] **Step 3: Write the implementation**

Dans `nfogen/api.py`, ajouter `integrity_job_runner` au bloc d'import
optionnel existant (`nfogen/api.py:57-66`) :

```python
    from . import (
        commit_job_runner,
        gapscan,
        gapscan_config_store,
        gapscan_library,
        gapscan_runner,
        integrity_job_runner,
        tracker_profile,
        upload_history_store,
        upload_prep,
    )
```

Puis, à la suite des endpoints `commit-jobs` existants
(`nfogen/api.py`, après `gapscan_commit_job_cancel`) :

```python
class VerifyIntegrityRequest(BaseModel):
    staged_path: str


@app.post("/gapscan/verify-integrity", dependencies=[Depends(require_token)])
def gapscan_verify_integrity(req: VerifyIntegrityRequest) -> dict[str, str]:
    """Demarre la verification approfondie EN TACHE DE FOND (AUTOMATION.md,
    sous-projet 7) -- renvoie un job_id immediatement, suivi via
    GET /gapscan/integrity-jobs/{job_id}. `ffmpeg`/`ffprobe` absents du
    serveur -> 400 immediat (voir integrity_job_runner.start())."""
    _require_gapscan_available()
    job_id = _run_upload_prep(integrity_job_runner.start, req.staged_path)
    return {"job_id": job_id}


@app.get("/gapscan/integrity-jobs/{job_id}", dependencies=[Depends(require_token)])
def gapscan_integrity_job_status(job_id: str) -> dict[str, Any]:
    _require_gapscan_available()
    status = integrity_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    return status


@app.post("/gapscan/integrity-jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def gapscan_integrity_job_cancel(job_id: str) -> dict[str, str]:
    _require_gapscan_available()
    status = integrity_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    if status["state"] in ("done", "error", "cancelled"):
        raise HTTPException(status_code=409, detail="Cette tâche est déjà terminée.")
    integrity_job_runner.cancel(job_id)
    return {"status": "cancelling"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k integrity`
Expected: PASS (toutes)

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`
Expected: PASS (aucune régression)

- [ ] **Step 6: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: endpoints /gapscan/verify-integrity + /gapscan/integrity-jobs/*"
```

---

## Task 6 : Frontend — types et client API

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: type `IntegrityJobState`, interface `VideoIntegrityReport`, interface `IntegrityJob` (`types.ts`) ; fonctions `verifyIntegrity(stagedPath: string): Promise<{ job_id: string }>`, `integrityJobStatus(jobId: string): Promise<IntegrityJob>`, `cancelIntegrityJob(jobId: string): Promise<{ status: string }>` (`client.ts`).

- [ ] **Step 1: Add the types**

Dans `frontend/src/api/types.ts`, à la suite de l'interface `CommitJob`
existante :

```typescript
/** POST /gapscan/verify-integrity + GET /gapscan/integrity-jobs/{id}
 * (AUTOMATION.md, sous-projet 7 -- verification approfondie du fichier
 * video). Meme patron que CommitJob : tache de fond suivie en polling,
 * jamais de blocage de la page sur un gros fichier. */
export type IntegrityJobState = "verifying" | "done" | "error" | "cancelled";

export interface VideoIntegrityReport {
  passed: boolean;
  errors: string[];
  warnings: string[];
}

export interface IntegrityJob {
  job_id: string;
  state: IntegrityJobState;
  /** 0-100. */
  percent: number;
  started_at: number;
  finished_at: number | null;
  /** Erreur d'EXECUTION du job (ffmpeg absent, exception) -- distincte
   * d'un rapport `result.passed = false` (echec de VERIFICATION). */
  error: string | null;
  result: VideoIntegrityReport | null;
}
```

- [ ] **Step 2: Add the client functions**

Dans `frontend/src/api/client.ts`, à la suite de `cancelCommitJob` :

```typescript
/** Demarre la verification approfondie EN TACHE DE FOND (AUTOMATION.md,
 * sous-projet 7) -- renvoie un job_id immediatement, suivi via
 * integrityJobStatus(). Jamais appelee pour un brouillon, uniquement
 * avant "Uploader directement" (voir UploadPrepPanel.tsx). */
export function verifyIntegrity(stagedPath: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>("/gapscan/verify-integrity", {
    method: "POST",
    body: JSON.stringify({ staged_path: stagedPath }),
  });
}

export function integrityJobStatus(jobId: string): Promise<IntegrityJob> {
  return request<IntegrityJob>(`/gapscan/integrity-jobs/${encodeURIComponent(jobId)}`);
}

export function cancelIntegrityJob(jobId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/gapscan/integrity-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
```

Ajouter `IntegrityJob` à l'import de types en haut du fichier (bloc
`import type { ... } from "./types";`), par ordre alphabétique.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: aucune erreur (ces fonctions ne sont pas encore appelées,
juste définies — Task 7 les branche)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat(frontend): types + client pour la verification d'integrite"
```

---

## Task 7 : Frontend — `UploadPrepPanel.tsx` vérifie avant "Uploader directement"

**Files:**
- Modify: `frontend/src/components/UploadPrepPanel.tsx`
- Modify: `frontend/src/components/UploadPrepPanel.test.tsx`

**Interfaces:**
- Consumes: `verifyIntegrity`, `integrityJobStatus`, `cancelIntegrityJob` (Task 6), `IntegrityJob` (Task 6).
- Produces: aucune nouvelle prop publique — comportement interne de `handleSend(index, direct)` modifié uniquement pour `direct === true`.

- [ ] **Step 1: Write the failing tests**

Ajouter à `frontend/src/components/UploadPrepPanel.test.tsx`, à la
suite des tests "Uploader directement" existants. Étendre d'abord le
mock du module (`vi.mock("../api/client", ...)`) avec les 3 nouvelles
fonctions :

```typescript
vi.mock("../api/client", () => ({
  prepareUploadPreview: vi.fn(),
  prepareUploadCommit: vi.fn(),
  commitJobStatus: vi.fn(),
  cancelCommitJob: vi.fn(),
  sendToTracker: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
  verifyIntegrity: vi.fn(),
  integrityJobStatus: vi.fn(),
  cancelIntegrityJob: vi.fn(),
}));
```

Et à l'import correspondant :

```typescript
import {
  cancelCommitJob,
  cancelIntegrityJob,
  commitJobStatus,
  integrityJobStatus,
  listAllProfiles,
  prepareUploadCommit,
  prepareUploadPreview,
  readManagedProfile,
  sendToTracker,
  verifyIntegrity,
} from "../api/client";
```

Dans `beforeEach`, ajouter `vi.mocked(verifyIntegrity).mockReset();` /
`vi.mocked(integrityJobStatus).mockReset();` /
`vi.mocked(cancelIntegrityJob).mockReset();` aux resets existants.

Nouveaux tests (après le test existant `"Uploader directement demande
confirmation, appelle sendToTracker avec direct:true, ..."`, en
reprenant le même helper `renderPanel`/`ONE_GROUP`/`DONE_JOB` déjà
présents dans le fichier) :

```typescript
it("Uploader directement lance d'abord une verification d'integrite avant sendToTracker", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(verifyIntegrity).mockResolvedValue({ job_id: "integrity-1" });
  vi.mocked(integrityJobStatus).mockResolvedValue({
    job_id: "integrity-1", state: "done", percent: 100,
    started_at: 1, finished_at: 2, error: null,
    result: { passed: true, errors: [], warnings: [] },
  });
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: null, draft_url: "https://c411.org/torrents/1", duplicate_warning: null,
    presentation_warning: null, seed_warning: null,
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Uploader directement" }));

  await waitFor(() => {
    expect(verifyIntegrity).toHaveBeenCalledWith(DONE_JOB.result.staged_path);
  });
  await waitFor(() => {
    expect(sendToTracker).toHaveBeenCalled();
  });
  expect(await screen.findByText(/Uploadé directement/)).toBeInTheDocument();
});

it("bloque l'upload direct si la verification d'integrite echoue, n'appelle jamais sendToTracker", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(verifyIntegrity).mockResolvedValue({ job_id: "integrity-1" });
  vi.mocked(integrityJobStatus).mockResolvedValue({
    job_id: "integrity-1", state: "done", percent: 100,
    started_at: 1, finished_at: 2, error: null,
    result: { passed: false, errors: ["Fichier probablement tronqué."], warnings: [] },
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Uploader directement" }));

  expect(await screen.findByText(/Fichier probablement tronqué/)).toBeInTheDocument();
  expect(sendToTracker).not.toHaveBeenCalled();
});

it("Creer un brouillon n'appelle jamais verifyIntegrity", async () => {
  const user = userEvent.setup();
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: "d1", draft_url: "https://c411.org/drafts/1", duplicate_warning: null,
    presentation_warning: null, seed_warning: null,
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Créer un brouillon" }));

  await waitFor(() => expect(sendToTracker).toHaveBeenCalled());
  expect(verifyIntegrity).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: FAIL — `verifyIntegrity`/`integrityJobStatus` jamais appelés
(le premier nouveau test échoue sur l'assertion `toHaveBeenCalledWith`)

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/components/UploadPrepPanel.tsx` :

```typescript
import { cancelCommitJob, cancelIntegrityJob, commitJobStatus, integrityJobStatus, prepareUploadCommit, prepareUploadPreview, sendToTracker, verifyIntegrity } from "../api/client";
import { ApiError } from "../api/types";
import type {
  CommitJob,
  IntegrityJob,
  SeasonPackRequest,
  SendToTrackerResult,
  UploadCommitResult,
  UploadGroupProposal,
} from "../api/types";
```

Ajouter un état pour la vérification en cours, à la suite des états
`sendResults`/`sendErrors` existants :

```typescript
  // Verification d'integrite AVANT un upload direct (AUTOMATION.md,
  // sous-projet 7) -- jamais pour un brouillon. Cle : par index de
  // groupe, comme les autres etats de ce composant.
  const [integrityJobs, setIntegrityJobs] = useState<Record<number, IntegrityJob>>({});
  const [integrityErrors, setIntegrityErrors] = useState<Record<number, string>>({});
```

Ajouter, à la suite de `handleCancel` :

```typescript
  async function pollIntegrityUntilTerminal(index: number, jobId: string): Promise<IntegrityJob> {
    for (;;) {
      const job = await integrityJobStatus(jobId);
      setIntegrityJobs((prev) => ({ ...prev, [index]: job }));
      if (TERMINAL_STATES.includes(job.state)) return job;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }

  async function handleCancelIntegrity(index: number) {
    const job = integrityJobs[index];
    if (!job) return;
    try {
      await cancelIntegrityJob(job.job_id);
    } catch {
      // best effort -- le prochain poll reflete l'etat reel de toute facon
    }
  }
```

Remplacer `handleSend` par :

```typescript
  async function handleSend(index: number, direct: boolean) {
    const commit = commitResults[index];
    if (!commit) return;
    // Upload direct : part reellement en moderation (POST /api/torrents,
    // retour d'un membre de l'equipe C411, 2026-09-07) -- une derniere
    // confirmation, contrairement au brouillon qui reste toujours privé.
    if (direct && !confirm("Uploader directement sur C411 (hors brouillon) ? Ça part réellement en modération.")) {
      return;
    }
    setSending({ index, direct });
    setSendErrors((prev) => ({ ...prev, [index]: "" }));
    setIntegrityErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      // Verification approfondie (AUTOMATION.md, sous-projet 7) --
      // UNIQUEMENT pour un upload direct, jamais un brouillon (qui reste
      // toujours privé tant que l'utilisateur ne le finalise pas
      // lui-meme sur le site).
      if (direct) {
        const { job_id } = await verifyIntegrity(commit.staged_path);
        const job = await pollIntegrityUntilTerminal(index, job_id);
        setIntegrityJobs((prev) => {
          const next = { ...prev };
          delete next[index];
          return next;
        });
        if (job.state !== "done" || !job.result?.passed) {
          const message =
            job.state === "cancelled"
              ? null
              : job.state === "error"
                ? (job.error ?? "Vérification impossible.")
                : (job.result?.errors.join(" ") ?? "Vérification échouée.");
          if (message) {
            setIntegrityErrors((prev) => ({ ...prev, [index]: message }));
          }
          return;
        }
      }
      const result = await sendToTracker({
        releaseName: commit.release_name,
        stagedPath: commit.staged_path,
        torrentPath: commit.torrent_path,
        nfoPath: commit.nfo_path,
        profile,
        mediaType,
        radarrMovieId: radarrMovieId ?? undefined,
        sonarrSeriesId: sonarrSeriesId ?? undefined,
        tmdbId: tmdbId ?? undefined,
        tvdbId: tvdbId ?? undefined,
        genre: genre ?? undefined,
        seasonNumber: seasonNumber ?? undefined,
        draftId: direct ? undefined : sendResults[index]?.draft_id,
        direct,
      });
      setSendResults((prev) => ({ ...prev, [index]: result }));
      setSentDirect((prev) => ({ ...prev, [index]: direct }));
    } catch (e) {
      setSendErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Envoi impossible.",
      }));
    } finally {
      setSending(null);
    }
  }
```

Enfin, dans le JSX, ajouter l'affichage de la progression/erreurs
juste après le bloc des boutons "Créer un brouillon"/"Uploader
directement" (avant `{sendErrors[index] && ...}`) :

```tsx
          {integrityJobs[index] && (
            <div className="space-y-1">
              <div className="h-2 w-full overflow-hidden rounded bg-surface-2">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${integrityJobs[index].percent}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-xs text-ink-dim">
                <span>Vérification du fichier… — {Math.round(integrityJobs[index].percent)}%</span>
                <button type="button" onClick={() => handleCancelIntegrity(index)} className="text-crit underline">
                  Annuler
                </button>
              </div>
            </div>
          )}
          {integrityErrors[index] && <p className="text-xs text-crit">⚠ {integrityErrors[index]}</p>}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: PASS (toutes)

- [ ] **Step 5: Run the full frontend suite + typecheck + lint**

Run: `cd frontend && npx vitest run && npx tsc -b --noEmit && npx oxlint`
Expected: PASS partout (aucune régression, aucune nouvelle erreur de
lint hormis les 2 avertissements pré-existants déjà connus)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UploadPrepPanel.tsx frontend/src/components/UploadPrepPanel.test.tsx
git commit -m "feat(frontend): verifie l'integrite du fichier avant un upload direct"
```

---

## Task 8 : Dépendance système + documentation

**Files:**
- Modify: `Dockerfile`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `AUTOMATION.md`

**Interfaces:**
- Consumes: rien de nouveau — documente ce qui a été livré dans les tâches 1 à 7.

- [ ] **Step 1: Ajouter `ffmpeg` au `Dockerfile`**

Dans `Dockerfile`, remplacer :

```dockerfile
# libmediainfo0v5 : dependance systeme requise par pymediainfo pour
# l'extraction video/audio (cf. README.md, section Installation).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*
```

par :

```dockerfile
# libmediainfo0v5 : dependance systeme requise par pymediainfo pour
# l'extraction video/audio (cf. README.md, section Installation).
# ffmpeg : verification approfondie du fichier avant un upload direct
# (nfogen/video_integrity.py, AUTOMATION.md sous-projet 7) -- decodage
# reel du flux, pas seulement les metadonnees du conteneur.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmediainfo0v5 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Ajouter `ffmpeg` au README (installation manuelle)**

Dans `README.md`, remplacer :

```bash
apt-get install libmediainfo0v5 mediainfo   # Debian/Ubuntu
```

par :

```bash
apt-get install libmediainfo0v5 mediainfo ffmpeg   # Debian/Ubuntu
```

- [ ] **Step 3: Vérifier que l'image Docker se construit toujours**

Run: `docker build -t nfogen-test .`
Expected: build réussi (aucune erreur `apt-get`)

- [ ] **Step 4: `CHANGELOG.md`**

Ajouter en tête de la section `### Ajouté` du `[Non publié]` :

```markdown
- **Vérification approfondie du fichier vidéo avant un upload direct**
  (AUTOMATION.md, sous-projet 7, brainstorm 2026-09-08/09 : "il faut que
  le média soit sûr de respecter les règles du profil/tracker [...]
  meme si il ny a rien de marqué faut trouvé a la limite declanché une
  verifi hardcore") : nouveau `nfogen/video_integrity.py` — décode
  réellement le fichier (`ffmpeg -v error -f null -`), compare durée
  réelle/annoncée (troncature) et offsets audio/vidéo (désync), en plus
  des métadonnées déjà fournies par MediaInfo. Tourne en tâche de fond
  (`nfogen/integrity_job_runner.py`, même patron que la mise en scène)
  avant **tout** clic "Uploader directement" — jamais pour "Créer un
  brouillon". Échec ⇒ bloqué complètement (ni brouillon ni upload),
  signalé pour action manuelle — jamais de dégradation silencieuse.
  Nouvelle dépendance système : `ffmpeg` (déjà utilisé comme outil de
  test dans le projet, promu ici en dépendance d'exécution réelle).
```

- [ ] **Step 5: `AUTOMATION.md`**

Ajouter une nouvelle section après "Sous-projet 9" (packs INTÉGRALE,
déjà présent) :

```markdown
## Sous-projet 7a : Vérification approfondie du fichier vidéo (conception et livraison 2026-09-09)

Reprise du sous-projet 7 original ("À concevoir" depuis 2026-08-27) —
brainstorm du 2026-09-08/09 a révélé qu'il regroupait en fait 4
sous-systèmes indépendants (vérification approfondie, règles de
résolution automatique, file d'attente un-par-un, email) : chacun son
cycle spec → plan → implémentation. Celui-ci est le premier, prérequis
de sécurité des trois autres.

**Prérequis avant tout upload direct** (manuel aujourd'hui, futur
pipeline automatique demain) : `nfogen/video_integrity.py` décode
réellement le fichier vidéo (`ffmpeg -v error -xerror -f null -`,
détecte la corruption qu'un en-tête de conteneur valide peut masquer),
compare la durée réellement décodée à celle annoncée par le conteneur
(`ffprobe`, tolérance 5s — détecte un fichier tronqué/téléchargement
incomplet) et l'offset de démarrage audio vs vidéo (tolérance 0.5s —
détecte une désynchronisation). Complémentaire, jamais un doublon, des
vérifications de conformité tracker déjà existantes
(`name_proposal.py`, `GroupProposal.blocked`).

Tourne en tâche de fond (`nfogen/integrity_job_runner.py`, même patron
que la mise en scène/génération de `.torrent`, sous-projet 4c) —
`ffmpeg -progress pipe:1` alimente une barre de progression réelle,
jamais un blocage de la page sur un gros fichier. Un échec (corruption,
troncature, désync) bloque **complètement** l'upload direct — ni
brouillon ni envoi, signalé pour action manuelle (le fichier source
reste probablement à re-télécharger via Sonarr/Radarr) — jamais de
dégradation silencieuse en brouillon comme pour une métadonnée TMDB
manquante (cas différent, déjà géré par ailleurs).

S'applique aussi bien à un upload direct manuel (bouton "Uploader
directement" existant) qu'au futur pipeline automatique — jamais à
"Créer un brouillon", qui reste privé tant que l'utilisateur ne le
finalise pas lui-même sur le site.

Nouvelle dépendance système : `ffmpeg` (fournit aussi `ffprobe`),
ajouté au `Dockerfile` et au README — déjà présent sur les runners
GitHub Actions (`ubuntu-latest`), déjà utilisé comme outil de *test*
dans le projet (`tests/test_c411.py`, génération de clips synthétiques
via `ffmpeg -f lavfi`) avant d'être promu ici en dépendance
d'exécution réelle.

Voir [docs/superpowers/specs/2026-09-09-video-integrity-verification-design.md](docs/superpowers/specs/2026-09-09-video-integrity-verification-design.md)
et [docs/superpowers/plans/2026-09-09-video-integrity-verification.md](docs/superpowers/plans/2026-09-09-video-integrity-verification.md).
```

- [ ] **Step 6: Run the full test suites one last time**

Run: `pytest -q && cd frontend && npx vitest run && npx tsc -b --noEmit && npx oxlint`
Expected: PASS partout

- [ ] **Step 7: Commit**

```bash
git add Dockerfile README.md CHANGELOG.md AUTOMATION.md
git commit -m "docs: verification approfondie -- Dockerfile/README/CHANGELOG/AUTOMATION.md"
```

---

## Après le plan

Une fois les 8 tâches livrées et poussées, poller GitHub Actions
jusqu'à `conclusion: success` sur le dernier commit (même discipline
que les sous-projets précédents), puis proposer d'enchaîner sur le
sous-projet suivant de la décomposition révisée (règles de résolution
automatique par profil, `rules.json`) — qui consommera
`video_integrity`/`integrity_job_runner` comme filet de sécurité avant
tout upload direct automatique.
