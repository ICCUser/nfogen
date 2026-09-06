# Bibliothèque locale et scan ciblé (sous-projet 8) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une page "Bibliothèque" qui liste l'inventaire local Radarr/Sonarr sans jamais appeler le tracker, permet de filtrer/sélectionner des titres (unitairement ou par lot), de savoir lesquels ont déjà été traités par nfogen (Confirmer/Envoyer), et de lancer un scan C411 **restreint** à cette sélection — sans toucher au bulk-scan existant.

**Architecture:** Une clé stable (`movie_key`/`series_key`, extraite de `gapscan._result_key`) relie la sélection faite en bibliothèque aux items réellement traités par `run_gapscan`. Un nouveau module `gapscan_library.py` (synchrone, zéro appel tracker) construit l'inventaire à partir de `list_movie_files()`/`list_season_files()` (déjà existants) enrichis de `genres`/`added_at`. Un historique JSON persistant (`upload_history_store.py`, même patron que `gapscan_results_store.py`) garde trace de chaque Confirmer/Envoi réussi via une clé plus simple (`radarr_movie_id`/`sonarr_series_id`), déjà disponible aux points d'appel concernés sans plomberie supplémentaire.

**Tech Stack:** Python 3.11+ / FastAPI / pytest (backend), React 18 + TypeScript + Vite + Vitest (frontend). Aucune nouvelle dépendance.

**Spec:** [docs/superpowers/specs/2026-09-06-library-targeted-scan-design.md](../specs/2026-09-06-library-targeted-scan-design.md)

## Global Constraints

- Zéro appel au client C411/tracker dans `gapscan_library.py` — inventaire 100% Radarr/Sonarr.
- `only` et `selection` ne suppriment JAMAIS des résultats préexistants d'un type/titre non concerné — toujours préservés depuis `previous_results` (incident réel 2026-08-28).
- `selection` a priorité sur `only` si les deux sont fournis.
- L'écriture de `upload_history_store` ne doit **jamais** faire échouer un Confirmer/Envoi par ailleurs réussi (try/except large, silencieux).
- Une clé de sélection invalide/obsolète (bibliothèque modifiée entretemps) est ignorée silencieusement, jamais une erreur bloquante — sauf une clé mal FORMÉE (JSON invalide), qui reste un 400 (erreur de requête, pas une clé "juste absente").
- Attribution de commit : `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Après chaque push, poller GitHub Actions jusqu'à un run terminé (`conclusion`) sur ce commit avant de considérer la tâche faite — discipline établie cette session après un CI-break passé inaperçu.

---

## Task 1: `nfogen/gapscan.py` — extraire `movie_key`/`series_key`, ajouter `selection`

**Files:**
- Modify: `nfogen/gapscan.py:277-356`
- Test: `tests/test_gapscan.py`

**Interfaces:**
- Produces: `movie_key(imdb_id: Optional[str], tmdb_id: Optional[str], title: str, year: Optional[int]) -> tuple`, `series_key(tvdb_id: Optional[int], imdb_id: Optional[str], title: str, season_number: Optional[int]) -> tuple`, `run_gapscan(..., selection: Optional[set[tuple]] = None)`.

- [ ] **Step 1: Écrire les tests d'extraction (non-régression) et de `selection`**

Ajouter à `tests/test_gapscan.py` (regarder l'en-tête du fichier existant pour les imports/fixtures déjà en place — réutiliser les mêmes builders `RadarrMovieFile`/`SonarrSeasonFile`/`TorznabClient` factices que les tests `run_gapscan` existants) :

```python
from nfogen.gapscan import movie_key, series_key


def test_movie_key_prefers_imdb_then_tmdb_then_title():
    assert movie_key("tt123", "456", "Title", 2020) == ("movie", "tt123", 2020)
    assert movie_key(None, "456", "Title", 2020) == ("movie", "456", 2020)
    assert movie_key(None, None, "Title", 2020) == ("movie", "Title", 2020)


def test_series_key_prefers_tvdb_then_imdb_then_title():
    assert series_key(789, "tt123", "Title", 1) == ("series", 789, 1)
    assert series_key(None, "tt123", "Title", 1) == ("series", "tt123", 1)
    assert series_key(None, None, "Title", 1) == ("series", "Title", 1)


def test_run_gapscan_selection_restricts_to_selected_movie_only(monkeypatch):
    """Deux films en bibliotheque, selection ne contient que le premier :
    seul lui doit declencher un appel c411, le second est repris tel quel
    depuis previous_results (jamais supprime, jamais reinterroge)."""
    movie_a = RadarrMovieFile(
        movie_id=1, title="Movie A", year=2020, imdb_id="tt001", tmdb_id=1,
    )
    movie_b = RadarrMovieFile(
        movie_id=2, title="Movie B", year=2021, imdb_id="tt002", tmdb_id=2,
    )
    radarr = _FakeRadarr(movies=[movie_a, movie_b])
    c411 = _FakeC411()  # doit enregistrer chaque appel search_movie
    previous_b = GapResult(
        media_type="movie", title="Movie B", year=2021, season_number=None,
        imdb_id="tt002", tmdb_id="2", tvdb_id=None, status=GapStatus.COVERED,
        local_quality=build_quality(None),
    )
    selection = {movie_key("tt001", "1", "Movie A", 2020)}

    results = run_gapscan(
        c411, radarr=radarr, previous_results=[previous_b], selection=selection,
    )

    titles_checked = [m.title for m in c411.movie_calls]
    assert titles_checked == ["Movie A"] or "tt001" in str(c411.movie_calls)
    assert any(r.title == "Movie B" and r is previous_b for r in results) or \
        any(r.title == "Movie B" for r in results)
```

Adapter ce dernier test aux vrais noms de fakes/fixtures déjà présents dans `tests/test_gapscan.py` (`_FakeRadarr`/`_FakeC411` ou équivalents — lire le fichier avant d'écrire ce test pour réutiliser l'existant plutôt que d'en recréer un autre). Le point à vérifier précisément : `movie_b` (hors sélection) apparaît dans `results` SANS que `c411.search_movie` ait été appelé pour lui, et `movie_a` (dans la sélection) a bien déclenché un appel C411.

- [ ] **Step 2: Lancer les tests, vérifier l'échec attendu**

Run: `pytest tests/test_gapscan.py -v -k "movie_key or series_key or selection"`
Expected: FAIL (`movie_key`/`series_key` n'existent pas encore, `selection` n'est pas un paramètre accepté).

- [ ] **Step 3: Extraire `movie_key`/`series_key`, refactorer `_result_key`, ajouter `selection`**

Remplacer dans `nfogen/gapscan.py` (lignes 277-356) :

```python
def movie_key(imdb_id: Optional[str], tmdb_id: Optional[str], title: str, year: Optional[int]) -> tuple:
    """Identifiant stable d'un film, reutilise a la fois par le mode
    incremental (_result_key) et par gapscan_library.py (meme calcul des
    deux cotes, pour qu'une selection faite en bibliotheque retrouve
    exactement le bon item ici)."""
    return ("movie", imdb_id or tmdb_id or title, year)


def series_key(tvdb_id: Optional[int], imdb_id: Optional[str], title: str, season_number: Optional[int]) -> tuple:
    """Meme role que movie_key, cote serie/saison."""
    return ("series", tvdb_id or imdb_id or title, season_number)


def _result_key(r: GapResult) -> tuple:
    """Identifiant stable d'un titre (ou saison) entre deux scans, pour
    retrouver son resultat precedent en mode incremental -- voir
    movie_key/series_key (extraites pour etre reutilisees telles quelles
    par gapscan_library.py)."""
    if r.media_type == "movie":
        return movie_key(r.imdb_id, r.tmdb_id, r.title, r.year)
    return series_key(r.tvdb_id, r.imdb_id, r.title, r.season_number)


def _item_key(kind: str, item: object) -> tuple:
    """Meme calcul que _result_key, mais depuis un item BRUT (RadarrMovieFile/
    SonarrSeasonFile) avant meme d'avoir construit un GapResult -- utilise
    par run_gapscan pour retrouver un resultat precedent ET pour filtrer
    selon `selection`, sans dupliquer la logique de cle a deux endroits."""
    if kind == "movie":
        tmdb_id = str(item.tmdb_id) if item.tmdb_id else None  # type: ignore[attr-defined]
        return movie_key(item.imdb_id, tmdb_id, item.title, item.year)  # type: ignore[attr-defined]
    return series_key(item.tvdb_id, item.imdb_id, item.title, item.season_number)  # type: ignore[attr-defined]


def run_gapscan(
    c411: TorznabClient,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    previous_results: Optional[list[GapResult]] = None,
    only: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
    selection: Optional[set[tuple]] = None,
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

    `selection` (AUTOMATION.md, sous-projet 8, optionnel) : ensemble de cles
    (`movie_key`/`series_key`) -- si fourni, seuls les items dont la cle est
    dans cet ensemble sont reellement interroges sur C411 ; TOUS les autres
    items (locaux, hors selection) sont repris tels quels depuis
    `previous_results` s'ils y figurent, sinon simplement absents du
    resultat (jamais recalcules a vide). A priorite sur `only` si les deux
    sont fournis -- combiner les deux n'a pas de sens. Retour utilisateur,
    2026-09-06 : "pour eviter de scan comme un porc toute la bibliotech".

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

    if selection is not None:
        selected_items = [(kind, item) for kind, item in items if _item_key(kind, item) in selection]
        # Tout item LOCAL qui existe mais n'est pas selectionne : repris tel
        # quel depuis previous_results s'il y figure deja -- jamais recalcule,
        # jamais supprime (meme garde-fou que `only` plus bas, mais au niveau
        # titre individuel plutot que bibliotheque entiere).
        carried_over = [
            previous_by_key[_item_key(kind, item)]
            for kind, item in items
            if _item_key(kind, item) not in selection and _item_key(kind, item) in previous_by_key
        ]
        items = selected_items
    else:
        carried_over = []

    total = len(items)
    results: list[GapResult] = []
    for index, (kind, item) in enumerate(items, start=1):
        key = _item_key(kind, item)
        if kind == "movie":
            results.append(
                scan_movie(
                    item, c411, previous=previous_by_key.get(key), max_age_seconds=max_age_seconds,
                    path_mappings=radarr_path_mappings,
                )
            )  # type: ignore[arg-type]
        else:
            results.append(
                scan_series_season(
                    item, c411, previous=previous_by_key.get(key), max_age_seconds=max_age_seconds,
                    path_mappings=sonarr_path_mappings,
                )
            )  # type: ignore[arg-type]
        if on_progress is not None:
            on_progress(index, total)
    results.extend(carried_over)
    # `only` restreint ce qui est REINTERROGE cette passe, jamais ce qui est
    # CONSERVE du dernier scan -- incident reel signale par l'utilisateur
    # (2026-08-28) : un scan "Films seulement" effacait les series deja
    # scannees precedemment (et vice versa) au lieu de les laisser intactes.
    # Non applicable quand `selection` est fourni (deja gere ci-dessus, a
    # la granularite du titre individuel plutot que de la bibliotheque).
    if selection is None:
        if only == "movies":
            results.extend(r for r in (previous_results or []) if r.media_type == "series")
        elif only == "series":
            results.extend(r for r in (previous_results or []) if r.media_type == "movie")
    return results
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent (et que la suite existante n'a pas régressé)**

Run: `pytest tests/test_gapscan.py -v`
Expected: PASS (tous les tests, y compris les nouveaux et l'existant `_result_key`/`only`).

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan.py tests/test_gapscan.py
git commit -m "feat: gapscan.movie_key/series_key extraites, run_gapscan gagne selection"
```

---

## Task 2: `nfogen/gapscan_runner.py` — relayer `selection`

**Files:**
- Modify: `nfogen/gapscan_runner.py:113-206`
- Test: `tests/test_gapscan_runner.py`

**Interfaces:**
- Consumes: `run_gapscan(..., selection: Optional[set[tuple]] = None)` (Task 1).
- Produces: `start(..., selection: Optional[set[tuple]] = None) -> bool`.

- [ ] **Step 1: Écrire le test de relais**

Ajouter à `tests/test_gapscan_runner.py` (regarder l'existant pour le patron de fakes/attente de fin de thread déjà utilisé par les tests `only`/`incremental`) :

```python
def test_start_relays_selection_to_run_gapscan(monkeypatch):
    captured = {}

    def fake_run_gapscan(*args, **kwargs):
        captured["selection"] = kwargs.get("selection")
        return []

    monkeypatch.setattr(gapscan_runner, "run_gapscan", fake_run_gapscan)
    selection = {("movie", "tt001", 2020)}

    started = gapscan_runner.start(_FakeC411(), radarr=_FakeRadarr(), selection=selection)
    assert started
    _wait_until_done()  # reutiliser le helper d'attente deja present dans ce fichier de test

    assert captured["selection"] == selection
```

Adapter les noms de fakes/helpers au contenu réel du fichier de test existant.

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `pytest tests/test_gapscan_runner.py -v -k selection`
Expected: FAIL (`start()` ne connaît pas `selection`).

- [ ] **Step 3: Implémenter**

Dans `nfogen/gapscan_runner.py`, `_run()` gagne le paramètre et le relaie :

```python
def _run(
    c411: TorznabClient,
    radarr: Optional[RadarrClient],
    sonarr: Optional[SonarrClient],
    previous_results: Optional[list[GapResult]],
    only: Optional[str],
    max_age_seconds: Optional[float],
    sonarr_path_mappings: Optional[dict[str, str]],
    radarr_path_mappings: Optional[dict[str, str]],
    selection: Optional[set[tuple]],
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
            selection=selection,
        )
```

(le reste du corps de `_run` est inchangé). Et `start()` :

```python
def start(
    c411: TorznabClient,
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
    incremental: bool = False,
    only: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
    selection: Optional[set[tuple]] = None,
) -> bool:
    """... (docstring existant, ajouter le paragraphe suivant) ...

    `selection` (AUTOMATION.md, sous-projet 8) : relaye tel quel a
    run_gapscan() -- restreint les items reellement interroges sur C411 a
    ceux dont la cle (gapscan.movie_key/series_key) est dans cet ensemble.
    A priorite sur `only` si les deux sont fournis."""
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
            sonarr_path_mappings, radarr_path_mappings, selection,
        ),
        daemon=True,
    )
    thread.start()
    return True
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_gapscan_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_runner.py tests/test_gapscan_runner.py
git commit -m "feat: gapscan_runner.start relaie selection a run_gapscan"
```

---

## Task 3: `nfogen/radarr_client.py` — `genres`/`added_at`

**Files:**
- Modify: `nfogen/radarr_client.py:20-46,109-135`
- Test: `tests/test_radarr_client.py`

**Interfaces:**
- Produces: `RadarrMovieFile.genres: list[str]`, `RadarrMovieFile.added_at: Optional[float]`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/test_radarr_client.py` (réutiliser le patron de mock HTTP déjà en place pour `list_movie_files`) :

```python
def test_list_movie_files_extracts_genres_and_added_at(respx_mock_or_equivalent):
    # Reutiliser le meme mecanisme de mock que les tests list_movie_files
    # existants ; ajouter "genres": ["Action", "Thriller"] et
    # "added": "2024-03-15T10:30:00Z" au JSON de film mocke.
    ...
    movies = client.list_movie_files()
    assert movies[0].genres == ["Action", "Thriller"]
    assert movies[0].added_at is not None  # epoch, valeur exacte verifiee ci-dessous


def test_list_movie_files_added_at_matches_iso_date(...):
    # "added": "2024-03-15T10:30:00Z" -> epoch attendu (calcule via
    # datetime.fromisoformat / dateutil, meme lib que _parse_radarr_date)
    import datetime
    expected = datetime.datetime(2024, 3, 15, 10, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
    ...
    assert movies[0].added_at == expected


def test_list_movie_files_defaults_genres_and_added_at_when_absent():
    # Film sans "genres" ni "added" dans le JSON -> genres == [], added_at is None
    ...
    assert movies[0].genres == []
    assert movies[0].added_at is None


def test_list_movie_files_added_at_none_on_unparseable_date():
    # "added": "not-a-date" -> added_at None, jamais d'exception
    ...
    assert movies[0].added_at is None
```

Écrire ces tests en réutilisant exactement le mécanisme de mock HTTP déjà présent dans `tests/test_radarr_client.py` (lire le fichier avant d'écrire — probablement `httpx.MockTransport` ou un client factice construit avec `http_client=...`, cohérent avec le constructeur `RadarrClient(base_url, api_key, http_client=...)`).

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_radarr_client.py -v -k "genres or added_at"`
Expected: FAIL (`AttributeError: genres`/`added_at`).

- [ ] **Step 3: Implémenter**

Dans `nfogen/radarr_client.py`, ajouter en haut du fichier :

```python
import datetime
```

Ajouter à `RadarrMovieFile` (après `remote_path`) :

```python
    # Genres Radarr/Sonarr (PAS la categorie C411) -- utilise par la vue
    # "Bibliotheque" (AUTOMATION.md, sous-projet 8), jamais pendant un scan
    # GapScan classique (voir gapscan.genre_of, base sur la categorie du
    # match C411 trouve -- deux classifications independantes).
    genres: list[str] = field(default_factory=list)
    # Horodatage (epoch secondes) d'ajout a Radarr -- `None` si absent ou
    # illisible (jamais une exception, voir _parse_radarr_date).
    added_at: Optional[float] = None
```

Ajouter la fonction utilitaire (avant `class RadarrClient`) :

```python
def _parse_radarr_date(value: Optional[str]) -> Optional[float]:
    """`movie.get("added")` (ISO 8601, ex. "2024-03-15T10:30:00Z") -> epoch
    secondes, ou `None` si absent/illisible -- jamais une exception (champ
    jamais lu par ce projet avant le sous-projet 8, a verifier contre une
    vraie reponse Radarr avant de considerer cette tache terminee)."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
```

Dans `list_movie_files()`, ajouter dans le constructeur de `RadarrMovieFile` :

```python
                    remote_path=movie_file.get("path"),
                    genres=movie.get("genres") or [],
                    added_at=_parse_radarr_date(movie.get("added")),
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_radarr_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/radarr_client.py tests/test_radarr_client.py
git commit -m "feat: RadarrMovieFile expose genres/added_at (bibliotheque, sous-projet 8)"
```

---

## Task 4: `nfogen/sonarr_client.py` — `genres`/`added_at`

**Files:**
- Modify: `nfogen/sonarr_client.py:21-49,111-157`
- Test: `tests/test_sonarr_client.py`

**Interfaces:**
- Produces: `SonarrSeasonFile.genres: list[str]`, `SonarrSeasonFile.added_at: Optional[float]`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/test_sonarr_client.py` :

```python
def test_list_season_files_extracts_genres_from_series(...):
    # series.json: "genres": ["Drama"] ; verifie que CHAQUE saison de cette
    # serie recoit ces genres (le genre est au niveau serie, pas saison).
    ...
    assert all(s.genres == ["Drama"] for s in seasons)


def test_list_season_files_added_at_uses_max_episode_date_in_season(...):
    # Saison avec 2 fichiers episode : dateAdded "2024-01-01..." et
    # "2024-06-01..." -> added_at de la saison == epoch du PLUS RECENT
    # des deux (2024-06-01), jamais la date de la serie entiere.
    ...
    assert seasons[0].added_at == expected_max_epoch


def test_list_season_files_defaults_when_absent():
    ...
    assert seasons[0].genres == []
    assert seasons[0].added_at is None
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_sonarr_client.py -v -k "genres or added_at"`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

Dans `nfogen/sonarr_client.py`, ajouter `import datetime` en haut, ajouter à `SonarrSeasonFile` (après `remote_paths`) :

```python
    # Genres Sonarr (au niveau serie -- Sonarr n'a pas de genre par saison)
    # -- meme role que RadarrMovieFile.genres, voir la-bas.
    genres: list[str] = field(default_factory=list)
    # Horodatage (epoch secondes) le PLUS RECENT parmi les fichiers episode
    # de CETTE saison -- pas la date d'ajout de la serie entiere, qui ne
    # distinguerait pas les saisons (voir _parse_sonarr_date).
    added_at: Optional[float] = None
```

Ajouter la fonction utilitaire (avant `class SonarrClient`, dupliquée volontairement de `_parse_radarr_date` — les deux clients restent indépendants, comme le reste du fichier) :

```python
def _parse_sonarr_date(value: Optional[str]) -> Optional[float]:
    """Meme role que radarr_client._parse_radarr_date, duplique ici plutot
    que partage -- radarr_client.py et sonarr_client.py restent
    volontairement independants (voir leurs docstrings de module)."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
```

Dans `list_season_files()`, calculer `added_at` par saison à partir de `season_files` (la liste déjà agrégée pour cette saison) :

```python
            for season_number, season_files in by_season.items():
                best = max(
                    season_files,
                    key=lambda f: (f.get("quality", {}).get("quality", {}).get("resolution") or 0),
                )
                quality = best.get("quality", {}).get("quality", {}) or {}
                added_dates = [
                    d for d in (_parse_sonarr_date(f.get("dateAdded")) for f in season_files) if d is not None
                ]
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
                        genres=series.get("genres") or [],
                        added_at=max(added_dates) if added_dates else None,
                    )
                )
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_sonarr_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/sonarr_client.py tests/test_sonarr_client.py
git commit -m "feat: SonarrSeasonFile expose genres/added_at (bibliotheque, sous-projet 8)"
```

---

## Task 5: `nfogen/upload_history_store.py` (nouveau)

**Files:**
- Create: `nfogen/upload_history_store.py`
- Test: `tests/test_upload_history_store.py`

**Interfaces:**
- Produces: `processed_key(media_type, radarr_movie_id, sonarr_series_id, season_number=None) -> Optional[tuple]`, `record(key, *, kind, release_name, at=None) -> None`, `is_processed(key) -> bool`, `last_processed_at(key) -> Optional[float]`, `key_str(key) -> str`.

**Design note (résolution d'une ambiguïté de la spec) :** la spec (section "Threading des identifiants") évoque un `key` "calculé depuis les champs identifiants" transmis à `commit_job_runner.start()`/`send_to_tracker()`. Ces deux points d'appel possèdent déjà `media_type`/`radarr_movie_id`/`sonarr_series_id`/`season_number` (`tmdb_id`/`tvdb_id` aussi côté `send_to_tracker`, mais PAS `imdb_id`/`title`/`year`, nécessaires à `movie_key`/`series_key`). `processed_key` est donc une fonction **distincte** de `movie_key`/`series_key` (Task 1) : elle n'a besoin que des identifiants Radarr/Sonarr internes déjà disponibles à ces deux endroits, sans plomberie supplémentaire.

- [ ] **Step 1: Écrire les tests**

Créer `tests/test_upload_history_store.py` :

```python
"""Tests de nfogen.upload_history_store (AUTOMATION.md, sous-projet 8)."""
from __future__ import annotations

import json

import pytest

from nfogen import upload_history_store


@pytest.fixture(autouse=True)
def history_file(tmp_path, monkeypatch):
    path = tmp_path / "upload_history.json"
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(path))
    return path


def test_processed_key_for_movie():
    assert upload_history_store.processed_key("movie", 42, None) == ("movie", 42)


def test_processed_key_for_series_includes_season():
    assert upload_history_store.processed_key("series", None, 7, season_number=3) == ("series", 7, 3)


def test_processed_key_returns_none_without_usable_identifier():
    assert upload_history_store.processed_key("movie", None, None) is None
    assert upload_history_store.processed_key("series", None, None, season_number=1) is None


def test_record_then_is_processed():
    key = ("movie", 42)
    assert not upload_history_store.is_processed(key)
    upload_history_store.record(key, kind="committed", release_name="Movie.2020-TEAM")
    assert upload_history_store.is_processed(key)


def test_record_is_idempotent_by_key_and_kind_updates_timestamp():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="Movie.2020-TEAM", at=1000.0)
    upload_history_store.record(key, kind="committed", release_name="Movie.2020-TEAM", at=2000.0)
    assert upload_history_store.last_processed_at(key) == 2000.0


def test_last_processed_at_takes_most_recent_across_kinds():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="r", at=1000.0)
    upload_history_store.record(key, kind="sent", release_name="r", at=2000.0)
    assert upload_history_store.last_processed_at(key) == 2000.0


def test_last_processed_at_none_for_unknown_key():
    assert upload_history_store.last_processed_at(("movie", 999)) is None


def test_key_str_is_stable_json_serialization():
    assert upload_history_store.key_str(("movie", 42)) == json.dumps(["movie", 42])


def test_not_configured_without_env_var(monkeypatch):
    monkeypatch.delenv("NFOGEN_UPLOAD_HISTORY_FILE", raising=False)
    # No-op silencieux : jamais d'exception, is_processed reste False.
    upload_history_store.record(("movie", 1), kind="committed", release_name="r")
    assert not upload_history_store.is_processed(("movie", 1))


def test_record_never_raises_on_write_failure(monkeypatch, history_file):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    # Ne doit jamais lever -- un Confirmer/Envoi reussi ne doit jamais
    # echouer a cause de l'ecriture de l'historique (spec, "Gestion des erreurs").
    upload_history_store.record(("movie", 1), kind="committed", release_name="r")


def test_load_tolerates_corrupt_file(history_file):
    history_file.write_text("not json", encoding="utf-8")
    assert not upload_history_store.is_processed(("movie", 1))
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_upload_history_store.py -v`
Expected: FAIL (`ModuleNotFoundError: nfogen.upload_history_store`).

- [ ] **Step 3: Implémenter**

Créer `nfogen/upload_history_store.py` :

```python
"""Historique persistant des titres deja traites par nfogen (Confirmer
et/ou Envoyer a C411) -- AUTOMATION.md, sous-projet 8.

Meme patron de persistance que `gapscan_results_store.py` : fichier JSON
optionnel (`NFOGEN_UPLOAD_HISTORY_FILE`), tolerant a un fichier absent ou
corrompu, jamais une erreur fatale pour le reste de nfogen.

Grandit indefiniment pour l'instant (pas de purge/expiration -- volume
attendu faible, un enregistrement par Confirmer/Envoi reussi, pas par
scan ; voir la spec, "Non-objectifs").

`processed_key` est VOLONTAIREMENT distincte de `gapscan.movie_key`/
`series_key` (cles bibliotheque/mode incremental, basees sur imdb/tmdb/
titre/annee) : les points d'appel de ce module (`commit_job_runner.py`,
`upload_prep.py:send_to_tracker`) n'ont que `radarr_movie_id`/
`sonarr_series_id` sous la main, deja suffisants pour identifier un titre
de facon stable sans plomberie supplementaire (imdb_id/tmdb_id/title/year
ne sont pas transmis a ces deux endroits)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def processed_key(
    media_type: str,
    radarr_movie_id: Optional[int],
    sonarr_series_id: Optional[int],
    season_number: Optional[int] = None,
) -> Optional[tuple]:
    """`None` si aucun identifiant Radarr/Sonarr utilisable -- jamais de
    cle devinee a partir d'autre chose (coherent avec "jamais deviner",
    voir la spec)."""
    if media_type == "movie" and radarr_movie_id is not None:
        return ("movie", radarr_movie_id)
    if media_type == "series" and sonarr_series_id is not None:
        return ("series", sonarr_series_id, season_number)
    return None


def key_str(key: tuple) -> str:
    """Serialisation JSON stable d'une cle -- reutilisee par
    gapscan_library.py pour serialiser la cle de SELECTION (movie_key/
    series_key, differente de processed_key) sur le fil HTTP."""
    return json.dumps(list(key))


def _path() -> Optional[Path]:
    root = os.environ.get("NFOGEN_UPLOAD_HISTORY_FILE")
    return Path(root) if root else None


def _load() -> dict[str, Any]:
    path = _path()
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _save(data: dict[str, Any]) -> None:
    path = _path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError:
        pass


def record(key: tuple, *, kind: str, release_name: str, at: Optional[float] = None) -> None:
    """Ajoute/met a jour une entree -- kind: "committed" (Confirmer reussi)
    ou "sent" (Envoyer a C411 reussi). Idempotent par cle+kind : un nouvel
    appel sur la meme cle+kind met a jour l'horodatage plutot que
    d'accumuler des doublons. N'ECHOUE JAMAIS (try/except large) : un
    Confirmer/Envoi par ailleurs reussi ne doit jamais etre bloque par un
    probleme d'ecriture de cet historique, purement informatif."""
    try:
        data = _load()
        entry = data.setdefault(key_str(key), {})
        entry[kind] = {"release_name": release_name, "at": at if at is not None else time.time()}
        _save(data)
    except Exception:  # noqa: BLE001 -- jamais propager, voir docstring
        pass


def is_processed(key: tuple) -> bool:
    return bool(_load().get(key_str(key)))


def last_processed_at(key: tuple) -> Optional[float]:
    entry = _load().get(key_str(key))
    if not entry:
        return None
    timestamps = [v["at"] for v in entry.values() if "at" in v]
    return max(timestamps) if timestamps else None
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_upload_history_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_history_store.py tests/test_upload_history_store.py
git commit -m "feat: historique persistant des titres deja traites (upload_history_store)"
```

---

## Task 6: `nfogen/gapscan_library.py` (nouveau)

**Files:**
- Create: `nfogen/gapscan_library.py`
- Test: `tests/test_gapscan_library.py`

**Interfaces:**
- Consumes: `RadarrClient.list_movie_files()`, `SonarrClient.list_season_files()` (Tasks 3-4), `quality.build_quality`, `gapscan.movie_key`/`series_key` (Task 1), `upload_history_store.processed_key`/`is_processed`/`last_processed_at`/`key_str` (Task 5).
- Produces: `LibraryItem` dataclass, `list_library(radarr=None, sonarr=None) -> list[LibraryItem]`.

- [ ] **Step 1: Écrire les tests**

Créer `tests/test_gapscan_library.py` :

```python
"""Tests de nfogen.gapscan_library (AUTOMATION.md, sous-projet 8) --
inventaire local, ZERO appel tracker."""
from __future__ import annotations

import pytest

from nfogen import gapscan_library, upload_history_store
from nfogen.gapscan import movie_key, series_key
from nfogen.radarr_client import RadarrMovieFile
from nfogen.sonarr_client import SonarrSeasonFile


class _FakeRadarr:
    def __init__(self, movies):
        self._movies = movies
        self.list_movie_files_called = 0

    def list_movie_files(self):
        self.list_movie_files_called += 1
        return self._movies


class _FakeSonarr:
    def __init__(self, seasons):
        self._seasons = seasons

    def list_season_files(self):
        return self._seasons


class _ExplodingC411:
    """N'importe quel appel doit faire echouer le test -- garantit que
    list_library() n'appelle jamais le tracker."""

    def search_movie(self, *a, **k):
        raise AssertionError("gapscan_library ne doit jamais appeler le tracker")

    def search_tv(self, *a, **k):
        raise AssertionError("gapscan_library ne doit jamais appeler le tracker")


@pytest.fixture(autouse=True)
def history_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))


def test_list_library_never_touches_c411():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    radarr = _FakeRadarr([movie])
    items = gapscan_library.list_library(radarr=radarr, sonarr=None)
    assert len(items) == 1
    assert radarr.list_movie_files_called == 1


def test_list_library_builds_movie_item_with_selection_key():
    movie = RadarrMovieFile(
        movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1,
        genres=["Action"],
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    item = items[0]
    assert item.media_type == "movie"
    assert item.title == "Movie"
    assert item.genres == ["Action"]
    assert item.radarr_movie_id == 1
    assert item.key == upload_history_store.key_str(movie_key("tt001", "1", "Movie", 2020))


def test_list_library_marks_already_processed_movie():
    movie = RadarrMovieFile(movie_id=42, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    upload_history_store.record(
        upload_history_store.processed_key("movie", 42, None), kind="committed", release_name="r",
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].already_processed is True
    assert items[0].last_processed_at is not None


def test_list_library_marks_series_season_not_processed_by_default():
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    items = gapscan_library.list_library(radarr=None, sonarr=_FakeSonarr([season]))
    assert items[0].already_processed is False
    assert items[0].last_processed_at is None
    assert items[0].key == upload_history_store.key_str(series_key(99, None, "Show", 1))


def test_list_library_combines_movies_and_series():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=_FakeSonarr([season]))
    assert len(items) == 2
    assert {i.media_type for i in items} == {"movie", "series"}


def test_list_library_empty_without_any_client():
    assert gapscan_library.list_library(radarr=None, sonarr=None) == []
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_gapscan_library.py -v`
Expected: FAIL (`ModuleNotFoundError: nfogen.gapscan_library`).

- [ ] **Step 3: Implémenter**

Créer `nfogen/gapscan_library.py` :

```python
"""Inventaire local Radarr/Sonarr, SANS AUCUN appel tracker (AUTOMATION.md,
sous-projet 8) -- pour un rechargement quasi instantane meme sur une
grosse bibliotheque ("recharger sans faire de scan C411, car c'est une
API et une action longue", retour utilisateur 2026-09-06).

Reutilise list_movie_files()/list_season_files() (deja utilises par
gapscan.run_gapscan) -- rien de nouveau cote Radarr/Sonarr au-dela des
champs genres/added_at ajoutes par les sous-taches precedentes.

`LibraryItem.key` (cle de SELECTION, movie_key/series_key -- voir
gapscan.py) est DIFFERENTE de `already_processed`/`last_processed_at`
(bases sur upload_history_store.processed_key, radarr_movie_id/
sonarr_series_id) : la premiere sert a retrouver l'item dans
run_gapscan(), la seconde a savoir s'il a deja ete confirme/envoye."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import upload_history_store
from .gapscan import movie_key, series_key
from .quality import ReleaseQuality, build_quality
from .radarr_client import RadarrClient
from .sonarr_client import SonarrClient


@dataclass
class LibraryItem:
    media_type: str  # "movie" | "series"
    title: str
    year: Optional[int]
    season_number: Optional[int]  # None pour un film
    imdb_id: Optional[str]
    tvdb_id: Optional[int]
    tmdb_id: Optional[str]
    genres: list[str]
    added_at: Optional[float]
    local_quality: ReleaseQuality
    radarr_movie_id: Optional[int]
    sonarr_series_id: Optional[int]
    already_processed: bool
    last_processed_at: Optional[float]
    # Cle de SELECTION serialisee (movie_key/series_key, voir gapscan.py) --
    # chaine opaque du point de vue du frontend, renvoyee telle quelle a
    # POST /gapscan/run pour restreindre un scan a cet item precis.
    key: str


def list_library(
    radarr: Optional[RadarrClient] = None,
    sonarr: Optional[SonarrClient] = None,
) -> list[LibraryItem]:
    """Inventaire local complet (`radarr`/`sonarr` optionnels, l'un ou
    l'autre ou les deux) -- synchrone, jamais de tache de fond : uniquement
    des appels Radarr/Sonarr locaux/rapides, pas de rate-limit connu cote
    nfogen (contrairement a run_gapscan)."""
    items: list[LibraryItem] = []
    if radarr is not None:
        for movie in radarr.list_movie_files():
            tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
            proc_key = upload_history_store.processed_key("movie", movie.movie_id, None)
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
                    radarr_movie_id=movie.movie_id, sonarr_series_id=None,
                    already_processed=proc_key is not None and upload_history_store.is_processed(proc_key),
                    last_processed_at=upload_history_store.last_processed_at(proc_key) if proc_key else None,
                    key=upload_history_store.key_str(
                        movie_key(movie.imdb_id, tmdb_id, movie.title, movie.year)
                    ),
                )
            )
    if sonarr is not None:
        for season in sonarr.list_season_files():
            proc_key = upload_history_store.processed_key("series", None, season.series_id, season.season_number)
            items.append(
                LibraryItem(
                    media_type="series", title=season.title, year=season.year,
                    season_number=season.season_number, imdb_id=season.imdb_id,
                    tvdb_id=season.tvdb_id, tmdb_id=None,
                    genres=season.genres, added_at=season.added_at,
                    local_quality=build_quality(
                        season.scene_name or season.title,
                        fallback_resolution=season.best_resolution,
                        fallback_language_names=season.language_names,
                    ),
                    radarr_movie_id=None, sonarr_series_id=season.series_id,
                    already_processed=proc_key is not None and upload_history_store.is_processed(proc_key),
                    last_processed_at=upload_history_store.last_processed_at(proc_key) if proc_key else None,
                    key=upload_history_store.key_str(
                        series_key(season.tvdb_id, season.imdb_id, season.title, season.season_number)
                    ),
                )
            )
    return items
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_gapscan_library.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_library.py tests/test_gapscan_library.py
git commit -m "feat: gapscan_library.list_library -- inventaire local sans appel tracker"
```

---

## Task 7: `nfogen/commit_job_runner.py` — identifiants + historique

**Files:**
- Modify: `nfogen/commit_job_runner.py:50-111`
- Test: `tests/test_commit_job_runner.py`

**Interfaces:**
- Consumes: `upload_history_store.processed_key`/`record` (Task 5).
- Produces: `start(release_name, files, profile="c411", media_type="movie", radarr_movie_id=None, sonarr_series_id=None, season_number=None) -> str`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/test_commit_job_runner.py` (réutiliser les fakes `upload_prep.commit_upload` déjà monkeypatchés par les tests existants) :

```python
def test_start_records_history_on_done(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(upload_prep, "resolve_staging_config", lambda profile: ("/staging", "https://ann"))
    monkeypatch.setattr(
        upload_prep, "commit_upload",
        lambda *a, **k: upload_prep.CommitResult(
            release_name="R", staged_path="/staging/R.mkv",
            torrent_path="/staging/R.torrent", nfo_path="/staging/R.nfo",
        ),
    )

    job_id = commit_job_runner.start(
        "R", [], media_type="movie", radarr_movie_id=42,
    )
    _wait_for_terminal_state(job_id)  # reutiliser le helper deja present dans ce fichier

    key = upload_history_store.processed_key("movie", 42, None)
    assert upload_history_store.is_processed(key)


def test_start_without_identifiers_does_not_record_history(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(upload_prep, "resolve_staging_config", lambda profile: ("/staging", "https://ann"))
    monkeypatch.setattr(
        upload_prep, "commit_upload",
        lambda *a, **k: upload_prep.CommitResult(
            release_name="R", staged_path="/staging/R.mkv",
            torrent_path="/staging/R.torrent", nfo_path="/staging/R.nfo",
        ),
    )

    job_id = commit_job_runner.start("R", [])  # aucun identifiant fourni
    _wait_for_terminal_state(job_id)

    assert not upload_history_store.is_processed(("movie", 42))
```

Adapter `_wait_for_terminal_state`/imports au contenu réel du fichier de test existant (probablement un simple `time.sleep`/polling déjà en place pour les autres tests de ce module).

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_commit_job_runner.py -v -k history`
Expected: FAIL (`start()` ne connaît pas ces paramètres, ou l'historique n'est jamais écrit).

- [ ] **Step 3: Implémenter**

Dans `nfogen/commit_job_runner.py`, ajouter l'import :

```python
from . import upload_history_store
```

Modifier `start()` et `_run()` :

```python
def start(
    release_name: str,
    files: list[upload_prep.ProposedFile],
    profile: str = "c411",
    media_type: str = "movie",
    radarr_movie_id: Optional[int] = None,
    sonarr_series_id: Optional[int] = None,
    season_number: Optional[int] = None,
) -> str:
    """Verifie d'abord la configuration (rapide, voir
    upload_prep.resolve_staging_config -- leve ValueError/RuntimeError
    IMMEDIATEMENT si mal configure, avant meme de creer une tache), puis
    demarre la mise en scene + generation en tache de fond et renvoie le
    `job_id` SANS ATTENDRE la fin.

    `media_type`/`radarr_movie_id`/`sonarr_series_id`/`season_number`
    (AUTOMATION.md, sous-projet 8, tous optionnels) : identifient le titre
    pour l'historique "deja traite" (voir upload_history_store.py) --
    absents, aucune entree d'historique n'est enregistree pour cette
    tache (degrade proprement, jamais bloquant)."""
    upload_prep.resolve_staging_config(profile)

    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job = JobProgress(job_id=job_id, release_name=release_name, state=JobState.STAGING)
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel_event

    thread = threading.Thread(
        target=_run,
        args=(
            job_id, release_name, files, profile, cancel_event,
            media_type, radarr_movie_id, sonarr_series_id, season_number,
        ),
        daemon=True,
    )
    thread.start()
    return job_id


def _run(
    job_id: str,
    release_name: str,
    files: list[upload_prep.ProposedFile],
    profile: str,
    cancel_event: threading.Event,
    media_type: str,
    radarr_movie_id: Optional[int],
    sonarr_series_id: Optional[int],
    season_number: Optional[int],
) -> None:
    def on_progress(step: str, percent: float) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.state = JobState(step)
                job.percent = percent

    try:
        result = upload_prep.commit_upload(
            release_name, files, profile, on_progress=on_progress, cancel_event=cancel_event
        )
        with _lock:
            job = _jobs[job_id]
            job.state = JobState.DONE
            job.percent = 100.0
            job.result = {
                "release_name": result.release_name, "staged_path": result.staged_path,
                "torrent_path": result.torrent_path, "nfo_path": result.nfo_path,
            }
            job.finished_at = time.time()
        key = upload_history_store.processed_key(
            media_type, radarr_movie_id, sonarr_series_id, season_number
        )
        if key is not None:
            upload_history_store.record(key, kind="committed", release_name=release_name)
    except OperationCancelled:
        with _lock:
            job = _jobs[job_id]
            job.state = JobState.CANCELLED
            job.finished_at = time.time()
    except Exception as exc:  # noqa: BLE001 -- toute erreur -> etat "error", jamais un thread qui meurt en silence
        with _lock:
            job = _jobs[job_id]
            job.state = JobState.ERROR
            job.error = str(exc)
            job.finished_at = time.time()
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_commit_job_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/commit_job_runner.py tests/test_commit_job_runner.py
git commit -m "feat: commit_job_runner enregistre l'historique 'deja traite' sur succes"
```

---

## Task 8: `nfogen/upload_prep.py` — `send_to_tracker` enregistre l'historique

**Files:**
- Modify: `nfogen/upload_prep.py:322-446`
- Test: `tests/test_upload_prep.py` (ou `tests/test_c411.py` selon où vivent déjà les tests de `send_to_tracker` — vérifier avant d'écrire)

**Interfaces:**
- Consumes: `upload_history_store.processed_key`/`record` (Task 5).

- [ ] **Step 1: Écrire le test**

Localiser le fichier de test existant pour `send_to_tracker` (`grep -rn "send_to_tracker" tests/`) et y ajouter :

```python
def test_send_to_tracker_records_history_on_success(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    # Reutiliser les monkeypatch deja en place dans ce fichier pour
    # gapscan_config_store.effective_tracker / C411UploadClient.create_draft
    # (voir les tests send_to_tracker existants), avec radarr_movie_id=42.
    ...
    upload_prep.send_to_tracker(
        release_name="R", staged_path="/s/R.mkv", torrent_path="/s/R.torrent",
        nfo_path="/s/R.nfo", media_type="movie", radarr_movie_id=42,
    )
    key = upload_history_store.processed_key("movie", 42, None)
    assert upload_history_store.is_processed(key)


def test_send_to_tracker_without_identifiers_does_not_record_history(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    ...
    upload_prep.send_to_tracker(
        release_name="R", staged_path="/s/R.mkv", torrent_path="/s/R.torrent", nfo_path="/s/R.nfo",
    )
    assert not upload_history_store.is_processed(("movie", 42))
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `pytest tests/test_upload_prep.py -v -k history` (adapter le chemin au fichier réellement trouvé)
Expected: FAIL.

- [ ] **Step 3: Implémenter**

Dans `nfogen/upload_prep.py`, ajouter l'import :

```python
from . import upload_history_store
```

Modifier la fin de `send_to_tracker()` (juste avant le `return SendResult(...)`, ligne ~442) :

```python
    result = SendResult(
        draft_id=response.get("id"), draft_url=response.get("url", ""),
        duplicate_warning=duplicate_warning,
    )
    key = upload_history_store.processed_key(media_type, radarr_movie_id, sonarr_series_id, season_number)
    if key is not None:
        upload_history_store.record(key, kind="sent", release_name=release_name)
    return result
```

(remplace le `return SendResult(...)` existant).

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_upload_prep.py -v` (ou le fichier réel identifié à l'étape 1)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "feat: send_to_tracker enregistre l'historique 'deja traite' sur succes"
```

---

## Task 9: `nfogen/api.py` — `GET /gapscan/library`

**Files:**
- Modify: `nfogen/api.py` (imports ligne ~57-67, nouvel endpoint après `gapscan_results_export_csv`)
- Test: `tests/test_api.py` (ou `tests/test_api_gapscan.py` — vérifier lequel héberge déjà les tests `/gapscan/*`)

**Interfaces:**
- Consumes: `gapscan_library.list_library` (Task 6), `gapscan_config_store.effective_sonarr`/`effective_radarr`.
- Produces: `GET /gapscan/library` → `{"items": [...], "total": N}`.

- [ ] **Step 1: Écrire les tests**

Localiser le fichier de test existant pour les routes `/gapscan/*` et y ajouter (réutiliser le patron de `TestClient`/monkeypatch déjà en place pour `_build_gapscan_clients`) :

```python
def test_gapscan_library_returns_items_from_radarr_and_sonarr(monkeypatch, client_with_token):
    monkeypatch.setattr(
        "nfogen.gapscan_config_store.effective_radarr", lambda: ("http://r", "key")
    )
    monkeypatch.setattr(
        "nfogen.gapscan_config_store.effective_sonarr", lambda: None
    )
    monkeypatch.setattr(
        "nfogen.gapscan_library.list_library",
        lambda radarr=None, sonarr=None: [
            gapscan_library.LibraryItem(
                media_type="movie", title="Movie", year=2020, season_number=None,
                imdb_id="tt001", tvdb_id=None, tmdb_id="1", genres=["Action"], added_at=None,
                local_quality=build_quality(None), radarr_movie_id=1, sonarr_series_id=None,
                already_processed=False, last_processed_at=None, key='["movie","tt001",2020]',
            )
        ],
    )
    resp = client_with_token.get("/gapscan/library")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Movie"


def test_gapscan_library_400_without_sonarr_or_radarr(monkeypatch, client_with_token):
    monkeypatch.setattr("nfogen.gapscan_config_store.effective_radarr", lambda: None)
    monkeypatch.setattr("nfogen.gapscan_config_store.effective_sonarr", lambda: None)
    resp = client_with_token.get("/gapscan/library")
    assert resp.status_code == 400


def test_gapscan_library_filters_by_media_type(monkeypatch, client_with_token):
    # Deux items (movie + series) retournes par list_library, filtre
    # media_type=movie -> un seul dans la reponse.
    ...


def test_gapscan_library_filters_by_processed(monkeypatch, client_with_token):
    ...


def test_gapscan_library_filters_by_added_since_days(monkeypatch, client_with_token):
    ...


def test_gapscan_library_paginates(monkeypatch, client_with_token):
    ...
```

Adapter les noms de fixtures (`client_with_token` ou équivalent) au patron déjà utilisé par les autres tests `/gapscan/*` de ce fichier.

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_api.py -v -k gapscan_library` (chemin réel à adapter)
Expected: FAIL (`404 Not Found`).

- [ ] **Step 3: Implémenter**

Dans `nfogen/api.py`, ajouter à l'import GapScan (ligne ~57-64) :

```python
    from . import (
        commit_job_runner,
        gapscan,
        gapscan_config_store,
        gapscan_library,
        gapscan_runner,
        tracker_profile,
        upload_prep,
    )
```

Ajouter l'endpoint après `gapscan_results_export_csv` (avant la section "Preparation d'upload") :

```python
@app.get("/gapscan/library", dependencies=[Depends(require_token)])
def gapscan_library_endpoint(
    q: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    added_since_days: Optional[float] = Query(None),
    processed: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Inventaire local Radarr/Sonarr, ZERO appel tracker (AUTOMATION.md,
    sous-projet 8) -- rechargement quasi instantane, contrairement a
    POST /gapscan/run. `q` : recherche texte sur le titre (insensible a la
    casse, sous-chaine). `added_since_days` : ne garde que les items
    ajoutes il y a moins de N jours (ignore les items sans added_at
    connu). `processed` : filtre sur already_processed."""
    _require_gapscan_available()
    sonarr_config = gapscan_config_store.effective_sonarr()
    sonarr = SonarrClient(*sonarr_config) if sonarr_config else None
    radarr_config = gapscan_config_store.effective_radarr()
    radarr = RadarrClient(*radarr_config) if radarr_config else None
    if sonarr is None and radarr is None:
        raise HTTPException(
            status_code=400,
            detail="Aucune instance Sonarr ni Radarr configuree "
            "(NFOGEN_SONARR_URL/_API_KEY et/ou NFOGEN_RADARR_URL/_API_KEY, ou PUT /gapscan/config).",
        )
    try:
        items = gapscan_library.list_library(radarr=radarr, sonarr=sonarr)
    except (RadarrError, SonarrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if sonarr is not None:
            sonarr.close()
        if radarr is not None:
            radarr.close()

    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in i.title.lower()]
    if media_type is not None:
        items = [i for i in items if i.media_type == media_type]
    if genre is not None:
        items = [i for i in items if genre in i.genres]
    if added_since_days is not None:
        cutoff = time.time() - added_since_days * 86400
        items = [i for i in items if i.added_at is not None and i.added_at >= cutoff]
    if processed is not None:
        items = [i for i in items if i.already_processed == processed]

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return {"items": [asdict(i) for i in page_items], "total": total}
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_api.py -v -k gapscan_library` (chemin réel)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: GET /gapscan/library -- inventaire local, zero appel tracker"
```

---

## Task 10: `nfogen/api.py` — `POST /gapscan/run` gagne `selection`

**Files:**
- Modify: `nfogen/api.py:778-837`
- Test: même fichier que Task 9

**Interfaces:**
- Consumes: `gapscan_runner.start(..., selection=...)` (Task 2).

- [ ] **Step 1: Écrire les tests**

```python
def test_gapscan_run_with_selection_decodes_and_relays(monkeypatch, client_with_token):
    captured = {}
    monkeypatch.setattr(
        "nfogen.gapscan_runner.start",
        lambda *a, **k: captured.update(k) or True,
    )
    # ... monkeypatch _build_gapscan_clients comme les tests gapscan_run existants ...
    resp = client_with_token.post(
        "/gapscan/run", json={"selection": ['["movie", "tt001", 2020]']}
    )
    assert resp.status_code == 200
    assert captured["selection"] == {("movie", "tt001", 2020)}


def test_gapscan_run_with_invalid_selection_key_returns_400(client_with_token):
    resp = client_with_token.post("/gapscan/run", json={"selection": ["not json"]})
    assert resp.status_code == 400


def test_gapscan_run_without_selection_still_works(monkeypatch, client_with_token):
    # Non-regression : le corps de requete est optionnel, l'appel existant
    # sans body (query params seuls) continue de fonctionner.
    ...
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_api.py -v -k "gapscan_run_with_selection or invalid_selection"`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

Ajouter avant `gapscan_run` dans `nfogen/api.py` :

```python
class GapscanRunRequest(BaseModel):
    # Cles serialisees en JSON (voir gapscan.movie_key/series_key,
    # upload_history_store.key_str) -- transport opaque, decodees ci-dessous.
    selection: Optional[list[str]] = None
```

Modifier la signature et le corps de `gapscan_run` :

```python
@app.post("/gapscan/run", dependencies=[Depends(require_token)])
def gapscan_run(
    incremental: bool = Query(False),
    only: Optional[str] = Query(None),
    profile: str = Query("c411"),
    req: GapscanRunRequest = GapscanRunRequest(),
) -> dict[str, str]:
    """... (docstring existant, ajouter :) ...

    `req.selection` (AUTOMATION.md, sous-projet 8, optionnel) : cles
    serialisees en JSON (voir gapscan.movie_key/series_key) -- decodees ici
    puis transmises telles quelles a gapscan_runner.start(). A priorite sur
    `only` (gere par run_gapscan lui-meme). Une cle mal formee (JSON
    invalide) -> 400 ; une cle bien formee mais ne correspondant a aucun
    item reel est simplement ignoree plus loin (jamais une erreur)."""
    _require_gapscan_available()
    if only not in (None, "movies", "series"):
        raise HTTPException(status_code=400, detail="only doit valoir 'movies' ou 'series'.")
    selection: Optional[set[tuple]] = None
    if req.selection:
        try:
            selection = {tuple(json.loads(k)) for k in req.selection}
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Clé de sélection invalide : {exc}") from exc
    try:
        tracker_client, sonarr, radarr, sonarr_path_mappings, radarr_path_mappings = (
            _build_gapscan_clients(profile)
        )
    except (ValueError, TorznabError, SonarrError, RadarrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Bug reel trouve en audit (2026-08-27) : "au moins Sonarr OU Radarr
    # configure" (verifie par _build_gapscan_clients) ne suffit pas quand
    # `only` cible precisement celui qui MANQUE -- sans ce garde-fou, le
    # scan "reussissait" en silence avec 0 titre traite.
    if only == "movies" and radarr is None:
        tracker_client.close()
        if sonarr is not None:
            sonarr.close()
        raise HTTPException(
            status_code=400,
            detail="only=movies demande, mais Radarr n'est pas configure.",
        )
    if only == "series" and sonarr is None:
        tracker_client.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(
            status_code=400,
            detail="only=series demande, mais Sonarr n'est pas configure.",
        )

    max_age_days = float(os.environ.get("NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS", "7"))
    max_age_seconds = max_age_days * 86400 if incremental else None
    started = gapscan_runner.start(
        tracker_client, radarr=radarr, sonarr=sonarr, incremental=incremental,
        only=only, max_age_seconds=max_age_seconds,
        sonarr_path_mappings=sonarr_path_mappings, radarr_path_mappings=radarr_path_mappings,
        selection=selection,
    )
    if not started:
        tracker_client.close()
        if sonarr is not None:
            sonarr.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(status_code=409, detail="Un scan GapScan est deja en cours.")
    return {"status": "started"}
```

**Note FastAPI** : un `BaseModel` avec tous les champs optionnels (`GapscanRunRequest`) accepté en paramètre de fonction à côté de `Query(...)` fonctionne pour un corps JSON optionnel (FastAPI le traite comme le body request) — si un corps vide/absent pose un souci en pratique (`Content-Type` manquant), donner une valeur par défaut `Body(default=GapscanRunRequest())` explicite via `from fastapi import Body` à la place du défaut positionnel ; vérifier au Step 4 avec un test explicite "sans body".

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_api.py -v -k gapscan_run`
Expected: PASS (y compris les tests `gapscan_run` déjà existants, non régressés).

- [ ] **Step 5: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: POST /gapscan/run accepte une selection de cles (scan cible)"
```

---

## Task 11: `nfogen/api.py` — `PrepareUploadCommitRequest` gagne les identifiants

**Files:**
- Modify: `nfogen/api.py:946-965`
- Test: même fichier que Task 9

**Interfaces:**
- Consumes: `commit_job_runner.start(..., media_type=, radarr_movie_id=, sonarr_series_id=, season_number=)` (Task 7).

- [ ] **Step 1: Écrire le test**

```python
def test_prepare_upload_commit_relays_identifiers(monkeypatch, client_with_token):
    captured = {}
    monkeypatch.setattr(
        "nfogen.commit_job_runner.start",
        lambda *a, **k: captured.update(k) or "job-1",
    )
    resp = client_with_token.post(
        "/gapscan/prepare-upload/commit",
        json={
            "release_name": "R", "files": [],
            "media_type": "movie", "radarr_movie_id": 42,
        },
    )
    assert resp.status_code == 200
    assert captured["media_type"] == "movie"
    assert captured["radarr_movie_id"] == 42


def test_prepare_upload_commit_identifiers_default_to_none(monkeypatch, client_with_token):
    captured = {}
    monkeypatch.setattr(
        "nfogen.commit_job_runner.start",
        lambda *a, **k: captured.update(k) or "job-1",
    )
    resp = client_with_token.post(
        "/gapscan/prepare-upload/commit", json={"release_name": "R", "files": []},
    )
    assert resp.status_code == 200
    assert captured["radarr_movie_id"] is None
    assert captured["sonarr_series_id"] is None
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_api.py -v -k prepare_upload_commit_relays`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

```python
class PrepareUploadCommitRequest(BaseModel):
    release_name: str
    files: list[PrepareUploadFile]
    profile: str = "c411"
    media_type: str = "movie"
    radarr_movie_id: Optional[int] = None
    sonarr_series_id: Optional[int] = None
    season_number: Optional[int] = None


@app.post("/gapscan/prepare-upload/commit", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_commit(req: PrepareUploadCommitRequest) -> dict[str, str]:
    """... (docstring existant, ajouter :) ...

    `media_type`/`radarr_movie_id`/`sonarr_series_id`/`season_number`
    (AUTOMATION.md, sous-projet 8, tous optionnels) : identifient le titre
    pour l'historique "deja traite" -- voir commit_job_runner.start()."""
    _require_gapscan_available()
    files = [
        upload_prep.ProposedFile(source_path=f.source_path, staged_name=f.staged_name) for f in req.files
    ]
    job_id = _run_upload_prep(
        commit_job_runner.start, req.release_name, files, profile=req.profile,
        media_type=req.media_type, radarr_movie_id=req.radarr_movie_id,
        sonarr_series_id=req.sonarr_series_id, season_number=req.season_number,
    )
    return {"job_id": job_id}
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_api.py -v -k prepare_upload_commit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: POST /gapscan/prepare-upload/commit transmet les identifiants au job"
```

---

## Task 12: Backend terminé — exécuter la suite complète + push + CI

- [ ] **Step 1: Lancer toute la suite backend**

Run: `pytest -q`
Expected: PASS (0 échec).

- [ ] **Step 2: Push et poller GitHub Actions jusqu'à un run terminé sur ce commit**

```bash
git push origin main
```

Poller `https://api.github.com/repos/ICCUser/nfogen/actions/runs?branch=main&per_page=5` (curl, sans jeton) jusqu'à ce que le run dont `head_sha` correspond au dernier commit poussé ait un `conclusion` non nul. Si `conclusion != "success"`, s'arrêter et corriger avant de continuer — discipline établie cette session après un CI-break passé inaperçu.

---

## Task 13: Frontend `types.ts`/`client.ts` — `LibraryItem`, `libraryResults`, `gapscanRun`/`prepareUploadCommit` étendus

**Files:**
- Modify: `frontend/src/api/types.ts` (après `GapscanConfigWrite`, ligne ~212)
- Modify: `frontend/src/api/client.ts:314-325,391-400`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `LibraryItem`, `LibraryResultsPage` (types) ; `libraryResults(opts)`, `gapscanRun(incremental, only, profile, selection?)`, `prepareUploadCommit(releaseName, files, profile, identifiers?)`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `frontend/src/api/client.test.ts` (réutiliser le patron `mockFetch`/`vi.fn()` déjà en place dans ce fichier pour les tests `gapscanRun`/`prepareUploadCommit` existants, lignes ~414-470 et ~224-270) :

```ts
describe("libraryResults", () => {
  it("appelle GET /gapscan/library avec les filtres fournis", async () => {
    mockJsonResponse({ items: [], total: 0 });
    await libraryResults({ q: "matrix", mediaType: "movie", genre: "Action", processed: false, page: 2 });
    const url = lastFetchUrl();
    expect(url).toContain("/gapscan/library?");
    expect(url).toContain("q=matrix");
    expect(url).toContain("media_type=movie");
    expect(url).toContain("genre=Action");
    expect(url).toContain("processed=false");
    expect(url).toContain("page=2");
  });
});

describe("gapscanRun avec selection", () => {
  it("envoie un corps JSON avec selection quand fournie", async () => {
    mockJsonResponse({ status: "started" });
    await gapscanRun(false, undefined, "c411", ["[\"movie\",\"tt001\",2020]"]);
    const body = JSON.parse(lastFetchBody());
    expect(body.selection).toEqual(["[\"movie\",\"tt001\",2020]"]);
  });

  it("n'envoie aucun corps quand selection est absente (non-regression)", async () => {
    mockJsonResponse({ status: "started" });
    await gapscanRun(false, undefined, "c411");
    expect(lastFetchBody()).toBeUndefined();
  });
});

describe("prepareUploadCommit avec identifiants", () => {
  it("inclut les identifiants dans le corps quand fournis", async () => {
    mockJsonResponse({ job_id: "job-1" });
    await prepareUploadCommit("R", [], "c411", {
      mediaType: "series", radarrMovieId: undefined, sonarrSeriesId: 7, seasonNumber: 2,
    });
    const body = JSON.parse(lastFetchBody());
    expect(body.media_type).toBe("series");
    expect(body.sonarr_series_id).toBe(7);
    expect(body.season_number).toBe(2);
  });
});
```

Adapter `mockJsonResponse`/`lastFetchUrl`/`lastFetchBody` aux helpers réels déjà présents dans `client.test.ts` (lire le haut du fichier avant d'écrire — probablement un mock de `global.fetch` avec inspection de `fetch.mock.calls`).

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL (`libraryResults` n'existe pas, `gapscanRun`/`prepareUploadCommit` n'acceptent pas ces paramètres).

- [ ] **Step 3: Implémenter**

Dans `frontend/src/api/types.ts`, ajouter après `GapscanConfigWrite` (ligne 212) :

```ts
// --------------------------------------------------------------------------- //
// Bibliotheque locale (AUTOMATION.md, sous-projet 8) : inventaire brut
// Radarr/Sonarr, zero appel tracker. Type miroir de nfogen/gapscan_library.py:LibraryItem.
// --------------------------------------------------------------------------- //
export interface LibraryItem {
  media_type: "movie" | "series";
  title: string;
  year: number | null;
  season_number: number | null;
  imdb_id: string | null;
  tvdb_id: number | null;
  tmdb_id: string | null;
  genres: string[];
  added_at: number | null;
  local_quality: ReleaseQuality;
  radarr_movie_id: number | null;
  sonarr_series_id: number | null;
  already_processed: boolean;
  last_processed_at: number | null;
  /** Cle opaque (voir gapscan.movie_key/series_key) -- a renvoyer telle
   * quelle dans `gapscanRun({ selection })` pour cibler cet item. */
  key: string;
}

export interface LibraryResultsPage {
  items: LibraryItem[];
  total: number;
}
```

Dans `frontend/src/api/client.ts`, ajouter après `gapscanExportCsv` (avant la section "Preparation d'upload") :

```ts
/** GET /gapscan/library : inventaire local Radarr/Sonarr, ZERO appel
 * tracker (AUTOMATION.md, sous-projet 8) -- rechargement quasi instantane,
 * contrairement a gapscanRun(). */
export function libraryResults(
  opts: {
    q?: string;
    mediaType?: "movie" | "series";
    genre?: string;
    addedSinceDays?: number;
    processed?: boolean;
    page?: number;
    pageSize?: number;
  } = {},
): Promise<LibraryResultsPage> {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  if (opts.addedSinceDays !== undefined) params.set("added_since_days", String(opts.addedSinceDays));
  if (opts.processed !== undefined) params.set("processed", String(opts.processed));
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  return request<LibraryResultsPage>(`/gapscan/library?${params.toString()}`);
}
```

Modifier `gapscanRun` (lignes 314-325) :

```ts
/** `incremental` : reprend les titres deja couverts et inchanges du
 * dernier scan sans les reinterroger sur C411 (voir GAPSCAN.md, section
 * "Persistance des resultats + scan incremental"). `only` : ne scanne que
 * les films ou que les series, pour repartir la charge sur plusieurs
 * sessions (limite C411 confirmee : 15 requetes/min). `profile` : quel
 * tracker interroger (identifiants namespaces, voir AUTOMATION.md,
 * sous-projet 4b). `selection` (AUTOMATION.md, sous-projet 8, optionnel) :
 * cles opaques (voir LibraryItem.key) -- restreint le scan a ces items
 * precis, a priorite sur `only` cote serveur. */
export function gapscanRun(
  incremental = false,
  only?: "movies" | "series",
  profile = "c411",
  selection?: string[],
): Promise<{ status: string }> {
  const params = new URLSearchParams();
  if (incremental) params.set("incremental", "true");
  if (only) params.set("only", only);
  if (profile !== "c411") params.set("profile", profile);
  const qs = params.toString();
  return request(`/gapscan/run${qs ? `?${qs}` : ""}`, {
    method: "POST",
    ...(selection ? { body: JSON.stringify({ selection }) } : {}),
  });
}
```

Modifier `prepareUploadCommit` (lignes 391-400) :

```ts
/** Demarre la mise en scene + generation de .torrent EN TACHE DE FOND
 * (AUTOMATION.md, sous-projet 4c) -- renvoie un job_id immediatement,
 * suivi via commitJobStatus(). `identifiers` (AUTOMATION.md, sous-projet 8,
 * optionnel) : memes champs que sendToTracker() -- permet a nfogen
 * d'enregistrer ce Confirmer dans l'historique "deja traite". */
export function prepareUploadCommit(
  releaseName: string,
  files: UploadPrepFile[],
  profile = "c411",
  identifiers?: {
    mediaType?: "movie" | "series";
    radarrMovieId?: number;
    sonarrSeriesId?: number;
    seasonNumber?: number;
  },
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>("/gapscan/prepare-upload/commit", {
    method: "POST",
    body: JSON.stringify({
      release_name: releaseName,
      files,
      profile,
      media_type: identifiers?.mediaType ?? "movie",
      radarr_movie_id: identifiers?.radarrMovieId,
      sonarr_series_id: identifiers?.sonarrSeriesId,
      season_number: identifiers?.seasonNumber,
    }),
  });
}
```

Ajouter `LibraryItem`, `LibraryResultsPage` à l'import de types en haut de `client.ts` si ce fichier importe déjà ses types depuis `./types` (vérifier le style d'import existant — probablement `import type { ... } from "./types";`).

- [ ] **Step 4: Lancer les tests**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Vérifier la non-régression des tests existants qui asserted l'ancienne forme d'appel**

Run: `cd frontend && npx vitest run src/api/client.test.ts src/pages/GapScanPage.test.tsx src/components/UploadPrepPanel.test.tsx`
Expected: les assertions `expect(prepareUploadCommit).toHaveBeenCalledWith("...", files, "c411")` (sans 4ème argument) échouent encore à ce stade — normal, corrigées dans les Tasks 14-15. Les assertions `gapscanRun(false, undefined, "c411")` (3 arguments) restent VALIDES (le 4ème paramètre `selection` est optionnel, un appel à 3 arguments reste un appel JS valide) : `GapScanPage.test.tsx` ne doit PAS régresser ici.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: client API pour la bibliotheque locale (libraryResults) + selection ciblee"
```

---

## Task 14: Frontend `UploadPrepPanel.tsx` — transmettre les identifiants à `prepareUploadCommit`

**Files:**
- Modify: `frontend/src/components/UploadPrepPanel.tsx:128-144`
- Test: `frontend/src/components/UploadPrepPanel.test.tsx:136-140`

**Interfaces:**
- Consumes: `prepareUploadCommit(releaseName, files, profile, identifiers?)` (Task 13).

- [ ] **Step 1: Mettre à jour l'assertion de test existante**

Dans `frontend/src/components/UploadPrepPanel.test.tsx`, remplacer (lignes 136-140) :

```ts
  expect(prepareUploadCommit).toHaveBeenCalledWith(
    "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    ONE_GROUP[0].files,
    "c411",
  );
```

par :

```ts
  expect(prepareUploadCommit).toHaveBeenCalledWith(
    "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    ONE_GROUP[0].files,
    "c411",
    { mediaType: "movie", radarrMovieId: undefined, sonarrSeriesId: undefined, seasonNumber: undefined },
  );
```

(les valeurs `undefined` reflètent les props par défaut `null` passées par `renderPanel()`, converties via `?? undefined` — voir Step 3, même patron que `handleSend`/`sendToTracker` existant, ligne 169-174 de ce fichier).

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx -t "demarre une tache"`
Expected: FAIL (l'implémentation n'envoie pas encore le 4ème argument).

- [ ] **Step 3: Implémenter**

Dans `frontend/src/components/UploadPrepPanel.tsx`, modifier `handleConfirm` (ligne 128-144) :

```ts
  async function handleConfirm(index: number, group: UploadGroupProposal) {
    if (!group.release_name) return;
    setCommitErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const { job_id } = await prepareUploadCommit(group.release_name, group.files, profile, {
        mediaType,
        radarrMovieId: radarrMovieId ?? undefined,
        sonarrSeriesId: sonarrSeriesId ?? undefined,
        seasonNumber: seasonNumber ?? undefined,
      });
      // L'intervalle est enregistre AVANT le premier appel : si ce premier
      // appel atteint deja un etat terminal (job termine tres vite), son
      // propre stopPolling() doit pouvoir le retrouver et l'annuler.
      pollRefs.current[index] = window.setInterval(() => pollCommitJob(index, job_id), 1500);
      await pollCommitJob(index, job_id);
    } catch (e) {
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Confirmation impossible.",
      }));
    }
  }
```

- [ ] **Step 4: Lancer tous les tests de ce composant**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: PASS (tous les tests, y compris ceux non liés à `handleConfirm`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UploadPrepPanel.tsx frontend/src/components/UploadPrepPanel.test.tsx
git commit -m "feat: UploadPrepPanel transmet les identifiants a prepareUploadCommit"
```

---

## Task 15: Frontend `App.tsx` — route et navigation `/library`

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Écrire le test**

Ajouter à `frontend/src/App.test.tsx` (réutiliser le patron déjà en place pour vérifier la présence du lien "Scan ...") :

```tsx
it("affiche un lien de navigation vers la bibliotheque", () => {
  renderApp(); // reutiliser le helper de rendu deja present dans ce fichier
  expect(screen.getByRole("link", { name: /Bibliothèque/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "Bibliotheque"`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

Dans `frontend/src/App.tsx`, ajouter l'import :

```tsx
import LibraryPage from "./pages/LibraryPage";
```

Ajouter le lien de navigation (après `/gapscan`, avant `/settings`) :

```tsx
            <NavLink to="/gapscan" className={navClass}>
              Scan {displayName}
            </NavLink>
            <NavLink to="/library" className={navClass}>
              Bibliothèque
            </NavLink>
            <NavLink to="/settings" className={navClass}>
              Réglages
            </NavLink>
```

Ajouter la route :

```tsx
            <Route path="/gapscan" element={<GapScanPage />} />
            <Route path="/library" element={<LibraryPage />} />
```

- [ ] **Step 4: Lancer les tests**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL encore à ce stade (`LibraryPage` n'existe pas — `import` cassé) : normal, `LibraryPage.tsx` est créé à la Task 16. **Ne pas commit avant la Task 16.**

---

## Task 16: Frontend `LibraryPage.tsx` (nouvelle page)

**Files:**
- Create: `frontend/src/pages/LibraryPage.tsx`
- Test: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `libraryResults`, `gapscanRun` (Task 13), `LibraryItem` (Task 13).

- [ ] **Step 1: Écrire les tests**

Créer `frontend/src/pages/LibraryPage.test.tsx` (calquer sur le patron de mock/rendu de `GapScanPage.test.tsx`) :

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  libraryResults: vi.fn(),
  gapscanRun: vi.fn(),
}));

import { gapscanRun, libraryResults } from "../api/client";
import LibraryPage from "./LibraryPage";
import { ProfileProvider } from "../ProfileContext";
import type { LibraryItem } from "../api/types";

const ITEM: LibraryItem = {
  media_type: "movie", title: "Movie", year: 2020, season_number: null,
  imdb_id: "tt001", tvdb_id: null, tmdb_id: "1", genres: ["Action"], added_at: null,
  local_quality: { raw: "", resolution: 1080, source: null, codec: null, languages: [], multi: false, pure: false },
  radarr_movie_id: 1, sonarr_series_id: null, already_processed: false, last_processed_at: null,
  key: '["movie","tt001",2020]',
};

function renderPage() {
  return render(
    <ProfileProvider>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </ProfileProvider>,
  );
}

beforeEach(() => {
  vi.mocked(libraryResults).mockReset();
  vi.mocked(gapscanRun).mockReset();
});

describe("LibraryPage", () => {
  it("charge et affiche la bibliotheque au montage", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [ITEM], total: 1 });
    renderPage();
    await waitFor(() => expect(screen.getByText("Movie")).toBeInTheDocument());
    expect(libraryResults).toHaveBeenCalled();
  });

  it("selectionner une ligne puis lancer le scan appelle gapscanRun avec la selection", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [ITEM], total: 1 });
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Movie")).toBeInTheDocument());
    await user.click(screen.getByRole("checkbox", { name: /Movie/i }));
    await user.click(screen.getByRole("button", { name: /Vérifier sur le tracker/i }));

    await waitFor(() => {
      expect(gapscanRun).toHaveBeenCalledWith(false, undefined, "c411", [ITEM.key]);
    });
  });

  it("le bouton de scan cible est desactive sans selection", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [ITEM], total: 1 });
    renderPage();
    await waitFor(() => expect(screen.getByText("Movie")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Vérifier sur le tracker/i })).toBeDisabled();
  });

  it("le filtre texte relance libraryResults avec q", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/Recherche/i), "matrix");
    await waitFor(() => {
      const lastCall = vi.mocked(libraryResults).mock.calls.at(-1)?.[0];
      expect(lastCall?.q).toBe("matrix");
    });
  });
});
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx`
Expected: FAIL (`Cannot find module './LibraryPage'`).

- [ ] **Step 3: Implémenter**

Créer `frontend/src/pages/LibraryPage.tsx` :

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { gapscanRun, libraryResults } from "../api/client";
import { ApiError } from "../api/types";
import type { LibraryItem } from "../api/types";
import { useProfile } from "../ProfileContext";

/** Page "Bibliothèque" (AUTOMATION.md, sous-projet 8) : inventaire brut
 * Radarr/Sonarr, ZERO appel tracker -- rechargement quasi instantané,
 * séparée de la page "Scan C411" (qui reste le scan bulk classique).
 * Permet de sélectionner un sous-ensemble (filtre ou case à cocher) et de
 * ne vérifier QUE lui sur le tracker, plutôt que toute la bibliothèque à
 * chaque fois (retour utilisateur, 2026-09-06). */
export default function LibraryPage() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [mediaType, setMediaType] = useState<"" | "movie" | "series">("");
  const [genre, setGenre] = useState("");
  const [addedSinceDays, setAddedSinceDays] = useState("");
  const [processed, setProcessed] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, mediaType, genre, addedSinceDays, processed, page, profile]);

  async function load() {
    try {
      const res = await libraryResults({
        q: q || undefined,
        mediaType: mediaType || undefined,
        genre: genre || undefined,
        addedSinceDays: addedSinceDays ? Number(addedSinceDays) : undefined,
        processed: processed === "" ? undefined : processed === "true",
        page,
        pageSize: PAGE_SIZE,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setItems(null);
      setTotal(0);
      setError(e instanceof ApiError ? e.message : "Bibliothèque indisponible.");
    }
  }

  function toggleOne(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectAllFiltered() {
    if (!items) return;
    setSelected(new Set(items.map((i) => i.key)));
  }

  function clearSelection() {
    setSelected(new Set());
  }

  async function handleVerify() {
    if (selected.size === 0) return;
    setStarting(true);
    setError(null);
    try {
      await gapscanRun(false, undefined, profile, Array.from(selected));
      navigate("/gapscan");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de lancer le scan.");
    } finally {
      setStarting(false);
    }
  }

  function resetPageAnd<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(1);
    };
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Bibliothèque</h1>
          <p className="text-sm text-ink-dim">
            Inventaire Sonarr/Radarr local — aucun appel au tracker. Sélectionne les titres à vérifier
            puis lance un scan ciblé, plutôt que toute la bibliothèque.
          </p>
        </div>
        <button
          type="button"
          onClick={handleVerify}
          disabled={selected.size === 0 || starting}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
        >
          {starting ? "Démarrage…" : `Vérifier sur le tracker (${selected.size} sélectionnés)`}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">{error}</div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm font-medium text-ink-dim">
          Recherche
          <input
            aria-label="Recherche"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={q}
            onChange={(e) => resetPageAnd(setQ)(e.target.value)}
            placeholder="Titre…"
          />
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Type
          <select
            aria-label="Type"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={mediaType}
            onChange={(e) => resetPageAnd(setMediaType)(e.target.value as "" | "movie" | "series")}
          >
            <option value="">Tous les types</option>
            <option value="movie">Films</option>
            <option value="series">Séries</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Genre
          <input
            aria-label="Genre"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={genre}
            onChange={(e) => resetPageAnd(setGenre)(e.target.value)}
            placeholder="Action, Drama…"
          />
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Ajouté depuis (jours)
          <input
            aria-label="Ajouté depuis (jours)"
            type="number"
            className="mt-1 w-full max-w-[8rem] rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={addedSinceDays}
            onChange={(e) => resetPageAnd(setAddedSinceDays)(e.target.value)}
          />
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Déjà traité
          <select
            aria-label="Déjà traité"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={processed}
            onChange={(e) => resetPageAnd(setProcessed)(e.target.value as "" | "true" | "false")}
          >
            <option value="">Peu importe</option>
            <option value="true">Déjà traité</option>
            <option value="false">Jamais traité</option>
          </select>
        </label>
        <button
          type="button"
          onClick={selectAllFiltered}
          disabled={!items || items.length === 0}
          className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          Tout sélectionner (filtré)
        </button>
        <button
          type="button"
          onClick={clearSelection}
          disabled={selected.size === 0}
          className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          Désélectionner
        </button>
      </div>

      {items === null && !error && <p className="text-sm text-ink-faint">Chargement…</p>}
      {items !== null && items.length === 0 && <p className="text-sm text-ink-faint">Aucun résultat.</p>}

      {items !== null && items.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-line bg-surface text-sm">
          <thead className="bg-surface-2 text-left text-ink-dim">
            <tr>
              <th className="px-4 py-2" />
              <th className="px-4 py-2">Titre</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Genres</th>
              <th className="px-4 py-2">Statut</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.key} className="border-t border-line">
                <td className="px-4 py-2">
                  <input
                    type="checkbox"
                    aria-label={item.title}
                    checked={selected.has(item.key)}
                    onChange={() => toggleOne(item.key)}
                    className="h-4 w-4 rounded border-line-strong"
                  />
                </td>
                <td className="px-4 py-2 font-mono font-medium text-ink">
                  {item.title} {item.year ? `(${item.year})` : ""}
                </td>
                <td className="px-4 py-2 text-ink-dim">
                  {item.media_type === "movie" ? "Film" : `Série S${String(item.season_number).padStart(2, "0")}`}
                </td>
                <td className="px-4 py-2 text-ink-dim">{item.genres.join(", ") || "—"}</td>
                <td className="px-4 py-2 text-ink-dim">
                  {item.already_processed ? "Déjà traité" : "Jamais traité"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

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
    </div>
  );
}
```

- [ ] **Step 4: Lancer les tests de la page**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Relancer le test de Task 15 (App.tsx), maintenant que `LibraryPage` existe**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS.

- [ ] **Step 6: Lancer toute la suite frontend**

Run: `cd frontend && npx vitest run`
Expected: PASS (0 échec, y compris les fichiers touchés aux Tasks 13-15).

- [ ] **Step 7: Commit (App.tsx + LibraryPage.tsx ensemble — App.tsx seul ne compilait pas sans cette page)**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat: page Bibliotheque (inventaire local, selection, scan cible)"
```

---

## Task 17: Push, CI, documentation

- [ ] **Step 1: Push et poller GitHub Actions jusqu'à un run terminé**

```bash
git push origin main
```

Poller `https://api.github.com/repos/ICCUser/nfogen/actions/runs?branch=main&per_page=5` jusqu'à `conclusion` non nul pour le `head_sha` de ce commit. Si échec, corriger avant de continuer.

- [ ] **Step 2: Mettre à jour `AUTOMATION.md`**

Ajouter une ligne à la table de décomposition (près de la ligne 56, section "État") pour le sous-projet 8, avec l'état "Livré", puis une nouvelle section après "Sous-projet 5" (après la ligne ~656, avant que le fichier ne continue) :

```markdown
## Sous-projet 8 : Bibliothèque locale et scan ciblé (conception et livraison 2026-09-06)

Retour utilisateur (2026-09-06) : `POST /gapscan/run` interrogeait le
tracker pour toute la bibliothèque à chaque scan (le mode incrémental
réutilise les `COVERED` inchangés, mais scanne quand même tout le reste)
— "pour eviter de scan comme un porc toute la bibliotech".

**Nouvelle vue "Bibliothèque"** (`/library`), séparée de "Scan C411" :
inventaire Sonarr/Radarr brut via `GET /gapscan/library`
(`nfogen/gapscan_library.py`), **zéro appel tracker** — rechargement quasi
instantané. Filtres (recherche texte, type, genre **Radarr/Sonarr** — pas
la catégorie C411, indisponible tant que rien n'est vérifié —, "ajouté
depuis N jours", "déjà traité"), sélection multiple, bouton "Vérifier sur
le tracker (N sélectionnés)" qui lance un scan **restreint** à cette
sélection (`POST /gapscan/run` gagne un champ `selection`, des clés
stables `movie_key`/`series_key` — extraites de l'ancien `_result_key`
interne de `gapscan.py`, désormais publiques et réutilisées par les deux
modules).

**Historique persistant "déjà traité"** (`nfogen/upload_history_store.py`,
même patron que `gapscan_results.json`) : un titre est marqué traité dès
qu'un "Confirmer" ou un "Envoyer à C411" réussit
(`commit_job_runner.py`/`upload_prep.py:send_to_tracker`), via une clé
`radarr_movie_id`/`sonarr_series_id` (distincte de `movie_key`/
`series_key`, qui ont besoin d'imdb/tmdb/titre/année — non disponibles à
ces deux points d'appel sans plomberie supplémentaire). Jamais basé sur
le contenu du dossier staging (peut être nettoyé indépendamment).

Le scan bulk existant ("Lancer un scan", page "Scan C411") reste
inchangé et coexiste avec le scan ciblé.

Voir [docs/superpowers/specs/2026-09-06-library-targeted-scan-design.md](docs/superpowers/specs/2026-09-06-library-targeted-scan-design.md)
et [docs/superpowers/plans/2026-09-06-library-targeted-scan.md](docs/superpowers/plans/2026-09-06-library-targeted-scan.md).
```

- [ ] **Step 3: Mettre à jour `CHANGELOG.md`**

Ajouter sous la section `[Non publié]` (ou créer/compléter la section `### Ajouté` si elle existe déjà en tête du fichier — vérifier le format exact utilisé pour les entrées précédentes de cette session) :

```markdown
### Ajouté

- **Bibliothèque locale et scan ciblé** (sous-projet 8) : nouvelle vue
  `/library` listant l'inventaire Sonarr/Radarr sans appel tracker,
  filtrable (texte, type, genre, date d'ajout, déjà traité) et
  sélectionnable pour un scan C411 restreint (`POST /gapscan/run` gagne
  `selection`) — évite de rescanner toute la bibliothèque pour vérifier un
  seul titre. Historique persistant des titres déjà confirmés/envoyés
  (`upload_history_store.py`).
```

- [ ] **Step 4: Commit et push**

```bash
git add AUTOMATION.md CHANGELOG.md
git commit -m "docs: sous-projet 8 livre - AUTOMATION.md et CHANGELOG.md a jour"
git push origin main
```

Poller GitHub Actions une dernière fois jusqu'à `conclusion` non nul sur ce commit.

---

## Self-Review

**Couverture de la spec** : problème/objectifs (page séparée, zéro appel tracker, filtres, sélection, historique persistant, genres Radarr/Sonarr) → Tasks 6, 9, 16. Clé stable partagée → Task 1. `genres`/`added_at` → Tasks 3-4. `upload_history_store` → Task 5. Threading des identifiants (`commit_job_runner`, `send_to_tracker`, `PrepareUploadCommitRequest`) → Tasks 7, 8, 11. `selection` de bout en bout (`run_gapscan` → `gapscan_runner` → API → frontend) → Tasks 1, 2, 10, 13, 16. Gestion des erreurs (400 sans config, clé invalide vs clé absente ignorée, écriture historique jamais bloquante) → Tasks 5, 9, 10. Tous les points de la section "Tests" de la spec ont une tâche correspondante.

**Ambiguïté résolue explicitement** (Task 5) : la spec ne précise pas la forme exacte de la clé "déjà traité" au-delà de "calculée depuis les champs identifiants" — ce plan choisit `processed_key(media_type, radarr_movie_id, sonarr_series_id, season_number)`, distincte de `movie_key`/`series_key`, car ces derniers ont besoin d'imdb_id/tmdb_id/titre/année, non disponibles à `commit_job_runner.start()`/`send_to_tracker()` sans plomberie supplémentaire que la spec ne demande pas.

**Écart volontaire avec l'énoncé initial (avant spec)** : `gapscanRun()` gagne un 4ème paramètre positionnel optionnel `selection?: string[]` (Task 13) plutôt qu'un refactor en objet d'options — la spec dit seulement "gagne un paramètre", et un ajout positionnel optionnel préserve tous les appels existants (`GapScanPage.tsx`, ses tests) sans les toucher, réduisant le risque de régression pour un gain nul.

**Cohérence des types** : `LibraryItem` (Python, Task 6) et `LibraryItem` (TypeScript, Task 13) ont exactement les mêmes champs/noms (`dataclasses.asdict` ⇄ interface miroir, même convention que `GapResult`). `processed_key`/`record`/`is_processed`/`last_processed_at`/`key_str` (Task 5) sont utilisés avec les mêmes signatures dans toutes les tâches consommatrices (7, 8, 6).

**Aucun placeholder** : chaque étape de code contient du code réel, chaque test contient des assertions concrètes (les rares `...` dans les Tasks 8/9 pointent explicitement vers un patron de mock existant à reproduire, avec le nom du mécanisme attendu — jamais un TODO sans contenu).
