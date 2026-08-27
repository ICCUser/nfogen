"""Client pour l'API REST de Radarr (v3), lecture seule.

Symetrique de `sonarr_client.py` pour les films : ne recupere que ce qu'il
faut pour GapScan. Aucune ecriture, aucune modification de la bibliotheque
Radarr.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


class RadarrError(RuntimeError):
    """Erreur reseau ou reponse inattendue de l'API Radarr."""


@dataclass
class RadarrMovieFile:
    """Un film possede localement (ignore si pas encore telecharge).

    `scene_name` (nom de release d'origine, si Radarr l'a conserve) est
    prefere a `title` pour extraire la qualite/langue fine -- voir
    `quality.build_quality`.
    """

    movie_id: int
    title: str
    year: Optional[int]
    imdb_id: Optional[str]
    tmdb_id: Optional[int]
    best_resolution: Optional[int] = None
    quality_name: Optional[str] = None
    scene_name: Optional[str] = None
    language_names: list[str] = field(default_factory=list)


class RadarrClient:
    """Client HTTP pour l'API v3 de Radarr."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not api_key:
            raise RadarrError("URL ou cle API Radarr manquante.")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RadarrClient":
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
            raise RadarrError(f"Appel Radarr echoue ({path}) : {exc}") from exc
        return response.json()

    def list_movies(self) -> list[dict[str, Any]]:
        """`GET /api/v3/movie` brut."""
        return self._get("/api/v3/movie")

    def list_movie_files(self) -> list[RadarrMovieFile]:
        """Bibliotheque locale : un film sans fichier telecharge (`hasFile`
        faux) n'apparait pas : rien a comparer a C411 pour lui."""
        movies: list[RadarrMovieFile] = []
        for movie in self.list_movies():
            movie_file = movie.get("movieFile")
            if not movie.get("hasFile") or not movie_file:
                continue
            quality = movie_file.get("quality", {}).get("quality", {}) or {}
            movies.append(
                RadarrMovieFile(
                    movie_id=movie["id"],
                    title=movie.get("title", ""),
                    year=movie.get("year"),
                    imdb_id=movie.get("imdbId"),
                    tmdb_id=movie.get("tmdbId"),
                    best_resolution=quality.get("resolution"),
                    quality_name=quality.get("name"),
                    scene_name=movie_file.get("sceneName"),
                    language_names=[lang.get("name", "") for lang in movie_file.get("languages", [])],
                )
            )
        return movies
