"""Client pour l'API REST de Radarr (v3), lecture seule.

Symetrique de `sonarr_client.py` pour les films : ne recupere que ce qu'il
faut pour GapScan. Aucune ecriture, aucune modification de la bibliotheque
Radarr.
"""
from __future__ import annotations

import datetime
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
    # Titres alternatifs connus de Radarr (ex. titre de sortie FR different
    # de l'original) -- utilises en repli par gapscan.py quand la recherche
    # C411 par titre principal ne trouve rien : C411 est un tracker
    # francophone, qui liste souvent sous le titre de diffusion FR (ex.
    # "Wild Card" -> "Joker"), pas l'original (retour utilisateur, 2026-08-27).
    alternate_titles: list[str] = field(default_factory=list)
    # Chemin absolu du fichier tel que rapporte par Radarr -- peut differer
    # du chemin que nfogen doit reellement ouvrir si nfogen tourne ailleurs
    # que Radarr (voir AUTOMATION.md, sous-projet 1 : mapping de chemins).
    remote_path: Optional[str] = None
    # Genres Radarr/Sonarr (PAS la categorie C411) -- utilise par la vue
    # "Bibliotheque" (AUTOMATION.md, sous-projet 8), jamais pendant un scan
    # GapScan classique (voir gapscan.genre_of, base sur la categorie du
    # match C411 trouve -- deux classifications independantes).
    genres: list[str] = field(default_factory=list)
    # Horodatage (epoch secondes) d'ajout a Radarr -- `None` si absent ou
    # illisible (jamais une exception, voir _parse_radarr_date).
    added_at: Optional[float] = None


@dataclass
class RadarrMovieDetails:
    """Metadonnees de presentation d'un film (synopsis, affiche, genres,
    realisateur/casting) -- recuperees A LA DEMANDE (voir get_movie_details),
    jamais pendant le scan GapScan (voir AUTOMATION.md, sous-projet 5,
    decision 1 : inutile pour l'ecrasante majorite des 1000+ items scannes,
    seulement pour celui qu'on envoie reellement a un tracker). Radarr
    interroge deja TMDB pour son propre usage -- reutilise ici plutot
    qu'un client TMDB dedie."""

    overview: str = ""
    poster_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)


def _parse_radarr_date(value: Optional[str]) -> Optional[float]:
    """`movie.get("added")` (ISO 8601, ex. "2024-03-15T10:30:00Z") -> epoch
    secondes, ou `None` si absent/illisible -- jamais une exception (champ
    jamais lu par ce projet avant le sous-projet 8, a verifier contre une
    vraie reponse Radarr avant de considerer cette tache terminee)."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


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
                    alternate_titles=[
                        t.get("title", "") for t in movie.get("alternateTitles", []) if t.get("title")
                    ],
                    remote_path=movie_file.get("path"),
                    genres=movie.get("genres") or [],
                    added_at=_parse_radarr_date(movie.get("added")),
                )
            )
        return movies

    def get_movie_details(self, movie_id: int) -> RadarrMovieDetails:
        """`GET /api/v3/movie/{id}` : metadonnees de presentation completes
        d'UN film -- jamais appele en boucle pendant un scan, uniquement au
        moment de preparer un envoi vers un tracker (voir upload_prep.py)."""
        movie = self._get(f"/api/v3/movie/{movie_id}")
        poster_url = next(
            (img.get("remoteUrl") for img in movie.get("images", []) if img.get("coverType") == "poster"),
            None,
        )
        directors = [
            c["person"]["name"]
            for c in movie.get("credits", [])
            if c.get("type") == "crew" and c.get("job") == "Director" and c.get("person", {}).get("name")
        ]
        cast = [
            c["person"]["name"]
            for c in movie.get("credits", [])
            if c.get("type") == "cast" and c.get("person", {}).get("name")
        ]
        return RadarrMovieDetails(
            overview=movie.get("overview") or "",
            poster_url=poster_url,
            genres=movie.get("genres") or [],
            directors=directors,
            cast=cast,
        )
