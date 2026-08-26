"""Orchestration GapScan : bibliotheque locale (Sonarr/Radarr) vs catalogue C411.

Ne telecharge, n'heberge et ne distribue aucun contenu : compare des
metadonnees deja en ta possession (ta bibliotheque) a des metadonnees
publiques du tracker (recherche Torznab), pour identifier des candidats a
l'upload. Voir `GAPSCAN.md` pour le contexte complet et les hierarchies de
qualite par defaut (`quality.py`, ajustables).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Optional

from .c411_client import C411Client, C411Error, C411Release
from .quality import ReleaseQuality, build_quality, is_language_gap, is_quality_upgrade
from .radarr_client import RadarrClient, RadarrMovieFile
from .sonarr_client import SonarrClient, SonarrSeasonFile


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
    c411_matches: list[C411Release] = field(default_factory=list)
    has_freeleech_alternative: bool = False
    has_double_upload_window: bool = False
    error: Optional[str] = None  # detail si status == ERROR, sinon None


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _filter_by_year(matches: list[C411Release], year: Optional[int]) -> list[C411Release]:
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


def _classify(local_quality: ReleaseQuality, matches: list[C411Release]) -> GapStatus:
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


def scan_movie(movie: RadarrMovieFile, c411: C411Client) -> GapResult:
    tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
    local_quality = build_quality(
        movie.scene_name or movie.title,
        fallback_resolution=movie.best_resolution,
        fallback_language_names=movie.language_names,
    )
    base = dict(
        media_type="movie", title=movie.title, year=movie.year, season_number=None,
        imdb_id=movie.imdb_id, tmdb_id=tmdb_id, tvdb_id=None, local_quality=local_quality,
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
    except C411Error as exc:
        return GapResult(**base, status=GapStatus.ERROR, error=str(exc))
    return GapResult(
        **base,
        status=_classify(local_quality, matches),
        c411_matches=matches,
        has_freeleech_alternative=any(m.is_freeleech or m.is_half_leech for m in matches),
        has_double_upload_window=any(m.is_double_upload for m in matches),
    )


def scan_series_season(season: SonarrSeasonFile, c411: C411Client) -> GapResult:
    local_quality = build_quality(
        season.scene_name or season.title,
        fallback_resolution=season.best_resolution,
        fallback_language_names=season.language_names,
    )
    base = dict(
        media_type="series", title=season.title, year=season.year,
        season_number=season.season_number, imdb_id=season.imdb_id, tmdb_id=None,
        tvdb_id=season.tvdb_id, local_quality=local_quality,
    )
    try:
        matches = c411.search_tv(imdb_id=season.imdb_id, season=season.season_number)
        if not matches:
            matches = c411.search_tv(query=season.title, season=season.season_number)
    except C411Error as exc:
        return GapResult(**base, status=GapStatus.ERROR, error=str(exc))
    return GapResult(
        **base,
        status=_classify(local_quality, matches),
        c411_matches=matches,
        has_freeleech_alternative=any(m.is_freeleech or m.is_half_leech for m in matches),
        has_double_upload_window=any(m.is_double_upload for m in matches),
    )


def run_gapscan(
    c411: C411Client,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[GapResult]:
    """Lance un scan complet. `radarr`/`sonarr` optionnels (l'un ou l'autre,
    ou les deux). `on_progress(traites, total)`, appele apres chaque item --
    utilise par `gapscan_runner.py` pour exposer une progression via
    `GET /gapscan/status` sans dupliquer cette boucle ailleurs."""
    items: list[tuple[str, object]] = []
    if radarr is not None:
        items.extend(("movie", movie) for movie in radarr.list_movie_files())
    if sonarr is not None:
        items.extend(("series", season) for season in sonarr.list_season_files())

    total = len(items)
    results: list[GapResult] = []
    for index, (kind, item) in enumerate(items, start=1):
        if kind == "movie":
            results.append(scan_movie(item, c411))  # type: ignore[arg-type]
        else:
            results.append(scan_series_season(item, c411))  # type: ignore[arg-type]
        if on_progress is not None:
            on_progress(index, total)
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
