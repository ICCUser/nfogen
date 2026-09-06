"""Inventaire local Radarr/Sonarr, SANS AUCUN appel tracker par defaut
(AUTOMATION.md, sous-projet 8) -- pour un rechargement quasi instantane
meme sur une grosse bibliotheque ("recharger sans faire de scan C411, car
c'est une API et une action longue", retour utilisateur 2026-09-06).

Reutilise list_movie_files()/list_season_files() (deja utilises par
gapscan.run_gapscan) -- rien de nouveau cote Radarr/Sonarr au-dela des
champs genres/added_at ajoutes par les sous-taches precedentes.

`LibraryItem.key` (cle de SELECTION, movie_key/series_key -- voir
gapscan.py) est DIFFERENTE de `already_processed`/`last_processed_at`
(bases sur upload_history_store.processed_key, radarr_movie_id/
sonarr_series_id) : la premiere sert a retrouver l'item dans
run_gapscan(), la seconde a savoir s'il a deja ete confirme/envoye.

Fusion Bibliotheque/Scan (retour utilisateur, 2026-09-06 : "ca fait
doublon" -- les deux pages se recouvraient trop pour justifier d'exister
separement) : `previous_results` (optionnel, les derniers resultats de
scan connus -- gapscan_runner.results()) enrichit chaque item du statut
tracker DEJA CONNU pour lui, retrouve via la MEME cle que la selection
(movie_key/series_key) -- jamais une nouvelle interrogation de C411 ici."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import upload_history_store
from .gapscan import GapResult, genre_of, movie_key, series_key
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
    # Statut tracker DEJA CONNU (dernier scan bulk ou cible, voir
    # `previous_results` de list_library) -- `None` si ce titre n'a jamais
    # ete verifie sur le tracker. Jamais rafraichi ici (list_library ne
    # fait aucun appel tracker).
    status: Optional[str] = None
    checked_at: Optional[float] = None
    has_freeleech_alternative: bool = False
    has_double_upload_window: bool = False
    error: Optional[str] = None
    local_paths: list[str] = field(default_factory=list)
    path_resolved: bool = False
    path_error: Optional[str] = None
    # Categorie C411 du match trouve (voir gapscan.genre_of) -- DISTINCT de
    # `genres` (Radarr/Sonarr) : les deux classifications restent
    # volontairement independantes (voir la spec du sous-projet 8).
    tracker_genre: Optional[str] = None


def _previous_key(r: GapResult) -> str:
    """Meme calcul que gapscan._result_key (prive), duplique ici en chaine
    (voir upload_history_store.key_str) pour matcher directement
    LibraryItem.key -- reutilise movie_key/series_key (deja publiques,
    extraites pour precisement cet usage), plutot que d'importer un nom
    prive d'un autre module."""
    if r.media_type == "movie":
        return upload_history_store.key_str(movie_key(r.imdb_id, r.tmdb_id, r.title, r.year))
    return upload_history_store.key_str(series_key(r.tvdb_id, r.imdb_id, r.title, r.season_number))


def list_library(
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    previous_results: Optional[list[GapResult]] = None,
    profile: str = "c411",
) -> list[LibraryItem]:
    """Inventaire local complet (`radarr`/`sonarr` optionnels, l'un ou
    l'autre ou les deux) -- synchrone, jamais de tache de fond : uniquement
    des appels Radarr/Sonarr locaux/rapides, pas de rate-limit connu cote
    nfogen (contrairement a run_gapscan).

    `previous_results` (optionnel) : derniers resultats de scan connus
    (bulk ou cible, voir gapscan_runner.results()) -- chaque item reprend
    le statut tracker DEJA CONNU pour lui (retrouve via la meme cle que la
    selection), sans jamais reinterroger C411 ici. `None`/absent : aucun
    item n'a de statut connu (comportement d'origine, avant la fusion
    Bibliotheque/Scan).

    `profile` : quel profil de tracker pour classer `tracker_genre`
    (gapscan.genre_of, categories Torznab namespacees par profil)."""
    previous_by_key = {_previous_key(r): r for r in (previous_results or [])}

    items: list[LibraryItem] = []
    if radarr is not None:
        for movie in radarr.list_movie_files():
            tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
            proc_key = upload_history_store.processed_key("movie", movie.movie_id, None)
            key = upload_history_store.key_str(movie_key(movie.imdb_id, tmdb_id, movie.title, movie.year))
            previous = previous_by_key.get(key)
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
                    key=key,
                    status=previous.status.value if previous else None,
                    checked_at=previous.checked_at if previous else None,
                    has_freeleech_alternative=previous.has_freeleech_alternative if previous else False,
                    has_double_upload_window=previous.has_double_upload_window if previous else False,
                    error=previous.error if previous else None,
                    local_paths=previous.local_paths if previous else [],
                    path_resolved=previous.path_resolved if previous else False,
                    path_error=previous.path_error if previous else None,
                    tracker_genre=genre_of(previous, profile) if previous else None,
                )
            )
    if sonarr is not None:
        for season in sonarr.list_season_files():
            proc_key = upload_history_store.processed_key(
                "series", None, season.series_id, season.season_number
            )
            key = upload_history_store.key_str(
                series_key(season.tvdb_id, season.imdb_id, season.title, season.season_number)
            )
            previous = previous_by_key.get(key)
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
                    key=key,
                    status=previous.status.value if previous else None,
                    checked_at=previous.checked_at if previous else None,
                    has_freeleech_alternative=previous.has_freeleech_alternative if previous else False,
                    has_double_upload_window=previous.has_double_upload_window if previous else False,
                    error=previous.error if previous else None,
                    local_paths=previous.local_paths if previous else [],
                    path_resolved=previous.path_resolved if previous else False,
                    path_error=previous.path_error if previous else None,
                    tracker_genre=genre_of(previous, profile) if previous else None,
                )
            )
    return items
