"""Client pour l'API REST de Lidarr (v1), lecture seule.

Symetrique de `radarr_client.py`/`sonarr_client.py` pour la musique : ne
recupere que ce qu'il faut pour GapScan Musique. Aucune ecriture, aucune
modification de la bibliotheque Lidarr.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional

import httpx


class LidarrError(RuntimeError):
    """Erreur reseau ou reponse inattendue de l'API Lidarr."""


@dataclass
class LidarrAlbumFile:
    """Un album possede localement (au moins un fichier telecharge)."""

    album_id: int
    artist_name: str
    album_title: str
    release_year: Optional[int]
    musicbrainz_album_id: Optional[str]
    musicbrainz_artist_id: Optional[str]
    remote_path: Optional[str]
    size_bytes: Optional[int]
    added_at: Optional[float]
    track_count: int


def _parse_lidarr_date(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _parse_year(release_date: Optional[str]) -> Optional[int]:
    if not release_date or len(release_date) < 4:
        return None
    try:
        return int(release_date[:4])
    except ValueError:
        return None


def _common_dir(paths: list[str]) -> Optional[str]:
    """Dossier parent commun aux fichiers d'un album (ex. le dossier de
    l'album lui-meme) -- calcule le vrai prefixe commun a TOUS les chemins,
    gere les albums multi-disques. Retourne `None` si `paths` est vide."""
    if not paths:
        return None
    import posixpath

    if len(paths) == 1:
        return posixpath.dirname(paths[0])
    try:
        return posixpath.commonpath(paths)
    except ValueError:
        # Chemins sans racine commune, retourner le dirname du premier
        return posixpath.dirname(paths[0])


class LidarrClient:
    """Client HTTP pour l'API v1 de Lidarr."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not api_key:
            raise LidarrError("URL ou cle API Lidarr manquante.")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "LidarrClient":
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
            raise LidarrError(f"Appel Lidarr echoue ({path}) : {exc}") from exc
        return response.json()

    def list_artists(self) -> list[dict[str, Any]]:
        """`GET /api/v1/artist` brut."""
        return self._get("/api/v1/artist")

    def list_albums(self) -> list[dict[str, Any]]:
        """`GET /api/v1/album` brut (tous artistes)."""
        return self._get("/api/v1/album", params={"includeAllArtistAlbums": "true"})

    def list_track_files(self, album_id: int) -> list[dict[str, Any]]:
        """`GET /api/v1/trackfile?albumId={id}` brut."""
        return self._get("/api/v1/trackfile", params={"albumId": album_id})

    def list_album_files(self) -> list[LidarrAlbumFile]:
        """Bibliotheque locale : un album sans fichier telecharge
        (`statistics.trackFileCount == 0`) n'apparait pas -- rien a
        comparer a C411 pour lui."""
        artists_by_id = {a["id"]: a for a in self.list_artists()}
        albums: list[LidarrAlbumFile] = []
        for album in self.list_albums():
            stats = album.get("statistics") or {}
            track_count = stats.get("trackFileCount") or 0
            if not track_count:
                continue
            artist = artists_by_id.get(album.get("artistId"), {})
            track_files = self.list_track_files(album["id"])
            paths = [t.get("path", "") for t in track_files if t.get("path")]
            added_dates = [_parse_lidarr_date(t.get("dateAdded")) for t in track_files]
            added_dates = [d for d in added_dates if d is not None]
            albums.append(
                LidarrAlbumFile(
                    album_id=album["id"],
                    artist_name=artist.get("artistName", ""),
                    album_title=album.get("title", ""),
                    release_year=_parse_year(album.get("releaseDate")),
                    musicbrainz_album_id=album.get("foreignAlbumId"),
                    musicbrainz_artist_id=artist.get("foreignArtistId"),
                    remote_path=_common_dir(paths),
                    size_bytes=stats.get("sizeOnDisk"),
                    added_at=min(added_dates) if added_dates else None,
                    track_count=track_count,
                )
            )
        return albums
