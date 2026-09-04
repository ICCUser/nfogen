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
from typing import Any, Optional

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
class SendResult:
    """Resultat de `send_to_tracker()` : le brouillon cree/mis a jour
    n'entre JAMAIS en file de moderation tout seul (voir AUTOMATION.md,
    sous-projet 5, decision 6) -- c'est a l'utilisateur de le finaliser
    sur le site du tracker. `duplicate_warning` : non None si la
    verification anti-doublon n'a pas pu avoir lieu ou a trouve une
    release existante -- jamais bloquant."""

    draft_id: Any
    draft_url: str
    duplicate_warning: Optional[str] = None


@dataclass
class CommitResult:
    """Resultat de `commit_upload()` : ou le contenu a ete mis en scene
    (fichier unique ou dossier selon la taille du groupe), ou le `.torrent`
    correspondant a ete ecrit, et ou le `.nfo` (un seul, meme pour un pack
    multi-fichiers) a ete ecrit."""

    release_name: str
    staged_path: str
    torrent_path: str
    nfo_path: str


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


def _language_hint_from_audio_tracks(audio_languages: list[str], language_codes: dict[str, str]) -> str:
    """Construit un indice de langue a partir des VRAIES pistes audio du
    fichier (`extract_video_metadata`), jamais du nom de fichier -- comble
    un ecart reel (nom de fichier sans tag de langue, alors que le fichier
    a bien des pistes FR/EN detectees). `language_codes` (voir
    tracker_profile.audio_language_codes) : mapping code/nom MediaInfo ->
    code court reconnu par les alias de langue du profil -- vide si le
    profil n'en declare aucun, jamais de supposition au-dela. Plusieurs
    langues sont combinees avec '+' (ex. 'FR+EN') pour que le profil
    detecte le prefixe MULTI attendu sur les releases multi-langues."""
    codes: list[str] = []
    for lang in audio_languages:
        if not lang:
            continue
        code = language_codes.get(lang.strip().lower())
        if code and code not in codes:
            codes.append(code)
    return "+".join(codes)


def preview_upload(
    local_paths: list[str], profile: str = "c411", title_override: Optional[str] = None
) -> list[GroupProposal]:
    """Sans aucune ecriture disque : extrait les metadonnees (best-effort --
    une extraction illisible devient un avertissement, jamais un
    plantage), groupe par equipe (`group_by_team`), propose un nom de
    pack + un nom par fichier pour chaque groupe, valide via le VRAI
    validateur du profil (`registry.get_validator`) -- recupere
    gratuitement `cross_checks`/`upscale_checks`/`track_language_checks`
    sans dupliquer cette logique ici. `title_override` (AUTOMATION.md,
    sous-projet 5) : remplace le titre deduit du nom de fichier pour TOUS
    les groupes de cet appel (ex. titre officiel du tracker different du
    titre Sonarr/Radarr, "A Guy And A Girl" -> "Un Gars, Une Fille")."""
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

    language_codes = tracker_profile.audio_language_codes(profile)
    hints: list[Optional[str]] = []
    for m in metas:
        title_tag = m.get("general_title") or ""
        audio_hint = _language_hint_from_audio_tracks(m.get("audio_languages") or [], language_codes)
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
            category="video", profile=profile, filenames=group_filenames, title_hints=group_hints,
            title_override=title_override,
        )
        warnings = group_extraction_warnings + list(pack.warnings)

        if pack.name is None:
            proposals.append(GroupProposal(release_name=None, files=[], warnings=warnings, blocked=True))
            continue

        files: list[ProposedFile] = []
        for path, filename, hint in zip(group_paths, group_filenames, group_hints):
            single = propose_release_name(
                category="video", profile=profile, filenames=[filename], title_hints=[hint],
                title_override=title_override,
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
    announce_url = gapscan_config_store.effective_tracker_announce_url(profile)
    if not announce_url:
        raise ValueError(
            f"Adresse d'annonce non configurée pour le profil '{profile}' "
            "(PUT /gapscan/config, champ tracker_announce_url)."
        )

    if len(files) == 1:
        staged_path = str(Path(staging_dir) / files[0].staged_name)
        file_staging.stage_file(files[0].source_path, staged_path)
        raw_text = extract.extract_video_text(Path(staged_path))
    else:
        target_dir = str(Path(staging_dir) / release_name)
        file_staging.stage_files(
            [f.source_path for f in files], target_dir, [f.staged_name for f in files]
        )
        staged_path = target_dir
        # Un seul .nfo pour tout le pack (pas un par episode) : coherent
        # avec un seul release_name / .torrent par groupe (confirme par
        # l'utilisateur, 2026-08-28).
        raw_text = extract.extract_video_dir_text(Path(staged_path))

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

    torrent_path = str(Path(staging_dir) / f"{release_name}.torrent")
    piece_sizes = tracker_profile.torrent_piece_sizes(profile)
    torrent_builder.build_torrent(staged_path, announce_url, torrent_path, piece_sizes)
    return CommitResult(
        release_name=release_name, staged_path=staged_path, torrent_path=torrent_path, nfo_path=nfo_path
    )


def send_to_tracker(
    *,
    release_name: str,
    staged_path: str,
    torrent_path: str,
    nfo_path: str,
    profile: str = "c411",
    media_type: str = "movie",
    radarr_movie_id: Optional[int] = None,
    sonarr_series_id: Optional[int] = None,
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    genre: Optional[str] = None,
    season_number: Optional[int] = None,
    draft_id: Optional[Any] = None,
) -> SendResult:
    """Cree (ou met a jour si `draft_id` deja connu) un BROUILLON C411
    pour un groupe deja confirme par `commit_upload()` -- jamais une
    soumission reelle (voir AUTOMATION.md, sous-projet 5, decision 6).
    Recupere les metadonnees de presentation (synopsis/affiche/genres) A
    LA DEMANDE aupres de Radarr/Sonarr (jamais pendant le scan GapScan),
    rend la description BBCode, calcule categorie/sous-categorie/options
    depuis le release_name deja confirme, verifie les doublons (best
    effort, jamais bloquant), puis appelle l'API."""
    tracker_config = gapscan_config_store.effective_tracker(profile)
    if tracker_config is None:
        raise ValueError(
            f"Clé API du tracker '{profile}' non configurée (PUT /gapscan/config)."
        )
    api_key, base_url = tracker_config

    # Metadonnees de presentation : a la demande, jamais pendant le scan
    # (voir AUTOMATION.md, decision 1).
    overview, poster_url, genres, directors, cast = "", None, [], [], []
    if media_type == "movie" and radarr_movie_id is not None:
        radarr_config = gapscan_config_store.effective_radarr()
        if radarr_config:
            radarr = RadarrClient(*radarr_config)
            try:
                details = radarr.get_movie_details(radarr_movie_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
            finally:
                radarr.close()
    elif media_type == "series" and sonarr_series_id is not None:
        sonarr_config = gapscan_config_store.effective_sonarr()
        if sonarr_config:
            sonarr = SonarrClient(*sonarr_config)
            try:
                details = sonarr.get_series_details(sonarr_series_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
            finally:
                sonarr.close()

    # Infos qualite (source/langue/codec/resolution) : extraites du
    # release_name DEJA CONFIRME via les memes tokens que la validation
    # (sous-projet 4b), pas redemandees au moteur de nommage.
    schema = read_profile(profile)["rules"].get("video", {})
    capture_values = rules_captures(release_name, schema)

    description = render_upload_description(
        profile,
        {
            "title": release_name, "overview": overview, "poster_url": poster_url,
            "genres": genres, "directors": directors, "cast": cast,
            "resolution": capture_values.get("resolution", ""),
            "source": capture_values.get("source", ""),
            "video_codec": capture_values.get("video_codec", ""),
            "audio_languages": [],
        },
    )

    category_id, subcategory_id = c411_upload_options.build_category_ids(profile, media_type, genre)
    if category_id is None or subcategory_id is None:
        raise ValueError(
            f"Catégorie/sous-catégorie non configurées pour le profil '{profile}' "
            f"(rules.json -> tracker.upload.subcategory_id, media_type='{media_type}')."
        )
    options = c411_upload_options.build_options(profile, capture_values, release_name, season_number)

    torrent_bytes = Path(torrent_path).read_bytes()
    nfo_bytes = Path(nfo_path).read_bytes()

    upload_client = C411UploadClient(api_key, base_url=base_url.rstrip("/") + "/api")
    try:
        duplicate_warning = None
        if tmdb_id is not None:
            tmdb_type = "movie" if media_type == "movie" else "tv"
            try:
                releases = upload_client.check_duplicates(tmdb_id, tmdb_type)
                if releases:
                    duplicate_warning = (
                        f"{len(releases)} release(s) déjà approuvée(s) pour cet identifiant TMDB "
                        "sur le tracker — vérifie qu'il ne s'agit pas d'un doublon avant de finaliser."
                    )
            except C411UploadError as exc:
                duplicate_warning = f"Vérification des doublons impossible : {exc}"
        else:
            duplicate_warning = (
                "Vérification des doublons non effectuée : identifiant TMDB inconnu pour ce média."
            )

        tmdb_data = {"id": tmdb_id, "type": "movie" if media_type == "movie" else "tv"} if tmdb_id else None

        if draft_id is not None:
            response = upload_client.update_draft(
                draft_id, torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes, title=release_name,
                description=description, category_id=category_id, subcategory_id=subcategory_id,
                options=options, tmdb_data=tmdb_data,
            )
        else:
            response = upload_client.create_draft(
                torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes, title=release_name,
                description=description, category_id=category_id, subcategory_id=subcategory_id,
                options=options, tmdb_data=tmdb_data,
            )
    finally:
        upload_client.close()

    return SendResult(
        draft_id=response.get("id"), draft_url=response.get("url", ""),
        duplicate_warning=duplicate_warning,
    )
