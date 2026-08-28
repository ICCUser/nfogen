# Orchestration nommage -> mise en scene + torrent (AUTOMATION.md sous-projet 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relier les briques existantes (proposition de nom, mise en scene, generation de `.torrent`) en un flux "apercu sans ecriture disque -> confirmation par groupe" utilisable depuis un bouton sur la page GapScan.

**Architecture:** Un nouveau module pur `nfogen/upload_prep.py` orchestre `name_proposal.py`/`file_staging.py`/`torrent_builder.py` sans dupliquer leur logique ; il reutilise le VRAI validateur du profil (`registry.get_validator`) pour recuperer gratuitement `cross_checks`/`upscale_checks`/`track_language_checks`. Deux endpoints HTTP (`preview` lecture seule, `commit` par groupe) exposent ce module ; un composant React dedie (`UploadPrepPanel`) l'affiche depuis un bouton sur `GapScanPage`.

**Tech Stack:** Python (FastAPI, dataclasses), pytest, React/TypeScript, Vitest/Testing Library.

**Spec:** [AUTOMATION.md](../../../AUTOMATION.md), section "Sous-projet 4 : Orchestration du nommage -> mise en scene + `.torrent`".

## Global Constraints

- TDD strict : test rouge confirme avant toute implementation, pour chaque etape.
- `npx tsc --noEmit -p tsconfig.app.json` (jamais `npx tsc --noEmit` seul — ne verifie rien dans ce depot, `tsconfig.json` racine a `files: []`).
- Aucun sous-agent (`Agent`/subagent) sur ce projet — execution entierement inline.
- Jamais modifier/deplacer le fichier media source original — `file_staging.py` (deja livre) est le seul point d'ecriture, jamais appele directement sur un chemin source.
- Le "passkey"/l'adresse d'annonce C411 ne doit jamais apparaitre dans un log ni une reponse HTTP en clair au-dela de ce qui est deja expose par `gapscan_config_store.py`.
- `commit_upload()` necessite l'extra optionnel `automation` (torf) — degrade proprement (pas de crash a l'import) si absent, comme le reste de GapScan degrade sans son extra.
- Toutes les chaines visibles utilisateur (avertissements, labels UI) en francais, coherent avec le reste du projet.
- Commit frequent, un commit par tache.

---

## File Structure

- **Create** `nfogen/upload_prep.py` : dataclasses `ProposedFile`/`GroupProposal`/`CommitResult`, `group_by_team()`, `preview_upload()`, `commit_upload()`.
- **Create** `tests/test_upload_prep.py` : tests unitaires/integration du module ci-dessus.
- **Modify** `nfogen/name_proposal.py` : `_extract_team` -> `extract_team_tag` (public), `_strip_ext` -> `strip_ext` (public), memes corps, tous les appels internes mis a jour.
- **Modify** `tests/test_name_proposal.py` : 2 tests directs des fonctions nouvellement publiques.
- **Modify** `nfogen/api.py` : import guarde de `upload_prep`, 2 endpoints `/gapscan/prepare-upload/preview` et `/gapscan/prepare-upload/commit`, modeles de requete Pydantic, helper `_run_upload_prep`.
- **Modify** `tests/test_api.py` : tests des 2 nouveaux endpoints (auth, gating GapScan, preview reel, commit reel).
- **Modify** `frontend/src/api/types.ts` : `UploadPrepFile`, `UploadGroupProposal`, `UploadCommitResult`.
- **Modify** `frontend/src/api/client.ts` : `prepareUploadPreview()`, `prepareUploadCommit()`.
- **Create** `frontend/src/components/UploadPrepPanel.tsx` : affichage de l'apercu + confirmation par groupe.
- **Create** `frontend/src/components/UploadPrepPanel.test.tsx` : tests du composant.
- **Modify** `frontend/src/pages/GapScanPage.tsx` : bouton "Preparer l'upload" par ligne eligible, etat pour afficher le panneau.
- **Modify** `frontend/src/pages/GapScanPage.test.tsx` : test du nouveau bouton.
- **Modify** `AUTOMATION.md`, `CHANGELOG.md` : marquer le sous-projet 4 comme livre.

---

### Task 1: `name_proposal.py` — rendre publiques `extract_team_tag` / `strip_ext`

**Files:**
- Modify: `nfogen/name_proposal.py`
- Test: `tests/test_name_proposal.py`

**Interfaces:**
- Produces: `extract_team_tag(text: str) -> str | None`, `strip_ext(filename: str) -> str` — utilisees par `nfogen/upload_prep.py` (Task 2).

- [ ] **Step 1: Write the failing tests**

Ajouter a la fin de `tests/test_name_proposal.py` :

```python
# --------------------------------------------------------------------------- #
# Fonctions publiques reutilisees par l'orchestration (AUTOMATION.md,
# sous-projet 4) : group_by_team() a besoin de detecter le tag d'equipe
# et de retirer l'extension d'un nom de fichier, independamment d'un
# calcul complet de proposition.
# --------------------------------------------------------------------------- #
def test_extract_team_tag_is_public():
    from nfogen.name_proposal import extract_team_tag

    assert extract_team_tag("Mr.Robot.S01E01.1080p.WEB.H264-NTb") == "NTb"
    assert extract_team_tag("aucune-equipe-ici.txt") is None or extract_team_tag("sans_suffixe") is None


def test_strip_ext_is_public():
    from nfogen.name_proposal import strip_ext

    assert strip_ext("Movie.2020.1080p.mkv") == "Movie.2020.1080p"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -k "extract_team_tag_is_public or strip_ext_is_public" -v`
Expected: FAIL avec `ImportError: cannot import name 'extract_team_tag'`

- [ ] **Step 3: Renommer dans `nfogen/name_proposal.py`**

Renommer la definition et tous les appels internes (garder le corps identique) :
- `def _strip_ext(filename: str) -> str:` -> `def strip_ext(filename: str) -> str:`
- `def _extract_team(text: str) -> str | None:` -> `def extract_team_tag(text: str) -> str | None:`
- Tous les appels `_strip_ext(` -> `strip_ext(` (dans `_clean_title`'s appelants et `propose_video_release_name`, precisement la ligne `stems = [_strip_ext(f) for f in filenames]`).
- Tous les appels `_extract_team(` -> `extract_team_tag(` (dans `_extract_team` -> ex-nom lui-meme n'a pas d'auto-appel ; dans la boucle `team = (_extract_team(hint) if hint else None) or _extract_team(stem)` -> `extract_team_tag(hint) if hint else None) or extract_team_tag(stem)`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -v`
Expected: tous les tests du fichier passent (le renommage ne doit rien casser).

- [ ] **Step 5: Commit**

```bash
git add nfogen/name_proposal.py tests/test_name_proposal.py
git commit -m "AUTOMATION sous-projet 4 (1/6) : rend extract_team_tag/strip_ext publiques"
```

---

### Task 2: `nfogen/upload_prep.py` — dataclasses + `group_by_team()`

**Files:**
- Create: `nfogen/upload_prep.py`
- Create: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: `nfogen.name_proposal.extract_team_tag`, `nfogen.name_proposal.strip_ext` (Task 1).
- Produces: `ProposedFile(source_path: str, staged_name: str)`, `GroupProposal(release_name: str | None, files: list[ProposedFile], warnings: list[str], blocked: bool)`, `CommitResult(release_name: str, staged_path: str, torrent_path: str)`, `group_by_team(filenames: list[str], hints: list[str | None]) -> list[list[int]]` — utilises par Task 3/4/5.

- [ ] **Step 1: Write the failing tests**

Creer `tests/test_upload_prep.py` :

```python
"""Tests de l'orchestration nommage -> mise en scene + torrent
(`nfogen/upload_prep.py`, AUTOMATION.md sous-projet 4)."""
from __future__ import annotations

from nfogen.upload_prep import group_by_team


def test_files_with_same_team_form_one_group():
    filenames = ["Show.S01E01.1080p.WEB.x264-TEAM.mkv", "Show.S01E02.1080p.WEB.x264-TEAM.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]


def test_files_with_different_teams_form_separate_groups():
    filenames = ["Show.S01E01.1080p.WEB.x264-TeamA.mkv", "Show.S01E02.1080p.WEB.x264-TeamB.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0], [1]]


def test_hint_takes_priority_over_filename_for_grouping():
    filenames = ["Show.S01E01.1080p.WEB.x264-FromFilename.mkv"]
    hints = ["Show S01E01 1080p WebDl x264 - FromHint"]
    groups = group_by_team(filenames, hints)
    # Le hint donne "FromHint", different du nom de fichier -- ne doit pas
    # se retrouver mélangé avec un fichier qui, lui, n'a que "FromFilename".
    other = ["Show.S01E02.1080p.WEB.x264-FromFilename.mkv"]
    combined = group_by_team(filenames + other, hints + [None])
    assert combined == [[0], [1]]


def test_files_with_no_detectable_team_form_their_own_group():
    filenames = ["random_clip_one.mkv", "random_clip_two.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]  # les deux "None" forment un seul groupe ensemble


def test_group_order_matches_first_appearance():
    filenames = [
        "Show.S01E01.1080p.WEB.x264-TeamB.mkv",
        "Show.S01E02.1080p.WEB.x264-TeamA.mkv",
        "Show.S01E03.1080p.WEB.x264-TeamB.mkv",
    ]
    groups = group_by_team(filenames, [None, None, None])
    assert groups == [[0, 2], [1]]


def test_empty_input_returns_no_groups():
    assert group_by_team([], []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.upload_prep'`

- [ ] **Step 3: Write minimal implementation**

Creer `nfogen/upload_prep.py` :

```python
"""Orchestration nommage -> mise en scene + `.torrent` (AUTOMATION.md,
sous-projet 4) : relie `name_proposal.py` (nommage), `file_staging.py` +
`torrent_builder.py` (sous-projet 2) sans dupliquer leur logique. Deux
etapes volontairement separees : `preview_upload()` (lecture seule --
extraction MediaInfo + calcul des noms + avertissements, AUCUNE ecriture
disque) puis `commit_upload()` (mise en scene + `.torrent`, un groupe a la
fois) -- la mise en scene cree de vrais fichiers et la generation de
`.torrent` hash tout le contenu, potentiellement lent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .name_proposal import extract_team_tag, strip_ext


@dataclass
class ProposedFile:
    """Un fichier source et le nom individuel propose pour sa mise en
    scene (ex: `Show.S01E01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM.mkv`)."""

    source_path: str
    staged_name: str


@dataclass
class GroupProposal:
    """Une proposition d'upload pour un groupe de fichiers partageant le
    meme tag d'equipe (voir `group_by_team`). `release_name` est le nom
    de PACK (dossier + `.torrent`) ; `None` si aucune proposition n'a pu
    etre calculee. `blocked=True` : ce groupe ne peut pas etre confirme
    (nom impossible a calculer, ou nom calcule non conforme a la
    convention du profil) -- toujours accompagne d'un avertissement
    explicite dans `warnings`."""

    release_name: Optional[str]
    files: list[ProposedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False


@dataclass
class CommitResult:
    """Resultat de `commit_upload()` : ou le contenu a ete mis en scene
    (fichier unique ou dossier selon la taille du groupe) et ou le
    `.torrent` correspondant a ete ecrit."""

    release_name: str
    staged_path: str
    torrent_path: str


def group_by_team(filenames: list[str], hints: list[Optional[str]]) -> list[list[int]]:
    """Groupe les index de `filenames` par tag d'equipe detecte (meme
    priorite indice > nom de fichier que `name_proposal.propose_video_release_name`).
    Resout un cas reel signale par l'utilisateur : un pack assemble a
    partir de plusieurs releases (tags d'equipe differents) ne doit plus
    faire echouer toute la proposition en bloc -- chaque equipe devient
    son propre groupe, propose independamment. Aucun tag detecte = son
    propre groupe (jamais fusionne par supposition avec un tag reel).
    Ordre des groupes = ordre de premiere apparition du tag."""
    groups: dict[Optional[str], list[int]] = {}
    order: list[Optional[str]] = []
    for i, (filename, hint) in enumerate(zip(filenames, hints)):
        stem = strip_ext(filename)
        team = (extract_team_tag(hint) if hint else None) or extract_team_tag(stem)
        if team not in groups:
            groups[team] = []
            order.append(team)
        groups[team].append(i)
    return [groups[team] for team in order]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "AUTOMATION sous-projet 4 (2/6) : upload_prep.py, group_by_team()"
```

---

### Task 3: `preview_upload()` — apercu sans ecriture disque

**Files:**
- Modify: `nfogen/upload_prep.py`
- Test: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: `nfogen.engine.propose_release_name(*, category, profile, filenames, title_hints) -> NameProposal` (existant), `nfogen.registry.get_validator(profile, category) -> Validator | None` (existant), `nfogen.models.RenderContext` (existant), `nfogen.extract.extract_video_metadata(source: Path) -> dict` (existant, champs `video_height`/`video_width`/`video_bit_rate`/`frame_rate`/`video_format`/`audio_languages`/`subtitle_languages`/`general_title`), `group_by_team` (Task 2).
- Produces: `preview_upload(local_paths: list[str], profile: str = "c411") -> list[GroupProposal]` — utilise par Task 5 (API) et Task 4 (rien, independant).

- [ ] **Step 1: Write the failing tests**

Ajouter a `tests/test_upload_prep.py` :

```python
from unittest.mock import patch

from nfogen.upload_prep import preview_upload


def _fake_metadata(**overrides):
    base = {
        "video_height": None, "video_width": None, "video_format": None,
        "video_bit_rate": None, "frame_rate": None,
        "audio_languages": [], "subtitle_languages": [], "general_title": None,
    }
    base.update(overrides)
    return base


def test_single_movie_file_proposes_a_name_and_matching_staged_file():
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(["/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"])
    assert len(proposals) == 1
    group = proposals[0]
    assert group.blocked is False
    assert group.release_name is not None
    assert group.release_name.startswith("Kaamelott")
    assert len(group.files) == 1
    assert group.files[0].source_path == "/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"
    assert group.files[0].staged_name == f"{group.release_name}.mkv"


def test_season_pack_same_team_produces_one_group_with_per_file_names():
    paths = [
        "/media/One.Piece.S01E01.MULTI.VFF.1080p.WEB.AC3.x264-NOTAG.mkv",
        "/media/One.Piece.S01E02.MULTI.VFF.1080p.WEB.AC3.x264-NOTAG.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    group = proposals[0]
    assert group.release_name is not None
    assert ".S01." in group.release_name  # identifiant de pack, pas par-episode
    assert len(group.files) == 2
    assert "S01E01" in group.files[0].staged_name
    assert "S01E02" in group.files[1].staged_name
    # Le nom de pack sert de prefixe coherent sur chaque fichier individuel.
    assert group.files[0].staged_name.startswith("One.Piece")


def test_multi_team_pack_splits_into_separate_groups():
    paths = [
        "/media/Show.S01E01.1080p.WEB.x264-TeamA.mkv",
        "/media/Show.S01E02.1080p.WEB.x264-TeamB.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 2
    release_names = {p.release_name for p in proposals}
    assert any(name and name.endswith("-TeamA") for name in release_names)
    assert any(name and name.endswith("-TeamB") for name in release_names)


def test_ambiguous_group_is_blocked_with_no_files():
    """Deux saisons differentes AVEC le meme tag d'equipe : group_by_team ne
    les separe pas (meme equipe), mais name_proposal refuse toujours ce cas
    (saisons incoherentes) -- le groupe est marque bloque plutot que de
    deviner laquelle utiliser."""
    paths = ["/media/Show.S01E01.1080p.WEB.x264-TEAM.mkv", "/media/Show.S02E01.1080p.WEB.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert proposals[0].blocked is True
    assert proposals[0].release_name is None
    assert proposals[0].files == []
    assert any("saisons" in w for w in proposals[0].warnings)


def test_extraction_failure_for_one_file_does_not_crash():
    def fake_extract(source):
        if "corrupt" in str(source):
            raise RuntimeError("libmediainfo: fichier illisible")
        return _fake_metadata()

    paths = ["/media/corrupt.S01E01.1080p.WEB.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", side_effect=fake_extract):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert any("illisible" in w.lower() or "métadonnées" in w.lower() for w in proposals[0].warnings)
    assert proposals[0].release_name is not None  # l'echec d'extraction n'empeche pas le nommage


def test_upscale_warning_surfaces_through_real_c411_validator():
    """Preuve du cablage complet : preview_upload() reutilise le VRAI
    validateur du profil C411 (cross_checks + upscale_checks), sans aucune
    logique dupliquee ici."""
    meta = _fake_metadata(
        video_height=1080, video_width=1920, video_bit_rate=1_500_000, frame_rate=24.0,
    )
    paths = ["/media/Movie.2020.VFF.1080p.BluRay.AC3.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=meta):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert any("upscale" in w.lower() for w in proposals[0].warnings)
    assert proposals[0].blocked is False  # avertissement, jamais bloquant


def test_name_with_no_detectable_codec_is_blocked_by_real_validator():
    """Le nom propose ne respecte pas la convention C411 (codec video
    obligatoire absent) -- le vrai validateur du profil le refuse, le
    groupe est bloque plutot que mis en scene avec un nom invalide."""
    paths = ["/media/nom_totalement_generique.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert proposals[0].blocked is True


def test_empty_local_paths_returns_empty_list():
    assert preview_upload([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -k preview -v`
Expected: FAIL avec `AttributeError: module 'nfogen.upload_prep' has no attribute 'preview_upload'`

- [ ] **Step 3: Write minimal implementation**

Ajouter a `nfogen/upload_prep.py` (apres les imports existants, ajouter) :

```python
from . import extract
from .engine import propose_release_name
from .models import RenderContext
from .registry import get_validator
```

Puis ajouter apres `group_by_team` :

```python
def _extraction_warning(filename: str) -> str:
    return f"[{filename}] Métadonnées illisibles : extraction MediaInfo échouée."


def preview_upload(local_paths: list[str], profile: str = "c411") -> list[GroupProposal]:
    """Sans aucune ecriture disque : extrait les metadonnees (best-effort --
    une extraction illisible devient un avertissement, jamais un
    plantage), groupe par equipe (`group_by_team`), propose un nom de
    pack + un nom par fichier pour chaque groupe, valide via le VRAI
    validateur du profil (`registry.get_validator`) -- recupere
    gratuitement `cross_checks`/`upscale_checks`/`track_language_checks`
    sans dupliquer cette logique ici."""
    if not local_paths:
        return []

    filenames = [Path(p).name for p in local_paths]
    metas: list[dict] = []
    extraction_warning_by_index: dict[int, str] = {}
    for i, path in enumerate(local_paths):
        try:
            meta = extract.extract_video_metadata(Path(path))
        except Exception:
            meta = {}
            extraction_warning_by_index[i] = _extraction_warning(filenames[i])
        meta["name"] = filenames[i]
        metas.append(meta)

    hints: list[Optional[str]] = [m.get("general_title") or None for m in metas]
    validator = get_validator(profile, "video")

    proposals: list[GroupProposal] = []
    for index_group in group_by_team(filenames, hints):
        group_paths = [local_paths[i] for i in index_group]
        group_filenames = [filenames[i] for i in index_group]
        group_hints = [hints[i] for i in index_group]
        group_metas = [metas[i] for i in index_group]
        group_extraction_warnings = [
            extraction_warning_by_index[i] for i in index_group if i in extraction_warning_by_index
        ]

        pack = propose_release_name(
            category="video", profile=profile, filenames=group_filenames, title_hints=group_hints
        )
        warnings = group_extraction_warnings + list(pack.warnings)

        if pack.name is None:
            proposals.append(GroupProposal(release_name=None, files=[], warnings=warnings, blocked=True))
            continue

        files: list[ProposedFile] = []
        for path, filename, hint in zip(group_paths, group_filenames, group_hints):
            single = propose_release_name(
                category="video", profile=profile, filenames=[filename], title_hints=[hint]
            )
            base_name = single.name or pack.name
            files.append(ProposedFile(source_path=path, staged_name=base_name + Path(filename).suffix))

        blocked = False
        if validator is not None:
            ctx = RenderContext(
                profile=profile, category="video",
                data={"release_name": pack.name, "video_metadata": group_metas},
            )
            try:
                warnings = warnings + validator(ctx, "")
            except ValueError as exc:
                warnings = warnings + [str(exc)]
                blocked = True

        proposals.append(
            GroupProposal(release_name=pack.name, files=files, warnings=warnings, blocked=blocked)
        )
    return proposals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "AUTOMATION sous-projet 4 (3/6) : preview_upload()"
```

---

### Task 4: `commit_upload()` — mise en scene + `.torrent`

**Files:**
- Modify: `nfogen/upload_prep.py`
- Test: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: `nfogen.file_staging.stage_file(source_path, target_path) -> str`, `nfogen.file_staging.stage_files(source_paths, target_dir, names) -> list[str]`, `nfogen.gapscan_config_store.effective_staging_dir() -> str | None`, `nfogen.gapscan_config_store.effective_c411_announce_url() -> str | None` (tous existants). `nfogen.torrent_builder.build_torrent(staged_path, announce_url, output_path)` (existant, import differe -- extra `automation`).
- Produces: `commit_upload(release_name: str, files: list[ProposedFile], profile: str = "c411") -> CommitResult` — utilise par Task 5 (API).

- [ ] **Step 1: Write the failing tests**

Ajouter a `tests/test_upload_prep.py` :

```python
from pathlib import Path as _Path

from nfogen.upload_prep import CommitResult, ProposedFile, commit_upload


def _make_source(tmp_path, name: str, content: bytes = b"contenu de test") -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_commit_single_file_stages_and_builds_torrent(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_c411_announce_url",
        lambda: "https://c411.example/announce/abc123",
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files)

    assert isinstance(result, CommitResult)
    assert result.staged_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.mkv")
    assert _Path(result.staged_path).is_file()
    assert result.torrent_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.torrent")
    assert _Path(result.torrent_path).is_file()


def test_commit_multi_file_group_stages_into_a_folder(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_c411_announce_url",
        lambda: "https://c411.example/announce/abc123",
    )
    files = [
        ProposedFile(source_path=_make_source(tmp_path, "e01.mkv"), staged_name="Show.S01E01-TEAM.mkv"),
        ProposedFile(source_path=_make_source(tmp_path, "e02.mkv"), staged_name="Show.S01E02-TEAM.mkv"),
    ]

    result = commit_upload("Show.S01-TEAM", files)

    pack_dir = staging_dir / "Show.S01-TEAM"
    assert result.staged_path == str(pack_dir)
    assert (pack_dir / "Show.S01E01-TEAM.mkv").is_file()
    assert (pack_dir / "Show.S01E02-TEAM.mkv").is_file()
    assert _Path(result.torrent_path).is_file()


def test_commit_without_staging_dir_configured_raises(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: None)
    with pytest.raises(ValueError, match="scene"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


def test_commit_without_announce_url_configured_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_c411_announce_url", lambda: None
    )
    with pytest.raises(ValueError, match="annonce"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


def test_commit_without_automation_extra_raises(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep._TORRENT_BUILDER_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="automation"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])
```

Ajouter en tete du fichier de test (avec les autres imports) : `import pytest`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -k commit -v`
Expected: FAIL avec `AttributeError: module 'nfogen.upload_prep' has no attribute 'commit_upload'`

- [ ] **Step 3: Write minimal implementation**

Ajouter aux imports de `nfogen/upload_prep.py` :

```python
from . import file_staging, gapscan_config_store

try:
    from . import torrent_builder

    _TORRENT_BUILDER_AVAILABLE = True
except ImportError:
    _TORRENT_BUILDER_AVAILABLE = False
```

Ajouter a la fin du fichier :

```python
def commit_upload(release_name: str, files: list[ProposedFile], profile: str = "c411") -> CommitResult:
    """Met en scene (hardlink/copie, `file_staging.py`) et genere le
    `.torrent` (`torrent_builder.py`) pour UN groupe deja propose par
    `preview_upload()` -- le frontend renvoie exactement ce qu'il a recu
    pour ce groupe, aucun etat serveur entre les deux appels. Fichier
    unique mis en scene directement (`<release_name><ext>`), groupe
    multi-fichiers dans un dossier (`<release_name>/<nom par fichier>`)."""
    if not _TORRENT_BUILDER_AVAILABLE:
        raise RuntimeError(
            "Génération de .torrent indisponible : pip install nfogen[automation]"
        )
    staging_dir = gapscan_config_store.effective_staging_dir()
    if not staging_dir:
        raise ValueError(
            "Dossier de mise en scène non configuré (PUT /gapscan/config, champ staging_dir)."
        )
    announce_url = gapscan_config_store.effective_c411_announce_url()
    if not announce_url:
        raise ValueError(
            "Adresse d'annonce C411 non configurée (PUT /gapscan/config, champ c411_announce_url)."
        )

    if len(files) == 1:
        staged_path = str(Path(staging_dir) / files[0].staged_name)
        file_staging.stage_file(files[0].source_path, staged_path)
    else:
        target_dir = str(Path(staging_dir) / release_name)
        file_staging.stage_files(
            [f.source_path for f in files], target_dir, [f.staged_name for f in files]
        )
        staged_path = target_dir

    torrent_path = str(Path(staging_dir) / f"{release_name}.torrent")
    torrent_builder.build_torrent(staged_path, announce_url, torrent_path)
    return CommitResult(release_name=release_name, staged_path=staged_path, torrent_path=torrent_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: tous les tests passent (verifier que `torf` est installe dans le venv : `.venv/Scripts/python.exe -m pip show torf`, sinon `pip install torf`).

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "AUTOMATION sous-projet 4 (4/6) : commit_upload()"
```

---

### Task 5: API — `/gapscan/prepare-upload/preview` et `/commit`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `nfogen.upload_prep.preview_upload`, `nfogen.upload_prep.commit_upload`, `nfogen.upload_prep.ProposedFile` (Task 2-4).
- Produces: `POST /gapscan/prepare-upload/preview` (body `{local_paths: string[], profile?: string}` -> `GroupProposal[]` en JSON), `POST /gapscan/prepare-upload/commit` (body `{release_name: string, files: {source_path, staged_name}[], profile?: string}` -> `CommitResult` en JSON) — utilises par Task 6 (frontend).

- [ ] **Step 1: Write the failing tests**

Ajouter a `tests/test_api.py`, apres la section GapScan existante (chercher `def test_gapscan_config_write_then_read_back` et ajouter a la suite) :

```python
# --------------------------------------------------------------------------- #
# Preparation d'upload (POST /gapscan/prepare-upload/preview, /commit --
# AUTOMATION.md sous-projet 4)
# --------------------------------------------------------------------------- #
def test_prepare_upload_routes_require_gapscan_available(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)
    assert client.post("/gapscan/prepare-upload/preview", json={"local_paths": []}).status_code == 501
    assert (
        client.post("/gapscan/prepare-upload/commit", json={"release_name": "x", "files": []}).status_code
        == 501
    )


def test_prepare_upload_routes_require_auth_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    assert client.post("/gapscan/prepare-upload/preview", json={"local_paths": []}).status_code == 401
    assert (
        client.post("/gapscan/prepare-upload/commit", json={"release_name": "x", "files": []}).status_code
        == 401
    )


def test_prepare_upload_preview_empty_paths_returns_empty_list(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/prepare-upload/preview", json={"local_paths": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_prepare_upload_preview_real_c411_profile(reload_api):
    """Bout-en-bout via l'API : pas de fichier reel necessaire, MediaInfo
    echouera sur un chemin inexistant (extraction best-effort, voir
    upload_prep.preview_upload) mais le nommage/groupement fonctionnent
    quand meme sur le nom de fichier seul."""
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/gapscan/prepare-upload/preview",
        json={"local_paths": ["/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["release_name"].startswith("Kaamelott")
    assert body[0]["files"][0]["source_path"] == "/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"


def test_prepare_upload_commit_without_staging_dir_is_400(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)
    resp = client.post(
        "/gapscan/prepare-upload/commit",
        json={"release_name": "X", "files": [{"source_path": "/x.mkv", "staged_name": "X.mkv"}]},
    )
    assert resp.status_code == 400
    assert "scène" in resp.json()["detail"] or "scene" in resp.json()["detail"].lower()


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
            "c411_announce_url": "https://c411.example/announce/abc123",
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
    body = resp.json()
    assert body["release_name"] == "Movie.2020.1080p.x264-TEAM"
    assert body["staged_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.mkv")
    assert body["torrent_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.torrent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k prepare_upload -v`
Expected: FAIL avec des 404 (routes inexistantes) sur la plupart des assertions de status_code.

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/api.py`, ajouter `upload_prep` a l'import guarde GapScan existant (chercher le bloc `try: from . import gapscan_config_store, gapscan_runner`) :

```python
try:
    from . import gapscan_config_store, gapscan_runner, upload_prep
    from .c411_client import C411Client, C411Error
    from .radarr_client import RadarrClient, RadarrError
    from .sonarr_client import SonarrClient, SonarrError

    _GAPSCAN_AVAILABLE = True
except ImportError:
    _GAPSCAN_AVAILABLE = False
```

Ajouter `from dataclasses import asdict` si pas deja importe (verifier — deja utilise ligne ~825 pour `gapscan_results`, donc deja present, ne pas dupliquer l'import).

A la fin du fichier (apres `gapscan_results_export_csv`), ajouter :

```python
# --------------------------------------------------------------------------- #
# Preparation d'upload (AUTOMATION.md, sous-projet 4) : nommage -> mise en
# scene + .torrent, a partir de chemins locaux deja resolus (voir
# GapResult.local_paths, sous-projet 1). Le frontend a deja ces chemins en
# memoire depuis GET /gapscan/results -- pas besoin d'un identifiant
# GapResult, ce module reste decouple du modele de donnees GapScan.
# --------------------------------------------------------------------------- #
def _run_upload_prep(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la préparation d'upload")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


class PrepareUploadPreviewRequest(BaseModel):
    local_paths: list[str] = []
    profile: str = "c411"


@app.post("/gapscan/prepare-upload/preview", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_preview(req: PrepareUploadPreviewRequest) -> list[dict[str, Any]]:
    _require_gapscan_available()
    proposals = _run_upload_prep(upload_prep.preview_upload, req.local_paths, profile=req.profile)
    return [asdict(p) for p in proposals]


class PrepareUploadFile(BaseModel):
    source_path: str
    staged_name: str


class PrepareUploadCommitRequest(BaseModel):
    release_name: str
    files: list[PrepareUploadFile]
    profile: str = "c411"


@app.post("/gapscan/prepare-upload/commit", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_commit(req: PrepareUploadCommitRequest) -> dict[str, Any]:
    _require_gapscan_available()
    files = [
        upload_prep.ProposedFile(source_path=f.source_path, staged_name=f.staged_name) for f in req.files
    ]
    result = _run_upload_prep(upload_prep.commit_upload, req.release_name, files, profile=req.profile)
    return asdict(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k prepare_upload -v`
Expected: tous les tests passent.

Puis la suite complete pour verifier l'absence de regression :

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: tous les tests passent (compter le total avant/apres pour verifier que rien n'a disparu silencieusement).

- [ ] **Step 5: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "AUTOMATION sous-projet 4 (5/6) : API /gapscan/prepare-upload/preview + /commit"
```

---

### Task 6: Frontend — types + client API

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: types `UploadPrepFile`, `UploadGroupProposal`, `UploadCommitResult` ; fonctions `prepareUploadPreview(localPaths: string[], profile?: string): Promise<UploadGroupProposal[]>`, `prepareUploadCommit(releaseName: string, files: UploadPrepFile[], profile?: string): Promise<UploadCommitResult>` — utilises par Task 7 (composant).

- [ ] **Step 1: Write the failing test**

Lire `frontend/src/api/client.test.ts` pour voir le pattern de test existant (mock de `fetch` global), puis y ajouter :

```ts
describe("prepareUploadPreview / prepareUploadCommit", () => {
  it("preview envoie local_paths et profile, renvoie la liste de groupes", async () => {
    const groups = [
      { release_name: "Movie.2020.1080p.x264-TEAM", files: [{ source_path: "/a.mkv", staged_name: "Movie.2020.1080p.x264-TEAM.mkv" }], warnings: [], blocked: false },
    ];
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => groups,
    });

    const result = await prepareUploadPreview(["/a.mkv"]);

    expect(result).toEqual(groups);
    const [url, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/gapscan/prepare-upload/preview");
    expect(JSON.parse(init.body as string)).toEqual({ local_paths: ["/a.mkv"], profile: "c411" });
  });

  it("commit envoie release_name/files/profile, renvoie le resultat", async () => {
    const commitResult = { release_name: "Movie.2020.1080p.x264-TEAM", staged_path: "/staging/Movie.2020.1080p.x264-TEAM.mkv", torrent_path: "/staging/Movie.2020.1080p.x264-TEAM.torrent" };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => commitResult,
    });

    const files = [{ source_path: "/a.mkv", staged_name: "Movie.2020.1080p.x264-TEAM.mkv" }];
    const result = await prepareUploadCommit("Movie.2020.1080p.x264-TEAM", files);

    expect(result).toEqual(commitResult);
    const [url, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/gapscan/prepare-upload/commit");
    expect(JSON.parse(init.body as string)).toEqual({
      release_name: "Movie.2020.1080p.x264-TEAM",
      files,
      profile: "c411",
    });
  });
});
```

Ajouter `prepareUploadPreview, prepareUploadCommit` a l'import depuis `"./client"` en tete du fichier de test.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `prepareUploadPreview is not a function` (ou erreur d'import TypeScript).

- [ ] **Step 3: Write minimal implementation**

Dans `frontend/src/api/types.ts`, ajouter a la fin du fichier :

```ts
// --------------------------------------------------------------------------- //
// Preparation d'upload (AUTOMATION.md, sous-projet 4) : nommage -> mise en
// scene + .torrent, a partir des chemins locaux deja resolus par GapScan.
// --------------------------------------------------------------------------- //
export interface UploadPrepFile {
  source_path: string;
  staged_name: string;
}

export interface UploadGroupProposal {
  /** null si aucune proposition n'a pu etre calculee pour ce groupe. */
  release_name: string | null;
  files: UploadPrepFile[];
  warnings: string[];
  /** true : ce groupe ne peut pas etre confirme (voir warnings pour le detail). */
  blocked: boolean;
}

export interface UploadCommitResult {
  release_name: string;
  staged_path: string;
  torrent_path: string;
}
```

Dans `frontend/src/api/client.ts`, ajouter `UploadCommitResult` et `UploadGroupProposal` et `UploadPrepFile` a l'import de types en tete du fichier, puis a la fin du fichier :

```ts
// --------------------------------------------------------------------------- //
// Preparation d'upload (AUTOMATION.md, sous-projet 4)
// --------------------------------------------------------------------------- //
/** Aucune ecriture disque cote serveur -- calcule uniquement les noms
 * proposes et les avertissements (voir nfogen/upload_prep.py:preview_upload). */
export function prepareUploadPreview(
  localPaths: string[],
  profile = "c411",
): Promise<UploadGroupProposal[]> {
  return request<UploadGroupProposal[]>("/gapscan/prepare-upload/preview", {
    method: "POST",
    body: JSON.stringify({ local_paths: localPaths, profile }),
  });
}

/** Met en scene (hardlink/copie) et genere le .torrent pour UN groupe deja
 * renvoye par `prepareUploadPreview` -- renvoyer exactement ce que
 * l'apercu a produit pour ce groupe (voir nfogen/upload_prep.py:commit_upload). */
export function prepareUploadCommit(
  releaseName: string,
  files: UploadPrepFile[],
  profile = "c411",
): Promise<UploadCommitResult> {
  return request<UploadCommitResult>("/gapscan/prepare-upload/commit", {
    method: "POST",
    body: JSON.stringify({ release_name: releaseName, files, profile }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS.

Puis verifier les types : `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: aucune erreur.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "AUTOMATION sous-projet 4 (6/6a) : client API prepareUploadPreview/Commit"
```

---

### Task 7: Frontend — composant `UploadPrepPanel`

**Files:**
- Create: `frontend/src/components/UploadPrepPanel.tsx`
- Create: `frontend/src/components/UploadPrepPanel.test.tsx`

**Interfaces:**
- Consumes: `prepareUploadPreview`, `prepareUploadCommit` (Task 6), types `UploadGroupProposal`/`UploadCommitResult` (Task 6).
- Produces: `export default function UploadPrepPanel(props: { localPaths: string[]; title: string; onClose: () => void }): JSX.Element` — utilise par Task 8 (`GapScanPage.tsx`).

- [ ] **Step 1: Write the failing test**

Creer `frontend/src/components/UploadPrepPanel.test.tsx` :

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import UploadPrepPanel from "./UploadPrepPanel";

vi.mock("../api/client", () => ({
  prepareUploadPreview: vi.fn(),
  prepareUploadCommit: vi.fn(),
}));

import { prepareUploadCommit, prepareUploadPreview } from "../api/client";
import { ApiError } from "../api/types";
import type { UploadGroupProposal } from "../api/types";

const ONE_GROUP: UploadGroupProposal[] = [
  {
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    files: [
      { source_path: "/media/movie.mkv", staged_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.mkv" },
    ],
    warnings: [],
    blocked: false,
  },
];

const BLOCKED_GROUP: UploadGroupProposal[] = [
  { release_name: null, files: [], warnings: ["Aucune année ni tag de saison détecté."], blocked: true },
];

beforeEach(() => {
  vi.mocked(prepareUploadPreview).mockReset();
  vi.mocked(prepareUploadCommit).mockReset();
});

afterEach(() => vi.restoreAllMocks());

it("charge et affiche l'apercu au montage", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  render(<UploadPrepPanel localPaths={["/media/movie.mkv"]} title="Movie" onClose={vi.fn()} />);

  await waitFor(() => {
    expect(screen.getByText(/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM/)).toBeInTheDocument();
  });
  expect(prepareUploadPreview).toHaveBeenCalledWith(["/media/movie.mkv"]);
});

it("un groupe bloque n'a pas de bouton Confirmer, affiche l'avertissement", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(BLOCKED_GROUP);
  render(<UploadPrepPanel localPaths={["/media/x.mkv"]} title="X" onClose={vi.fn()} />);

  await waitFor(() => {
    expect(screen.getByText(/Aucune année ni tag de saison/)).toBeInTheDocument();
  });
  expect(screen.queryByRole("button", { name: /Confirmer/i })).not.toBeInTheDocument();
});

it("Confirmer appelle prepareUploadCommit et affiche le resultat", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    staged_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.mkv",
    torrent_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.torrent",
  });
  const user = userEvent.setup();
  render(<UploadPrepPanel localPaths={["/media/movie.mkv"]} title="Movie" onClose={vi.fn()} />);

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  await waitFor(() => {
    expect(screen.getByText(/staging\/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM\.torrent/)).toBeInTheDocument();
  });
  expect(prepareUploadCommit).toHaveBeenCalledWith(
    "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    ONE_GROUP[0].files,
  );
});

it("une erreur de chargement affiche un message", async () => {
  vi.mocked(prepareUploadPreview).mockRejectedValue(new ApiError(500, "Erreur interne du serveur."));
  render(<UploadPrepPanel localPaths={["/media/movie.mkv"]} title="Movie" onClose={vi.fn()} />);

  await waitFor(() => {
    expect(screen.getByText(/Erreur interne du serveur/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: FAIL — module `./UploadPrepPanel` introuvable.

- [ ] **Step 3: Write minimal implementation**

Creer `frontend/src/components/UploadPrepPanel.tsx` :

```tsx
import { useEffect, useState } from "react";
import { prepareUploadCommit, prepareUploadPreview } from "../api/client";
import { ApiError } from "../api/types";
import type { UploadCommitResult, UploadGroupProposal } from "../api/types";

/** Apercu (sans ecriture disque) puis confirmation par groupe de la mise
 * en scene + generation de .torrent (AUTOMATION.md, sous-projet 4). Un
 * groupe = un tag d'equipe detecte -- un pack assemble depuis plusieurs
 * releases devient plusieurs groupes independants (voir
 * nfogen/upload_prep.py:group_by_team). Jamais de "tout confirmer" :
 * chaque groupe se confirme individuellement, coherent avec la decision
 * "upload un par un" (AUTOMATION.md, "Decisions deja prises"). */
export default function UploadPrepPanel({
  localPaths,
  title,
  onClose,
}: {
  localPaths: string[];
  title: string;
  onClose: () => void;
}) {
  const [groups, setGroups] = useState<UploadGroupProposal[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [committing, setCommitting] = useState<number | null>(null);
  const [commitResults, setCommitResults] = useState<Record<number, UploadCommitResult>>({});
  const [commitErrors, setCommitErrors] = useState<Record<number, string>>({});

  useEffect(() => {
    let cancelled = false;
    prepareUploadPreview(localPaths)
      .then((g) => {
        if (!cancelled) setGroups(g);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof ApiError ? e.message : "Aperçu indisponible.");
      });
    return () => {
      cancelled = true;
    };
  }, [localPaths]);

  async function handleConfirm(index: number, group: UploadGroupProposal) {
    if (!group.release_name) return;
    setCommitting(index);
    setCommitErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const result = await prepareUploadCommit(group.release_name, group.files);
      setCommitResults((prev) => ({ ...prev, [index]: result }));
    } catch (e) {
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Confirmation impossible.",
      }));
    } finally {
      setCommitting(null);
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

          {!group.blocked && group.release_name && !commitResults[index] && (
            <button
              type="button"
              onClick={() => handleConfirm(index, group)}
              disabled={committing === index}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              {committing === index ? "Confirmation…" : "Confirmer"}
            </button>
          )}
          {commitErrors[index] && <p className="text-xs text-crit">{commitErrors[index]}</p>}
          {commitResults[index] && (
            <p className="text-xs text-good">
              Mis en scène : <span className="font-mono">{commitResults[index].staged_path}</span>
              <br />
              Torrent : <span className="font-mono">{commitResults[index].torrent_path}</span>
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: PASS.

Puis : `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: aucune erreur.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UploadPrepPanel.tsx frontend/src/components/UploadPrepPanel.test.tsx
git commit -m "AUTOMATION sous-projet 4 (6/6b) : composant UploadPrepPanel"
```

---

### Task 8: Frontend — bouton "Préparer l'upload" sur `GapScanPage`

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Modify: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `UploadPrepPanel` (Task 7).

- [ ] **Step 1: Write the failing test**

Dans `frontend/src/pages/GapScanPage.test.tsx`, ajouter au mock de `"../api/client"` en tete (chercher le `vi.mock("../api/client", ...)`) rien de nouveau n'est requis cote client (le panneau mock ses propres appels), mais ajouter un mock du composant lui-meme pour isoler ce test :

```ts
vi.mock("../components/UploadPrepPanel", () => ({
  default: ({ title, onClose }: { title: string; onClose: () => void }) => (
    <div>
      <p>Panneau upload pour {title}</p>
      <button onClick={onClose}>Fermer le panneau</button>
    </div>
  ),
}));
```

Puis ajouter un test (pres des autres tests de rendu de la table de resultats) :

```tsx
it("affiche un bouton Préparer l'upload sur une ligne avec chemin résolu, ouvre le panneau", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanConfig).mockResolvedValue(CONFIGURED);
  vi.mocked(gapscanStatus).mockResolvedValue(IDLE_STATUS);
  vi.mocked(gapscanResults).mockResolvedValue([{ ...MATRIX_GAP, local_paths: ["/media/matrix.mkv"] }]);

  renderPage();

  const button = await screen.findByRole("button", { name: /Préparer l'upload/i });
  await user.click(button);

  expect(await screen.findByText("Panneau upload pour Matrix")).toBeInTheDocument();
});

it("n'affiche pas de bouton Préparer l'upload si le chemin n'est pas résolu", async () => {
  vi.mocked(gapscanConfig).mockResolvedValue(CONFIGURED);
  vi.mocked(gapscanStatus).mockResolvedValue(IDLE_STATUS);
  vi.mocked(gapscanResults).mockResolvedValue([{ ...MATRIX_GAP, local_paths: [], path_resolved: false }]);

  renderPage();

  await screen.findByText("Matrix (1999)");
  expect(screen.queryByRole("button", { name: /Préparer l'upload/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: FAIL — bouton "Préparer l'upload" introuvable.

- [ ] **Step 3: Write minimal implementation**

Dans `frontend/src/pages/GapScanPage.tsx` :

1. Ajouter l'import (avec les autres imports de composants) :

```tsx
import UploadPrepPanel from "../components/UploadPrepPanel";
```

2. Ajouter un etat, apres les etats existants (pres de `const [error, setError] = useState<string | null>(null);`) :

```tsx
const [activeUpload, setActiveUpload] = useState<{ title: string; localPaths: string[] } | null>(null);
```

3. Dans la derniere colonne de la table (chercher `<td className="px-4 py-2 text-right">`), ajouter le bouton a cote du lien "Générer" existant :

```tsx
<td className="px-4 py-2 text-right">
  <Link to="/" className="text-sm text-accent-ink underline">
    Générer
  </Link>
  {r.path_resolved && r.local_paths.length > 0 && (
    <button
      type="button"
      onClick={() => setActiveUpload({ title: r.title, localPaths: r.local_paths })}
      className="ml-3 text-sm text-accent-ink underline"
    >
      Préparer l'upload
    </button>
  )}
</td>
```

4. Juste avant la fermeture du `<div className="space-y-4">` racine (a la toute fin du JSX, apres le bloc `{results !== null && results.length > 0 && (...)}`), ajouter :

```tsx
{activeUpload && (
  <UploadPrepPanel
    localPaths={activeUpload.localPaths}
    title={activeUpload.title}
    onClose={() => setActiveUpload(null)}
  />
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: PASS.

Puis : `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: aucune erreur.

Puis la suite Vitest complete : `cd frontend && npx vitest run`
Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/GapScanPage.tsx frontend/src/pages/GapScanPage.test.tsx
git commit -m "AUTOMATION sous-projet 4 (6/6c) : bouton Préparer l'upload sur GapScanPage"
```

---

### Task 9: Documentation — marquer le sous-projet 4 comme livré

**Files:**
- Modify: `AUTOMATION.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Mettre a jour `AUTOMATION.md`**

Dans le tableau de decomposition, changer la ligne du sous-projet 4 :

```
| 4 | Orchestration du nommage → mise en scène + `.torrent` (utilise les sous-projets 2 et 3) | **Livré (2026-08-28)**, voir [le plan](docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md) |
```

A la fin de la section "Sous-projet 4" (apres le paragraphe "Pas dans ce sous-projet"), remplacer la ligne `À implémenter.` par (documenter tout ecart reel constate pendant l'implementation, sinon indiquer explicitement qu'il n'y en a pas — ne jamais laisser "À implémenter." si le code est livré) :

```
**Livré (2026-08-28)** — [décrire ici tout écart réel entre cette conception
et l'implémentation finale, constaté pendant l'exécution du plan ; si
aucun écart, écrire "conforme à la conception ci-dessus, aucun écart
notable" comme pour le sous-projet 2].

Voir le plan d'implémentation complet (code exact) :
[docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md](docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md).
```

- [ ] **Step 2: Mettre a jour `CHANGELOG.md`**

Sous `## [Non publié]` -> `### Ajouté`, ajouter une entree (meme style que les 3 precedentes du meme sous-titre) :

```
- **Orchestration nommage → mise en scène + `.torrent`**
  (`nfogen/upload_prep.py`) : à partir de chemins locaux résolus, calcule
  un nom de release par groupe (groupement automatique par tag d'équipe
  détecté — un pack assemblé depuis plusieurs releases devient plusieurs
  uploads distincts), avec un aperçu sans écriture disque avant toute mise
  en scène. Bouton "Préparer l'upload" sur la page GapScan. Quatrième
  brique du pipeline d'automatisation.
```

- [ ] **Step 3: Commit**

```bash
git add AUTOMATION.md CHANGELOG.md
git commit -m "AUTOMATION.md/CHANGELOG.md : marque le sous-projet 4 comme livre"
```

---

## Self-Review (effectue par l'auteur du plan)

- **Couverture du spec** : preview lecture seule -> Task 3 ; commit par groupe -> Task 4 ; indice de titre automatique (`general_title`) -> Task 3 (`hints = [m.get("general_title") ...]`) ; nommage par fichier reutilisant `propose_video_release_name` sans modification -> Task 3 (appel par-fichier explicite) ; groupement par equipe -> Task 2 ; validation reutilisee sans duplication -> Task 3 (`get_validator` + `RenderContext`) ; disposition fichier unique vs dossier -> Task 4 ; API sans nouvel identifiant GapResult -> Task 5 (`local_paths` en entree directe) ; bouton UI par groupe, jamais "tout confirmer" -> Task 7/8. Tout couvert.
- **Placeholders** : aucun "TBD"/"a completer" dans les etapes de code ; Task 9 documente explicitement qu'un ecart reel doit etre transcrit s'il existe (pas laisse en blanc).
- **Coherence des types** : `ProposedFile`/`GroupProposal`/`CommitResult` (Task 2) repris a l'identique dans Task 3/4/5 (memes noms de champs `source_path`/`staged_name`/`release_name`/`files`/`warnings`/`blocked`/`staged_path`/`torrent_path`) et dans les types TS (Task 6, `UploadPrepFile`/`UploadGroupProposal`/`UploadCommitResult`, meme snake_case cote JSON que les dataclasses Python via `asdict`).

---

**Plan complet et sauvegardé dans `docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md`. Deux options d'exécution :**

**1. Subagent-Driven (recommandé habituellement)** — mais **exclu ici** : l'utilisateur a explicitement demandé aucun sous-agent sur ce projet ("franchement, pas de sub agent, aucun agent sur ce projet").

**2. Exécution inline** — via `superpowers:executing-plans`, tâche par tâche dans cette session, avec points de contrôle.

Je pars sur l'exécution inline, cohérent avec la contrainte déjà posée sur ce projet.
