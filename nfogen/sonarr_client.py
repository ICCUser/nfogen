"""Client pour l'API REST de Sonarr (v3), lecture seule.

Ne recupere que ce qu'il faut pour GapScan : la bibliotheque locale,
agregee par saison (les releases C411 sont le plus souvent packagees par
saison, cf. `GAPSCAN.md`). Aucune ecriture, aucune modification de la
bibliotheque Sonarr.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


class SonarrError(RuntimeError):
    """Erreur reseau ou reponse inattendue de l'API Sonarr."""


@dataclass
class SonarrSeasonFile:
    """Une saison possedee localement, agregee depuis ses fichiers d'episodes.

    `best_resolution`/`quality_name` viennent du meilleur fichier de la
    saison (le plus haute resolution). `scene_name` (nom de release
    d'origine, si Sonarr l'a conserve) est prefere a `title` pour extraire
    la qualite/langue fine -- voir `quality.build_quality`.
    """

    series_id: int
    title: str
    year: Optional[int]
    tvdb_id: Optional[int]
    imdb_id: Optional[str]
    season_number: int
    episode_file_count: int
    # Sonarr identifie une serie par TVDB (voir `tvdb_id`), mais expose
    # AUSSI un `tmdbId` (cross-reference qu'il maintient lui-meme) --
    # confirme en conditions reelles le 2026-09-06 (retour utilisateur :
    # "tmdb possede bien quelque chose... meme dans sonarr le lien est
    # https://www.themoviedb.org/tv/63174"), jamais lu jusqu'ici. Permet
    # la meme verification anti-doublon C411 (TMDB-only) que pour un film.
    tmdb_id: Optional[int] = None
    best_resolution: Optional[int] = None
    quality_name: Optional[str] = None
    scene_name: Optional[str] = None
    language_names: list[str] = field(default_factory=list)
    # Titres alternatifs connus de Sonarr (ex. titre de diffusion FR
    # different de l'original, "White Collar" -> "FBI, duo tres special")
    # -- meme raison que RadarrMovieFile.alternate_titles, voir la-bas.
    alternate_titles: list[str] = field(default_factory=list)
    # Chemins absolus de CHAQUE fichier episode de la saison (une saison
    # est intrinsequement multi-fichiers, contrairement a un film) -- voir
    # AUTOMATION.md, sous-projet 1.
    remote_paths: list[str] = field(default_factory=list)
    # Genres Sonarr (au niveau serie -- Sonarr n'a pas de genre par saison)
    # -- meme role que RadarrMovieFile.genres, voir la-bas.
    genres: list[str] = field(default_factory=list)
    # Horodatage (epoch secondes) le PLUS RECENT parmi les fichiers episode
    # de CETTE saison -- pas la date d'ajout de la serie entiere, qui ne
    # distinguerait pas les saisons (voir _parse_sonarr_date).
    added_at: Optional[float] = None


@dataclass
class SonarrSeriesDetails:
    """Meme role que RadarrMovieDetails, cote series -- voir la-bas. Sonarr
    n'expose pas de credits structures (realisateur/casting) comme Radarr :
    `directors`/`cast` restent toujours vides pour une serie."""

    overview: str = ""
    poster_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)


def _parse_sonarr_date(value: Optional[str]) -> Optional[float]:
    """Meme role que radarr_client._parse_radarr_date, duplique ici plutot
    que partage -- radarr_client.py et sonarr_client.py restent
    volontairement independants (voir leurs docstrings de module)."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class SonarrClient:
    """Client HTTP pour l'API v3 de Sonarr."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not api_key:
            raise SonarrError("URL ou cle API Sonarr manquante.")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SonarrClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        try:
            response = self._client.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"X-Api-Key": self._api_key},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SonarrError(f"Appel Sonarr echoue ({path}) : {exc}") from exc
        return response.json()

    def list_series(self) -> list[dict[str, Any]]:
        """`GET /api/v3/series` brut."""
        return self._get("/api/v3/series")

    def list_episode_files(self, series_id: int) -> list[dict[str, Any]]:
        """`GET /api/v3/episodefile?seriesId=...` brut."""
        return self._get("/api/v3/episodefile", params={"seriesId": series_id})

    def list_season_files(self) -> list[SonarrSeasonFile]:
        """Bibliotheque locale agregee par saison.

        Une saison sans aucun fichier telecharge n'apparait pas : rien a
        comparer a C411 pour elle. La saison 0 (convention Sonarr pour les
        "Specials" -- extras/bonus/hors-serie) est exclue : ce n'est pas
        une vraie saison diffusee, elle ne correspond a aucune convention
        de pack C411 standard (incident reel corrige le 2026-08-26,
        "Misfits S00" remontait a tort dans les resultats).
        """
        seasons: list[SonarrSeasonFile] = []
        for series in self.list_series():
            files = self.list_episode_files(series["id"])
            by_season: dict[int, list[dict[str, Any]]] = {}
            for episode_file in files:
                season_number = episode_file["seasonNumber"]
                if season_number == 0:
                    continue
                by_season.setdefault(season_number, []).append(episode_file)
            for season_number, season_files in by_season.items():
                best = max(
                    season_files,
                    key=lambda f: (f.get("quality", {}).get("quality", {}).get("resolution") or 0),
                )
                quality = best.get("quality", {}).get("quality", {}) or {}
                added_dates = [
                    d for d in (_parse_sonarr_date(f.get("dateAdded")) for f in season_files) if d is not None
                ]
                seasons.append(
                    SonarrSeasonFile(
                        series_id=series["id"],
                        title=series.get("title", ""),
                        year=series.get("year"),
                        tvdb_id=series.get("tvdbId"),
                        tmdb_id=series.get("tmdbId"),
                        imdb_id=series.get("imdbId"),
                        season_number=season_number,
                        episode_file_count=len(season_files),
                        best_resolution=quality.get("resolution"),
                        quality_name=quality.get("name"),
                        scene_name=best.get("sceneName"),
                        language_names=[lang.get("name", "") for lang in best.get("languages", [])],
                        alternate_titles=[
                            t.get("title", "")
                            for t in series.get("alternateTitles", [])
                            if t.get("title")
                        ],
                        remote_paths=[f.get("path") for f in season_files if f.get("path")],
                        genres=series.get("genres") or [],
                        added_at=max(added_dates) if added_dates else None,
                    )
                )
        return seasons

    def get_series_details(self, series_id: int) -> SonarrSeriesDetails:
        """`GET /api/v3/series/{id}` : metadonnees de presentation d'UNE
        serie -- jamais appele en boucle pendant un scan, uniquement au
        moment de preparer un envoi vers un tracker (voir upload_prep.py)."""
        series = self._get(f"/api/v3/series/{series_id}")
        poster_url = next(
            (img.get("remoteUrl") for img in series.get("images", []) if img.get("coverType") == "poster"),
            None,
        )
        return SonarrSeriesDetails(
            overview=series.get("overview") or "",
            poster_url=poster_url,
            genres=series.get("genres") or [],
        )
