"""Orchestration GapScan : bibliotheque locale (Sonarr/Radarr) vs catalogue C411.

Ne telecharge, n'heberge et ne distribue aucun contenu : compare des
metadonnees deja en ta possession (ta bibliotheque) a des metadonnees
publiques du tracker (recherche Torznab), pour identifier des candidats a
l'upload. Voir `GAPSCAN.md` pour le contexte complet et les hierarchies de
qualite par defaut (`quality.py`, ajustables).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Iterable, Optional

from . import tracker_profile
from .path_mapping import resolve_and_validate
from .quality import ReleaseQuality, build_quality, is_language_gap, is_quality_upgrade
from .radarr_client import RadarrClient, RadarrMovieFile
from .sonarr_client import SonarrClient, SonarrSeasonFile
from .torznab_client import TorznabClient, TorznabError, TorznabRelease


class GapStatus(str, Enum):
    ABSENT = "absent"              # aucune release C411 trouvee pour ce titre
    QUALITY_GAP = "quality_gap"    # ta version est meilleure que tout ce qui existe sur C411
    LANGUAGE_GAP = "language_gap"  # une version de qualite comparable existe, mais pas ta langue
    COVERED = "covered"            # une release equivalente (qualite + langue) existe deja
    ERROR = "error"                 # C411 injoignable/en erreur pour ce titre (429, 520...) -- pas verifie


@dataclass
class GapResult:
    """Le resultat de la comparaison pour un titre (ou une saison)."""

    media_type: str  # "movie" | "series"
    title: str
    year: Optional[int]
    season_number: Optional[int]
    imdb_id: Optional[str]
    tmdb_id: Optional[str]
    tvdb_id: Optional[int]
    status: GapStatus
    local_quality: ReleaseQuality
    c411_matches: list[TorznabRelease] = field(default_factory=list)
    has_freeleech_alternative: bool = False
    has_double_upload_window: bool = False
    error: Optional[str] = None  # detail si status == ERROR, sinon None
    # Horodatage de la derniere verification REELLE aupres de C411 (`None`
    # pour un resultat persiste avant l'ajout de ce champ) -- repris tel
    # quel (pas rafraichi) quand ce resultat est simplement REPRIS sans
    # reinterroger C411 (mode incremental), pour que `_can_reuse` puisse
    # juger de sa fraicheur reelle. Voir `max_age_seconds`.
    checked_at: Optional[float] = None
    # Chemin(s) local(aux) reels apres resolution du mapping distant/local
    # (voir path_mapping.py) -- vide/False si non resolu (aucun chemin
    # connu, fichier introuvable, ou non lisible). Toujours revalide a
    # chaque scan, meme quand le verdict C411 est repris tel quel en mode
    # incremental (voir scan_movie/scan_series_season).
    local_paths: list[str] = field(default_factory=list)
    path_resolved: bool = False
    path_error: Optional[str] = None


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _filter_by_year(matches: list[TorznabRelease], year: Optional[int]) -> list[TorznabRelease]:
    """Ecarte les matches d'un repli par TITRE dont le millesime explicite
    differe de `year` (ex. plusieurs films distincts partagent le meme
    titre a des annees differentes -- incident reel, "Joker" 2015/2019/
    2024). Une release sans annee detectable dans son titre n'est pas
    ecartee par prudence (ambigu plutot que silencieusement ignore)."""
    if year is None:
        return matches
    kept = []
    for m in matches:
        found = _YEAR_RE.search(m.title)
        if found is None or int(found.group(1)) == year:
            kept.append(m)
    return kept


def _quality_fingerprint(q: ReleaseQuality) -> tuple:
    """Les seuls champs qui affectent une comparaison C411 (`is_quality_upgrade`/
    `is_language_gap`) -- exclut `raw` (le nom de fichier exact peut differer
    cosmetiquement sans rien changer au verdict)."""
    return (q.resolution, q.source, q.codec, tuple(sorted(q.languages)), q.multi, q.pure)


def _can_reuse(
    previous: Optional[GapResult],
    local_quality: ReleaseQuality,
    max_age_seconds: Optional[float] = None,
) -> bool:
    """Mode incremental (voir run_gapscan/gapscan_runner.py) : un resultat
    precedent n'est reutilisable sans reinterroger C411 que s'il etait deja
    COVERED (un gap merite d'etre reverifie, C411 a pu se remplir depuis) ET
    que la qualite locale n'a pas change depuis (sinon la comparaison
    pourrait changer) -- retour utilisateur, 2026-08-26 : "je vais pas tout
    rescanner a chaque fois".

    `max_age_seconds` (optionnel) : au-dela de cet age, meme un COVERED
    inchange est reverifie -- C411 retire et ajoute des releases assez
    souvent (retour utilisateur, 2026-08-27), un COVERED indefiniment
    repris pourrait devenir faux avec le temps. `None` (par defaut) :
    aucune limite d'age. Un resultat sans `checked_at` (persiste avant
    l'ajout de ce champ) est traite comme perime des qu'une limite est
    demandee -- prudence plutot que suppose "toujours frais"."""
    if previous is None or previous.status != GapStatus.COVERED:
        return False
    if _quality_fingerprint(previous.local_quality) != _quality_fingerprint(local_quality):
        return False
    if max_age_seconds is None:
        return True
    if previous.checked_at is None:
        return False
    return (time.time() - previous.checked_at) < max_age_seconds


def _classify(local_quality: ReleaseQuality, matches: list[TorznabRelease]) -> GapStatus:
    if not matches:
        return GapStatus.ABSENT
    # Releases dont la qualite n'est pas strictement depassee par la tienne :
    # seules celles-la peuvent legitimement "couvrir" ta version.
    comparable = [m for m in matches if not is_quality_upgrade(local_quality, m.quality)]
    if not comparable:
        return GapStatus.QUALITY_GAP
    if all(is_language_gap(local_quality, m.quality) for m in comparable):
        return GapStatus.LANGUAGE_GAP
    return GapStatus.COVERED


def genre_of(result: GapResult, profile: str = "c411") -> Optional[str]:
    """'anime'/'documentaire' d'apres la categorie du PREMIER match trouve
    (deja trie par pertinence cote tracker) et les codes de categorie
    Torznab declares par CE profil (rules.json -> tracker.torznab_categories,
    voir tracker_profile.py) ; `None` si ce match est un film/serie
    standard, si le profil n'a rien declare, OU si aucun match n'existe du
    tout -- un titre "absent" n'a par definition aucune categorie, jamais
    classifiable par genre fin (voir GAPSCAN.md, limite assumee)."""
    if not result.c411_matches:
        return None
    category = result.c411_matches[0].category
    categories = tracker_profile.torznab_categories(profile)
    if category in categories.get("anime", []):
        return "anime"
    if category in categories.get("documentaire", []):
        return "documentaire"
    return None


def scan_movie(
    movie: RadarrMovieFile,
    c411: TorznabClient,
    previous: Optional[GapResult] = None,
    max_age_seconds: Optional[float] = None,
    path_mappings: Optional[dict[str, str]] = None,
) -> GapResult:
    tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
    local_quality = build_quality(
        movie.scene_name or movie.title,
        fallback_resolution=movie.best_resolution,
        fallback_language_names=movie.language_names,
    )
    remote_paths = [movie.remote_path] if movie.remote_path else []
    local_paths, path_resolved, path_error = resolve_and_validate(remote_paths, path_mappings or {})
    if _can_reuse(previous, local_quality, max_age_seconds):
        # Le verdict C411 est repris tel quel, mais la validation de
        # chemin doit toujours etre fraiche (AUTOMATION.md, sous-projet 1).
        return replace(
            previous, local_paths=local_paths, path_resolved=path_resolved, path_error=path_error
        )
    base = dict(
        media_type="movie", title=movie.title, year=movie.year, season_number=None,
        imdb_id=movie.imdb_id, tmdb_id=tmdb_id, tvdb_id=None, local_quality=local_quality,
        local_paths=local_paths, path_resolved=path_resolved, path_error=path_error,
    )
    # Une erreur C411 (429, 520, timeout...) sur CE titre ne doit pas
    # empecher de savoir ce qu'on connait deja localement, ni interrompre
    # le reste du scan (voir run_gapscan, qui continue sur les titres
    # suivants) -- incident reel du 2026-08-25.
    try:
        matches = c411.search_movie(imdb_id=movie.imdb_id, tmdb_id=tmdb_id)
        if not matches:
            # Repli par titre : necessaire meme quand un ID externe est
            # connu, pas seulement en son absence -- torznab:attr imdbid/
            # tmdbid ne sont PAS systematiquement presents sur les releases
            # C411 (cf. GAPSCAN.md), une recherche par ID peut donc echouer
            # a tort. Filtre par annee pour ne pas confondre des films
            # homonymes de millesimes differents (incident reel, "Joker").
            matches = _filter_by_year(c411.search_movie(query=movie.title), movie.year)
        if not matches:
            # Repli par titre ALTERNATIF : C411 est un tracker francophone,
            # qui liste souvent un film sous son titre de sortie/diffusion
            # FR, pas l'original (incident reel, "Wild Card" -> "Joker",
            # retour utilisateur 2026-08-27). S'arrete au premier titre
            # alternatif qui trouve quelque chose.
            for alt_title in movie.alternate_titles:
                if alt_title == movie.title:
                    continue
                matches = _filter_by_year(c411.search_movie(query=alt_title), movie.year)
                if matches:
                    break
    except TorznabError as exc:
        return GapResult(**base, status=GapStatus.ERROR, error=str(exc))
    return GapResult(
        **base,
        status=_classify(local_quality, matches),
        c411_matches=matches,
        has_freeleech_alternative=any(m.is_freeleech or m.is_half_leech for m in matches),
        has_double_upload_window=any(m.is_double_upload for m in matches),
        checked_at=time.time(),
    )


def scan_series_season(
    season: SonarrSeasonFile,
    c411: TorznabClient,
    previous: Optional[GapResult] = None,
    max_age_seconds: Optional[float] = None,
    path_mappings: Optional[dict[str, str]] = None,
) -> GapResult:
    local_quality = build_quality(
        season.scene_name or season.title,
        fallback_resolution=season.best_resolution,
        fallback_language_names=season.language_names,
    )
    local_paths, path_resolved, path_error = resolve_and_validate(
        season.remote_paths, path_mappings or {}
    )
    if _can_reuse(previous, local_quality, max_age_seconds):
        return replace(
            previous, local_paths=local_paths, path_resolved=path_resolved, path_error=path_error
        )
    base = dict(
        media_type="series", title=season.title, year=season.year,
        season_number=season.season_number, imdb_id=season.imdb_id, tmdb_id=None,
        tvdb_id=season.tvdb_id, local_quality=local_quality,
        local_paths=local_paths, path_resolved=path_resolved, path_error=path_error,
    )
    try:
        matches = c411.search_tv(imdb_id=season.imdb_id, season=season.season_number)
        if not matches:
            matches = c411.search_tv(query=season.title, season=season.season_number)
        if not matches:
            # Repli par titre alternatif -- meme raison que scan_movie, voir
            # la-bas ("White Collar" -> "FBI, duo tres special").
            for alt_title in season.alternate_titles:
                if alt_title == season.title:
                    continue
                matches = c411.search_tv(query=alt_title, season=season.season_number)
                if matches:
                    break
    except TorznabError as exc:
        return GapResult(**base, status=GapStatus.ERROR, error=str(exc))
    return GapResult(
        **base,
        status=_classify(local_quality, matches),
        c411_matches=matches,
        has_freeleech_alternative=any(m.is_freeleech or m.is_half_leech for m in matches),
        has_double_upload_window=any(m.is_double_upload for m in matches),
        checked_at=time.time(),
    )


def _result_key(r: GapResult) -> tuple:
    """Identifiant stable d'un titre (ou saison) entre deux scans, pour
    retrouver son resultat precedent en mode incremental : prefere les
    identifiants externes (stables meme si le titre change de casse/
    ponctuation), repli sur titre(+annee) sinon."""
    if r.media_type == "movie":
        return ("movie", r.imdb_id or r.tmdb_id or r.title, r.year)
    return ("series", r.tvdb_id or r.imdb_id or r.title, r.season_number)


def run_gapscan(
    c411: TorznabClient,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    previous_results: Optional[list[GapResult]] = None,
    only: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
) -> list[GapResult]:
    """Lance un scan. `radarr`/`sonarr` optionnels (l'un ou l'autre, ou les
    deux). `on_progress(traites, total)`, appele apres chaque item -- utilise
    par `gapscan_runner.py` pour exposer une progression via
    `GET /gapscan/status` sans dupliquer cette boucle ailleurs.

    `previous_results` (mode incremental, optionnel) : resultats du dernier
    scan termine -- un titre deja COVERED et inchange localement est repris
    tel quel sans reinterroger C411 (voir `_can_reuse`), sauf s'il depasse
    `max_age_seconds`. Retour utilisateur, 2026-08-26/27.

    `only` ("movies"/"series"/None) : ne scanne qu'une des deux bibliotheques
    -- pour repartir la charge sur plusieurs sessions (limite C411 confirmee :
    15 requetes/min). Retour utilisateur, 2026-08-27.

    `sonarr_path_mappings`/`radarr_path_mappings` : tables de resolution de
    chemin distant -> local, une par connexion (voir AUTOMATION.md,
    sous-projet 1)."""
    items: list[tuple[str, object]] = []
    if radarr is not None and only != "series":
        items.extend(("movie", movie) for movie in radarr.list_movie_files())
    if sonarr is not None and only != "movies":
        items.extend(("series", season) for season in sonarr.list_season_files())

    previous_by_key: dict[tuple, GapResult] = {}
    if previous_results:
        for r in previous_results:
            previous_by_key[_result_key(r)] = r

    total = len(items)
    results: list[GapResult] = []
    for index, (kind, item) in enumerate(items, start=1):
        if kind == "movie":
            tmdb_id = str(item.tmdb_id) if item.tmdb_id else None  # type: ignore[attr-defined]
            key = ("movie", item.imdb_id or tmdb_id or item.title, item.year)  # type: ignore[attr-defined]
            results.append(
                scan_movie(
                    item, c411, previous=previous_by_key.get(key), max_age_seconds=max_age_seconds,
                    path_mappings=radarr_path_mappings,
                )
            )  # type: ignore[arg-type]
        else:
            key = ("series", item.tvdb_id or item.imdb_id or item.title, item.season_number)  # type: ignore[attr-defined]
            results.append(
                scan_series_season(
                    item, c411, previous=previous_by_key.get(key), max_age_seconds=max_age_seconds,
                    path_mappings=sonarr_path_mappings,
                )
            )  # type: ignore[arg-type]
        if on_progress is not None:
            on_progress(index, total)
    # `only` restreint ce qui est REINTERROGE cette passe, jamais ce qui est
    # CONSERVE du dernier scan -- incident reel signale par l'utilisateur
    # (2026-08-28) : un scan "Films seulement" effacait les series deja
    # scannees precedemment (et vice versa) au lieu de les laisser intactes.
    if only == "movies":
        results.extend(r for r in (previous_results or []) if r.media_type == "series")
    elif only == "series":
        results.extend(r for r in (previous_results or []) if r.media_type == "movie")
    return results


_STATUS_ORDER = {
    GapStatus.ABSENT: 0,
    GapStatus.QUALITY_GAP: 1,
    GapStatus.LANGUAGE_GAP: 2,
    GapStatus.ERROR: 3,  # a verifier manuellement, mais moins actionnable qu'un gap confirme
    GapStatus.COVERED: 4,
}


def sort_by_priority(results: Iterable[GapResult]) -> list[GapResult]:
    """Gaps d'abord (absent > qualite > langue > couvert) ; a egalite de
    statut, priorite a un badge FL/50% deja present sur C411 pour ce titre
    (bon plan de telechargement pendant que tu prepares l'upload)."""
    return sorted(
        results,
        key=lambda r: (_STATUS_ORDER[r.status], not r.has_freeleech_alternative, r.title),
    )
