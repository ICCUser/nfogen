"""Client pour l'API Web de qBittorrent (v2) -- AUTOMATION.md, sous-projet
6. Utilise pour ajouter un .torrent RE-SIGNE par le tracker (recupere
MANUELLEMENT par l'utilisateur -- l'endpoint de telechargement C411 exige
une session navigateur, pas la cle API, verifie en conditions reelles
2026-09-06 : aucune automatisation possible cote recuperation) et le
pointer sur le contenu DEJA en scene par nfogen -- jamais retelecharge
par ce module, seulement verifie/seede par qBittorrent lui-meme.

`list_torrents()` (retour utilisateur, 2026-09-06 : voir ce qui est
actuellement en seed) est lecture seule -- aucune ecriture, aucune
modification de la file qBittorrent."""
from __future__ import annotations

from typing import Any, Optional

import httpx


class QBittorrentError(RuntimeError):
    """Erreur reseau, authentification ou reponse inattendue de l'API qBittorrent."""


class QBittorrentClient:
    """Client HTTP pour l'API Web v2 de qBittorrent."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not username or not password:
            raise QBittorrentError("URL, utilisateur ou mot de passe qBittorrent manquant.")
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None
        self._logged_in = False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "QBittorrentClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _login(self) -> None:
        try:
            response = self._client.post(
                f"{self._base_url}/api/v2/auth/login",
                data={"username": self._username, "password": self._password},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Connexion à qBittorrent échouée : {exc}") from exc
        if response.text.strip() != "Ok.":
            raise QBittorrentError("Authentification qBittorrent refusée (identifiants incorrects ?).")
        self._logged_in = True

    def add_torrent(self, torrent_bytes: bytes, save_path: str, filename: str = "release.torrent") -> None:
        """Ajoute un .torrent DEJA telecharge (voir docstring du module),
        pointe sur `save_path` -- le contenu doit deja s'y trouver. Leve
        `QBittorrentError` en cas d'echec (connexion, authentification,
        ou refus par qBittorrent)."""
        if not self._logged_in:
            self._login()
        try:
            response = self._client.post(
                f"{self._base_url}/api/v2/torrents/add",
                files={"torrents": (filename, torrent_bytes, "application/x-bittorrent")},
                data={"savepath": save_path},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Ajout du torrent à qBittorrent échoué : {exc}") from exc
        if response.text.strip() != "Ok.":
            raise QBittorrentError(f"qBittorrent a refusé le torrent : {response.text.strip()}")

    def list_torrents(self) -> list[dict[str, Any]]:
        """`GET /api/v2/torrents/info` brut -- lecture seule, pour afficher
        ce qui est actuellement en seed (nom, taille, progression, ratio,
        statut, vitesse d'upload...). Leve `QBittorrentError` en cas
        d'echec (connexion ou authentification)."""
        if not self._logged_in:
            self._login()
        try:
            response = self._client.get(f"{self._base_url}/api/v2/torrents/info")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Lecture des torrents qBittorrent échouée : {exc}") from exc
        return response.json()
