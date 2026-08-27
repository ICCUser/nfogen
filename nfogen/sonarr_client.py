"""Client pour l'API REST de Sonarr (v3), lecture seule.

Ne recupere que ce qu'il faut pour GapScan : la bibliotheque locale,
agregee par saison (les releases C411 sont le plus souvent packagees par
saison, cf. `GAPSCAN.md`). Aucune ecriture, aucune modification de la
bibliotheque Sonarr.
"""
from __future__ import annotations

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
    best_resolution: Optional[int] = None
    quality_name: Optional[str] = None
    scene_name: Optional[str] = None
    language_names: list[str] = field(default_factory=list)


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
                seasons.append(
                    SonarrSeasonFile(
                        series_id=series["id"],
                        title=series.get("title", ""),
                        year=series.get("year"),
                        tvdb_id=series.get("tvdbId"),
                        imdb_id=series.get("imdbId"),
                        season_number=season_number,
                        episode_file_count=len(season_files),
                        best_resolution=quality.get("resolution"),
                        quality_name=quality.get("name"),
                        scene_name=best.get("sceneName"),
                        language_names=[lang.get("name", "") for lang in best.get("languages", [])],
                    )
                )
        return seasons
