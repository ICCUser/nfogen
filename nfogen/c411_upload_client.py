"""Client pour l'API d'upload de C411 (POST/PATCH /api/user/drafts,
GET /api/torrents/by-tmdb) -- voir AUTOMATION.md, sous-projet 5.

DELIBEREMENT specifique a C411, contrairement a torznab_client.py : cette
API REST (endpoints, champs, format `options`) n'a aucun standard
equivalent partage par d'autres trackers (voir AUTOMATION.md, "Principe
directeur", et decision 4 du sous-projet 5). Reste nomme et pense comme
specifique jusqu'a preuve du contraire (un deuxieme tracker a integrer un
jour).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx


class C411UploadError(RuntimeError):
    """Erreur reseau ou reponse inattendue de l'API d'upload C411."""


class C411UploadClient:
    """Client HTTP pour l'API d'upload/brouillons de C411."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://c411.org/api",
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise C411UploadError("Cle API C411 manquante.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "C411UploadClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _redact(self, exc: Exception) -> str:
        return str(exc).replace(self._api_key, "<cle redigee>")

    def check_duplicates(self, tmdb_id: int, tmdb_type: str) -> list[dict[str, Any]]:
        """`GET /api/torrents/by-tmdb?tmdbId=...&tmdbType=movie|tv` :
        releases deja approuvees pour cet identifiant TMDB (10 max, limite
        30 requetes/min cote C411 -- appele une seule fois par tentative
        d'envoi, jamais en boucle). Leve C411UploadError en cas d'echec ;
        l'appelant (upload_prep.send_to_tracker) decide de degrader en
        avertissement plutot que de bloquer l'envoi (AUTOMATION.md,
        decision 5 : jamais bloquant)."""
        try:
            response = self._client.get(
                f"{self._base_url}/torrents/by-tmdb",
                params={"tmdbId": tmdb_id, "tmdbType": tmdb_type},
                headers=self._headers(),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise C411UploadError(f"Vérification des doublons échouée : {self._redact(exc)}") from exc
        return response.json().get("releases", [])
