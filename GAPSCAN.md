# GapScan — Comparateur bibliothèque locale ↔ catalogue C411

Nouvelle brique de `nfogen` : à partir de ta bibliothèque Sonarr/Radarr,
détecter les films/séries que tu possèdes mais dont **ta version précise**
n'est pas (ou pas encore) disponible sur C411 — candidats naturels à
uploader avec `nfogen` (génération NFO déjà existante).

> Statut (2026-08-25) : clients Sonarr/Radarr/C411, extraction/comparaison
> qualité-langue et orchestration codés et testés (236 tests, dont 25 dédiés
> à `quality.py`) — voir "Encore à fournir #2" pour ce qui manque encore
> avant un test en conditions réelles. Pas encore d'endpoints `/gapscan/*`
> ni de page frontend.

## Décisions déjà prises (2026-08-25)

| Sujet | Décision |
| --- | --- |
| Accès C411 | Via **clé API C411** existante (pas de scraping/cookies) — voir "À fournir". |
| Granularité du "gap" | Combinaison des trois : présence du titre, **qualité/source**, et **langue** (VFF/VFQ/VOSTFR...). Barème exact à définir avec les règles de qualité C411 — voir "À fournir". |
| Intégration | Nouveau module dans le repo `nfogen` existant (pas de repo séparé) : réutilise auth, config, déploiement (`scripts/install.sh`, Docker, `NFOGEN_*` env vars). |
| Interface | Page dédiée dans le frontend React existant dès la V1 (pas de CLI-only en attendant). |

## API C411 — vérifiée en direct le 2026-08-25

Bonne nouvelle : C411 expose une **API Torznab standard** (le protocole
que parlent déjà Prowlarr/Sonarr/Radarr/Jackett), pas une API maison —
confirmé par capture d'écran (section "Intégrations API" du site) et par
appels réels avec la clé fournie.

**Correction (2026-08-26)** : cette section affirmait que la clé était
cantonnée au scope "Torznab/RSS (lecture)" et ne permettait aucun
téléchargement. Confirmé faux par l'utilisateur — sa clé permet aussi de
pousser un upload (`POST /api/torrents`, même clé). GapScan n'appelle
jamais cet endpoint (lecture seule par construction, `c411_client.py` n'a
que `search_movie`/`search_tv`) donc aucun changement de code, mais la clé
elle-même est plus sensible que documenté ici à l'origine : une clé
compromise permettrait plus qu'une simple lecture du catalogue. Pousser un
upload directement depuis nfogen (utiliser cette capacité plutôt que de
simplement la documenter) est noté en piste future ci-dessous.

- **Base URL** : `https://c411.org/api`
- **Auth** : clé en query param `?apikey=...`, la même que pour
  `POST /api/torrents` (upload) -- pas un scope separe malgre le header
  `Authorization: Bearer` different vu dans la capture pour cet endpoint.
- **`t=caps`** (sans clé) → capacités + catégories. Pertinent pour
  GapScan : `2000`/`2030`/`2060`/`2070`/`2010` (Films, Anime, Documentaire,
  Collection) et `5000`/`5070`/`5080`/`5060` (Séries, Anime Série,
  Documentaire, Sport).
- **Recherche** :
  - `t=movie` (params `q`, `imdbid`, `tmdbid`)
  - `t=tvsearch` (params `q`, `season`, `ep`, `tmdbid`, `imdbid`)
  - `t=search` (`q` seul, tous types)
  - `limits max="100" default="25"` → pagination à gérer pour un scan
    complet de bibliothèque.
- **Réponse** : RSS/XML Torznab standard, un `<item>` par release :
  - `title` = le `release_name` C411 complet, au même format que la
    convention déjà encodée dans
    [`nfogen/profiles/c411/rules.json`](nfogen/profiles/c411/rules.json)
    (résolution, langue, codec parseables directement avec les mêmes
    regex que la validation d'upload — juste dans l'autre sens).
  - `torznab:attr imdbid`/`tmdbid` — présents sur la plupart des items
    mais **pas systématiquement** (ex. un pack COLLECTION peut ne pas les
    avoir alors qu'un épisode single les a) → matching par ID en
    priorité, repli sur titre+année si absent.
  - `torznab:attr downloadvolumefactor` : `0` = badge **FL**, `0.5` =
    badge **50%**, `1` = normal.
  - `torznab:attr uploadvolumefactor` : `2` = badge **2x**, `1` = normal.
  - `seeders`/`peers`/`grabs`/`size`/`infohash` également disponibles.
- Pas de doc publique trouvée (le wiki répond 403 sans session
  navigateur) — tout ce qui précède vient des appels réels + de la
  capture "Configuration rapide".

### Freeleech / priorisation (confirmé via wiki "Ratio & Seedtime")

| Badge | `downloadvolumefactor` | `uploadvolumefactor` | Effet |
| --- | --- | --- | --- |
| FL | `0` | — | Le téléchargement ne compte pas du tout |
| 50% | `0.5` | — | Moitié du téléchargement compte |
| 2x | — | `2` | Upload compte double |

Règle de priorisation GapScan : sur les items **absents localement mais
présents sur C411** (candidats de téléchargement), trier FL puis 50% en
premier (aucun/faible impact ratio). Sur les items **gaps à uploader**,
signaler si un 2x global est actif (upload rapporte double pendant cette
fenêtre) — pas d'impact par torrent puisque le 2x s'applique plutôt au
niveau compte/événement qu'à une release individuelle inexistante.
Ratio minimum pour télécharger : **0.8** (crédit initial 50 Go) — à
afficher dans l'UI si le ratio du compte s'en approche, information
disponible seulement via le site web (pas vue dans l'API Torznab) donc
hors scope automatisable pour l'instant.

## Encore à fournir par toi

1. ~~**Politique anti-doublon C411**~~ : **fourni et intégré (2026-08-25)**
   — texte complet collé en bas de ce fichier ("Régle Copié directement du
   site c411" + "Copie des règles de la page cat-video"). Réconcilié dans
   `nfogen/quality.py` : chaîne de priorité réelle (résolution > source >
   type audio > codec vidéo > canaux audio > HDR, langue gérée à part),
   coexistences VFF/VFQ (ne se remplacent plus l'une l'autre — c'était un
   bug de la heuristique par défaut initiale, corrigé), HDR+DV combiné vs
   séparé. Deux limites assumées faute de la page "Guide des slots"
   (référencée par la politique mais jamais fournie, contient les valeurs
   de repli exactes par slot) : l'ordre source/codec vidéo/HDR utilisé est
   un ordre GÉNÉRAL raisonnable, pas un ordre contextuel par slot ; la
   règle de poids spécifique aux WEBRip (accepté seulement si plus léger
   que l'existant, sauf meilleure langue) n'est pas modélisée — demanderait
   de faire remonter la taille des fichiers depuis Sonarr/Radarr, absente
   aujourd'hui de `SonarrSeasonFile`/`RadarrMovieFile`. Détail dans les
   docstrings de `quality.py`.
2. **Confirmation Sonarr/Radarr** : toujours en attente — `.env` ne
   contient pour l'instant que `NFOGEN_C411_API_KEY` (vérifiée en direct,
   `search_movie` répond). `NFOGEN_SONARR_URL`/`NFOGEN_SONARR_API_KEY`/
   `NFOGEN_RADARR_URL`/`NFOGEN_RADARR_API_KEY` restent vides — à remplir
   pour tester `sonarr_client.py`/`radarr_client.py` en conditions réelles
   (juste confirmer que ce sont des instances v3 standard, API REST
   `/api/v3/...`).

## Architecture prévue

```text
nfogen/
├── sonarr_client.py     # GET /api/v3/series, /api/v3/episodefile — titre, année, IDs (tvdbId/imdbId), qualité, langues
├── radarr_client.py     # GET /api/v3/movie, /api/v3/moviefile     — idem films
├── c411_client.py       # Client API C411 (clé API) : recherche par titre/ID externe, parsing qualité/langue des releases listées
├── gapscan.py           # Orchestration : bibliothèque locale -> matching -> liste de GapResult
├── models.py            # + dataclass GapResult (titre, année, ids externes, quality_local, language_local, statut_c411, raisons)
└── api.py               # + endpoints /gapscan/*
```

### Flux

1. `sonarr_client` + `radarr_client` construisent l'inventaire local :
   un item par film/épisode-pack, avec identifiants externes (IMDb/TVDB —
   essentiels pour un matching fiable, le titre seul est ambigu) et les
   caractéristiques de **ta** version (résolution, source, codec, langues
   audio).
2. Pour chaque item, `c411_client` interroge C411 (par ID externe si
   l'API le permet, sinon par titre+année en repli) et récupère les
   releases déjà présentes sur le tracker pour ce titre.
3. `gapscan` compare ta version à l'ensemble des releases C411 trouvées et
   classe chaque item :
   - **Absent** — le titre n'existe sous aucune forme sur C411.
   - **Qualité manquante** — le titre existe, mais pas dans ta
     résolution/source (barème exact = point "À fournir" #1).
   - **Langue manquante** — le titre existe dans une qualité comparable,
     mais pas ta combinaison de langues (ex. tu as VFQ, C411 n'a que
     VOSTFR).
   - **Couvert** — une release équivalente ou meilleure existe déjà :
     exclu des résultats par défaut (affichable en option "voir tout").
   - **Non vérifié (erreur)** — ajouté le 2026-08-25, suite à un incident
     réel (voir "Résilience et rate-limiting" ci-dessous) : la recherche
     C411 pour CE titre a échoué (429, 520, timeout...). N'interrompt plus
     le scan des titres suivants ; qualité/langue locale connue quand
     même affichée, aucune release C411 comparée.
4. Résultat exposé via l'API et la page frontend, avec pour chaque gap un
   lien direct vers `POST /generate` (le profil C411 existant) pour
   préparer le NFO d'upload.

## Endpoints API (implémentés le 2026-08-25)

| Endpoint | Auth | Usage |
|---|---|---|
| `POST /gapscan/run` | oui (même modèle que `/profiles/store*`) | Lance un scan (tâche de fond — voir "Exécution" ci-dessous). `?incremental=true` : reprend les titres déjà couverts et inchangés du dernier scan sans les réinterroger (sauf s'ils dépassent `NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS`, 7 jours par défaut). `?only=movies`/`?only=series` : ne scanne qu'une des deux bibliothèques. `400` si mal configuré ou `only` invalide, `409` si un scan tourne déjà |
| `GET /gapscan/status` | oui | État (`idle`/`running`/`done`/`error`) + progression (`processed`/`total`) du dernier scan |
| `GET /gapscan/results` | oui | Derniers résultats (JSON), filtrable par statut (`?status=absent`) |
| `GET /gapscan/results/export.csv` | oui | Export CSV, mêmes filtres |
| `GET /gapscan/config` | oui | Configuration effective : booléens `*_configured` + URLs (jamais les clés) |
| `PUT /gapscan/config` | oui | Enregistre URLs/clés Sonarr/Radarr/C411 — mise à jour partielle, un champ omis reste inchangé |

**Retour sur la décision "pas de PUT" prise plus haut dans ce fichier** :
ajouté le 2026-08-25, après un premier test manuel de l'app — éditer
`.env` à la main et redémarrer le service à chaque changement de clé
Sonarr/Radarr était trop de friction pour un usage réel. Contrairement à
`NFOGEN_API_TOKEN` (qui protège nfogen lui-même, jamais de `PUT`), les
clés Sonarr/Radarr/C411 sont des identifiants **sortants** vers des
services tiers : rien ne justifiait de bloquer leur modification à chaud.
`nfogen/gapscan_config_store.py` : fichier JSON optionnel
(`NFOGEN_GAPSCAN_CONFIG_FILE`, jamais commit), relu à chaque appel (pas de
cache, comme `accounts.py`), toujours prioritaire sur les variables
d'environnement historiques quand les deux sont présentes — celles-ci
restent utilisables seules (lecture seule, pas de `PUT`) pour un
déploiement non interactif (docker-compose, `.env` sans UI).

**Exécution** : implémenté (2026-08-25) — `POST /gapscan/run` lance un scan
en tâche de fond (`nfogen/gapscan_runner.py`, `threading.Thread`), un seul
scan à la fois (409 sinon), résultats gardés en mémoire jusqu'au prochain
scan (pas de re-scan à chaque chargement de page). Limitation de débit vers
C411 : `NFOGEN_C411_MIN_INTERVAL_SECONDS` (0.5s par défaut, ajustable) —
valeur prudente faute de limites documentées publiquement. Persistance sur
disque et mode incrémental : voir "Persistance des résultats" plus bas.

## Frontend prévu

Nouvelle page (ex. "Scan C411") dans `frontend/` :
- Bouton de lancement + barre de progression (poll `/gapscan/status`).
- Table triable/filtrable (par statut, type film/série, année) des gaps.
- Export CSV.
- Par ligne : lien vers la génération NFO (profil C411 déjà existant)
  pré-rempli avec ce que `nfogen` peut déduire (résolution, langues) du
  fichier local via Sonarr/Radarr.

## Sécurité / conformité

- Les clés API (Sonarr, Radarr, C411) suivent le même traitement que les
  secrets existants du projet : jamais en clair côté client, stockage
  serveur uniquement, protégé par `NFOGEN_API_TOKEN`/comptes nommés. La clé
  C411 est plus sensible qu'il n'y paraît : elle permet aussi de pousser un
  upload (`POST /api/torrents`, voir plus haut), pas seulement de lire le
  catalogue -- une clé compromise a un impact plus large qu'une simple
  fuite de lecture.
- GapScan **ne télécharge, n'héberge et ne distribue aucun contenu** —
  même avertissement que le reste de `nfogen` (voir README). Il ne fait
  que comparer des métadonnées (ta bibliothèque locale que tu possèdes
  déjà, vs le catalogue d'un tracker dont tu es membre via ta propre clé
  API) pour t'aider à identifier quoi uploader toi-même.
- Respect des conditions d'utilisation de l'API C411 (rate limiting côté
  client, pas de contournement d'authentification).

### Incident réel (2026-08-25) : clé API C411 exposée en clair

Premier test manuel de l'app : une réponse `520` de C411 a fait apparaître
la clé API en clair dans le message d'erreur affiché par
`GET /gapscan/status` — `httpx` inclut l'URL complète (donc `?apikey=...`)
dans `HTTPStatusError.__str__` et d'autres erreurs `httpx.HTTPError`, non
anticipé à l'écriture initiale de `c411_client.py`. Clé exposée
immédiatement régénérée par l'utilisateur. Corrigé : `C411Client._search()`
rédige systématiquement la clé de tout message d'erreur avant de le
propager, quelle que soit l'erreur rencontrée (testé explicitement, avec
la clé et les paramètres de la requête réelle qui a échoué). `Sonarr`/
`RadarrClient` non concernés : leur clé passe par un en-tête
(`X-Api-Key`), jamais dans l'URL.

### Résilience et rate-limiting

Suite du même test manuel : `NFOGEN_C411_MIN_INTERVAL_SECONDS=0.5`
(défaut initial) a déclenché un `429 Too Many Requests` — confirme un vrai
rate-limit côté C411, non documenté publiquement (page
`/user/integrations/guide` inaccessible sans session navigateur, 403).
Deux correctifs :

- **Défaut relevé à 2.0s**, et `C411Client` réessaie automatiquement une
  fois après un `429` (respecte l'en-tête `Retry-After` s'il est présent,
  sinon 5s par défaut) avant d'abandonner ce titre.
- **Un titre en échec n'interrompt plus tout le scan** : `scan_movie`/
  `scan_series_season` renvoient un `GapResult` de statut `error` (nouveau,
  voir "Flux" ci-dessus) au lieu de laisser l'exception remonter — avant ce
  correctif, la progression déjà faite sur une grosse bibliothèque était
  perdue au premier accroc réseau, transitoire ou non.

### Premier scan réel (2026-08-26) : deux correctifs de justesse du matching

- **Saison 0 exclue** : `Misfits S00` remontait dans les résultats — la
  saison 0 est la convention Sonarr pour les "Specials" (extras, hors
  série), pas une vraie saison diffusée, sans équivalent dans les packs
  C411 standard. `sonarr_client.list_season_files()` l'exclut désormais.
- **Repli par titre trop restrictif** : un film avec un `imdb_id`/`tmdb_id`
  connu (ex. Joker) ne trouvait rien sur C411 si l'ID n'y était pas
  reporté — cf. "présents sur la plupart des items mais pas
  systématiquement" plus haut. `scan_movie()` retente désormais par titre
  dès que la recherche par ID échoue, plus seulement quand aucun ID n'est
  connu. Filtré par année (`_filter_by_year`) pour ne pas confondre des
  films homonymes de millésimes différents (plusieurs "Joker" existent :
  2019, 2024...) — une release sans année détectable dans son titre n'est
  pas écartée par prudence.
- **Piste non retenue pour l'instant, notée pour plus tard** : la clé API
  C411 de l'utilisateur permet aussi de pousser un upload (voir correction
  plus haut, section "API C411"). GapScan reste strictement lecture seule
  (aucun appel à `POST /api/torrents`) — automatiser l'upload depuis
  nfogen à partir d'un gap détecté serait un changement de nature du
  projet (nfogen ne télécharge/n'héberge/ne distribue rien aujourd'hui,
  voir README "Avertissement"), à décider explicitement plutôt qu'à
  ajouter incidemment.

### Persistance des résultats + scan incrémental (2026-08-26)

Retour utilisateur après le premier scan réel complet (~1140 titres) :
"à chaque MAJ je vais devoir refaire un scan ? ... j'ai déjà scanné, je vais
pas tout rescanner c'est pas fou". Deux problèmes distincts, réglés
ensemble :

1. **Les résultats ne survivaient pas à un redémarrage du processus** — y
   compris celui déclenché par `scripts/update.sh` lui-même. `_progress`/
   `_results` dans `gapscan_runner.py` étaient purement en mémoire.
   Corrigé : `nfogen/gapscan_results_store.py` (même principe que
   `gapscan_config_store.py`) écrit le dernier scan terminé sur disque —
   fichier optionnel `NFOGEN_GAPSCAN_RESULTS_FILE` (ajouté par
   `scripts/install.sh`, `chmod 600`), rechargé au chargement du module.
   `GET /gapscan/results` répond donc correctement juste après un
   redémarrage, avant même qu'un nouveau scan ait tourné.
2. **Un nouveau scan repartait toujours de zéro** — même si rien n'avait
   changé localement pour la plupart des titres. Corrigé : `POST
   /gapscan/run?incremental=true` (`gapscan_runner.start(..., incremental=
   True)` → `run_gapscan(..., previous_results=...)`) reprend tel quel le
   résultat précédent d'un titre si (a) il était déjà `covered` et (b) sa
   qualité locale (résolution/source/codec/langues/`pure`) n'a pas changé
   depuis — aucun appel C411 dans ce cas. Tout le reste (nouveaux titres,
   qualité locale changée, titres pas encore couverts) est réinterrogé
   normalement : un gap non comblé mérite d'être revérifié, C411 a pu se
   remplir depuis le dernier passage.

Le frontend expose ce choix (scan complet vs rapide) sur la page "Scan
C411", rapide par défaut dès qu'un scan précédent existe.

### Débit confirmé, scan par catégorie, expiration du mode incrémental, titres alternatifs (2026-08-27)

Suite d'échange avec les admins C411 + retours après usage réel du mode
incrémental :

- **Débit réellement sûr** : les admins C411 ont confirmé directement une
  limite de **15 requêtes/min par utilisateur**. `NFOGEN_C411_MIN_INTERVAL_SECONDS`
  (2.0s par défaut, choisi avant cette confirmation, sur la seule base d'un
  429 observé une fois) dépassait cette limite (~30/min). Nouveau défaut :
  **4.5s (~13,3/min)**, marge de sécurité sous le seuil confirmé.
- **Scan par catégorie** : `POST /gapscan/run?only=movies` ou `?only=series`
  scanne Radarr ou Sonarr séparément (`run_gapscan(..., only=...)`), pour
  répartir la charge sur plusieurs sessions si besoin. Sélecteur ajouté sur
  la page "Scan C411". (Les codes de catégorie C411 eux-mêmes — Film 2000,
  Série TV 5000, etc. — n'ont pas besoin d'être passés explicitement : les
  types Torznab `t=movie`/`t=tvsearch` déjà utilisés par `c411_client.py`
  scopent déjà la recherche côté indexeur.)
- **Expiration du mode incrémental** : retour utilisateur — C411 retire et
  ajoute des torrents assez souvent, un `covered` repris indéfiniment sans
  jamais être revérifié pourrait devenir faux avec le temps. `GapResult`
  gagne un champ `checked_at` (horodatage de la dernière vérification
  RÉELLE auprès de C411 ; conservé tel quel, pas rafraîchi, quand un
  résultat est simplement repris sans réinterroger C411). `_can_reuse()`
  n'accepte de reprendre un `covered` que s'il a moins de
  `NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS` (7 jours par défaut, ajustable)
  — au-delà, réinterrogé normalement même si rien n'a changé localement.
  Un résultat persisté avant l'ajout de ce champ (`checked_at` absent) est
  traité comme périmé par prudence dès qu'une limite d'âge est demandée.
- **Titres alternatifs (VF)** : C411 est un tracker francophone qui liste
  souvent un titre sous son nom de sortie/diffusion FR, pas l'original —
  incident réel remonté : "Wild Card" (film avec Jason Statham) sort en
  France sous le titre "Joker" ; "White Collar" est diffusée sous "FBI, duo
  très spécial". La recherche par ID (imdb/tmdb/tvdb) reste toujours
  tentée en premier (la plus fiable), puis le titre original en repli ;
  seulement si les deux échouent, `scan_movie()`/`scan_series_season()`
  essaient maintenant chaque titre alternatif connu de Sonarr/Radarr
  (`alternateTitles`, exposé via `RadarrMovieFile.alternate_titles`/
  `SonarrSeasonFile.alternate_titles`), dans l'ordre, jusqu'au premier qui
  trouve quelque chose. Toujours filtré par année pour les films
  (`_filter_by_year`), pour ne pas confondre un homonyme d'un autre
  millésime. Best-effort : ne fonctionne que si Sonarr/Radarr ont
  effectivement indexé ce titre alternatif pour ce média précis — pas
  garanti à 100%.

### Filtre type/genre + pagination serveur (2026-08-28)

**Constat** : 1140+ médias dans la bibliothèque de l'utilisateur, le
tableau `GET /gapscan/results` renvoie tout d'un coup (pas de pagination),
et le seul filtre disponible sur les résultats déjà scannés est le statut
(`GapStatus`) — aucun moyen d'afficher "seulement les films" ou "seulement
les animés" une fois un scan combiné (Films + séries) terminé (le menu
"Films seulement/Séries seulement" ne contrôle QUE ce qui est scanné, pas
ce qui est affiché).

**Genre (Animé/Documentaire)** : dérivé de `c411_matches[0].category` (le
premier match, déjà trié par pertinence C411), jamais du côté
Sonarr/Radarr — confirmé par l'utilisateur : "les trackers sont les plus à
même de donner ça". Table de correspondance **vérifiée en direct** via
`GET https://c411.org/api?t=caps` (la note précédente de ce fichier,
`2030`/`2060`/`2070` = "Films/Anime/Documentaire", était fausse — `2030`
est en fait le code **Film générique**, ce qui expliquait un faux
classement "Anime" sur un film totalement étranger au genre pendant les
tests) :

| Genre | Films | Séries |
|---|---|---|
| Standard (Film/Série) | `2030` | `5000` |
| Animé | `2060` | `5070` |
| Documentaire | `2070` | `5080` |

**Limite assumée, actée avec l'utilisateur** : un titre `"absent"` (aucun
match C411 trouvé) n'a par définition aucune catégorie — impossible de le
classer Animé/Documentaire tant que rien n'est trouvé. Ces titres restent
filtrables par `media_type` (Film/Série, toujours connu via Sonarr/Radarr)
mais jamais par genre fin ; un filtre Animé/Documentaire actif les exclut
simplement (comportement voulu, pas un bug).

**Pagination** : côté **serveur** (choix explicite de l'utilisateur, pense
à la scalabilité au-delà de 1140 titres) — `GET /gapscan/results` gagne
`page`/`page_size` en plus de `status` (déjà existant) et des nouveaux
`media_type`/`genre`. Réponse enveloppée `{items, total}` au lieu d'une
liste nue (rupture du contrat existant, assumée puisque frontend et API
sont versionnés/déployés ensemble). Le tri des colonnes est explicitement
**hors scope** de ce lot (à ajouter plus tard si besoin réel une fois le
tableau plus maniable).

**Conception** :
1. `nfogen/gapscan.py` : `genre_of(result: GapResult) -> Optional[str]`
   (fonction pure, `"anime"`/`"documentaire"`/`None`), table de
   correspondance ci-dessus.
2. `nfogen/gapscan_runner.py` : `results()` gagne `media_type_filter` et
   `genre_filter` (même principe que `status_filter` déjà là).
3. `nfogen/api.py` : `GET /gapscan/results` gagne `media_type`, `genre`,
   `page` (défaut 1), `page_size` (défaut 50, max 500) ; chaque item de la
   réponse gagne un champ `genre` calculé (`genre_of`) — un seul endroit
   qui connaît la table de correspondance, jamais dupliquée côté
   TypeScript. `GET /gapscan/results/export.csv` gagne les mêmes filtres
   media_type/genre (cohérence avec la vue affichée) + colonne `genre`.
4. Frontend (`GapScanPage.tsx`) : nouveau `<select>` à côté du filtre
   Statut existant ; pagination précédent/suivant sous le tableau
   ("Page X / Y — N résultats"). Tout changement de filtre remet la page
   à 1.

**Livré (2026-08-28)** — un écart par rapport à la conception initiale :
deux `<select>` séparés (Type, Genre) prévus au départ, **fusionnés en un
seul** après retour utilisateur ("deux menus qui se combinent, c'est pas
intuitif") — chaque option du select unique correspond directement à une
catégorie C411 réelle (Films, Séries, Films d'animation, Séries animées,
Documentaires films/séries). Aucun changement côté API : `media_type`/
`genre` restent deux paramètres distincts, combinés uniquement côté
frontend à la sélection.

Voir le plan d'implémentation complet (code exact) :
[docs/superpowers/plans/2026-08-28-gapscan-genre-filter-pagination.md](docs/superpowers/plans/2026-08-28-gapscan-genre-filter-pagination.md).

## Plan de tests (calqué sur l'existant, `tests/test_c411.py` etc.)

- `sonarr_client`/`radarr_client` : tests contre des réponses JSON figées
  (fixtures), pas d'appel réseau réel en CI.
- `c411_client` : idem, fixtures basées sur l'exemple de réponse que tu
  fourniras (point "À fournir" #2).
- `gapscan` : tests de la logique de classification (absent / qualité
  manquante / langue manquante / couvert) sur des cas synthétiques,
  indépendants des deux clients.

## Prochaine étape

Dès que tu me donnes les points 1 et 2 de "À fournir", je peux poser le
squelette (`models.py`, `c411_client.py` avec fixtures, endpoints
`/gapscan/*` vides) et itérer dessus.


## Regle Copié directement du site c411 https://c411.org/guide/slots

 Système de priorités

Quand un slot est déjà occupé, le système compare le nouveau torrent avec l'occupant actuel selon une chaîne de critères. Le premier critère qui diffère détermine le vainqueur.
Chaîne de priorité (du plus important au moins important)
1
Langue·MULTI.VF2 > VF2 (VFF/VFQ seuls déclenchent la coexistence)
2
Résolution·Plus haute = mieux (2160p > 1080p > 720p)
3
Source·Contextuel au profil (voir détail ci-dessous)
4
Type audio·Lossless > Lossy (selon le slot)
5
Codec vidéo·Selon le slot (H.265 > H.264 ou AV1)
6
Canaux audio·Plus de canaux = mieux (7.1 > 5.1 > 2.0)
7
Codec audio·Compatibilité : AAC > EAC3. Autres profils : EAC3 > AAC
8
HDR·Contextuel au slot (DV.HDR10+ ou HDR10)

Si tous les critères sont identiques, c'est le torrent le plus ancien qui reste en place. À date égale, celui avec le plus de seeders est conservé.
Priorité des langues
PRIORITÉ 1
MULTI.VF2
VO + VFF + VFQ
PRIORITÉ 2
VF2
VFF + VFQ (sans VO)

VFF ou VFQ seul ne constitue pas un niveau de priorité - c'est un cas de coexistence temporaire. Quand il n'existe ni VF2 ni MULTI.VF2, une version VFF et une version VFQ peuvent occuper le même slot en attendant une version unifiée.
Priorité des sources (contextuelle)

L'ordre de priorité des sources varie selon le profil et le type de slot :
CompatibilitéBluRay > WEB-DL > HDTV > DVDRip
HC PureBluRay (DVDRip fallback pour les slots 1080p)
HC OptimiséBluRay > WEB-DL > DVDRip (slots 1080p) / BluRay > WEB-DL (slots 2160p)
OptimisationBluRay > WEB-DL > DVDRip > HDTV
Slots Bluray.HDLight/WRBluray.HDLight > WEBRip > WEB-DL (le WEB-DL ou WEBRip occupe le slot en attendant un Bluray.HDLight)
Coexistences temporaires

Dans certains cas, deux versions d'un même contenu peuvent coexister temporairement dans un slot, en attendant qu'une version unifiée arrive.
VFF + VFQ

Quand il n'existe pas encore de version VF2 ou MULTI.VF2, le système autorise la coexistence d'une version VFF et d'une version VFQ dans le même slot.

Fusion : dès qu'une VF2 ou MULTI.VF2 arrive, les deux sont remplacées.
HDR + DV séparés

Quand il n'existe pas de version combinée DV.HDR10, une version HDR-only et une version DV-only peuvent coexister temporairement.

Fusion : dès qu'une version DV.HDR10 ou DV.HDR10+ arrive, les deux sont remplacées.
Lossy + Lossless

Une version avec piste audio lossless (TrueHD, DTS-HD MA, FLAC) et une version lossy (EAC3, AAC, AC3) peuvent coexister de façon permanente dans le même slot. Cela permet de proposer à la fois la meilleure qualité audio et une version plus compatible / légère.

Permanent : contrairement aux splits VFF/VFQ et HDR/DV, la coexistence lossy/lossless n'a pas de version "unifiée" - un torrent ne peut pas être à la fois lossy et lossless. Une meilleure langue ne provoque pas non plus le remplacement d'un lossless par un lossy.
Règles Bluray.HDLight / WEBRip

Les Bluray.HDLight (encodes légers depuis un Blu-ray) et les WEBRip (ré-encodes depuis un flux web) partagent les mêmes slots. Le Bluray.HDLight est prioritaire, suivi du WEBRip puis du WEB-DL en fallback. Les WEBRip ont des conditions spécifiques de taille pour être acceptés.
Plus léger que le WEB-DL existant
Si un WEB-DL existe, le WEBRip doit peser moins lourd
Plus léger que le BluRay existant
Si un BluRay encodé existe, le WEBRip doit aussi peser moins

Exception : un WEBRip avec plus de langues (ex : VF2 vs VFF) est accepté même s'il est plus lourd - l'excédent de poids est justifié par les pistes audio supplémentaires.
Versions spéciales

Certains films ont des versions alternatives (montage différent, format différent, etc.). Chaque version spéciale dispose de son propre jeu complet de 28 slots, totalement indépendant de la version théâtrale.
UNCUTTHEATRICALEXTENDEDDIRECTOR'S CUTIMAXOpen MatteHybridAD

Par exemple, la version Director's Cut d'un film et sa version théâtrale ne sont jamais en concurrence. Chacune a ses 28 slots indépendants.
Versions correctives

Si vous détectez un problème dans votre propre upload (mauvais encodage, piste audio défectueuse, sous-titres manquants...), vous pouvez uploader une version corrective qui remplacera votre version précédente, même si un autre torrent est normalement prioritaire.
PROPERREAL PROPERREPACKFIXRERIPv2

Remplace la version du même uploader uniquement

Un fichier NFO décrivant les corrections est obligatoire

Si l'occupant du slot est un autre uploader, la version corrective est traitée comme un upload normal 

## Copie des regles de la page https://c411.org/wiki/cat-video

Catégorie Films & Vidéos

Dans toute bibliothèque audiovisuelle, la qualité d’un catalogue ne se mesure pas à la quantité de fichiers disponibles, mais à la rigueur avec laquelle ils sont sélectionnés, qualifiés et présentés. Un tracker n’échappe pas à cette logique. Sans standards clairs, le catalogue se fragmente, les doublons se multiplient, la compatibilité se dégrade et le seed se disperse, au détriment de l’ensemble de la communauté.

Les règles qui suivent ont donc été conçues comme un cadre méthodique. Elles commencent par définir ce qui peut être publié dans la catégorie Films et Vidéos, tant sur la typologie des contenus que sur les formats admis. Elles précisent ensuite les exigences techniques minimales relatives à la résolution, au bitrate, à l’encodage, à l’audio et aux sous-titres. Elles encadrent également les situations particulières, notamment les remux, les packs et le mux de sous-titres, ainsi que la politique de doublons et les interdictions destinées à écarter les sources dégradées et les transcodages inutiles. Enfin, une procédure de dérogation peut être envisagée à titre exceptionnel, selon des conditions formalisées.
Formats et types autorisés

Il est essentiel de délimiter clairement ce qui peut être publié dans la catégorie. Deux aspects sont à distinguer : d’une part, la nature du contenu (ce que vous uploadez) ; d’autre part, son format technique (comment il est conditionné et lu).
Précision sur les noms

Les noms doivent être dans le titre d'exploitation du média en France ! Nous sommes un tracker FR et notre priorité est de proposé des release dans les noms qui sont utilisé en France.

Par exemple :

    "Now you can see me" : Il s'agit du titre qui est utilisé à l'international, néanmoins en France, le titre d'exploitation est Insaisissables

    "Anyone but you" : Il s'agit du titre qui est utilisé à l'international, néanmoins en France, le titre d'exploitation est Tout sauf toi

    "Avengers" : Avengers est un titre anglais, mais il s'agit du titre qui est utilisé à l'exploitation en France, alors il est valable

Précision sur les TAGs de Team

Les caractères spéciaux contenus dans le nom des Teams tombent sous le même régime que les règles de nommage; Ils sont interdits

De ce fait, les caractères spéciaux inclus dans le nom de la Team sont tout simplement retirés

Par exemple :

    Tsundere-Raws devient TsundereRaws

Types de contenus acceptés

Le premier repère concerne la typologie du contenu. Cette liste sert de cadre de référence pour maintenir un catalogue cohérent, éviter les dépôts hors-sujet et faciliter le classement.

    Films (longs métrages commerciaux)

    Séries TV : épisode unique, saison complète, ou intégrale (si série terminée)

    Séries animées / Anime

    Documentaires

    Émissions TV

    Concerts, Clips vidéo, Spectacles

    Événements sportifs

    Courts métrages (non amateurs uniquement)

Dans un but de cohérence, les fichiers des packs doivent impérativement partager les mêmes specs (même langues, sous-titres, codec), autrement il sera préférable de ne pas faire de pack et mettre à disposition les éléments de façons unitaire :)

IMPORTANT : Lorsque la release dispose de plusieurs nom en fonction de la langue, préférez le nom français utilisé pour l'exploitation. Le titre original sera inscrit dans votre description.
Formats de fichiers acceptés

Une fois le contenu identifié, le format doit répondre à des standards précis. L’objectif est simple : assurer une compatibilité large, un rendu fiable sur la plupart des lecteurs et une intégration propre dans les outils de médiathèque.

    Conteneurs :

        .MKV.MP4

        .M4V

        .AVI

        .TS

        .M2TS

    Encodes et remux :

        MKVMP4

    Contenu Blu-Ray complet :

        BDMVISO

    Contenu DVD complet :

        VIDEO_TSISO

Packs autorisés

Enfin, certains regroupements sont admis lorsqu’ils apportent une vraie valeur d’usage, en rassemblant des contenus liés de manière évidente et structurée.

    Saisons complètes de séries

        Pas de pack en plusieurs partie, c'est un tracker et non un site de DL :)

    Intégrales

        Nécessite que la série soit terminée :)

    Séries de films

    Saga

    Collections

    Packs Réalisateur/Acteur

    Packs Animation

        Les Kai sont autorisés :)

IMPORTANT : Dans un but de cohérence, les fichiers des packs doivent impérativement partager les mêmes specs (même langues, sous-titres, codec), autrement il sera préférable de ne pas faire de pack et mettre à disposition les éléments de façons unitaire :)
Informations techniques

La section technique a pour vocation de rendre la release immédiatement intelligible. Elle permet aux peers d’anticiper la compatibilité avec leur matériel, d’évaluer la qualité attendue et, pour la modération, de vérifier d’un coup d’œil que l’upload s’inscrit dans les standards du tracker.
Vidéo

Les critères vidéo constituent le socle de la conformité. Ils fixent à la fois le périmètre des résolutions admises, les seuils de compression acceptables, ainsi que les pratiques d’encodage et de traitement d’image autorisées.
1. Résolution

La résolution est la première information structurante d’un upload. Elle doit refléter fidèlement le contenu du fichier et rester cohérente avec la source. Vous trouverez ci-dessous les résolutions autorisées, à renseigner dans le champ « Résolution ».Vous trouverez ici, les résolutions autorisés pour vos uploads, à insérer dans le champs 'Résolution' :
Résolution	Largeur min.	Hauteur min.
SD	640 pixels	360 pixels
720p	1280 pixels	720 pixels
1080p	1920 pixels	1080 pixels
2160p	3840 pixels	2160 pixels

Rappel : la précision de la résolution n'est pas obligatoire lorsque la résolution est inférieure à 720p ;)
2. Encodage

Petit point explication :

L’encodage correspond au processus qui consiste à convertir une source vidéo (Blu-ray, WEB-DL, HDTV, etc.) en un fichier de distribution plus simple à stocker, à partager et à lire. Une source “brute” peut être très volumineuse, contenir des structures peu pratiques (par exemple un BDMV), ou être inadaptée à certains usages. L’encodage vise donc à produire un fichier exploitable, en trouvant un équilibre maîtrisé entre qualité, poids et compatibilité.

Sur le plan technique, l’encodage fixe les caractéristiques essentielles du rendu final. Le choix du codec vidéo (H.264/AVC, H.265/HEVC, AV1…) détermine la méthode de compression et influe directement sur l’efficacité à taille égale. Ensuite, des paramètres structurants encadrent la qualité perçue et la stabilité de lecture, notamment le CRF ou le bitrate, la résolution, la profondeur de couleur (8/10 bits), l’éventuelle gestion du HDR/SDR, ou encore certains profils et niveaux destinés à assurer une compatibilité correcte avec les lecteurs et téléviseurs.

C’est précisément cette combinaison de choix qui explique pourquoi deux releases d’un même contenu peuvent être très différentes, même à résolution identique.

La réalisation concrète de l’encodage est assurée par des logiciels spécialisés, appelés encodeurs (HandBrake, StaxRip, FFmpeg, etc.). Ces outils pilotent des moteurs d’encodage tels que x264 (pour produire du H.264) ou x265 (pour produire du H.265).

En pratique, le codec constitue le standard de compression, tandis que l’encodeur est l’outil qui applique ce standard en fonction de réglages précis. Bien configuré, il permet de produire un fichier cohérent, reproductible et conforme aux exigences du catalogue C411, en garantissant une qualité stable plutôt qu’un simple “gain de taille” au détriment du rendu :)

À présent revenons au guide.

Les encodages (codec) acceptés

    H.262 (MPEG-2) : Accepté à titre exceptionnel uniquement pour les médias très anciens si aucune version supérieure n'est disponible

    H.263 (XVID) : Accepté à titre exceptionnel uniquement pour les médias très anciens si aucune version supérieure n'est disponible

    VC-1 : Accepté uniquement sur les versions pures (REMUX / ISO / BDMV) issues de Blu-ray anciens. Interdit en encode.

    H.264 (AVC) : Standard le plus répandu et le plus compatible. Recommandé pour les versions “compatibilité”

        Le TAG AVC (et non H264) est obligatoire sur les version pure (REMUX/ISO/BDMV)

    H.265 (HEVC) : Codec plus efficace que H.264 (meilleure compression). Très utilisé en 1080p/2160p, y compris en HDR.

        Le TAG HEVC (et non H265) est obligatoire sur les version pure (REMUX/ISO/BDMV)

    AV1 : Codec moderne très efficace (excellent rapport qualité/taille). Compatibilité plus variable selon les appareils, mais en forte adoption.

Moteurs d'encodage accepté (CPU)

    x264

        TAG INTERDIT sur version Pure (REMUX/ISO/BDMV)

    x265

        TAG INTERDIT sur version Pure (REMUX/ISO/BDMV)

    SVT-AV1

Moteurs d'encodage INTERDIT (GPU)

    NVENC / QSV / AMF : encodage via GPU/IGPU (très rapide), mais qualité moins régulière à taille égale

Les bitrates minumum par encodage

    Pour H263/XVID

Format	Bitrate minimum
SD	1500 kb/s

    Pour AV1/H265/H264/WEBRip

Format	Bitrate minimum
1080p x264	2 500 kb/s
1080p x265	1 200 kb/s
1080p AV1	800 kb/s
2160p x265	2 800 kb/s
2160p AV1	2 200 kb/s

    Exception pour la source WEB/WEB-DL

Dans le cadre d’un WEB/WEB-DL, l’objectif prioritaire est de conserver le fichier source dans son état le plus proche possible de l’original (« untouched »). Les plateformes VOD diffusent en effet des flux déjà fortement optimisés, avec des débits souvent contenus, de sorte qu’un ré-encodage introduit fréquemment une dégradation perceptible sans bénéfice réel. Par ailleurs, ces bitrates évoluent régulièrement au gré des optimisations opérées par les services, ce qui rend l’établissement d’un seuil universel peu pertinent. En conséquence, lorsqu’un WEB-DL est bien identifier, aucun minimum de bitrate n’est exigé.

    Exception pour les WEB-DL Netflix (NF)

Les flux Netflix sont déjà encodés et optimisés pour la diffusion en streaming. En pratique, une qualité vidéo satisfaisante peut donc être atteinte avec un débit moyen sensiblement plus faible que sur d’autres WEB-DL.
Format	Minimum Bit rate	Maximum bit rate
1080p	5 000 kb/s	7 500 kb/s

Recommandation d'encodageAu-delà des chiffres, la méthode d’encodage compte autant que le résultat. Les recommandations ci-dessous ont été retenues pour garantir des encodes propres, reproductibles et comparables, tout en évitant les configurations trop rapides qui sacrifient la qualité.

    Mode CRF recommandé

    Mode ABR toléré uniquement en 2 passes :

        x264 : "rc=2pass"x265 : "rc=abr" avec "stats-read=2"

    Preset minimum : Medium (Fast et plus rapides = suppression)

    Les paramètres d'encode doivent être visibles pour les uploads en Pending

INTERDIT : Tout encodage avec GPU (NVENC, AMF, QSV...)

RAPPEL DES CONVENTIONS :

- HEVC / AVC : flux vidéo original provenant directement du disque, sans ré-encodage. À utiliser pour les REMUX, BDMV et ISO.

- H264 / H265 : flux vidéo provenant d'une plateforme de streaming, encodeur inconnu (encodeurs propriétaires). À utiliser pour les WEB-DL untouched.

- x264 / x265 : flux vidéo ré-encodé avec l'encodeur open source x264 ou x265. À utiliser pour les encodes (BluRay, WEBrip, DVDrip) et WEB-DL encodés
3. HDR et Dolby Vision

Le HDR (HDR10 / HDR10+) et le Dolby Vision ajoutent un niveau d’exigence supplémentaire, car ils reposent sur des profils et des modes de lecture qui varient fortement selon les appareils. Les règles ci-dessous ont pour objectif d’éviter les publications ambiguës, de garantir un rendu fidèle à la source, et de préserver la compatibilité (notamment le fallback HDR10 lorsque c’est possible).

1) Profils Dolby Vision : règles de base

Le Dolby Vision se décline en plusieurs profils, l’idée est de conserver le DV quand il est présent, et s’assurer que le HDR soit lisible sur les appareils non compatibles DV lorsque la source le permet.

    Profile 5 : Profil le plus courant sur les sources WEB (Netflix, iTunes, Disney+, etc.)

    Profile 7 : Profil des Blu-ray UHD commerciaux (BDMV/REMUX) généralement base HDR10 + enhancement layer DV convertir en P8 pour rip x265

    Profile 8 : C’est le profil le plus pratique côté “rip” car il est conçu pour fonctionner sur une base HDR10, de ce fait il demeure OBLIGATOIRE pour tout rip x265 DV HDR

2) Règle de nommage : position des tags HDR / DV

Lorsque votre version dispose d'un HDR, celui-ci doit être précisé à la suite de la source. Merci de ne rien indiquer lorsqu'il s'agit de SDR :)

3) Tags HDR autorisés

    HDR/HDR10 (par défaut) : Le 10 correspond à 10 bits, nous préférons qu'il soit indiquer directement de cette manière afin de faciliter le parsing lors de l'automatisation

    HDR10PLUS

4) Tags Dolby Vision autorisés

    DV (référence)

    Variantes tolérées : DoVi / DOVI / DolbyVision (idéalement éviter les multiples variantes dans le catalogue)

5) Cas “DV + HDR”

Le tag DV.HDR doit être réservé aux releases où le Dolby Vision repose sur une base HDR10 (fallback HDR10 assuré).

Cela correspond typiquement à :

    Profil 7 (dvhe.07) (UHD Blu-ray)

    Profil 8.x (dvhe.08) (rip DV HDR10-compatible)

Ces deux profils garantissent que les lecteurs compatibles Dolby Vision activeront le DV, tandis que les appareils non compatibles basculeront automatiquement sur la couche HDR10.

ATTENTION : Le HDR et DV (Dolby Vision) ne sont pas la même chose !

6) Exemples conformes

    Squid.Game.2021.S01.MULTi.VFF.2160p.WEBRip.4KLight.DV.HDR10.EAC3.Atmos.5.1.x265-ASKO

    Le.Comte.de.Monte.Cristo.2024.VOF.2160p.BluRay.DV.HDR10.TrueHD.Atmos.7.1.x265-ZEKEY

    Miss.Marvel.2022.S01.MULTI.VFF.2160p.WEBRIP.4KLight.DV.HDR10.DDP.ATMOS.5.1.X265-QTZ

4.Le Filtrage

Le filtrage n’est acceptable que s’il reste mesuré et transparent. Toute intervention sur l’image modifie la signature visuelle de la source. Pour cette raison, chaque traitement appliqué doit être explicitement mentionné dans la présentation et le NFO. Un lien vers des comparaisons (ex : slow.pics) est apprécié.
Autorisé

    Filtres de correction d'image : debanding, dehaloing, anti-aliasing, dithering, rescale

    Degrain/Denoise (améliore l'efficacité de compression)

    Post-sharp/contrasharp appliqué par les denoisers

Interdit

    Sharpening excessif

    Altération de la colorimétrie

    Upscale vidéo (ex: DVD 480p vers 1080p)

    Filtres IA (Topaz Video AI, etc.)

Audio

L’audio fait partie intégrante de la qualité perçue. Au-delà du simple “ça s’entend”, il engage la compatibilité des lecteurs, la fidélité du rendu et la cohérence du catalogue. Les règles ci-dessous encadrent donc le codec, le débit, la langue et les exigences minimales attendues.
1. Le Codec

Le choix du codec audio doit être explicitement identifiable dans le nommage. La liste suivante regroupe les écritures admises pour le champ « CodecAudio ». Chaque appellation citée est autorisée.

Lorsque plusieurs pistes audio avec différents codec sont présents au sein du même fichier; le TAG du Codec audio sera choisi en fonction des critères suivants :

    Codecs Lossy : Le TAG de la piste audio VF avec le plus de canaux doit être dans le titre

    Codec Lossless : Le TAG de la piste audio avec le plus de canaux doit être dans le titre, peu importe sa langue (car codec lossless souvent en VO)

PS : si un refus de votre upload venait à se produire pour cette raison, merci de nous faire un ticket upload ;)

Codecs Lossy

Compression qui réduit la taille en supprimant une partie des informations audio, avec une qualité généralement très bonne mais non identique à la source.

    Général / streaming

        AAC : AAC.2.0 / AAC.5.1OPUS : OPUS.2.0 / OPUS.5.1

        VORBIS : VORBIS.2.0

        MP3 : MP3.2.0

    Dolby

        AC3 (Dolby Digital) : AC3.2.0 / AC3.5.1EAC3 / DDP (Dolby Digital Plus) :

            EAC3.2.0 (DDP.2.0)EAC3.5.1 (DDP.5.1)

            EAC3.7.1 (DDP.7.1)

            EAC3.ATMOS.5.1 / EAC3.ATMOS.7.1 (DDP Atmos) → Atmos “lossy” sur base EAC3

        DTS

            DTS (core) : DTS.5.1

Codec Lossless (sans perte)

Compression (ou flux) qui conserve l’intégralité du signal, pour une restitution strictement fidèle à la source, au prix d’un fichier plus volumineux.

DTS

    DTS.HD.MA : DTS.HD.MA.5.1/DTS.HD.MA.7.1

    DTSX : DTSX.7.1

Dolby

    TRUEHD : TRUEHD.5.1 / TRUEHD.7.1

    TRUEHD.Atmos : TRUEHD.ATMOS.7.1

LPCM
2. Bitrate Audio

Le bitrate audio fixe un minimum de lisibilité et évite les pistes sous-compressées qui dégradent fortement l’expérience, en particulier sur les dialogues. Le tableau ci-dessous résume les exigences minimales retenues selon les cas d’usage.

( Tableau en cours de création)
3. Langue des pistes

La langue doit être indiquée sans ambiguïté, car elle conditionne immédiatement la compréhension et la recherche. Les tags suivants sont acceptés pour le champ « Langue » et doivent être utilisés conformément à leur définition.

Lorsqu'il n'y a qu'une seule piste audio mais qu'elle est muette :

    The.Bear.S04.MUET.1080p.WEB.EAC3.5.1.H264-TF

NOTE : s'il y a des sous-titres, la règime des sous-titres reste le même : The.Bear.S04.MUET.VOSTFR.1080p.WEB.EAC3.5.1.H264-TF

Lorsqu'il n'y a qu'une seule piste audio en Français (FR) :

    VOF : Version Officielle Française

        Exemple : The.Bear.S04.VOF.1080p.WEB.EAC3.5.1.H264-TFA

    TRUEFRENCH : Version Française Francophone

        Exemple : The.Incredibles.2004.TRUEFRENCH.1080p.BluRay.DTS.HD.MA.5.1.x264-LOST

    VFF : Version Française Francophone

        Exemple : Lego.Batman.Le.Film.2017.VFF.2160p.BluRay.4KLight.HDR10.AC3.5.1.x265-QTZ

    VFI : Version Française Internationale

        Exemple : The.Mandalorian.S01.VFI.2160p.WEB.HDR10.AC3.5.1.H265-FW

    VFB : Version Française Belge

        Exemple : Twisters.2024.VFB.2160p.WEB.HDR.EAC3.5.1.H265-FW

    VFQ : Version Française Québécoise

        Exemple : Twisters.2024.VFQ.2160p.WEB.HDR.EAC3.5.1.H265-FW

Lorsqu'il y a plusieurs piste audio de langues différentes dans le fichier :

    Présence d'une seule piste FR :

        Le TAG MULTI et la précision de la piste audio FR deviennent obligatoire. Ce TAG n'est valable que si présence d'une piste FR

            Exemple :

                The.Bear.S04.MULTI.VOF.1080p.WEB.EAC3.5.1.H264-TFAThe.Incredibles.2004.MULTI.TRUEFRENCH.1080p.BluRay.DTS.HD.MA.5.1.x264-LOST

                Lego.Batman.Le.Film.2017.MULTI.VFF.2160p.BluRay.4KLight.HDR10.AC3.5.1.x265-QTZ

                The.Mandalorian.S01.MULTI.VFI.2160p.WEB.HDR10.AC3.5.1.H265-FW

                Twisters.2024.MULTI.VFQ.2160p.WEB.HDR.EAC3.5.1.H265-FW

    Présence de plusieurs piste en FR :

        Lorsque VFF et VFQ sont présent alors le TAG MULTI.VF2 est obligatoire

            Exemple :

                Severance.S01.MULTI.VF2.1080p.WEB.EAC3.5.1.H264-FW

Lorsqu'il n'y a aucune piste audio en FR :

Dans ce cas là, le fichier doit alors obligatoirement inclure des sous-titres FR complets pour être qualifié VOSTFR, sinon il est interdit
4. Exigence technique minimales

Ces exigences constituent un socle de qualité, conçu pour assurer une expérience homogène et éviter les pistes audio “dégradées” alors qu’une meilleure piste existe sur la source. Elles s’appliquent indépendamment des préférences individuelles, dans une logique de standard commun.

    Son Stéréo obligatoire sur tout upload (sauf vieux films en Mono)

    Blu-ray Rip HD : piste 5.1 minimum si disponible sur le Blu-ray source

    Release multilingue : piste française en 5.1 minimum si disponible

    Audio MP3 : uniquement pour les vidéos SD

Les Sources

La notion de “source” n’est pas une formalité. Elle renseigne l’origine du master et permet, à elle seule, d’anticiper la qualité attendue, la cohérence du catalogue et les éventuelles contraintes de compatibilité. Pour cette raison, seules les sources clairement identifiables et conformes aux standards du tracker sont admises dans le champ « Source ».

Vous trouverez ici, les source que nous acceptons pour vos uploads, à insérer dans le champs 'Source ' :
1. Plateformes / WEB

    WEB-DL/WEB : Fichier obtenu par extraction ou téléchargement direct depuis une plateforme de streaming, en conservant le flux encodé par le service (audio/vidéo généralement inchangés) (H264 / H265). C’est, en pratique, la forme la plus “proche de la source” côté WEB.

    WEBRip : Fichier dérivé d’une source WEB mais passé par un rip ou une recompression (capture, ré-encodage, transcodage ou extraction non bit-perfect) (x264 / x265). La qualité dépend fortement de la méthode et peut varier d’excellente à médiocre.

Précision sur la qualification de WEB-DL/WEB

Afin d'éviter tout WEBrip qui se ferait passer pour du WEB-DL/WEB et protéger le "Label" WEB-DL/WEB, nous adoptons une approche strictes en trois étapes afin de l'identifier.

Lorsque le TAG WEB/WEB-DL est présent dans la release, voici comment la TP procède :

    Vérification de la présence de la mention untouched dans le NFO :

        Si présent -> WEB/WEB-DL

        Si absent -> Passage à l'étape suivante

    Vérification de la présence d'un moteur d'encode (x264, x265) dans le NFO :

        Si présent -> Passage à l'étape suivante

        Si absent -> WEB/WEB-DL

    Vérification de la légitimité de Plateforme VOD source du WEB-DL/WEB par la mention dans la description

        Si Plateforme VOD officielle -> WEB/WEB-DL et utilisation du moteur d'encode dans le titre à la place du codec (x265,x264)

        Si Plateforme VOD non officielle -> Requalification en WEBRIP

        Si Absence de la mention de Plateforme VOD-> Refus de la TP

2. Télévision / Diffusion

    HDTV : Enregistrement d’une diffusion télévisée en haute définition (TNT, câble, satellite, IPTV légitime), généralement avec les paramètres et contraintes de la diffusion (logos, coupures pub possibles, débit variable).

    PDTV / SDTV : Enregistrement d’une diffusion TV en définition standard. “PDTV” désigne souvent une source TV numérisée/encodée proprement mais en SD ; “SDTV” est un terme plus générique pour la TV SD, avec une qualité globalement inférieure à la HD.

À l'upload : les captures TV (TVRip) sont acceptées sous l'appellation SDTV. Le token TVRip seul est refusé par le formulaire : choisissez SDTV comme source et gardez la qualité d'origine.

3. Disques et supports officiels

Bluray

Les sources de d'encodage BluRay

Ces sources sont celles utilisées dans le titre de la release lors d'un encodage.

    BluRay : Source issue d’un Blu-ray commercial (1080p), réputée stable et qualitative (bitrate plus élevé, pistes audio souvent meilleures que le WEB).

    UHD.BluRay : Source issue d’un Blu-ray Ultra HD (2160p), souvent associée à HDR (HDR10, Dolby Vision selon les cas) et à des pistes audio premium.

Les structure de BluRay sans réencodage (untouched)

Lorsque la source BluRay est pure (=lorsque la release n'est pas un encodage) elle doit obligatoirement être suivie de l'un des deux TAG suivant, qui vise à préciser la structure de la source, dans le titre de la release, en complément de la source BluRay (classique ou UHD)

    BDMV : Arborescence complète d’un Blu-ray (structure de disque : dossiers, playlists, métadonnées). C’est le “disque” tel quel, non remuxé.

        Exemple de nommage :

            WALL.E.2008.MULTI.VFF.2160p.UHD.BluRay.BDMV.DV.HDR10PLUS.TrueHD.7.1.HEVC-NOTAG

            WALL.E.2008.MULTI.VFF.1080p.BluRay.BDMV.DTS.5.1.AVC-NOTAG

    ISO : image disque bit-à-bit d’un Blu-ray / UHD Blu-ray.

        Exemple de nommage :

            WALL.E.2008.MULTI.VFF.2160p.UHD.BluRay.ISO.DV.HDR10PLUS.AC3.5.1.HEVC-NOTAG

            WALL.E.2008.MULTI.VFF.1080p.BluRay.ISO.DTS.5.1.AVC-NOTAG

    REMUX : Reconditionnement “sans perte” d’un Blu-ray/UHD : on copie les flux audio/vidéo tels quels (pas de ré-encodage) dans un conteneur MKV, en conservant la qualité et les pistes choisies.

        Exemple de nommage :

            WALL.E.2008.MULTI.VFF.2160p.UHD.BluRay.REMUX.DV.HDR10PLUS.TrueHD.7.1.HEVC-NOTAG

            WALL.E.2008.MULTI.VFF.1080p.BluRay.REMUX.DTS.5.1.AVC-NOTAG

DVD

    DVD : Source issue d’un DVD commercial (SD, typiquement 480p/576p), avec les limites du format (compression, définition, parfois interlacing).

    VIDEO_TS : structure complète DVD.

    DVDRip : rip ré-encodé depuis DVD (qualité variable, parfois accepté surtout pour anciens contenus).

Le reste est interdit, nous restons à l'écoute si vous avez des exceptions, nous verrons au cas par cas ;)
Les Sous-titres

Le sous-titrage n’est pas un simple “bonus” de confort. Il conditionne l’accessibilité d’une release, sa compréhension immédiate et, pour un tracker francophone, la cohérence même du catalogue. Les règles qui suivent visent donc à encadrer la langue, la qualité et la présentation des sous-titres de manière uniforme.
1. Langue

Lorsque la release n'a aucune piste audio en VF, alors elle doit obligatoirement avoir des sous-titres en VF complets (on est un tracker FR quand même) et la mention VOSTFR dans le titre devient obligatoire (la mention se fait à la place de "Langue").

Exception : Les concerts n'ont pas besoin d'avoir de pistes et de sous-titres en VF

Exemple : Sentenced.To.Be.A.Hero.S01E01.VOSTFR.1080p.WEBRip.AAC.2.0.x264-NOTAG

Néanmoins il existe différent type de VOSTFR, en fonction de leur auteur, pour cela lorsque les sous-titres ne sont pas officiel , il convient de les qualifier des manières suivantes :

    FANSUB : Sous-titres réalisé par des fans dévoués et consciencieux

        Exemple : Sentenced.To.Be.A.Hero.S01E01.VOSTFR.FANSUB.1080p.WEBRip.AAC.2.0.x264-NOTAG

    FASTSUB : Sous-titres produit rapidement afin de permettre une release rapide (souvent pour respecter un rythme, ou pour être le plus rapide à proposer la release) au détriments de la qualité des ST

        Exemple : Sentenced.To.Be.A.Hero.S01E01.VOSTFR.FASTSUB.1080p.WEBRip.AAC.2.0.x264-NOTAG

INTERDIT : Sous-titres par traduction automatique

Rappel : Pas de besoin de préciser lorsqu'il s'agit des ST officiels, VOSTFR suffit !
2. Format

Afin d’assurer une compatibilité maximale et une lisibilité constante, certains formats de sous-titres sont à privilégier. Les standards ci-dessous constituent la référence attendue pour les encodes et facilitent la validation comme l’usage au quotidien.

Format recommandé pour encodes :

    SRT en UTF-8

    PGS

    ASS

IMPORTANT : Films/Séries/Anime sans piste audio en VF ont l'obligations d'avoir des sous-titres FR complets obligatoires

Précisions concernant les muxers

La politique de sous-titrage vise à garantir une lecture immédiate, homogène et durable. Pour cette raison, le tracker privilégie une intégration propre des sous-titres directement au fichier vidéo, ainsi qu’une traçabilité claire lorsque vous intervenez sur une release existante.

Les sous-titres doivent obligatoirement être muxés avec la vidéo, si vous muxez des sous-titres à une release merci de respecter les consignes suivantes :

    Ne pas laisser le tag d'origine, mettre le vôtre ou "NoTag"

    Mentionner le nom original de la release dans le NFO et/ou présentation

    Si le pack contient ≤ 10 épisodes, tous doivent être listés dans le NFO

3. Type de sous-titrage

Au-delà de la langue et du format, il est essentiel d’indiquer la nature du sous-titrage. Cette précision évite les malentendus, puisqu’un sous-titre “forcé” ne couvre pas le même besoin qu’un sous-titrage complet, et qu’un SDH répond à des exigences d’accessibilité spécifiques.

    Complets/FULL : traduisent l’intégralité des dialogues (et parfois certaines indications utiles) sur tout le programme.

    Forcés/Forced : n’affichent que les passages indispensables (langue étrangère, texte à l’écran, répliques non traduites), même si les sous-titres sont désactivés.

    SDH : sous-titres pour sourds et malentendants, incluant dialogues + indications sonores (bruits, musique, ambiance) et parfois l’identification des locuteurs.

Politique des doublons

La politique des doublons vise à préserver un catalogue lisible et à concentrer le seed sur les versions réellement utiles. Sans cette discipline, les mêmes contenus se multiplient sous des variations mineures, ce qui fragmente les téléchargements et affaiblit la disponibilité à long terme. Les règles ci-dessous permettent donc de distinguer ce qui relève d’un apport réel de ce qui constitue une redondance.

Ces règles reposent sur un principe de priorité et un système de slots prédéfinis.
1. Le Principe de Priorité

La notion de priorité implique qu’en présence d’une version plus conforme au profil de référence, la déclinaison la moins pertinente est retirée, afin de préserver le seed, limiter la fragmentation et maintenir l’uniformité du catalogue.

Priorité générales :

    Lorsque deux releases sont en tout points identique, la règle de l'antériorité s'applique ( la plus récente ne sera pas accepté)

        Si les Torrents ont été ajouté en même temps, alors uniquement le torrent avec le plus de seed sera conservé

    Les versions correctives sont prioritaires et ont vocation à remplacer la release initiale concernée. Ainsi, si une team publie une release puis publie ensuite une version corrigée (ex. REPACK) de cette même release, la première version sera retirée afin de ne conserver que la version corrigée. Sont considérées comme versions correctives prioritaires :

        PROPER

        REAL PROPER

        REPACK

        FIX

        RERIP

        v2

NOTE : Les versions correctives doivent obligatoirement préciser les corrections apportés dans le NFO
2. Le système de slots

Pour chaque release, l'ensemble des versions acceptées est défini à l'avance sous la forme de 28 slots (emplacements), répartis en 4 profils correspondant à quatre usages :

    Compatibilité (2 slots) : lecture directe partout (1080p, H.264, audio lossy).

    Home Cinéma Pure (7 slots) : versions sans encodage (REMUX, BDMV, ISO), audio lossless prioritaire.

    Home Cinéma Optimisé (12 slots) : encodage de haute qualité (H.265, AV1), Dolby Vision et lossless quand ils sont disponibles.

    Optimisation (7 slots) : compromis taille/qualité (H.265, audio lossy).

Un upload est accepté s'il correspond à un slot libre, ou s'il est prioritaire sur l'occupant actuel d'un slot. Quand un slot est occupé, la comparaison suit toujours le même ordre : la langue d'abord (MULTI.VF2 > VF2), puis la résolution, la source, le type audio (lossless/lossy), le codec vidéo, les canaux audio, le codec audio et enfin le HDR. La plupart de ces critères sont contextuels au slot visé : chaque slot définit son critère principal et ses valeurs de repli. Par exemple, le profil Optimisation privilégie le HDR10 : le Dolby Vision y est accepté en repli, mais ne remplace jamais un HDR10.

Coexistences : dans trois cas, deux versions peuvent occuper le même slot :

    VFF + VFQ (temporaire) : en l'absence de version VF2 ou MULTI.VF2, une version VFF et une version VFQ coexistent jusqu'à ce qu'une version qui les rassemble existe.

    HDR + DV séparés (temporaire) : en l'absence de version combinée DV.HDR10 ou DV.HDR10+, une version HDR et une version DV coexistent jusqu'à ce qu'une version combinée existe.

    Lossy + Lossless (permanente) : il ne s'agit pas d'un ordre de priorité entre deux versions. Une version lossless et une version lossy du même slot coexistent durablement : aucune version ne peut les rassembler, et aucune ne remplace l'autre.

Conditions WEBRip : un WEBRip n'est accepté que si son poids est strictement inférieur à celui du WEB-DL existant et du BluRay existant de même résolution. Exception : si le WEBRip apporte une meilleure langue que la version existante, il est accepté même s'il est plus lourd (l'excédent de poids est justifié par les pistes audio supplémentaires). Le nombre de pistes audio n'est pas un critère bloquant. Les torrents importés sans taille connue (imports historiques) ne sont pas soumis à ces vérifications de poids.

La liste détaillée des 28 slots (critères, sources, priorités et valeurs de repli de chaque slot) est décrite sur la page Guide des slots, qui constitue la référence. En cas de divergence entre cette page et le guide, le guide prévaut.
3. Exceptions

Ne sont pas des doublons à la releases initiale :

    Saison complète quand seuls des épisodes existent

    Version avec nouvelle piste audio VO/FR absente du tracker

    Les Versions spéciales :

        UNCUT

        THEATRICAL

        EXTENDED

        DIRECTOR'S CUT / DC

        IMAX

        Open Matte

        Hybrid

        AD (Audio Description)

        3D (variantes FSBS / HSBS)

INTERDICTION

Cette section regroupe les interdictions majeures. Elle vise à préserver la lisibilité du catalogue, à éviter l’introduction de sources dégradées ou trompeuses, et à empêcher les publications qui nuisent à la qualité globale ou fragmentent inutilement le seed.
1. Sources et qualité

Certaines sources, par nature, ne répondent pas aux standards attendus. D’autres pratiques altèrent artificiellement la qualité ou reposent sur des transcodages qui dégradent le fichier sans apporter de valeur. Les cas suivants sont donc exclus.

    Vidéos CAM, TS, SCR, MD, DVDSCR

    Vidéos avec REF < 3 (tolérance à REF 2 pour HDTV/WEB uniquement)

    Encodes depuis DVD (sauf vieux anime en LD/DVDRip sans alternative)

    Encodes depuis une autre encode (uniquement depuis source pure : Blu-ray, remux...)

    Upscales ou transcodages vers résolution/codec supérieur

    Vidéos YouTube, Dailymotion, RuTube (sauf tutoriels ou émissions exclusives)

    Transcodages ou optimisations "Plex"

2. Formats

Au-delà du contenu, certains formats empêchent une exploitation correcte, nuisent à la pérennité ou compliquent la validation. Pour garantir une structure propre et un usage immédiat, les formats suivants ne sont pas admis.

    Formats archive : RAR, ZIP, 7z

    Formats vidéo interdits : WMV, MOV, SWF, FLV, RM

    Sous-titres incrustés (sauf si d'origine diffuseur ou anime)

3. Contenu

Le tracker n’a pas vocation à héberger des contenus ambigus, dégradés ou éditorialement incohérents. Les interdictions ci-dessous visent à écarter les publications qui nuisent à la lisibilité du catalogue ou à l’expérience des peers.

    DVD/Blu-ray non officiels ou Bootlegs

    Vidéos avec watermarks ou textes défilants gênants

    Vidéos ou montages amateurs

    Plusieurs épisodes encodés dans un seul fichier (sauf diffusion officielle)

    Saisons incomplètes : c'est soit un épisode, une saison, ou une intégrale

    Les films encore en salle sont strictement interdits

4. Multi-format et multi-tag

Pour éviter les packs hétérogènes, difficiles à automatiser et nuisibles au seed, le tracker impose une cohérence stricte. Un pack doit rester uniformément qualifié, tant sur ses caractéristiques techniques que sur son origine.

    Multi-format interdit : tous les fichiers d'un pack doivent avoir la même qualité (format, résolution, codec, langue, source, bitrate)

    Multi-tag interdit : tous les fichiers doivent provenir du même encodeur/team

Dérogations possibles

Une dérogation peut être accordée pour :

    Vieux films/séries si résolution ou bitrate audio inférieur aux minimums requis et qu'aucune meilleure qualité n'existe

    Multi-tag ou multi-format sur séries très longues (anime) dont les teams ont changé
