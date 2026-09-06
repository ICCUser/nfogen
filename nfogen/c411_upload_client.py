"""Client pour l'API d'upload de C411 (POST/PATCH /api/user/drafts,
GET /api/torrents/by-tmdb) -- voir AUTOMATION.md, sous-projet 5.

DELIBEREMENT specifique a C411, contrairement a torznab_client.py : cette
API REST (endpoints, champs, format `options`) n'a aucun standard
equivalent partage par d'autres trackers (voir AUTOMATION.md, "Principe
directeur", et decision 4 du sous-projet 5). Reste nomme et pense comme
specifique jusqu'a preuve du contraire (un deuxieme tracker a integrer un
jour).

Format exact du corps JSON de `POST`/`PATCH /api/user/drafts` confirme
en conditions reelles le 2026-09-06, apres plusieurs hypotheses rejetees
tour a tour (`torrent`/`nfo` en base64, `multipart/form-data`,
`torrentFile`/`nfoFile` en simple chaine base64 -- voir AUTOMATION.md,
sous-projet 5, pour l'historique complet) : le corps ENVOYE utilise des
champs PLATS -- `torrentFileName`/`torrentFileData` et
`nfoFileName`/`nfoFileData` (chaine de nom de fichier + chaine base64
separement), confirme en creant un brouillon reel avec ce format exact
et en constatant `torrentFile`/`nfoFile` bien remplis a la relecture.
La reponse de l'API restructure ces champs plats en objets imbriques
`torrentFile: {name, data}`/`nfoFile: {name, data}` -- une asymetrie
lecture/ecriture, jamais documentee, qui a rendu ce format difficile a
deviner sans comparer un brouillon reel cree depuis le site web."""
from __future__ import annotations

import base64
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

    def _draft_body(
        self,
        *,
        torrent_bytes: bytes,
        nfo_bytes: bytes,
        torrent_filename: str,
        nfo_filename: str,
        title: str,
        description: str,
        category_id: int,
        subcategory_id: int,
        options: dict[str, Any],
        description_format: str,
        uploader_note: Optional[str],
        tmdb_data: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "torrentFileName": torrent_filename,
            "torrentFileData": base64.b64encode(torrent_bytes).decode("ascii"),
            "nfoFileName": nfo_filename,
            "nfoFileData": base64.b64encode(nfo_bytes).decode("ascii"),
            "title": title,
            "description": description,
            "descriptionFormat": description_format,
            "categoryId": category_id,
            "subcategoryId": subcategory_id,
            "options": options,
        }
        if uploader_note:
            body["uploaderNote"] = uploader_note
        if tmdb_data:
            body["tmdbData"] = tmdb_data
        return body

    def _handle_draft_response(self, request_desc: str, send) -> dict[str, Any]:
        try:
            response = send()
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise C411UploadError(
                    "Authentification refusée par C411 (401/403) — vérifie que ta clé API a le "
                    "scope upload/brouillons sur https://c411.org/user/integrations."
                ) from exc
            detail = None
            try:
                payload = exc.response.json()
                detail = payload.get("message") or payload.get("error")
            except Exception:  # noqa: BLE001 -- corps non-JSON ou inattendu, repli generique
                pass
            raise C411UploadError(detail or f"{request_desc} échouée : {self._redact(exc)}") from exc
        except httpx.HTTPError as exc:
            raise C411UploadError(f"{request_desc} échouée : {self._redact(exc)}") from exc
        return response.json()

    def create_draft(
        self,
        *,
        torrent_bytes: bytes,
        nfo_bytes: bytes,
        torrent_filename: str,
        nfo_filename: str,
        title: str,
        description: str,
        category_id: int,
        subcategory_id: int,
        options: dict[str, Any],
        description_format: str = "standard",
        uploader_note: Optional[str] = None,
        tmdb_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """`POST /api/user/drafts` : cree un NOUVEAU brouillon -- n'entre
        JAMAIS en file de moderation tout seul (voir AUTOMATION.md,
        decision 6). `torrent_bytes`/`nfo_bytes` envoyes en base64 sous
        des champs plats `torrentFileName`/`torrentFileData` et
        `nfoFileName`/`nfoFileData` (voir note en tete de module --
        format confirme en conditions reelles)."""
        body = self._draft_body(
            torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes,
            torrent_filename=torrent_filename, nfo_filename=nfo_filename,
            title=title, description=description,
            category_id=category_id, subcategory_id=subcategory_id, options=options,
            description_format=description_format, uploader_note=uploader_note, tmdb_data=tmdb_data,
        )
        return self._handle_draft_response(
            "Création du brouillon",
            lambda: self._client.post(f"{self._base_url}/user/drafts", json=body, headers=self._headers()),
        )

    def update_draft(
        self,
        draft_id: Any,
        *,
        torrent_bytes: bytes,
        nfo_bytes: bytes,
        torrent_filename: str,
        nfo_filename: str,
        title: str,
        description: str,
        category_id: int,
        subcategory_id: int,
        options: dict[str, Any],
        description_format: str = "standard",
        uploader_note: Optional[str] = None,
        tmdb_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """`PATCH /api/user/drafts/{draft_id}` : met a jour un brouillon
        DEJA CREE (evite d'en accumuler des doublons vers la limite de 15
        -- voir AUTOMATION.md, decision 6). Meme format de champs plats
        que `create_draft` (voir note en tete de module)."""
        body = self._draft_body(
            torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes,
            torrent_filename=torrent_filename, nfo_filename=nfo_filename,
            title=title, description=description,
            category_id=category_id, subcategory_id=subcategory_id, options=options,
            description_format=description_format, uploader_note=uploader_note, tmdb_data=tmdb_data,
        )
        return self._handle_draft_response(
            "Mise à jour du brouillon",
            lambda: self._client.patch(
                f"{self._base_url}/user/drafts/{draft_id}", json=body, headers=self._headers()
            ),
        )
