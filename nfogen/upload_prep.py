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

from . import extract, file_staging, gapscan_config_store
from .engine import propose_release_name
from .models import RenderContext
from .name_proposal import extract_team_tag, strip_ext
from .registry import get_validator

try:
    from . import torrent_builder

    _TORRENT_BUILDER_AVAILABLE = True
except ImportError:
    _TORRENT_BUILDER_AVAILABLE = False


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


# Codes de langue MediaInfo (piste audio reelle du fichier) -> code court
# reconnu par les alias de langue du profil (rules.json -> language_aliases).
# Volontairement limite aux langues deja couvertes par les combinaisons
# existantes de la config C411 (FR+EN/EN+FR/FR+JA/JA+FR) -- jamais invente
# au-dela, meme philosophie "ne jamais deviner" que le reste du projet.
_AUDIO_LANGUAGE_CODE: dict[str, str] = {
    "fr": "FR", "fre": "FR", "fra": "FR", "french": "FR",
    "en": "EN", "eng": "EN", "english": "EN",
    "ja": "JA", "jpn": "JA", "japanese": "JA",
}


def _language_hint_from_audio_tracks(audio_languages: list[str]) -> str:
    """Construit un indice de langue a partir des VRAIES pistes audio du
    fichier (`extract_video_metadata`), jamais du nom de fichier -- comble
    un ecart reel (nom de fichier sans tag de langue, alors que le fichier a
    bien des pistes FR/EN detectees). Plusieurs langues sont combinees avec
    '+' (ex. 'FR+EN') pour que le profil detecte le prefixe MULTI attendu
    par C411 sur les releases multi-langues (retour utilisateur explicite,
    2026-08-28 : sans ca, deux pistes ne signaleraient jamais MULTI).
    Chaine vide si rien de reconnu -- jamais de supposition au-dela des
    combinaisons que le profil sait deja gerer."""
    codes: list[str] = []
    for lang in audio_languages:
        if not lang:
            continue
        code = _AUDIO_LANGUAGE_CODE.get(lang.strip().lower())
        if code and code not in codes:
            codes.append(code)
    return "+".join(codes)


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

    hints: list[Optional[str]] = []
    for m in metas:
        title_tag = m.get("general_title") or ""
        audio_hint = _language_hint_from_audio_tracks(m.get("audio_languages") or [])
        combined = " ".join(part for part in (title_tag, audio_hint) if part)
        hints.append(combined or None)
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
