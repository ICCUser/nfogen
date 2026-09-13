# Categorie Musique (Audio, Lidarr) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner a nfogen un pipeline complet (Lidarr -> detection de gap -> nommage -> NFO -> description -> upload C411) pour la categorie Musique, symetrique a celui deja existant pour films/series.

**Architecture:** Un nouveau client REST Lidarr (lecture seule, meme patron que `radarr_client.py`), une fonction de scan dediee (`scan_album`), un moteur de nommage dedie (`propose_music_release_name`, le gabarit Musique etant structurellement different du gabarit video), et la generalisation du rendu de description BBCode par categorie. Le NFO audio et l'extraction MediaInfo (`extract_album`) existent deja et sont reutilises tels quels.

**Tech Stack:** Python 3.13, httpx (client HTTP), pytest, Jinja2 (templates), pymediainfo (deja utilise par `extract_album`).

**Spec:** `docs/superpowers/specs/2026-09-13-music-category-lidarr-design.md`

## Global Constraints

- Aucune ecriture sur Lidarr : lecture seule, meme garde-fou que Radarr/Sonarr (`docstring` de tete de chaque client existant).
- Rien ne doit changer dans le comportement existant de la categorie video (`propose_video_release_name`, `render_upload_description` par defaut, `run_gapscan` pour movie/series) -- toute extension est additive, verifiee par la suite de tests existante qui doit rester verte.
- Les ids d'options C411 specifiques a l'Audio (types 15/16, voir `C411_API.htm`) ne sont pas documentes publiquement -- la Tache 4 exige une verification EN DIRECT (`GET /api/categories/18/options`) avant d'ecrire une seule valeur en dur dans `rules.json`. Aucune valeur devinee.
- **Hors perimetre de ce plan (deliberement, YAGNI)** : integration UI frontend (page Bibliotheque / panneau "Preparer l'upload" pour la musique) et integration dans l'orchestrateur `run_gapscan()` existant (incremental/selection/on_progress, deja complexe pour video). Ce plan livre un pipeline backend complet et testable de bout en bout (appelable via un script/la CLI), suffisant pour valider l'approche avant d'investir dans l'UI -- sous-projet de suivi separe une fois ce pipeter valide en conditions reelles.
- Podcast/Radio et Samples restent hors perimetre (sous-projets separes, voir la spec).

---

### Task 1: Client Lidarr (lecture seule)

**Files:**
- Create: `nfogen/lidarr_client.py`
- Test: `tests/test_lidarr_client.py`

**Interfaces:**
- Consumes: rien (nouveau module autonome, meme patron que `nfogen/radarr_client.py`).
- Produces: `LidarrClient(base_url, api_key, http_client=None, timeout=30.0)`, `LidarrClient.list_album_files() -> list[LidarrAlbumFile]`, `LidarrError` (exception), `LidarrAlbumFile` (dataclass : `album_id: int`, `artist_name: str`, `album_title: str`, `release_year: Optional[int]`, `musicbrainz_album_id: Optional[str]`, `musicbrainz_artist_id: Optional[str]`, `remote_path: Optional[str]`, `size_bytes: Optional[int]`, `added_at: Optional[float]`, `track_count: int`).

L'API Lidarr v1 (stable, publique, meme conventions que Radarr/Sonarr) expose :
- `GET /api/v1/artist` : liste des artistes suivis, chaque entree porte `id`, `artistName`, `foreignArtistId` (MusicBrainz artist ID), `statistics.trackFileCount`.
- `GET /api/v1/album?includeAllArtistAlbums=true` : liste des albums, chaque entree porte `id`, `artistId`, `title`, `releaseDate` (ISO), `foreignAlbumId` (MusicBrainz release-group ID), `statistics.trackFileCount`, `statistics.sizeOnDisk`.
- `GET /api/v1/trackfile?albumId={id}` : fichiers locaux d'un album, chaque entree porte `path`, `size`, `dateAdded`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lidarr_client.py
from __future__ import annotations

import httpx
import pytest

from nfogen.lidarr_client import LidarrClient, LidarrError


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, responses: dict[str, object]):
        self._responses = responses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path_and_query = request.url.raw_path.decode()
        for path, body in self._responses.items():
            if path_and_query.startswith(path):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})


def _client(responses: dict[str, object]) -> LidarrClient:
    http_client = httpx.Client(transport=_FakeTransport(responses))
    return LidarrClient("http://lidarr.local:8686", "fake-key", http_client=http_client)


def test_list_album_files_skips_albums_without_local_tracks():
    responses = {
        "/api/v1/artist": [
            {"id": 1, "artistName": "Daft Punk", "foreignArtistId": "056e4f3e-d505-4dad-8ec1-d04f521cbb56"},
        ],
        "/api/v1/album": [
            {
                "id": 10, "artistId": 1, "title": "Random Access Memories",
                "releaseDate": "2013-05-17T00:00:00Z",
                "foreignAlbumId": "2c04a86b-3f75-4c50-9b7a-3f5e5e5e5e5e",
                "statistics": {"trackFileCount": 13, "sizeOnDisk": 987654321},
            },
            {
                "id": 11, "artistId": 1, "title": "Homework",
                "releaseDate": "1997-01-20T00:00:00Z",
                "foreignAlbumId": None,
                "statistics": {"trackFileCount": 0, "sizeOnDisk": 0},
            },
        ],
        "/api/v1/trackfile?albumId=10": [
            {"path": "/music/Daft Punk/RAM/01.flac", "size": 50000000, "dateAdded": "2024-01-01T00:00:00Z"},
        ],
    }
    client = _client(responses)
    try:
        albums = client.list_album_files()
    finally:
        client.close()

    assert len(albums) == 1  # "Homework" (0 fichier local) est ignore
    album = albums[0]
    assert album.album_id == 10
    assert album.artist_name == "Daft Punk"
    assert album.album_title == "Random Access Memories"
    assert album.release_year == 2013
    assert album.musicbrainz_album_id == "2c04a86b-3f75-4c50-9b7a-3f5e5e5e5e5e"
    assert album.musicbrainz_artist_id == "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
    assert album.remote_path == "/music/Daft Punk/RAM"
    assert album.size_bytes == 987654321
    assert album.track_count == 13


def test_missing_base_url_or_api_key_raises():
    with pytest.raises(LidarrError):
        LidarrClient("", "key")
    with pytest.raises(LidarrError):
        LidarrClient("http://lidarr.local", "")


def test_network_error_raises_lidarr_error():
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(_raise))
    client = LidarrClient("http://lidarr.local", "fake-key", http_client=http_client)
    try:
        with pytest.raises(LidarrError):
            client.list_album_files()
    finally:
        client.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_lidarr_client.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.lidarr_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# nfogen/lidarr_client.py
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
    l'album lui-meme) -- `None` si `paths` est vide."""
    if not paths:
        return None
    import posixpath

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_lidarr_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Ruff + commit**

```bash
./.venv/Scripts/python.exe -m ruff check nfogen/lidarr_client.py tests/test_lidarr_client.py
git add nfogen/lidarr_client.py tests/test_lidarr_client.py
git commit -m "feat: client Lidarr en lecture seule (categorie Musique)"
```

---

### Task 2: `TorznabClient.search_music` + `GapResult` etendu + `scan_album`

**IMPORTANT -- correction issue de l'auto-relecture de ce plan** : `TorznabClient`
(`nfogen/torznab_client.py`, deja lu integralement) n'a PAS de methode
generique `.search(query, category=...)` -- seulement `search_movie(query,
imdb_id, tmdb_id)` et `search_tv(query, imdb_id, tmdb_id, season, ep)`.
L'endpoint Torznab generique existe bien (`t=search`, confirme par le vrai
`GET /api/?t=caps` lu cette session : `<search available="yes"
supportedParams="q"/>`) mais ne supporte QUE `q` -- pas de parametre
categorie cote serveur pour cet endpoint. Cette tache ajoute donc d'abord
`search_music()` a `TorznabClient` avant d'ecrire `scan_album`.

**Files:**
- Modify: `nfogen/torznab_client.py`
- Modify: `nfogen/gapscan.py`
- Test: `tests/test_torznab_client.py`
- Test: `tests/test_gapscan.py`

**Interfaces:**
- Consumes: `LidarrAlbumFile` (Task 1), `TorznabRelease`/`parse_torznab_response` (existant), `GapResult`/`GapStatus`/`ReleaseQuality`/`build_quality` (existant dans `gapscan.py`).
- Produces: `TorznabClient.search_music(query: str) -> list[TorznabRelease]`, `GapResult.lidarr_album_id: Optional[int]` (nouveau champ, defaut `None`), `scan_album(album: LidarrAlbumFile, c411: TorznabClient, *, previous: Optional[GapResult] = None, max_age_seconds: Optional[float] = None) -> GapResult`.

**Limite connue, documentee plutot que masquee** : `t=search` ne filtre pas
par categorie cote serveur -- les resultats peuvent inclure des matches
hors Audio (homonymes dans d'autres categories). `scan_album` ne fait donc
PAS de filtrage supplementaire dans ce premier jet (le texte de recherche,
`f"{artist_name} {album_title}"`, est deja assez specifique en pratique) --
a affiner si des faux positifs reels sont observes.

- [ ] **Step 1: Write the failing test (TorznabClient.search_music)**

```python
# a ajouter a tests/test_torznab_client.py (reutilise les fixtures/helpers deja presents dans ce fichier, ex. httpx.MockTransport)
def test_search_music_uses_generic_search_endpoint():
    captured = {}

    def _handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, text=EMPTY_TORZNAB_RESPONSE)  # constante deja utilisee ailleurs dans ce fichier pour une reponse Torznab vide -- reutilise-la, ou construis un XML minimal <rss><channel></channel></rss> si elle n'existe pas encore

    http_client = httpx.Client(transport=httpx.MockTransport(_handler))
    client = TorznabClient("fake-key", http_client=http_client)
    client.search_music("Daft Punk Random Access Memories")

    assert captured["params"]["t"] == "search"
    assert captured["params"]["q"] == "Daft Punk Random Access Memories"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_torznab_client.py -k search_music -v`
Expected: FAIL avec `AttributeError: 'TorznabClient' object has no attribute 'search_music'`

- [ ] **Step 3: Write minimal implementation (TorznabClient.search_music)**

Ajouter juste apres `search_tv` dans `nfogen/torznab_client.py` :

```python
    def search_music(self, query: str) -> list[TorznabRelease]:
        """`t=search` : recherche generique par titre libre, seul parametre
        supporte par cet endpoint (confirme en direct via GET /api/?t=caps,
        `<search available="yes" supportedParams="q"/>`) -- pas de filtre
        categorie cote serveur, contrairement a `search_movie`/`search_tv`
        qui ciblent deja une categorie implicitement."""
        return self._search({"t": "search", "q": query})
```

- [ ] **Step 4: Run test to verify it passes, then full suite + ruff + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_torznab_client.py -v
./.venv/Scripts/python.exe -m ruff check nfogen/torznab_client.py tests/test_torznab_client.py
git add nfogen/torznab_client.py tests/test_torznab_client.py
git commit -m "feat: TorznabClient.search_music -- endpoint de recherche generique C411"
```

- [ ] **Step 5: Write the failing test (scan_album)**

```python
# a ajouter a tests/test_gapscan.py (reutilise les helpers _release()/TorznabRelease deja presents dans ce fichier)
from nfogen.lidarr_client import LidarrAlbumFile


def _album(**overrides) -> LidarrAlbumFile:
    base = dict(
        album_id=10, artist_name="Daft Punk", album_title="Random Access Memories",
        release_year=2013, musicbrainz_album_id="2c04a86b-3f75-4c50-9b7a-3f5e5e5e5e5e",
        musicbrainz_artist_id="056e4f3e-d505-4dad-8ec1-d04f521cbb56",
        remote_path="/music/Daft Punk/RAM", size_bytes=987654321,
        added_at=1700000000.0, track_count=13,
    )
    base.update(overrides)
    return LidarrAlbumFile(**base)


class _FakeC411Music:
    def __init__(self, releases):
        self._releases = releases

    def search_music(self, query: str):
        return self._releases


def test_scan_album_absent_when_no_c411_match():
    result = scan_album(_album(), _FakeC411Music([]))
    assert result.media_type == "music"
    assert result.status == GapStatus.ABSENT
    assert result.title == "Daft Punk - Random Access Memories"
    assert result.lidarr_album_id == 10


def test_scan_album_covered_when_equivalent_release_exists():
    existing = _release("Daft.Punk.Random.Access.Memories.2013.FLAC", category="3010")
    result = scan_album(_album(), _FakeC411Music([existing]))
    assert result.status == GapStatus.COVERED
```

- [ ] **Step 6: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -k scan_album -v`
Expected: FAIL avec `NameError: name 'scan_album' is not defined` (ou `AttributeError` sur `lidarr_album_id`)

- [ ] **Step 7: Write minimal implementation (scan_album)**

Ajouter le champ a `GapResult` (juste apres `sonarr_series_id`) :

```python
    sonarr_series_id: Optional[int] = None
    # Identifiant Lidarr interne de l'album -- meme role que
    # radarr_movie_id/sonarr_series_id, pour la categorie Musique.
    lidarr_album_id: Optional[int] = None
```

Ajouter `scan_album`, juste apres `scan_movie` :

```python
def scan_album(
    album: "LidarrAlbumFile",
    c411,
    *,
    previous: Optional[GapResult] = None,
    max_age_seconds: Optional[float] = None,
) -> GapResult:
    """Compare UN album Lidarr au catalogue C411. Symetrique de `scan_movie`
    pour la musique -- pas de recherche par identifiant universel (voir
    decision 3 de la spec, docs/superpowers/specs/2026-09-13-music-category-
    lidarr-design.md) : recherche texte via `c411.search_music()` (endpoint
    generique Torznab, pas de filtre categorie cote serveur -- voir la note
    de limite connue en tete de cette tache)."""
    title = f"{album.artist_name} - {album.album_title}"
    local_quality = build_quality(raw=f"{album.artist_name}.{album.album_title}.{album.release_year}")
    if previous is not None and _can_reuse(previous, local_quality, max_age_seconds):
        return replace(previous, local_paths=previous.local_paths)

    try:
        matches = c411.search_music(f"{album.artist_name} {album.album_title}")
    except TorznabError as exc:
        return GapResult(
            media_type="music", title=title, year=album.release_year, season_number=None,
            imdb_id=None, tmdb_id=None, tvdb_id=None, status=GapStatus.ERROR,
            local_quality=local_quality, error=str(exc), checked_at=time.time(),
            lidarr_album_id=album.album_id,
        )

    status = GapStatus.COVERED if matches else GapStatus.ABSENT
    return GapResult(
        media_type="music", title=title, year=album.release_year, season_number=None,
        imdb_id=None, tmdb_id=None, tvdb_id=None, status=status,
        local_quality=local_quality, c411_matches=matches, checked_at=time.time(),
        lidarr_album_id=album.album_id,
    )
```

Ajouter l'import en tete de fichier :

```python
from .lidarr_client import LidarrAlbumFile
```

- [ ] **Step 8: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -k scan_album -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Run full gapscan suite (non-regression) + ruff + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -v
./.venv/Scripts/python.exe -m ruff check nfogen/gapscan.py tests/test_gapscan.py
git add nfogen/gapscan.py tests/test_gapscan.py
git commit -m "feat: scan_album -- detection de gap C411 pour la musique (Lidarr)"
```

---

### Task 3: Nommage Musique (`propose_music_release_name`)

**Files:**
- Modify: `nfogen/name_proposal.py`
- Test: `tests/test_name_proposal.py`

**Interfaces:**
- Consumes: `NameProposal` (dataclass existante, `name: str | None`, `fields: dict[str, str]`, `warnings: list[str]`).
- Produces: `propose_music_release_name(artist: str, title: str, year: Optional[int], codec: str, bit_rate_kbps: Optional[int], bit_depth: Optional[int], sample_rate_hz: Optional[int], team: str, config: dict[str, Any], is_coffret: bool = False) -> NameProposal`.

Format officiel (doc "Le Nommage de l'upload", deja lu) :
- Lossless (codec dans `config["lossless_codecs"]`, ex. `["FLAC", "ALAC", "WAV", "WV", "AIF"]`) : `Artiste.Titre.Annee.Codec[BitProfondeur.Frequence]-TAG`, ex. `The.Weeknd.Blinding.Lights.2019.FLAC[16bit.44.1kHz]-NOTAG`. Frequence affichee en kHz avec une decimale (`44100 Hz` -> `44.1kHz`).
- Lossy : `Artiste.Titre.Annee.Codec[Bitratekbps]-TAG`, ex. `Demi.Lovato.Title.2025.MP3[320kbps]-NOTAG`.
- Coffret (`is_coffret=True`) : insere `.[COFFRET]` avant `.Annee`.

- [ ] **Step 1: Write the failing test**

```python
# a ajouter a tests/test_name_proposal.py
MUSIC_CONFIG = {"lossless_codecs": ["FLAC", "ALAC", "WAV", "WV", "AIF"]}


def test_propose_music_release_name_lossless_shows_bit_depth_and_sample_rate():
    proposal = propose_music_release_name(
        artist="The Weeknd", title="Blinding Lights", year=2019, codec="FLAC",
        bit_rate_kbps=None, bit_depth=16, sample_rate_hz=44100, team="NOTAG",
        config=MUSIC_CONFIG,
    )
    assert proposal.name == "The.Weeknd.Blinding.Lights.2019.FLAC[16bit.44.1kHz]-NOTAG"


def test_propose_music_release_name_lossy_shows_bitrate():
    # NOTE : la doc officielle C411 ecrit cet exemple precis
    # "Demi.Lovato.It.s.Not.That.Deep...-NOTAG" (apostrophe convertie en
    # point), mais `_normalize_title_text` (deja reutilisee ici, deja
    # validee par un vrai retour de moderation C411 pour la video --
    # "Un Gars, Une Fille" -> "Un.Gars.Une.Fille", PONCTUATION RETIREE,
    # jamais convertie en point) retire l'apostrophe entierement. On
    # suit le comportement DEJA VALIDE de la fonction reutilisee plutot
    # que de copier aveuglement l'orthographe exacte de cet exemple
    # particulier de la doc -- a corriger si un vrai retour de
    # moderation musique montre le contraire.
    proposal = propose_music_release_name(
        artist="Demi Lovato", title="Its Not That Deep", year=2025, codec="MP3",
        bit_rate_kbps=320, bit_depth=None, sample_rate_hz=None, team="NOTAG",
        config=MUSIC_CONFIG,
    )
    assert proposal.name == "Demi.Lovato.Its.Not.That.Deep.2025.MP3[320kbps]-NOTAG"


def test_propose_music_release_name_coffret_inserts_tag():
    proposal = propose_music_release_name(
        artist="Daft Punk", title="Discovery", year=2001, codec="FLAC",
        bit_rate_kbps=None, bit_depth=16, sample_rate_hz=44100, team="TEAM",
        config=MUSIC_CONFIG, is_coffret=True,
    )
    assert proposal.name == "Daft.Punk.Discovery.[COFFRET].2001.FLAC[16bit.44.1kHz]-TEAM"


def test_propose_music_release_name_missing_technical_info_is_a_warning():
    proposal = propose_music_release_name(
        artist="X", title="Y", year=2020, codec="FLAC",
        bit_rate_kbps=None, bit_depth=None, sample_rate_hz=None, team="NOTAG",
        config=MUSIC_CONFIG,
    )
    assert proposal.name is None
    assert any("profondeur" in w or "frequence" in w for w in proposal.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -k propose_music -v`
Expected: FAIL avec `ImportError: cannot import name 'propose_music_release_name'`

- [ ] **Step 3: Write minimal implementation**

Ajouter en fin de `nfogen/name_proposal.py` :

```python
def propose_music_release_name(
    *,
    artist: str,
    title: str,
    year: Optional[int],
    codec: str,
    bit_rate_kbps: Optional[int],
    bit_depth: Optional[int],
    sample_rate_hz: Optional[int],
    team: str,
    config: dict[str, Any],
    is_coffret: bool = False,
) -> NameProposal:
    """Nom de release pour la categorie Musique (audit de conformite C411,
    2026-09-13, doc officielle "Le Nommage de l'upload", section Musique).
    Format structurellement different du gabarit video (suffixe entre
    crochets dont le contenu depend du type de codec) -- fonction dediee,
    pas de reutilisation de `propose_video_release_name`."""
    lossless_codecs = {c.lower() for c in config.get("lossless_codecs", [])}
    is_lossless = codec.lower() in lossless_codecs

    if is_lossless:
        if bit_depth is None or sample_rate_hz is None:
            return NameProposal(
                None, {},
                [
                    "Profondeur (bits) et frequence d'echantillonnage requises "
                    "pour un codec lossless (rules.json -> audio.name_proposal.lossless_codecs)."
                ],
            )
        khz = sample_rate_hz / 1000
        khz_str = f"{khz:.1f}".rstrip("0").rstrip(".") if khz != int(khz) else str(int(khz))
        suffix = f"[{bit_depth}bit.{khz_str}kHz]"
    else:
        if bit_rate_kbps is None:
            return NameProposal(
                None, {}, ["Bitrate (kbps) requis pour un codec lossy."],
            )
        suffix = f"[{bit_rate_kbps}kbps]"

    clean_artist = _normalize_title_text(artist)
    clean_title = _normalize_title_text(title)
    coffret_token = ".[COFFRET]" if is_coffret else ""
    year_str = str(year) if year is not None else ""

    fields = {
        "artist": clean_artist, "title": clean_title, "year": year_str,
        "codec": codec, "suffix": suffix, "team": team,
    }
    name = f"{clean_artist}.{clean_title}{coffret_token}.{year_str}.{codec}{suffix}-{team}"
    name = re.sub(r"\.{2,}", ".", name)
    return NameProposal(name, fields, [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -k propose_music -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full name_proposal suite (non-regression) + ruff + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -v
./.venv/Scripts/python.exe -m ruff check nfogen/name_proposal.py tests/test_name_proposal.py
git add nfogen/name_proposal.py tests/test_name_proposal.py
git commit -m "feat: propose_music_release_name -- nommage dedie categorie Musique"
```

---

### Task 4: Verification en direct des ids d'options Audio C411 + config `rules.json`

**Files:**
- Modify: `nfogen/profiles/c411/rules.json`
- Modify: `nfogen/rules.schema.json` (si `additionalProperties: false` sur `audio`/`tracker.upload`)
- Test: `tests/test_tracker_profile.py`

**Interfaces:**
- Consumes: rien de nouveau (memes accesseurs generiques `tracker_profile.upload_config`/`audio_language_codes`-style deja existants).
- Produces: `rules.json -> audio.name_proposal` (`lossless_codecs`), `rules.json -> tracker.upload.subcategory_id["music"] = 18`, `rules.json -> tracker.upload.category_id` (deja `1`... **ATTENTION** : verifie en direct, la doc `C411_reference.htm` montre `categoryId=3` pour Audio alors que `category_id` actuel du profil est `1` -- **`category_id` doit devenir une map par media_type**, pas un entier fixe, sinon la musique heriterait a tort du categoryId Films. Voir Step 3.).

**Etape manuelle obligatoire AVANT d'ecrire la moindre valeur d'option** :

```bash
KEY=$(grep -oP '"c411_api_key"\s*:\s*"\K[^"]+' /var/lib/nfogen/*.json 2>/dev/null | head -1)
curl -s "https://c411.org/api/categories/18/options" -H "Authorization: Bearer $KEY" | python3 -m json.tool
```

Note le resultat (chaque `optionTypeId` et ses `values`) avant de continuer -- **ne poursuis PAS cette tache sans ce resultat en main**. Adapte les valeurs `lang_option_id`/`lang_values`/`format_option_id`/`format_values` ci-dessous en fonction du VRAI retour (les noms de variables ci-dessous sont indicatifs, a renommer selon ce que l'API retourne reellement -- ex. si le type 15 s'appelle "Format" et le 16 "Qualite", nomme les cles de `rules.json` en consequence).

- [ ] **Step 1: Write the failing test**

```python
# a ajouter a tests/test_tracker_profile.py
def test_c411_upload_category_id_is_per_media_type():
    config = tracker_profile.upload_config("c411")
    assert config["category_id"]["movie"] == 1
    assert config["category_id"]["series"] == 1
    assert config["category_id"]["music"] == 3


def test_c411_music_subcategory_id():
    config = tracker_profile.upload_config("c411")
    assert config["subcategory_id"]["music"] == 18
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tracker_profile.py -k "category_id_is_per_media_type or music_subcategory" -v`
Expected: FAIL (`category_id` est actuellement un entier, pas une map ; `subcategory_id["music"]` absent)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/profiles/c411/rules.json`, section `tracker.upload` :
- Remplace `"category_id": 1` par `"category_id": {"movie": 1, "series": 1, "music": 3}`.
- Ajoute `"music": 18` a `"subcategory_id"`.
- Ajoute une nouvelle section `audio` au meme niveau que `video` :

```json
"audio": {
  "name_proposal": {
    "lossless_codecs": ["FLAC", "ALAC", "WAV", "WV", "AIF"]
  }
}
```

Modifie `nfogen/c411_upload_options.py::build_category_ids()` pour lire `category_id` comme une map indexee par `media_type` (meme repli que `subcategory_id` -- `config.get("category_id", {}).get(media_type)` au lieu de `config.get("category_id")`). **Ce changement casse potentiellement l'usage actuel pour movie/series** -- verifie ET adapte les tests existants de `tests/test_c411_upload_options.py` qui testent `build_category_ids` (ils passaient jusque-la un entier fixe ; adapte le mapping de test `UPLOAD_RULES` de ce fichier en consequence, meme changement de forme).

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tracker_profile.py tests/test_c411_upload_options.py -v`
Expected: PASS, zero regression sur les tests movie/series existants (deja adaptes a l'etape 3)

- [ ] **Step 5: Ruff + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check nfogen/c411_upload_options.py nfogen/profiles/c411/rules.json tests/test_tracker_profile.py tests/test_c411_upload_options.py
git add nfogen/profiles/c411/rules.json nfogen/c411_upload_options.py tests/test_tracker_profile.py tests/test_c411_upload_options.py
git commit -m "feat: categoryId par media_type + configuration Audio (C411, Musique)"
```

---

### Task 5: Description BBCode parametree par categorie + template Audio

**Files:**
- Modify: `nfogen/upload_description.py`
- Create: `nfogen/profiles/c411/templates/upload_description_audio.j2`
- Test: `tests/test_upload_description.py`

**Interfaces:**
- Consumes: `render.render_template(profile, category, context)` (existant, generique -- charge `<profile>/<category>.j2`, aucun changement necessaire dans `render.py`).
- Produces: `render_upload_description(profile: str, context: dict[str, Any], *, category: str = "video") -> str` (signature etendue, retro-compatible : tout appel existant sans `category` continue de charger `upload_description.j2` comme avant).

- [ ] **Step 1: Write the failing test**

```python
# a ajouter a tests/test_upload_description.py
MUSIC_CONTEXT = {
    "title": "Daft Punk - Random Access Memories", "artist": "Daft Punk",
    "album": "Random Access Memories", "genre": "Electronic", "year": "2013",
    "codec": "FLAC", "format": "FLAC", "overall_bit_rate": "1000 kb/s",
    "channel": "2 channels", "total_size_dec": "1.2 GB",
    "tracklist": [{"index": 1, "name": "Daft Punk - Give Life Back to Music", "duration": 275}],
}


def test_renders_audio_description_with_artist_album_and_tracklist():
    out = render_upload_description("c411", MUSIC_CONTEXT, category="audio")
    assert "Daft Punk" in out
    assert "Random Access Memories" in out
    assert "Give Life Back to Music" in out


def test_video_description_unaffected_by_new_category_param():
    out = render_upload_description("c411", FULL_CONTEXT)  # appel existant, sans category
    assert "Dom Cobb est un voleur experimente" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_upload_description.py -k "audio_description or video_description_unaffected" -v`
Expected: FAIL avec `TypeError: render_upload_description() got an unexpected keyword argument 'category'`

- [ ] **Step 3: Write minimal implementation**

```python
# nfogen/upload_description.py
def render_upload_description(profile: str, context: dict[str, Any], *, category: str = "video") -> str:
    """Rend le template de description BBCode pour la categorie donnee.
    Audit de conformite C411, 2026-09-13 : le template `upload_description.j2`
    d'origine est 100% video (codec/resolution/sous-titres) -- generalise
    par categorie (`upload_description_<categorie>.j2`) pour la Musique et
    les futures categories, sans jamais toucher au comportement video
    existant (`category="video"` par defaut, charge toujours
    `upload_description.j2` tel quel, aucun renommage de fichier)."""
    template_name = "upload_description" if category == "video" else f"upload_description_{category}"
    return render.render_template(profile, template_name, context)
```

Nouveau template `nfogen/profiles/c411/templates/upload_description_audio.j2` :

```jinja
[center][size=150]{{ title }}[/size][/center]

[b][size=120]Informations[/size][/b]
[b]Artiste :[/b] {{ artist }}
[b]Album :[/b] {{ album }}
{% if genre %}[b]Genre :[/b] {{ genre }}
{% endif %}{% if year %}[b]Annee :[/b] {{ year }}
{% endif %}
[b][size=120]Details techniques[/size][/b]
[list]
[*]Codec : {{ codec }}
{% if format %}[*]Format : {{ format }}
{% endif %}{% if overall_bit_rate %}[*]Debit : {{ overall_bit_rate }}
{% endif %}{% if channel %}[*]Canaux : {{ channel }}
{% endif %}{% if total_size_dec %}[*]Taille totale : {{ total_size_dec }}
{% endif %}[/list]
{% if tracklist %}
[b][size=120]Tracklist[/size][/b]
[list=1]
{% for t in tracklist %}[*]{{ t.name }}
{% endfor %}[/list]
{% endif %}

[i]Genere par nfogen.nfo[/i]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_upload_description.py -v`
Expected: PASS, tous les tests existants (video) restent verts

- [ ] **Step 5: Trouver et mettre a jour les appelants existants + ruff + commit**

```bash
grep -rn "render_upload_description(" nfogen/upload_prep.py
```

Verifie que l'appel existant dans `upload_prep.py` (video) continue de fonctionner sans changement (il n'a pas besoin de passer `category`, le defaut `"video"` couvre son cas).

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check nfogen/upload_description.py tests/test_upload_description.py
git add nfogen/upload_description.py nfogen/profiles/c411/templates/upload_description_audio.j2 tests/test_upload_description.py
git commit -m "feat: description BBCode parametree par categorie + template Audio"
```

---

### Task 6: Pipeline complet de bout en bout (extraction -> nom -> NFO -> description)

**Files:**
- Create: `nfogen/music_upload_prep.py`
- Test: `tests/test_music_upload_prep.py`

**Interfaces:**
- Consumes: `extract_album` (`nfogen/extract.py`, existant), `propose_music_release_name` (Task 3), `render_upload_description(..., category="audio")` (Task 5), `profile_store.read_profile` (existant, deja utilise par `upload_prep.py` pour charger `rules.json`/templates), `render.render_template` (existant, pour le NFO `audio.j2`).
- Produces: `preview_music_upload(source_path: str, profile: str = "c411", team: str = "NOTAG", is_coffret: bool = False) -> dict[str, Any]` -- renvoie `{"release_name": str | None, "warnings": list[str], "nfo_text": str, "description": str}`. Fonction PURE de previsualisation (aucune ecriture disque, aucun appel reseau) -- symetrique du role de `upload_prep.preview_upload()` pour la video, mais scope reduit ici a la previsualisation (staging/torrent/upload C411 pour la musique restent un sous-projet de suivi, voir Global Constraints).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_music_upload_prep.py
from __future__ import annotations

from pathlib import Path

import pytest

from nfogen.music_upload_prep import preview_music_upload


def test_preview_music_upload_builds_name_nfo_and_description(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", "")
    album_dir = tmp_path / "Daft Punk - Random Access Memories"
    album_dir.mkdir()
    # Fichier audio minimal factice -- extract_album degrade proprement
    # (ValueError attrape) si MediaInfo ne peut rien en tirer ; ce test
    # utilise donc un monkeypatch de extract_album plutot qu'un vrai
    # fichier FLAC (non disponible en CI).
    fake_metadata = {
        "artist": "Daft Punk", "album": "Random Access Memories", "genre": "Electronic",
        "year": "2013", "codec": "FLAC", "format": "FLAC", "overall_bit_rate": "1000 kb/s",
        "bit_rate_mode": "VBR", "channel": "2 channels / 44.1 kHz / 16 bits", "quality": "Lossless",
        "writing_library": "undefined", "encoding_settings": "undefined",
        "tracklist": [{"index": 1, "name": "Daft Punk - Give Life Back to Music", "title": "Give Life Back to Music", "artist": "Daft Punk", "size": 50000000, "duration": 275}],
        "total_size": 987654321, "total_duration": 3594, "playing_time": "59:54",
    }
    import nfogen.music_upload_prep as mod
    monkeypatch.setattr(mod, "extract_album", lambda path: fake_metadata)

    result = preview_music_upload(str(album_dir), profile="c411", team="NOTAG")

    assert result["release_name"] is not None
    assert result["release_name"].startswith("Daft.Punk.Random.Access.Memories.2013.FLAC")
    assert "Daft Punk" in result["nfo_text"]
    assert "Random Access Memories" in result["description"]
    assert result["warnings"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_music_upload_prep.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.music_upload_prep'`

- [ ] **Step 3: Write minimal implementation**

```python
# nfogen/music_upload_prep.py
"""Previsualisation d'un upload Musique (audit de conformite C411,
2026-09-13, sous-projet Musique) : assemble nom de release, NFO et
description BBCode a partir d'un dossier d'album local, SANS aucune
ecriture disque ni appel reseau -- symetrique de la previsualisation
video (`upload_prep.preview_upload`), mais scope reduit au premier jet
(staging/torrent/upload C411 restent un sous-projet de suivi, voir
docs/superpowers/plans/2026-09-13-music-category-lidarr.md, Global
Constraints)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .extract import extract_album
from .name_proposal import propose_music_release_name
from .profile_store import read_profile
from .render import render_template
from .upload_description import render_upload_description


def preview_music_upload(
    source_path: str,
    profile: str = "c411",
    team: str = "NOTAG",
    is_coffret: bool = False,
) -> dict[str, Any]:
    metadata = extract_album(Path(source_path))
    config = read_profile(profile)["rules"].get("audio", {}).get("name_proposal", {})

    bit_rate_kbps = None
    bit_depth = None
    sample_rate_hz = None
    channel_text = metadata.get("channel", "")
    # `extract_album` renvoie le champ "channel" tel que fourni par
    # MediaInfo (ex. "2 channels / 44.1 kHz / 16 bits") -- pas encore
    # decompose en champs individuels, on les extrait ici plutot que de
    # modifier `extract_album` (module partage avec la CLI existante,
    # perimetre de ce sous-projet limite a la Musique automatisee).
    import re

    khz_match = re.search(r"([\d.]+)\s*kHz", channel_text)
    if khz_match:
        sample_rate_hz = int(float(khz_match.group(1)) * 1000)
    bits_match = re.search(r"(\d+)\s*bits?", channel_text)
    if bits_match:
        bit_depth = int(bits_match.group(1))
    kbps_match = re.search(r"([\d.]+)\s*kb/s", metadata.get("overall_bit_rate", ""))
    if kbps_match:
        bit_rate_kbps = round(float(kbps_match.group(1)))

    proposal = propose_music_release_name(
        artist=metadata.get("artist", ""), title=metadata.get("album", ""),
        year=int(metadata["year"]) if metadata.get("year") else None,
        codec=metadata.get("codec", ""), bit_rate_kbps=bit_rate_kbps,
        bit_depth=bit_depth, sample_rate_hz=sample_rate_hz, team=team,
        config=config, is_coffret=is_coffret,
    )

    nfo_text = render_template(profile, "audio", metadata)
    description = render_upload_description(
        profile,
        {
            "title": f"{metadata.get('artist', '')} - {metadata.get('album', '')}",
            "artist": metadata.get("artist", ""), "album": metadata.get("album", ""),
            "genre": metadata.get("genre", ""), "year": metadata.get("year", ""),
            "codec": metadata.get("codec", ""), "format": metadata.get("format", ""),
            "overall_bit_rate": metadata.get("overall_bit_rate", ""),
            "channel": metadata.get("channel", ""),
            "total_size_dec": metadata.get("total_size", ""),
            "tracklist": metadata.get("tracklist", []),
        },
        category="audio",
    )

    return {
        "release_name": proposal.name, "warnings": proposal.warnings,
        "nfo_text": nfo_text, "description": description,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_music_upload_prep.py -v`
Expected: PASS

- [ ] **Step 5: Suite complete + ruff + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check nfogen/music_upload_prep.py tests/test_music_upload_prep.py
git add nfogen/music_upload_prep.py tests/test_music_upload_prep.py
git commit -m "feat: pipeline de previsualisation Musique de bout en bout"
```

---

## Suite de ce sous-projet (hors ce plan, YAGNI)

Une fois ce pipeline valide (`preview_music_upload` teste contre un VRAI album local, resultat inspecte manuellement par l'utilisateur) :
- Staging/torrent/upload C411 reel pour la musique (reutilise `file_staging.py`/`torrent_builder.py`/`C411UploadClient`, deja generiques -- juste besoin de brancher `preview_music_upload` dessus, meme role que `upload_prep.commit_upload`/`send_to_tracker` pour la video).
- Integration dans `run_gapscan()` (incremental/selection) une fois `scan_album` valide isolement.
- UI frontend (Bibliotheque + Preparer l'upload pour la musique).
