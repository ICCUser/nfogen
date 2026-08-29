# GapScan Genre Filter + Server-Side Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un filtre Type (Film/Série) et Genre (Animé/Documentaire) sur les résultats GapScan déjà scannés, avec pagination côté serveur pour supporter une bibliothèque de 1000+ titres.

**Architecture:** Le genre est dérivé (jamais stocké) de la catégorie C411 du premier match trouvé (`gapscan.genre_of()`), donc aucune migration de la persistance disque. `GET /gapscan/results` gagne `media_type`/`genre`/`page`/`page_size` et change de forme (`{items, total}` au lieu d'une liste nue) ; le frontend suit.

**Tech Stack:** Python (FastAPI), pytest, React/TypeScript, Vitest/Testing Library.

**Spec:** [GAPSCAN.md](../../../GAPSCAN.md), section "Filtre type/genre + pagination serveur (2026-08-28)".

## Global Constraints

- TDD strict : test rouge confirmé avant toute implémentation, pour chaque étape.
- `npx tsc --noEmit -p tsconfig.app.json` (jamais `npx tsc --noEmit` seul).
- Aucun sous-agent sur ce projet — exécution entièrement inline.
- Table de correspondance catégorie C411 → genre, **vérifiée en direct** via `GET https://c411.org/api?t=caps` (2026-08-28) : Film=`2030`, Série=`5000`, Animé=`2060`(film)/`5070`(série), Documentaire=`2070`(film)/`5080`(série). Ne jamais réutiliser l'ancienne table de `GAPSCAN.md` (fausse, corrigée le 2026-08-28).
- Un titre `"absent"` (aucun match C411) n'a par définition aucune catégorie : `genre_of()` renvoie toujours `None` pour lui — comportement voulu, pas un bug à "corriger".
- Le tri des colonnes est explicitement hors scope de ce plan.
- Toutes les chaînes visibles utilisateur en français, cohérent avec le reste du projet.
- Commit fréquent, un commit par tâche.

---

## File Structure

- **Modify** `nfogen/gapscan.py` : `genre_of(result: GapResult) -> Optional[str]`.
- **Modify** `tests/test_gapscan.py` : tests de `genre_of()`, `_release()` gagne un paramètre `category`.
- **Modify** `nfogen/gapscan_runner.py` : `results()` gagne `media_type_filter`/`genre_filter`.
- **Modify** `tests/test_gapscan_runner.py` : tests des nouveaux filtres, `_season()` ajouté.
- **Modify** `nfogen/api.py` : `GET /gapscan/results` (pagination + filtres + enveloppe `{items, total}` + champ `genre` par item), `GET /gapscan/results/export.csv` (mêmes filtres + colonne `genre`).
- **Modify** `tests/test_api.py` : tests des nouveaux paramètres/enveloppe, mise à jour des 6 tests existants qui supposaient une liste nue.
- **Modify** `frontend/src/api/types.ts` : `GapResult.genre`, `GapscanResultsPage`.
- **Modify** `frontend/src/api/client.ts` : `gapscanResults()`/`gapscanExportCsv()` changent de signature.
- **Modify** `frontend/src/api/client.test.ts` : tests des nouvelles signatures.
- **Modify** `frontend/src/pages/GapScanPage.tsx` : selects Type/Genre, pagination, câblage à la nouvelle forme de réponse.
- **Modify** `frontend/src/pages/GapScanPage.test.tsx` : tests des nouveaux filtres/pagination.
- **Modify** `GAPSCAN.md`, `CHANGELOG.md` : marquer comme livré.

---

### Task 1: `genre_of()` — dérivation du genre depuis la catégorie C411

**Files:**
- Modify: `nfogen/gapscan.py`
- Test: `tests/test_gapscan.py`

**Interfaces:**
- Consumes: `GapResult` (déjà défini, champ `c411_matches: list[C411Release]`), `C411Release.category: Optional[str]` (déjà défini).
- Produces: `genre_of(result: GapResult) -> Optional[str]` (renvoie `"anime"`, `"documentaire"`, ou `None`) — utilisé par Task 2 (`gapscan_runner.results()`) et Task 3/4 (`api.py`).

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_gapscan.py`, étendre l'import en tête de fichier :

```python
from nfogen.c411_client import C411Error, C411Release
from nfogen.gapscan import (
    GapResult,
    GapStatus,
    genre_of,
    run_gapscan,
    scan_movie,
    scan_series_season,
    sort_by_priority,
)
from nfogen.quality import ReleaseQuality
```

Étendre `_release()` (déjà existant) pour accepter un `category` optionnel :

```python
def _release(
    title: str, imdb_id: Optional[str] = None, dvf: float = 1.0, uvf: float = 1.0,
    category: Optional[str] = None,
) -> C411Release:
    return C411Release(title=title, guid=title, link="https://c411.org/x", imdb_id=imdb_id,
                        download_volume_factor=dvf, upload_volume_factor=uvf, category=category)
```

Ajouter à la fin du fichier :

```python
# --------------------------------------------------------------------------- #
# Genre (Anime/Documentaire) : derive de la categorie C411 du PREMIER match
# trouve (AUTOMATION.md/GAPSCAN.md, "Filtre type/genre + pagination
# serveur", 2026-08-28). Table verifiee en direct via
# GET https://c411.org/api?t=caps -- 2030/5000 = Film/Serie standard,
# 2060/5070 = Anime (film/serie), 2070/5080 = Documentaire (film/serie).
# --------------------------------------------------------------------------- #
def _result(status: GapStatus = GapStatus.ABSENT, c411_matches: Optional[list] = None) -> GapResult:
    return GapResult(
        media_type="movie", title="X", year=2020, season_number=None,
        imdb_id=None, tmdb_id=None, tvdb_id=None, status=status,
        local_quality=ReleaseQuality(raw=""), c411_matches=c411_matches or [],
    )


def test_genre_of_returns_none_when_no_c411_matches():
    assert genre_of(_result()) is None


def test_genre_of_anime_for_movie_category():
    result = _result(status=GapStatus.COVERED, c411_matches=[_release("X", category="2060")])
    assert genre_of(result) == "anime"


def test_genre_of_anime_for_series_category():
    result = _result(status=GapStatus.COVERED, c411_matches=[_release("X", category="5070")])
    assert genre_of(result) == "anime"


def test_genre_of_documentaire_for_movie_and_series_categories():
    movie = _result(status=GapStatus.COVERED, c411_matches=[_release("X", category="2070")])
    series = _result(status=GapStatus.COVERED, c411_matches=[_release("X", category="5080")])
    assert genre_of(movie) == "documentaire"
    assert genre_of(series) == "documentaire"


def test_genre_of_none_for_standard_film_or_series_category():
    """2030/5000 = Film/Serie generique -- pas un genre special, meme
    valeur (None) que "aucune categorie"."""
    result = _result(status=GapStatus.COVERED, c411_matches=[_release("X", category="2030")])
    assert genre_of(result) is None


def test_genre_of_uses_the_first_match_when_several_exist():
    """Le premier match (deja trie par pertinence cote C411) fait foi."""
    result = _result(
        status=GapStatus.COVERED,
        c411_matches=[_release("X", category="2060"), _release("X2", category="2070")],
    )
    assert genre_of(result) == "anime"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -k genre_of -v`
Expected: FAIL avec `ImportError: cannot import name 'genre_of' from 'nfogen.gapscan'`

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/gapscan.py`, ajouter après `_classify()` (chercher `def _classify(local_quality: ReleaseQuality, matches: list[C411Release]) -> GapStatus:` et sa fin) :

```python
# Categories C411 (verifiees le 2026-08-28 via GET https://c411.org/api?t=caps)
# pertinentes pour le filtre genre. Films (2xxx) et series (5xxx) ont des
# codes distincts, pas besoin de connaitre media_type pour desambiguer.
# 2030/5000 (Film/Serie standard) ne sont pas retenus ici : aucun filtre
# "standard" distinct de "pas de genre special" (voir GAPSCAN.md).
_ANIME_CATEGORIES = {"2060", "5070"}
_DOCUMENTARY_CATEGORIES = {"2070", "5080"}


def genre_of(result: GapResult) -> Optional[str]:
    """'anime'/'documentaire' d'apres la categorie C411 du PREMIER match
    trouve (deja trie par pertinence cote C411) ; `None` si ce match est un
    film/serie standard, OU si aucun match n'existe du tout -- un titre
    "absent" n'a par definition aucune categorie, jamais classifiable par
    genre fin (voir GAPSCAN.md, limite assumee)."""
    if not result.c411_matches:
        return None
    category = result.c411_matches[0].category
    if category in _ANIME_CATEGORIES:
        return "anime"
    if category in _DOCUMENTARY_CATEGORIES:
        return "documentaire"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -v`
Expected: tous les tests du fichier passent (vérifier l'absence de régression sur les tests existants).

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan.py tests/test_gapscan.py
git commit -m "GapScan sous-projet filtre : genre_of() (categorie C411 -> anime/documentaire)"
```

---

### Task 2: `gapscan_runner.results()` — filtres `media_type`/`genre`

**Files:**
- Modify: `nfogen/gapscan_runner.py`
- Test: `tests/test_gapscan_runner.py`

**Interfaces:**
- Consumes: `genre_of` (Task 1).
- Produces: `results(status_filter=None, media_type_filter=None, genre_filter=None) -> list[GapResult]` — utilisé par Task 3/4 (`api.py`).

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_gapscan_runner.py`, ajouter un helper `_season()` juste après `_movie()` (chercher `def _movie(title: str = "Matrix") -> RadarrMovieFile:` et sa fin) :

```python
def _season(title: str = "Severance", season_number: int = 1) -> SonarrSeasonFile:
    return SonarrSeasonFile(
        series_id=1, title=title, year=2020, tvdb_id=1, imdb_id=None,
        season_number=season_number, episode_file_count=1,
    )
```

Ajouter à la fin du fichier :

```python
def test_results_filterable_by_media_type():
    c411 = FakeC411(movie_results=[], tv_results=[])
    radarr = FakeRadarr(movies=[_movie("A")])
    sonarr = FakeSonarr(seasons=[_season("B")])

    gapscan_runner.start(c411, radarr=radarr, sonarr=sonarr)
    _wait_until_not_running()

    movies = gapscan_runner.results(media_type_filter="movie")
    assert len(movies) == 1 and movies[0].title == "A"
    series = gapscan_runner.results(media_type_filter="series")
    assert len(series) == 1 and series[0].title == "B"


def test_results_filterable_by_genre():
    anime_release = C411Release(title="A", guid="A", link="https://c411.org/x", category="2060")
    c411 = FakeC411(movie_results=[anime_release])
    radarr = FakeRadarr(movies=[_movie("A")])

    gapscan_runner.start(c411, radarr=radarr)
    _wait_until_not_running()

    assert len(gapscan_runner.results(genre_filter="anime")) == 1
    assert gapscan_runner.results(genre_filter="documentaire") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_runner.py -k "filterable_by_media_type or filterable_by_genre" -v`
Expected: FAIL avec `TypeError: results() got an unexpected keyword argument 'media_type_filter'`

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/gapscan_runner.py`, modifier l'import (chercher `from .gapscan import GapResult, run_gapscan, sort_by_priority`) :

```python
from .gapscan import GapResult, genre_of, run_gapscan, sort_by_priority
```

Remplacer `results()` :

```python
def results(
    status_filter: Optional[str] = None,
    media_type_filter: Optional[str] = None,
    genre_filter: Optional[str] = None,
) -> list[GapResult]:
    """Resultats du dernier scan termine. `status_filter` : une valeur de
    `GapStatus` (ex. "absent"). `media_type_filter` : "movie" ou "series".
    `genre_filter` : "anime" ou "documentaire" (voir `gapscan.genre_of` --
    un titre sans match C411 ne correspond jamais a un genre_filter)."""
    with _lock:
        items = list(_results)
    if status_filter is not None:
        items = [r for r in items if r.status.value == status_filter]
    if media_type_filter is not None:
        items = [r for r in items if r.media_type == media_type_filter]
    if genre_filter is not None:
        items = [r for r in items if genre_of(r) == genre_filter]
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_runner.py -v`
Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_runner.py tests/test_gapscan_runner.py
git commit -m "GapScan sous-projet filtre : results() gagne media_type_filter/genre_filter"
```

---

### Task 3: API — pagination + filtres sur `GET /gapscan/results`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `gapscan_runner.results(status_filter, media_type_filter, genre_filter)` (Task 2), `gapscan.genre_of` (Task 1).
- Produces: `GET /gapscan/results?status=&media_type=&genre=&page=&page_size=` -> `{"items": [...], "total": N}` (chaque item gagne un champ `"genre"`) — utilisé par Task 5 (client TS).

- [ ] **Step 1: Update the 6 existing tests that assume a bare list**

Dans `tests/test_api.py`, ces call-sites cassent avec la nouvelle enveloppe `{items, total}` — les corriger AVANT d'écrire les nouveaux tests (sinon la suite reste rouge pour la mauvaise raison) :

Remplacer (chercher `results = client.get("/gapscan/results").json()` en premier, ligne ~1429) :
```python
    results = client.get("/gapscan/results").json()
    assert len(results) == 1
    assert results[0]["media_type"] == "movie"
    assert results[0]["title"] == "Matrix"
    assert results[0]["status"] == "absent"  # FakeGapscanC411 ne renvoie jamais de match
```
par :
```python
    body = client.get("/gapscan/results").json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["media_type"] == "movie"
    assert body["items"][0]["title"] == "Matrix"
    assert body["items"][0]["status"] == "absent"  # FakeGapscanC411 ne renvoie jamais de match
```

Remplacer (chercher `results = client.get("/gapscan/results").json()` en second, ligne ~1476) :
```python
    results = client.get("/gapscan/results").json()
    assert {r["media_type"] for r in results} == {"movie"}
```
par :
```python
    body = client.get("/gapscan/results").json()
    assert {r["media_type"] for r in body["items"]} == {"movie"}
```

Remplacer les deux occurrences (chercher `client.get("/gapscan/results").json()[0]["status"]`, lignes ~1562 et ~1570) :
```python
    assert client.get("/gapscan/results").json()[0]["status"] == "covered"
```
par (les deux fois) :
```python
    assert client.get("/gapscan/results").json()["items"][0]["status"] == "covered"
```

Remplacer (chercher `test_gapscan_results_filterable_by_status_query_param`, corps de la fonction) :
```python
    assert len(client.get("/gapscan/results", params={"status": "absent"}).json()) == 1
    assert client.get("/gapscan/results", params={"status": "covered"}).json() == []
```
par :
```python
    assert client.get("/gapscan/results", params={"status": "absent"}).json()["total"] == 1
    assert client.get("/gapscan/results", params={"status": "covered"}).json() == {"items": [], "total": 0}
```

- [ ] **Step 2: Run to confirm these 6 corrected tests still pass against the OLD code**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "gapscan_run_uses or gapscan_run_only_movies or gapscan_run_incremental_reuses or gapscan_results_filterable_by_status" -v`
Expected: FAIL (l'API renvoie encore une liste nue, pas `{items, total}`) — confirme que ces tests décrivent bien le nouveau contrat attendu, pas encore implémenté. C'est le rouge de cette tâche.

- [ ] **Step 3: Write the new failing tests**

Ajouter à `tests/test_api.py`, juste après `test_gapscan_results_filterable_by_status_query_param` :

`_FakeGapscanRadarr.list_movie_files()` renvoie toujours exactement UN
film ("Matrix", codé en dur) — pas de moyen de le paramétrer par
construction. Pour un test à 3 films, sous-classer (même principe que
`_FakeGapscanC411Covered` déjà dans le fichier, qui sous-classe
`_FakeGapscanC411`) :

```python
class _FakeGapscanRadarrThreeMovies(_FakeGapscanRadarr):
    def list_movie_files(self):
        return [
            RadarrMovieFile(movie_id=1, title="A", year=1999, imdb_id="tt1", tmdb_id=1),
            RadarrMovieFile(movie_id=2, title="B", year=1999, imdb_id="tt2", tmdb_id=2),
            RadarrMovieFile(movie_id=3, title="C", year=1999, imdb_id="tt3", tmdb_id=3),
        ]


def test_gapscan_results_paginated(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod, radarr_cls=_FakeGapscanRadarrThreeMovies)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    page1 = client.get("/gapscan/results", params={"page": 1, "page_size": 2}).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2

    page2 = client.get("/gapscan/results", params={"page": 2, "page_size": 2}).json()
    assert page2["total"] == 3
    assert len(page2["items"]) == 1


def test_gapscan_results_filterable_by_media_type_and_genre(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    assert client.get("/gapscan/results", params={"media_type": "movie"}).json()["total"] == 1
    assert client.get("/gapscan/results", params={"media_type": "series"}).json()["total"] == 0
    assert client.get("/gapscan/results", params={"genre": "anime"}).json() == {"items": [], "total": 0}


def test_gapscan_results_items_include_genre_field(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    body = client.get("/gapscan/results").json()
    assert body["items"][0]["genre"] is None  # FakeGapscanC411 : aucun match -> pas de genre
```

`_patch_gapscan_clients(monkeypatch, mod, radarr_cls=..., sonarr_cls=...)` et `RadarrMovieFile` sont déjà importés/définis dans `tests/test_api.py` (chercher `def _patch_gapscan_clients` et `from nfogen.radarr_client import RadarrMovieFile` en tête de fichier) — aucun nouvel import necessaire au-dela de la classe `_FakeGapscanRadarrThreeMovies` ci-dessus.

- [ ] **Step 4: Run all new/modified tests to verify they fail correctly**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "gapscan_results" -v`
Expected: FAIL (paramètres `media_type`/`genre`/`page`/`page_size` non reconnus par l'endpoint, ou 422 selon FastAPI).

- [ ] **Step 5: Write minimal implementation**

Dans `nfogen/api.py`, modifier l'import guardé (chercher `from . import gapscan_config_store, gapscan_runner, upload_prep`) :

```python
try:
    from . import gapscan, gapscan_config_store, gapscan_runner, upload_prep
    from .c411_client import C411Client, C411Error
    from .radarr_client import RadarrClient, RadarrError
    from .sonarr_client import SonarrClient, SonarrError

    _GAPSCAN_AVAILABLE = True
except ImportError:
    _GAPSCAN_AVAILABLE = False
```

Remplacer `gapscan_results` (chercher `@app.get("/gapscan/results", dependencies=[Depends(require_token)])`) :

```python
@app.get("/gapscan/results", dependencies=[Depends(require_token)])
def gapscan_results(
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    _require_gapscan_available()
    items = gapscan_runner.results(
        status_filter=status, media_type_filter=media_type, genre_filter=genre
    )
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    serialized: list[dict[str, Any]] = []
    for r in page_items:
        d = asdict(r)
        d["genre"] = gapscan.genre_of(r)
        serialized.append(d)
    return {"items": serialized, "total": total}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "gapscan_results or gapscan_run" -v`
Expected: tous les tests passent, y compris les 6 corrigés à l'étape 1.

- [ ] **Step 7: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "API GapScan sous-projet filtre : pagination + media_type/genre sur GET /gapscan/results"
```

---

### Task 4: API — filtres + colonne `genre` sur l'export CSV

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `gapscan_runner.results(status_filter, media_type_filter, genre_filter)` (Task 2), `gapscan.genre_of` (Task 1).

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_api.py`, juste après `test_gapscan_results_export_csv` :

```python
def test_gapscan_results_export_csv_includes_genre_column_and_filters(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    resp = client.get("/gapscan/results/export.csv")
    assert resp.status_code == 200
    header = resp.text.splitlines()[0]
    assert "genre" in header.split(",")

    filtered = client.get("/gapscan/results/export.csv", params={"media_type": "series"})
    assert filtered.status_code == 200
    assert len(filtered.text.splitlines()) == 1  # seulement l'en-tete, aucun resultat serie
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k export_csv_includes_genre -v`
Expected: FAIL (colonne `genre` absente, filtre `media_type` ignoré par l'endpoint actuel).

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/api.py`, remplacer `_CSV_COLUMNS` et `gapscan_results_export_csv` :

```python
_CSV_COLUMNS = [
    "media_type", "title", "year", "season_number", "status", "genre",
    "imdb_id", "tmdb_id", "tvdb_id",
    "local_resolution", "local_source", "local_languages",
    "has_freeleech_alternative", "has_double_upload_window", "error",
]


@app.get("/gapscan/results/export.csv", dependencies=[Depends(require_token)])
def gapscan_results_export_csv(
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
) -> Response:
    _require_gapscan_available()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for r in gapscan_runner.results(
        status_filter=status, media_type_filter=media_type, genre_filter=genre
    ):
        writer.writerow(
            [
                r.media_type, r.title, r.year, r.season_number, r.status.value,
                gapscan.genre_of(r) or "",
                r.imdb_id, r.tmdb_id, r.tvdb_id,
                r.local_quality.resolution, r.local_quality.source,
                "+".join(r.local_quality.languages),
                r.has_freeleech_alternative, r.has_double_upload_window, r.error or "",
            ]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="gapscan.csv"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -v`
Expected: tous les tests du fichier passent.

Puis la suite complète pour verifier l'absence de regression :

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "API GapScan sous-projet filtre : colonne genre + filtres sur l'export CSV"
```

---

### Task 5: Frontend — types + client API

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `GapResult.genre: "anime" | "documentaire" | null`, `GapscanResultsPage { items: GapResult[]; total: number }`, `gapscanResults(opts?: {status?, mediaType?, genre?, page?, pageSize?}): Promise<GapscanResultsPage>`, `gapscanExportCsv(opts?: {status?, mediaType?, genre?}): Promise<Blob>` — utilisés par Task 6 (`GapScanPage.tsx`).

- [ ] **Step 1: Write the failing tests**

Dans `frontend/src/api/client.test.ts`, chercher le test existant `describe("GapScan", ...)` ou la zone testant `gapscanResults`/`gapscanExportCsv` (si aucun test dédié n'existe déjà pour ces deux fonctions dans ce fichier, les ajouter à la fin) :

```ts
describe("gapscanResults / gapscanExportCsv", () => {
  it("envoie tous les filtres et la pagination, renvoie {items, total}", async () => {
    const page = { items: [], total: 42 };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(page));

    const result = await gapscanResults({
      status: "absent", mediaType: "movie", genre: "anime", page: 2, pageSize: 25,
    });

    expect(result).toEqual(page);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("status=absent");
    expect(url).toContain("media_type=movie");
    expect(url).toContain("genre=anime");
    expect(url).toContain("page=2");
    expect(url).toContain("page_size=25");
  });

  it("gapscanResults sans options utilise page=1/page_size=50 par defaut", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], total: 0 }));

    await gapscanResults();

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("page=1");
    expect(url).toContain("page_size=50");
  });

  it("gapscanExportCsv envoie les filtres media_type/genre", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("a,b\n", { status: 200 }));

    await gapscanExportCsv({ mediaType: "series", genre: "documentaire" });

    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("media_type=series");
    expect(url).toContain("genre=documentaire");
  });
});
```

Ajouter `gapscanExportCsv, gapscanResults` à l'import depuis `"./client"` en tête du fichier.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `gapscanResults`/`gapscanExportCsv` renvoient encore l'ancienne forme, ou n'acceptent pas ces paramètres (erreur de type TS possible aussi selon la config).

- [ ] **Step 3: Write minimal implementation**

Dans `frontend/src/api/types.ts`, modifier `GapResult` (ajouter le champ, chercher `path_error: string | null;` dans l'interface `GapResult` et l'`}` qui suit) :

```ts
export interface GapResult {
  media_type: "movie" | "series";
  title: string;
  year: number | null;
  season_number: number | null;
  imdb_id: string | null;
  tmdb_id: string | null;
  tvdb_id: number | null;
  status: GapStatus;
  local_quality: ReleaseQuality;
  c411_matches: C411Match[];
  has_freeleech_alternative: boolean;
  has_double_upload_window: boolean;
  error: string | null;
  local_paths: string[];
  path_resolved: boolean;
  path_error: string | null;
  /** "anime"/"documentaire" d'apres la categorie C411 du premier match
   * trouve ; null si standard OU si aucun match (voir GAPSCAN.md). */
  genre: "anime" | "documentaire" | null;
}

/** GET /gapscan/results : pagination cote serveur (voir GAPSCAN.md,
 * "Filtre type/genre + pagination serveur"). */
export interface GapscanResultsPage {
  items: GapResult[];
  total: number;
}
```

Dans `frontend/src/api/client.ts`, remplacer `gapscanResults` et `gapscanExportCsv` (chercher `export function gapscanResults` et `export async function gapscanExportCsv`) :

```ts
export function gapscanResults(
  opts: {
    status?: string;
    mediaType?: "movie" | "series";
    genre?: "anime" | "documentaire";
    page?: number;
    pageSize?: number;
  } = {},
): Promise<GapscanResultsPage> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  return request<GapscanResultsPage>(`/gapscan/results?${params.toString()}`);
}

export async function gapscanExportCsv(
  opts: {
    status?: string;
    mediaType?: "movie" | "series";
    genre?: "anime" | "documentaire";
  } = {},
): Promise<Blob> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  const qs = params.toString();
  const resp = await safeFetch(`${getBaseUrl()}/gapscan/results/export.csv${qs ? `?${qs}` : ""}`, {
    credentials: "include",
  });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return resp.blob();
}
```

Ajouter `GapscanResultsPage` à l'import de types en tête de `client.ts` (chercher l'import `type { GapResult, ...} from "./types"`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS.

Puis vérifier les types : `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: aucune erreur.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "Frontend GapScan sous-projet filtre : client API gapscanResults/ExportCsv pagines+filtres"
```

---

### Task 6: Frontend — selects Type/Genre + pagination sur `GapScanPage`

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Modify: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `gapscanResults`, `gapscanExportCsv`, `GapscanResultsPage` (Task 5).

- [ ] **Step 1: Fix the 9 existing call sites that assume a bare array, then add `genre` to the fixture**

`gapscanResults` change de forme (liste nue -> `{items, total}`) : `frontend/src/pages/GapScanPage.test.tsx` a 9 appels `vi.mocked(gapscanResults).mockResolvedValue(...)`/`mockResolvedValueOnce(...)` qui passent encore un tableau nu. Les remplacer TOUS (recherche/remplace ligne par ligne, dans l'ordre du fichier) :

1. `vi.mocked(gapscanResults).mockResolvedValue([]);` (dans le `beforeEach` global) ->
   `vi.mocked(gapscanResults).mockResolvedValue({ items: [], total: 0 });`
2. `vi.mocked(gapscanResults).mockResolvedValue([MATRIX_GAP]);` (première occurrence, test "affiche les resultats deja disponibles...") ->
   `vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });`
3.
   ```ts
   vi.mocked(gapscanResults).mockResolvedValue([
     { ...MATRIX_GAP, path_resolved: false, path_error: "Fichier introuvable apres resolution : /mnt/nas/Matrix.mkv" },
   ]);
   ```
   ->
   ```ts
   vi.mocked(gapscanResults).mockResolvedValue({
     items: [
       { ...MATRIX_GAP, path_resolved: false, path_error: "Fichier introuvable apres resolution : /mnt/nas/Matrix.mkv" },
     ],
     total: 1,
   });
   ```
4. `vi.mocked(gapscanResults).mockResolvedValue([{ ...MATRIX_GAP, path_resolved: true, path_error: null }]);` ->
   `vi.mocked(gapscanResults).mockResolvedValue({ items: [{ ...MATRIX_GAP, path_resolved: true, path_error: null }], total: 1 });`
5.
   ```ts
   vi.mocked(gapscanResults).mockResolvedValue([
     { ...MATRIX_GAP, local_paths: ["/media/matrix.mkv"], path_resolved: true },
   ]);
   ```
   ->
   ```ts
   vi.mocked(gapscanResults).mockResolvedValue({
     items: [{ ...MATRIX_GAP, local_paths: ["/media/matrix.mkv"], path_resolved: true }],
     total: 1,
   });
   ```
6.
   ```ts
   vi.mocked(gapscanResults).mockResolvedValue([
     { ...MATRIX_GAP, local_paths: [], path_resolved: false },
   ]);
   ```
   ->
   ```ts
   vi.mocked(gapscanResults).mockResolvedValue({
     items: [{ ...MATRIX_GAP, local_paths: [], path_resolved: false }],
     total: 1,
   });
   ```
7. `vi.mocked(gapscanResults).mockResolvedValueOnce([]).mockResolvedValueOnce([MATRIX_GAP]);` ->
   `vi.mocked(gapscanResults).mockResolvedValueOnce({ items: [], total: 0 }).mockResolvedValueOnce({ items: [MATRIX_GAP], total: 1 });`
8. et 9. les deux occurrences restantes de `vi.mocked(gapscanResults).mockResolvedValue([MATRIX_GAP]);` (dans les tests vers la fin du fichier, autour de "scan precedent disponible"/"Films seulement") -> même remplacement que le point 2 : `vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });`

Ajouter aussi `genre: null,` à la définition de `MATRIX_GAP` (chercher `const MATRIX_GAP: GapResult = {` et son champ `status: "absent",` — ajouter `genre: null,` juste après, sinon TypeScript refuse l'objet une fois `GapResult.genre` requis par Task 5).

Puis ajouter ces nouveaux tests dans le `describe("GapScanPage", ...)` :

```tsx
it("affiche les selects Type et Genre, appelle gapscanResults avec les filtres choisis", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });

  renderPage();
  await screen.findByText(/Matrix \(1999\)/);

  await user.selectOptions(screen.getByLabelText("Type"), "movie");
  await waitFor(() => {
    expect(gapscanResults).toHaveBeenLastCalledWith(
      expect.objectContaining({ mediaType: "movie", page: 1 }),
    );
  });

  await user.selectOptions(screen.getByLabelText("Genre"), "anime");
  await waitFor(() => {
    expect(gapscanResults).toHaveBeenLastCalledWith(
      expect.objectContaining({ mediaType: "movie", genre: "anime", page: 1 }),
    );
  });
});

it("affiche la pagination et change de page au clic sur Suivant", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 120 });

  renderPage();
  await screen.findByText(/Page 1 \/ 3/);

  await user.click(screen.getByRole("button", { name: "Suivant" }));

  await waitFor(() => {
    expect(gapscanResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
  });
});

it("changer de filtre revient a la page 1", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 120 });

  renderPage();
  await screen.findByText(/Page 1 \/ 3/);
  await user.click(screen.getByRole("button", { name: "Suivant" }));
  await waitFor(() => screen.getByText(/Page 2 \/ 3/));

  await user.selectOptions(screen.getByLabelText("Type"), "series");

  await waitFor(() => {
    expect(gapscanResults).toHaveBeenLastCalledWith(expect.objectContaining({ mediaType: "series", page: 1 }));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: FAIL massivement (la page appelle encore l'ancienne signature de `gapscanResults`, `results.length` plante sur un objet `{items, total}` plutôt qu'un tableau, aucun select "Type"/"Genre" n'existe).

- [ ] **Step 3: Write minimal implementation**

Dans `frontend/src/pages/GapScanPage.tsx`, ajouter aux imports de types (chercher `import type { GapResult, GapscanConfig, GapscanConfigWrite, GapscanStatus, GapStatus } from "../api/types";`) :

```tsx
import type {
  GapResult,
  GapscanConfig,
  GapscanConfigWrite,
  GapscanStatus,
  GapStatus,
} from "../api/types";
```

(pas de nouveau type à importer explicitement — `GapscanResultsPage` n'est utilisé qu'en interne via l'inférence de `gapscanResults()`).

Ajouter les nouveaux états, juste après `const [filter, setFilter] = useState<GapStatus | "">("");` :

```tsx
const [mediaTypeFilter, setMediaTypeFilter] = useState<"" | "movie" | "series">("");
const [genreFilter, setGenreFilter] = useState<"" | "anime" | "documentaire">("");
const [page, setPage] = useState(1);
const [total, setTotal] = useState(0);
const PAGE_SIZE = 50;
```

Remplacer le `useEffect` de chargement (chercher `useEffect(() => {\n    loadResults();` avec le commentaire au-dessus) :

```tsx
  // Tout changement de filtre remet la page a 1 via les handlers ci-dessous
  // (setFilter/setPage groupes dans le meme gestionnaire d'evenement,
  // React les applique en un seul rendu -- pas de double appel reseau).
  // Charge aussi au montage (tous les filtres valent "" et page=1 au
  // premier rendu).
  useEffect(() => {
    loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, mediaTypeFilter, genreFilter, page]);

  function handleFilterChange(next: GapStatus | "") {
    setFilter(next);
    setPage(1);
  }

  function handleMediaTypeChange(next: "" | "movie" | "series") {
    setMediaTypeFilter(next);
    setPage(1);
  }

  function handleGenreChange(next: "" | "anime" | "documentaire") {
    setGenreFilter(next);
    setPage(1);
  }
```

Remplacer `loadResults()` :

```tsx
  async function loadResults() {
    try {
      const res = await gapscanResults({
        status: filter || undefined,
        mediaType: mediaTypeFilter || undefined,
        genre: genreFilter || undefined,
        page,
        pageSize: PAGE_SIZE,
      });
      setResults(res.items);
      setTotal(res.total);
    } catch (e) {
      setResults(null);
      setTotal(0);
      setError(e instanceof ApiError ? e.message : "Résultats indisponibles.");
    }
  }
```

Remplacer `handleExportCsv()` :

```tsx
  async function handleExportCsv() {
    try {
      const blob = await gapscanExportCsv({
        status: filter || undefined,
        mediaType: mediaTypeFilter || undefined,
        genre: genreFilter || undefined,
      });
      downloadBlob(blob, "gapscan.csv");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Export impossible.");
    }
  }
```

Remplacer le bloc du select "Filtrer par statut" (chercher `<label className="block text-sm font-medium text-ink-dim">\n        Filtrer par statut`) par trois selects côte à côte :

```tsx
      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm font-medium text-ink-dim">
          Filtrer par statut
          <select
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value as GapStatus | "")}
          >
            {FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Type
          <select
            aria-label="Type"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={mediaTypeFilter}
            onChange={(e) => handleMediaTypeChange(e.target.value as "" | "movie" | "series")}
          >
            <option value="">Tous les types</option>
            <option value="movie">Films</option>
            <option value="series">Séries</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Genre
          <select
            aria-label="Genre"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={genreFilter}
            onChange={(e) => handleGenreChange(e.target.value as "" | "anime" | "documentaire")}
          >
            <option value="">Tous les genres</option>
            <option value="anime">Animé</option>
            <option value="documentaire">Documentaire</option>
          </select>
        </label>
      </div>
```

Ajouter la pagination juste avant la fermeture `{activeUpload && (` (chercher `      )}\n\n      {activeUpload && (`, insérer entre le bloc `<table>...</table>)}` et ce commentaire) :

```tsx
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-ink-dim">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
          >
            Précédent
          </button>
          <span>
            Page {page} / {Math.max(1, Math.ceil(total / PAGE_SIZE))} — {total} résultats
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => (p * PAGE_SIZE < total ? p + 1 : p))}
            disabled={page * PAGE_SIZE >= total}
            className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
          >
            Suivant
          </button>
        </div>
      )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: PASS.

Puis : `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: aucune erreur.

Puis la suite Vitest complète : `cd frontend && npx vitest run`
Expected: tous les tests passent.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/GapScanPage.tsx frontend/src/pages/GapScanPage.test.tsx
git commit -m "Frontend GapScan sous-projet filtre : selects Type/Genre + pagination sur GapScanPage"
```

---

### Task 7: Documentation — marquer comme livré

**Files:**
- Modify: `GAPSCAN.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Mettre a jour GAPSCAN.md**

Dans la section "Filtre type/genre + pagination serveur (2026-08-28)", ajouter juste après le dernier paragraphe de "Conception" (avant la section suivante) :

```
**Livré (2026-08-28)** — [décrire ici tout écart réel entre cette
conception et l'implémentation finale, constaté pendant l'exécution du
plan ; si aucun écart, écrire "conforme à la conception ci-dessus, aucun
écart notable"].

Voir le plan d'implémentation complet (code exact) :
[docs/superpowers/plans/2026-08-28-gapscan-genre-filter-pagination.md](docs/superpowers/plans/2026-08-28-gapscan-genre-filter-pagination.md).
```

- [ ] **Step 2: Mettre a jour CHANGELOG.md**

Sous `## [Non publié]` -> `### Ajouté`, ajouter (même style que les entrées précédentes) :

```
- **Filtre Type/Genre + pagination serveur sur GapScan** : `GET
  /gapscan/results` accepte maintenant `media_type`/`genre` (Animé/
  Documentaire, dérivé de la catégorie C411 du match trouvé) en plus du
  filtre statut existant, avec pagination côté serveur (`page`/
  `page_size`) — supporte des bibliothèques de 1000+ titres sans tout
  charger d'un coup.
```

- [ ] **Step 3: Run the full test suite one more time**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check .`
Expected: tous les tests passent, ruff propre.

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p tsconfig.app.json`
Expected: tous les tests passent, aucune erreur de type.

- [ ] **Step 4: Commit**

```bash
git add GAPSCAN.md CHANGELOG.md
git commit -m "GAPSCAN.md/CHANGELOG.md : marque le filtre type/genre + pagination comme livre"
```

---

## Self-Review (effectué par l'auteur du plan)

- **Couverture du spec** : genre dérivé de la catégorie C411 (table vérifiée) -> Task 1 ; limite "absent" jamais classifiable -> Task 1 (test dédié) + doc ; pagination serveur -> Task 3 ; filtre média_type/genre sur résultats -> Task 2/3 ; export CSV cohérent avec la vue -> Task 4 ; deux selects + pagination frontend -> Task 6 ; tri explicitement hors scope -> non traité, conforme. Tout couvert.
- **Rupture de contrat assumée** : `GET /gapscan/results` change de forme (liste nue -> `{items, total}`) — Task 3 Step 1 corrige explicitement les 6 tests existants qui en dépendaient AVANT d'ajouter les nouveaux, pour ne jamais laisser la suite rouge pour la mauvaise raison. Le frontend (Task 6 Step 1) fait de même pour ses propres tests.
- **Placeholders** : aucun "TBD"/"à compléter" dans les étapes de code ; Task 7 documente explicitement qu'un écart réel doit être transcrit s'il existe.
- **Cohérence des types** : `genre_of() -> Optional[str]` (Task 1) repris tel quel dans `results()` (Task 2) et l'API (Task 3/4) ; `GapscanResultsPage {items, total}` (Task 5) correspond exactement à ce que l'API renvoie (Task 3) ; `mediaType`/`genre` en camelCase côté TS mappés vers `media_type`/`genre` en snake_case côté requête HTTP, cohérent avec le reste de `client.ts` (`titleHints` -> `title_hints`).

---

**Plan complet et sauvegardé dans `docs/superpowers/plans/2026-08-28-gapscan-genre-filter-pagination.md`. Deux options d'exécution :**

**1. Subagent-Driven (recommandé habituellement)** — mais **exclu ici** : l'utilisateur a explicitement demandé aucun sous-agent sur ce projet.

**2. Exécution inline** — via `superpowers:executing-plans`, tâche par tâche, avec points de contrôle.

Je pars sur l'exécution inline, cohérent avec la contrainte déjà posée sur ce projet.
