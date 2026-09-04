# Suivi d'avancement asynchrone de "Confirmer" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Ce projet interdit l'usage de sous-agents (mémoire projet "No subagents on nfogen") : exécution obligatoirement inline via superpowers:executing-plans, jamais subagent-driven-development.**

**Goal:** "Confirmer" (mise en scène + `.torrent`) s'exécute en tâche de fond avec suivi de progression en pourcentage (copie ET hash du torrent), plusieurs tâches en parallèle, annulation, et un encart "Transferts en cours" qui survit à un rechargement de page.

**Architecture:** Un nouveau registre de tâches en mémoire (`nfogen/commit_job_runner.py`, indexé par `job_id`, calqué sur `gapscan_runner.py`) exécute `upload_prep.commit_upload()` dans un thread par tâche. `commit_upload` gagne des callbacks adaptateurs (`on_progress`/`cancel_event`) qui convertissent les compteurs bruts de `file_staging.py` (octets) et `torrent_builder.py` (pièces torf) en un pourcentage par étape. `POST /gapscan/prepare-upload/commit` renvoie désormais `{job_id}` immédiatement ; le frontend interroge en polling (1500 ms) jusqu'à un état terminal.

**Tech Stack:** Python (threading, torf), TypeScript/React.

**Spec:** [docs/superpowers/specs/2026-09-04-async-commit-progress-design.md](../specs/2026-09-04-async-commit-progress-design.md) (approuvée par l'utilisateur, 2026-09-04).

## Global Constraints

- TDD strict : test qui échoue d'abord (RED confirmé pour la bonne raison), puis implémentation minimale, puis vert.
- Un commit par tâche. Suite complète (`pytest` + `ruff check`, puis `npx vitest run` + `npx tsc --noEmit -p tsconfig.app.json`) après toute tâche touchant un module partagé.
- **Aucun test existant ne doit régresser sans raison documentée.** Deux tests existants CHANGENT de comportement dans ce plan et sont explicitement mis à jour (Tâche 6) : `test_prepare_upload_commit_real_flow` (le corps de réponse change de forme) et le test `client.test.ts` équivalent côté frontend (Tâche 7). Tous les autres tests de `commit_upload`/`file_staging`/`torrent_builder` restent verts SANS modification (les nouveaux paramètres sont optionnels, valeur par défaut `None`).
- **Déviation assumée par rapport à la spec, à documenter dans le journal AUTOMATION.md en fin de plan** : la spec suggérait `torf.Torrent.generate(interval=1.0)` : ce plan utilise `interval=0` (rappelé après CHAQUE pièce hachée, pas throttlé dans le temps) — la spec elle-même flaguait cette valeur comme "ajustable", et `interval=0` rend le comportement déterministe et testable sans dépendre du timing, tout en restant raisonnable (le nombre de pièces d'un torrent reste modeste, contrairement à un flux d'octets).
- Taille de bloc de copie : **16 Mio** (`nfogen/file_staging.py`, constante `_COPY_CHUNK_SIZE`, ajustable).
- Cadence de polling frontend : **1500 ms**, identique à `GapScanPage.tsx` pour `gapscanStatus()`.

---

### Task 1: `nfogen/cancellation.py` + copie par blocs avec progression/annulation (`file_staging.py`)

**Files:**
- Create: `nfogen/cancellation.py`
- Modify: `nfogen/file_staging.py`
- Test: `tests/test_file_staging.py`

**Interfaces:**
- Produces: `OperationCancelled(RuntimeError)` (`nfogen/cancellation.py`) ; `stage_file(source_path, target_path, on_progress=None, cancel_event=None) -> str` ; `stage_files(source_paths, target_dir, names, on_progress=None, cancel_event=None) -> list[str]`. `on_progress: Optional[Callable[[int, int], None]]` reçoit `(bytes_done, bytes_total)`, appelé au moins une fois à la fin avec `bytes_done == bytes_total`. `cancel_event: Optional[threading.Event]` — si déjà positionné (ou positionné en cours de copie), lève `OperationCancelled` et supprime le fichier partiel.

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_file_staging.py`, ajouter en tête du fichier :

```python
import threading

from nfogen.cancellation import OperationCancelled
```

Puis ajouter (après les 4 tests existants) :

```python
def test_stage_file_hardlink_reports_progress_once(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"
    calls: list[tuple[int, int]] = []

    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert calls == [(len("contenu"), len("contenu"))]


def test_stage_file_copy_reports_progress_in_chunks(tmp_path, monkeypatch):
    import nfogen.file_staging as file_staging_module

    monkeypatch.setattr(file_staging_module, "_COPY_CHUNK_SIZE", 4)  # force plusieurs blocs
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")  # 10 octets, 4 par bloc -> 3 appels (4,4,2)
    target = tmp_path / "staged.mkv"
    calls: list[tuple[int, int]] = []

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert target.read_bytes() == b"0123456789"
    assert calls == [(4, 10), (8, 10), (10, 10)]


def test_stage_file_copy_cancellation_removes_partial_file_and_raises(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        stage_file(str(source), str(target), cancel_event=cancel_event)

    assert not target.exists()


def test_stage_files_aggregates_progress_across_multiple_files(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 20)
    target_dir = tmp_path / "staged" / "Release.Name"
    calls: list[tuple[int, int]] = []

    stage_files(
        [str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"],
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls[-1] == (30, 30)  # tout copie a la fin (hardlink, meme volume ici -- 2 appels au total)
    assert all(done <= total == 30 for done, total in calls)


def test_stage_files_propagates_cancellation_from_a_file_mid_pack(tmp_path, monkeypatch):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 10)
    target_dir = tmp_path / "staged" / "Release.Name"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        stage_files([str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"], cancel_event=cancel_event)

    assert not (target_dir / "E01.mkv").exists()
    assert not (target_dir / "E02.mkv").exists()  # jamais tente, la boucle s'arrete au premier fichier
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_staging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.cancellation'`.

- [ ] **Step 3: Write minimal implementation**

Create `nfogen/cancellation.py` :

```python
"""Signal d'annulation partage entre les operations longues declenchees en
tache de fond (copie de fichier, hachage de torrent -- voir AUTOMATION.md,
sous-projet 4c). Module minuscule et neutre : file_staging.py et
torrent_builder.py n'ont aucune autre relation d'import entre eux, pas de
raison que l'un depende de l'autre pour cette seule exception.
"""
from __future__ import annotations


class OperationCancelled(RuntimeError):
    """Une operation (copie, hachage de torrent...) a ete interrompue via
    un threading.Event fourni par l'appelant (voir commit_job_runner.py)."""
```

Modify `nfogen/file_staging.py` (remplacer tout le fichier) :

```python
"""Mise en scene de fichiers avant creation d'un .torrent -- jamais le
fichier original (voir AUTOMATION.md, sous-projet 2) : cree un hardlink
sous le nom voulu (0 octet supplementaire), avec repli automatique sur
une copie complete si la cible n'est pas sur le meme systeme de fichiers
(EXDEV) -- meme detection que celle deja utilisee ailleurs dans le
projet pour ce cas.

Important pour les consommateurs de ce module (ex. torrent_builder.py) :
un hardlink partage le meme contenu que l'original -- n'ECRIRE JAMAIS
dans un chemin mis en scene, seulement le lire.

`on_progress`/`cancel_event` (AUTOMATION.md, sous-projet 4c) : optionnels,
utilises par commit_job_runner.py pour suivre/annuler une mise en scene
en tache de fond. Le chemin hardlink est instantane (un seul appel
on_progress) ; seul le repli copie est effectivement decoupe en blocs.
"""
from __future__ import annotations

import errno
import os
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

from .cancellation import OperationCancelled

_COPY_CHUNK_SIZE = 16 * 1024 * 1024  # 16 Mio


def _copy_with_progress(
    source_path: str,
    target_path: str,
    on_progress: Optional[Callable[[int, int], None]],
    cancel_event: Optional[threading.Event],
) -> None:
    total = os.path.getsize(source_path)
    done = 0
    try:
        with open(source_path, "rb") as src, open(target_path, "wb") as dst:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelled(f"Copie annulée : {source_path} -> {target_path}")
                chunk = src.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        shutil.copystat(source_path, target_path)
    except OperationCancelled:
        Path(target_path).unlink(missing_ok=True)
        raise
    if on_progress:
        on_progress(total, total)


def stage_file(
    source_path: str,
    target_path: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Met `source_path` a disposition sous `target_path` : hardlink si
    possible, copie complete par blocs en repli (systemes de fichiers
    differents). Cree les dossiers parents de `target_path` si besoin.
    Renvoie `target_path`."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source_path, target_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        _copy_with_progress(source_path, target_path, on_progress, cancel_event)
        return target_path
    if on_progress:
        size = target.stat().st_size
        on_progress(size, size)
    return target_path


def stage_files(
    source_paths: list[str],
    target_dir: str,
    names: list[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> list[str]:
    """Met en scene plusieurs fichiers d'un coup (ex. un pack de saison) --
    un nom de sortie par source, meme ordre. `on_progress`, si fourni,
    recoit une progression CUMULEE sur l'ensemble des fichiers (pas par
    fichier individuel) -- une seule barre pour tout le groupe. Renvoie
    les chemins finaux, dans le meme ordre."""
    grand_total = sum(os.path.getsize(p) for p in source_paths)
    done_before = 0
    results: list[str] = []
    for source, name in zip(source_paths, names):
        target_path = str(Path(target_dir) / name)

        def _relay(done: int, total: int, _done_before: int = done_before) -> None:
            if on_progress:
                on_progress(_done_before + done, grand_total)

        results.append(
            stage_file(
                source, target_path,
                on_progress=_relay if on_progress else None, cancel_event=cancel_event,
            )
        )
        done_before += os.path.getsize(source)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_staging.py -v`
Expected: all PASS (les 4 tests existants inclus, inchangés).

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/cancellation.py nfogen/file_staging.py tests/test_file_staging.py
git commit -m "feat: copie par blocs avec progression/annulation (file_staging.py)"
```

---

### Task 2: Progression + annulation natives dans `torrent_builder.py`

**Files:**
- Modify: `nfogen/torrent_builder.py`
- Test: `tests/test_torrent_builder.py`

**Interfaces:**
- Consumes: `OperationCancelled` (Tâche 1).
- Produces: `build_torrent(staged_path, announce_url, output_path, piece_sizes, on_progress=None, cancel_event=None) -> None`. `on_progress: Optional[Callable[[int, int], None]]` reçoit `(pieces_done, pieces_total)` (compteurs bruts de `torf`, pas de conversion en octets ici). `cancel_event` positionné → lève `OperationCancelled`, aucun `.torrent` écrit.

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_torrent_builder.py`, ajouter en tête :

```python
import threading

from nfogen.cancellation import OperationCancelled
```

Puis ajouter (après les tests existants) :

```python
def test_build_torrent_reports_progress_as_pieces_are_hashed(tmp_path):
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * 64)  # 64 octets / 16 = 4 pieces
    output = tmp_path / "output.torrent"
    calls: list[tuple[int, int]] = []

    build_torrent(
        str(staged), "https://c411.org/announce/SECRET", str(output), [{"piece_size": 16}],
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls  # au moins un appel
    assert calls[-1] == (4, 4)
    assert all(done <= total == 4 for done, total in calls)
    assert output.is_file()


def test_build_torrent_cancellation_stops_hashing_and_writes_nothing(tmp_path):
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * 64)
    output = tmp_path / "output.torrent"
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        build_torrent(
            str(staged), "https://c411.org/announce/SECRET", str(output), [{"piece_size": 16}],
            cancel_event=cancel_event,
        )

    assert not output.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_torrent_builder.py -k "progress or cancellation" -v`
Expected: FAIL — `TypeError: build_torrent() got an unexpected keyword argument 'on_progress'`.

- [ ] **Step 3: Write minimal implementation**

Modify `nfogen/torrent_builder.py` :

```python
"""Construction du fichier .torrent final (voir AUTOMATION.md, sous-projet
2) : tracker prive, une seule adresse d'annonce (celle du compte, jamais
journalisee/exposee -- voir gapscan_config_store.py), taille de piece
choisie selon le bareme fourni par l'appelant (voir tracker_profile.py --
ce module reste agnostique du tracker, aucune table en dur ici).

`on_progress`/`cancel_event` (AUTOMATION.md, sous-projet 4c) : relayes
directement au callback natif de torf (Torrent.generate), aucune
reimplementation du hachage necessaire.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

import torf

from .cancellation import OperationCancelled


def piece_size_for(total_bytes: int, piece_sizes: list[dict[str, int]]) -> int:
    """Taille de piece (en octets) pour un contenu de `total_bytes`, d'apres
    le bareme `piece_sizes` du profil (rules.json -> tracker.torrent_piece_sizes,
    voir tracker_profile.py) -- plus aucune valeur specifique a un tracker
    en dur ici. Chaque entree : `{"max_bytes": N, "piece_size": P}` (piece
    P pour tout contenu < N octets), sauf la DERNIERE entree qui peut
    omettre `max_bytes` (piece par defaut au-dela de tous les seuils).
    Fonction pure, testable sans I/O."""
    for entry in piece_sizes:
        max_bytes = entry.get("max_bytes")
        if max_bytes is None or total_bytes < max_bytes:
            return entry["piece_size"]
    raise ValueError(
        "Barème de taille de pièce vide ou mal terminé (attendu : une dernière "
        "entrée sans 'max_bytes', voir rules.json -> tracker.torrent_piece_sizes)."
    )


def _total_size(path: str) -> int:
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def build_torrent(
    staged_path: str,
    announce_url: str,
    output_path: str,
    piece_sizes: list[dict[str, int]],
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    """Construit un .torrent prive a partir de `staged_path` (fichier ou
    dossier -- un dossier pour un pack multi-fichiers -- deja mis en scene
    par file_staging.py, jamais le fichier original) et l'ecrit dans
    `output_path`. Taille de piece choisie via `piece_size_for` a partir du
    bareme `piece_sizes` du profil (voir tracker_profile.torrent_piece_sizes).
    `cancel_event` positionne pendant le hachage -> OperationCancelled, le
    fichier .torrent n'est jamais ecrit (write() n'est appele qu'apres un
    generate() reussi)."""
    total_bytes = _total_size(staged_path)
    torrent = torf.Torrent(
        path=staged_path,
        trackers=[announce_url],
        private=True,
        piece_size=piece_size_for(total_bytes, piece_sizes),
    )

    callback = None
    if on_progress or cancel_event:

        def callback(_torrent: torf.Torrent, _filepath: str, pieces_done: int, pieces_total: int):
            if cancel_event is not None and cancel_event.is_set():
                return True  # torf : non-None => arrete le hachage
            if on_progress:
                on_progress(pieces_done, pieces_total)
            return None

    success = torrent.generate(callback=callback, interval=0)
    if not success:
        raise OperationCancelled(f"Génération du torrent annulée : {staged_path}")
    torrent.write(output_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_torrent_builder.py -v`
Expected: all PASS (tests existants inclus, inchangés).

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/torrent_builder.py tests/test_torrent_builder.py
git commit -m "feat: progression/annulation natives (torf) dans torrent_builder.py"
```

---

### Task 3: `commit_upload` gagne des hooks adaptateurs + `resolve_staging_config`

**Files:**
- Modify: `nfogen/upload_prep.py`
- Test: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: `file_staging.stage_file`/`stage_files(..., on_progress, cancel_event)` (Tâche 1), `torrent_builder.build_torrent(..., on_progress, cancel_event)` (Tâche 2).
- Produces : `resolve_staging_config(profile: str = "c411") -> tuple[str, str]` (renvoie `(staging_dir, announce_url)`, lève `ValueError`/`RuntimeError` — EXTRAIT du début de `commit_upload`, appelé aussi par `commit_job_runner.start()` en Tâche 4 pour échouer vite AVANT de démarrer une tâche). `commit_upload(release_name, files, profile="c411", on_progress=None, cancel_event=None) -> CommitResult` — `on_progress: Optional[Callable[[str, float], None]]` reçoit `(step_name, percent)` avec `step_name` dans `"staging"`/`"generating_nfo"`/`"building_torrent"` (valeurs texte brutes — `commit_upload` ne connaît PAS le type `JobState` de `commit_job_runner.py`, qui dépend déjà de `upload_prep.py` : lui faire connaître `JobState` en retour créerait un import circulaire).

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_upload_prep.py`, ajouter (après `test_commit_without_automation_extra_raises`) :

```python
def test_resolve_staging_config_returns_staging_dir_and_announce_url(monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: "/staging"
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    assert resolve_staging_config("c411") == ("/staging", "https://c411.example/announce/abc123")


def test_resolve_staging_config_raises_without_staging_dir(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: None)
    with pytest.raises(ValueError, match="scène"):
        resolve_staging_config("c411")


def test_commit_upload_reports_progress_through_all_three_steps(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_text", lambda path: "General\nFormat : Matroska\n"
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]
    calls: list[tuple[str, float]] = []

    commit_upload(
        "Movie.2020.1080p.x264-TEAM", files, on_progress=lambda step, pct: calls.append((step, pct))
    )

    steps_seen = [step for step, _ in calls]
    assert steps_seen[0] == "staging"
    assert "generating_nfo" in steps_seen
    assert steps_seen[-1] == "building_torrent"
    assert calls[-1][1] == 100.0  # 100% a la toute fin de la derniere etape


def test_commit_upload_without_hooks_behaves_exactly_as_before(tmp_path, monkeypatch):
    """Comportement 100% synchrone inchange quand on_progress/cancel_event
    sont omis (voir Global Constraints) -- meme scenario que
    test_commit_single_file_stages_and_builds_torrent, sans hooks."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_text", lambda path: "General\nFormat : Matroska\n"
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files)

    assert isinstance(result, CommitResult)
    assert _Path(result.staged_path).is_file()


def test_commit_upload_propagates_cancellation(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        commit_upload("Movie.2020.1080p.x264-TEAM", files, cancel_event=cancel_event)
```

Ajouter en tête du fichier de test (si absent) : `import threading` et `from nfogen.cancellation import OperationCancelled`, et étendre l'import existant `from nfogen.upload_prep import (...)` avec `resolve_staging_config`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -k "resolve_staging_config or reports_progress or without_hooks or propagates_cancellation" -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_staging_config'`.

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/upload_prep.py`, étendre les imports :

```python
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import c411_upload_options, engine, extract, file_staging, gapscan_config_store, tracker_profile
from .c411_upload_client import C411UploadClient, C411UploadError
from .engine import propose_release_name
from .models import RenderContext
from .name_proposal import extract_team_tag, strip_ext
from .profile_store import read_profile
from .radarr_client import RadarrClient
from .registry import get_validator
from .rules import captures as rules_captures
from .sonarr_client import SonarrClient
from .upload_description import render_upload_description
```

(seul ajout : `import threading` et `Callable` dans l'import `typing`.)

Remplacer `commit_upload` par :

```python
def resolve_staging_config(profile: str = "c411") -> tuple[str, str]:
    """Verifications rapides (config uniquement, aucune I/O lourde) --
    faites AVANT de demarrer une tache de fond (voir
    commit_job_runner.start(), sous-projet 4c), pour que les erreurs de
    configuration restent visibles IMMEDIATEMENT (comme avant sous-projet
    4c), pas seulement apres coup dans l'etat d'une tache. Renvoie
    `(staging_dir, announce_url)`."""
    if not _TORRENT_BUILDER_AVAILABLE:
        raise RuntimeError(
            "Génération de .torrent indisponible : pip install nfogen[automation]"
        )
    staging_dir = gapscan_config_store.effective_staging_dir()
    if not staging_dir:
        raise ValueError(
            "Dossier de mise en scène non configuré (PUT /gapscan/config, champ staging_dir)."
        )
    announce_url = gapscan_config_store.effective_tracker_announce_url(profile)
    if not announce_url:
        raise ValueError(
            f"Adresse d'annonce non configurée pour le profil '{profile}' "
            "(PUT /gapscan/config, champ tracker_announce_url)."
        )
    return staging_dir, announce_url


def commit_upload(
    release_name: str,
    files: list[ProposedFile],
    profile: str = "c411",
    on_progress: Optional[Callable[[str, float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> CommitResult:
    """Met en scene (hardlink/copie, `file_staging.py`) et genere le
    `.torrent` (`torrent_builder.py`) pour UN groupe deja propose par
    `preview_upload()` -- le frontend renvoie exactement ce qu'il a recu
    pour ce groupe, aucun etat serveur entre les deux appels. Fichier
    unique mis en scene directement (`<release_name><ext>`), groupe
    multi-fichiers dans un dossier (`<release_name>/<nom par fichier>`).

    `on_progress`/`cancel_event` (AUTOMATION.md, sous-projet 4c,
    optionnels) : role d'ADAPTATEUR -- convertit les callbacks bruts de
    file_staging.py (bytes_done, bytes_total) et torrent_builder.py
    (pieces_done, pieces_total) en pourcentages 0-100 relayes a
    on_progress(step_name, percent). Omis : comportement 100% synchrone
    inchange (aucun test existant ne casse)."""
    staging_dir, announce_url = resolve_staging_config(profile)

    def _staging_progress(done: int, total: int) -> None:
        if on_progress:
            pct = (done / total * 100) if total else 100.0
            on_progress("staging", pct)

    if len(files) == 1:
        staged_path = str(Path(staging_dir) / files[0].staged_name)
        file_staging.stage_file(
            files[0].source_path, staged_path,
            on_progress=_staging_progress if on_progress else None, cancel_event=cancel_event,
        )
        raw_text = extract.extract_video_text(Path(staged_path))
    else:
        target_dir = str(Path(staging_dir) / release_name)
        file_staging.stage_files(
            [f.source_path for f in files], target_dir, [f.staged_name for f in files],
            on_progress=_staging_progress if on_progress else None, cancel_event=cancel_event,
        )
        staged_path = target_dir
        # Un seul .nfo pour tout le pack (pas un par episode) : coherent
        # avec un seul release_name / .torrent par groupe (confirme par
        # l'utilisateur, 2026-08-28).
        raw_text = extract.extract_video_dir_text(Path(staged_path))

    if on_progress:
        on_progress("generating_nfo", 0.0)
    # Lu depuis le chemin MIS EN SCENE (pas l'original) : "Complete name"
    # dans le .nfo reflete alors le nom de release final, pas le nom de
    # telechargement d'origine.
    nfo_filename: list[str] = []
    nfo = engine.generate(
        category="video", profile=profile,
        data={"release_name": release_name, "raw_text": raw_text},
        filename=nfo_filename,
    )
    nfo_path = str(Path(staging_dir) / (nfo_filename[0] if nfo_filename else f"{release_name}.nfo"))
    Path(nfo_path).write_text(nfo, encoding="utf-8")
    if on_progress:
        on_progress("generating_nfo", 100.0)

    torrent_path = str(Path(staging_dir) / f"{release_name}.torrent")
    piece_sizes = tracker_profile.torrent_piece_sizes(profile)

    def _torrent_progress(pieces_done: int, pieces_total: int) -> None:
        if on_progress:
            pct = (pieces_done / pieces_total * 100) if pieces_total else 100.0
            on_progress("building_torrent", pct)

    torrent_builder.build_torrent(
        staged_path, announce_url, torrent_path, piece_sizes,
        on_progress=_torrent_progress if on_progress else None, cancel_event=cancel_event,
    )
    return CommitResult(
        release_name=release_name, staged_path=staged_path, torrent_path=torrent_path, nfo_path=nfo_path
    )
```

(le reste du fichier — `send_to_tracker`, etc. — inchangé.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: all PASS (tous les tests existants de `commit_upload` inclus, inchangés).

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "feat: commit_upload gagne des hooks adaptateurs on_progress/cancel_event"
```

---

### Task 4: `nfogen/commit_job_runner.py` — registre de tâches par `job_id`

**Files:**
- Create: `nfogen/commit_job_runner.py`
- Test: `tests/test_commit_job_runner.py`

**Interfaces:**
- Consumes: `upload_prep.resolve_staging_config`, `upload_prep.commit_upload(..., on_progress, cancel_event)` (Tâche 3), `OperationCancelled` (Tâche 1).
- Produces : `start(release_name: str, files: list[upload_prep.ProposedFile], profile: str = "c411") -> str` (renvoie `job_id` immédiatement, lève `ValueError`/`RuntimeError` synchrone si config manquante) ; `status(job_id: str) -> Optional[dict[str, Any]]` (`None` si inconnu) ; `list_jobs() -> list[dict[str, Any]]` ; `cancel(job_id: str) -> bool`. Chaque dict de statut : `{job_id, release_name, state, percent, started_at, finished_at, error, result}` avec `state` dans `"staging"`/`"generating_nfo"`/`"building_torrent"`/`"done"`/`"error"`/`"cancelled"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_commit_job_runner.py` :

```python
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

from nfogen import commit_job_runner
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

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None):
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

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None):
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

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None):
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

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None):
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

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None):
        raise RuntimeError("NAS déconnecté")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)
    job_id = commit_job_runner.start("X", FILES)

    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "NAS déconnecté" in status["error"]


# --------------------------------------------------------------------------- #
# Registre / liste
# --------------------------------------------------------------------------- #
def test_status_of_unknown_job_is_none():
    assert commit_job_runner.status("does-not-exist") is None


def test_list_jobs_includes_multiple_concurrent_and_finished_jobs(monkeypatch):
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None):
        return CommitResult(release_name=release_name, staged_path="p", torrent_path="t", nfo_path="n")

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)
    job_id_1 = commit_job_runner.start("A", FILES)
    job_id_2 = commit_job_runner.start("B", FILES)
    _wait_until_terminal(job_id_1)
    _wait_until_terminal(job_id_2)

    ids = {j["job_id"] for j in commit_job_runner.list_jobs()}
    assert {job_id_1, job_id_2} <= ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_commit_job_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.commit_job_runner'`.

- [ ] **Step 3: Write minimal implementation**

Create `nfogen/commit_job_runner.py` :

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_commit_job_runner.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/commit_job_runner.py tests/test_commit_job_runner.py
git commit -m "feat: nfogen/commit_job_runner.py - registre de taches de commit par job_id"
```

---

### Task 5: `api.py` — `POST .../commit` devient asynchrone + 3 nouveaux endpoints

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `commit_job_runner.start/status/list_jobs/cancel` (Tâche 4).
- Produces : `POST /gapscan/prepare-upload/commit` renvoie désormais `{"job_id": "<hex>"}` (200) au lieu du `CommitResult` complet — erreurs de config toujours surfacées en 400 immédiatement (via `resolve_staging_config`, appelé par `commit_job_runner.start` avant tout thread). `GET /gapscan/commit-jobs` → `list[dict]`. `GET /gapscan/commit-jobs/{job_id}` → `dict`, 404 si inconnu. `POST /gapscan/commit-jobs/{job_id}/cancel` → `{"status": "cancelling"}`, 404 si inconnu, 409 si déjà terminé.

- [ ] **Step 1: Write the failing tests**

D'abord, dans `tests/test_api.py`, étendre les deux tests existants `test_prepare_upload_routes_require_gapscan_available`/`test_prepare_upload_routes_require_auth_when_token_configured` (chercher leur définition exacte) pour couvrir les 3 nouvelles routes :

```python
def test_prepare_upload_routes_require_gapscan_available(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)
    assert client.post("/gapscan/prepare-upload/preview", json={"local_paths": []}).status_code == 501
    assert (
        client.post("/gapscan/prepare-upload/commit", json={"release_name": "x", "files": []}).status_code
        == 501
    )
    assert client.get("/gapscan/commit-jobs").status_code == 501
    assert client.get("/gapscan/commit-jobs/x").status_code == 501
    assert client.post("/gapscan/commit-jobs/x/cancel").status_code == 501


def test_prepare_upload_routes_require_auth_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    assert client.post("/gapscan/prepare-upload/preview", json={"local_paths": []}).status_code == 401
    assert (
        client.post("/gapscan/prepare-upload/commit", json={"release_name": "x", "files": []}).status_code
        == 401
    )
    assert client.get("/gapscan/commit-jobs").status_code == 401
    assert client.get("/gapscan/commit-jobs/x").status_code == 401
    assert client.post("/gapscan/commit-jobs/x/cancel").status_code == 401
```

Puis remplacer `test_prepare_upload_commit_real_flow` (le corps de réponse change de forme — CHANGEMENT ASSUMÉ, voir Global Constraints) :

```python
def test_prepare_upload_commit_real_flow(reload_api, tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    source = tmp_path / "source.mkv"
    source.write_bytes(b"contenu de test")

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)
    put = client.put(
        "/gapscan/config",
        json={
            "tracker_announce_url": "https://c411.example/announce/abc123",
            "staging_dir": str(staging_dir),
        },
    )
    assert put.status_code == 200

    resp = client.post(
        "/gapscan/prepare-upload/commit",
        json={
            "release_name": "Movie.2020.1080p.x264-TEAM",
            "files": [{"source_path": str(source), "staged_name": "Movie.2020.1080p.x264-TEAM.mkv"}],
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_id

    deadline = time.monotonic() + 5.0
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/gapscan/commit-jobs/{job_id}").json()
        if status["state"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.01)

    assert status["state"] == "done"
    body = status["result"]
    assert body["release_name"] == "Movie.2020.1080p.x264-TEAM"
    assert body["staged_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.mkv")
    assert body["torrent_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.torrent")
    assert body["nfo_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.nfo")
    assert (staging_dir / "Movie.2020.1080p.x264-TEAM.nfo").is_file()
```

`test_prepare_upload_commit_without_staging_dir_is_400` reste **inchangé** (toujours un 400 synchrone, voir Interfaces).

Enfin, ajouter les tests dédiés aux 3 nouveaux endpoints (après `test_prepare_upload_commit_real_flow`) :

```python
def test_commit_job_status_404_for_unknown_job(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/commit-jobs/does-not-exist")
    assert resp.status_code == 404


def test_commit_jobs_list_is_empty_initially(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/commit-jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_cancel_unknown_job_is_404(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/commit-jobs/does-not-exist/cancel")
    assert resp.status_code == 404


def test_cancel_already_finished_job_is_409(reload_api, tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    source = tmp_path / "source.mkv"
    source.write_bytes(b"contenu")

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)
    client.put(
        "/gapscan/config",
        json={
            "tracker_announce_url": "https://c411.example/announce/abc123",
            "staging_dir": str(staging_dir),
        },
    )
    resp = client.post(
        "/gapscan/prepare-upload/commit",
        json={"release_name": "X", "files": [{"source_path": str(source), "staged_name": "X.mkv"}]},
    )
    job_id = resp.json()["job_id"]

    deadline = time.monotonic() + 5.0
    status = {"state": "staging"}
    while time.monotonic() < deadline and status["state"] not in ("done", "error", "cancelled"):
        status = client.get(f"/gapscan/commit-jobs/{job_id}").json()
        time.sleep(0.01)

    cancel_resp = client.post(f"/gapscan/commit-jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "prepare_upload_routes or prepare_upload_commit_real_flow or commit_job or cancel_already_finished or cancel_unknown" -v`
Expected: FAIL — routes nouvelles en 404 (pas encore enregistrées), `test_prepare_upload_commit_real_flow` échoue sur `resp.json()["job_id"]` (KeyError, la réponse actuelle est encore l'ancien `CommitResult`).

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/api.py`, étendre l'import conditionnel existant (chercher `from . import gapscan, gapscan_config_store, gapscan_runner, tracker_profile, upload_prep`) :

```python
    from . import (
        commit_job_runner, gapscan, gapscan_config_store, gapscan_runner, tracker_profile, upload_prep,
    )
```

Puis remplacer `gapscan_prepare_upload_commit` :

```python
@app.post("/gapscan/prepare-upload/commit", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_commit(req: PrepareUploadCommitRequest) -> dict[str, str]:
    """Demarre la mise en scene + generation de .torrent EN TACHE DE FOND
    (AUTOMATION.md, sous-projet 4c) -- renvoie un job_id immediatement,
    suivi via GET /gapscan/commit-jobs/{job_id}. Erreurs de configuration
    (staging_dir/announce_url manquants) restent surfacees immediatement
    (voir upload_prep.resolve_staging_config, verifie AVANT de demarrer la
    tache, dans commit_job_runner.start())."""
    _require_gapscan_available()
    files = [
        upload_prep.ProposedFile(source_path=f.source_path, staged_name=f.staged_name) for f in req.files
    ]
    job_id = _run_upload_prep(commit_job_runner.start, req.release_name, files, profile=req.profile)
    return {"job_id": job_id}


@app.get("/gapscan/commit-jobs", dependencies=[Depends(require_token)])
def gapscan_commit_jobs() -> list[dict[str, Any]]:
    _require_gapscan_available()
    return commit_job_runner.list_jobs()


@app.get("/gapscan/commit-jobs/{job_id}", dependencies=[Depends(require_token)])
def gapscan_commit_job_status(job_id: str) -> dict[str, Any]:
    _require_gapscan_available()
    status = commit_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    return status


@app.post("/gapscan/commit-jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def gapscan_commit_job_cancel(job_id: str) -> dict[str, str]:
    _require_gapscan_available()
    status = commit_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    if status["state"] in ("done", "error", "cancelled"):
        raise HTTPException(status_code=409, detail="Cette tâche est déjà terminée.")
    commit_job_runner.cancel(job_id)
    return {"status": "cancelling"}
```

(placer les 3 nouveaux endpoints juste après `gapscan_prepare_upload_commit`, avant `class PrepareUploadSendRequest`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/api.py tests/test_api.py
git commit -m "feat: POST /gapscan/prepare-upload/commit devient asynchrone + endpoints commit-jobs"
```

At this point, run the full backend suite one final time (`pytest`, `ruff check nfogen/ tests/`) — le backend de ce sous-projet est complet, la suite des tâches passe au frontend.

---

### Task 6: Frontend — types + client API pour les tâches de commit

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces : `CommitJobState`, `CommitJob { job_id, release_name, state, percent, started_at, finished_at, error, result }` (types). `prepareUploadCommit(releaseName, files, profile?) -> Promise<{ job_id: string }>` (signature de retour CHANGÉE — tous les appelants mis à jour en Tâche 7). `commitJobStatus(jobId: string) -> Promise<CommitJob>`. `listCommitJobs() -> Promise<CommitJob[]>`. `cancelCommitJob(jobId: string) -> Promise<{ status: string }>`.

- [ ] **Step 1: Write the failing tests**

Dans `frontend/src/api/types.ts`, après `UploadCommitResult`, ajouter :

```ts
/** POST /gapscan/prepare-upload/commit ne bloque plus : cree une tache de
 * fond suivie via job_id (AUTOMATION.md, sous-projet 4c). */
export type CommitJobState =
  | "staging"
  | "generating_nfo"
  | "building_torrent"
  | "done"
  | "error"
  | "cancelled";

export interface CommitJob {
  job_id: string;
  release_name: string;
  state: CommitJobState;
  /** 0-100, relatif a l'ETAPE EN COURS (state). */
  percent: number;
  started_at: number;
  finished_at: number | null;
  error: string | null;
  result: UploadCommitResult | null;
}
```

Dans `frontend/src/api/client.test.ts`, remplacer le test existant `"commit envoie release_name/files/profile, renvoie le resultat"` (dans `describe("prepareUploadPreview / prepareUploadCommit", ...)`) :

```ts
  it("commit envoie release_name/files/profile, renvoie un job_id", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ job_id: "abc123" }));

    const files = [{ source_path: "/a.mkv", staged_name: "Movie.2020.1080p.x264-TEAM.mkv" }];
    const result = await prepareUploadCommit("Movie.2020.1080p.x264-TEAM", files);

    expect(result).toEqual({ job_id: "abc123" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/prepare-upload/commit");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      release_name: "Movie.2020.1080p.x264-TEAM",
      files,
      profile: "c411",
    });
  });
```

Puis ajouter un nouveau `describe` (après celui de `prepareUploadPreview`/`prepareUploadCommit`) :

```ts
describe("commitJobStatus / listCommitJobs / cancelCommitJob", () => {
  const JOB = {
    job_id: "abc123", release_name: "Movie.2020.1080p.x264-TEAM", state: "staging", percent: 42,
    started_at: 1000, finished_at: null, error: null, result: null,
  };

  it("commitJobStatus GET le bon chemin, renvoie la tache", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(JOB));

    const result = await commitJobStatus("abc123");

    expect(result).toEqual(JOB);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/commit-jobs/abc123");
  });

  it("listCommitJobs renvoie la liste complete", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([JOB]));

    const result = await listCommitJobs();

    expect(result).toEqual([JOB]);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/commit-jobs");
  });

  it("cancelCommitJob POST vers /cancel", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "cancelling" }));

    const result = await cancelCommitJob("abc123");

    expect(result).toEqual({ status: "cancelling" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/commit-jobs/abc123/cancel");
    expect((init as RequestInit).method).toBe("POST");
  });
});
```

Étendre l'import existant depuis `"./client"` avec `cancelCommitJob, commitJobStatus, listCommitJobs`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `commitJobStatus`/`listCommitJobs`/`cancelCommitJob` ne sont pas exportés par `./client` ; le test "renvoie un job_id" échoue (l'implémentation actuelle renvoie encore `UploadCommitResult`).

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/api/client.ts`, étendre l'import de types :

```ts
import type {
  CommitJob,
  GapscanConfig,
  GapscanConfigWrite,
  GapscanResultsPage,
  GapscanStatus,
  GenerateResult,
  ManagedProfile,
  NameProposal,
  ProfilesByCategory,
  RulesDocument,
  SendToTrackerResult,
  TemplatesDocument,
  UploadCommitResult,
  UploadGroupProposal,
  UploadPrepFile,
} from "./types";
```

Remplacer `prepareUploadCommit` et ajouter les trois nouvelles fonctions juste après :

```ts
/** Demarre la mise en scene + generation de .torrent EN TACHE DE FOND
 * (AUTOMATION.md, sous-projet 4c) -- renvoie un job_id immediatement,
 * suivi via commitJobStatus(). */
export function prepareUploadCommit(
  releaseName: string,
  files: UploadPrepFile[],
  profile = "c411",
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>("/gapscan/prepare-upload/commit", {
    method: "POST",
    body: JSON.stringify({ release_name: releaseName, files, profile }),
  });
}

export function commitJobStatus(jobId: string): Promise<CommitJob> {
  return request<CommitJob>(`/gapscan/commit-jobs/${encodeURIComponent(jobId)}`);
}

export function listCommitJobs(): Promise<CommitJob[]> {
  return request<CommitJob[]>("/gapscan/commit-jobs");
}

export function cancelCommitJob(jobId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/gapscan/commit-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: all PASS.

- [ ] **Step 5: `tsc` + commit**

Note : `UploadPrepPanel.tsx` ne connaît pas encore le nouveau retour de `prepareUploadCommit` — `tsc` va probablement afficher une erreur préexistante sur `UploadPrepPanel.tsx` (résolue en Tâche 7). Confirmer que les seules erreurs sont dans ce fichier.

```bash
cd frontend
npx vitest run src/api/client.test.ts
npx tsc --noEmit -p tsconfig.app.json
git add src/api/types.ts src/api/client.ts src/api/client.test.ts
git commit -m "feat: client API pour les taches de commit (job_id, status, list, cancel)"
```

---

### Task 7: `UploadPrepPanel.tsx` — barre de progression + annulation

**Files:**
- Modify: `frontend/src/components/UploadPrepPanel.tsx`
- Test: `frontend/src/components/UploadPrepPanel.test.tsx`

**Interfaces:**
- Consumes: `prepareUploadCommit`, `commitJobStatus`, `cancelCommitJob` (Tâche 6).
- Produces : `handleConfirm` démarre une tâche puis la suit en polling (1500 ms) jusqu'à un état terminal — remplace le bouton "Confirmer" par une barre de progression + libellé d'étape + bouton "Annuler" pendant les états non terminaux. À `done` : comportement inchangé (affiche `staged_path`/`torrent_path`/`nfo_path`, débloque "Envoyer à C411"). À `error`/`cancelled` : message d'erreur, bouton "Confirmer" réapparaît (nouvelle tentative possible).

- [ ] **Step 1: Write the failing tests**

D'abord, lire `frontend/src/components/UploadPrepPanel.test.tsx` en entier pour repérer TOUS les tests qui appellent `handleConfirm`/cliquent sur "Confirmer" et dépendent de `prepareUploadCommit` (au minimum : "Confirmer appelle prepareUploadCommit et affiche le resultat", "affiche le bouton Envoyer a C411...", "affiche l'avertissement anti-doublon...", et tout autre test qui clique Confirmer avant d'interagir avec le résultat).

Étendre le mock `vi.mock("../api/client", ...)` et son import avec `commitJobStatus`/`cancelCommitJob` :

```ts
vi.mock("../api/client", () => ({
  prepareUploadPreview: vi.fn(),
  prepareUploadCommit: vi.fn(),
  commitJobStatus: vi.fn(),
  cancelCommitJob: vi.fn(),
  sendToTracker: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
}));
```

```ts
import {
  cancelCommitJob,
  commitJobStatus,
  listAllProfiles,
  prepareUploadCommit,
  prepareUploadPreview,
  readManagedProfile,
  sendToTracker,
} from "../api/client";
```

Ajouter un petit helper en tête du fichier (après `ONE_GROUP`/`BLOCKED_GROUP`) pour le job "terminé immédiatement" (le cas commun de la plupart des tests existants) :

```ts
const DONE_JOB = {
  job_id: "job-1", release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
  state: "done" as const, percent: 100, started_at: 1000, finished_at: 1001, error: null,
  result: {
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    staged_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.mkv",
    torrent_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.torrent",
    nfo_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.nfo",
  },
};
```

Dans `beforeEach`, ajouter `vi.mocked(commitJobStatus).mockReset(); vi.mocked(cancelCommitJob).mockReset();`.

Remplacer le test `"Confirmer appelle prepareUploadCommit et affiche le resultat"` :

```ts
it("Confirmer demarre une tache, affiche le resultat une fois terminee (done)", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  await waitFor(() => {
    expect(screen.getByText(/staging\/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM\.torrent/)).toBeInTheDocument();
  });
  expect(prepareUploadCommit).toHaveBeenCalledWith(
    "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    ONE_GROUP[0].files,
    "c411",
  );
  expect(commitJobStatus).toHaveBeenCalledWith("job-1");
});

it("affiche une barre de progression et un bouton Annuler pendant une tache en cours", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue({
    job_id: "job-1", release_name: "X", state: "staging", percent: 42,
    started_at: 1000, finished_at: null, error: null, result: null,
  });
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  expect(await screen.findByText(/42\s*%/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Annuler/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Confirmer/i })).not.toBeInTheDocument();
});

it("Annuler appelle cancelCommitJob avec le job_id en cours", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue({
    job_id: "job-1", release_name: "X", state: "staging", percent: 10,
    started_at: 1000, finished_at: null, error: null, result: null,
  });
  vi.mocked(cancelCommitJob).mockResolvedValue({ status: "cancelling" });
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Annuler/i }));

  expect(cancelCommitJob).toHaveBeenCalledWith("job-1");
});

it("etat error : affiche le message et fait reapparaitre Confirmer", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue({
    job_id: "job-1", release_name: "X", state: "error", percent: 0,
    started_at: 1000, finished_at: 1001, error: "NAS déconnecté", result: null,
  });
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  expect(await screen.findByText(/NAS déconnecté/)).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /Confirmer/i })).toBeInTheDocument();
});
```

Mettre à jour les deux tests existants sur "Envoyer à C411" (`"affiche le bouton Envoyer a C411..."` et `"affiche l'avertissement anti-doublon..."`) en ajoutant `vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);` juste après le `vi.mocked(prepareUploadCommit).mockResolvedValue(...)` existant, et en remplaçant ce dernier par `vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });` (au lieu du `CommitResult` complet renvoyé directement) — le reste de ces deux tests (assertions sur `sendToTracker`) reste inchangé.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: FAIL — `commitJobStatus`/`cancelCommitJob` non appelés (le composant actuel utilise encore directement le retour de `prepareUploadCommit`), pas de bouton "Annuler".

- [ ] **Step 3: Write the implementation**

Remplacer `frontend/src/components/UploadPrepPanel.tsx` en entier :

```tsx
import { useEffect, useRef, useState } from "react";
import { cancelCommitJob, commitJobStatus, prepareUploadCommit, prepareUploadPreview, sendToTracker } from "../api/client";
import { ApiError } from "../api/types";
import type { CommitJob, SendToTrackerResult, UploadCommitResult, UploadGroupProposal } from "../api/types";
import { useProfile } from "../ProfileContext";

const STEP_LABELS: Record<string, string> = {
  staging: "Mise en scène",
  generating_nfo: "Génération du .nfo",
  building_torrent: "Génération du torrent",
};

const TERMINAL_STATES = ["done", "error", "cancelled"];

/** Apercu (sans ecriture disque) puis confirmation par groupe de la mise
 * en scene + generation de .torrent (AUTOMATION.md, sous-projet 4). Un
 * groupe = un tag d'equipe detecte -- un pack assemble depuis plusieurs
 * releases devient plusieurs groupes independants (voir
 * nfogen/upload_prep.py:group_by_team). Jamais de "tout confirmer" :
 * chaque groupe se confirme individuellement, coherent avec la decision
 * "upload un par un" (AUTOMATION.md, "Decisions deja prises").
 *
 * "Confirmer" demarre une tache de fond suivie en polling (AUTOMATION.md,
 * sous-projet 4c) -- une mise en scene par copie (volumes differents) ou
 * un hachage de torrent peuvent prendre plusieurs minutes, jamais bloquer
 * la page pendant ce temps. */
export default function UploadPrepPanel({
  localPaths,
  title,
  mediaType,
  radarrMovieId,
  sonarrSeriesId,
  tmdbId,
  tvdbId,
  genre,
  seasonNumber,
  onClose,
}: {
  localPaths: string[];
  title: string;
  mediaType: "movie" | "series";
  radarrMovieId: number | null;
  sonarrSeriesId: number | null;
  tmdbId: number | null;
  tvdbId: number | null;
  genre: "anime" | "documentaire" | null;
  seasonNumber: number | null;
  onClose: () => void;
}) {
  const { profile: globalProfile, profiles } = useProfile();
  const [profile, setProfile] = useState(globalProfile);
  const [groups, setGroups] = useState<UploadGroupProposal[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  const [titleOverride, setTitleOverride] = useState(title);
  const [commitJobs, setCommitJobs] = useState<Record<number, CommitJob>>({});
  const [commitResults, setCommitResults] = useState<Record<number, UploadCommitResult>>({});
  const [commitErrors, setCommitErrors] = useState<Record<number, string>>({});
  const [sending, setSending] = useState<number | null>(null);
  const [sendResults, setSendResults] = useState<Record<number, SendToTrackerResult>>({});
  const [sendErrors, setSendErrors] = useState<Record<number, string>>({});
  const pollRefs = useRef<Record<number, number>>({});

  async function loadPreview(override?: string, profileOverride: string = profile) {
    setRecalculating(true);
    setLoadError(null);
    try {
      const g = await prepareUploadPreview(localPaths, profileOverride, override || undefined);
      setGroups(g);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Aperçu indisponible.");
    } finally {
      setRecalculating(false);
    }
  }

  useEffect(() => {
    loadPreview(title);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localPaths]);

  useEffect(() => {
    return () => {
      Object.values(pollRefs.current).forEach((id) => window.clearInterval(id));
    };
  }, []);

  function handleProfileChange(next: string) {
    setProfile(next);
    loadPreview(titleOverride, next);
  }

  function stopPolling(index: number) {
    const id = pollRefs.current[index];
    if (id !== undefined) {
      window.clearInterval(id);
      delete pollRefs.current[index];
    }
  }

  async function pollCommitJob(index: number, jobId: string) {
    try {
      const job = await commitJobStatus(jobId);
      setCommitJobs((prev) => ({ ...prev, [index]: job }));
      if (!TERMINAL_STATES.includes(job.state)) return;
      stopPolling(index);
      setCommitJobs((prev) => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
      if (job.state === "done" && job.result) {
        setCommitResults((prev) => ({ ...prev, [index]: job.result as UploadCommitResult }));
      } else if (job.state === "error") {
        setCommitErrors((prev) => ({ ...prev, [index]: job.error ?? "Confirmation impossible." }));
      } else {
        setCommitErrors((prev) => ({ ...prev, [index]: "Annulé." }));
      }
    } catch (e) {
      stopPolling(index);
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Suivi de la tâche impossible.",
      }));
    }
  }

  async function handleConfirm(index: number, group: UploadGroupProposal) {
    if (!group.release_name) return;
    setCommitErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const { job_id } = await prepareUploadCommit(group.release_name, group.files, profile);
      // L'intervalle est enregistre AVANT le premier appel : si ce premier
      // appel atteint deja un etat terminal (job termine tres vite), son
      // propre stopPolling() doit pouvoir le retrouver et l'annuler.
      pollRefs.current[index] = window.setInterval(() => pollCommitJob(index, job_id), 1500);
      await pollCommitJob(index, job_id);
    } catch (e) {
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Confirmation impossible.",
      }));
    }
  }

  async function handleCancel(index: number) {
    const job = commitJobs[index];
    if (!job) return;
    try {
      await cancelCommitJob(job.job_id);
    } catch {
      // best effort -- le prochain polling reflete l'etat reel de toute facon
    }
  }

  async function handleSend(index: number) {
    const commit = commitResults[index];
    if (!commit) return;
    setSending(index);
    setSendErrors((prev) => ({ ...prev, [index]: "" }));
    try {
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
        draftId: sendResults[index]?.draft_id,
      });
      setSendResults((prev) => ({ ...prev, [index]: result }));
    } catch (e) {
      setSendErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Envoi impossible.",
      }));
    } finally {
      setSending(null);
    }
  }

  return (
    <div className="space-y-3 rounded-md border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-sm font-semibold text-ink">Préparer l'upload — {title}</h2>
        <button type="button" onClick={onClose} className="text-sm text-ink-faint hover:text-ink">
          Fermer
        </button>
      </div>

      <div className="flex items-end gap-2">
        <label className="block text-xs font-medium text-ink-dim">
          Profil pour cet upload
          <select
            aria-label="Profil pour cet upload"
            className="mt-1 w-full max-w-[10rem] rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink"
            value={profile}
            onChange={(e) => handleProfileChange(e.target.value)}
          >
            {Object.keys(profiles).length === 0 && <option value="c411">c411</option>}
            {Object.keys(profiles).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="block flex-1 text-xs font-medium text-ink-dim">
          Titre (si différent de celui déduit du nom de fichier)
          <input
            className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-1.5 text-sm text-ink font-mono"
            placeholder="Laisser vide pour garder le titre déduit du nom de fichier"
            value={titleOverride}
            onChange={(e) => setTitleOverride(e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => loadPreview(titleOverride)}
          disabled={recalculating}
          className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          {recalculating ? "Calcul…" : "Recalculer"}
        </button>
      </div>

      {loadError && <p className="text-sm text-crit">{loadError}</p>}
      {!groups && !loadError && <p className="text-sm text-ink-faint">Calcul de l'aperçu…</p>}

      {groups && groups.length === 0 && (
        <p className="text-sm text-ink-faint">Aucun fichier à préparer.</p>
      )}

      {groups?.map((group, index) => (
        <div key={index} className="space-y-2 rounded-md border border-line-strong p-3">
          <p className="font-mono text-sm font-medium text-ink">
            {group.release_name ?? "(nom impossible à calculer)"}
          </p>
          <ul className="space-y-0.5 text-xs text-ink-dim">
            {group.files.map((f) => (
              <li key={f.source_path} className="font-mono">
                {f.source_path.split(/[/\\]/).pop()} → {f.staged_name}
              </li>
            ))}
          </ul>
          {group.warnings.length > 0 && (
            <ul className="space-y-0.5 text-xs text-warn">
              {group.warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}

          {!group.blocked && group.release_name && !commitResults[index] && !commitJobs[index] && (
            <button
              type="button"
              onClick={() => handleConfirm(index, group)}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              Confirmer
            </button>
          )}
          {commitJobs[index] && (
            <div className="space-y-1">
              <div className="h-2 w-full overflow-hidden rounded bg-surface-2">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${commitJobs[index].percent}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-xs text-ink-dim">
                <span>
                  {STEP_LABELS[commitJobs[index].state] ?? commitJobs[index].state} —{" "}
                  {Math.round(commitJobs[index].percent)}%
                </span>
                <button type="button" onClick={() => handleCancel(index)} className="text-crit underline">
                  Annuler
                </button>
              </div>
            </div>
          )}
          {commitErrors[index] && <p className="text-xs text-crit">{commitErrors[index]}</p>}
          {commitResults[index] && (
            <p className="text-xs text-good">
              Mis en scène : <span className="font-mono">{commitResults[index].staged_path}</span>
              <br />
              Torrent : <span className="font-mono">{commitResults[index].torrent_path}</span>
              <br />
              NFO : <span className="font-mono">{commitResults[index].nfo_path}</span>
            </p>
          )}
          {commitResults[index] && !sendResults[index] && (
            <button
              type="button"
              onClick={() => handleSend(index)}
              disabled={sending === index}
              className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
            >
              {sending === index ? "Envoi…" : "Envoyer à C411"}
            </button>
          )}
          {sendErrors[index] && <p className="text-xs text-crit">{sendErrors[index]}</p>}
          {sendResults[index] && (
            <div className="space-y-1 text-xs">
              <p className="text-good">
                Brouillon créé :{" "}
                <a
                  href={sendResults[index].draft_url}
                  className="underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {sendResults[index].draft_url}
                </a>
                <br />
                Finalise-le sur le site pour l'envoyer réellement en modération.
              </p>
              {sendResults[index].duplicate_warning && (
                <p className="text-warn">⚠ {sendResults[index].duplicate_warning}</p>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Full frontend suite + `tsc`, then commit**

```bash
cd frontend
npx vitest run
npx tsc --noEmit -p tsconfig.app.json
git add src/components/UploadPrepPanel.tsx src/components/UploadPrepPanel.test.tsx
git commit -m "feat: UploadPrepPanel suit Confirmer en polling (progression + annulation)"
```

---

### Task 8: `ActiveTransfersTray.tsx` — encart "Transferts en cours"

**Files:**
- Create: `frontend/src/components/ActiveTransfersTray.tsx`
- Create: `frontend/src/components/ActiveTransfersTray.test.tsx`
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Modify: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `listCommitJobs`, `cancelCommitJob` (Tâche 6).
- Produces : `<ActiveTransfersTray />` — aucune prop. Monté sur `GapScanPage.tsx`, indépendamment de `activeUpload`. N'affiche que les tâches dans un état NON terminal (`staging`/`generating_nfo`/`building_torrent`) — une tâche terminée disparaît de l'encart dès son prochain rafraîchissement (le résultat reste visible dans le panneau d'origine s'il est encore ouvert). Masqué (`null`) si aucune tâche active.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ActiveTransfersTray.test.tsx` :

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import ActiveTransfersTray from "./ActiveTransfersTray";

vi.mock("../api/client", () => ({
  listCommitJobs: vi.fn(),
  cancelCommitJob: vi.fn(),
}));

import { cancelCommitJob, listCommitJobs } from "../api/client";

beforeEach(() => {
  vi.mocked(listCommitJobs).mockReset();
  vi.mocked(cancelCommitJob).mockReset();
});

afterEach(() => vi.restoreAllMocks());

const ACTIVE_JOB = {
  job_id: "job-1", release_name: "Movie.2020.BluRay-TEAM", state: "staging" as const, percent: 30,
  started_at: 1000, finished_at: null, error: null, result: null,
};

const DONE_JOB = {
  job_id: "job-2", release_name: "Show.S01.WEB-TEAM", state: "done" as const, percent: 100,
  started_at: 900, finished_at: 950, error: null,
  result: { release_name: "Show.S01.WEB-TEAM", staged_path: "p", torrent_path: "t", nfo_path: "n" },
};

it("n'affiche rien quand aucune tache active", async () => {
  vi.mocked(listCommitJobs).mockResolvedValue([]);
  const { container } = render(<ActiveTransfersTray />);

  await waitFor(() => expect(listCommitJobs).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("affiche les taches actives avec leur pourcentage, masque les taches terminees", async () => {
  vi.mocked(listCommitJobs).mockResolvedValue([ACTIVE_JOB, DONE_JOB]);
  render(<ActiveTransfersTray />);

  expect(await screen.findByText(/Movie\.2020\.BluRay-TEAM/)).toBeInTheDocument();
  expect(screen.queryByText(/Show\.S01\.WEB-TEAM/)).not.toBeInTheDocument();
  expect(screen.getByText(/30\s*%/)).toBeInTheDocument();
});

it("Annuler appelle cancelCommitJob avec le bon job_id", async () => {
  vi.mocked(listCommitJobs).mockResolvedValue([ACTIVE_JOB]);
  vi.mocked(cancelCommitJob).mockResolvedValue({ status: "cancelling" });
  const user = userEvent.setup();
  render(<ActiveTransfersTray />);

  await user.click(await screen.findByRole("button", { name: /Annuler/i }));

  expect(cancelCommitJob).toHaveBeenCalledWith("job-1");
});
```

Dans `frontend/src/pages/GapScanPage.test.tsx`, ajouter un mock du nouveau composant (même pattern que `UploadPrepPanel` — voir `vi.mock("../components/UploadPrepPanel", ...)` existant) :

```tsx
vi.mock("../components/ActiveTransfersTray", () => ({
  default: () => <div>Transferts en cours (mock)</div>,
}));
```

Puis ajouter un test :

```tsx
it("affiche l'encart Transferts en cours", async () => {
  renderPage();
  expect(await screen.findByText("Transferts en cours (mock)")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/ActiveTransfersTray.test.tsx src/pages/GapScanPage.test.tsx`
Expected: FAIL — `Failed to resolve import "./ActiveTransfersTray"` ; sur `GapScanPage.test.tsx`, le texte "Transferts en cours (mock)" n'est pas trouvé (le composant n'est pas encore monté).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/ActiveTransfersTray.tsx` :

```tsx
import { useEffect, useRef, useState } from "react";
import { cancelCommitJob, listCommitJobs } from "../api/client";
import type { CommitJob } from "../api/types";

const STEP_LABELS: Record<string, string> = {
  staging: "Mise en scène",
  generating_nfo: "Génération du .nfo",
  building_torrent: "Génération du torrent",
};

const ACTIVE_STATES = ["staging", "generating_nfo", "building_torrent"];

/** Encart INDEPENDANT de tout panneau "Preparer l'upload" ouvert -- visible
 * meme apres un rechargement de page (AUTOMATION.md, sous-projet 4c) :
 * interroge GET /gapscan/commit-jobs au montage, puis en continu tant qu'au
 * moins une tache est active. N'affiche que les taches NON terminales --
 * une fois done/error/cancelled, le resultat reste visible dans le panneau
 * d'origine (s'il est encore ouvert) ; pas de mecanisme de "rejet" ici, le
 * registre serveur n'est jamais purge (voir commit_job_runner.py). Masque
 * si aucune tache active. */
export default function ActiveTransfersTray() {
  const [jobs, setJobs] = useState<CommitJob[]>([]);
  const pollRef = useRef<number | null>(null);

  async function refresh() {
    try {
      const all = await listCommitJobs();
      setJobs(all);
    } catch {
      // best effort -- pas d'erreur bloquante pour un simple encart de suivi
    }
  }

  async function handleCancel(jobId: string) {
    try {
      await cancelCommitJob(jobId);
    } catch {
      // best effort -- si la tache s'est deja terminee entre-temps (404),
      // le prochain refresh() reflete l'etat reel de toute facon
    } finally {
      refresh();
    }
  }

  useEffect(() => {
    refresh();
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible = jobs.filter((j) => ACTIVE_STATES.includes(j.state));

  useEffect(() => {
    const hasActive = visible.length > 0;
    if (hasActive && pollRef.current === null) {
      pollRef.current = window.setInterval(refresh, 1500);
    } else if (!hasActive && pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible.length]);

  if (visible.length === 0) return null;

  return (
    <div className="space-y-2 rounded-md border border-line bg-surface p-3">
      <h2 className="font-display text-xs font-semibold text-ink-dim">Transferts en cours</h2>
      {visible.map((job) => (
        <div key={job.job_id} className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink">
            <span className="font-mono">{job.release_name}</span>
            <button
              type="button"
              onClick={() => handleCancel(job.job_id)}
              className="text-crit underline"
            >
              Annuler
            </button>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-surface-2">
            <div className="h-full bg-accent transition-all" style={{ width: `${job.percent}%` }} />
          </div>
          <p className="text-xs text-ink-dim">
            {STEP_LABELS[job.state] ?? job.state} — {Math.round(job.percent)}%
          </p>
        </div>
      ))}
    </div>
  );
}
```

Dans `frontend/src/pages/GapScanPage.tsx`, ajouter l'import (après `UploadPrepPanel`) :

```tsx
import ActiveTransfersTray from "../components/ActiveTransfersTray";
```

Et monter le composant juste après la fermeture du bloc d'en-tête (`</div>` qui suit le bouton "Lancer un scan", juste avant `{notConfigured && (`) :

```tsx
      </div>

      <ActiveTransfersTray />

      {notConfigured && (
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ActiveTransfersTray.test.tsx src/pages/GapScanPage.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Full frontend suite + `tsc`, then commit**

```bash
cd frontend
npx vitest run
npx tsc --noEmit -p tsconfig.app.json
git add src/components/ActiveTransfersTray.tsx src/components/ActiveTransfersTray.test.tsx src/pages/GapScanPage.tsx src/pages/GapScanPage.test.tsx
git commit -m "feat: encart Transferts en cours (ActiveTransfersTray) - survit a un rechargement de page"
```

At this point, run the full backend suite (`pytest`, `ruff check nfogen/ tests/`) AND the full frontend suite (`npx vitest run`, `npx tsc --noEmit -p tsconfig.app.json`) one final time together — this is the "merged result" check before handing off to `finishing-a-development-branch`.

---

## Post-implementation documentation (not a TDD task, do last)

- [ ] Mettre à jour AUTOMATION.md : nouvelle section "Sous-projet 4c : Suivi d'avancement asynchrone de Confirmer" (Livré, date du jour), lien vers la spec et ce plan, résumé de la déviation assumée (`torf interval=0` au lieu de `1.0`).
- [ ] Mettre à jour le tableau de décomposition (AUTOMATION.md) si sous-projet 4c y mérite une ligne dédiée.
- [ ] `CHANGELOG.md` : nouvelle entrée `### Ajouté` — Confirmer s'exécute en tâche de fond avec suivi de progression (copie + hash du torrent), plusieurs tâches en parallèle, annulation, encart "Transferts en cours" qui survit à un rechargement de page.
- [ ] Rappeler à l'utilisateur, dans le message de fin de session : les tâches en cours sont perdues si le serveur redémarre pendant l'opération (non-objectif assumé, voir la spec) — pas de reprise automatique.
