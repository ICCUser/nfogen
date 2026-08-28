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

from . import extract
from .engine import propose_release_name
from .models import RenderContext
from .name_proposal import extract_team_tag, strip_ext
from .registry import get_validator


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
