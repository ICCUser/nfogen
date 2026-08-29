# Automatisation upload — Du gap détecté au torrent en seed

Objectif de fond (formulé par l'utilisateur, 2026-08-27) : éliminer le
travail manuel entre "je remarque qu'un média manque sur le tracker" et
"il est en seed, uploadé". Contrainte de résilience : si C411 disparaît un
jour (comme ygg), seul un nouveau **profil** (règles + templates) doit
être à créer — le reste du pipeline (accès aux fichiers, génération,
détection de gap) doit rester agnostique du tracker.

Ce fichier documente la conception du pipeline complet ; `GAPSCAN.md`
documente la détection de gap elle-même (déjà livrée), ce fichier prend le
relais pour tout ce qui vient après.

## Principe directeur : agnostique du tracker (comme Prowlarr pour Radarr/Sonarr)

Rappel explicite (utilisateur, 2026-08-27) : multi-tracker à terme, **sans
sacrifier la fonctionnalité pour autant** — même logique que Radarr/Sonarr,
qui ne parlent jamais directement à un tracker : c'est Prowlarr qui
absorbe la diversité des indexeurs (définitions par indexeur) et n'expose
à Radarr/Sonarr qu'une interface unique standardisée (Torznab). Seul le
**profil** doit rester la pièce qui connaît un tracker en particulier —
exactement le principe déjà appliqué à la génération de NFO (`rules.json`
+ templates par profil, cœur agnostique, voir README.md).

**Où c'est déjà vrai aujourd'hui** : la recherche (`c411_client.py`) parle
Torznab standard — le protocole que parlent déjà Prowlarr/Sonarr/Radarr/
Jackett (voir GAPSCAN.md). Rien dans `_search()`/`search_movie()`/
`search_tv()` n'est spécifique à C411 ; seul `base_url` (déjà configurable)
distingue une instance C411 d'un autre indexeur Torznab. Le nommage
(`C411Client`, `C411Release`, `c411_client.py`) est donc trompeur — il
laisse penser à du code spécifique alors que ce n'est déjà pas le cas.
Renommage en `TorznabClient` à envisager (change de nature aucun
comportement, juste rend l'agnosticisme déjà réel explicite) — pas
urgent, mais peu coûteux le jour où un deuxième tracker Torznab entre en
jeu.

**Où ça ne l'est PAS encore** : contrairement à la recherche, il n'existe
**aucun standard équivalent à Torznab pour l'upload** — catégories,
format de description, règles de taille de pièce, méthode d'auth
(passkey vs clé API vs autre) varient d'un tracker à l'autre sans
convention commune. C'est le vrai défi des sous-projets 3 (nommage) et 4
(upload) : il faudra concevoir une extension déclarative du profil
existant (catégories, gabarit de requête d'upload, contraintes de
génération de torrent) plutôt que du code Python câblé par tracker — à
traiter explicitement quand ces sous-projets seront détaillés, pas
supposé résolu par analogie avec Prowlarr.

## Décomposition et ordre (2026-08-27)

Projet trop large pour une seule conception : découpé en 8 sous-projets
indépendants, chacun avec son propre cycle conception → implémentation.
Ordre confirmé par l'utilisateur (le sous-projet 3 a été ajouté le
2026-08-27, en cours de route, quand `name_proposal.py` s'est révélé
moins agnostique que supposé — voir sa section pour le contexte) :

| # | Sous-projet | État |
|---|---|---|
| 1 | Accès NAS en lecture seule (résolution de chemins Sonarr/Radarr → chemin local) | **Livré (2026-08-27)**, voir [le plan](docs/superpowers/plans/2026-08-27-gapscan-nas-path-resolution.md) |
| 2 | Mise en scène du fichier (hardlink/copie) + génération du `.torrent` | **Livré (2026-08-27)**, voir [le plan](docs/superpowers/plans/2026-08-27-automation-staging-torrent.md) |
| 3 | Rendre `name_proposal.py` agnostique du tracker (source/codecs déclaratifs) | **Livré (2026-08-27)**, voir [le plan](docs/superpowers/plans/2026-08-27-name-proposal-agnostic.md) |
| 4 | Orchestration du nommage → mise en scène + `.torrent` (utilise les sous-projets 2 et 3) | **Livré (2026-08-28)**, voir [le plan](docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md) |
| 5 | Upload vers C411 | À concevoir |
| 6 | Intégration qBittorrent (récupération du `.torrent` signé, mise en seed) | À concevoir |
| 7 | File d'attente un-par-un + email (succès/erreur) + règles de résolution automatique pilotées par le profil | À concevoir |
| 8 | Lidarr (musique) | Facultatif, en dernier |

## Décisions déjà prises (2026-08-27)

| Sujet | Décision |
|---|---|
| Fichier média source | **Jamais modifié, jamais déplacé/renommé.** Lecture seule stricte — le renommer casserait le suivi de chemin de Sonarr/Radarr/Lidarr ("film inexistant"). Seuls le `.torrent` et le `.nfo` (fichiers neufs) sont nommés selon la convention du tracker. |
| Où nfogen tourne vs où tournent Sonarr/Radarr | Pas forcément le même hôte/conteneur. Un mapping de chemins est nécessaire (voir sous-projet 1) — même principe que "Remote Path Mappings" dans Sonarr/Radarr eux-mêmes. |
| Hardlink vs copie | Détection **automatique** : tente `os.link()`, capture `EXDEV` (périphériques différents), bascule sur une copie dans ce cas. Pas besoin de déclarer la topologie à l'avance ; gère aussi une bibliothèque pas uniformément sur un seul montage. Option de forcer la copie manuellement conservée. |
| Seed à travers un lien lent (VPN site-to-site, etc.) | Explicitement écarté. Seul le transfert initial (une fois) peut passer par un lien lent ; jamais le service continu aux peers. |
| Génération du `.torrent` | Taille de pièce par barème (voir règles C411 ci-dessous), passkey jamais journalisée/exposée (même discipline que la clé API C411 dans `c411_client.py`), flags "seed immédiatement" + "tracker privé" obligatoires. |
| Upload | **Un par un, jamais en lot** — choix délibéré de l'utilisateur comme garde-fou, même si son rang C411 autoriserait le lot. |
| Après upload | C411 renvoie un `.torrent` **re-signé par eux** — c'est CE fichier-là qui doit être chargé dans qBittorrent pour seed, pas celui généré localement. |
| Email | Succès → minimal ("prêt à envoyer, confirme ?"), rien de plus. Erreur → détail complet de l'erreur inclus. |
| Résolution automatique de champs ambigus (ex. "French" générique → VFF) | Doit être pilotée par les règles du **profil** (pas de logique Python câblée en dur par tracker) — cohérent avec l'architecture existante (profils déclaratifs, cœur agnostique). Explicitement signalé comme le point le plus délicat par l'utilisateur ; pas résolu dans cette conception. |
| Lidarr | Confirmé voulu, mais explicitement facultatif — construit en dernier. |

### Règles C411 de création de torrent (copiées par l'utilisateur, 2026-08-27)

Barème taille de pièce (jamais "Auto" — un `.torrent` de plus de 16 Mo
risque d'être rejeté/mal géré) :

| Poids du fichier | Taille des pièces |
|---|---|
| < 1 Go | 1 Mo |
| < 2 Go | 2 Mo |
| < 3 Go | 4 Mo |
| < 8 Go | 8 Mo |
| > 8 Go | 16 Mo |

L'adresse d'annonce privée contient la passkey de l'utilisateur — aussi
sensible qu'une clé API, jamais à journaliser/exposer. Cocher "commencer à
seeder" + "tracker privé" à la création. Après soumission sur `/upload`
(catégorie + description, éventuellement auto-remplie par l'assistant TMDB
de C411), le torrent passe par une modération humaine ("Team Pending")
avant d'être public — atténue (sans l'annuler) le risque d'automatiser
cette étape.

## Sous-projet 1 : Accès NAS en lecture seule (résolution de chemins)

**But** : étant donné un fichier connu de Sonarr/Radarr (via leur API),
obtenir un chemin que le process nfogen peut réellement ouvrir en lecture
— que nfogen tourne sur la même machine qu'eux ou non.

**Constat** : `RadarrClient.list_movie_files()`/`SonarrClient.list_season_files()`
n'extraient aujourd'hui AUCUN chemin de fichier (`path`/`relativePath` des
API Radarr/Sonarr) — GapScan n'en a jamais eu besoin, seulement des
métadonnées de comparaison. Premier changement nécessaire : extraire ce
champ.

**Conception** :

1. **Extraction du chemin brut** : `RadarrMovieFile`/`SonarrSeasonFile`
   gagnent un champ `remote_path: Optional[str]` (`movieFile.path` /
   `episodeFile.path`, tel que rapporté par Sonarr/Radarr).
2. **Table de mapping, par connexion** (Sonarr et Radarr ont chacun la
   leur, comme leurs propres "Remote Path Mappings") : liste de paires
   `{remote_prefix, local_prefix}`, stockée dans `gapscan_config_store.py`
   (mêmes principes que l'existant : fichier JSON, `chmod 600`, `PUT`
   partiel). Vide par défaut = chemins identiques des deux côtés (cas
   swizzin actuel de l'utilisateur).
3. **Résolution** : préfixe le plus long de la table qui correspond au
   `remote_path`, substitué par le préfixe local correspondant. Sans
   correspondance dans la table (vide ou aucun préfixe ne matche) :
   `remote_path` est utilisé tel quel (comportement actuel implicite,
   déploiement à chemins identiques).
4. **Validation à chaque scan GapScan** (décision utilisateur, pas
   seulement au moment de préparer un upload) : après résolution, on
   vérifie que le chemin résolu existe et est lisible. Résultat exposé
   sur `GapResult` (nouveaux champs `local_path: Optional[str]`,
   `path_resolved: bool`, `path_error: Optional[str]`) — un mapping cassé
   se voit dès le scan suivant, pas seulement en pleine préparation d'un
   upload.
5. **Alternative écartée** : détection automatique du bon chemin local
   (recherche par taille/hash sur un répertoire racine configuré) — trop
   fragile (lent sur une grosse bibliothèque, ambigu en cas de fichiers de
   taille identique) pour un gain marginal face à une config manuelle que
   l'utilisateur maîtrise déjà via Sonarr lui-même.

**Pas encore tranché / pour la suite** : lecture effective du fichier
(ouverture, streaming pour le hash de pièces) appartient au sous-projet 2,
pas à celui-ci — le sous-projet 1 se limite à "obtenir et valider un
chemin local exploitable".

**Livré (2026-08-27)** — écarts par rapport à la conception ci-dessus,
découverts pendant la planification/implémentation :

- La table de mapping est un simple `dict[str, str]` (`{prefixe_distant:
  prefixe_local}`), pas une liste de `{remote_prefix, local_prefix}` —
  plus simple, et réutilise directement `KeyValueEditor` (déjà générique)
  côté frontend sans transformation.
- `SonarrSeasonFile` expose `remote_paths: list[str]` (pluriel — une
  saison est intrinsèquement multi-fichiers), pas un `remote_path`
  singulier comme pour `RadarrMovieFile`. `GapResult` reflète ça
  uniformément avec `local_paths: list[str]` (une entrée pour un film,
  N pour une saison).
- Résolution/validation implémentées dans un module dédié
  `nfogen/path_mapping.py` (`resolve_path`/`resolve_and_validate`), pas
  directement dans `gapscan.py` — logique pure, testable sans mock
  filesystem lourd.
- La validation "à chaque scan" s'applique aussi aux titres dont le
  verdict C411 est repris tel quel en mode incrémental : `scan_movie`/
  `scan_series_season` recalculent toujours `local_paths`/`path_resolved`/
  `path_error` avant de décider s'il faut réinterroger C411, et
  utilisent `dataclasses.replace()` pour ne rafraîchir QUE ces 3 champs
  sur un résultat par ailleurs repris — un scan incrémental ne raccourcit
  donc jamais la vérification de chemin, seulement l'appel réseau à C411.

Voir le plan d'implémentation complet (10 tâches TDD, code exact) :
[docs/superpowers/plans/2026-08-27-gapscan-nas-path-resolution.md](docs/superpowers/plans/2026-08-27-gapscan-nas-path-resolution.md).

## Sous-projet 2 : Mise en scène du fichier (hardlink/copie) + génération du `.torrent`

**But** : étant donné les chemins locaux résolus par le sous-projet 1
(`GapResult.local_paths`) et un nom de sortie voulu, préparer le(s)
fichier(s) sans jamais toucher à l'original, puis produire un `.torrent`
conforme aux règles C411 (barème de taille de pièce, flag privé, adresse
d'annonce).

**Décisions (2026-08-27)** :

- **Bibliothèque** : [`torf`](https://github.com/rndusr/torf) (pure
  Python). Écarté `libtorrent` (bindings C++ de qBittorrent — plus
  "authentique" mais lourd à installer/compiler sur le swizzin, le genre
  de friction déjà rencontrée avec npm/pip sur ce serveur) et un encodeur
  bencode maison (risque de bugs subtils). API vérifiée directement dans
  le code source de `torf` : `Torrent(path=, trackers=, private=,
  piece_size=)`, `piece_size` doit être un multiple de 16 Kio (toutes les
  valeurs du barème C411 le sont), `path` accepte un fichier OU un
  dossier (donc un pack de plusieurs épisodes fonctionne en pointant sur
  un sous-dossier), `.generate()` calcule les hashs, `.write(chemin)`
  écrit le fichier.
- **Secret séparé de la clé API** : le "passkey" C411 (lié au compte, un
  seul existe, le régénérer casse TOUS les seeds en cours — donc à
  manipuler avec la même prudence qu'un secret à fort impact) est stocké
  comme `c411_announce_url` : l'**URL d'annonce privée complète**, copiée
  telle quelle depuis le profil C411, pas juste le passkey brut — nfogen
  n'a pas besoin de connaître/reconstruire le format d'URL du tracker.
  Mêmes principes que le reste de `gapscan_config_store.py` (jamais
  renvoyé en clair par `GET`, `chmod 600`).
- **Dossier de mise en scène** : un seul `staging_dir` configuré une fois
  (pas par connexion Sonarr/Radarr comme les mappings de chemins — c'est
  un dossier propre à nfogen, pas une bibliothèque tierce), sur le même
  système de fichiers que les médias (nécessaire pour le hardlink).
- **Nommage différé au sous-projet 3** : ce sous-projet accepte le nom de
  sortie voulu en paramètre explicite (fourni par l'appelant) plutôt que
  de le calculer — reste testable dès maintenant sans dépendre du
  sous-projet 3.
- **Hardlink avec repli automatique sur copie** : réutilise exactement la
  détection déjà décidée (tente `os.link()`, capture `EXDEV`, bascule sur
  une copie) — voir "Décisions déjà prises" plus haut.

**Conception** :

1. **`nfogen/file_staging.py`** (nouveau, pur filesystem) :
   `stage_file(source_path, target_path)` (un hardlink ou une copie) et
   `stage_files(source_paths, target_dir, names)` (plusieurs fichiers d'un
   coup, pour un pack de saison — un nom par source, même ordre).
2. **`nfogen/torrent_builder.py`** (nouveau, utilise `torf`) :
   `piece_size_for(total_bytes) -> int` (barème C411, fonction pure,
   testable sans I/O) et `build_torrent(staged_path, announce_url,
   output_path)` qui construit et écrit le `.torrent` (privé, piece_size
   du barème, un seul tracker).
3. **Config** : `gapscan_config_store.py` gagne `c411_announce_url` et
   `staging_dir` (mêmes principes que l'existant).

**Nouvelle dépendance** : `torf`, dans un extra pip dédié `automation`
(pas `gapscan` — GapScan seul n'en a pas besoin, garde son empreinte
minimale pour qui veut juste détecter des gaps sans automatiser
l'upload).

**Pas encore tranché / pour la suite** : structure de dossier exacte pour
un pack multi-fichiers dans `staging_dir` (un sous-dossier par upload,
nommé comment) — dépend du nommage réel, calculé au sous-projet 3.

**Livré (2026-08-27)** — conforme à la conception, aucun écart notable.
Point de vérification a posteriori : l'API réelle de `torf` a été
vérifiée dans son code source avant d'écrire `torrent_builder.py`
(`Torrent(path=, trackers=, private=, piece_size=)`, `piece_size`
multiple de 16 Kio — toutes les valeurs du barème C411 le sont —,
`path` accepte un fichier ou un dossier, `.generate()`/`.write()`/
`.read()` classmethod) plutôt que supposée, pour éviter d'écrire un
module contre une API imaginée. `file_staging.py`/`torrent_builder.py`
sont testés et fonctionnels mais **pas encore appelés** depuis un flux
utilisateur — ils attendent le sous-projet 3 (nommage réel) pour être
orchestrés ensemble.

Voir le plan d'implémentation complet (7 tâches TDD, code exact) :
[docs/superpowers/plans/2026-08-27-automation-staging-torrent.md](docs/superpowers/plans/2026-08-27-automation-staging-torrent.md).

## Sous-projet 3 : Rendre `name_proposal.py` agnostique du tracker

**Contexte** : en préparant la conception du nommage pour l'automatisation
(devenu le sous-projet 4), relecture de `nfogen/name_proposal.py` — déjà
utilisé par la page "Générer" et la CLI (`nfogen --propose-name`), donc
pas un module neuf pour l'automatisation, mais le cœur même de
l'application de base. Retour utilisateur (2026-08-27) : "il a été fait
sûrement à la va-vite... je te conseille de le reprendre et de faire en
sorte qu'il soit le plus neutre possible." Vérifié en le lisant : exact.

**Constat (déjà à moitié agnostique)** :
- **Déjà déclaratif** (piloté par `rules.json -> video -> name_proposal`,
  aucun code à toucher pour un nouveau tracker) : le gabarit final
  (`template.format(**fields)`) et les alias de langue
  (`language_aliases`).
- **Câblé en dur en Python** (donc impossible à adapter sans toucher au
  code pour un futur tracker) : la liste des sources reconnues ET leur
  normalisation exacte dans le nom final (ex. `"bdremux"` → toujours
  `"BluRay.REMUX"`, jamais autre chose), la casse imposée sur le codec
  vidéo (toujours minuscule) et le codec audio (toujours majuscule).

**Décision (2026-08-27)** — arbitrage entre agnosticisme et sur-ingénierie
sans un second tracker réel pour valider une abstraction complète :

- **Passe en config** (`rules.json`), même mécanisme que `language_aliases`
  (le plus long alias qui correspond l'emporte, insensible à la casse) :
  `source_aliases`, `video_codec_aliases`, `audio_codec_aliases`. Un
  tracker différent de C411 peut vouloir une casse/orthographe/liste de
  sources différente — c'est désormais un changement de `rules.json`, pas
  de code.
- **Reste câblé en Python** (conventions jugées quasi universelles dans
  l'écosystème des trackers, confirmé par l'utilisateur — "si la plupart
  des trackers utilisent ces deux conventions, vas-y, les hors piste on
  s'en fout") : détection résolution (`1080p`), saison/épisode
  (`S01E01`), année, et position du tag d'équipe (`-TEAM` en fin de nom).
  Si un futur tracker casse vraiment l'une de ces deux hypothèses, à
  sortir en config à ce moment-là — pas avant, deviner sans un cas réel
  produirait une abstraction mal calibrée.

**Conception** :

1. **`nfogen/name_proposal.py`** : remplace `_SOURCE_RE`/`_SOURCE_ALIASES`,
   `_VIDEO_CODEC_RE`, `_AUDIO_CODEC_RE` par un mécanisme générique unique
   `_detect_via_aliases(text, aliases) -> str` (le plus long alias
   présent dans `text`, insensible à la casse, sinon chaîne vide) —
   réutilisé pour la langue (déjà existant, migré vers cette fonction
   commune), la source, le codec vidéo, le codec audio. Réduit aussi la
   duplication de code entre les quatre détections.
2. **`nfogen/profiles/c411/rules.json`** : `name_proposal` gagne
   `source_aliases`/`video_codec_aliases`/`audio_codec_aliases`, peuplés
   pour reproduire **exactement** les sorties actuelles (aucun changement
   de comportement pour C411 — seule la provenance du savoir change,
   Python → JSON).
3. **Tests** : `tests/test_name_proposal.py` migre son `CONFIG` de test
   pour inclure les nouveaux alias (sinon la détection source/codec ne
   trouve plus rien, ces champs dépendaient jusqu'ici du câblage Python
   retiré).

**Pas dans ce sous-projet** (delta volontairement laissé de côté, YAGNI) :
- Détection résolution/saison-épisode/année/équipe rendue configurable —
  voir "Décision" ci-dessus.
- Un mécanisme de canonicalisation croisée entre orthographes de codec
  différentes (ex. unifier `h264`/`avc`/`x264` vers une seule sortie) :
  aucun test actuel ne l'exige, laissé en `passthrough` (chaque alias
  reconnu se normalise vers lui-même, casse mise à part) — un profil
  peut choisir d'unifier ça lui-même dans ses propres `*_aliases` s'il le
  souhaite, sans changement de code.

**Livré (2026-08-27)** — un écart par rapport au plan initial : livré en
**un seul commit**, pas deux comme prévu. Trouvé à l'exécution que
`tests/test_api.py` (`POST /propose-name`) exerce le **vrai** profil C411
de bout en bout, pas seulement le `CONFIG` isolé de
`tests/test_name_proposal.py` — le refactor seul (avant de peupler
`rules.json`) cassait donc réellement 2 tests existants, pas juste
temporairement "en attente" d'une deuxième tâche. Jamais commité dans cet
état intermédiaire. Comportement final vérifié identique à l'ancien via un
check de bout en bout (même sortie exacte sur un cas réel, One Piece S01)
en plus de la suite de tests existante, inchangée dans ses assertions.

Voir le plan d'implémentation complet (code exact, alias reproduits un
par un) : [docs/superpowers/plans/2026-08-27-name-proposal-agnostic.md](docs/superpowers/plans/2026-08-27-name-proposal-agnostic.md).

## Sous-projet 4 : Orchestration du nommage → mise en scène + `.torrent`

**But** : étant donné des chemins locaux déjà résolus (sous-projet 1,
`GapResult.local_paths`), calculer le(s) nom(s) de release (sous-projet 3),
mettre en scène les fichiers et générer le(s) `.torrent` (sous-projet 2) —
sans jamais rien committer sur disque avant confirmation explicite.

**Décisions (2026-08-28)** :

- **Deux étapes séparées, jamais fusionnées** : `preview_upload()` (lecture
  seule — extraction MediaInfo + calcul des noms + avertissements, aucune
  écriture disque) puis `commit_upload()` (mise en scène + `.torrent`, un
  groupe à la fois). Nécessaire parce que la mise en scène crée de vrais
  fichiers et que la génération de `.torrent` hash tout le contenu
  (potentiellement lent) — l'utilisateur doit pouvoir voir le résultat
  avant d'engager quoi que ce soit. Correspond aussi au principe déjà
  établi de `name_proposal.py` : une proposition à relire, jamais appliquée
  à l'aveugle.
- **Indice de titre automatique** : contrairement à la page "Générer" où
  l'utilisateur colle le tag `Title` embarqué à la main, l'orchestration le
  lit elle-même via `extract.extract_video_metadata()` (`general_title`,
  déjà extrait) et le fournit comme `title_hints` — automatise un geste que
  l'utilisateur fait déjà manuellement, pas une nouvelle logique de
  détection.
- **Nommage par fichier dans un pack** : `propose_video_release_name`
  n'a besoin d'aucune modification. Appelé une fois avec **tous** les
  fichiers du groupe → nom de pack (dossier + `.torrent`, identifiant
  `S01`). Appelé une deuxième fois **par fichier** (liste à un seul
  élément) → nom individuel avec son propre identifiant `S01E0X` (déjà le
  comportement de la fonction pour une liste de longueur 1, voir
  `test_single_episode_keeps_episode_number`) — aucune fonction nouvelle
  requise dans `name_proposal.py`.
- **Groupement automatique par tag d'équipe (résout un cas réel rencontré
  par l'utilisateur — packs assemblés à partir de plusieurs releases)** :
  aujourd'hui, des tags d'équipe différents dans un pack font échouer
  `propose_video_release_name` en bloc (`None`, un seul message d'erreur).
  L'orchestration groupe D'ABORD les fichiers par tag d'équipe détecté
  (même priorité indice > nom de fichier que la détection existante ;
  aucun tag détecté = son propre groupe, jamais fusionné par supposition)
  puis calcule **une proposition + un `.torrent` par groupe**. Un pack
  `S01E01-05` (TeamA) + `S01E06-12` (TeamB) devient deux uploads distincts
  au lieu d'un refus complet. `name_proposal._extract_team` devient public
  (`extract_team_tag`, comportement inchangé) pour être réutilisé ici.
- **Validation réutilisée telle quelle, aucune duplication** : une fois un
  nom de groupe proposé, l'orchestration appelle le **vrai** validateur du
  profil (`registry.get_validator(profile, "video")`, celui qui tourne
  déjà pour `nfogen.generate()`) via un `RenderContext` construit à la
  volée (`data={"release_name": ..., "video_metadata": [...]}`) — récupère
  gratuitement `cross_checks`, `upscale_checks` (sous-projet précédent) et
  `track_language_checks` sans réimplémenter quoi que ce soit. Une
  `ValueError` (nom non conforme, ex. codec vidéo introuvable donc token
  requis absent) transforme le groupe en "bloqué" (aucune mise en scène
  possible) plutôt que de laisser planter l'appel.
- **Disposition du fichier mis en scène** : un groupe à un seul fichier
  (film, ou épisode isolé) est mis en scène comme fichier unique
  (`staging_dir/<release_name>.<ext>`) ; un groupe à plusieurs fichiers
  (pack) comme dossier (`staging_dir/<release_name>/<nom par fichier>`) —
  convention scene standard (torrent fichier unique pour un film, torrent
  dossier pour un pack). Le `.torrent` est écrit à côté
  (`staging_dir/<release_name>.torrent`).
- **API sans nouvel identifiant** : pas besoin d'ajouter un `id` à
  `GapResult` — le frontend a déjà `local_paths` en mémoire depuis
  `GET /gapscan/results` et les repasse directement en entrée de
  `POST /gapscan/prepare-upload/preview`. Garde `upload_prep.py` découplé
  du modèle de données GapScan (ne connaît que des chemins), réutilisable
  si un futur déclencheur (sous-projet 7) ne vient pas de GapScan.

**Conception** :

1. **`nfogen/upload_prep.py`** (nouveau) :
   - `group_by_team(filenames, hints) -> list[list[int]]` : pur, groupe des
     index par tag d'équipe détecté (`None` compris comme groupe à part).
   - `preview_upload(local_paths, profile="c411") -> list[GroupProposal]` :
     extraction MediaInfo par fichier (best-effort : une extraction
     illisible devient un avertissement, jamais un plantage), groupement,
     proposition de pack + par fichier, validation via le vrai validateur
     du profil. Aucune écriture disque.
   - `commit_upload(release_name, files, profile="c411") -> CommitResult` :
     mise en scène (`file_staging`) + `.torrent` (`torrent_builder`, taille
     de pièce du barème C411) dans `gapscan_config_store.effective_staging_dir()`
     avec `gapscan_config_store.effective_c411_announce_url()`. Nécessite
     l'extra `automation` (torf) — comportement 501 identique au reste si
     absent.
2. **API** (`nfogen/api.py`, sous `/gapscan/prepare-upload/*`, même garde
   `_require_gapscan_available()` que le reste de GapScan) :
   - `POST /gapscan/prepare-upload/preview` — `{local_paths, profile}` →
     liste de groupes (nom de pack, fichiers avec nom individuel,
     avertissements, bloqué ou non).
   - `POST /gapscan/prepare-upload/commit` — `{release_name, files, profile}`
     (le frontend renvoie exactement ce que `preview` a produit pour CE
     groupe) → dossier/fichier mis en scène + chemin du `.torrent`.
3. **Frontend** : bouton "Préparer l'upload" sur une ligne GapScan → appelle
   `preview`, affiche chaque groupe (nom proposé, fichiers, avertissements)
   dans une carte avec un bouton "Confirmer" **par groupe** (jamais un
   "tout confirmer" — cohérent avec la décision "upload un par un").

**Pas dans ce sous-projet** (laissé au sous-projet 7, YAGNI) :
- Correction manuelle d'un nom refusé/bloqué (forcer un `release_name`) —
  l'utilisateur doit repasser par la page "Générer" existante pour l'instant.
- Déclenchement automatique (file d'attente, email) — ici uniquement un
  bouton manuel dans GapScan.

**Livré (2026-08-28)** — conforme à la conception ci-dessus, aucun écart
notable. `extract_team_tag`/`strip_ext` (ex-`_extract_team`/`_strip_ext`)
rendues publiques dans `name_proposal.py` sans changement de comportement
(renommage pur). Le bouton "Préparer l'upload" n'apparaît sur une ligne
GapScan que si `path_resolved` est vrai et `local_paths` non vide.

**Extension (2026-08-28, retour utilisateur après test réel)** —
`commit_upload()` génère et met aussi en scène le `.nfo` (moteur
`nfogen.generate()` existant, aucune duplication), en plus du média et du
`.torrent` : un seul `.nfo` par groupe, même pour un pack multi-fichiers
(`extract_video_dir_text` sur le dossier déjà mis en scène). `CommitResult`
gagne un champ `nfo_path`. Lu depuis le chemin **mis en scène** (pas
l'original) pour que "Complete name" dans le `.nfo` reflète le nom de
release final. Sous-projet 5 (upload C411) n'aura donc qu'à lire ce `.nfo`
déjà prêt, pas à en générer un.

Aussi corrigé le même jour, découverts en testant en conditions réelles
(hors scope de la conception initiale, documentés ici car dans le même
module/branche) :
- `preview_upload()` déduit un indice de langue depuis les vraies pistes
  audio du fichier (`extract_video_metadata`) quand le nom de fichier n'en
  porte aucun — combine plusieurs langues avec `+` pour déclencher le
  préfixe `MULTI` attendu par C411.
- `quality.py:SOURCE_RANK` traitait WEB-DL/WEBRip et WEB comme des sources
  différentes (faux `quality_gap` sur des titres déjà couverts par une
  release C411 équivalente) — voir CHANGELOG.md pour le détail.

Voir le plan d'implémentation complet (code exact) :
[docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md](docs/superpowers/plans/2026-08-28-automation-upload-orchestration.md).

## Sous-projet 5 : Upload vers C411 (notes préliminaires, 2026-08-28)

Pas encore conçu formellement, mais plusieurs découvertes réelles pendant
les tests du sous-projet 4 réduisent significativement le périmètre
attendu — à documenter avant de les perdre.

**Problème déclencheur** : le titre du `release_name` proposé
(`name_proposal.py`) vient **uniquement du nom de fichier** — jamais
corrigé vers le titre français attendu par C411 (cas réel : "A Guy And A
Girl" au lieu de "Un gars, une fille"). Aucun mécanisme de correction
n'existe aujourd'hui.

**La présentation C411 ("Cover manquante" + page d'aide "Présentation
HTML", collées par l'utilisateur, 2026-08-28)** — trois onglets existent
pour la description d'une release à l'upload :
- **Standard (BBCode)**
- **HTML brut** — réservé aux membres de l'équipe interne (grades G0/G3),
  **pas accessible à un compte normal** — hors scope pour nfogen.
- **Généré automatiquement** — construit par C411 lui-même **depuis TMDB
  + le `.nfo`**. Quand l'auto-détection TMDB échoue (release trop
  ambiguë), C411 propose une recherche manuelle (coller un ID TMDB) ou un
  lien d'image direct — la cover reste optionnelle, jamais bloquante.

Conséquence importante : nfogen n'a probablement **pas besoin de
construire une présentation HTML lui-même** pour un premier lot — juste
s'assurer qu'un ID TMDB correct est associé à l'upload (déjà connu via
`movie.tmdb_id`/`RadarrMovieFile`) et soumettre le `.nfo` (déjà généré,
sous-projet 4) ; C411 se charge du reste via "Généré automatiquement".
Web scraping quelconque ou générateur HTML maison : à écarter tant que
cette hypothèse n'est pas infirmée par un vrai test d'upload.

**Principe rappelé par l'utilisateur (agnosticisme)** : la logique "aller
chercher titre/synopsis dans la langue attendue par le tracker" doit être
pilotée par le **profil** (ex. un futur champ `metadata_language: "fr"`
dans `rules.json`), jamais une langue française codée en dur dans
`upload_prep.py` ou ailleurs — même principe que tout le reste de ce
pipeline.

**Décision (2026-08-28) : le tracker, pas la config *arr.** Piste
envisagée un temps : s'appuyer sur le réglage "Metadata Language" de
Radarr/Sonarr (ils interrogent déjà TMDB/TVDB eux-mêmes) plutôt que
d'ajouter un client dédié. **Écartée** : c'est un réglage global à
l'instance, pas pensé pour ça — si l'utilisateur veut son Radarr/Sonarr en
anglais pour son usage perso mais publier en français sur C411, les deux
besoins entrent en conflit sur un seul réglage. Ça casserait aussi le
principe déjà posé pour tout le pipeline : **seul le profil doit savoir ce
qu'un tracker exige**, jamais un réglage *arr sans rapport. Donc :
interroger **TMDB directement**, langue pilotée par le profil
(`metadata_language` dans `rules.json`).

**TMDB seul, pas TVDB** (décision utilisateur, 2026-08-28 : accès TVDB
non fonctionnel de son côté, et ça évite une deuxième authentification à
maintenir) :
- **Films** : `movie.tmdb_id` déjà connu (Radarr) → direct.
- **Séries** : Sonarr ne donne qu'un `tvdb_id` → pont via l'endpoint TMDB
  `find` (`GET /find/{tvdb_id}?external_source=tvdb_id`). Si le pont ne
  trouve rien (rare), avertissement + repli sur le titre déjà connu —
  jamais bloquant, jamais deviné.
- **Authentification** : Read Access Token TMDB (Bearer, pas la clé v3 en
  paramètre d'URL) — recommandé par TMDB, en lecture seule (principe du
  moindre privilège, même discipline que la clé API C411 : jamais
  journalisée/exposée).

**Livraison 1 (2026-08-28) — Livré, conforme à la conception, aucun écart
notable.** Titre éditable dans le panneau "Préparer l'upload", indépendant
de toute intégration TMDB : `title_override` enfilé de bout en bout
(`name_proposal.propose_video_release_name` → `engine.propose_release_name`
→ `upload_prep.preview_upload` → `POST /gapscan/prepare-upload/preview` →
`UploadPrepPanel`). Ponctuation naturelle (virgule, apostrophe...) retirée
entièrement, jamais convertie en point — confirmé auprès du support C411.

**Livraison 2 (pas commencée)** : intégration TMDB (client dédié,
`metadata_language` dans `rules.json`, pré-remplissage automatique du
champ titre de la Livraison 1) — nécessite le Read Access Token TMDB de
l'utilisateur (déjà en sa possession).
