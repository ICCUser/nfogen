"""Client pour l'API TMDB (v3, auth par parametre `api_key`), lecture
seule -- complete Radarr/Sonarr pour les 3 champs absents des deux API
(confirme par des dumps reels, voir docs/superpowers/specs/
2026-09-07-template-charte-tmdb-design.md) : pays de production,
createur(s) (series), note TMDB. Best-effort par construction : toute
erreur leve `TMDBError`, a l'appelant (upload_prep.send_to_tracker) de
l'attraper et de continuer sans ces champs -- jamais silencieux ici."""
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

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.get(
                f"{_BASE_URL}{path}", params={"api_key": self._api_key}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TMDBError(f"Appel TMDB échoué ({path}) : {exc}") from exc
        return response.json()

    @staticmethod
    def _country(data: dict[str, Any]) -> Optional[str]:
        countries = data.get("production_countries") or []
        return countries[0].get("name") if countries else None

    @staticmethod
    def _vote_average(data: dict[str, Any]) -> Optional[float]:
        value = data.get("vote_average")
        return round(value, 1) if value else None  # 0/None traites comme "jamais note"

    def get_movie_extra(self, tmdb_id: int) -> TMDBExtraDetails:
        data = self._get(f"/movie/{tmdb_id}")
        return TMDBExtraDetails(country=self._country(data), vote_average=self._vote_average(data))

    def get_series_extra(self, tmdb_id: int) -> TMDBExtraDetails:
        data = self._get(f"/tv/{tmdb_id}")
        creators = [c["name"] for c in data.get("created_by", []) if c.get("name")]
        return TMDBExtraDetails(
            country=self._country(data), vote_average=self._vote_average(data), creators=creators
        )
