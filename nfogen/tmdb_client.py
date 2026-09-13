"""Client pour l'API TMDB (v3, auth par parametre `api_key`), lecture
seule -- complete Radarr/Sonarr pour les champs absents des deux API
(confirme par des dumps reels, voir docs/superpowers/specs/
2026-09-07-template-charte-tmdb-design.md) : pays de production,
createur(s) (series), note TMDB, et un synopsis DANS LA LANGUE DU
TRACKER (retour reel de moderation C411, 2026-09-13 : "le synopsis est
en anglais" -- l'overview de upload_prep.py vient de Radarr/Sonarr, dans
la langue de LEUR propre config metadata, jamais controlee par nfogen ;
TMDB, lui, sait renvoyer une version localisee via `language=...`, code
configurable par profil -- voir tracker_profile.tmdb_language(),
"fr-FR" par defaut).
Best-effort par construction : toute erreur leve `TMDBError`, a
l'appelant (upload_prep.send_to_tracker) de l'attraper et de continuer
sans ces champs -- jamais silencieux ici."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

_BASE_URL = "https://api.themoviedb.org/3"


class TMDBError(RuntimeError):
    """Erreur reseau, authentification ou reponse inattendue de l'API TMDB."""


@dataclass
class TMDBExtraDetails:
    country: Optional[str] = None
    vote_average: Optional[float] = None
    creators: list[str] = field(default_factory=list)
    overview_localized: Optional[str] = None


class TMDBClient:
    """Client HTTP pour l'API v3 de TMDB."""

    def __init__(
        self,
        api_key: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise TMDBError("Clé API TMDB manquante.")
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TMDBClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get(self, path: str, **extra_params: str) -> dict[str, Any]:
        try:
            response = self._client.get(
                f"{_BASE_URL}{path}", params={"api_key": self._api_key, **extra_params}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TMDBError(f"Appel TMDB échoué ({path}) : {exc}") from exc
        return response.json()

    def _overview_localized(self, path: str, language: str) -> Optional[str]:
        """Synopsis dans `language` (code TMDB, ex. "fr-FR"), ou `None` si
        TMDB n'a pas de traduction pour ce titre dans cette langue (chaine
        vide) -- jamais une chaine vide affichee a la place d'un vrai
        synopsis, laisse le repli existant (overview Radarr/Sonarr, voir
        upload_prep.py) prendre le relais dans ce cas."""
        data = self._get(path, language=language)
        return data.get("overview") or None

    @staticmethod
    def _country(data: dict[str, Any]) -> Optional[str]:
        countries = data.get("production_countries") or []
        return countries[0].get("name") if countries else None

    @staticmethod
    def _vote_average(data: dict[str, Any]) -> Optional[float]:
        value = data.get("vote_average")
        return round(value, 1) if value else None  # 0/None traites comme "jamais note"

    def get_movie_extra(self, tmdb_id: int, language: str = "fr-FR") -> TMDBExtraDetails:
        data = self._get(f"/movie/{tmdb_id}")
        return TMDBExtraDetails(
            country=self._country(data), vote_average=self._vote_average(data),
            overview_localized=self._overview_localized(f"/movie/{tmdb_id}", language),
        )

    def get_series_extra(self, tmdb_id: int, language: str = "fr-FR") -> TMDBExtraDetails:
        data = self._get(f"/tv/{tmdb_id}")
        creators = [cr["name"] for cr in data.get("created_by", []) if cr.get("name")]
        return TMDBExtraDetails(
            country=self._country(data), vote_average=self._vote_average(data), creators=creators,
            overview_localized=self._overview_localized(f"/tv/{tmdb_id}", language),
        )
