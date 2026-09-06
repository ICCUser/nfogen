# Bibliothèque locale et scan ciblé (sous-projet 8)

**Statut** : approuvé par l'utilisateur (2026-09-06), prêt pour le plan d'implémentation.

## Problème

`POST /gapscan/run` interroge aujourd'hui le tracker (rate-limité, 15
req/min sur C411) pour **chaque** film/série de la bibliothèque
Radarr/Sonarr à chaque scan — le mode incrémental existant (`incremental`)
réutilise les titres déjà `COVERED` et inchangés, mais scanne quand même
tout le reste. Retour utilisateur (2026-09-06) : "pour eviter de scan
comme un porc toute la bibliotech", il faut pouvoir choisir **quoi**
vérifier sur le tracker, pas seulement **quand** (incrémental).

Trois usages explicitement demandés, tous à couvrir :
1. Je viens d'ajouter un titre à Radarr/Sonarr → vérifier juste lui.
2. Je veux re-vérifier un titre/une franchise précise → chercher par nom.
3. Je veux parcourir toute ma bibliothèque et cocher au cas par cas.

Plus deux besoins connexes :
- Recharger la bibliothèque locale (Radarr/Sonarr) **sans** déclencher de
  scan C411 — c'est une API externe, l'action est longue.
- Savoir si un titre a déjà été traité par nfogen (Confirmer et/ou Envoyer
  à C411), pour éviter de le re-sélectionner par erreur.

## Objectifs (validés avec l'utilisateur)

- Nouvelle vue **"Bibliothèque"**, séparée de la page "Scan C411"
  actuelle : inventaire Radarr/Sonarr brut, **zéro appel tracker** —
  rechargement quasi instantané même sur une grosse bibliothèque.
- Filtres : recherche texte (titre), Type (Films/Séries), Genre (voir
  ci-dessous), "ajouté depuis N jours", "Déjà traité".
- Sélection : case à cocher par ligne + "sélectionner tout le filtré".
- Bouton "Vérifier sur le tracker (N sélectionnés)" → scan **restreint**
  à la sélection, sans toucher aux résultats déjà connus des autres
  titres.
- "Lancer un scan" (bulk, page "Scan C411" actuelle) **reste inchangé** —
  toujours possible de tout vérifier d'un coup.
- **Genre en bibliothèque** : classé depuis les genres **Radarr/Sonarr**
  eux-mêmes (`movie.genres`/`series.genres`, déjà exposés par l'API — le
  même champ que `RadarrMovieDetails.genres`/`SonarrSeriesDetails.genres`
  du sous-projet 5), **pas** la catégorie C411 (indisponible tant que
  rien n'est vérifié sur le tracker). Un genre différent de celui de la
  page "Scan C411" (qui reste basé sur la catégorie du match C411 trouvé)
  — deux classifications distinctes, chacune pertinente pour sa vue.
- **"Déjà traité"** : historique **persistant** (nouveau fichier JSON,
  même esprit que `gapscan_results.json`) alimenté à chaque Confirmer et
  Envoyer à C411 réussi — fiable même si le dossier staging est nettoyé
  plus tard (notamment une fois qBittorrent branché, sous-projet 6).
  **Jamais** basé sur le contenu actuel du dossier staging.

## Non-objectifs (hors scope, YAGNI)

- Modifier la page "Scan C411" existante (table de résultats déjà
  vérifiés, filtre statut/type/genre C411) — reste telle quelle,
  simplement complétée par la nouvelle vue.
- Retirer/fusionner "Lancer un scan" (bulk) — les deux mécanismes
  coexistent.
- Purger/faire expirer l'historique "déjà traité" — grandit indéfiniment
  pour l'instant (volume attendu faible, un enregistrement par
  Confirmer/Envoi, pas par scan).
- Suivre le statut réel de modération sur C411 (le brouillon peut être
  finalisé, refusé, ou jamais soumis — nfogen ne le sait pas) : "déjà
  traité" signifie seulement "nfogen a déjà produit un `.torrent`/un
  brouillon pour ce titre", pas "accepté par C411".

## Architecture

### Clé stable partagée : `nfogen/gapscan.py`

`_result_key()` existe déjà pour le mode incrémental (retrouver le
résultat précédent d'un titre entre deux scans). Elle est **extraite** en
deux fonctions pures, publiques, réutilisées par le nouveau module
bibliothèque :

```python
def movie_key(imdb_id: Optional[str], tmdb_id: Optional[str], title: str, year: Optional[int]) -> tuple:
    return ("movie", imdb_id or tmdb_id or title, year)


def series_key(tvdb_id: Optional[int], imdb_id: Optional[str], title: str, season_number: Optional[int]) -> tuple:
    return ("series", tvdb_id or imdb_id or title, season_number)


def _result_key(r: GapResult) -> tuple:
    """Identifiant stable d'un titre (ou saison) entre deux scans -- voir
    movie_key/series_key (extraites pour etre reutilisees par
    gapscan_library.py, meme calcul de cle des deux cotes)."""
    if r.media_type == "movie":
        return movie_key(r.imdb_id, r.tmdb_id, r.title, r.year)
    return series_key(r.tvdb_id, r.imdb_id, r.title, r.season_number)
```

Cette garantie (même calcul de clé partout) est ce qui permet à une
sélection faite depuis `/gapscan/library` de retrouver exactement les
bons items dans `run_gapscan()`.

**Transport sur le fil** : chaque clé est sérialisée en JSON
(`json.dumps(list(key))`, ex. `'["movie", "tt0133093", 1999]'`) — le
frontend la traite comme une chaîne **opaque** (jamais interprétée,
simplement renvoyée telle quelle lors de la sélection). Le serveur la
redécode (`json.loads`) pour comparer aux clés calculées en interne.

### `nfogen/radarr_client.py`/`sonarr_client.py` — deux champs de plus

`RadarrMovieFile`/`SonarrSeasonFile` gagnent :
- `genres: list[str]` — extrait de `movie.get("genres")`/`series.get("genres")`,
  **déjà présent dans la réponse brute** de `list_movies()`/`list_series()`
  (même champ que celui utilisé par `get_movie_details`/`get_series_details`
  du sous-projet 5, mais ici sans appel supplémentaire : la liste bulk
  contient déjà ces objets complets).
- `added_at: Optional[float]` (epoch secondes) — Radarr : `movie.get("added")`
  (ISO 8601, converti). Sonarr : **la plus récente `dateAdded` des fichiers
  épisode de la saison** (pas la date d'ajout de la série entière, qui ne
  distinguerait pas les saisons) — cohérent avec l'agrégation par saison
  déjà faite par `list_season_files()`.

**⚠️ Point à vérifier pendant l'implémentation** : les noms de champs
`added`/`dateAdded` sont ceux documentés par l'API Radarr/Sonarr v3, mais
n'ont jamais été lus par ce projet jusqu'ici — à confirmer contre une
vraie réponse avant de considérer cette tâche terminée (comme pour
`c411_upload_client.py` en son temps).

### Nouveau module : `nfogen/gapscan_library.py`

```python
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

def list_library(
    radarr: Optional[RadarrClient], sonarr: Optional[SonarrClient],
) -> list[LibraryItem]:
    """Inventaire local SANS AUCUN appel tracker -- reutilise
    list_movie_files()/list_season_files() (deja utilises par
    run_gapscan) et upload_history_store.is_processed() pour le statut
    "deja traite". Rapide : uniquement des appels Radarr/Sonarr, jamais
    C411."""
```

Cette fonction s'exécute **synchrone** (pas de tâche de fond) : contrairement
à `run_gapscan`, elle ne fait que des appels HTTP locaux/rapides
(Radarr/Sonarr, pas de rate-limit connu côté nfogen), cohérent avec le
besoin exprimé ("recharger sans scan long").

### `nfogen/upload_history_store.py` (nouveau)

Même patron de persistance que `gapscan_results_store.py` (fichier JSON,
`NFOGEN_UPLOAD_HISTORY_FILE`, tolérant à un fichier absent/corrompu).

```python
def record(key: tuple, *, kind: str, release_name: str, at: Optional[float] = None) -> None:
    """Ajoute une entree a l'historique -- kind: "committed" (Confirmer
    reussi) ou "sent" (Envoyer a C411 reussi). Idempotent par cle+kind
    (une nouvelle Confirmer/Envoi sur le meme titre met a jour l'horodatage,
    n'accumule pas les doublons)."""

def is_processed(key: tuple) -> bool:
    """Vrai si au moins une entree (committed OU sent) existe pour cette cle."""

def last_processed_at(key: tuple) -> Optional[float]:
    """Horodatage le plus recent (committed ou sent) pour cette cle, ou None."""
```

**Appelants** :
- `nfogen/commit_job_runner.py:_run()` — sur `JobState.DONE`, appelle
  `upload_history_store.record(key, kind="committed", release_name=...)`.
  Le `key` est calculé depuis les champs identifiants (voir ci-dessous),
  transmis à `start()`.
- `nfogen/upload_prep.py:send_to_tracker()` — juste avant de renvoyer
  `SendResult` avec succès, même appel avec `kind="sent"`.

**Threading des identifiants** : `commit_job_runner.start()` et
`POST /gapscan/prepare-upload/commit` gagnent les **mêmes champs
optionnels** que `send_to_tracker`/`POST /gapscan/prepare-upload/send`
possède déjà (`media_type`, `radarr_movie_id`, `sonarr_series_id`,
`tmdb_id`, `tvdb_id`, `season_number`) — le frontend les a déjà sous la
main (`UploadPrepPanel.tsx` les reçoit déjà en props pour l'appel
`sendToTracker`), il suffit de les transmettre aussi à
`prepareUploadCommit`. Absents (`None`) : pas d'entrée d'historique
enregistrée pour ce Confirmer (dégrade proprement, jamais bloquant —
cohérent avec "jamais deviner").

### `nfogen/gapscan.py:run_gapscan` — parametre `selection`

```python
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
```

`selection` (déjà décodée en tuples par la couche API) : si fourni,
**restreint** les items réellement interrogés sur C411 à ceux dont la clé
(`movie_key`/`series_key`) est dans l'ensemble — exactement le même
principe que `only` ("movies"/"series"), mais au niveau titre individuel.
`selection` a priorité sur `only` si les deux sont fournis (n'a pas de
sens de les combiner). Les items **exclus** de la sélection sont
**préservés** tels quels depuis `previous_results` (jamais supprimés du
résultat global) — même garde-fou que celui déjà en place pour `only`
(incident réel du 2026-08-28, "un scan Films seulement effaçait les
séries déjà scannées").

**`nfogen/gapscan_runner.py`** (orchestration en tâche de fond,
au-dessus de `run_gapscan`) doit relayer ce même paramètre de bout en
bout : `start(..., selection: Optional[set[tuple]] = None)` le transmet
à son `_run()` interne (thread), qui le passe tel quel à `run_gapscan()`
— sans ça, l'API pourrait décoder `selection` sans jamais l'acheminer
jusqu'à la fonction qui filtre réellement les items.

### `nfogen/api.py`

- **`GET /gapscan/library`** (nouveau) — construit les clients
  Radarr/Sonarr (réutilise `_build_gapscan_clients`, sans le client C411),
  appelle `gapscan_library.list_library()`, applique les filtres serveur
  (texte, type, genre, `added_since_days`, `processed`) + pagination
  (`page`/`page_size`, même contrat que `/gapscan/results`).
- **`POST /gapscan/run`** — gagne un champ `selection: Optional[list[str]]`
  (clés JSON sérialisées) ; décodées (`json.loads` par entrée) avant
  d'appeler `gapscan_runner.start(..., selection=...)` → `run_gapscan`.
- **`PrepareUploadCommitRequest`** — gagne les mêmes champs optionnels que
  `PrepareUploadSendRequest` (`media_type`, `radarr_movie_id`,
  `sonarr_series_id`, `tmdb_id`, `tvdb_id`, `season_number`), transmis à
  `commit_job_runner.start()`.

### Frontend

**Nouvelle page `LibraryPage.tsx`** (nouvelle route, ex. `/library`, lien
de navigation à côté de "Scan C411") :
- Recherche texte, sélecteurs Type/Genre/"ajouté depuis"/"Déjà traité",
  pagination — même disposition que `GapScanPage.tsx` aujourd'hui.
- Case à cocher par ligne + case "tout sélectionner (le filtré)".
- Bouton "Vérifier sur le tracker (N sélectionnés)" → `gapscanRun({ selection: [...] })`,
  puis redirige/bascule vers "Scan C411" pour voir la progression (même
  mécanisme de polling déjà en place, `gapscanStatus()`).
- **`client.ts`/`types.ts`** : `LibraryItem`, `libraryResults(filters)`,
  `gapscanRun()` gagne un paramètre `selection?: string[]`.
- `UploadPrepPanel.tsx` : `handleConfirm` transmet désormais les mêmes
  champs identifiants à `prepareUploadCommit` qu'à `sendToTracker` (déjà
  reçus en props, voir ci-dessus) — `prepareUploadCommit()` gagne ces
  paramètres optionnels côté client.

## Gestion des erreurs

- `GET /gapscan/library` sans Sonarr ni Radarr configuré : même 400 que
  `/gapscan/run` aujourd'hui (`_build_gapscan_clients` déjà lève cette
  erreur).
- `selection` contenant une clé qui ne correspond à aucun item réel
  (bibliothèque modifiée entre le chargement et le clic) : silencieusement
  ignorée, jamais d'erreur bloquante — cohérent avec "jamais deviner,
  jamais bloquant".
- Écriture de `upload_history_store` échoue (disque plein, permissions) :
  capturée, jamais propagée — un Confirmer/Envoi réussi ne doit **jamais**
  échouer à cause d'un problème d'écriture de l'historique, purement
  informatif.

## Tests

- `gapscan.py` : `movie_key`/`series_key` extraites, `_result_key`
  toujours correcte (non-régression) ; `run_gapscan` avec `selection`
  restreint bien les items interrogés et préserve les autres.
- `radarr_client.py`/`sonarr_client.py` : `genres`/`added_at` extraits
  correctement (mock), absents → valeurs neutres (`[]`/`None`), jamais de
  plantage.
- `gapscan_library.py` : `list_library` sans aucun appel au client C411
  (vérifié via un mock qui lève si `search_movie`/`search_tv` est appelé) ;
  `already_processed`/`last_processed_at` reflètent `upload_history_store`.
- `upload_history_store.py` : `record`/`is_processed`/`last_processed_at`,
  idempotence par clé+kind, tolérance fichier absent/corrompu.
- `commit_job_runner.py`/`upload_prep.py` : `record()` appelé avec la
  bonne clé sur succès ; absent silencieusement si les identifiants ne
  sont pas fournis ; jamais d'échec de Confirmer/Envoi si l'écriture de
  l'historique échoue.
- `api.py` : `GET /gapscan/library` (filtres, pagination, 400 sans
  config) ; `POST /gapscan/run` avec `selection` (restreint bien, clé
  invalide ignorée).
- Frontend : `LibraryPage` (rendu, sélection, filtre, appel
  `gapscanRun({selection})`) ; `UploadPrepPanel` transmet les identifiants
  à `prepareUploadCommit`.

## Points à vérifier pendant l'implémentation (pas bloquants)

- Noms exacts des champs Radarr/Sonarr (`added`/`dateAdded`) — à confirmer
  contre une vraie réponse avant de considérer la tâche terminée.
- Le filtre "Genre" en bibliothèque utilise le vocabulaire Radarr/Sonarr
  (ex. "Animation", "Documentary" en anglais, tels que TMDB/TVDB les
  fournissent) — potentiellement différent des libellés "Animés"/
  "Documentaires" affichés côté page "Scan C411" (basés sur les
  catégories Torznab C411). Les deux filtres restent **indépendants**,
  assumé dans ce sous-projet ; une éventuelle unification resterait à
  discuter séparément si elle s'avère gênante à l'usage.
