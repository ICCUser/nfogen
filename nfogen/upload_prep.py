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

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from . import (
    c411_upload_options,
    engine,
    extract,
    file_staging,
    gapscan_config_store,
    gapscan_runner,
    tracker_profile,
    upload_history_store,
)
from .c411_upload_client import C411UploadClient, C411UploadError
from .engine import propose_release_name
from .languages import flagcdn_url, resolve_language
from .models import RenderContext
from .name_proposal import extract_team_tag, propose_season_pack_name, strip_ext
from .profile_store import read_profile
from .qbittorrent_client import QBittorrentClient, QBittorrentError
from .radarr_client import RadarrClient
from .registry import get_validator
from .rules import captures as rules_captures
from .sonarr_client import SonarrClient
from .tmdb_client import TMDBClient, TMDBError
from .upload_description import render_upload_description

# Bannieres de section du template d'upload (assets statiques, voir
# scripts/generate_upload_banners.py + docs/superpowers/specs/
# 2026-09-07-template-charte-tmdb-design.md) -- pas une config
# utilisateur, ce sont des assets nfogen commites dans le repo.
_BANNER_BASE_URL = "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners"
_BANNER_INFORMATIONS = f"{_BANNER_BASE_URL}/informations.webp"
_BANNER_SYNOPSIS = f"{_BANNER_BASE_URL}/synopsis.webp"
_BANNER_DETAILS_TECHNIQUES = f"{_BANNER_BASE_URL}/details-techniques.webp"
_BANNER_TELECHARGEMENT = f"{_BANNER_BASE_URL}/telechargement.webp"

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
class SeasonPackSeasonFiles:
    """Fichiers d'UNE saison du pack -- garde l'association fichier/saison
    explicite (jamais devinee depuis le chemin), voir SeasonPackRequest."""

    season_number: int
    local_paths: list[str]


@dataclass
class SeasonPackRequest:
    """Pack multi-saisons DEJA VALIDE par l'appelant (retour utilisateur,
    2026-09-08 -- voir gapscan_library.detect_season_packs : memes equipe
    garantie, saisons consecutives) -- transmis tel quel par l'API (voir
    api.py)."""

    title: str
    team: str
    is_full_series: bool
    seasons: list[SeasonPackSeasonFiles]  # ordonne par season_number croissant


@dataclass
class SendResult:
    """Resultat de `send_to_tracker()`. Par defaut (`direct=False`), le
    brouillon cree/mis a jour n'entre JAMAIS en file de moderation tout
    seul (voir AUTOMATION.md, sous-projet 5, decision 6) -- c'est a
    l'utilisateur de le finaliser sur le site du tracker ; `draft_id`/
    `draft_url` identifient alors ce brouillon. En mode `direct=True`
    (upload direct, `POST /api/torrents`), ces memes champs identifient
    plutot le torrent uploade, deja parti en moderation. `duplicate_warning` :
    non None si la verification anti-doublon n'a pas pu avoir lieu ou a
    trouve une release existante -- jamais bloquant. `presentation_warning`
    (retour C411, 2026-09-07 -- "tous les elements doivent y figurer...
    c'est obligatoire") : non None si Pays/Createur(s)/Note TMDB/IMDB
    seront absents de la description faute de cle API TMDB configuree --
    jamais bloquant non plus, juste un signal pour ne pas se faire
    rejeter par la moderation comme deja arrive (bit rate manquant).
    `seed_warning` (retour utilisateur, 2026-09-07 -- "le torrent n'est
    jamais envoye a qbit !!!!") : non None si l'ajout automatique a
    qBittorrent (uniquement en mode `direct=True` -- un brouillon reste
    prive, jamais mis en seed automatiquement) n'a pas pu avoir lieu
    (qBittorrent non configure, ou echec de connexion/ajout) -- jamais
    bloquant, l'upload C411 a deja reussi a ce stade."""

    draft_id: Any
    draft_url: str
    duplicate_warning: Optional[str] = None
    presentation_warning: Optional[str] = None
    seed_warning: Optional[str] = None


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


def _known_local_paths() -> set[str]:
    """Union des `local_paths` des derniers resultats de scan connus
    (`gapscan_runner.results()`) -- l'UNIQUE source dont
    `gapscan_library.list_library()` tire les `local_paths` exposes au
    frontend (`GET /gapscan/library`) : un `source_path` absent de cet
    ensemble n'a jamais ete legitimement communique par nfogen lui-meme
    (voir audit securite 2026-09-09 -- sans ce controle, un appelant
    authentifie pouvait forger n'importe quel `source_path` pour faire
    lire/copier un fichier arbitraire du serveur)."""
    known: set[str] = set()
    for result in gapscan_runner.results():
        known.update(result.local_paths)
    return known


def _validate_known_source_paths(paths: list[str]) -> None:
    """Leve ValueError si un des `paths` n'a jamais figure dans un scan
    GapScan connu (voir `_known_local_paths`)."""
    unknown = sorted({p for p in paths if p not in _known_local_paths()})
    if unknown:
        raise ValueError(
            "Chemin(s) source non reconnu(s) (jamais retourné par un scan de la "
            f"Bibliothèque) : {', '.join(unknown)}"
        )


def _path_within(path: str, root: str) -> bool:
    """Vrai si `path`, une fois resolu, reste sous `root` (resolu aussi).
    `Path.resolve()` neutralise a la fois les composants '..' ET le cas
    ou `path` est absolu -- `Path(root) / path` ignorerait sinon
    silencieusement `root` quand `path` est deja absolu (comportement de
    l'operateur `/` de pathlib, voir audit securite 2026-09-09)."""
    try:
        resolved = Path(path).resolve()
        resolved_root = Path(root).resolve()
    except OSError:
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


def validate_staged_path(path: str) -> None:
    """Leve ValueError si `path` ne reste pas sous le dossier de mise en
    scene configure -- protege `send_to_tracker()`/`verify-integrity`
    contre un `staged_path` arbitraire fourni par le client (voir audit
    securite 2026-09-09). Les valeurs LEGITIMES de `staged_path` sont
    TOUJOURS produites par `commit_upload()` sous ce meme dossier."""
    staging_dir = gapscan_config_store.effective_staging_dir()
    if not staging_dir or not _path_within(path, staging_dir):
        raise ValueError(f"Chemin hors du dossier de mise en scène : {path}")


def _preview_season_pack(season_pack: SeasonPackRequest, profile: str) -> GroupProposal:
    """Un pack multi-saisons DEJA VALIDE (voir SeasonPackRequest) donne
    TOUJOURS un seul GroupProposal -- jamais de group_by_team() ici (les
    fichiers de plusieurs saisons portent des tokens SxxExx differents,
    group_by_team n'a pas de sens pour ce cas). Le premier fichier de la
    premiere saison sert de representant pour extraire langue/resolution/
    codec/source (memes alias que la proposition standard, voir
    propose_season_pack_name)."""
    _validate_known_source_paths(
        [source_path for season in season_pack.seasons for source_path in season.local_paths]
    )

    warnings: list[str] = []
    files: list[ProposedFile] = []
    representative_filename: Optional[str] = None
    for season in season_pack.seasons:
        for source_path in season.local_paths:
            filename = Path(source_path).name
            if representative_filename is None:
                representative_filename = filename
            try:
                extract.extract_video_metadata(Path(source_path))
            except Exception:
                warnings.append(_extraction_warning(filename))
            files.append(
                ProposedFile(source_path=source_path, staged_name=f"S{season.season_number:02d}/{filename}")
            )

    if not files or representative_filename is None:
        return GroupProposal(
            release_name=None, files=[], warnings=["Aucun fichier fourni pour ce pack."], blocked=True
        )

    config = read_profile(profile)["rules"].get("video", {}).get("name_proposal", {})
    season_numbers = [s.season_number for s in season_pack.seasons]
    proposal = propose_season_pack_name(
        title=season_pack.title, season_numbers=season_numbers, is_full_series=season_pack.is_full_series,
        team=season_pack.team, representative_filename=representative_filename, config=config,
    )
    warnings = warnings + list(proposal.warnings)

    if proposal.name is None:
        return GroupProposal(release_name=None, files=[], warnings=warnings, blocked=True)

    return GroupProposal(release_name=proposal.name, files=files, warnings=warnings, blocked=False)


def preview_upload(
    local_paths: list[str], profile: str = "c411", title_override: Optional[str] = None,
    season_pack: Optional[SeasonPackRequest] = None,
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
    titre Sonarr/Radarr, "A Guy And A Girl" -> "Un Gars, Une Fille").
    `season_pack` (AUTOMATION.md, retour utilisateur 2026-09-08) :
    court-circuite tout ce qui precede -- `local_paths` est alors ignore,
    voir `_preview_season_pack`."""
    if season_pack is not None:
        return [_preview_season_pack(season_pack, profile)]

    if not local_paths:
        return []

    _validate_known_source_paths(local_paths)

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
    media_type: str = "movie",
    radarr_movie_id: Optional[int] = None,
    sonarr_series_id: Optional[int] = None,
    season_number: Optional[int] = None,
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
    inchange (aucun test existant ne casse).

    `media_type`/`radarr_movie_id`/`sonarr_series_id`/`season_number`
    (AUTOMATION.md, sous-projet 8, tous optionnels) : decident si un
    fichier deja present dans le dossier de mise en scene peut etre
    regenere sans risque -- incident reel, 2026-09-06 ("[Errno 17] File
    exists" sur un dechet d'un essai precedent). Un titre JAMAIS enregistre
    comme confirme/envoye (voir upload_history_store.py) est considere
    comme un dechet sur a regenerer (toujours depuis la source locale,
    jamais un nouveau telechargement). Un titre DEJA confirme/envoye
    -- potentiellement en cours de seed -- fait lever une erreur claire
    plutot que d'ecraser silencieusement (l'integration qBittorrent/
    Transmission, sous-projet 6, n'existe pas encore pour verifier
    reellement l'etat de seed)."""
    staging_dir, announce_url = resolve_staging_config(profile)
    _validate_known_source_paths([f.source_path for f in files])

    history_key = upload_history_store.processed_key(
        media_type, radarr_movie_id, sonarr_series_id, season_number
    )
    already_processed = history_key is not None and upload_history_store.is_processed(history_key)
    overwrite = not already_processed

    def _staging_progress(done: int, total: int) -> None:
        if on_progress:
            pct = (done / total * 100) if total else 100.0
            on_progress("staging", pct)

    try:
        if len(files) == 1:
            staged_path = str(Path(staging_dir) / files[0].staged_name)
            validate_staged_path(staged_path)
            file_staging.stage_file(
                files[0].source_path, staged_path,
                on_progress=_staging_progress if on_progress else None, cancel_event=cancel_event,
                overwrite=overwrite,
            )
            raw_text = extract.extract_video_text(Path(staged_path))
        else:
            target_dir = str(Path(staging_dir) / release_name)
            validate_staged_path(target_dir)
            for f in files:
                validate_staged_path(str(Path(target_dir) / f.staged_name))
            file_staging.stage_files(
                [f.source_path for f in files], target_dir, [f.staged_name for f in files],
                on_progress=_staging_progress if on_progress else None, cancel_event=cancel_event,
                overwrite=overwrite,
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
        validate_staged_path(nfo_path)
        # Un titre DEJA traite dont le .nfo existe encore n'est jamais
        # retouche (meme prudence que le fichier mis en scene/le .torrent) --
        # un titre pas encore traite (ou sans .nfo existant) est toujours
        # (re)ecrit normalement.
        if overwrite or not Path(nfo_path).exists():
            Path(nfo_path).write_text(nfo, encoding="utf-8")
        if on_progress:
            on_progress("generating_nfo", 100.0)

        torrent_path = str(Path(staging_dir) / f"{release_name}.torrent")
        validate_staged_path(torrent_path)
        piece_sizes = tracker_profile.torrent_piece_sizes(profile)

        def _torrent_progress(pieces_done: int, pieces_total: int) -> None:
            if on_progress:
                pct = (pieces_done / pieces_total * 100) if pieces_total else 100.0
                on_progress("building_torrent", pct)

        torrent_builder.build_torrent(
            staged_path, announce_url, torrent_path, piece_sizes,
            on_progress=_torrent_progress if on_progress else None, cancel_event=cancel_event,
            overwrite=overwrite, source=tracker_profile.torrent_source(profile),
        )
    except FileExistsError as exc:
        when = ""
        last_at = upload_history_store.last_processed_at(history_key) if history_key else None
        if last_at is not None:
            when = f" le {datetime.fromtimestamp(last_at).strftime('%Y-%m-%d %H:%M')}"
        raise FileExistsError(
            f"Un fichier de mise en scène (média, .torrent ou .nfo) existe déjà pour « {release_name} » "
            f"et ce titre a déjà été confirmé/envoyé{when} — vérifie qu'il n'est pas en cours de seed "
            "avant de le supprimer manuellement, puis relance Confirmer."
        ) from exc

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
    direct: bool = False,
) -> SendResult:
    """Cree (ou met a jour si `draft_id` deja connu) un BROUILLON C411 par
    defaut -- jamais une soumission reelle (voir AUTOMATION.md, sous-projet
    5, decision 6). `direct=True` (retour d'un membre de l'equipe C411,
    2026-09-07 : un vrai endpoint d'upload direct existe, decouvert apres
    coup -- voir `C411UploadClient.upload_torrent`) : part reellement en
    moderation (`POST /api/torrents`), jamais de notion de mise a jour
    (`draft_id` ignore dans ce mode -- un upload direct est un one-shot).
    Recupere les metadonnees de presentation (synopsis/affiche/genres) A
    LA DEMANDE aupres de Radarr/Sonarr (jamais pendant le scan GapScan),
    rend la description BBCode, calcule categorie/sous-categorie/options
    depuis le release_name deja confirme, verifie les doublons (best
    effort, jamais bloquant), puis appelle l'API."""
    for path in (staged_path, torrent_path, nfo_path):
        validate_staged_path(path)
    tracker_config = gapscan_config_store.effective_tracker(profile)
    if tracker_config is None:
        raise ValueError(
            f"Clé API du tracker '{profile}' non configurée (PUT /gapscan/config)."
        )
    api_key, base_url = tracker_config

    # Metadonnees de presentation : a la demande, jamais pendant le scan
    # (voir AUTOMATION.md, decision 1). `release_date`/`runtime_minutes`/
    # `distributor`/`certification` confirmes disponibles en conditions
    # reelles le 2026-09-06 (retour utilisateur) -- pas de "pays de
    # production", absent des deux API, jamais devine.
    overview, poster_url, genres, directors, cast = "", None, [], [], []
    release_date, runtime_minutes, distributor, certification = None, None, None, None
    imdb_id: Optional[str] = None
    if media_type == "movie" and radarr_movie_id is not None:
        radarr_config = gapscan_config_store.effective_radarr()
        if radarr_config:
            radarr = RadarrClient(*radarr_config)
            try:
                details = radarr.get_movie_details(radarr_movie_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
                release_date, runtime_minutes = details.release_date, details.runtime_minutes
                distributor, certification = details.studio, details.certification
                imdb_id = details.imdb_id
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
                release_date, runtime_minutes = details.release_date, details.runtime_minutes
                distributor, certification = details.network, details.certification
                imdb_id = details.imdb_id
            finally:
                sonarr.close()

    # Enrichissement TMDB best-effort (Pays/Createur(s)/Note) -- absent des
    # deux API Radarr/Sonarr, confirme par des dumps reels (voir
    # docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md).
    # Silencieux sur toute erreur : ne bloque jamais l'envoi (decision
    # utilisateur, 2026-09-07).
    country, tmdb_rating, creators = None, None, []
    tmdb_api_key = gapscan_config_store.effective_tmdb_api_key()
    # Retour C411, 2026-09-07 : tous les elements de la presentation
    # doivent y figurer ("c'est obligatoire") -- sans cle TMDB, Pays/
    # Createur(s)/Note/IMDB seront absents de la description generee.
    presentation_warning = (
        "Description incomplète : clé API TMDB non configurée — Pays, "
        "créateur(s), note TMDB et lien IMDB seront absents (voir Réglages)."
        if not tmdb_api_key else None
    )
    if tmdb_api_key and tmdb_id:
        try:
            tmdb_client = TMDBClient(tmdb_api_key)
            try:
                extra = (
                    tmdb_client.get_movie_extra(int(tmdb_id)) if media_type == "movie"
                    else tmdb_client.get_series_extra(int(tmdb_id))
                )
            finally:
                tmdb_client.close()
            country, tmdb_rating, creators = extra.country, extra.vote_average, extra.creators
        except TMDBError:
            pass

    imdb_url = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else None

    # Infos qualite (source/langue/codec/resolution) : extraites du
    # release_name DEJA CONFIRME via les memes tokens que la validation
    # (sous-projet 4b), pas redemandees au moteur de nommage. `team` :
    # meme extraction que `name_proposal.py` (evite de dupliquer une
    # regex, voir extract_team_tag).
    schema = read_profile(profile)["rules"].get("video", {})
    capture_values = rules_captures(release_name, schema)
    team = extract_team_tag(release_name)

    # Langues audio/sous-titres + debit video : extraits du VRAI fichier
    # mis en scene (MediaInfo), jamais devines -- `audio_languages`
    # restait cable en dur a [] jusqu'ici (retour utilisateur, 2026-09-06).
    # Pour un pack (dossier), le premier episode reste representatif
    # (codec/langues identiques d'un episode a l'autre dans l'ecrasante
    # majorite des cas).
    staged = Path(staged_path)
    if staged.is_dir():
        per_file_metadata = extract.extract_video_dir_metadata(staged)
        first_metadata = per_file_metadata[0] if per_file_metadata else {}
        file_count = len(per_file_metadata)
        total_size_bytes = sum(f.stat().st_size for f in staged.rglob("*") if f.is_file())
    else:
        first_metadata = extract.extract_video_metadata(staged)
        file_count = 1
        total_size_bytes = staged.stat().st_size
    audio_languages = [lang for lang in first_metadata.get("audio_languages", []) if lang]
    subtitle_languages = [lang for lang in first_metadata.get("subtitle_languages", []) if lang]
    video_bit_rate = first_metadata.get("video_bit_rate")
    container = first_metadata.get("container")
    hdr_format = first_metadata.get("hdr_format")
    # Formatage fait ici (pas en Jinja) : plus simple a tester, evite
    # l'arithmetique fragile dans le gabarit.
    runtime_display = (
        f"{runtime_minutes // 60}h{runtime_minutes % 60:02d}min" if runtime_minutes else None
    )
    video_bit_rate_kbps = round(video_bit_rate / 1000) if video_bit_rate else None

    # Tableau BBCode par piste (retour utilisateur, 2026-09-07 : drapeaux +
    # canaux/codec/debit/sample rate, inspire de la description
    # auto-generee de C411 elle-meme) -- construit ici (noms affiches +
    # drapeaux deja resolus), le template reste simple.
    audio_rows = []
    for t in first_metadata.get("audio_tracks", []):
        name, flag_code = resolve_language(t.get("language"))
        audio_rows.append({
            "flag": flagcdn_url(flag_code) if flag_code else None,
            "language": name, "channels": t.get("channels"),
            "codec": t.get("codec"), "bit_rate_kbps": t.get("bit_rate_kbps"),
            "sampling_khz": t.get("sampling_khz"),
        })
    subtitle_rows = []
    for t in first_metadata.get("subtitle_tracks", []):
        name, flag_code = resolve_language(t.get("language"))
        subtitle_rows.append({
            "flag": flagcdn_url(flag_code) if flag_code else None,
            "language": name, "forced": t.get("forced", False),
        })

    description = render_upload_description(
        profile,
        {
            "title": release_name, "overview": overview, "poster_url": poster_url,
            "genres": genres, "directors": directors, "cast": cast,
            "country": country, "creators": creators, "tmdb_rating": tmdb_rating,
            "imdb_url": imdb_url,
            "resolution": capture_values.get("resolution", ""),
            "source": capture_values.get("source", ""),
            "video_codec": capture_values.get("video_codec", ""),
            "audio_languages": audio_languages,
            "subtitle_languages": subtitle_languages,
            "audio_rows": audio_rows, "subtitle_rows": subtitle_rows,
            "video_bit_rate_kbps": video_bit_rate_kbps,
            "container": container, "hdr_format": hdr_format,
            "release_date": release_date, "runtime_display": runtime_display,
            "distributor": distributor, "certification": certification,
            "release_name": release_name, "team": team,
            "file_count": file_count, "total_size_bytes": total_size_bytes,
            "banner_informations": _BANNER_INFORMATIONS,
            "banner_synopsis": _BANNER_SYNOPSIS,
            "banner_details_techniques": _BANNER_DETAILS_TECHNIQUES,
            "banner_telechargement": _BANNER_TELECHARGEMENT,
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
            # tmdb_id manquant reste anormal pour un FILM (Radarr est
            # TMDB-natif) comme pour une SERIE (Sonarr expose bien un
            # tmdbId, confirme en conditions reelles le 2026-09-06 --
            # gapscan.py le recupere desormais, voir scan_series_season) :
            # signale dans les deux cas.
            duplicate_warning = (
                "Vérification des doublons non effectuée : identifiant TMDB inconnu pour ce média."
            )

        tmdb_data = {"id": tmdb_id, "type": "movie" if media_type == "movie" else "tv"} if tmdb_id else None

        if direct:
            # Upload direct : jamais de notion de mise a jour (draft_id
            # ignore), un seul appel, part reellement en moderation.
            response = upload_client.upload_torrent(
                torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes,
                torrent_filename=f"{release_name}.torrent", nfo_filename=f"{release_name}.nfo",
                title=release_name, description=description, category_id=category_id,
                subcategory_id=subcategory_id, options=options, tmdb_data=tmdb_data,
            )
        elif draft_id is not None:
            response = upload_client.update_draft(
                draft_id, torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes,
                torrent_filename=f"{release_name}.torrent", nfo_filename=f"{release_name}.nfo",
                title=release_name, description=description, category_id=category_id,
                subcategory_id=subcategory_id, options=options, tmdb_data=tmdb_data,
            )
        else:
            response = upload_client.create_draft(
                torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes,
                torrent_filename=f"{release_name}.torrent", nfo_filename=f"{release_name}.nfo",
                title=release_name, description=description, category_id=category_id,
                subcategory_id=subcategory_id, options=options, tmdb_data=tmdb_data,
            )
    finally:
        upload_client.close()

    # `POST /api/torrents` peut renvoyer une URL relative (voir l'exemple
    # `by-tmdb` de la doc C411, "url": "/torrents/{infoHash}") -- jamais
    # confirme en conditions reelles pour CET endpoint precis (contrairement
    # au format des brouillons, deja verifie), donc reste defensif : prefixe
    # avec le domaine du tracker si l'URL renvoyee n'en a pas deja un.
    draft_url = response.get("url", "")
    if direct and draft_url and not draft_url.startswith("http"):
        draft_url = base_url.rstrip("/") + draft_url

    # Ajout automatique a qBittorrent -- UNIQUEMENT pour l'upload direct
    # (retour utilisateur, 2026-09-07 : "le torrent n'est jamais envoye a
    # qbit" -- le .torrent local porte deja source=C411, voir
    # torrent_builder.py, donc plus besoin du depot manuel une fois
    # reellement parti en moderation). Un brouillon reste prive tant que
    # l'utilisateur ne le finalise pas lui-meme : jamais mis en seed ici.
    # Best-effort, jamais bloquant -- l'upload C411 a deja reussi.
    seed_warning = None
    if direct:
        qbittorrent_config = gapscan_config_store.effective_qbittorrent()
        if qbittorrent_config is None:
            seed_warning = (
                "Torrent envoyé à C411, mais pas ajouté à qBittorrent : non configuré (voir Réglages)."
            )
        else:
            qb = QBittorrentClient(*qbittorrent_config)
            try:
                qb.add_torrent(
                    torrent_bytes, str(Path(staged_path).parent), filename=f"{release_name}.torrent",
                    tags="NFOGEN",
                )
            except QBittorrentError as exc:
                seed_warning = f"Torrent envoyé à C411, mais échec de l'ajout à qBittorrent : {exc}"
            finally:
                qb.close()

    result = SendResult(
        draft_id=response.get("id"), draft_url=draft_url,
        duplicate_warning=duplicate_warning, presentation_warning=presentation_warning,
        seed_warning=seed_warning,
    )
    key = upload_history_store.processed_key(media_type, radarr_movie_id, sonarr_series_id, season_number)
    if key is not None:
        upload_history_store.record(key, kind="sent", release_name=release_name)
    return result
