# GapScan : résolution de chemins NAS (sous-projet 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Étant donné un fichier connu de Sonarr/Radarr, obtenir et valider (à chaque scan GapScan) un chemin local réel que nfogen peut ouvrir en lecture — que nfogen tourne sur la même machine qu'eux ou non.

**Architecture:** Un nouveau module pur `nfogen/path_mapping.py` (résolution par plus long préfixe + validation filesystem, aucune dépendance sur le reste du projet). `gapscan_config_store.py` stocke une table de mapping `{prefixe_distant: prefixe_local}` par connexion (Sonarr, Radarr), au même endroit que le reste de la config GapScan. `radarr_client.py`/`sonarr_client.py` exposent désormais le chemin brut rapporté par l'API (absent aujourd'hui). `gapscan.py` résout+valide ce chemin à chaque scan (y compris quand le verdict C411 est repris tel quel en mode incrémental — la validation de chemin, elle, est TOUJOURS fraîche). Le frontend expose la config des mappings (réutilise `KeyValueEditor`, déjà générique) et un indicateur de statut par ligne de résultat.

**Tech Stack:** Python 3.10+ (dataclasses, `os.path`), FastAPI, React + TypeScript, pytest, Vitest.

**Spec:** [AUTOMATION.md](../../../AUTOMATION.md), section "Sous-projet 1 : Accès NAS en lecture seule (résolution de chemins)".

## Global Constraints

- Le fichier média source n'est **jamais** modifié/renommé/déplacé — ce plan est strictement lecture seule sur les fichiers réels.
- La table de mapping est **par connexion** (Sonarr et Radarr ont chacune la leur), pas une table globale unique.
- Résolution par **le plus long préfixe** qui correspond, avec limite de répertoire respectée (`/data/media2` ne doit jamais matcher le préfixe `/data/media`).
- Sans mapping configuré (table vide), le chemin distant est utilisé tel quel — comportement par défaut, pas une erreur.
- Validation du chemin **à chaque scan GapScan** — y compris pour un titre dont le verdict C411 est repris tel quel en mode incrémental (voir `gapscan_runner.py`/`_can_reuse`) : la fraîcheur de la validation de chemin est indépendante de celle du verdict C411.
- Pas de détection automatique du bon chemin local (pas de recherche par taille/hash) — config manuelle uniquement, comme les "Remote Path Mappings" de Sonarr/Radarr eux-mêmes.
- TDD strict : test en échec confirmé (RED) avant chaque implémentation. `pytest -q` et `ruff check .` propres avant chaque commit ; `npx vitest run`, `npx tsc --noEmit`, `npm run lint` propres avant chaque commit touchant `frontend/`.
- Style du projet : commentaires en français, denses sur le "pourquoi" pas le "quoi", jamais de TODO laissé dans le code.

---

### Task 1: `nfogen/path_mapping.py` — résolution de chemin + validation filesystem

**Files:**
- Create: `nfogen/path_mapping.py`
- Test: `tests/test_path_mapping.py`

**Interfaces:**
- Produces: `resolve_path(remote_path: str, mappings: dict[str, str]) -> str`, `resolve_and_validate(remote_paths: list[str], mappings: dict[str, str]) -> tuple[list[str], bool, Optional[str]]`. Ces deux fonctions sont consommées par la Task 5 (`gapscan.py`).

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_path_mapping.py` :

```python
"""Tests de nfogen.path_mapping (resolution de chemins Sonarr/Radarr vers un
chemin local, meme principe que les "Remote Path Mappings" de Sonarr/Radarr
eux-memes -- voir AUTOMATION.md, sous-projet 1)."""
from __future__ import annotations

from nfogen.path_mapping import resolve_and_validate, resolve_path


def test_resolve_path_without_mapping_returns_input_unchanged():
    assert resolve_path("/data/media/Matrix.mkv", {}) == "/data/media/Matrix.mkv"


def test_resolve_path_substitutes_matching_prefix():
    mappings = {"/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media/Matrix.mkv", mappings) == "/mnt/nas/media/Matrix.mkv"


def test_resolve_path_uses_the_longest_matching_prefix():
    mappings = {"/data": "/mnt/wrong", "/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media/Matrix.mkv", mappings) == "/mnt/nas/media/Matrix.mkv"


def test_resolve_path_does_not_confuse_a_sibling_directory():
    """'/data/media2' ne doit pas matcher le prefixe '/data/media' juste
    parce qu'il commence par la meme chaine -- limite de repertoire."""
    mappings = {"/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media2/Matrix.mkv", mappings) == "/data/media2/Matrix.mkv"


def test_resolve_path_matches_the_prefix_exactly():
    mappings = {"/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media", mappings) == "/mnt/nas/media"


def test_resolve_and_validate_returns_error_when_no_remote_paths():
    resolved, ok, error = resolve_and_validate([], {})
    assert resolved == []
    assert ok is False
    assert "Aucun chemin" in error


def test_resolve_and_validate_ok_when_file_exists_and_readable(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("contenu")
    resolved, ok, error = resolve_and_validate([str(f)], {})
    assert resolved == [str(f)]
    assert ok is True
    assert error is None


def test_resolve_and_validate_fails_when_file_missing(tmp_path):
    missing = str(tmp_path / "absent.mkv")
    resolved, ok, error = resolve_and_validate([missing], {})
    assert ok is False
    assert "introuvable" in error
    assert missing in error


def test_resolve_and_validate_applies_mapping_before_checking(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("contenu")
    mappings = {"/data/media": str(tmp_path)}
    resolved, ok, error = resolve_and_validate(["/data/media/Matrix.mkv"], mappings)
    assert resolved == [str(f)]
    assert ok is True


def test_resolve_and_validate_stops_at_the_first_missing_file(tmp_path):
    f = tmp_path / "E01.mkv"
    f.write_text("contenu")
    missing = str(tmp_path / "E02.mkv")
    resolved, ok, error = resolve_and_validate([str(f), missing], {})
    assert ok is False
    assert missing in error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_path_mapping.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'nfogen.path_mapping'`

- [ ] **Step 3: Write the implementation**

Créer `nfogen/path_mapping.py` :

```python
"""Resolution de chemins distants (Sonarr/Radarr) vers un chemin local que
nfogen peut ouvrir -- meme principe que les "Remote Path Mappings" de
Sonarr/Radarr eux-memes pour leur client de telechargement (voir
AUTOMATION.md, sous-projet 1). Sans mapping configure, le chemin distant
est utilise tel quel (deploiement a chemins identiques, ex. nfogen sur le
meme hote que Sonarr/Radarr).
"""
from __future__ import annotations

import os
from typing import Optional


def _matches_prefix(path: str, prefix: str) -> bool:
    """`True` si `path` est `prefix` lui-meme, ou est sous `prefix` (limite
    de repertoire respectee) -- un simple `str.startswith` confondrait a
    tort `/data/media2` avec le prefixe `/data/media`."""
    prefix = prefix.rstrip("/\\")
    if not prefix:
        return False
    return path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "\\")


def resolve_path(remote_path: str, mappings: dict[str, str]) -> str:
    """Substitue le prefixe distant le plus long de `mappings` qui
    correspond a `remote_path` par son equivalent local. Sans
    correspondance, `remote_path` est renvoye tel quel."""
    best_prefix: Optional[str] = None
    for remote_prefix in mappings:
        if _matches_prefix(remote_path, remote_prefix) and (
            best_prefix is None or len(remote_prefix) > len(best_prefix)
        ):
            best_prefix = remote_prefix
    if best_prefix is None:
        return remote_path
    local_prefix = mappings[best_prefix].rstrip("/\\")
    remainder = remote_path[len(best_prefix.rstrip("/\\")):]
    return local_prefix + remainder


def resolve_and_validate(
    remote_paths: list[str], mappings: dict[str, str]
) -> tuple[list[str], bool, Optional[str]]:
    """`(chemins_locaux, ok, erreur)`. `ok` est faux si `remote_paths` est
    vide (Sonarr/Radarr n'a fourni aucun chemin) ou si un des chemins
    resolus est introuvable/non lisible -- jamais d'exception levee, un
    probleme de chemin ne doit pas faire planter un scan complet (meme
    logique que les erreurs C411, voir gapscan.py)."""
    if not remote_paths:
        return [], False, "Aucun chemin connu pour ce fichier (Sonarr/Radarr ne l'a pas fourni)."
    resolved = [resolve_path(p, mappings) for p in remote_paths]
    for local_path in resolved:
        if not os.path.isfile(local_path):
            return resolved, False, f"Fichier introuvable apres resolution : {local_path}"
        if not os.access(local_path, os.R_OK):
            return resolved, False, f"Fichier non lisible : {local_path}"
    return resolved, True, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_path_mapping.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Lint**

Run: `ruff check nfogen/path_mapping.py tests/test_path_mapping.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add nfogen/path_mapping.py tests/test_path_mapping.py
git commit -m "AUTOMATION sous-projet 1 (1/6) : nfogen/path_mapping.py

Resolution par plus long prefixe (limite de repertoire respectee) +
validation filesystem, module pur sans dependance sur le reste du
projet. Voir AUTOMATION.md."
```

---

### Task 2: `nfogen/gapscan_config_store.py` — stockage des mappings de chemins

**Files:**
- Modify: `nfogen/gapscan_config_store.py`
- Test: `tests/test_gapscan_config_store.py`
- Test: `tests/test_api.py` (une assertion existante en dict exact casse dès cette task — voir Step 5)

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `write(..., sonarr_path_mappings: Optional[dict[str, str]] = None, radarr_path_mappings: Optional[dict[str, str]] = None)`, `effective_sonarr_path_mappings() -> dict[str, str]`, `effective_radarr_path_mappings() -> dict[str, str]`. `status()` inclut désormais `sonarr_path_mappings`/`radarr_path_mappings`. Consommés par la Task 7 (`api.py`).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_gapscan_config_store.py` (à la fin du fichier, avant la dernière fonction si besoin de garder les tests groupés par thème — sinon en fin de fichier) :

```python
def test_path_mappings_default_to_empty_dict():
    assert store.effective_sonarr_path_mappings() == {}
    assert store.effective_radarr_path_mappings() == {}


def test_write_then_read_sonarr_path_mappings():
    store.write(sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"})
    assert store.effective_sonarr_path_mappings() == {"/data/tv": "/mnt/nas/tv"}


def test_write_then_read_radarr_path_mappings():
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_write_path_mappings_does_not_erase_other_fields():
    store.write(c411_api_key="secret")
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_c411() == ("secret", "https://c411.org")
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_status_includes_path_mappings():
    store.write(
        sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"},
        radarr_path_mappings={"/data/movies": "/mnt/nas/movies"},
    )
    status = store.status()
    assert status["sonarr_path_mappings"] == {"/data/tv": "/mnt/nas/tv"}
    assert status["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}


def test_status_path_mappings_empty_by_default():
    status = store.status()
    assert status["sonarr_path_mappings"] == {}
    assert status["radarr_path_mappings"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gapscan_config_store.py -v -k path_mapping`
Expected: FAIL — `write() got an unexpected keyword argument 'sonarr_path_mappings'` / `AttributeError: module 'nfogen.gapscan_config_store' has no attribute 'effective_sonarr_path_mappings'` / `KeyError: 'sonarr_path_mappings'`

- [ ] **Step 3: Write the implementation**

Dans `nfogen/gapscan_config_store.py`, modifier `write()` :

```python
def write(
    *,
    c411_api_key: Optional[str] = None,
    c411_base_url: Optional[str] = None,
    sonarr_url: Optional[str] = None,
    sonarr_api_key: Optional[str] = None,
    radarr_url: Optional[str] = None,
    radarr_api_key: Optional[str] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
) -> None:
    """Met a jour uniquement les champs fournis (`None` = inchange) --
    jamais une reecriture complete, un PUT partiel ne doit pas effacer le
    reste de la configuration deja enregistree."""
    path = _path()
    data = _load()
    updates = {
        "c411_api_key": c411_api_key,
        "c411_base_url": c411_base_url,
        "sonarr_url": sonarr_url,
        "sonarr_api_key": sonarr_api_key,
        "radarr_url": radarr_url,
        "radarr_api_key": radarr_api_key,
        "sonarr_path_mappings": sonarr_path_mappings,
        "radarr_path_mappings": radarr_path_mappings,
    }
    for key, value in updates.items():
        if value is not None:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
```

Ajouter après `effective_radarr()` :

```python
def effective_sonarr_path_mappings() -> dict[str, str]:
    """Table de mapping {prefixe distant: prefixe local} pour Sonarr --
    vide par defaut (deploiement a chemins identiques). Pas de repli sur
    une variable d'environnement : uniquement configurable via le fichier
    (pas de cas d'usage non interactif identifie pour l'instant, contrairement
    aux cles/URLs)."""
    return _load().get("sonarr_path_mappings") or {}


def effective_radarr_path_mappings() -> dict[str, str]:
    return _load().get("radarr_path_mappings") or {}
```

Modifier `status()` pour inclure les deux nouveaux champs :

```python
def status() -> dict[str, Any]:
    """Etat effectif (fichier prioritaire, sinon variables d'environnement)
    -- jamais les cles elles-memes, seulement si chaque service est
    configure et son URL (non sensible). Les mappings de chemins ne sont
    pas des secrets : renvoyes en entier."""
    c411 = effective_c411()
    sonarr = effective_sonarr()
    radarr = effective_radarr()
    return {
        "c411_configured": c411 is not None,
        "c411_base_url": c411[1] if c411 else None,
        "sonarr_configured": sonarr is not None,
        "sonarr_url": sonarr[0] if sonarr else None,
        "radarr_configured": radarr is not None,
        "radarr_url": radarr[0] if radarr else None,
        "sonarr_path_mappings": effective_sonarr_path_mappings(),
        "radarr_path_mappings": effective_radarr_path_mappings(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan_config_store.py -v`
Expected: PASS (tous les tests du fichier, existants + nouveaux)

- [ ] **Step 5: Fix the now-broken exact-dict test in `test_api.py`**

`GET /gapscan/config` (`nfogen/api.py`, fonction `gapscan_config()`) appelle
déjà `gapscan_config_store.status()` sans modification et renvoie son
résultat tel quel — donc `status()` gagnant 2 clés casse immédiatement
`test_gapscan_config_reports_which_services_are_configured` dans
`tests/test_api.py` (comparaison de dict exacte), avant même la Task 7.
Mettre à jour ce test :

```python
def test_gapscan_config_reports_which_services_are_configured(reload_api):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_C411_API_KEY="x",
        NFOGEN_SONARR_URL=None,
        NFOGEN_SONARR_API_KEY=None,
        NFOGEN_RADARR_URL="http://radarr.local",
        NFOGEN_RADARR_API_KEY="y",
    )
    client = TestClient(mod.app)
    resp = client.get("/gapscan/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "c411_configured": True,
        "c411_base_url": "https://c411.org",
        "sonarr_configured": False,
        "sonarr_url": None,
        "radarr_configured": True,
        "radarr_url": "http://radarr.local",
        "sonarr_path_mappings": {},
        "radarr_path_mappings": {},
    }
    # jamais la cle elle-meme dans la reponse, meme par accident.
```

- [ ] **Step 6: Lint + full suite**

Run: `ruff check nfogen/gapscan_config_store.py tests/test_gapscan_config_store.py tests/test_api.py`
Run: `pytest -q`
Expected: clean, tous les tests passent (y compris le test corrigé à l'étape 5).

- [ ] **Step 7: Commit**

```bash
git add nfogen/gapscan_config_store.py tests/test_gapscan_config_store.py tests/test_api.py
git commit -m "AUTOMATION sous-projet 1 (2/6) : stocke les mappings de chemins

sonarr_path_mappings/radarr_path_mappings, memes principes que le
reste de gapscan_config_store.py (fichier JSON, chmod 600, PUT
partiel). Pas des secrets : inclus en entier dans status()."
```

---

### Task 3: `nfogen/radarr_client.py` — extraction du chemin distant

**Files:**
- Modify: `nfogen/radarr_client.py`
- Test: `tests/test_radarr_client.py`

**Interfaces:**
- Produces: `RadarrMovieFile.remote_path: Optional[str]`. Consommé par la Task 5 (`gapscan.py`).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_radarr_client.py`, avant `test_requires_base_url_and_api_key` :

```python
def test_list_movie_files_exposes_the_remote_path():
    movies_with_path = [
        {
            **MOVIES[0],
            "movieFile": {**MOVIES[0]["movieFile"], "path": "/data/media/Matrix (1999)/Matrix.mkv"},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=movies_with_path)

    movies = _client(handler).list_movie_files()
    assert movies[0].remote_path == "/data/media/Matrix (1999)/Matrix.mkv"


def test_list_movie_files_defaults_remote_path_to_none_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MOVIES)  # pas de cle "path" dans movieFile

    movies = _client(handler).list_movie_files()
    assert movies[0].remote_path is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_radarr_client.py -v -k remote_path`
Expected: FAIL — `AttributeError: 'RadarrMovieFile' object has no attribute 'remote_path'`

- [ ] **Step 3: Write the implementation**

Dans `nfogen/radarr_client.py`, ajouter le champ à `RadarrMovieFile` (après `alternate_titles`) :

```python
    alternate_titles: list[str] = field(default_factory=list)
    # Chemin absolu du fichier tel que rapporte par Radarr -- peut differer
    # du chemin que nfogen doit reellement ouvrir si nfogen tourne ailleurs
    # que Radarr (voir AUTOMATION.md, sous-projet 1 : mapping de chemins).
    remote_path: Optional[str] = None
```

Dans `list_movie_files()`, ajouter `remote_path=movie_file.get("path")` à la construction de `RadarrMovieFile` :

```python
            movies.append(
                RadarrMovieFile(
                    movie_id=movie["id"],
                    title=movie.get("title", ""),
                    year=movie.get("year"),
                    imdb_id=movie.get("imdbId"),
                    tmdb_id=movie.get("tmdbId"),
                    best_resolution=quality.get("resolution"),
                    quality_name=quality.get("name"),
                    scene_name=movie_file.get("sceneName"),
                    language_names=[lang.get("name", "") for lang in movie_file.get("languages", [])],
                    alternate_titles=[
                        t.get("title", "") for t in movie.get("alternateTitles", []) if t.get("title")
                    ],
                    remote_path=movie_file.get("path"),
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_radarr_client.py -v`
Expected: PASS

- [ ] **Step 5: Lint**

Run: `ruff check nfogen/radarr_client.py tests/test_radarr_client.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add nfogen/radarr_client.py tests/test_radarr_client.py
git commit -m "AUTOMATION sous-projet 1 (3/6) : RadarrMovieFile.remote_path

Chemin absolu tel que rapporte par Radarr (movieFile.path), absent
jusqu'ici -- necessaire pour la resolution de chemin (path_mapping.py)."
```

---

### Task 4: `nfogen/sonarr_client.py` — extraction des chemins distants (saison)

**Files:**
- Modify: `nfogen/sonarr_client.py`
- Test: `tests/test_sonarr_client.py`

**Interfaces:**
- Produces: `SonarrSeasonFile.remote_paths: list[str]` (un chemin par episode de la saison — une saison est intrinsequement multi-fichiers, contrairement a un film). Consommé par la Task 5 (`gapscan.py`).

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_sonarr_client.py`, avant `test_series_without_episode_files_produces_no_season` :

```python
def test_list_season_files_exposes_remote_paths_for_every_episode_in_the_season():
    files_with_paths = [
        {**EPISODE_FILES[0], "path": "/data/tv/Breaking Bad/Season 01/E01.mkv"},
        {**EPISODE_FILES[1], "path": "/data/tv/Breaking Bad/Season 01/E02.mkv"},
        {**EPISODE_FILES[2], "path": "/data/tv/Breaking Bad/Season 02/E01.mkv"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=files_with_paths)

    seasons = _client(handler).list_season_files()

    season1 = next(s for s in seasons if s.season_number == 1)
    assert season1.remote_paths == [
        "/data/tv/Breaking Bad/Season 01/E01.mkv",
        "/data/tv/Breaking Bad/Season 01/E02.mkv",
    ]
    season2 = next(s for s in seasons if s.season_number == 2)
    assert season2.remote_paths == ["/data/tv/Breaking Bad/Season 02/E01.mkv"]


def test_list_season_files_remote_paths_empty_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/series":
            return httpx.Response(200, json=SERIES)
        return httpx.Response(200, json=EPISODE_FILES)  # pas de cle "path"

    seasons = _client(handler).list_season_files()
    assert seasons[0].remote_paths == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sonarr_client.py -v -k remote_path`
Expected: FAIL — `AttributeError: 'SonarrSeasonFile' object has no attribute 'remote_paths'`

- [ ] **Step 3: Write the implementation**

Dans `nfogen/sonarr_client.py`, ajouter le champ à `SonarrSeasonFile` (après `alternate_titles`) :

```python
    alternate_titles: list[str] = field(default_factory=list)
    # Chemins absolus de CHAQUE fichier episode de la saison (une saison
    # est intrinsequement multi-fichiers, contrairement a un film) -- voir
    # AUTOMATION.md, sous-projet 1.
    remote_paths: list[str] = field(default_factory=list)
```

Dans `list_season_files()`, ajouter `remote_paths=...` à la construction :

```python
                seasons.append(
                    SonarrSeasonFile(
                        series_id=series["id"],
                        title=series.get("title", ""),
                        year=series.get("year"),
                        tvdb_id=series.get("tvdbId"),
                        imdb_id=series.get("imdbId"),
                        season_number=season_number,
                        episode_file_count=len(season_files),
                        best_resolution=quality.get("resolution"),
                        quality_name=quality.get("name"),
                        scene_name=best.get("sceneName"),
                        language_names=[lang.get("name", "") for lang in best.get("languages", [])],
                        alternate_titles=[
                            t.get("title", "")
                            for t in series.get("alternateTitles", [])
                            if t.get("title")
                        ],
                        remote_paths=[f.get("path") for f in season_files if f.get("path")],
                    )
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sonarr_client.py -v`
Expected: PASS

- [ ] **Step 5: Lint**

Run: `ruff check nfogen/sonarr_client.py tests/test_sonarr_client.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add nfogen/sonarr_client.py tests/test_sonarr_client.py
git commit -m "AUTOMATION sous-projet 1 (4/6) : SonarrSeasonFile.remote_paths

Chemin absolu de chaque episode de la saison (episodeFile.path),
absent jusqu'ici -- pluriel, contrairement a RadarrMovieFile.remote_path
(une saison est intrinsequement multi-fichiers)."
```

---

### Task 5: `nfogen/gapscan.py` — `GapResult` + intégration dans `scan_movie`/`scan_series_season`

**Files:**
- Modify: `nfogen/gapscan.py`
- Test: `tests/test_gapscan.py`

**Interfaces:**
- Consumes: `path_mapping.resolve_and_validate(remote_paths: list[str], mappings: dict[str, str]) -> tuple[list[str], bool, Optional[str]]` (Task 1), `RadarrMovieFile.remote_path` (Task 3), `SonarrSeasonFile.remote_paths` (Task 4).
- Produces: `GapResult.local_paths: list[str]`, `GapResult.path_resolved: bool`, `GapResult.path_error: Optional[str]`. `scan_movie(..., path_mappings: Optional[dict[str, str]] = None)`, `scan_series_season(..., path_mappings: Optional[dict[str, str]] = None)`. Consommés par la Task 6 (`run_gapscan`).

**Point d'attention (contrainte du plan) :** en mode incrémental, quand `_can_reuse()` fait reprendre le verdict C411 précédent tel quel, la validation de chemin doit malgré tout être **refaite à neuf** — jamais reprise de l'ancien résultat. Utiliser `dataclasses.replace()` sur le résultat repris pour n'écraser que les 3 champs de chemin.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_gapscan.py`, juste après `test_scan_movie_flags_double_upload_window` (avant la section "Mode incremental") :

```python
def test_scan_movie_resolves_and_validates_the_local_path(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    result = scan_movie(_movie(remote_path=str(f)), c411, path_mappings={})
    assert result.local_paths == [str(f)]
    assert result.path_resolved is True
    assert result.path_error is None


def test_scan_movie_reports_when_the_local_path_is_missing():
    c411 = FakeC411(movie_results=[])
    result = scan_movie(_movie(remote_path="/nope/absent.mkv"), c411, path_mappings={})
    assert result.path_resolved is False
    assert "introuvable" in result.path_error


def test_scan_movie_without_a_remote_path_reports_unresolved():
    c411 = FakeC411(movie_results=[])
    result = scan_movie(_movie(remote_path=None), c411)
    assert result.path_resolved is False
    assert result.local_paths == []


def test_scan_movie_applies_the_configured_path_mapping(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    c411 = FakeC411(movie_results=[])
    result = scan_movie(
        _movie(remote_path="/data/media/Matrix.mkv"), c411,
        path_mappings={"/data/media": str(tmp_path)},
    )
    assert result.local_paths == [str(f)]
    assert result.path_resolved is True
```

Ajouter à la section "Mode incremental" (après les tests `_can_reuse` existants, avant `test_scan_series_season_reuses_previous_result_when_covered_and_unchanged`) :

```python
def test_scan_movie_reuse_still_refreshes_path_validation(tmp_path):
    """Le mode incremental reprend le verdict C411, mais PAS le statut de
    chemin -- celui-ci doit toujours refleter l'etat reel du disque a
    l'instant du scan (AUTOMATION.md, sous-projet 1 : "valide a chaque
    scan"), meme quand le verdict C411 est repris tel quel."""
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(remote_path=str(f)), c411_first, path_mappings={})
    assert previous.path_resolved is True

    f.unlink()  # le fichier disparait entre les deux scans
    c411_second = FakeC411()  # ne doit pas etre appele (reuse du verdict C411)
    result = scan_movie(_movie(remote_path=str(f)), c411_second, previous=previous, path_mappings={})

    assert c411_second.calls == []  # verdict C411 bien repris (COVERED)
    assert result.status == GapStatus.COVERED
    assert result.path_resolved is False  # mais le chemin est bien revalide
    assert "introuvable" in result.path_error
```

Ajouter à la section `scan_series_season`, après `test_scan_series_season_covered` :

```python
def test_scan_series_season_resolves_and_validates_local_paths(tmp_path):
    f = tmp_path / "E01.mkv"
    f.write_text("x")
    c411 = FakeC411(tv_results=[_release("Breaking.Bad.S01.MULTI.VFF.2160p.WEBRip.x265-SQUEEZE")])
    result = scan_series_season(_season(remote_paths=[str(f)]), c411, path_mappings={})
    assert result.local_paths == [str(f)]
    assert result.path_resolved is True


def test_scan_series_season_reports_when_any_episode_path_is_missing(tmp_path):
    f = tmp_path / "E01.mkv"
    f.write_text("x")
    missing = str(tmp_path / "E02.mkv")
    c411 = FakeC411(tv_results=[])
    result = scan_series_season(_season(remote_paths=[str(f), missing]), c411, path_mappings={})
    assert result.path_resolved is False
    assert missing in result.path_error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gapscan.py -v -k "path or reuse_still_refreshes"`
Expected: FAIL — `TypeError: scan_movie() got an unexpected keyword argument 'path_mappings'` (et similaire pour `scan_series_season`)

- [ ] **Step 3: Write the implementation**

En tête de `nfogen/gapscan.py`, modifier les imports :

```python
from dataclasses import dataclass, field, replace
```

et ajouter :

```python
from .path_mapping import resolve_and_validate
```

Modifier `GapResult` : ajouter ces 3 champs après `checked_at` (déjà
présent aujourd'hui, ne pas le redéfinir — seul le bloc `local_paths`
et après est nouveau) :

```python
    checked_at: Optional[float] = None
    # Chemin(s) local(aux) reels apres resolution du mapping distant/local
    # (voir path_mapping.py) -- vide/False si non resolu (aucun chemin
    # connu, fichier introuvable, ou non lisible). Toujours revalide a
    # chaque scan, meme quand le verdict C411 est repris tel quel en mode
    # incremental (voir scan_movie/scan_series_season).
    local_paths: list[str] = field(default_factory=list)
    path_resolved: bool = False
    path_error: Optional[str] = None
```

Modifier `scan_movie()` :

```python
def scan_movie(
    movie: RadarrMovieFile,
    c411: C411Client,
    previous: Optional[GapResult] = None,
    max_age_seconds: Optional[float] = None,
    path_mappings: Optional[dict[str, str]] = None,
) -> GapResult:
    tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
    local_quality = build_quality(
        movie.scene_name or movie.title,
        fallback_resolution=movie.best_resolution,
        fallback_language_names=movie.language_names,
    )
    remote_paths = [movie.remote_path] if movie.remote_path else []
    local_paths, path_resolved, path_error = resolve_and_validate(remote_paths, path_mappings or {})
    if _can_reuse(previous, local_quality, max_age_seconds):
        # Le verdict C411 est repris tel quel, mais la validation de
        # chemin doit toujours etre fraiche (voir Global Constraints).
        return replace(
            previous, local_paths=local_paths, path_resolved=path_resolved, path_error=path_error
        )
    base = dict(
        media_type="movie", title=movie.title, year=movie.year, season_number=None,
        imdb_id=movie.imdb_id, tmdb_id=tmdb_id, tvdb_id=None, local_quality=local_quality,
        local_paths=local_paths, path_resolved=path_resolved, path_error=path_error,
    )
    # Une erreur C411 (429, 520, timeout...) sur CE titre ne doit pas
    # empecher de savoir ce qu'on connait deja localement, ni interrompre
    # le reste du scan (voir run_gapscan, qui continue sur les titres
    # suivants) -- incident reel du 2026-08-25.
    try:
        matches = c411.search_movie(imdb_id=movie.imdb_id, tmdb_id=tmdb_id)
        if not matches:
            # Repli par titre : necessaire meme quand un ID externe est
            # connu, pas seulement en son absence -- torznab:attr imdbid/
            # tmdbid ne sont PAS systematiquement presents sur les releases
            # C411 (cf. GAPSCAN.md), une recherche par ID peut donc echouer
            # a tort. Filtre par annee pour ne pas confondre des films
            # homonymes de millesimes differents (incident reel, "Joker").
            matches = _filter_by_year(c411.search_movie(query=movie.title), movie.year)
        if not matches:
            # Repli par titre ALTERNATIF : C411 est un tracker francophone,
            # qui liste souvent un film sous son titre de sortie/diffusion
            # FR, pas l'original (incident reel, "Wild Card" -> "Joker",
            # retour utilisateur 2026-08-27). S'arrete au premier titre
            # alternatif qui trouve quelque chose.
            for alt_title in movie.alternate_titles:
                if alt_title == movie.title:
                    continue
                matches = _filter_by_year(c411.search_movie(query=alt_title), movie.year)
                if matches:
                    break
    except C411Error as exc:
        return GapResult(**base, status=GapStatus.ERROR, error=str(exc))
    return GapResult(
        **base,
        status=_classify(local_quality, matches),
        c411_matches=matches,
        has_freeleech_alternative=any(m.is_freeleech or m.is_half_leech for m in matches),
        has_double_upload_window=any(m.is_double_upload for m in matches),
        checked_at=time.time(),
    )
```

Modifier `scan_series_season()` de la même façon (remplacer toute la fonction) :

```python
def scan_series_season(
    season: SonarrSeasonFile,
    c411: C411Client,
    previous: Optional[GapResult] = None,
    max_age_seconds: Optional[float] = None,
    path_mappings: Optional[dict[str, str]] = None,
) -> GapResult:
    local_quality = build_quality(
        season.scene_name or season.title,
        fallback_resolution=season.best_resolution,
        fallback_language_names=season.language_names,
    )
    local_paths, path_resolved, path_error = resolve_and_validate(
        season.remote_paths, path_mappings or {}
    )
    if _can_reuse(previous, local_quality, max_age_seconds):
        return replace(
            previous, local_paths=local_paths, path_resolved=path_resolved, path_error=path_error
        )
    base = dict(
        media_type="series", title=season.title, year=season.year,
        season_number=season.season_number, imdb_id=season.imdb_id, tmdb_id=None,
        tvdb_id=season.tvdb_id, local_quality=local_quality,
        local_paths=local_paths, path_resolved=path_resolved, path_error=path_error,
    )
    try:
        matches = c411.search_tv(imdb_id=season.imdb_id, season=season.season_number)
        if not matches:
            matches = c411.search_tv(query=season.title, season=season.season_number)
        if not matches:
            # Repli par titre alternatif -- meme raison que scan_movie, voir
            # la-bas ("White Collar" -> "FBI, duo tres special").
            for alt_title in season.alternate_titles:
                if alt_title == season.title:
                    continue
                matches = c411.search_tv(query=alt_title, season=season.season_number)
                if matches:
                    break
    except C411Error as exc:
        return GapResult(**base, status=GapStatus.ERROR, error=str(exc))
    return GapResult(
        **base,
        status=_classify(local_quality, matches),
        c411_matches=matches,
        has_freeleech_alternative=any(m.is_freeleech or m.is_half_leech for m in matches),
        has_double_upload_window=any(m.is_double_upload for m in matches),
        checked_at=time.time(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan.py -v`
Expected: PASS (tous les tests du fichier, existants + nouveaux)

- [ ] **Step 5: Lint**

Run: `ruff check nfogen/gapscan.py tests/test_gapscan.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add nfogen/gapscan.py tests/test_gapscan.py
git commit -m "AUTOMATION sous-projet 1 (5/6) : resolution de chemin dans scan_*

GapResult gagne local_paths/path_resolved/path_error. scan_movie/
scan_series_season resolvent+valident via path_mapping.py a chaque
appel -- y compris quand le verdict C411 est repris tel quel en mode
incremental (dataclasses.replace, la validation de chemin reste
toujours fraiche, voir AUTOMATION.md)."
```

---

### Task 6: `run_gapscan()` + `gapscan_runner.py` — threading des mappings de chemins

**Files:**
- Modify: `nfogen/gapscan.py` (fonction `run_gapscan`)
- Modify: `nfogen/gapscan_runner.py`
- Test: `tests/test_gapscan.py`, `tests/test_gapscan_runner.py`

**Interfaces:**
- Consumes: `scan_movie(..., path_mappings=)`, `scan_series_season(..., path_mappings=)` (Task 5).
- Produces: `run_gapscan(..., sonarr_path_mappings: Optional[dict[str, str]] = None, radarr_path_mappings: Optional[dict[str, str]] = None)`, `gapscan_runner.start(..., sonarr_path_mappings=None, radarr_path_mappings=None)`. Consommés par la Task 7 (`api.py`).

- [ ] **Step 1: Write the failing test (run_gapscan)**

Ajouter à `tests/test_gapscan.py`, après `test_run_gapscan_reuses_previous_results_for_unchanged_covered_items` :

```python
def test_run_gapscan_passes_path_mappings_to_movies_and_series(tmp_path):
    movie_file = tmp_path / "Matrix.mkv"
    movie_file.write_text("x")
    season_file = tmp_path / "E01.mkv"
    season_file.write_text("x")

    class _RadarrWithPath:
        def list_movie_files(self):
            return [_movie(remote_path="/remote/Matrix.mkv")]

    class _SonarrWithPath:
        def list_season_files(self):
            return [_season(remote_paths=["/remote/E01.mkv"])]

    c411 = FakeC411(movie_results=[], tv_results=[])
    results = run_gapscan(
        c411, radarr=_RadarrWithPath(), sonarr=_SonarrWithPath(),
        radarr_path_mappings={"/remote": str(tmp_path)},
        sonarr_path_mappings={"/remote": str(tmp_path)},
    )
    movie_result = next(r for r in results if r.media_type == "movie")
    series_result = next(r for r in results if r.media_type == "series")
    assert movie_result.path_resolved is True
    assert series_result.path_resolved is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gapscan.py -v -k passes_path_mappings`
Expected: FAIL — `TypeError: run_gapscan() got an unexpected keyword argument 'radarr_path_mappings'`

- [ ] **Step 3: Write the implementation (run_gapscan)**

Dans `nfogen/gapscan.py`, modifier la signature et le corps de `run_gapscan()` :

```python
def run_gapscan(
    c411: C411Client,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    previous_results: Optional[list[GapResult]] = None,
    only: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
) -> list[GapResult]:
    """Lance un scan. `radarr`/`sonarr` optionnels (l'un ou l'autre, ou les
    deux). `on_progress(traites, total)`, appele apres chaque item -- utilise
    par `gapscan_runner.py` pour exposer une progression via
    `GET /gapscan/status` sans dupliquer cette boucle ailleurs.

    `previous_results` (mode incremental, optionnel) : resultats du dernier
    scan termine -- un titre deja COVERED et inchange localement est repris
    tel quel sans reinterroger C411 (voir `_can_reuse`), sauf s'il depasse
    `max_age_seconds`. Retour utilisateur, 2026-08-26/27.

    `only` ("movies"/"series"/None) : ne scanne qu'une des deux bibliotheques
    -- pour repartir la charge sur plusieurs sessions (limite C411 confirmee :
    15 requetes/min). Retour utilisateur, 2026-08-27.

    `sonarr_path_mappings`/`radarr_path_mappings` : tables de resolution de
    chemin distant -> local, une par connexion (voir AUTOMATION.md,
    sous-projet 1)."""
    items: list[tuple[str, object]] = []
    if radarr is not None and only != "series":
        items.extend(("movie", movie) for movie in radarr.list_movie_files())
    if sonarr is not None and only != "movies":
        items.extend(("series", season) for season in sonarr.list_season_files())

    previous_by_key: dict[tuple, GapResult] = {}
    if previous_results:
        for r in previous_results:
            previous_by_key[_result_key(r)] = r

    total = len(items)
    results: list[GapResult] = []
    for index, (kind, item) in enumerate(items, start=1):
        if kind == "movie":
            tmdb_id = str(item.tmdb_id) if item.tmdb_id else None  # type: ignore[attr-defined]
            key = ("movie", item.imdb_id or tmdb_id or item.title, item.year)  # type: ignore[attr-defined]
            results.append(
                scan_movie(
                    item, c411, previous=previous_by_key.get(key), max_age_seconds=max_age_seconds,
                    path_mappings=radarr_path_mappings,
                )
            )  # type: ignore[arg-type]
        else:
            key = ("series", item.tvdb_id or item.imdb_id or item.title, item.season_number)  # type: ignore[attr-defined]
            results.append(
                scan_series_season(
                    item, c411, previous=previous_by_key.get(key), max_age_seconds=max_age_seconds,
                    path_mappings=sonarr_path_mappings,
                )
            )  # type: ignore[arg-type]
        if on_progress is not None:
            on_progress(index, total)
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gapscan.py -v -k passes_path_mappings`
Expected: PASS

- [ ] **Step 5: Write the failing test (gapscan_runner)**

Ajouter à `tests/test_gapscan_runner.py`, après `test_start_with_incremental_and_max_age_reverifies_a_stale_covered_result` :

```python
def test_start_passes_path_mappings_through(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        remote_path="/remote/Matrix.mkv",
    )
    c411 = FakeC411(movie_results=[])

    gapscan_runner.start(
        c411, radarr=FakeRadarr(movies=[movie]),
        radarr_path_mappings={"/remote": str(tmp_path)},
    )
    _wait_until_not_running()

    assert gapscan_runner.results()[0].path_resolved is True
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_gapscan_runner.py -v -k passes_path_mappings`
Expected: FAIL — `TypeError: start() got an unexpected keyword argument 'radarr_path_mappings'`

- [ ] **Step 7: Write the implementation (gapscan_runner)**

Dans `nfogen/gapscan_runner.py`, modifier `_run()` et `start()` :

```python
def _run(
    c411: C411Client,
    radarr: Optional[RadarrClient],
    sonarr: Optional[SonarrClient],
    previous_results: Optional[list[GapResult]],
    only: Optional[str],
    max_age_seconds: Optional[float],
    sonarr_path_mappings: Optional[dict[str, str]],
    radarr_path_mappings: Optional[dict[str, str]],
) -> None:
    global _results
    try:
        def on_progress(done: int, total: int) -> None:
            with _lock:
                _progress.processed = done
                _progress.total = total

        collected = run_gapscan(
            c411, radarr=radarr, sonarr=sonarr, on_progress=on_progress,
            previous_results=previous_results, only=only, max_age_seconds=max_age_seconds,
            sonarr_path_mappings=sonarr_path_mappings, radarr_path_mappings=radarr_path_mappings,
        )
        sorted_results = sort_by_priority(collected)
        with _lock:
            _results = sorted_results
            _progress.state = ScanState.DONE
            _progress.finished_at = time.time()
        gapscan_results_store.save(sorted_results)
    except Exception as exc:  # noqa: BLE001 -- toute erreur client -> statut "error", jamais une exception non geree dans le thread
        with _lock:
            _progress.state = ScanState.ERROR
            _progress.error = str(exc)
            _progress.finished_at = time.time()
    finally:
        c411.close()
        if radarr is not None:
            radarr.close()
        if sonarr is not None:
            sonarr.close()


def start(
    c411: C411Client,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    incremental: bool = False,
    only: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
) -> bool:
    """Lance un scan en tache de fond avec des clients deja construits.
    `False` si un scan est deja en cours (un seul a la fois) -- les clients
    fournis restent alors a la charge de l'appelant (jamais fermes par ce
    module dans ce cas).

    `incremental` : reutilise les resultats du dernier scan (memoire ou
    persistes, voir _restore_persisted) pour les titres deja COVERED et
    dont la qualite locale n'a pas change -- evite de tout rescanner a
    chaque fois (retour utilisateur, 2026-08-26). `False` par defaut : scan
    complet, comportement historique. `max_age_seconds` : au-dela de cet
    age, un COVERED est reverifie meme en mode incremental (retour
    utilisateur, 2026-08-27 : C411 retire/ajoute des torrents assez
    souvent) -- ignore si `incremental` est faux.

    `only` ("movies"/"series"/None) : ne scanne qu'une des deux
    bibliotheques -- pour repartir la charge sur plusieurs sessions.

    `sonarr_path_mappings`/`radarr_path_mappings` : voir
    AUTOMATION.md, sous-projet 1."""
    with _lock:
        if _progress.state == ScanState.RUNNING:
            return False
        previous_results = list(_results) if incremental else None
        _progress.state = ScanState.RUNNING
        _progress.started_at = time.time()
        _progress.finished_at = None
        _progress.error = None
        _progress.total = 0
        _progress.processed = 0
    thread = threading.Thread(
        target=_run,
        args=(
            c411, radarr, sonarr, previous_results, only, max_age_seconds,
            sonarr_path_mappings, radarr_path_mappings,
        ),
        daemon=True,
    )
    thread.start()
    return True
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_gapscan_runner.py -v`
Expected: PASS (tous les tests du fichier)

- [ ] **Step 9: Lint + full suite**

Run: `ruff check nfogen/gapscan.py nfogen/gapscan_runner.py tests/test_gapscan.py tests/test_gapscan_runner.py`
Run: `pytest -q`
Expected: clean, tout passe

- [ ] **Step 10: Commit**

```bash
git add nfogen/gapscan.py nfogen/gapscan_runner.py tests/test_gapscan.py tests/test_gapscan_runner.py
git commit -m "AUTOMATION sous-projet 1 (6/6 backend) : mappings de chemins bout en bout

run_gapscan()/gapscan_runner.start() acceptent sonarr_path_mappings/
radarr_path_mappings et les transmettent a scan_movie/scan_series_season.
Backend complet pour la resolution de chemin -- reste l'exposition via
l'API (Task 7) et le frontend (Tasks 8-10)."
```

---

### Task 7: `nfogen/api.py` — exposition via `PUT`/`GET /gapscan/config` et `POST /gapscan/run`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `gapscan_config_store.write(..., sonarr_path_mappings=, radarr_path_mappings=)`, `effective_sonarr_path_mappings()`, `effective_radarr_path_mappings()` (Task 2) ; `gapscan_runner.start(..., sonarr_path_mappings=, radarr_path_mappings=)` (Task 6).
- Produces: `PUT /gapscan/config` accepte `sonarr_path_mappings`/`radarr_path_mappings` (`dict[str, str]`). `GET /gapscan/config` les renvoie. `POST /gapscan/run` les lit depuis le store et les transmet au runner.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_api.py`, après `test_gapscan_config_partial_write_preserves_other_fields` :

```python
def test_gapscan_config_write_then_read_back_path_mappings(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={"radarr_path_mappings": {"/data/movies": "/mnt/nas/movies"}},
    )
    assert put.status_code == 200
    assert put.json()["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}

    status = client.get("/gapscan/config").json()
    assert status["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}
    assert status["sonarr_path_mappings"] == {}
```

Ajouter après `test_gapscan_run_reads_the_incremental_max_age_env_var` :

```python
def test_gapscan_run_passes_configured_path_mappings_to_the_runner(reload_api, monkeypatch, tmp_path):
    captured: dict = {}

    def fake_start(
        c411, radarr=None, sonarr=None, incremental=False, only=None, max_age_seconds=None,
        sonarr_path_mappings=None, radarr_path_mappings=None,
    ):
        captured["radarr_path_mappings"] = radarr_path_mappings
        captured["sonarr_path_mappings"] = sonarr_path_mappings
        return True

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    client.put("/gapscan/config", json={"radarr_path_mappings": {"/data/movies": "/mnt/nas/movies"}})
    _patch_gapscan_clients(monkeypatch, mod)
    monkeypatch.setattr(mod.gapscan_runner, "start", fake_start)

    resp = client.post("/gapscan/run")

    assert resp.status_code == 200
    assert captured["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}
    assert captured["sonarr_path_mappings"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k "path_mappings"`
Expected: FAIL — `test_gapscan_config_write_then_read_back_path_mappings` echoue avec `KeyError`/assertion (le champ n'existe pas encore cote requete Pydantic, silencieusement ignore par FastAPI -> jamais ecrit) ; `test_gapscan_run_passes_configured_path_mappings_to_the_runner` echoue sur l'assertion `captured[...]` (jamais peuple, car `gapscan_run()` n'appelle pas encore `effective_*_path_mappings()`).

- [ ] **Step 3: Write the implementation**

Dans `nfogen/api.py`, modifier `GapscanConfigWriteRequest` :

```python
class GapscanConfigWriteRequest(BaseModel):
    c411_api_key: Optional[str] = None
    c411_base_url: Optional[str] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    sonarr_path_mappings: Optional[dict[str, str]] = None
    radarr_path_mappings: Optional[dict[str, str]] = None
```

Modifier `_build_gapscan_clients()` pour renvoyer aussi les mappings (change son type de retour d'un 3-uplet a un 5-uplet) :

```python
def _build_gapscan_clients() -> tuple[Any, Any, Any, dict[str, str], dict[str, str]]:
    """Construit les clients GapScan depuis gapscan_config_store (fichier ou
    environnement), plus les mappings de chemins configures. Leve
    ValueError (-> 400) si la configuration necessaire manque."""
    c411_config = gapscan_config_store.effective_c411()
    if c411_config is None:
        raise ValueError(
            "Cle API C411 non configuree (NFOGEN_C411_API_KEY, ou PUT /gapscan/config) : "
            "voir GAPSCAN.md."
        )
    c411_key, c411_base_url = c411_config
    # Limite confirmee directement par les admins C411 (2026-08-27) : 15
    # requetes/min par utilisateur (60/15 = 4s pile). 4.5s par defaut
    # desormais (~13,3/min), marge de securite -- 2.0s (~30/min, choisi
    # avant cette confirmation) depassait la limite reelle. Ajustable si
    # besoin.
    min_interval = float(os.environ.get("NFOGEN_C411_MIN_INTERVAL_SECONDS", "4.5"))
    c411 = C411Client(
        c411_key, base_url=c411_base_url.rstrip("/") + "/api", min_interval_seconds=min_interval
    )

    sonarr_config = gapscan_config_store.effective_sonarr()
    sonarr = SonarrClient(*sonarr_config) if sonarr_config else None

    radarr_config = gapscan_config_store.effective_radarr()
    radarr = RadarrClient(*radarr_config) if radarr_config else None

    if sonarr is None and radarr is None:
        c411.close()
        raise ValueError(
            "Aucune instance Sonarr ni Radarr configuree "
            "(NFOGEN_SONARR_URL/_API_KEY et/ou NFOGEN_RADARR_URL/_API_KEY, ou PUT /gapscan/config)."
        )
    return (
        c411, sonarr, radarr,
        gapscan_config_store.effective_sonarr_path_mappings(),
        gapscan_config_store.effective_radarr_path_mappings(),
    )
```

Modifier `gapscan_run()` pour dépaqueter le 5-uplet et transmettre les mappings :

```python
@app.post("/gapscan/run", dependencies=[Depends(require_token)])
def gapscan_run(
    incremental: bool = Query(False), only: Optional[str] = Query(None)
) -> dict[str, str]:
    """`incremental=true` : reutilise les resultats du dernier scan pour les
    titres deja couverts et inchanges localement (au-dela de
    NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS, reverifie quand meme -- C411
    retire/ajoute des torrents assez souvent). `only=movies`/`only=series` :
    ne scanne qu'une des deux bibliotheques, pour repartir la charge sur
    plusieurs sessions (limite C411 confirmee : 15 requetes/min). Voir
    gapscan_runner.start()."""
    _require_gapscan_available()
    if only not in (None, "movies", "series"):
        raise HTTPException(status_code=400, detail="only doit valoir 'movies' ou 'series'.")
    try:
        c411, sonarr, radarr, sonarr_path_mappings, radarr_path_mappings = _build_gapscan_clients()
    except (ValueError, C411Error, SonarrError, RadarrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Bug reel trouve en audit (2026-08-27) : "au moins Sonarr OU Radarr
    # configure" (verifie par _build_gapscan_clients) ne suffit pas quand
    # `only` cible precisement celui qui MANQUE -- sans ce garde-fou, le
    # scan "reussissait" en silence avec 0 titre traite.
    if only == "movies" and radarr is None:
        c411.close()
        if sonarr is not None:
            sonarr.close()
        raise HTTPException(
            status_code=400,
            detail="only=movies demande, mais Radarr n'est pas configure.",
        )
    if only == "series" and sonarr is None:
        c411.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(
            status_code=400,
            detail="only=series demande, mais Sonarr n'est pas configure.",
        )

    max_age_days = float(os.environ.get("NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS", "7"))
    max_age_seconds = max_age_days * 86400 if incremental else None
    started = gapscan_runner.start(
        c411, radarr=radarr, sonarr=sonarr, incremental=incremental,
        only=only, max_age_seconds=max_age_seconds,
        sonarr_path_mappings=sonarr_path_mappings, radarr_path_mappings=radarr_path_mappings,
    )
    if not started:
        c411.close()
        if sonarr is not None:
            sonarr.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(status_code=409, detail="Un scan GapScan est deja en cours.")
    return {"status": "started"}
```

`_build_gapscan_clients()` n'a qu'un seul appelant dans `nfogen/api.py` (`gapscan_run()`, déjà réécrit ci-dessus pour dépaqueter les 5 valeurs) — vérifié par `grep -n "_build_gapscan_clients()" nfogen/api.py` au moment d'écrire ce plan (2026-08-27), aucun autre site à mettre à jour.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k gapscan`
Expected: PASS (tous les tests gapscan de `test_api.py`, existants + nouveaux)

- [ ] **Step 5: Lint + full suite**

Run: `ruff check nfogen/api.py tests/test_api.py`
Run: `pytest -q`
Expected: clean, tout passe

- [ ] **Step 6: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "AUTOMATION sous-projet 1 (7) : expose les mappings de chemins via l'API

PUT/GET /gapscan/config accepte et renvoie sonarr_path_mappings/
radarr_path_mappings (pas des secrets, renvoyes en entier).
POST /gapscan/run les lit depuis le store et les transmet au runner.
_build_gapscan_clients() renvoie desormais un 5-uplet."
```

---

### Task 8: Frontend — types + client API

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `GapResult.local_paths: string[]`, `GapResult.path_resolved: boolean`, `GapResult.path_error: string | null` ; `GapscanConfig.sonarr_path_mappings: Record<string, string>`, `GapscanConfig.radarr_path_mappings: Record<string, string>` ; `GapscanConfigWrite.sonarr_path_mappings?: Record<string, string>`, `GapscanConfigWrite.radarr_path_mappings?: Record<string, string>`. Consommés par les Tasks 9-10.

- [ ] **Step 1: Update the types (pas de test dédié — types statiques, vérifiés par `tsc`)**

Dans `frontend/src/api/types.ts`, modifier `GapResult` :

```typescript
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
  /** Detail si status === "error" (C411 injoignable pour ce titre), sinon null. */
  error: string | null;
  /** Chemin(s) local(aux) reels apres resolution du mapping distant/local
   * (voir AUTOMATION.md, sous-projet 1). Vide/false si non resolu. */
  local_paths: string[];
  path_resolved: boolean;
  path_error: string | null;
}
```

Modifier `GapscanConfig` et `GapscanConfigWrite` :

```typescript
export interface GapscanConfig {
  c411_configured: boolean;
  c411_base_url: string | null;
  sonarr_configured: boolean;
  sonarr_url: string | null;
  radarr_configured: boolean;
  radarr_url: string | null;
  sonarr_path_mappings: Record<string, string>;
  radarr_path_mappings: Record<string, string>;
}

/** PUT /gapscan/config : chaque champ omis reste inchange cote serveur. */
export interface GapscanConfigWrite {
  c411_api_key?: string;
  c411_base_url?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_path_mappings?: Record<string, string>;
  radarr_path_mappings?: Record<string, string>;
}
```

- [ ] **Step 2: Check for existing tests asserting an exact `GapscanConfig`/`GapResult` object shape**

Run: `grep -n "sonarr_configured\|c411_matches: \[\]" frontend/src/api/client.test.ts frontend/src/pages/GapScanPage.test.tsx`

Si un test construit un objet littéral `GapscanConfig`/`GapResult` complet (comme `CONFIGURED`/`MATRIX_GAP` dans `GapScanPage.test.tsx`), l'ajout de champs requis dans l'interface va faire échouer la compilation TypeScript de ce fichier de test — mettre à jour ces littéraux avec les nouveaux champs (`sonarr_path_mappings: {}`, `radarr_path_mappings: {}`, `local_paths: []`, `path_resolved: true`, `path_error: null` — valeurs par défaut cohérentes avec le scénario du test).

- [ ] **Step 3: Run the frontend checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: erreurs de type sur les littéraux non mis à jour trouvés à l'étape 2 — les corriger, puis relancer jusqu'à `tsc` propre.

Run: `npx vitest run`
Expected: PASS

- [ ] **Step 4: Lint**

Run: `npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/pages/GapScanPage.test.tsx frontend/src/api/client.test.ts
git commit -m "AUTOMATION sous-projet 1 (8) : types frontend pour les chemins

GapResult.local_paths/path_resolved/path_error, GapscanConfig(Write)
.sonarr_path_mappings/radarr_path_mappings. Miroir des dataclasses
Python (Task 5/7)."
```

---

### Task 9: Frontend — configuration des mappings de chemins (réutilise `KeyValueEditor`)

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Modify: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `KeyValueEditor` (`frontend/src/components/ListEditor.tsx`, déjà générique — `value: Record<string,string>`, `onChange`, `keyPlaceholder`, `valuePlaceholder`), `GapscanConfig.sonarr_path_mappings`/`radarr_path_mappings` (Task 8).

- [ ] **Step 1: Write the failing test**

Ajouter à `frontend/src/pages/GapScanPage.test.tsx`, après le test `"enregistre Sonarr/Radarr via le formulaire de configuration"` :

```typescript
it("enregistre un mapping de chemin Radarr via le formulaire de configuration", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanConfigWrite).mockResolvedValue({
    ...CONFIGURED,
    radarr_path_mappings: { "/data/movies": "/mnt/nas/movies" },
  });

  renderPage();
  await user.click(await screen.findByRole("button", { name: /Configuration/ }));

  // KeyValueEditor part d'une liste vide : il faut d'abord ajouter une
  // ligne avant que ses champs existent. Deux editeurs (Sonarr puis
  // Radarr, dans cet ordre dans le JSX) partagent le meme libelle de
  // bouton "+ Ajouter" (KeyValueEditor ne permet pas de le personnaliser)
  // -- le second correspond a Radarr.
  const addButtons = screen.getAllByRole("button", { name: "+ Ajouter" });
  await user.click(addButtons[1]);

  await user.type(screen.getByPlaceholderText("Chemin distant (Radarr)"), "/data/movies");
  await user.type(screen.getByPlaceholderText("Chemin local (nfogen)"), "/mnt/nas/movies");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));

  expect(gapscanConfigWrite).toHaveBeenCalledWith(
    expect.objectContaining({
      radarr_path_mappings: { "/data/movies": "/mnt/nas/movies" },
    }),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx -t "mapping de chemin"`
Expected: FAIL — `Unable to find a label/placeholder text` (le champ n'existe pas encore)

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/pages/GapScanPage.tsx`, ajouter l'import :

```typescript
import { KeyValueEditor } from "../components/ListEditor";
```

Ajouter deux nouveaux états, après `const [c411BaseUrl, setC411BaseUrl] = useState("");` :

```typescript
  const [sonarrPathMappings, setSonarrPathMappings] = useState<Record<string, string>>({});
  const [radarrPathMappings, setRadarrPathMappings] = useState<Record<string, string>>({});
```

Dans le `useEffect` de chargement de la config (celui qui appelle `gapscanConfig()`), ajouter l'initialisation :

```typescript
  useEffect(() => {
    gapscanConfig()
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setC411BaseUrl(c.c411_base_url ?? "");
        setSonarrPathMappings(c.sonarr_path_mappings);
        setRadarrPathMappings(c.radarr_path_mappings);
        if (!c.c411_configured || (!c.sonarr_configured && !c.radarr_configured)) {
          setShowConfigForm(true);
        }
      });
    refreshStatus();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

Dans `handleSaveConfig()`, ajouter l'envoi (toujours, pas conditionnel comme les clés — un dictionnaire vide est une valeur valide qui doit pouvoir écraser une config précédente) :

```typescript
  async function handleSaveConfig() {
    setConfigSaving(true);
    setConfigError(null);
    setConfigSaved(false);
    try {
      // Seuls les champs non vides sont envoyes : un champ cle laisse vide
      // ne doit pas effacer une valeur deja enregistree (PUT partiel cote
      // serveur, voir gapscan_config_store.write()).
      const fields: GapscanConfigWrite = {};
      if (sonarrUrl.trim()) fields.sonarr_url = sonarrUrl.trim();
      if (sonarrApiKey.trim()) fields.sonarr_api_key = sonarrApiKey.trim();
      if (radarrUrl.trim()) fields.radarr_url = radarrUrl.trim();
      if (radarrApiKey.trim()) fields.radarr_api_key = radarrApiKey.trim();
      if (c411ApiKey.trim()) fields.c411_api_key = c411ApiKey.trim();
      if (c411BaseUrl.trim()) fields.c411_base_url = c411BaseUrl.trim();
      // Contrairement aux cles/URLs ci-dessus, un dictionnaire vide est une
      // valeur explicite valide ("aucun mapping") : toujours envoye.
      fields.sonarr_path_mappings = sonarrPathMappings;
      fields.radarr_path_mappings = radarrPathMappings;

      const updated = await gapscanConfigWrite(fields);
      setConfig(updated);
      setSonarrApiKey("");
      setRadarrApiKey("");
      setC411ApiKey("");
      setConfigSaved(true);
      setTimeout(() => setConfigSaved(false), 2000);
    } catch (e) {
      setConfigError(e instanceof ApiError ? e.message : "Enregistrement impossible.");
    } finally {
      setConfigSaving(false);
    }
  }
```

Dans le JSX du formulaire de configuration, après le bloc `<div className="grid grid-cols-2 gap-3">...</div>` (celui contenant les 6 champs Sonarr/Radarr/C411 existants) et avant `{configError && ...}`, ajouter :

```tsx
            <div className="space-y-2">
              <p className="text-sm font-medium text-ink-dim">
                Mapping de chemins Sonarr (si nfogen ne voit pas les mêmes chemins que Sonarr)
              </p>
              <KeyValueEditor
                value={sonarrPathMappings}
                onChange={setSonarrPathMappings}
                keyPlaceholder="Chemin distant (Sonarr)"
                valuePlaceholder="Chemin local (nfogen)"
              />
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium text-ink-dim">
                Mapping de chemins Radarr (si nfogen ne voit pas les mêmes chemins que Radarr)
              </p>
              <KeyValueEditor
                value={radarrPathMappings}
                onChange={setRadarrPathMappings}
                keyPlaceholder="Chemin distant (Radarr)"
                valuePlaceholder="Chemin local (nfogen)"
              />
            </div>
```

La ligne d'import de types en tête de fichier (ligne 13, `import type { GapResult, GapscanConfig, GapscanStatus, GapStatus } from "../api/types";`) doit devenir :

```typescript
import type { GapResult, GapscanConfig, GapscanConfigWrite, GapscanStatus, GapStatus } from "../api/types";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: PASS (tous les tests du fichier)

- [ ] **Step 5: Update the other config-form test that asserts the full payload**

Le test existant `"enregistre Sonarr/Radarr via le formulaire de configuration"` fait
`expect(gapscanConfigWrite).toHaveBeenCalledWith({...})` avec un objet EXACT (pas
`objectContaining`) — il va échouer car `fields` contient désormais aussi
`sonarr_path_mappings: {}`/`radarr_path_mappings: {}`. Mettre à jour cette
assertion pour inclure les deux nouveaux champs (valeurs `{}`, aucun mapping
saisi dans ce test) :

```typescript
    expect(gapscanConfigWrite).toHaveBeenCalledWith({
      sonarr_url: "http://sonarr.local:8989",
      sonarr_api_key: "sk-123",
      radarr_url: "http://radarr.local:7878",
      c411_base_url: "https://c411.org",
      sonarr_path_mappings: {},
      radarr_path_mappings: {},
    });
```

- [ ] **Step 6: Run full frontend checks**

Run: `npx vitest run && npx tsc --noEmit && npm run lint`
Expected: tout propre

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/GapScanPage.tsx frontend/src/pages/GapScanPage.test.tsx
git commit -m "AUTOMATION sous-projet 1 (9) : UI de config des mappings de chemins

Reutilise KeyValueEditor (deja generique, aucun nouveau composant).
Toujours envoye au PUT (contrairement aux cles/URLs) : un dictionnaire
vide est une valeur explicite valide."
```

---

### Task 10: Frontend — indicateur de statut de chemin dans le tableau de résultats

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Modify: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `GapResult.path_resolved`, `GapResult.path_error` (Task 8).

- [ ] **Step 1: Write the failing test**

Ajouter à `frontend/src/pages/GapScanPage.test.tsx`, après le test `"affiche les resultats deja disponibles au chargement, avec leur statut"` :

```typescript
it("signale un chemin local non resolu par un badge, avec le detail en infobulle", async () => {
  vi.mocked(gapscanResults).mockResolvedValue([
    { ...MATRIX_GAP, path_resolved: false, path_error: "Fichier introuvable apres resolution : /mnt/nas/Matrix.mkv" },
  ]);

  renderPage();

  const badge = await screen.findByTitle("Fichier introuvable apres resolution : /mnt/nas/Matrix.mkv");
  expect(badge).toBeInTheDocument();
});

it("n'affiche pas de badge de chemin quand le chemin est resolu", async () => {
  vi.mocked(gapscanResults).mockResolvedValue([{ ...MATRIX_GAP, path_resolved: true, path_error: null }]);

  renderPage();

  await screen.findByText(/Matrix \(1999\)/);
  expect(screen.queryByText("⚠ chemin")).not.toBeInTheDocument();
});
```

Vérifier que `MATRIX_GAP` (le littéral de test défini en haut du fichier, mis à jour à la Task 8) inclut bien `local_paths: [...]`, `path_resolved: true`, `path_error: null` par défaut — sinon l'ajouter à cette occasion.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx -t "chemin"`
Expected: FAIL — `Unable to find an element with the title` (le badge n'existe pas encore)

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/pages/GapScanPage.tsx`, dans la boucle `results.map(...)` du tableau, modifier la cellule Titre :

```tsx
                <td className="px-4 py-2 font-mono font-medium text-ink">
                  {r.title} {r.year ? `(${r.year})` : ""}
                  {!r.path_resolved && (
                    <span
                      className="ml-1 rounded-full bg-warn-bg px-2 py-0.5 text-xs text-warn"
                      title={r.path_error ?? "Chemin local non résolu"}
                    >
                      ⚠ chemin
                    </span>
                  )}
                </td>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: PASS (tous les tests du fichier)

- [ ] **Step 5: Run full frontend + backend checks**

Run: `npx vitest run && npx tsc --noEmit && npm run lint && npm run build`
Run (depuis la racine) : `pytest -q && ruff check .`
Expected: tout propre

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/GapScanPage.tsx frontend/src/pages/GapScanPage.test.tsx
git commit -m "AUTOMATION sous-projet 1 (10/10) : badge de statut de chemin

Un titre dont le chemin local n'est pas resolu (fichier introuvable,
non lisible, ou aucun chemin connu) affiche un badge avec le detail
en infobulle -- termine le sous-projet 1 (AUTOMATION.md)."
```

---

## Après ce plan

Sous-projet 1 livré et testé de bout en bout (backend + frontend). Mettre à
jour `AUTOMATION.md` : passer la ligne "Accès NAS en lecture seule" de
"Conception ci-dessous" à "Livré (2026-08-XX)" dans le tableau de
décomposition, et noter brièvement l'écart d'implémentation par rapport à
la conception initiale (mappings en `dict[str, str]` plutôt qu'en
`list[{remote, local}]` — découvert pendant la planification, plus simple
et réutilise directement `KeyValueEditor`). Sous-projet 2 (mise en scène du
fichier + génération du `.torrent`) à concevoir ensuite, avec sa propre
conception dans `AUTOMATION.md` puis son propre plan.
