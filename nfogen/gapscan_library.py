"""Inventaire local Radarr/Sonarr, SANS AUCUN appel tracker (AUTOMATION.md,
sous-projet 8) -- pour un rechargement quasi instantane meme sur une
grosse bibliotheque ("recharger sans faire de scan C411, car c'est une
API et une action longue", retour utilisateur 2026-09-06).

Reutilise list_movie_files()/list_season_files() (deja utilises par
gapscan.run_gapscan) -- rien de nouveau cote Radarr/Sonarr au-dela des
champs genres/added_at ajoutes par les sous-taches precedentes.

`LibraryItem.key` (cle de SELECTION, movie_key/series_key -- voir
gapscan.py) est DIFFERENTE de `already_processed`/`last_processed_at`
(bases sur upload_history_store.processed_key, radarr_movie_id/
sonarr_series_id) : la premiere sert a retrouver l'item dans
run_gapscan(), la seconde a savoir s'il a deja ete confirme/envoye."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import upload_history_store
from .gapscan import movie_key, series_key
from .quality import ReleaseQuality, build_quality
from .radarr_client import RadarrClient
from .sonarr_client import SonarrClient


@dataclass
class LibraryItem:
    media_type: str  # "movie" | "series"
    title: str
    year: Optional[int]
    season_number: Optional[int]  # None pour un film
    imdb_id: Optional[str]
    tvdb_id: Optional[int]
    tmdb_id: Optional[str]
    genres: list[str]
    added_at: Optional[float]
    local_quality: ReleaseQuality
    radarr_movie_id: Optional[int]
    sonarr_series_id: Optional[int]
    already_processed: bool
    last_processed_at: Optional[float]
    # Cle de SELECTION serialisee (movie_key/series_key, voir gapscan.py) --
    # chaine opaque du point de vue du frontend, renvoyee telle quelle a
    # POST /gapscan/run pour restreindre un scan a cet item precis.
    key: str


def list_library(
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
) -> list[LibraryItem]:
    """Inventaire local complet (`radarr`/`sonarr` optionnels, l'un ou
    l'autre ou les deux) -- synchrone, jamais de tache de fond : uniquement
    des appels Radarr/Sonarr locaux/rapides, pas de rate-limit connu cote
    nfogen (contrairement a run_gapscan)."""
    items: list[LibraryItem] = []
    if radarr is not None:
        for movie in radarr.list_movie_files():
            tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
            proc_key = upload_history_store.processed_key("movie", movie.movie_id, None)
            items.append(
                LibraryItem(
                    media_type="movie", title=movie.title, year=movie.year, season_number=None,
                    imdb_id=movie.imdb_id, tvdb_id=None, tmdb_id=tmdb_id,
                    genres=movie.genres, added_at=movie.added_at,
                    local_quality=build_quality(
                        movie.scene_name or movie.title,
                        fallback_resolution=movie.best_resolution,
                        fallback_language_names=movie.language_names,
                    ),
                    radarr_movie_id=movie.movie_id, sonarr_series_id=None,
                    already_processed=proc_key is not None and upload_history_store.is_processed(proc_key),
                    last_processed_at=upload_history_store.last_processed_at(proc_key) if proc_key else None,
                    key=upload_history_store.key_str(
                        movie_key(movie.imdb_id, tmdb_id, movie.title, movie.year)
                    ),
                )
            )
    if sonarr is not None:
        for season in sonarr.list_season_files():
            proc_key = upload_history_store.processed_key("series", None, season.series_id, season.season_number)
            items.append(
                LibraryItem(
                    media_type="series", title=season.title, year=season.year,
                    season_number=season.season_number, imdb_id=season.imdb_id,
                    tvdb_id=season.tvdb_id, tmdb_id=None,
                    genres=season.genres, added_at=season.added_at,
                    local_quality=build_quality(
                        season.scene_name or season.title,
                        fallback_resolution=season.best_resolution,
                        fallback_language_names=season.language_names,
                    ),
                    radarr_movie_id=None, sonarr_series_id=season.series_id,
                    already_processed=proc_key is not None and upload_history_store.is_processed(proc_key),
                    last_processed_at=upload_history_store.last_processed_at(proc_key) if proc_key else None,
                    key=upload_history_store.key_str(
                        series_key(season.tvdb_id, season.imdb_id, season.title, season.season_number)
                    ),
                )
            )
    return items
