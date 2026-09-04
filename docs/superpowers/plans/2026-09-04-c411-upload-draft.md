# Upload vers C411 (brouillons) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Ce projet interdit l'usage de sous-agents (mémoire projet "No subagents on nfogen") : exécution obligatoirement inline via superpowers:executing-plans, jamais subagent-driven-development.**

**Goal:** Un nouveau bouton "Envoyer à C411" dans "Préparer l'upload" crée (ou met à jour) un **brouillon** C411 (`POST`/`PATCH /api/user/drafts`) à partir d'un groupe déjà confirmé (sous-projet 4) — titre, description BBCode (synopsis/affiche/casting via Radarr/Sonarr), catégorie/options — sans jamais soumettre réellement en modération (ça reste un geste humain sur le site C411).

**Architecture:** Un nouveau module pur `nfogen/c411_upload_options.py` calcule catégorie/sous-catégorie/options depuis le `release_name` déjà confirmé (réutilise `rules.captures()`, déjà construit pour la validation) et la config déclarative du profil (`rules.json -> tracker.upload`, nouvelle). Un nouveau module `nfogen/upload_description.py` rend un gabarit BBCode (`upload_description.j2`, même moteur Jinja2 que les `.nfo`) à partir de métadonnées Radarr/Sonarr récupérées **à la demande** (nouvelles méthodes `get_movie_details`/`get_series_details`, pas ajoutées au scan GapScan). Un nouveau client `nfogen/c411_upload_client.py` (délibérément spécifique à C411, pas générique) parle à `POST /api/user/drafts` et `GET /api/torrents/by-tmdb`. `upload_prep.py` orchestre le tout dans une nouvelle fonction `send_to_tracker()`, exposée par un nouvel endpoint et un nouveau bouton frontend.

**Tech Stack:** Python (FastAPI, httpx, Jinja2), TypeScript/React.

**Spec:** [AUTOMATION.md, section "Sous-projet 5 : Upload vers C411" → "Conception complète (2026-09-04)"](../../../AUTOMATION.md) (déjà approuvée par l'utilisateur, y compris la révision "brouillon, jamais soumission directe").

## Global Constraints

- TDD strictement : test qui échoue d'abord, confirmer l'échec pour la bonne raison, puis implémenter.
- Un commit par tâche. Suite complète (`pytest` + `ruff check`, puis `npx vitest run` + `npx tsc --noEmit -p tsconfig.app.json`) avant de passer à la tâche suivante pour toute tâche qui touche un module partagé (`tracker_profile.py`, `upload_prep.py`, `api.py`).
- **Jamais de soumission réelle en modération** : ce plan ne construit QUE la création/mise à jour d'un brouillon (`POST`/`PATCH /api/user/drafts`). Aucun code de ce plan n'appelle `POST /api/torrents` (soumission directe) — voir AUTOMATION.md, décision 6.
- **Jamais bloquant, jamais deviné** : toute donnée absente (mapping non déclaré dans le profil, `tmdb_id` inconnu pour une série, métadonnée Radarr/Sonarr manquante) doit dégrader proprement (avertissement explicite, champ omis) — jamais une valeur inventée, jamais une exception non gérée qui casse le flux "Préparer l'upload".
- **Deux inconnues réelles à vérifier en conditions réelles avant de considérer ce sous-projet terminé** (signalées explicitement dans les tâches concernées, jamais traitées comme acquises) :
  1. La doc API donnée par l'utilisateur ne précise pas les noms exacts des champs du corps JSON de `POST /api/user/drafts` (seulement "les fichiers sont envoyés en base64 dans le body JSON") — ce plan suppose les mêmes noms que le formulaire multipart documenté (`torrent`, `nfo`, `title`, `description`, `categoryId`, `subcategoryId`, `options`, etc.), à confirmer/ajuster contre un vrai brouillon créé sur le compte de l'utilisateur (Tâche 10).
  2. La liste de sous-catégories donnée n'a qu'UN SEUL "Documentaire" (id 4), sans distinction film/série (contrairement aux codes Torznab de recherche) — ce plan mappe les deux vers `4`, à confirmer via `GET /api/categories` en conditions réelles (Tâche 5).

---

### Task 1: `GapResult` gagne `radarr_movie_id`/`sonarr_series_id`

**Files:**
- Modify: `nfogen/gapscan.py`
- Test: `tests/test_gapscan.py`

**Interfaces:**
- Produces: `GapResult.radarr_movie_id: Optional[int]`, `GapResult.sonarr_series_id: Optional[int]` — l'un des deux selon `media_type`, `None` sinon. Consommé par la Tâche 15 (frontend) puis la Tâche 11 (`send_to_tracker`).

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_gapscan.py`, localiser les tests existants `test_scan_movie_*`/`test_scan_series_season_*` (chercher `def _movie(` et `def _season(` pour les helpers de fixture déjà présents) et ajouter :

```python
def test_scan_movie_result_includes_radarr_movie_id():
    c411 = FakeC411(movie_results=[])
    result = scan_movie(_movie(movie_id=42), c411)
    assert result.radarr_movie_id == 42
    assert result.sonarr_series_id is None


def test_scan_series_season_result_includes_sonarr_series_id():
    c411 = FakeC411(movie_results=[], tv_results=[])
    result = scan_series_season(_season(series_id=99), c411)
    assert result.sonarr_series_id == 99
    assert result.radarr_movie_id is None
```

(`_movie(movie_id=...)`/`_season(series_id=...)` : vérifier que les helpers existants acceptent déjà ces kwargs — sinon les fixtures `RadarrMovieFile(movie_id=..., ...)`/`SonarrSeasonFile(series_id=..., ...)` construites directement dans le test, en copiant les champs obligatoires déjà utilisés par les tests voisins du même fichier.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -k radarr_movie_id -v`
Expected: FAIL — `AttributeError: 'GapResult' object has no attribute 'radarr_movie_id'`.

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/gapscan.py`, `GapResult` gagne deux champs (après `tvdb_id`, avant `status`) :

```python
    tvdb_id: Optional[int]
    radarr_movie_id: Optional[int] = None
    sonarr_series_id: Optional[int] = None
    status: GapStatus
```

Attention : les champs sans valeur par défaut doivent rester AVANT ceux avec valeur par défaut dans un dataclass — `status` (et tout ce qui suit) n'a pas de défaut, donc `radarr_movie_id`/`sonarr_series_id` (avec défaut `None`) doivent être ajoutés **après** tous les champs sans défaut existants, pas insérés au milieu. Les ajouter juste avant `has_freeleech_alternative` (le premier champ déjà à défaut) :

```python
@dataclass
class GapResult:
    media_type: str
    title: str
    year: Optional[int]
    season_number: Optional[int]
    imdb_id: Optional[str]
    tmdb_id: Optional[str]
    tvdb_id: Optional[int]
    status: GapStatus
    local_quality: ReleaseQuality
    c411_matches: list[TorznabRelease] = field(default_factory=list)
    has_freeleech_alternative: bool = False
    has_double_upload_window: bool = False
    error: Optional[str] = None
    checked_at: Optional[float] = None
    local_paths: list[str] = field(default_factory=list)
    path_resolved: bool = False
    path_error: Optional[str] = None
    radarr_movie_id: Optional[int] = None
    sonarr_series_id: Optional[int] = None
```

Dans `scan_movie()`, le dict `base` gagne `radarr_movie_id=movie.movie_id` :

```python
    base = dict(
        media_type="movie", title=movie.title, year=movie.year, season_number=None,
        imdb_id=movie.imdb_id, tmdb_id=tmdb_id, tvdb_id=None, radarr_movie_id=movie.movie_id,
        local_quality=local_quality,
        local_paths=local_paths, path_resolved=path_resolved, path_error=path_error,
    )
```

Dans `scan_series_season()`, le dict `base` gagne `sonarr_series_id=season.series_id` :

```python
    base = dict(
        media_type="series", title=season.title, year=season.year,
        season_number=season.season_number, imdb_id=season.imdb_id, tmdb_id=None,
        tvdb_id=season.tvdb_id, sonarr_series_id=season.series_id, local_quality=local_quality,
        local_paths=local_paths, path_resolved=path_resolved, path_error=path_error,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan.py -v`
Expected: all PASS (le champ `_can_reuse`/`dataclasses.replace()` du mode incrémental copie tous les champs automatiquement, aucun autre changement requis).

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/gapscan.py tests/test_gapscan.py
git commit -m "feat: GapResult porte l'id Radarr/Sonarr (pour la recuperation de metadonnees a la demande)"
```

---

### Task 2: `RadarrClient.get_movie_details()`

**Files:**
- Modify: `nfogen/radarr_client.py`
- Test: `tests/test_radarr_client.py`

**Interfaces:**
- Produces: `RadarrMovieDetails` (dataclass : `overview: str`, `poster_url: Optional[str]`, `genres: list[str]`, `directors: list[str]`, `cast: list[str]`), `RadarrClient.get_movie_details(movie_id: int) -> RadarrMovieDetails`.

- [ ] **Step 1: Write the failing tests**

Lire `tests/test_radarr_client.py` en entier d'abord pour reprendre exactement son pattern de mock HTTP (probablement `httpx.MockTransport`, comme `test_torznab_client.py`/`test_c411.py`). Ajouter, en s'inspirant de ce pattern :

```python
def test_get_movie_details_parses_overview_poster_genres_credits():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/movie/42"
        return httpx.Response(
            200,
            json={
                "id": 42,
                "overview": "Dom Cobb est un voleur experimente...",
                "genres": ["Science-Fiction", "Action"],
                "images": [
                    {"coverType": "fanart", "remoteUrl": "https://image.tmdb.org/fanart.jpg"},
                    {"coverType": "poster", "remoteUrl": "https://image.tmdb.org/poster.jpg"},
                ],
                "credits": [
                    {"type": "cast", "character": "Cobb", "person": {"name": "Leonardo DiCaprio"}},
                    {"type": "crew", "job": "Director", "person": {"name": "Christopher Nolan"}},
                ],
            },
        )

    client = RadarrClient(
        "http://radarr.local", "key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    details = client.get_movie_details(42)

    assert details.overview == "Dom Cobb est un voleur experimente..."
    assert details.genres == ["Science-Fiction", "Action"]
    assert details.poster_url == "https://image.tmdb.org/poster.jpg"
    assert details.directors == ["Christopher Nolan"]
    assert details.cast == ["Leonardo DiCaprio"]


def test_get_movie_details_degrades_gracefully_when_fields_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 42})

    client = RadarrClient(
        "http://radarr.local", "key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    details = client.get_movie_details(42)

    assert details.overview == ""
    assert details.poster_url is None
    assert details.genres == []
    assert details.directors == []
    assert details.cast == []
```

(Vérifier le nom exact de la classe d'exception/import déjà utilisé en tête du fichier de test existant avant d'ajouter `import httpx` si nécessaire — probablement déjà présent.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_radarr_client.py -k get_movie_details -v`
Expected: FAIL — `AttributeError: 'RadarrClient' object has no attribute 'get_movie_details'`.

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/radarr_client.py`, ajouter après `RadarrMovieFile` :

```python
@dataclass
class RadarrMovieDetails:
    """Metadonnees de presentation d'un film (synopsis, affiche, genres,
    realisateur/casting) -- recuperees A LA DEMANDE (voir get_movie_details),
    jamais pendant le scan GapScan (voir AUTOMATION.md, sous-projet 5,
    decision 1 : inutile pour l'ecrasante majorite des 1000+ items scannes,
    seulement pour celui qu'on envoie reellement a un tracker). Radarr
    interroge deja TMDB pour son propre usage -- reutilise ici plutot
    qu'un client TMDB dedie."""

    overview: str = ""
    poster_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
```

Puis, dans `RadarrClient`, ajouter (après `list_movie_files`) :

```python
    def get_movie_details(self, movie_id: int) -> RadarrMovieDetails:
        """`GET /api/v3/movie/{id}` : metadonnees de presentation completes
        d'UN film -- jamais appele en boucle pendant un scan, uniquement au
        moment de preparer un envoi vers un tracker (voir upload_prep.py)."""
        movie = self._get(f"/api/v3/movie/{movie_id}")
        poster_url = next(
            (img.get("remoteUrl") for img in movie.get("images", []) if img.get("coverType") == "poster"),
            None,
        )
        directors = [
            c["person"]["name"]
            for c in movie.get("credits", [])
            if c.get("type") == "crew" and c.get("job") == "Director" and c.get("person", {}).get("name")
        ]
        cast = [
            c["person"]["name"]
            for c in movie.get("credits", [])
            if c.get("type") == "cast" and c.get("person", {}).get("name")
        ]
        return RadarrMovieDetails(
            overview=movie.get("overview") or "",
            poster_url=poster_url,
            genres=movie.get("genres") or [],
            directors=directors,
            cast=cast,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_radarr_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/radarr_client.py tests/test_radarr_client.py
git commit -m "feat: RadarrClient.get_movie_details() - metadonnees de presentation a la demande"
```

---

### Task 3: `SonarrClient.get_series_details()`

**Files:**
- Modify: `nfogen/sonarr_client.py`
- Test: `tests/test_sonarr_client.py`

**Interfaces:**
- Produces: `SonarrSeriesDetails` (dataclass : mêmes champs que `RadarrMovieDetails`), `SonarrClient.get_series_details(series_id: int) -> SonarrSeriesDetails`.

- [ ] **Step 1: Write the failing tests**

Lire `tests/test_sonarr_client.py` en entier d'abord pour le pattern de mock exact, puis ajouter (Sonarr expose `images`/`genres` sur `/api/v3/series/{id}`, mais pas de `credits` structuré comme Radarr — pas de réalisateur/casting fiable côté séries, se limiter à synopsis/affiche/genres) :

```python
def test_get_series_details_parses_overview_poster_genres():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/series/99"
        return httpx.Response(
            200,
            json={
                "id": 99,
                "overview": "Walter White, professeur de chimie...",
                "genres": ["Drama", "Crime"],
                "images": [
                    {"coverType": "banner", "remoteUrl": "https://image.tmdb.org/banner.jpg"},
                    {"coverType": "poster", "remoteUrl": "https://image.tmdb.org/poster.jpg"},
                ],
            },
        )

    client = SonarrClient(
        "http://sonarr.local", "key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    details = client.get_series_details(99)

    assert details.overview == "Walter White, professeur de chimie..."
    assert details.genres == ["Drama", "Crime"]
    assert details.poster_url == "https://image.tmdb.org/poster.jpg"
    assert details.directors == []
    assert details.cast == []


def test_get_series_details_degrades_gracefully_when_fields_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 99})

    client = SonarrClient(
        "http://sonarr.local", "key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    details = client.get_series_details(99)

    assert details.overview == ""
    assert details.poster_url is None
    assert details.genres == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sonarr_client.py -k get_series_details -v`
Expected: FAIL — `AttributeError: 'SonarrClient' object has no attribute 'get_series_details'`.

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/sonarr_client.py`, ajouter après `SonarrSeasonFile` :

```python
@dataclass
class SonarrSeriesDetails:
    """Meme role que RadarrMovieDetails, cote series -- voir la-bas. Sonarr
    n'expose pas de credits structures (realisateur/casting) comme Radarr :
    `directors`/`cast` restent toujours vides pour une serie."""

    overview: str = ""
    poster_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
```

Puis, dans `SonarrClient`, ajouter (après `list_season_files`) :

```python
    def get_series_details(self, series_id: int) -> SonarrSeriesDetails:
        """`GET /api/v3/series/{id}` : metadonnees de presentation d'UNE
        serie -- jamais appele en boucle pendant un scan, uniquement au
        moment de preparer un envoi vers un tracker (voir upload_prep.py)."""
        series = self._get(f"/api/v3/series/{series_id}")
        poster_url = next(
            (img.get("remoteUrl") for img in series.get("images", []) if img.get("coverType") == "poster"),
            None,
        )
        return SonarrSeriesDetails(
            overview=series.get("overview") or "",
            poster_url=poster_url,
            genres=series.get("genres") or [],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sonarr_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/sonarr_client.py tests/test_sonarr_client.py
git commit -m "feat: SonarrClient.get_series_details() - metadonnees de presentation a la demande"
```

---

### Task 4: Schéma `tracker.upload`

**Files:**
- Modify: `nfogen/rules.schema.json`
- Test: `tests/test_profile_store.py`

**Interfaces:**
- Produces: un profil valide peut avoir `rules.tracker.upload` avec les clés `category_id`, `subcategory_id`, `language_option_id`, `language_values`, `quality_option_id`, `quality_values`, `season_option_id`, `season_values`, `episode_option_id`, `full_season_episode_value`.

- [ ] **Step 1: Write the failing test**

Dans `tests/test_profile_store.py`, ajouter (après les tests `test_tracker_*` existants de la Tâche 1 du sous-projet 4b) :

```python
def test_tracker_upload_section_is_valid():
    rules = {
        "tracker": {
            "upload": {
                "category_id": 1,
                "subcategory_id": {"movie": 6, "series": 7},
                "language_option_id": 1,
                "language_values": {"VFF": 2, "MULTI.VFF": 4},
                "quality_option_id": 2,
                "quality_values": {"BluRay": 11, "BluRay.HDLight": 413},
                "season_option_id": 7,
                "season_values": {"S01": 121},
                "episode_option_id": 6,
                "full_season_episode_value": 96,
            }
        }
    }
    ps.write_profile("uploadtest", rules=rules, templates={})
    read = ps.read_profile("uploadtest")
    assert read["rules"]["tracker"]["upload"]["category_id"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_store.py -k tracker_upload -v`
Expected: FAIL — `ProfileStoreError` ("'upload' was unexpected" ou similaire, `additionalProperties: false` sur `$defs.tracker`).

- [ ] **Step 3: Extend the schema**

Dans `nfogen/rules.schema.json`, le `$defs.tracker` gagne une propriété `upload` :

```json
        "min_request_interval_seconds": { "type": "number" },
        "torrent_piece_sizes": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "max_bytes": { "type": "integer" },
              "piece_size": { "type": "integer" }
            },
            "required": ["piece_size"],
            "additionalProperties": false
          }
        },
        "upload": { "$ref": "#/$defs/tracker_upload" }
      },
      "additionalProperties": false
    },
```

(le bloc `"min_request_interval_seconds"`/`"torrent_piece_sizes"` existe déjà dans `$defs.tracker` — juste y ajouter la ligne `"upload": { "$ref": "#/$defs/tracker_upload" }` avant la fermeture `},` du bloc `properties`, et ajouter une virgule après `torrent_piece_sizes` s'il n'y en a pas déjà une.)

Puis ajouter la définition `tracker_upload` (à côté de `$defs.tracker`, `$defs.source_marker_check`, etc.) :

```json
    "tracker_upload": {
      "type": "object",
      "description": "Mapping vers l'API d'upload du tracker (AUTOMATION.md, sous-projet 5) : categorie/sous-categorie et types/valeurs d'option, figes ici plutot que requetes dynamiquement a chaque envoi.",
      "properties": {
        "category_id": { "type": "integer" },
        "subcategory_id": {
          "type": "object",
          "additionalProperties": { "type": "integer" }
        },
        "language_option_id": { "type": "integer" },
        "language_values": {
          "type": "object",
          "additionalProperties": { "type": "integer" }
        },
        "quality_option_id": { "type": "integer" },
        "quality_values": {
          "type": "object",
          "additionalProperties": { "type": "integer" }
        },
        "season_option_id": { "type": "integer" },
        "season_values": {
          "type": "object",
          "additionalProperties": { "type": "integer" }
        },
        "episode_option_id": { "type": "integer" },
        "full_season_episode_value": { "type": "integer" }
      },
      "additionalProperties": false
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/rules.schema.json tests/test_profile_store.py
git commit -m "feat: autorise une section tracker.upload dans rules.json"
```

---

### Task 5: Peupler `tracker.upload` dans le profil c411

**Files:**
- Modify: `nfogen/profiles/c411/rules.json`
- Test: `tests/test_tracker_profile.py`

**Interfaces:**
- Consomme : le schéma de la Tâche 4.
- Produit : les vraies valeurs C411 (données par l'utilisateur, 2026-09-04), lues par la Tâche 6.

**⚠️ Point non vérifié (voir Global Constraints)** : `subcategory_id["movie:documentaire"]` et `subcategory_id["series:documentaire"]` pointent tous les deux vers `4` (seule valeur "Documentaire" donnée par l'utilisateur, pas de distinction film/série dans la liste fournie) — à confirmer via `GET /api/categories` en conditions réelles avant le premier envoi réel d'un documentaire.

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_tracker_profile.py`, ajouter (à côté des tests `test_c411_*` existants qui lisent le vrai profil livré) :

```python
def test_c411_upload_category_and_subcategory_ids():
    upload = tracker_profile.upload_config("c411")
    assert upload["category_id"] == 1
    assert upload["subcategory_id"] == {
        "movie": 6, "movie:anime": 1, "movie:documentaire": 4,
        "series": 7, "series:anime": 2, "series:documentaire": 4,
    }


def test_c411_upload_language_values():
    upload = tracker_profile.upload_config("c411")
    assert upload["language_option_id"] == 1
    assert upload["language_values"] == {"VFF": 2, "MULTI.VFF": 4, "VO": 1, "VOSTFR": 8}


def test_c411_upload_quality_values():
    upload = tracker_profile.upload_config("c411")
    assert upload["quality_option_id"] == 2
    assert upload["quality_values"] == {
        "BluRay.HDLight": 413, "BluRay": 11, "BluRay.REMUX": 12, "WEB": 25, "WEB.4K": 26,
    }


def test_c411_upload_season_values_cover_s01_to_s30():
    upload = tracker_profile.upload_config("c411")
    assert upload["season_option_id"] == 7
    assert upload["season_values"]["INTEGRALE"] == 118
    assert upload["season_values"]["S01"] == 121
    assert upload["season_values"]["S02"] == 122
    assert upload["season_values"]["S30"] == 150
    assert len(upload["season_values"]) == 31  # INTEGRALE + S01..S30


def test_c411_upload_episode_values():
    upload = tracker_profile.upload_config("c411")
    assert upload["episode_option_id"] == 6
    assert upload["full_season_episode_value"] == 96
```

(`tracker_profile.upload_config` n'existe pas encore — cette tâche peuple le profil d'abord, la Tâche 6 écrit la fonction ; ces tests restent en échec jusqu'à la fin de la Tâche 6, c'est attendu et normal pour cette tâche-ci — RED confirmé au Step 2 pour la BONNE raison à ce stade : `AttributeError` sur `tracker_profile.upload_config`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracker_profile.py -k c411_upload -v`
Expected: FAIL — `AttributeError: module 'nfogen.tracker_profile' has no attribute 'upload_config'`.

- [ ] **Step 3: Populate the profile**

Dans `nfogen/profiles/c411/rules.json`, la section `tracker` gagne une clé `upload` (après `torrent_piece_sizes`) :

```json
    "torrent_piece_sizes": [
      {"max_bytes": 1073741824, "piece_size": 1048576},
      {"max_bytes": 2147483648, "piece_size": 2097152},
      {"max_bytes": 3221225472, "piece_size": 4194304},
      {"max_bytes": 8589934592, "piece_size": 8388608},
      {"piece_size": 16777216}
    ],
    "upload": {
      "category_id": 1,
      "subcategory_id": {
        "movie": 6, "movie:anime": 1, "movie:documentaire": 4,
        "series": 7, "series:anime": 2, "series:documentaire": 4
      },
      "language_option_id": 1,
      "language_values": {"VFF": 2, "MULTI.VFF": 4, "VO": 1, "VOSTFR": 8},
      "quality_option_id": 2,
      "quality_values": {
        "BluRay.HDLight": 413, "BluRay": 11, "BluRay.REMUX": 12,
        "WEB": 25, "WEB.4K": 26
      },
      "season_option_id": 7,
      "season_values": {
        "INTEGRALE": 118,
        "S01": 121, "S02": 122, "S03": 123, "S04": 124, "S05": 125,
        "S06": 126, "S07": 127, "S08": 128, "S09": 129, "S10": 130,
        "S11": 131, "S12": 132, "S13": 133, "S14": 134, "S15": 135,
        "S16": 136, "S17": 137, "S18": 138, "S19": 139, "S20": 140,
        "S21": 141, "S22": 142, "S23": 143, "S24": 144, "S25": 145,
        "S26": 146, "S27": 147, "S28": 148, "S29": 149, "S30": 150
      },
      "episode_option_id": 6,
      "full_season_episode_value": 96
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracker_profile.py -v`
Expected: toujours les mêmes échecs `AttributeError` qu'au Step 2 (la fonction `upload_config` n'existe toujours pas — normal, c'est la Tâche 6). Ne PAS committer cette tâche seule si les tests échouent encore : enchaîner directement sur la Tâche 6 avant de committer les deux ensemble, OU committer cette tâche avec les tests marqués `@pytest.mark.xfail(reason="tracker_profile.upload_config pas encore ecrit, voir Tache 6")` temporairement si une pause est nécessaire entre les deux. Dans l'exécution normale de ce plan (tâches enchaînées), passer directement à la Tâche 6 sans commit intermédiaire ici.

- [ ] **Step 5: Commit (avec la Tâche 6, voir ci-dessous)**

---

### Task 6: `tracker_profile.upload_config()`

**Files:**
- Modify: `nfogen/tracker_profile.py`
- Test: `tests/test_tracker_profile.py` (déjà écrit à la Tâche 5)

**Interfaces:**
- Produces: `upload_config(profile: str) -> dict[str, Any]` — le sous-dict `tracker.upload` tel quel, `{}` si non déclaré (jamais de plantage, même philosophie que le reste du fichier).

- [ ] **Step 1: Confirm the tests from Task 5 still fail for the same reason**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracker_profile.py -k c411_upload -v`
Expected: FAIL — `AttributeError` (inchangé depuis la Tâche 5).

- [ ] **Step 2: Write minimal implementation**

Dans `nfogen/tracker_profile.py`, ajouter (après `torrent_piece_sizes`) :

```python
def upload_config(profile: str) -> dict[str, Any]:
    """Mapping catégorie/sous-catégorie/options vers l'API d'upload du
    tracker (rules.json -> tracker.upload, voir AUTOMATION.md sous-projet
    5) -- dictionnaire vide si non déclaré : aucun envoi n'est alors
    possible pour ce profil, jamais deviné."""
    return _tracker_section(profile).get("upload", {})
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracker_profile.py -v`
Expected: all PASS.

- [ ] **Step 4: Full suite + lint, then commit (Tasks 5+6 together)**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/profiles/c411/rules.json nfogen/tracker_profile.py tests/test_tracker_profile.py
git commit -m "feat: peuple tracker.upload (profil c411) + tracker_profile.upload_config()"
```

---

### Task 7: `nfogen/c411_upload_options.py` — catégorie/sous-catégorie/options (pur)

**Files:**
- Create: `nfogen/c411_upload_options.py`
- Test: `tests/test_c411_upload_options.py`

**Interfaces:**
- Consumes: `tracker_profile.upload_config(profile)` (Tâche 6), `rules.captures(release_name, schema) -> dict[str, str]` (existant, `nfogen/rules.py`).
- Produces (consommé par la Tâche 11) :
  - `build_category_ids(profile: str, media_type: str, genre: Optional[str]) -> tuple[Optional[int], Optional[int]]`
  - `build_options(profile: str, capture_values: dict[str, str], release_name: str, season_number: Optional[int] = None) -> dict[str, int | list[int]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_c411_upload_options.py` :

```python
"""Tests de nfogen.c411_upload_options (AUTOMATION.md, sous-projet 5) :
calcule categorie/sous-categorie/options a partir du release_name DEJA
CONFIRME (reutilise rules.captures, deja construit pour la validation) et
de la config declarative du profil -- pur, sans I/O, sans reseau."""
from __future__ import annotations

from nfogen import c411_upload_options as options_engine
from nfogen import profile_store as ps
from nfogen.registry import unregister_profile

import pytest


@pytest.fixture(autouse=True)
def _profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    yield tmp_path
    try:
        names = ps.list_profiles()
    except ps.ProfileStoreError:
        names = []
    for name in names:
        unregister_profile(name)


UPLOAD_RULES = {
    "tracker": {
        "upload": {
            "category_id": 1,
            "subcategory_id": {
                "movie": 6, "movie:anime": 1, "movie:documentaire": 4,
                "series": 7, "series:anime": 2,
            },
            "language_option_id": 1,
            "language_values": {"VFF": 2, "MULTI.VFF": 4},
            "quality_option_id": 2,
            "quality_values": {"BluRay": 11, "BluRay.HDLight": 413, "WEB": 25},
            "season_option_id": 7,
            "season_values": {"INTEGRALE": 118, "S01": 121, "S02": 122},
            "episode_option_id": 6,
            "full_season_episode_value": 96,
        }
    }
}


def test_build_category_ids_for_plain_movie():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    assert options_engine.build_category_ids("up", "movie", None) == (1, 6)


def test_build_category_ids_for_anime_series():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    assert options_engine.build_category_ids("up", "series", "anime") == (1, 2)


def test_build_category_ids_falls_back_to_media_type_when_genre_not_mapped():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    # "series:documentaire" n'est pas dans le mapping de test -- repli sur "series".
    assert options_engine.build_category_ids("up", "series", "documentaire") == (1, 7)


def test_build_category_ids_none_when_profile_has_no_upload_config():
    ps.write_profile("bare", rules={}, templates={})
    assert options_engine.build_category_ids("bare", "movie", None) == (None, None)


def test_build_options_for_bluray_hdlight_movie():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "MULTI.VFF"}
    release_name = "Joker.2015.MULTI.VFF.1080p.BluRay.HDLight.AC3.5.1.x264-NOTAG"
    result = options_engine.build_options("up", captures, release_name)
    assert result == {"1": [4], "2": 413}


def test_build_options_plain_bluray_without_hdlight_marker():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFF"}
    release_name = "Movie.2020.VFF.1080p.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result == {"1": [2], "2": 11}


def test_build_options_includes_season_and_full_season_episode_for_series():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "WEB", "language": "MULTI.VFF"}
    release_name = "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name, season_number=1)
    assert result == {"1": [4], "2": 25, "7": 121, "6": 96}


def test_build_options_omits_unmapped_fields_rather_than_guessing():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "HDTV", "language": "VOSTFR"}  # ni l'un ni l'autre dans le mapping de test
    release_name = "Movie.2020.VOSTFR.1080p.HDTV.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result == {}


def test_build_options_empty_dict_when_profile_has_no_upload_config():
    ps.write_profile("bare", rules={}, templates={})
    result = options_engine.build_options("bare", {"source": "BluRay"}, "Movie.2020.BluRay-TEAM")
    assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_c411_upload_options.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.c411_upload_options'`.

- [ ] **Step 3: Write the implementation**

Create `nfogen/c411_upload_options.py` :

```python
"""Calcule categorie/sous-categorie/options pour l'API d'upload C411
(POST/PATCH /api/user/drafts, voir AUTOMATION.md sous-projet 5) a partir
du release_name DEJA CONFIRME -- reutilise `rules.captures()`, deja
construit pour la validation du nom (sous-projet 4b), plutot que de
redemander au moteur de nommage ou de dupliquer sa logique. Pur, sans I/O :
un champ absent du mapping declaratif du profil (rules.json ->
tracker.upload) est simplement omis, jamais devine.
"""
from __future__ import annotations

from typing import Any, Optional

from . import tracker_profile


def build_category_ids(
    profile: str, media_type: str, genre: Optional[str]
) -> tuple[Optional[int], Optional[int]]:
    """`(category_id, subcategory_id)` pour ce media_type/genre, ou
    `(None, None)` si le profil n'a rien declare -- jamais devine. Cle de
    recherche `"{media_type}:{genre}"` (ex. "movie:anime") avec repli sur
    `media_type` seul si cette combinaison precise n'est pas mappee (ex.
    documentaire non distingue film/serie pour ce tracker)."""
    config = tracker_profile.upload_config(profile)
    category_id = config.get("category_id")
    subcategory_ids: dict[str, int] = config.get("subcategory_id", {})
    key = f"{media_type}:{genre}" if genre else media_type
    subcategory_id = subcategory_ids.get(key) or subcategory_ids.get(media_type)
    if category_id is None or subcategory_id is None:
        return None, None
    return category_id, subcategory_id


def build_options(
    profile: str,
    capture_values: dict[str, str],
    release_name: str,
    season_number: Optional[int] = None,
) -> dict[str, Any]:
    """Construit le JSON `options` (`{optionTypeId: optionValueId |
    [optionValueId, ...]}`, voir doc API C411) a partir des valeurs
    capturees dans le release_name confirme (`source`/`language`, voir
    rules.captures) et de la config declarative du profil. `season_number`
    (optionnel, series uniquement) ajoute les options Saison/Episode --
    toujours "saison complete" (`full_season_episode_value`), ce plan ne
    distingue pas un pack partiel (plusieurs equipes sur la meme saison,
    voir AUTOMATION.md "Pas dans ce sous-projet")."""
    config = tracker_profile.upload_config(profile)
    options: dict[str, Any] = {}

    language_option_id = config.get("language_option_id")
    language_values: dict[str, int] = config.get("language_values", {})
    language = capture_values.get("language")
    if language and language_option_id is not None and language in language_values:
        options[str(language_option_id)] = [language_values[language]]

    quality_option_id = config.get("quality_option_id")
    quality_values: dict[str, int] = config.get("quality_values", {})
    source = capture_values.get("source")
    if source:
        quality_key = f"{source}.HDLight" if "hdlight" in release_name.lower() else source
        if quality_option_id is not None and quality_key in quality_values:
            options[str(quality_option_id)] = quality_values[quality_key]

    if season_number is not None:
        season_option_id = config.get("season_option_id")
        season_values: dict[str, int] = config.get("season_values", {})
        season_key = f"S{int(season_number):02d}"
        if season_option_id is not None and season_key in season_values:
            options[str(season_option_id)] = season_values[season_key]

        episode_option_id = config.get("episode_option_id")
        full_season_value = config.get("full_season_episode_value")
        if episode_option_id is not None and full_season_value is not None:
            options[str(episode_option_id)] = full_season_value

    return options
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_c411_upload_options.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/c411_upload_options.py tests/test_c411_upload_options.py
git commit -m "feat: nfogen/c411_upload_options.py - categorie/sous-categorie/options a partir du nom confirme"
```

---

### Task 8: Gabarit BBCode + `render_upload_description()`

**Files:**
- Create: `nfogen/profiles/c411/templates/upload_description.j2`
- Create: `nfogen/upload_description.py`
- Test: `tests/test_upload_description.py`

**Interfaces:**
- Consumes: `render.render_template(profile, category, context)` (existant, `nfogen/render.py` — traite `"upload_description"` comme un nom de gabarit ordinaire, en dehors du système `CATEGORIES`/`registry`).
- Produces: `render_upload_description(profile: str, context: dict[str, Any]) -> str`. Contexte attendu (toutes clés optionnelles, gabarit tolérant à l'absence) : `title`, `overview`, `poster_url`, `genres` (list[str]), `directors` (list[str]), `cast` (list[str]), `resolution` (str), `source` (str), `video_codec` (str), `audio_languages` (list[str]).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_upload_description.py` :

```python
"""Tests de nfogen.upload_description (AUTOMATION.md, sous-projet 5) :
rend le gabarit BBCode de description d'upload -- meme moteur Jinja2 que
les .nfo (render.render_template), mecanisme parallele au systeme
categorie/registre (la description n'est pas un type de media)."""
from __future__ import annotations

from nfogen.upload_description import render_upload_description

FULL_CONTEXT = {
    "title": "Inception",
    "overview": "Dom Cobb est un voleur experimente...",
    "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
    "genres": ["Science-Fiction", "Action"],
    "directors": ["Christopher Nolan"],
    "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt"],
    "resolution": "2160",
    "source": "BluRay",
    "video_codec": "hevc",
    "audio_languages": ["French", "English"],
}


def test_renders_synopsis_and_poster():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Dom Cobb est un voleur experimente" in out
    assert "https://image.tmdb.org/t/p/w500/poster.jpg" in out


def test_renders_genres_directors_cast():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Science-Fiction" in out
    assert "Christopher Nolan" in out
    assert "Leonardo DiCaprio" in out


def test_renders_without_optional_fields():
    """Overview/poster/genres/directors/cast peuvent tous manquer (ex.
    Radarr/Sonarr n'ont rien trouve) -- le gabarit ne doit jamais planter,
    juste omettre les sections vides."""
    minimal = {
        "title": "Inception", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [],
        "resolution": "2160", "source": "BluRay", "video_codec": "hevc",
        "audio_languages": [],
    }
    out = render_upload_description("c411", minimal)
    assert "Inception" in out
    assert len(out) >= 20  # respecte le minimum de 20 caracteres exige par l'API C411


def test_output_meets_c411_minimum_length():
    """L'API C411 exige description >= 20 caracteres (voir doc, champs
    requis) -- verifie que meme le cas minimal du test precedent le
    respecte, contrat explicite plutot qu'implicite."""
    minimal = {
        "title": "X", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [],
        "resolution": "1080", "source": "WEB", "video_codec": "x264",
        "audio_languages": [],
    }
    out = render_upload_description("c411", minimal)
    assert len(out) >= 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_description.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.upload_description'`.

- [ ] **Step 3: Write the implementation**

Create `nfogen/profiles/c411/templates/upload_description.j2` (BBCode, syntaxe déjà vue dans les exemples curl de la doc C411 collée par l'utilisateur — `[center]`/`[img]`/`[h2]`/`[b]`/`[list]`) :

```jinja
{% if poster_url %}[center][img]{{ poster_url }}[/img][/center]

{% endif %}[h2]Synopsis[/h2]
{% if overview %}{{ overview }}{% else %}(synopsis non disponible){% endif %}

[h2]Informations[/h2]
{% if directors %}[b]Réalisateur :[/b] {{ directors|join(", ") }}
{% endif %}{% if cast %}[b]Acteurs :[/b] {{ cast|join(", ") }}
{% endif %}{% if genres %}[b]Genre :[/b] {{ genres|join(", ") }}
{% endif %}
[h2]Qualité[/h2]
[list]
[*]Vidéo : {{ video_codec }} {{ resolution }}p ({{ source }})
{% if audio_languages %}[*]Audio : {{ audio_languages|join(", ") }}
{% endif %}[/list]
```

Create `nfogen/upload_description.py` :

```python
"""Rendu de la description BBCode d'un upload (AUTOMATION.md, sous-projet
5) : meme moteur Jinja2 que les .nfo (`render.render_template`), mais
mecanisme PARALLELE au systeme categorie/registre -- une description n'est
pas un "type de media" comme video/audio/etc. (`declarative_profile.CATEGORIES`),
donc ce module ne passe jamais par `register`/`registry`, juste un rendu
direct."""
from __future__ import annotations

from typing import Any

from . import render


def render_upload_description(profile: str, context: dict[str, Any]) -> str:
    """Rend `profiles/<profile>/templates/upload_description.j2` avec le
    contexte fourni (titre, synopsis, affiche, genres, casting, infos
    qualite -- voir AUTOMATION.md pour la liste complete des cles
    attendues). Editable comme n'importe quel gabarit de profil."""
    return render.render_template(profile, "upload_description", context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_description.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/profiles/c411/templates/upload_description.j2 nfogen/upload_description.py tests/test_upload_description.py
git commit -m "feat: gabarit BBCode de description d'upload + render_upload_description()"
```

---

### Task 9: `nfogen/c411_upload_client.py` — anti-doublon

**Files:**
- Create: `nfogen/c411_upload_client.py`
- Test: `tests/test_c411_upload_client.py`

**Interfaces:**
- Produces: `C411UploadError`, `C411UploadClient(api_key, base_url="https://c411.org/api", http_client=None, timeout=30.0)` avec `check_duplicates(tmdb_id: int, tmdb_type: str) -> list[dict[str, Any]]`, `close()`, `__enter__`/`__exit__`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_c411_upload_client.py` :

```python
"""Tests de nfogen.c411_upload_client (AUTOMATION.md, sous-projet 5).
Client DELIBEREMENT specifique a C411 (pas de standard partage comme
Torznab, voir decision 4) -- verification anti-doublon dans cette tache,
creation/mise a jour de brouillon dans la Tache 10."""
from __future__ import annotations

import httpx
import pytest

from nfogen.c411_upload_client import C411UploadClient, C411UploadError


def _client_with_handler(handler) -> C411UploadClient:
    return C411UploadClient(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_check_duplicates_returns_existing_releases():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/torrents/by-tmdb"
        assert request.url.params.get("tmdbId") == "27205"
        assert request.url.params.get("tmdbType") == "movie"
        assert request.headers.get("authorization") == "Bearer test-key"
        return httpx.Response(200, json={
            "tmdbId": 27205, "tmdbType": "movie", "count": 1,
            "releases": [{"id": 48213, "name": "Inception", "infoHash": "abc123"}],
        })

    client = _client_with_handler(handler)
    releases = client.check_duplicates(27205, "movie")

    assert len(releases) == 1
    assert releases[0]["name"] == "Inception"


def test_check_duplicates_empty_when_no_release_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tmdbId": 1, "tmdbType": "tv", "count": 0, "releases": []})

    client = _client_with_handler(handler)
    assert client.check_duplicates(1, "tv") == []


def test_check_duplicates_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client_with_handler(handler)
    with pytest.raises(C411UploadError, match="[Dd]oublon"):
        client.check_duplicates(1, "movie")


def test_error_message_never_contains_the_api_key():
    secret_key = "25a31a6e545d4f8bf244ce44f717aac2064bfa26895297df1e5e430bf9b1c203"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(520, text="")

    client = C411UploadClient(
        api_key=secret_key, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(C411UploadError) as excinfo:
        client.check_duplicates(1, "movie")

    assert secret_key not in str(excinfo.value)


def test_client_requires_api_key():
    with pytest.raises(C411UploadError, match="[Cc]l[eé]"):
        C411UploadClient(api_key="")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_c411_upload_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.c411_upload_client'`.

- [ ] **Step 3: Write the implementation**

Create `nfogen/c411_upload_client.py` :

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_c411_upload_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/c411_upload_client.py tests/test_c411_upload_client.py
git commit -m "feat: nfogen/c411_upload_client.py - verification anti-doublon (GET /api/torrents/by-tmdb)"
```

---

### Task 10: `C411UploadClient` — création/mise à jour de brouillon

**Files:**
- Modify: `nfogen/c411_upload_client.py`
- Test: `tests/test_c411_upload_client.py`

**Interfaces:**
- Produces: `create_draft(*, torrent_bytes: bytes, nfo_bytes: bytes, title: str, description: str, category_id: int, subcategory_id: int, options: dict[str, Any], description_format: str = "standard", uploader_note: Optional[str] = None, tmdb_data: Optional[dict[str, Any]] = None) -> dict[str, Any]`, `update_draft(draft_id: int | str, **memes_champs_que_create_draft) -> dict[str, Any]`.

**⚠️ Point non vérifié (voir Global Constraints, à confirmer avant le premier essai réel)** : la doc API ne précise pas les noms exacts des champs JSON de `POST /api/user/drafts` — ce code suppose les mêmes noms que le formulaire multipart documenté (`torrent`, `nfo`, `title`, `description`, `categoryId`, `subcategoryId`, `options`, `descriptionFormat`, `uploaderNote`, `tmdbData`), avec `torrent`/`nfo` encodés en base64 (comportement textuel documenté : "Les fichiers torrent et NFO sont envoyés en base64 dans le body JSON"). **Avant de considérer cette tâche terminée, créer un vrai brouillon avec la clé API de l'utilisateur et vérifier/ajuster les noms de champs contre la vraie réponse.**

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_c411_upload_client.py`, ajouter :

```python
def test_create_draft_sends_base64_files_and_returns_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/user/drafts"
        assert request.method == "POST"
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    result = client.create_draft(
        torrent_bytes=b"torrent-bytes",
        nfo_bytes=b"nfo-bytes",
        title="Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM",
        description="[h2]Synopsis[/h2]...",
        category_id=1,
        subcategory_id=6,
        options={"1": [4], "2": 10},
    )

    assert result == {"id": 555, "url": "https://c411.org/user/drafts/555"}
    body = captured["body"]
    assert body["title"] == "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM"
    assert body["categoryId"] == 1
    assert body["subcategoryId"] == 6
    assert body["options"] == {"1": [4], "2": 10}
    assert body["descriptionFormat"] == "standard"
    assert base64.b64decode(body["torrent"]) == b"torrent-bytes"
    assert base64.b64decode(body["nfo"]) == b"nfo-bytes"


def test_create_draft_includes_optional_fields_when_given():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    client.create_draft(
        torrent_bytes=b"t", nfo_bytes=b"n", title="X", description="X" * 20,
        category_id=1, subcategory_id=6, options={},
        uploader_note="Note test", tmdb_data={"id": 27205, "type": "movie"},
    )

    assert captured["body"]["uploaderNote"] == "Note test"
    assert captured["body"]["tmdbData"] == {"id": 27205, "type": "movie"}


def test_create_draft_raises_a_clear_message_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid token"})

    client = _client_with_handler(handler)
    with pytest.raises(C411UploadError, match="scope"):
        client.create_draft(
            torrent_bytes=b"t", nfo_bytes=b"n", title="X", description="X" * 20,
            category_id=1, subcategory_id=6, options={},
        )


def test_update_draft_patches_the_existing_draft():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/user/drafts/555"
        assert request.method == "PATCH"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 555, "url": "https://c411.org/user/drafts/555"})

    client = _client_with_handler(handler)
    result = client.update_draft(
        555, torrent_bytes=b"t", nfo_bytes=b"n", title="X updated", description="X" * 20,
        category_id=1, subcategory_id=6, options={},
    )

    assert result == {"id": 555, "url": "https://c411.org/user/drafts/555"}
    assert captured["body"]["title"] == "X updated"
```

Ajouter `import base64` et `import json` en tête du fichier de test si absents.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_c411_upload_client.py -k "create_draft or update_draft" -v`
Expected: FAIL — `AttributeError: 'C411UploadClient' object has no attribute 'create_draft'`.

- [ ] **Step 3: Write the implementation**

Dans `nfogen/c411_upload_client.py`, ajouter `import base64` en tête, puis (après `check_duplicates`) :

```python
    def _draft_body(
        self,
        *,
        torrent_bytes: bytes,
        nfo_bytes: bytes,
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
            "torrent": base64.b64encode(torrent_bytes).decode("ascii"),
            "nfo": base64.b64encode(nfo_bytes).decode("ascii"),
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
        decision 6). `torrent_bytes`/`nfo_bytes` encodes en base64 dans le
        corps JSON (comportement documente par C411 pour cet endpoint)."""
        body = self._draft_body(
            torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes, title=title, description=description,
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
        -- voir AUTOMATION.md, decision 6)."""
        body = self._draft_body(
            torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes, title=title, description=description,
            category_id=category_id, subcategory_id=subcategory_id, options=options,
            description_format=description_format, uploader_note=uploader_note, tmdb_data=tmdb_data,
        )
        return self._handle_draft_response(
            "Mise à jour du brouillon",
            lambda: self._client.patch(
                f"{self._base_url}/user/drafts/{draft_id}", json=body, headers=self._headers()
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_c411_upload_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/c411_upload_client.py tests/test_c411_upload_client.py
git commit -m "feat: C411UploadClient.create_draft()/update_draft() - POST/PATCH /api/user/drafts"
```

---

### Task 11: `upload_prep.send_to_tracker()` — orchestration

**Files:**
- Modify: `nfogen/upload_prep.py`
- Test: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: tout ce qui précède (`c411_upload_options.build_category_ids`/`build_options`, `upload_description.render_upload_description`, `c411_upload_client.C411UploadClient`, `gapscan_config_store.effective_tracker`, `RadarrClient.get_movie_details`/`SonarrClient.get_series_details`, `rules.captures`, `rules_engine` via `profile_store.read_profile`).
- Produces: `SendResult` (dataclass : `draft_id: Any`, `draft_url: str`, `duplicate_warning: Optional[str]`), `send_to_tracker(*, release_name: str, staged_path: str, torrent_path: str, nfo_path: str, profile: str, media_type: str, radarr_movie_id: Optional[int] = None, sonarr_series_id: Optional[int] = None, tmdb_id: Optional[int] = None, tvdb_id: Optional[int] = None, genre: Optional[str] = None, season_number: Optional[int] = None, draft_id: Optional[Any] = None) -> SendResult`.

- [ ] **Step 1: Write the failing tests**

Lire d'abord les tests `test_commit_*` existants dans `tests/test_upload_prep.py` pour le pattern exact de `monkeypatch` déjà utilisé (`monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_tracker", ...)`, etc.), puis ajouter dans la même convention :

```python
def test_send_to_tracker_movie_creates_a_draft(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeRadarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_movie_details(self, movie_id):
            from nfogen.radarr_client import RadarrMovieDetails
            assert movie_id == 42
            return RadarrMovieDetails(overview="Synopsis test.", genres=["Action"])

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.RadarrClient", FakeRadarrClient)

    captured: dict = {}

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            captured["duplicates_checked"] = (tmdb_id, tmdb_type)
            return []

        def create_draft(self, **kwargs):
            captured["create_draft_kwargs"] = kwargs
            return {"id": 555, "url": "https://c411.org/user/drafts/555"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=42, tmdb_id=603,
    )

    assert result.draft_id == 555
    assert result.draft_url == "https://c411.org/user/drafts/555"
    assert result.duplicate_warning is None
    assert captured["duplicates_checked"] == (603, "movie")
    kwargs = captured["create_draft_kwargs"]
    assert kwargs["title"] == "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM"
    assert "Synopsis test." in kwargs["description"]
    assert kwargs["category_id"] == 1
    assert kwargs["subcategory_id"] == 6
    assert kwargs["options"] == {"2": 413}  # BluRay.HDLight, pas de langue reconnue dans ce nom de test


def test_send_to_tracker_series_without_tmdb_id_skips_duplicate_check_with_a_warning(tmp_path, monkeypatch):
    staged = tmp_path / "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM"
    staged.mkdir()
    torrent = tmp_path / "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeSonarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_series_details(self, series_id):
            from nfogen.sonarr_client import SonarrSeriesDetails
            return SonarrSeriesDetails(overview="Synopsis serie.")

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.SonarrClient", FakeSonarrClient)

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_draft(self, **kwargs):
            return {"id": 556, "url": "https://c411.org/user/drafts/556"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="series", sonarr_series_id=99, season_number=1,
        # tmdb_id absent : cas normal cote series, voir AUTOMATION.md decision 5
    )

    assert result.draft_id == 556
    assert result.duplicate_warning is not None
    assert "doublon" in result.duplicate_warning.lower()


def test_send_to_tracker_updates_an_existing_draft_when_draft_id_given(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeRadarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_movie_details(self, movie_id):
            from nfogen.radarr_client import RadarrMovieDetails
            return RadarrMovieDetails()

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.RadarrClient", FakeRadarrClient)

    captured: dict = {}

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def update_draft(self, draft_id, **kwargs):
            captured["draft_id"] = draft_id
            return {"id": draft_id, "url": f"https://c411.org/user/drafts/{draft_id}"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=1, tmdb_id=1, draft_id=555,
    )

    assert captured["draft_id"] == 555
    assert result.draft_id == 555


def test_send_to_tracker_requires_tracker_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker", lambda profile: None
    )
    with pytest.raises(ValueError, match="[Cc]l[eé]"):
        send_to_tracker(
            release_name="X", staged_path="/x.mkv", torrent_path="/x.torrent", nfo_path="/x.nfo",
            profile="c411", media_type="movie",
        )
```

(Ajouter `from nfogen.upload_prep import SendResult, send_to_tracker` à l'import existant de `tests/test_upload_prep.py` en tête de fichier.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -k send_to_tracker -v`
Expected: FAIL — `ImportError: cannot import name 'send_to_tracker' from 'nfogen.upload_prep'`.

- [ ] **Step 3: Write the implementation**

Dans `nfogen/upload_prep.py`, étendre les imports en tête de fichier :

```python
from . import engine, extract, file_staging, gapscan_config_store, tracker_profile
from . import c411_upload_options
from .c411_upload_client import C411UploadClient, C411UploadError
from .engine import propose_release_name
from .models import RenderContext
from .name_proposal import extract_team_tag, strip_ext
from .profile_store import read_profile
from .radarr_client import RadarrClient
from .registry import get_validator
from .rules import captures as rules_captures
from .sonarr_client import SonarrClient
from .upload_description import render_upload_description
```

Ajouter le dataclass `SendResult` (après `CommitResult`) :

```python
@dataclass
class SendResult:
    """Resultat de `send_to_tracker()` : le brouillon cree/mis a jour
    n'entre JAMAIS en file de moderation tout seul (voir AUTOMATION.md,
    sous-projet 5, decision 6) -- c'est a l'utilisateur de le finaliser
    sur le site du tracker. `duplicate_warning` : non None si la
    verification anti-doublon n'a pas pu avoir lieu ou a trouve une
    release existante -- jamais bloquant."""

    draft_id: Any
    draft_url: str
    duplicate_warning: Optional[str] = None
```

Ajouter `Any` à l'import `typing` en tête de fichier (`from typing import Any, Optional`).

Ajouter la fonction (à la fin du fichier) :

```python
def send_to_tracker(
    *,
    release_name: str,
    staged_path: str,
    torrent_path: str,
    nfo_path: str,
    profile: str = "c411",
    media_type: str = "movie",
    radarr_movie_id: Optional[int] = None,
    sonarr_series_id: Optional[int] = None,
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    genre: Optional[str] = None,
    season_number: Optional[int] = None,
    draft_id: Optional[Any] = None,
) -> SendResult:
    """Cree (ou met a jour si `draft_id` deja connu) un BROUILLON C411
    pour un groupe deja confirme par `commit_upload()` -- jamais une
    soumission reelle (voir AUTOMATION.md, sous-projet 5, decision 6).
    Recupere les metadonnees de presentation (synopsis/affiche/genres) A
    LA DEMANDE aupres de Radarr/Sonarr (jamais pendant le scan GapScan),
    rend la description BBCode, calcule categorie/sous-categorie/options
    depuis le release_name deja confirme, verifie les doublons (best
    effort, jamais bloquant), puis appelle l'API."""
    tracker_config = gapscan_config_store.effective_tracker(profile)
    if tracker_config is None:
        raise ValueError(
            f"Clé API du tracker '{profile}' non configurée (PUT /gapscan/config)."
        )
    api_key, base_url = tracker_config

    # Metadonnees de presentation : a la demande, jamais pendant le scan
    # (voir AUTOMATION.md, decision 1).
    overview, poster_url, genres, directors, cast = "", None, [], [], []
    if media_type == "movie" and radarr_movie_id is not None:
        radarr_config = gapscan_config_store.effective_radarr()
        if radarr_config:
            radarr = RadarrClient(*radarr_config)
            try:
                details = radarr.get_movie_details(radarr_movie_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
            finally:
                radarr.close()
    elif media_type == "series" and sonarr_series_id is not None:
        sonarr_config = gapscan_config_store.effective_sonarr()
        if sonarr_config:
            sonarr = SonarrClient(*sonarr_config)
            try:
                details = sonarr.get_series_details(sonarr_series_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
            finally:
                sonarr.close()

    # Infos qualite (source/langue/codec/resolution) : extraites du
    # release_name DEJA CONFIRME via les memes tokens que la validation
    # (sous-projet 4b), pas redemandees au moteur de nommage.
    schema = read_profile(profile)["rules"].get("video", {})
    capture_values = rules_captures(release_name, schema)

    description = render_upload_description(
        profile,
        {
            "title": release_name, "overview": overview, "poster_url": poster_url,
            "genres": genres, "directors": directors, "cast": cast,
            "resolution": capture_values.get("resolution", ""),
            "source": capture_values.get("source", ""),
            "video_codec": capture_values.get("video_codec", ""),
            "audio_languages": [],
        },
    )

    category_id, subcategory_id = c411_upload_options.build_category_ids(profile, media_type, genre)
    if category_id is None or subcategory_id is None:
        raise ValueError(
            f"Catégorie/sous-catégorie non configurées pour le profil '{profile}' "
            f"(rules.json -> tracker.upload.subcategory_id, media_type='{media_type}')."
        )
    options = c411_upload_options.build_options(profile, capture_values, release_name, season_number)

    torrent_bytes = Path(torrent_path).read_bytes()
    nfo_bytes = Path(nfo_path).read_bytes()

    upload_client = C411UploadClient(api_key, base_url=base_url.rstrip("/") + "/api")
    try:
        duplicate_warning = None
        if tmdb_id is not None:
            tmdb_type = "movie" if media_type == "movie" else "tv"
            try:
                releases = upload_client.check_duplicates(tmdb_id, tmdb_type)
                if releases:
                    duplicate_warning = (
                        f"{len(releases)} release(s) déjà approuvée(s) pour cet identifiant TMDB "
                        "sur le tracker — vérifie qu'il ne s'agit pas d'un doublon avant de finaliser."
                    )
            except C411UploadError as exc:
                duplicate_warning = f"Vérification des doublons impossible : {exc}"
        else:
            duplicate_warning = (
                "Vérification des doublons non effectuée : identifiant TMDB inconnu pour ce média."
            )

        tmdb_data = {"id": tmdb_id, "type": "movie" if media_type == "movie" else "tv"} if tmdb_id else None

        if draft_id is not None:
            response = upload_client.update_draft(
                draft_id, torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes, title=release_name,
                description=description, category_id=category_id, subcategory_id=subcategory_id,
                options=options, tmdb_data=tmdb_data,
            )
        else:
            response = upload_client.create_draft(
                torrent_bytes=torrent_bytes, nfo_bytes=nfo_bytes, title=release_name,
                description=description, category_id=category_id, subcategory_id=subcategory_id,
                options=options, tmdb_data=tmdb_data,
            )
    finally:
        upload_client.close()

    return SendResult(
        draft_id=response.get("id"), draft_url=response.get("url", ""),
        duplicate_warning=duplicate_warning,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "feat: upload_prep.send_to_tracker() - orchestration complete (brouillon C411)"
```

---

### Task 12: `POST /gapscan/prepare-upload/send`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `upload_prep.send_to_tracker(...)` (Tâche 11).
- Produces: `POST /gapscan/prepare-upload/send` → `{"draft_id": ..., "draft_url": ..., "duplicate_warning": ...}`.

- [ ] **Step 1: Write the failing tests**

Lire d'abord les tests `test_prepare_upload_commit_*` existants dans `tests/test_api.py` pour le pattern exact (`reload_api`, fixtures, headers), puis ajouter dans la même convention :

```python
def test_prepare_upload_send_creates_a_draft(reload_api, tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(
        mod.upload_prep, "send_to_tracker",
        lambda **kwargs: mod.upload_prep.SendResult(draft_id=555, draft_url="https://c411.org/user/drafts/555"),
    )
    client = TestClient(mod.app)

    resp = client.post(
        "/gapscan/prepare-upload/send",
        json={
            "release_name": "Movie.2020.BluRay-TEAM",
            "staged_path": str(staged), "torrent_path": str(torrent), "nfo_path": str(nfo),
            "profile": "c411", "media_type": "movie", "radarr_movie_id": 42, "tmdb_id": 603,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["draft_id"] == 555
    assert body["draft_url"] == "https://c411.org/user/drafts/555"
    assert body["duplicate_warning"] is None


def test_prepare_upload_send_requires_auth_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post("/gapscan/prepare-upload/send", json={
        "release_name": "X", "staged_path": "/x.mkv", "torrent_path": "/x.torrent", "nfo_path": "/x.nfo",
    })
    assert resp.status_code == 401


def test_prepare_upload_send_requires_gapscan_available(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/prepare-upload/send", json={
        "release_name": "X", "staged_path": "/x.mkv", "torrent_path": "/x.torrent", "nfo_path": "/x.nfo",
    })
    assert resp.status_code == 501
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k prepare_upload_send -v`
Expected: FAIL — `404 Not Found` (route pas encore enregistrée).

- [ ] **Step 3: Write the implementation**

Dans `nfogen/api.py`, ajouter après `gapscan_prepare_upload_commit` :

```python
class PrepareUploadSendRequest(BaseModel):
    release_name: str
    staged_path: str
    torrent_path: str
    nfo_path: str
    profile: str = "c411"
    media_type: str = "movie"
    radarr_movie_id: Optional[int] = None
    sonarr_series_id: Optional[int] = None
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    genre: Optional[str] = None
    season_number: Optional[int] = None
    draft_id: Optional[Any] = None


@app.post("/gapscan/prepare-upload/send", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_send(req: PrepareUploadSendRequest) -> dict[str, Any]:
    """Cree (ou met a jour) un BROUILLON C411 -- jamais une soumission
    reelle en moderation (voir AUTOMATION.md, sous-projet 5, decision 6)."""
    _require_gapscan_available()
    result = _run_upload_prep(
        upload_prep.send_to_tracker,
        release_name=req.release_name, staged_path=req.staged_path, torrent_path=req.torrent_path,
        nfo_path=req.nfo_path, profile=req.profile, media_type=req.media_type,
        radarr_movie_id=req.radarr_movie_id, sonarr_series_id=req.sonarr_series_id,
        tmdb_id=req.tmdb_id, tvdb_id=req.tvdb_id, genre=req.genre, season_number=req.season_number,
        draft_id=req.draft_id,
    )
    return asdict(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check nfogen/ tests/
git add nfogen/api.py tests/test_api.py
git commit -m "feat: POST /gapscan/prepare-upload/send - cree/met a jour un brouillon C411"
```

---

### Task 13: Frontend — types + client API

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `GapResult.radarr_movie_id: number | null`, `GapResult.sonarr_series_id: number | null` ; `SendToTrackerResult { draft_id: number | string; draft_url: string; duplicate_warning: string | null }` ; `sendToTracker(params: {...}) -> Promise<SendToTrackerResult>`.

- [ ] **Step 1: Write the failing tests**

Dans `frontend/src/api/client.test.ts`, ajouter (mirroring le pattern déjà utilisé pour `prepareUploadCommit` — lire ce test existant d'abord pour la convention exacte de mock/assertion) :

```ts
it("sendToTracker POST le bon corps et renvoie le resultat", async () => {
  mockFetchOnce({ draft_id: 555, draft_url: "https://c411.org/user/drafts/555", duplicate_warning: null });

  const result = await sendToTracker({
    releaseName: "Movie.2020.BluRay-TEAM",
    stagedPath: "/staging/Movie.2020.BluRay-TEAM.mkv",
    torrentPath: "/staging/Movie.2020.BluRay-TEAM.torrent",
    nfoPath: "/staging/Movie.2020.BluRay-TEAM.nfo",
    profile: "c411",
    mediaType: "movie",
    radarrMovieId: 42,
    tmdbId: 603,
  });

  expect(result).toEqual({ draft_id: 555, draft_url: "https://c411.org/user/drafts/555", duplicate_warning: null });
  const [, init] = vi.mocked(fetch).mock.calls[0];
  const body = JSON.parse((init as RequestInit).body as string);
  expect(body.release_name).toBe("Movie.2020.BluRay-TEAM");
  expect(body.radarr_movie_id).toBe(42);
  expect(body.tmdb_id).toBe(603);
});

it("sendToTracker envoie draft_id quand fourni (mise a jour)", async () => {
  mockFetchOnce({ draft_id: 555, draft_url: "https://c411.org/user/drafts/555", duplicate_warning: null });

  await sendToTracker({
    releaseName: "X", stagedPath: "/x", torrentPath: "/x.torrent", nfoPath: "/x.nfo",
    profile: "c411", mediaType: "movie", draftId: 555,
  });

  const [, init] = vi.mocked(fetch).mock.calls[0];
  const body = JSON.parse((init as RequestInit).body as string);
  expect(body.draft_id).toBe(555);
});
```

Ajouter `sendToTracker` à l'import depuis `"./client"` en tête du fichier de test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `sendToTracker` n'est pas exporté par `./client`.

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/api/types.ts`, `GapResult` gagne (après `sonarr_series_id`... c'est-à-dire, insérer près des autres identifiants existants comme `tmdb_id`/`tvdb_id`) :

```ts
  radarr_movie_id: number | null;
  sonarr_series_id: number | null;
```

Puis, après `UploadCommitResult`, ajouter :

```ts
export interface SendToTrackerResult {
  draft_id: number | string;
  draft_url: string;
  duplicate_warning: string | null;
}
```

Dans `frontend/src/api/client.ts`, ajouter (après `prepareUploadCommit`) :

```ts
/** Cree (ou met a jour si draftId deja connu) un BROUILLON sur le tracker
 * pour UN groupe deja confirme -- n'entre JAMAIS en file de moderation
 * tout seul (voir AUTOMATION.md, sous-projet 5, decision 6). */
export function sendToTracker(params: {
  releaseName: string;
  stagedPath: string;
  torrentPath: string;
  nfoPath: string;
  profile?: string;
  mediaType?: "movie" | "series";
  radarrMovieId?: number;
  sonarrSeriesId?: number;
  tmdbId?: number;
  tvdbId?: number;
  genre?: "anime" | "documentaire";
  seasonNumber?: number;
  draftId?: number | string;
}): Promise<SendToTrackerResult> {
  return request<SendToTrackerResult>("/gapscan/prepare-upload/send", {
    method: "POST",
    body: JSON.stringify({
      release_name: params.releaseName,
      staged_path: params.stagedPath,
      torrent_path: params.torrentPath,
      nfo_path: params.nfoPath,
      profile: params.profile ?? "c411",
      media_type: params.mediaType ?? "movie",
      radarr_movie_id: params.radarrMovieId,
      sonarr_series_id: params.sonarrSeriesId,
      tmdb_id: params.tmdbId,
      tvdb_id: params.tvdbId,
      genre: params.genre,
      season_number: params.seasonNumber,
      draft_id: params.draftId,
    }),
  });
}
```

Ajouter `SendToTrackerResult` à l'import de types déjà présent en tête de `client.ts`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: all PASS.

- [ ] **Step 5: `tsc` + commit**

Note : `GapScanPage.tsx`/`UploadPrepPanel.tsx` ne connaissent pas encore ces nouveaux champs — `tsc` peut afficher des erreurs préexistantes non liées à cette tâche ailleurs (Tâches 14-15) ; confirmer que les seules erreurs sont dans ces deux fichiers.

```bash
cd frontend
npx vitest run src/api/client.test.ts
npx tsc --noEmit -p tsconfig.app.json
git add src/api/types.ts src/api/client.ts src/api/client.test.ts
git commit -m "feat: client API sendToTracker() - creation/mise a jour de brouillon"
```

---

### Task 14: `GapScanPage.tsx` transmet les nouveaux identifiants

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Test: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Produces: `activeUpload` gagne `mediaType`, `radarrMovieId`, `sonarrSeriesId`, `tmdbId`, `tvdbId`, `genre`, `seasonNumber` — transmis à `<UploadPrepPanel>` (Tâche 15).

- [ ] **Step 1: Write the failing test**

Dans `frontend/src/pages/GapScanPage.test.tsx`, localiser le test "affiche un bouton Préparer l'upload... ouvre le panneau" (mock de `UploadPrepPanel` déjà présent en tête de fichier) et étendre le mock pour capter les nouvelles props, puis ajouter :

```tsx
vi.mock("../components/UploadPrepPanel", () => ({
  default: (props: {
    title: string; onClose: () => void; mediaType?: string; tmdbId?: number | null;
  }) => (
    <div>
      <p>Panneau upload pour {props.title}</p>
      <p>media_type={props.mediaType}</p>
      <p>tmdb_id={String(props.tmdbId)}</p>
      <button onClick={props.onClose}>Fermer le panneau</button>
    </div>
  ),
}));
```

(Remplace le mock existant du fichier — vérifier son contenu actuel exact avant de le modifier, garder la même forme pour les props déjà utilisées par les tests existants comme `title`/`onClose`.) Puis ajouter :

```tsx
it("transmet media_type/tmdb_id/radarr_movie_id au panneau Preparer l'upload", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanResults).mockResolvedValue({
    items: [{ ...MATRIX_GAP, local_paths: ["/media/matrix.mkv"], path_resolved: true, radarr_movie_id: 42 }],
    total: 1,
  });

  renderPage();

  const button = await screen.findByRole("button", { name: /Préparer l'upload/i });
  await user.click(button);

  expect(await screen.findByText("media_type=movie")).toBeInTheDocument();
  expect(await screen.findByText("tmdb_id=603")).toBeInTheDocument();
});
```

(`MATRIX_GAP` existe déjà dans ce fichier de test — vérifier qu'il inclut déjà `tmdb_id: "603"` comme constaté précédemment dans ce fichier ; ajouter `radarr_movie_id: null, sonarr_series_id: null` à sa définition de base si le typage `GapResult` les rend requis après la Tâche 13.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: FAIL — `media_type=undefined` (prop pas encore transmise).

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/pages/GapScanPage.tsx`, `activeUpload` gagne les nouveaux champs :

```tsx
  const [activeUpload, setActiveUpload] = useState<{
    title: string;
    localPaths: string[];
    mediaType: "movie" | "series";
    radarrMovieId: number | null;
    sonarrSeriesId: number | null;
    tmdbId: number | null;
    tvdbId: number | null;
    genre: "anime" | "documentaire" | null;
    seasonNumber: number | null;
  } | null>(null);
```

Le `onClick` du bouton "Préparer l'upload" (ligne ~617) devient :

```tsx
                      onClick={() =>
                        setActiveUpload({
                          title: r.title,
                          localPaths: r.local_paths,
                          mediaType: r.media_type,
                          radarrMovieId: r.radarr_movie_id,
                          sonarrSeriesId: r.sonarr_series_id,
                          tmdbId: r.tmdb_id ? Number(r.tmdb_id) : null,
                          tvdbId: r.tvdb_id,
                          genre: r.genre,
                          seasonNumber: r.season_number,
                        })
                      }
```

Et le rendu du panneau (ligne ~661) gagne les nouvelles props :

```tsx
        <UploadPrepPanel
          key={activeUpload.localPaths.join("|")}
          localPaths={activeUpload.localPaths}
          title={activeUpload.title}
          mediaType={activeUpload.mediaType}
          radarrMovieId={activeUpload.radarrMovieId}
          sonarrSeriesId={activeUpload.sonarrSeriesId}
          tmdbId={activeUpload.tmdbId}
          tvdbId={activeUpload.tvdbId}
          genre={activeUpload.genre}
          seasonNumber={activeUpload.seasonNumber}
          onClose={() => setActiveUpload(null)}
        />
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: FAIL encore normal ici tant que `UploadPrepPanel` (Tâche 15) n'accepte pas ces props en TypeScript — le test utilise un MOCK de `UploadPrepPanel` donc le test lui-même doit PASSER (le mock accepte n'importe quelle prop). Si `tsc` se plaint côté `GapScanPage.tsx` sur le typage de `UploadPrepPanelProps` réel (pas le mock), c'est attendu jusqu'à la Tâche 15 — le test runtime (vitest) doit déjà passer à cette étape.

- [ ] **Step 5: Commit**

```bash
cd frontend
npx vitest run src/pages/GapScanPage.test.tsx
git add src/pages/GapScanPage.tsx src/pages/GapScanPage.test.tsx
git commit -m "feat: GapScanPage transmet media_type/ids/genre/saison au panneau upload"
```

---

### Task 15: `UploadPrepPanel.tsx` — bouton "Envoyer à C411"

**Files:**
- Modify: `frontend/src/components/UploadPrepPanel.tsx`
- Test: `frontend/src/components/UploadPrepPanel.test.tsx`

**Interfaces:**
- Consumes: `sendToTracker()` (Tâche 13), nouvelles props de la Tâche 14.
- Produces: un bouton "Envoyer à C411" par groupe confirmé, affichant le lien du brouillon (et l'avertissement anti-doublon si présent) après succès.

- [ ] **Step 1: Write the failing tests**

Dans `frontend/src/components/UploadPrepPanel.test.tsx`, ajouter `sendToTracker` au mock `vi.mock("../api/client", ...)` existant et à son import, puis ajouter :

```tsx
it("affiche le bouton Envoyer a C411 seulement apres confirmation, et affiche le lien du brouillon", async () => {
  const user = userEvent.setup();
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-TEAM",
    staged_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-TEAM.mkv",
    torrent_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-TEAM.torrent",
    nfo_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-TEAM.nfo",
  });
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 555, draft_url: "https://c411.org/user/drafts/555", duplicate_warning: null,
  });

  render(
    <ProfileProvider>
      <UploadPrepPanel
        localPaths={["/media/movie.mkv"]} title="Movie" mediaType="movie"
        radarrMovieId={42} sonarrSeriesId={null} tmdbId={603} tvdbId={null}
        genre={null} seasonNumber={null} onClose={() => {}}
      />
    </ProfileProvider>,
  );

  expect(screen.queryByRole("button", { name: /Envoyer à C411/i })).not.toBeInTheDocument();

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  const sendButton = await screen.findByRole("button", { name: /Envoyer à C411/i });
  await user.click(sendButton);

  expect(await screen.findByText(/c411\.org\/user\/drafts\/555/)).toBeInTheDocument();
  expect(sendToTracker).toHaveBeenCalledWith(
    expect.objectContaining({
      releaseName: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-TEAM",
      mediaType: "movie", radarrMovieId: 42, tmdbId: 603,
    }),
  );
});

it("affiche l'avertissement anti-doublon quand present", async () => {
  const user = userEvent.setup();
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-TEAM",
    staged_path: "/staging/x.mkv", torrent_path: "/staging/x.torrent", nfo_path: "/staging/x.nfo",
  });
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 555, draft_url: "https://c411.org/user/drafts/555",
    duplicate_warning: "1 release(s) déjà approuvée(s) pour cet identifiant TMDB...",
  });

  render(
    <ProfileProvider>
      <UploadPrepPanel
        localPaths={["/media/movie.mkv"]} title="Movie" mediaType="movie"
        radarrMovieId={42} sonarrSeriesId={null} tmdbId={603} tvdbId={null}
        genre={null} seasonNumber={null} onClose={() => {}}
      />
    </ProfileProvider>,
  );

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Envoyer à C411/i }));

  expect(await screen.findByText(/déjà approuvée/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: FAIL — pas de bouton "Envoyer à C411" dans le rendu actuel.

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/components/UploadPrepPanel.tsx`, imports :

```ts
import { prepareUploadCommit, prepareUploadPreview, sendToTracker } from "../api/client";
import { ApiError } from "../api/types";
import type { SendToTrackerResult, UploadCommitResult, UploadGroupProposal } from "../api/types";
```

La signature du composant gagne les nouvelles props :

```ts
export default function UploadPrepPanel({
  localPaths,
  title,
  mediaType,
  radarrMovieId,
  sonarrSeriesId,
  tmdbId,
  tvdbId,
  genre,
  seasonNumber,
  onClose,
}: {
  localPaths: string[];
  title: string;
  mediaType: "movie" | "series";
  radarrMovieId: number | null;
  sonarrSeriesId: number | null;
  tmdbId: number | null;
  tvdbId: number | null;
  genre: "anime" | "documentaire" | null;
  seasonNumber: number | null;
  onClose: () => void;
}) {
```

Nouvel état (après `commitErrors`) :

```ts
  const [sending, setSending] = useState<number | null>(null);
  const [sendResults, setSendResults] = useState<Record<number, SendToTrackerResult>>({});
  const [sendErrors, setSendErrors] = useState<Record<number, string>>({});
```

Nouveau handler (après `handleConfirm`) :

```ts
  async function handleSend(index: number) {
    const commit = commitResults[index];
    if (!commit) return;
    setSending(index);
    setSendErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const result = await sendToTracker({
        releaseName: commit.release_name,
        stagedPath: commit.staged_path,
        torrentPath: commit.torrent_path,
        nfoPath: commit.nfo_path,
        profile,
        mediaType,
        radarrMovieId: radarrMovieId ?? undefined,
        sonarrSeriesId: sonarrSeriesId ?? undefined,
        tmdbId: tmdbId ?? undefined,
        tvdbId: tvdbId ?? undefined,
        genre: genre ?? undefined,
        seasonNumber: seasonNumber ?? undefined,
        draftId: sendResults[index]?.draft_id,
      });
      setSendResults((prev) => ({ ...prev, [index]: result }));
    } catch (e) {
      setSendErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Envoi impossible.",
      }));
    } finally {
      setSending(null);
    }
  }
```

Dans le JSX, après le bloc `{commitResults[index] && (...)}` existant (mise en scène/torrent/NFO), ajouter le bouton et le résultat :

```tsx
          {commitResults[index] && !sendResults[index] && (
            <button
              type="button"
              onClick={() => handleSend(index)}
              disabled={sending === index}
              className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
            >
              {sending === index ? "Envoi…" : "Envoyer à C411"}
            </button>
          )}
          {sendErrors[index] && <p className="text-xs text-crit">{sendErrors[index]}</p>}
          {sendResults[index] && (
            <div className="space-y-1 text-xs">
              <p className="text-good">
                Brouillon créé : <a href={sendResults[index].draft_url} className="underline" target="_blank" rel="noreferrer">
                  {sendResults[index].draft_url}
                </a>
                <br />
                Finalise-le sur le site pour l'envoyer réellement en modération.
              </p>
              {sendResults[index].duplicate_warning && (
                <p className="text-warn">⚠ {sendResults[index].duplicate_warning}</p>
              )}
            </div>
          )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Full frontend suite + `tsc`, then commit**

```bash
cd frontend
npx vitest run
npx tsc --noEmit -p tsconfig.app.json
git add src/components/UploadPrepPanel.tsx src/components/UploadPrepPanel.test.tsx
git commit -m "feat: bouton Envoyer a C411 - cree un brouillon apres confirmation locale"
```

At this point, run the full backend suite (`pytest`, `ruff check nfogen/ tests/`) AND the full frontend suite (`npx vitest run`, `npx tsc --noEmit -p tsconfig.app.json`) one final time together — this is the "merged result" check before handing off to `finishing-a-development-branch`.

---

## Post-implementation documentation (not a TDD task, do last)

- [ ] Mettre à jour AUTOMATION.md, sous-projet 5 : passer de "Conception complète (2026-09-04)" à "Livré (\<date\>)", avec un lien vers ce plan et la liste des écarts découverts en implémentant (au minimum : `GapResult` gagne `radarr_movie_id`/`sonarr_series_id` plutôt que les métadonnées elles-mêmes, voir Tâche 1).
- [ ] Mettre à jour le tableau de décomposition (sous-projet 5 : "Conçu" → "Livré").
- [ ] `CHANGELOG.md` : nouvelle entrée `### Ajouté` — brouillon C411 (bouton "Envoyer à C411"), métadonnées Radarr/Sonarr à la demande, mapping catégorie/options déclaratif par profil.
- [ ] Rappeler à l'utilisateur, dans le message de fin de session, les **deux points non vérifiés** (Global Constraints) à confirmer en conditions réelles avant une vraie utilisation : noms de champs exacts du corps JSON de `POST /api/user/drafts`, et distinction (ou non) Documentaire film/série côté `GET /api/categories`.
