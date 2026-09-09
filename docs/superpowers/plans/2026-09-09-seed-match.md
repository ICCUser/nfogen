# Seed d'une release C411 existante — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pour un titre `COVERED` dont le fichier local correspond
exactement à une release C411 existante, télécharger son `.torrent`,
l'ajouter à qBittorrent en pause pointé sur le fichier local, vérifier
réellement les pièces, reprendre le seed seulement si la vérification
confirme une correspondance parfaite.

**Architecture:** Nouveau module pur `nfogen/seed_match.py` (détection
de correspondance) ; `TorznabClient.download()` (télécharge via
`t=get`, déjà confirmé fonctionnel) ; `QBittorrentClient` gagne
`paused`/`tags` sur `add_torrent()` + un nouveau `resume()` ; nouveau
job de fond `nfogen/seed_match_job_runner.py` (même patron que
`integrity_job_runner.py`) ; 3 nouveaux endpoints HTTP ; bouton "Seed
possible" dans la Bibliothèque.

**Tech Stack:** Python (httpx déjà utilisé, `torf` déjà une dépendance
pour lire un `.torrent`), FastAPI, React/TypeScript.

**Spec:** [docs/superpowers/specs/2026-09-09-seed-match-design.md](../specs/2026-09-09-seed-match-design.md)

## Global Constraints

- La comparaison de correspondance porte UNIQUEMENT sur ce qui est
  parsable depuis un nom de release texte (résolution/source/codec
  vidéo/langues via `quality.parse_release_name`, déjà utilisé) + tag
  d'équipe (`name_proposal.extract_team_tag`) + taille exacte en
  octets — **jamais** le codec audio/canaux (non parsé depuis un nom
  de fichier dans ce projet).
- Zéro ou plusieurs candidats au pré-filtre ⇒ pas de correspondance
  proposée, jamais un choix deviné.
- Le torrent est TOUJOURS ajouté à qBittorrent **en pause**
  (`paused=True`) — jamais de reprise du seed avant que qBittorrent
  ait lui-même vérifié les pièces (`progress == 1.0`).
- Une vérification qui échoue (`progress < 1.0`, `missingFiles`,
  `error`) ⇒ le torrent reste en pause, **jamais retiré
  automatiquement** de qBittorrent, jamais de reprise.
- Tout torrent ajouté par nfogen (ce sous-projet ET l'auto-seed
  existant après upload direct) porte le tag qBittorrent `"NFOGEN"`.
- `key`/`guid` fournis par le client sont revalidés contre
  `gapscan_runner.results()` avant tout téléchargement — même
  principe que l'audit sécurité du 2026-09-09
  (`_validate_known_source_paths`).
- ⚠️ Les chaînes d'état qBittorrent (`pausedUP`, `queuedUP`,
  `checkedUP`, `missingFiles`, `error`) ne sont PAS vérifiées contre
  une instance réelle dans ce plan — la Task 5 doit le signaler
  explicitement à l'utilisateur avant integration finale (même
  prudence que le N+1 Sonarr du 2026-09-09, qui a cassé la production
  faute de vérification réelle).

---

## Task 1 : `nfogen/seed_match.py` — détection de correspondance

**Files:**
- Create: `nfogen/seed_match.py`
- Test: `tests/test_seed_match.py`

**Interfaces:**
- Consumes: `quality.ReleaseQuality` (existant), `name_proposal.extract_team_tag` (existant), `torznab_client.TorznabRelease` (existant, `.quality`/`.size`/`.guid`/`.title`).
- Produces: `SeedMatchCandidate(guid: str, release_name: str)` (dataclass), `find_seed_match(local_quality: ReleaseQuality, local_team: Optional[str], local_size: int, matches: list[TorznabRelease]) -> Optional[SeedMatchCandidate]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests de nfogen.seed_match (detection de correspondance exacte avec
une release C411 existante, en vue d'un seed sans re-upload)."""
from __future__ import annotations

from nfogen.quality import ReleaseQuality
from nfogen.seed_match import SeedMatchCandidate, find_seed_match
from nfogen.torznab_client import TorznabRelease


def _release(guid="guid-1", title="Movie.2020.1080p.BluRay.x264-TEAM", size=1_000_000):
    return TorznabRelease(title=title, guid=guid, link="https://c411.org/torrents/x", size=size)


LOCAL_QUALITY = ReleaseQuality(
    raw="Movie.2020.1080p.BluRay.x264-TEAM", resolution=1080, source="BLURAY",
    codec="X264", languages=["VFF"], multi=False, pure=False,
)


def test_finds_a_single_exact_candidate():
    release = _release()
    candidate = find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release])
    assert candidate == SeedMatchCandidate(guid="guid-1", release_name=release.title)


def test_no_match_when_size_differs():
    release = _release(size=2_000_000)
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release]) is None


def test_no_match_when_team_differs():
    release = _release(title="Movie.2020.1080p.BluRay.x264-OTHER")
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release]) is None


def test_no_match_when_resolution_differs():
    release = _release(title="Movie.2020.2160p.BluRay.x264-TEAM")
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release]) is None


def test_no_match_when_local_team_is_none():
    release = _release()
    assert find_seed_match(LOCAL_QUALITY, None, 1_000_000, [release]) is None


def test_no_match_when_ambiguous_multiple_candidates():
    release_a = _release(guid="guid-a")
    release_b = _release(guid="guid-b")
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release_a, release_b]) is None


def test_no_match_when_no_releases():
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, []) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_seed_match.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.seed_match'`

- [ ] **Step 3: Write the implementation**

```python
"""Detection d'une correspondance EXACTE entre un fichier local
(status GapStatus.COVERED) et UNE release C411 deja existante -- si
trouvee, permet de recuperer/seeder ce torrent au lieu de re-uploader
un fichier deja present a l'identique sur le tracker (retour
utilisateur, 2026-09-09).

Portee volontairement limitee a ce qui est parsable depuis un nom de
release TEXTE (resolution/source/codec video/langues, voir
quality.parse_release_name -- deja utilise pour TorznabRelease.quality)
+ tag d'equipe (name_proposal.extract_team_tag) + taille exacte en
octets. Le codec/canaux AUDIO ne sont PAS compares ici (jamais parses
depuis un simple nom de fichier dans ce projet) -- la verification
reelle des pieces par qBittorrent (voir seed_match_job_runner.py) reste
la seule preuve definitive d'une correspondance parfaite."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .name_proposal import extract_team_tag
from .quality import ReleaseQuality
from .torznab_client import TorznabRelease


@dataclass
class SeedMatchCandidate:
    guid: str
    release_name: str


def _quality_matches(a: ReleaseQuality, b: ReleaseQuality) -> bool:
    return (
        a.resolution == b.resolution
        and a.source == b.source
        and a.codec == b.codec
        and a.languages == b.languages
        and a.multi == b.multi
    )


def find_seed_match(
    local_quality: ReleaseQuality,
    local_team: Optional[str],
    local_size: int,
    matches: list[TorznabRelease],
) -> Optional[SeedMatchCandidate]:
    """`local_team` absent (aucun tag d'equipe detecte localement) ->
    jamais de correspondance proposee, trop peu de signal pour etre
    surs. Zero ou plusieurs candidats -> None, jamais un choix devine."""
    if local_team is None:
        return None
    candidates = [
        m for m in matches
        if m.size == local_size
        and extract_team_tag(m.title) == local_team
        and _quality_matches(local_quality, m.quality)
    ]
    if len(candidates) != 1:
        return None
    winner = candidates[0]
    return SeedMatchCandidate(guid=winner.guid, release_name=winner.title)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_seed_match.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add nfogen/seed_match.py tests/test_seed_match.py
git commit -m "feat: seed_match.find_seed_match -- correspondance exacte avec une release C411"
```

---

## Task 2 : `gapscan_library.py` — `LibraryItem.seed_match` + `find_result_by_key`

**Files:**
- Modify: `nfogen/gapscan_library.py`
- Test: `tests/test_gapscan_library.py`

**Interfaces:**
- Consumes: `seed_match.find_seed_match()` (Task 1).
- Produces: `LibraryItem.seed_match: Optional[dict[str, str]]` (`{"guid": ..., "release_name": ...}` ou `None`), `find_result_by_key(key: str, results: list[GapResult]) -> Optional[GapResult]` (fonction publique, réutilisée par l'API pour revalider un `key` client, voir Task 6).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_gapscan_library.py` :

```python
from nfogen.gapscan_library import find_result_by_key
from nfogen.gapscan import GapResult, GapStatus
from nfogen.quality import ReleaseQuality
from nfogen.torznab_client import TorznabRelease


def _movie_gap_result(status, c411_matches=None):
    return GapResult(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt0133093", tmdb_id="603", tvdb_id=None, status=status,
        local_quality=ReleaseQuality(raw="", resolution=1080, source="BLURAY", codec="X264", languages=["VFF"]),
        c411_matches=c411_matches or [],
    )


def test_gapscan_library_exposes_seed_match_when_exact_candidate_found(tmp_path, monkeypatch):
    from nfogen import gapscan_library

    local_file = tmp_path / "Matrix.1999.1080p.BluRay.x264-TEAM.mkv"
    local_file.write_bytes(b"x" * 1_000_000)

    release = TorznabRelease(
        title="Matrix.1999.1080p.BluRay.x264-TEAM", guid="guid-1",
        link="https://c411.org/torrents/x", size=1_000_000,
    )
    previous = _movie_gap_result(GapStatus.COVERED, c411_matches=[release])

    class FakeRadarr:
        def list_movie_files(self):
            return [_FakeMovie()]

    class _FakeMovie:
        movie_id = 42
        title = "Matrix"
        year = 1999
        imdb_id = "tt0133093"
        tmdb_id = 603
        scene_name = "Matrix.1999.1080p.BluRay.x264-TEAM"
        best_resolution = 1080
        language_names = ["French"]
        genres = []
        added_at = None

    monkeypatch.setattr(
        "nfogen.gapscan_library.path_mapping.resolve_and_validate",
        lambda paths, mappings: ([str(local_file)], True, None),
    )

    items = gapscan_library.list_library(radarr=FakeRadarr(), previous_results=[previous])
    assert items[0].seed_match == {"guid": "guid-1", "release_name": "Matrix.1999.1080p.BluRay.x264-TEAM"}


def test_gapscan_library_seed_match_none_when_not_covered(tmp_path, monkeypatch):
    from nfogen import gapscan_library

    local_file = tmp_path / "Matrix.1999.1080p.BluRay.x264-TEAM.mkv"
    local_file.write_bytes(b"x" * 1_000_000)
    previous = _movie_gap_result(GapStatus.ABSENT, c411_matches=[])

    class FakeRadarr:
        def list_movie_files(self):
            return [_FakeMovie2()]

    class _FakeMovie2:
        movie_id = 42
        title = "Matrix"
        year = 1999
        imdb_id = "tt0133093"
        tmdb_id = 603
        scene_name = "Matrix.1999.1080p.BluRay.x264-TEAM"
        best_resolution = 1080
        language_names = ["French"]
        genres = []
        added_at = None

    monkeypatch.setattr(
        "nfogen.gapscan_library.path_mapping.resolve_and_validate",
        lambda paths, mappings: ([str(local_file)], True, None),
    )

    items = gapscan_library.list_library(radarr=FakeRadarr(), previous_results=[previous])
    assert items[0].seed_match is None


def test_find_result_by_key_returns_matching_result():
    result = _movie_gap_result(GapStatus.COVERED)
    key = upload_history_store.key_str(movie_key("tt0133093", "603", "Matrix", 1999))
    assert find_result_by_key(key, [result]) is result


def test_find_result_by_key_returns_none_when_absent():
    assert find_result_by_key("does-not-exist", []) is None
```

Ajouter en tête du fichier de test (si absent) :
```python
from nfogen import upload_history_store
from nfogen.gapscan import movie_key
```

**Note** : ce test suppose que `list_library()` résout `local_paths`
via un module `path_mapping` importé dans `gapscan_library.py` — **si
la résolution des chemins se fait ailleurs** (ex. déjà résolue en
amont, avant l'appel à `list_library()`), adapter le mock au véritable
point d'entrée : le principe à tester reste "un `LibraryItem`
`COVERED` avec un chemin local RÉSOLU et un candidat exact unique
expose `seed_match`".

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gapscan_library.py -v -k seed_match`
Expected: FAIL — `LibraryItem` n'a pas d'attribut `seed_match`, `find_result_by_key` inconnu

- [ ] **Step 3: Write the implementation**

Dans `nfogen/gapscan_library.py`, ajouter aux imports :

```python
import os

from .seed_match import find_seed_match
```

Ajouter le champ à `LibraryItem` (à la suite de `team`) :

```python
    # Present uniquement si status == "covered" ET une SEULE release
    # C411 correspond exactement (taille + team + resolution/source/
    # codec/langues, voir seed_match.find_seed_match) -- permet de
    # proposer un seed sans re-upload (retour utilisateur, 2026-09-09).
    seed_match: Optional[dict[str, str]] = None
```

Ajouter la fonction (à la suite de `_previous_key`) :

```python
def find_result_by_key(key: str, results: list[GapResult]) -> Optional[GapResult]:
    """Retrouve le GapResult correspondant a `key` (LibraryItem.key)
    parmi des resultats de scan connus -- reutilise le meme calcul que
    list_library() (_previous_key), pour que le serveur puisse
    revalider un `key`/`guid` fournis par le client contre un scan
    reellement effectue (voir seed_match_job_runner.py, audit securite
    2026-09-09)."""
    return next((r for r in results if _previous_key(r) == key), None)


def _compute_seed_match(
    previous: Optional[GapResult], local_quality: ReleaseQuality, team: Optional[str],
    local_paths: list[str], path_resolved: bool,
) -> Optional[dict[str, str]]:
    if previous is None or previous.status != GapStatus.COVERED:
        return None
    if not path_resolved or not local_paths:
        return None
    try:
        local_size = os.path.getsize(local_paths[0])
    except OSError:
        return None
    candidate = find_seed_match(local_quality, team, local_size, previous.c411_matches)
    if candidate is None:
        return None
    return {"guid": candidate.guid, "release_name": candidate.release_name}
```

Ajouter `GapStatus` à l'import existant de `.gapscan` :

```python
from .gapscan import GapResult, GapStatus, genre_of, movie_key, series_key
```

Dans les DEUX branches de `list_library()` (film et série), extraire
`local_quality` dans une variable avant de construire le `LibraryItem`
(actuellement calculée inline via `build_quality(...)`), puis passer
`seed_match=_compute_seed_match(...)` :

Branche film — remplacer :
```python
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
```
par :
```python
            movie_quality = build_quality(
                movie.scene_name or movie.title,
                fallback_resolution=movie.best_resolution,
                fallback_language_names=movie.language_names,
            )
            movie_team = extract_team_tag(movie.scene_name or movie.title)
            items.append(
                LibraryItem(
                    media_type="movie", title=movie.title, year=movie.year, season_number=None,
                    imdb_id=movie.imdb_id, tvdb_id=None, tmdb_id=tmdb_id,
                    genres=movie.genres, added_at=movie.added_at,
                    local_quality=movie_quality,
```

Puis, dans le même bloc `LibraryItem(...)`, remplacer
`team=extract_team_tag(movie.scene_name or movie.title),` par
`team=movie_team,` et ajouter juste après :
```python
                    seed_match=_compute_seed_match(
                        previous, movie_quality, movie_team,
                        previous.local_paths if previous else [],
                        previous.path_resolved if previous else False,
                    ),
```

Répéter EXACTEMENT le même principe pour la branche série (`season`) :
extraire `season_quality`/`season_team` avant le `LibraryItem(...)`,
remplacer `team=extract_team_tag(season.scene_name or season.title),`
par `team=season_team,`, ajouter le même appel à
`_compute_seed_match(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan_library.py -v`
Expected: PASS (toutes, y compris les 4 nouvelles)

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_library.py tests/test_gapscan_library.py
git commit -m "feat: LibraryItem.seed_match + find_result_by_key"
```

---

## Task 3 : `TorznabClient.download()`

**Files:**
- Modify: `nfogen/torznab_client.py`
- Test: `tests/test_torznab_client.py` (ou `tests/test_c411_client.py` si c'est le nom réel du fichier de test existant — vérifier avec `ls tests/ | grep torznab` avant d'écrire, et utiliser le fichier trouvé)

**Interfaces:**
- Consumes: `TorznabClient._throttle()`/`_parse_retry_after()`/`_redact()` (existants).
- Produces: `TorznabClient.download(guid: str) -> bytes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_download_returns_raw_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["t"] == "get"
        assert request.url.params["id"] == "guid-1"
        assert request.url.params["apikey"] == "test-key"
        return httpx.Response(200, content=b"d8:announce...", headers={"content-type": "application/x-bittorrent"})

    client = TorznabClient("test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.download("guid-1") == b"d8:announce..."


def test_download_retries_once_after_429():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, content=b"torrent-bytes")

    client = TorznabClient("test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client._sleep = lambda seconds: None
    assert client.download("guid-1") == b"torrent-bytes"
    assert len(calls) == 2


def test_download_wraps_http_errors_and_redacts_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = TorznabClient("secret-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TorznabError) as exc_info:
        client.download("guid-1")
    assert "secret-key" not in str(exc_info.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_torznab_client.py -v -k download`
Expected: FAIL — `AttributeError: 'TorznabClient' object has no attribute 'download'`

- [ ] **Step 3: Write the implementation**

Dans `nfogen/torznab_client.py`, ajouter à `TorznabClient` (à la suite
de `search_tv`) :

```python
    def download(self, guid: str) -> bytes:
        """`t=get&id={guid}` -- telecharge le .torrent d'une release
        EXISTANTE sur C411 (pas necessairement uploadee par
        l'utilisateur) : confirme fonctionnel en conditions reelles
        (2026-09-09) avec la seule cle API. DISTINCT du telechargement
        du torrent RE-SIGNE de son propre upload apres moderation, qui
        lui exige une session navigateur (voir docstring de module de
        qbittorrent_client.py) -- deux endpoints differents. Meme
        throttle/retry-apres-429 que _search()."""
        for attempt in range(2):
            self._throttle()
            query = {"t": "get", "id": guid, "apikey": self._api_key}
            try:
                response = self._client.get(self._base_url, params=query)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt == 0:
                    self._sleep(self._parse_retry_after(exc.response))
                    continue
                raise TorznabError(
                    f"Téléchargement C411 échoué ({guid}) : {self._redact(exc)}"
                ) from exc
            except httpx.HTTPError as exc:
                raise TorznabError(f"Téléchargement C411 échoué ({guid}) : {self._redact(exc)}") from exc
            return response.content
        raise AssertionError("unreachable")  # la boucle retourne ou leve dans tous les cas
```

Mettre à jour le docstring de module (en tête du fichier) qui affirme
actuellement "Ce client ne telecharge [...] aucun contenu" — devenu
inexact :

```python
Ce client liste des metadonnees de releases deja presentes sur le
tracker (recherche), et peut desormais TELECHARGER le .torrent d'une
release existante via `download()` (`t=get`, retour utilisateur
2026-09-09 -- seed d'un fichier local deja identique, sans re-upload).
Toujours en lecture seule cote tracker : aucune ecriture, aucune
modification d'un torrent existant.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_torznab_client.py -v`
Expected: PASS (toutes, y compris les 3 nouvelles)

- [ ] **Step 5: Commit**

```bash
git add nfogen/torznab_client.py tests/test_torznab_client.py
git commit -m "feat: TorznabClient.download -- t=get, telecharge une release existante"
```

---

## Task 4 : `QBittorrentClient` — `paused`/`tags` + `resume()`

**Files:**
- Modify: `nfogen/qbittorrent_client.py`
- Modify: `nfogen/upload_prep.py`
- Modify: `tests/test_qbittorrent_client.py`
- Modify: `tests/test_upload_prep.py`

**Interfaces:**
- Produces: `QBittorrentClient.add_torrent(torrent_bytes, save_path, filename="release.torrent", *, paused: bool = False, tags: Optional[str] = None) -> None`, `QBittorrentClient.resume(torrent_hash: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_qbittorrent_client.py` :

```python
def test_add_torrent_sends_paused_and_tags_when_given():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        captured["content"] = request.content
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.add_torrent(b"x", "/data/staging", paused=True, tags="NFOGEN")

    assert b"paused" in captured["content"]
    assert b"true" in captured["content"]
    assert b"NFOGEN" in captured["content"]


def test_add_torrent_omits_paused_and_tags_by_default():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        captured["content"] = request.content
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.add_torrent(b"x", "/data/staging")

    assert b"paused" not in captured["content"]
    assert b"tags" not in captured["content"]


def test_resume_logs_in_then_posts_hash():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.content))
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, text="")

    client = _client(handler)
    client.resume("abc123")

    assert calls[0][0] == "/api/v2/auth/login"
    assert calls[1][0] == "/api/v2/torrents/resume"
    assert b"abc123" in calls[1][1]


def test_resume_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(500, text="boom")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[Rr]eprise"):
        client.resume("abc123")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_qbittorrent_client.py -v -k "paused or resume"`
Expected: FAIL — `add_torrent()` ne connait pas `paused`/`tags`, `resume` inconnu

- [ ] **Step 3: Write the implementation**

Dans `nfogen/qbittorrent_client.py`, remplacer `add_torrent` :

```python
    def add_torrent(
        self, torrent_bytes: bytes, save_path: str, filename: str = "release.torrent",
        *, paused: bool = False, tags: Optional[str] = None,
    ) -> None:
        """Ajoute un .torrent DEJA telecharge (voir docstring du module),
        pointe sur `save_path` -- le contenu doit deja s'y trouver.
        `paused` (retour utilisateur, 2026-09-09 -- seed_match_job_runner.py) :
        ajoute sans demarrer, pour laisser qBittorrent verifier les
        pieces avant toute decision de seed reelle. `tags` : etiquette
        qBittorrent (ex. "NFOGEN") -- distingue les torrents geres par
        nfogen des autres dans son interface. Leve `QBittorrentError` en
        cas d'echec (connexion, authentification, ou refus par qBittorrent)."""
        if not self._logged_in:
            self._login()
        data: dict[str, str] = {"savepath": save_path}
        if paused:
            data["paused"] = "true"
        if tags:
            data["tags"] = tags
        try:
            response = self._client.post(
                f"{self._base_url}/api/v2/torrents/add",
                files={"torrents": (filename, torrent_bytes, "application/x-bittorrent")},
                data=data,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Ajout du torrent à qBittorrent échoué : {exc}") from exc
        if response.text.strip() != "Ok.":
            raise QBittorrentError(f"qBittorrent a refusé le torrent : {response.text.strip()}")

    def resume(self, torrent_hash: str) -> None:
        """`POST /api/v2/torrents/resume` (hashes=<hash>) -- reprend un
        torrent ajoute en pause (voir seed_match_job_runner.py). Ne
        verifie pas le corps de la reponse (qBittorrent renvoie
        generalement un corps vide sur ce endpoint, contrairement a
        add_torrent) -- seul un code HTTP non 2xx est traite comme une
        erreur."""
        if not self._logged_in:
            self._login()
        try:
            response = self._client.post(
                f"{self._base_url}/api/v2/torrents/resume", data={"hashes": torrent_hash},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Reprise du torrent {torrent_hash} échouée : {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_qbittorrent_client.py -v`
Expected: PASS (toutes)

- [ ] **Step 5: Ajouter le tag "NFOGEN" à l'auto-seed existant**

Dans `nfogen/upload_prep.py`, la seule ligne `qb.add_torrent(...)`
existante (recherchée avec `grep -n "add_torrent(" nfogen/upload_prep.py`) :

```python
                qb.add_torrent(
                    torrent_bytes, str(Path(staged_path).parent), filename=f"{release_name}.torrent",
                )
```

devient :

```python
                qb.add_torrent(
                    torrent_bytes, str(Path(staged_path).parent), filename=f"{release_name}.torrent",
                    tags="NFOGEN",
                )
```

Dans `tests/test_upload_prep.py`, les DEUX classes fake qui définissent
`def add_torrent(self, torrent_bytes, save_path, filename):` (rechercher
avec `grep -n "def add_torrent" tests/test_upload_prep.py` — une dans
`FakeQBittorrentClient`, une dans `FailingQBittorrentClient`) deviennent :

```python
        def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
```

(`**kwargs` absorbe `tags=` sans que ces deux tests aient besoin de
l'asserter spécifiquement — non couvert par ce sous-projet, déjà
suffisamment testé par les nouveaux tests `qbittorrent_client.py`
ci-dessus).

- [ ] **Step 6: Run the full backend suite**

Run: `pytest -q`
Expected: PASS (aucune régression)

- [ ] **Step 7: Commit**

```bash
git add nfogen/qbittorrent_client.py nfogen/upload_prep.py tests/test_qbittorrent_client.py tests/test_upload_prep.py
git commit -m "feat: qBittorrent paused/tags sur add_torrent + resume() + tag NFOGEN partout"
```

---

## Task 5 : `nfogen/seed_match_job_runner.py`

**Files:**
- Create: `nfogen/seed_match_job_runner.py`
- Test: `tests/test_seed_match_job_runner.py`

**Interfaces:**
- Consumes: `torznab_client.TorznabClient.download()` (Task 3), `qbittorrent_client.QBittorrentClient.add_torrent(paused=True, tags="NFOGEN")`/`.resume()`/`.list_torrents()` (Task 4), `torf.Torrent.read()` (déjà une dépendance, voir `torrent_builder.py`).
- Produces: `start(tracker_client, qbittorrent_client, guid: str, local_dir: str, release_name: str) -> str` (job_id), `status(job_id: str) -> Optional[dict]`, `cancel(job_id: str) -> bool`. Dict de statut : `{"job_id", "state", "started_at", "finished_at", "error", "result"}` — `state` ∈ `"downloading"|"checking"|"done"|"mismatch"|"error"|"cancelled"`, `result` = `{"warning": str | None}` ou `None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests de nfogen.seed_match_job_runner. Meme convention que
test_integrity_job_runner.py."""
from __future__ import annotations

import importlib
import threading
import time

import pytest

from nfogen import seed_match_job_runner
from nfogen.qbittorrent_client import QBittorrentError
from nfogen.torznab_client import TorznabError


@pytest.fixture(autouse=True)
def _reset_runner():
    importlib.reload(seed_match_job_runner)
    yield
    importlib.reload(seed_match_job_runner)


def _wait_until_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = seed_match_job_runner.status(job_id)
        if status is not None and status["state"] in ("done", "mismatch", "error", "cancelled"):
            return status
        if time.monotonic() > deadline:
            raise TimeoutError("la tâche de test ne s'est jamais terminée")
        time.sleep(0.01)


class _FakeTorf:
    infohash = "abc123"


def _fake_torf_read(path):
    return _FakeTorf()


class FakeTracker:
    def __init__(self, torrent_bytes=b"d8:announce..."):
        self._torrent_bytes = torrent_bytes

    def download(self, guid):
        return self._torrent_bytes


class FakeQBittorrent:
    def __init__(self, list_results):
        self._added = None
        self._resumed = None
        self._list_results = list_results

    def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
        self._added = {"torrent_bytes": torrent_bytes, "save_path": save_path, "kwargs": kwargs}

    def list_torrents(self):
        return self._list_results

    def resume(self, torrent_hash):
        self._resumed = torrent_hash


def test_start_returns_job_id_immediately_and_reaches_done(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    tracker = FakeTracker()
    qb = FakeQBittorrent([{"hash": "abc123", "progress": 1.0, "state": "pausedUP"}])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id)

    assert status["state"] == "done"
    assert qb._added["kwargs"]["paused"] is True
    assert qb._added["kwargs"]["tags"] == "NFOGEN"
    assert qb._resumed == "abc123"


def test_start_reaches_mismatch_when_progress_incomplete(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    tracker = FakeTracker()
    qb = FakeQBittorrent([{"hash": "abc123", "progress": 0.5, "state": "pausedUP"}])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id)

    assert status["state"] == "mismatch"
    assert qb._resumed is None
    assert status["result"]["warning"]


def test_start_reaches_mismatch_on_missing_files(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    tracker = FakeTracker()
    qb = FakeQBittorrent([{"hash": "abc123", "progress": 0.0, "state": "missingFiles"}])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id)

    assert status["state"] == "mismatch"
    assert qb._resumed is None


def test_start_reaches_error_when_download_fails(monkeypatch):
    class FailingTracker:
        def download(self, guid):
            raise TorznabError("panne réseau")

    job_id = seed_match_job_runner.start(
        FailingTracker(), FakeQBittorrent([]), "guid-1", "/staging/Movie", "Movie.2020-TEAM",
    )
    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "panne réseau" in status["error"]


def test_start_reaches_error_when_qbittorrent_add_fails(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))

    class FailingQBittorrent(FakeQBittorrent):
        def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
            raise QBittorrentError("connexion échouée")

    job_id = seed_match_job_runner.start(
        FakeTracker(), FailingQBittorrent([]), "guid-1", "/staging/Movie", "Movie.2020-TEAM",
    )
    status = _wait_until_terminal(job_id)
    assert status["state"] == "error"
    assert "connexion échouée" in status["error"]


def test_start_reaches_error_on_verification_timeout(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    monkeypatch.setattr("nfogen.seed_match_job_runner._POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr("nfogen.seed_match_job_runner._CHECK_TIMEOUT_SECONDS", 0.03)
    tracker = FakeTracker()
    # hash absent de list_torrents() -> jamais trouve, doit finir par un timeout
    qb = FakeQBittorrent([])

    job_id = seed_match_job_runner.start(tracker, qb, "guid-1", "/staging/Movie", "Movie.2020-TEAM")
    status = _wait_until_terminal(job_id, timeout=2.0)
    assert status["state"] == "error"
    assert "trop longue" in status["error"] or "qBittorrent" in status["error"]


def test_cancel_before_add_never_calls_add_torrent(monkeypatch):
    monkeypatch.setattr("nfogen.seed_match_job_runner.torf.Torrent.read", staticmethod(_fake_torf_read))
    started = threading.Event()
    added_called = threading.Event()

    class SlowTracker:
        def download(self, guid):
            started.set()
            time.sleep(0.2)
            return b"torrent-bytes"

    class TrackedQBittorrent(FakeQBittorrent):
        def add_torrent(self, *args, **kwargs):
            added_called.set()
            super().add_torrent(*args, **kwargs)

    job_id = seed_match_job_runner.start(
        SlowTracker(), TrackedQBittorrent([]), "guid-1", "/staging/Movie", "Movie.2020-TEAM",
    )
    assert started.wait(timeout=5)
    assert seed_match_job_runner.cancel(job_id) is True
    status = _wait_until_terminal(job_id)
    assert status["state"] == "cancelled"
    assert not added_called.is_set()


def test_status_of_unknown_job_is_none():
    assert seed_match_job_runner.status("does-not-exist") is None


def test_cancel_unknown_job_returns_false():
    assert seed_match_job_runner.cancel("does-not-exist") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_seed_match_job_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.seed_match_job_runner'`

- [ ] **Step 3: Write the implementation**

```python
"""Execution en tache de fond du telechargement + verification d'une
correspondance de seed (AUTOMATION.md, retour utilisateur 2026-09-09) :
meme patron que integrity_job_runner.py (thread + job_id + polling,
etat en memoire uniquement)."""
from __future__ import annotations

import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import torf

from .qbittorrent_client import QBittorrentClient, QBittorrentError
from .torznab_client import TorznabClient, TorznabError

_POLL_INTERVAL_SECONDS = 1.5
_CHECK_TIMEOUT_SECONDS = 300.0

# Etats qBittorrent consideres comme "verification terminee, fichier
# complet" -- NON VERIFIES CONTRE UNE INSTANCE REELLE (voir
# AUTOMATION.md, meme prudence que le N+1 Sonarr du 2026-09-09).
_VERIFIED_COMPLETE_STATES = {"pausedUP", "queuedUP", "checkedUP"}
_VERIFIED_MISMATCH_STATES = {"missingFiles", "error"}


class SeedMatchJobState(str, Enum):
    DOWNLOADING = "downloading"
    CHECKING = "checking"
    DONE = "done"
    MISMATCH = "mismatch"
    ERROR = "error"
    CANCELLED = "cancelled"


_TERMINAL_STATES = (
    SeedMatchJobState.DONE, SeedMatchJobState.MISMATCH,
    SeedMatchJobState.ERROR, SeedMatchJobState.CANCELLED,
)


@dataclass
class SeedMatchJobProgress:
    job_id: str
    state: SeedMatchJobState
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


_lock = threading.Lock()
_jobs: dict[str, SeedMatchJobProgress] = {}
_cancel_events: dict[str, threading.Event] = {}


def start(
    tracker_client: TorznabClient, qbittorrent_client: QBittorrentClient,
    guid: str, local_dir: str, release_name: str,
) -> str:
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job = SeedMatchJobProgress(job_id=job_id, state=SeedMatchJobState.DOWNLOADING)
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel_event

    thread = threading.Thread(
        target=_run, args=(job_id, tracker_client, qbittorrent_client, guid, local_dir, release_name, cancel_event),
        daemon=True,
    )
    thread.start()
    return job_id


def _set_state(job_id: str, state: SeedMatchJobState, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.state = state
        for key, value in fields.items():
            setattr(job, key, value)


def _run(
    job_id: str, tracker_client: TorznabClient, qbittorrent_client: QBittorrentClient,
    guid: str, local_dir: str, release_name: str, cancel_event: threading.Event,
) -> None:
    try:
        torrent_bytes = tracker_client.download(guid)
        if cancel_event.is_set():
            _set_state(job_id, SeedMatchJobState.CANCELLED, finished_at=time.time())
            return

        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
            tmp.write(torrent_bytes)
            tmp_path = tmp.name
        infohash = torf.Torrent.read(tmp_path).infohash
        Path(tmp_path).unlink(missing_ok=True)

        qbittorrent_client.add_torrent(
            torrent_bytes, local_dir, filename=f"{release_name}.torrent", paused=True, tags="NFOGEN",
        )
        _set_state(job_id, SeedMatchJobState.CHECKING)

        deadline = time.monotonic() + _CHECK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if cancel_event.is_set():
                _set_state(job_id, SeedMatchJobState.CANCELLED, finished_at=time.time())
                return
            entry = next(
                (t for t in qbittorrent_client.list_torrents() if t.get("hash") == infohash), None,
            )
            if entry is not None:
                state = entry.get("state")
                progress = entry.get("progress", 0.0)
                if state in _VERIFIED_COMPLETE_STATES and progress == 1.0:
                    qbittorrent_client.resume(infohash)
                    _set_state(
                        job_id, SeedMatchJobState.DONE, finished_at=time.time(),
                        result={"warning": None},
                    )
                    return
                if state in _VERIFIED_MISMATCH_STATES or (state in _VERIFIED_COMPLETE_STATES and progress < 1.0):
                    _set_state(
                        job_id, SeedMatchJobState.MISMATCH, finished_at=time.time(),
                        result={
                            "warning": "Le fichier téléchargé ne correspond pas exactement — "
                            "resté en pause dans qBittorrent, à vérifier/supprimer manuellement.",
                        },
                    )
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)

        _set_state(
            job_id, SeedMatchJobState.ERROR, finished_at=time.time(),
            error="Vérification qBittorrent trop longue — vérifie manuellement dans son interface.",
        )
    except (TorznabError, QBittorrentError) as exc:
        _set_state(job_id, SeedMatchJobState.ERROR, finished_at=time.time(), error=str(exc))
    except Exception as exc:  # noqa: BLE001 -- toute erreur -> etat "error", jamais un thread qui meurt en silence
        _set_state(job_id, SeedMatchJobState.ERROR, finished_at=time.time(), error=str(exc))


def _serialize(job: SeedMatchJobProgress) -> dict[str, Any]:
    return {
        "job_id": job.job_id, "state": job.state.value,
        "started_at": job.started_at, "finished_at": job.finished_at,
        "error": job.error, "result": job.result,
    }


def status(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(job_id)
        return _serialize(job) if job is not None else None


def cancel(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.state in _TERMINAL_STATES:
            return False
        _cancel_events[job_id].set()
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_seed_match_job_runner.py -v`
Expected: PASS (toutes)

- [ ] **Step 5: Commit**

```bash
git add nfogen/seed_match_job_runner.py tests/test_seed_match_job_runner.py
git commit -m "feat: seed_match_job_runner.py -- telechargement + verification en tache de fond"
```

---

## Task 6 : Endpoints HTTP (`nfogen/api.py`)

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `seed_match_job_runner.start()/status()/cancel()` (Task 5), `gapscan_library.find_result_by_key()` (Task 2), `gapscan_runner.results()` (existant), `gapscan_config_store.effective_tracker()`/`effective_qbittorrent()` (existants, mêmes accesseurs déjà utilisés par `_build_gapscan_clients`/`upload_prep.send_to_tracker`).
- Produces: `POST /gapscan/seed-match/start` → `{"job_id": str}` (400 si `key`/`guid` non reconnus, ou qBittorrent non configuré) ; `GET /gapscan/seed-match-jobs/{job_id}` → dict de statut (404 si inconnu) ; `POST /gapscan/seed-match-jobs/{job_id}/cancel` → `{"status": "cancelling"}`.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_api.py` :

```python
def test_seed_match_start_returns_job_id(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    fake_result = type("R", (), {
        "c411_matches": [type("Rel", (), {"guid": "guid-1"})()],
        "local_paths": ["/staging/Movie/Movie.2020-TEAM.mkv"],
    })()
    monkeypatch.setattr(mod.gapscan_runner, "results", lambda **k: [fake_result])
    monkeypatch.setattr(mod.gapscan_library, "find_result_by_key", lambda key, results: fake_result)
    monkeypatch.setattr(
        mod.gapscan_config_store, "effective_tracker",
        lambda profile: ("api-key", "https://c411.example"),
    )
    monkeypatch.setattr(
        mod.gapscan_config_store, "effective_qbittorrent",
        lambda: ("http://qb.local", "admin", "pw", True),
    )
    monkeypatch.setattr(mod.seed_match_job_runner, "start", lambda *a, **k: "job-1")
    client = TestClient(mod.app)

    resp = client.post(
        "/gapscan/seed-match/start",
        json={"key": "some-key", "guid": "guid-1", "release_name": "Movie.2020-TEAM"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-1"}


def test_seed_match_start_400_when_key_not_found(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod.gapscan_runner, "results", lambda **k: [])
    monkeypatch.setattr(mod.gapscan_library, "find_result_by_key", lambda key, results: None)
    client = TestClient(mod.app)

    resp = client.post(
        "/gapscan/seed-match/start",
        json={"key": "unknown", "guid": "guid-1", "release_name": "X"},
    )
    assert resp.status_code == 400


def test_seed_match_start_400_when_guid_not_in_matches(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    fake_result = type("R", (), {"c411_matches": []})()
    monkeypatch.setattr(mod.gapscan_runner, "results", lambda **k: [fake_result])
    monkeypatch.setattr(mod.gapscan_library, "find_result_by_key", lambda key, results: fake_result)
    client = TestClient(mod.app)

    resp = client.post(
        "/gapscan/seed-match/start",
        json={"key": "some-key", "guid": "guid-inconnu", "release_name": "X"},
    )
    assert resp.status_code == 400


def test_seed_match_job_status_404_for_unknown_job(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/seed-match-jobs/does-not-exist")
    assert resp.status_code == 404


def test_seed_match_job_status_returns_job(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    fake_status = {
        "job_id": "job-1", "state": "done", "started_at": 1.0, "finished_at": 2.0,
        "error": None, "result": {"warning": None},
    }
    monkeypatch.setattr(mod.seed_match_job_runner, "status", lambda job_id: fake_status)
    client = TestClient(mod.app)

    resp = client.get("/gapscan/seed-match-jobs/job-1")
    assert resp.status_code == 200
    assert resp.json() == fake_status


def test_seed_match_cancel_unknown_is_404(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/seed-match-jobs/does-not-exist/cancel")
    assert resp.status_code == 404


def test_seed_match_endpoints_401_without_token(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret")
    client = TestClient(mod.app)

    assert client.post("/gapscan/seed-match/start", json={"key": "x", "guid": "y", "release_name": "z"}).status_code == 401
    assert client.get("/gapscan/seed-match-jobs/x").status_code == 401
    assert client.post("/gapscan/seed-match-jobs/x/cancel").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k seed_match`
Expected: FAIL — `AttributeError: module 'nfogen.api' has no attribute 'seed_match_job_runner'` (404 partout, endpoints inconnus)

- [ ] **Step 3: Write the implementation**

Ajouter `gapscan_library` et `seed_match_job_runner` au bloc d'import
optionnel existant (`nfogen/api.py`, dans le `from . import (...)`
sous le commentaire "GapScan : extra optionnel") :

```python
    from . import (
        commit_job_runner,
        gapscan,
        gapscan_config_store,
        gapscan_library,
        gapscan_runner,
        integrity_job_runner,
        seed_match_job_runner,
        tracker_profile,
        upload_history_store,
        upload_prep,
    )
```

Puis, à la suite des endpoints `verify-integrity`/`integrity-jobs`
existants :

```python
class SeedMatchStartRequest(BaseModel):
    key: str
    guid: str
    release_name: str


@app.post("/gapscan/seed-match/start", dependencies=[Depends(require_token)])
def gapscan_seed_match_start(req: SeedMatchStartRequest, profile: str = Query("c411")) -> dict[str, str]:
    """Demarre le telechargement + verification EN TACHE DE FOND -- `key`
    ET `guid` doivent correspondre a un scan GapScan reellement connu
    (voir gapscan_library.find_result_by_key, audit securite
    2026-09-09) : jamais de telechargement sur la seule foi d'un guid
    fourni tel quel par le client."""
    _require_gapscan_available()
    result = gapscan_library.find_result_by_key(req.key, gapscan_runner.results())
    if result is None:
        raise HTTPException(status_code=400, detail="Titre inconnu (aucun scan récent ne le connaît).")
    if not any(m.guid == req.guid for m in result.c411_matches):
        raise HTTPException(status_code=400, detail="Release C411 inconnue pour ce titre.")

    qbittorrent_config = gapscan_config_store.effective_qbittorrent()
    if qbittorrent_config is None:
        raise HTTPException(status_code=400, detail="qBittorrent non configuré (voir Réglages).")

    tracker_config = gapscan_config_store.effective_tracker(profile)
    if tracker_config is None:
        raise HTTPException(status_code=400, detail=f"Clé API du tracker '{profile}' non configurée.")
    tracker_key, tracker_base_url = tracker_config
    tracker_client = TorznabClient(tracker_key, base_url=tracker_base_url.rstrip("/") + "/api")
    qb_client = QBittorrentClient(*qbittorrent_config)

    local_dir = str(Path(result.local_paths[0]).parent) if result.local_paths else ""
    job_id = seed_match_job_runner.start(tracker_client, qb_client, req.guid, local_dir, req.release_name)
    return {"job_id": job_id}


@app.get("/gapscan/seed-match-jobs/{job_id}", dependencies=[Depends(require_token)])
def gapscan_seed_match_job_status(job_id: str) -> dict[str, Any]:
    _require_gapscan_available()
    status = seed_match_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    return status


@app.post("/gapscan/seed-match-jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def gapscan_seed_match_job_cancel(job_id: str) -> dict[str, str]:
    _require_gapscan_available()
    status = seed_match_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    if status["state"] in ("done", "mismatch", "error", "cancelled"):
        raise HTTPException(status_code=409, detail="Cette tâche est déjà terminée.")
    seed_match_job_runner.cancel(job_id)
    return {"status": "cancelling"}
```

**Note** : `TorznabClient`/`QBittorrentClient` sont déjà importés en
tête de `nfogen/api.py` pour d'autres usages (`_build_gapscan_clients`)
— vérifier avec `grep -n "^from .torznab_client\|^from .qbittorrent_client" nfogen/api.py`
avant d'ajouter un import en double.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k seed_match`
Expected: PASS (toutes)

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`
Expected: PASS (aucune régression)

- [ ] **Step 6: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: endpoints /gapscan/seed-match/start + /gapscan/seed-match-jobs/*"
```

---

## Task 7 : Frontend — types et client API

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `LibraryItem.seed_match: { guid: string; release_name: string } | null` (types.ts), type `SeedMatchJobState`, interface `SeedMatchJob` (types.ts) ; fonctions `startSeedMatch(key: string, guid: string, releaseName: string, profile?: string): Promise<{ job_id: string }>`, `seedMatchJobStatus(jobId: string): Promise<SeedMatchJob>`, `cancelSeedMatchJob(jobId: string): Promise<{ status: string }>` (client.ts).

- [ ] **Step 1: Add the types**

Dans `frontend/src/api/types.ts`, ajouter à `LibraryItem` (à la suite
de `team`) :

```typescript
  /** Present uniquement si status == "covered" ET une SEULE release
   * C411 correspond exactement (taille + team + resolution/source/
   * codec/langues) -- permet de proposer un seed sans re-upload
   * (retour utilisateur, 2026-09-09). */
  seed_match: { guid: string; release_name: string } | null;
```

Ajouter, à la suite de l'interface `IntegrityJob` existante :

```typescript
/** POST /gapscan/seed-match/start + GET /gapscan/seed-match-jobs/{id}
 * (retour utilisateur, 2026-09-09 -- seed d'une release C411 deja
 * possedee, sans re-upload). Meme patron que IntegrityJob. */
export type SeedMatchJobState = "downloading" | "checking" | "done" | "mismatch" | "error" | "cancelled";

export interface SeedMatchJob {
  job_id: string;
  state: SeedMatchJobState;
  started_at: number;
  finished_at: number | null;
  error: string | null;
  result: { warning: string | null } | null;
}
```

- [ ] **Step 2: Add the client functions**

Dans `frontend/src/api/client.ts`, ajouter à la suite de
`cancelIntegrityJob` :

```typescript
export function startSeedMatch(
  key: string, guid: string, releaseName: string, profile = "c411",
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/gapscan/seed-match/start?profile=${encodeURIComponent(profile)}`, {
    method: "POST",
    body: JSON.stringify({ key, guid, release_name: releaseName }),
  });
}

export function seedMatchJobStatus(jobId: string): Promise<SeedMatchJob> {
  return request<SeedMatchJob>(`/gapscan/seed-match-jobs/${encodeURIComponent(jobId)}`);
}

export function cancelSeedMatchJob(jobId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/gapscan/seed-match-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
```

Ajouter `SeedMatchJob` à l'import de types en haut du fichier, par
ordre alphabétique.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: aucune erreur

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat(frontend): types + client pour le seed d'une release existante"
```

---

## Task 8 : Frontend — bouton "Seed possible" dans la Bibliothèque

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `startSeedMatch`, `seedMatchJobStatus`, `cancelSeedMatchJob` (Task 7), `SeedMatchJob` (Task 7), `item.seed_match` (Task 7).

- [ ] **Step 1: Write the failing tests**

Étendre le mock `vi.mock("../api/client", ...)` de
`frontend/src/pages/LibraryPage.test.tsx` avec les 3 nouvelles
fonctions (`startSeedMatch: vi.fn()`, `seedMatchJobStatus: vi.fn()`,
`cancelSeedMatchJob: vi.fn()`), les ajouter à l'import correspondant,
et au `beforeEach` (`vi.mocked(startSeedMatch).mockReset()` etc. — même
principe que les autres mocks de ce fichier).

Ajouter au fixture `MATRIX_ITEM` un `seed_match: null` (comme les
autres champs déjà présents), puis ajouter :

```typescript
const MATRIX_WITH_SEED_MATCH: LibraryItem = {
  ...MATRIX_ITEM,
  status: "covered",
  seed_match: { guid: "guid-1", release_name: "Matrix.1999.1080p.BluRay.x264-TEAM" },
};

it("affiche le bouton 'Seed possible' quand seed_match est present", async () => {
  vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_WITH_SEED_MATCH], total: 1, season_packs: [] });
  renderPage();
  await screen.findByText(/Matrix \(1999\)/);
  expect(screen.getByRole("button", { name: "Seed possible" })).toBeInTheDocument();
});

it("n'affiche pas le bouton 'Seed possible' quand seed_match est absent", async () => {
  vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });
  renderPage();
  await screen.findByText(/Matrix \(1999\)/);
  expect(screen.queryByRole("button", { name: "Seed possible" })).not.toBeInTheDocument();
});

it("'Seed possible' lance le job, affiche le resultat DONE", async () => {
  const user = userEvent.setup();
  vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_WITH_SEED_MATCH], total: 1, season_packs: [] });
  vi.mocked(startSeedMatch).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(seedMatchJobStatus).mockResolvedValue({
    job_id: "job-1", state: "done", started_at: 1, finished_at: 2, error: null, result: { warning: null },
  });
  renderPage();
  await screen.findByText(/Matrix \(1999\)/);

  await user.click(screen.getByRole("button", { name: "Seed possible" }));

  expect(startSeedMatch).toHaveBeenCalledWith(MATRIX_ITEM.key, "guid-1", "Matrix.1999.1080p.BluRay.x264-TEAM");
  expect(await screen.findByText(/En seed/)).toBeInTheDocument();
});

it("'Seed possible' affiche l'avertissement quand le job finit en MISMATCH", async () => {
  const user = userEvent.setup();
  vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_WITH_SEED_MATCH], total: 1, season_packs: [] });
  vi.mocked(startSeedMatch).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(seedMatchJobStatus).mockResolvedValue({
    job_id: "job-1", state: "mismatch", started_at: 1, finished_at: 2, error: null,
    result: { warning: "Le fichier téléchargé ne correspond pas exactement — resté en pause dans qBittorrent." },
  });
  renderPage();
  await screen.findByText(/Matrix \(1999\)/);

  await user.click(screen.getByRole("button", { name: "Seed possible" }));

  expect(await screen.findByText(/ne correspond pas exactement/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx -t "Seed possible"`
Expected: FAIL — bouton absent, `startSeedMatch` jamais appelé

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/pages/LibraryPage.tsx`, ajouter aux imports :

```typescript
import { cancelSeedMatchJob, seedMatchJobStatus, startSeedMatch } from "../api/client";
import type { SeedMatchJob } from "../api/types";
```

Ajouter l'état (à la suite de `seasonPacks`) :

```typescript
  const [seedMatchJobs, setSeedMatchJobs] = useState<Record<string, SeedMatchJob>>({});
```

Ajouter les handlers (à la suite de `seasonsForPack`) :

```typescript
  async function pollSeedMatchUntilTerminal(key: string, jobId: string) {
    for (;;) {
      const job = await seedMatchJobStatus(jobId);
      setSeedMatchJobs((prev) => ({ ...prev, [key]: job }));
      if (["done", "mismatch", "error", "cancelled"].includes(job.state)) return;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }

  async function handleStartSeedMatch(item: LibraryItem) {
    if (!item.seed_match) return;
    try {
      const { job_id } = await startSeedMatch(item.key, item.seed_match.guid, item.seed_match.release_name);
      await pollSeedMatchUntilTerminal(item.key, job_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de démarrer le seed.");
    }
  }

  async function handleCancelSeedMatch(key: string) {
    const job = seedMatchJobs[key];
    if (!job) return;
    try {
      await cancelSeedMatchJob(job.job_id);
    } catch {
      // best effort
    }
  }
```

Dans le JSX, dans le `<td>` d'actions (celui contenant "Générer" et
"Préparer l'upload"), ajouter avant la fermeture du `<td>` :

```tsx
                  {item.seed_match && !seedMatchJobs[item.key] && (
                    <button
                      type="button"
                      onClick={() => handleStartSeedMatch(item)}
                      className="ml-3 text-sm text-accent-ink underline"
                    >
                      Seed possible
                    </button>
                  )}
                  {seedMatchJobs[item.key] && seedMatchJobs[item.key].state !== "done"
                    && seedMatchJobs[item.key].state !== "mismatch"
                    && seedMatchJobs[item.key].state !== "error" && (
                    <span className="ml-3 text-xs text-ink-dim">
                      Vérification…
                      <button
                        type="button"
                        onClick={() => handleCancelSeedMatch(item.key)}
                        className="ml-1 text-crit underline"
                      >
                        Annuler
                      </button>
                    </span>
                  )}
                  {seedMatchJobs[item.key]?.state === "done" && (
                    <span className="ml-3 text-xs text-good">✅ En seed</span>
                  )}
                  {seedMatchJobs[item.key]?.state === "mismatch" && (
                    <span className="ml-3 text-xs text-warn" title={seedMatchJobs[item.key].result?.warning ?? undefined}>
                      ⚠ {seedMatchJobs[item.key].result?.warning}
                    </span>
                  )}
                  {seedMatchJobs[item.key]?.state === "error" && (
                    <span className="ml-3 text-xs text-crit">⚠ {seedMatchJobs[item.key].error}</span>
                  )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx`
Expected: PASS (toutes)

- [ ] **Step 5: Run the full frontend suite + typecheck + lint**

Run: `cd frontend && npx vitest run && npx tsc -b --noEmit && npx oxlint`
Expected: PASS partout (aucune régression, aucune nouvelle erreur de
lint hormis les avertissements pré-existants déjà connus)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat(frontend): bouton 'Seed possible' dans la Bibliotheque"
```

---

## Task 9 : Documentation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `AUTOMATION.md`

- [ ] **Step 1: `CHANGELOG.md`**

Ajouter en tête de la section `### Ajouté` du `[Non publié]` :

```markdown
- **Seed d'une release C411 déjà possédée, sans re-upload** (retour
  utilisateur, 2026-09-09 : "est-ce pas possible de recuperer le
  torrent [...] afin de seed ce meme fichier ?") : pour un titre déjà
  couvert sur C411, si le fichier local correspond EXACTEMENT (taille +
  team + résolution/source/codec/langues) à une release existante,
  bouton "Seed possible" dans la Bibliothèque — télécharge son
  `.torrent` (`GET /api?t=get&id={guid}`, confirmé fonctionnel avec la
  seule clé API), l'ajoute à qBittorrent **en pause** pointé sur le
  fichier local, attend la vérification réelle des pièces par
  qBittorrent avant de reprendre le seed. Aucune correspondance
  ambiguë (zéro ou plusieurs candidats) n'est jamais proposée. Tout
  torrent ajouté par nfogen (celui-ci et l'auto-seed existant après
  upload direct) porte désormais le tag qBittorrent `NFOGEN`.
```

- [ ] **Step 2: `AUTOMATION.md`**

Ajouter une nouvelle section après la dernière section existante :

```markdown
## Sous-projet 10 : Seed d'une release C411 déjà possédée (conception et livraison 2026-09-09)

Retour utilisateur (2026-09-09) : pour un titre `COVERED` (déjà présent
sur C411), rien ne permettait de profiter d'une correspondance
EXACTE avec le fichier déjà possédé — l'utilisateur devait soit
renoncer, soit récupérer le `.torrent` manuellement sur le site.

**Téléchargement programmatique confirmé** : `GET
/api?t=get&id={guid}&apikey=...` (Torznab standard) renvoie le
`.torrent` directement, confirmé en conditions réelles — DISTINCT du
téléchargement du torrent re-signé de son propre upload (qui lui exige
une session navigateur, voir sous-projet 6). `TorznabClient.download()`
l'expose.

**Détection de correspondance** (`nfogen/seed_match.py`) : comparaison
stricte sur ce qui est parsable depuis le nom de release
(résolution/source/codec vidéo/langues, `quality.parse_release_name`)
+ tag d'équipe + taille exacte en octets — jamais le codec audio (non
parsable depuis un nom de fichier). Zéro ou plusieurs candidats ⇒
aucune correspondance proposée.

**Vérification réelle avant tout seed** (`nfogen/seed_match_job_runner.py`,
même patron de tâche de fond que la vérification d'intégrité vidéo,
sous-projet 7) : le torrent est ajouté à qBittorrent **en pause**,
pointé sur le fichier local déjà en place — qBittorrent vérifie
lui-même les pièces. Reprise automatique du seed uniquement si la
vérification confirme un fichier complet ; sinon, le torrent reste en
pause (jamais supprimé), avec un avertissement clair. Tag qBittorrent
`NFOGEN` sur tout torrent ajouté par nfogen (celui-ci et l'auto-seed
existant du sous-projet 6).

Voir [docs/superpowers/specs/2026-09-09-seed-match-design.md](docs/superpowers/specs/2026-09-09-seed-match-design.md)
et [docs/superpowers/plans/2026-09-09-seed-match.md](docs/superpowers/plans/2026-09-09-seed-match.md).
```

- [ ] **Step 3: Run the full test suites one last time**

Run: `pytest -q && cd frontend && npx vitest run && npx tsc -b --noEmit && npx oxlint`
Expected: PASS partout

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md AUTOMATION.md
git commit -m "docs: seed d'une release C411 existante -- CHANGELOG/AUTOMATION.md"
```

---

## Après le plan

Une fois les 9 tâches livrées et poussées, poller GitHub Actions
jusqu'à `conclusion: success` sur le dernier commit. **Avant de
considérer ce sous-projet définitivement acquis**, demander à
l'utilisateur de tester un vrai "Seed possible" sur un titre réel — les
chaînes d'état qBittorrent (`pausedUP`/`queuedUP`/`checkedUP`/
`missingFiles`) ne sont vérifiées contre aucune instance réelle dans ce
plan (même situation que le N+1 Sonarr du 2026-09-09, qui avait cassé
la production faute de ce test).
