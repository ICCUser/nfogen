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
| 4b | Généralisation tracker-agnostique (retrofit des sous-projets 2/4 + GapScan) | **Livré (2026-08-29)**, voir [le plan](docs/superpowers/plans/2026-08-29-tracker-agnostic-generalization.md) |
| 5 | Upload vers C411 | Conçu (2026-09-04), voir sa section ci-dessous |
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

## Sous-projet 4b : Généralisation tracker-agnostique (2026-08-29)

**But** : le principe directeur (ci-dessus) était déjà posé, mais les
sous-projets 2/4 (déjà livrés) et GapScan (livré avant même ce document)
ont chacun laissé passer une valeur spécifique à C411 en dur en Python là
où le profil aurait dû trancher. Ce sous-projet corrige ces quatre points
avant d'attaquer le sous-projet 5 (upload), qui aurait sinon reproduit le
même problème sur du code neuf.

**Déclencheur** : relecture demandée par l'utilisateur en voyant le
nombre de pages/scripts nommés "C411" alors que le but reste "je charge un
profil, il définit les règles du tracker, le reste de l'appli marche
pareil" (scan, génération, upload).

**Audit — ce qui est réellement couché en dur (pas juste `profile="c411"`
en valeur par défaut, qui est déjà agnostique)** :

1. **Codes de catégorie Torznab** (`gapscan.py:_ANIME_CATEGORIES`/
   `_DOCUMENTARY_CATEGORIES`, 2060/5070/2070/5080) — varient d'un indexeur
   Torznab à l'autre, câblés en constantes Python. (Le débit — 15
   requêtes/min chez C411, voir GAPSCAN.md § "Débit confirmé" — est lui
   déjà externalisé via `NFOGEN_C411_MIN_INTERVAL_SECONDS` : pas un vrai
   problème d'agnosticisme, juste un nom de variable d'environnement
   spécifique à généraliser en même temps que le reste du point 2
   ci-dessous, par cohérence.)
2. **Noms des champs de config** (`gapscan_config_store.py` :
   `c411_api_key`/`c411_base_url`/`c411_announce_url`) — le nom du
   tracker est câblé dans le nom du champ lui-même, pas seulement sa
   valeur ; un deuxième tracker ne peut pas cohabiter proprement.
3. **Barème de taille de pièce torrent** (`torrent_builder.py`, voir
   tableau sous "Règles C411 de création de torrent" ci-dessus) — recopié
   tel quel du sous-projet 2, jamais rendu déclaratif comme prévenu à
   l'époque (voir "Principe directeur" ci-dessus, § "Où ça ne l'est PAS
   encore").
4. **Combinaisons de langue MULTI whitelistées** (`upload_prep.py`,
   `FR+EN`/`EN+FR`/`FR+JA`/`JA+FR`) — même défaut, hérité du sous-projet 4.

`c411_client.py` parle déjà Torznab standard (voir "Principe directeur"
ci-dessus) — seul le nom (`C411Client`) est trompeur, aucun comportement
à changer, juste un renommage. `name_proposal.py`/`rules.json` (sous-projet
3) sont déjà 100% pilotés par profil — rien à toucher là.

**Décisions (utilisateur, 2026-08-29)** :

- **Identifiants par profil, pas un seul jeu global.** Chaque profil
  (`c411`, un futur autre tracker) garde ses propres identifiants,
  associés à son nom — cohérent avec "je charge un profil, il définit
  tout". Sonarr/Radarr restent globaux (une seule bibliothèque média,
  indépendante du tracker ciblé) : seuls les identifiants du **tracker**
  deviennent namespacés. Nouveau schéma du fichier de
  `gapscan_config_store.py` :
  ```json
  {
    "sonarr_url": "...", "sonarr_api_key": "...",
    "radarr_url": "...", "radarr_api_key": "...",
    "trackers": {
      "c411": { "api_key": "...", "base_url": "...", "announce_url": "..." }
    }
  }
  ```
  **Compat ascendante sans script de migration** : `effective_tracker("c411")`
  retombe sur les anciens champs plats (`c411_api_key`/`c411_base_url`/
  `c411_announce_url`) tant qu'aucun `trackers.c411` n'est encore
  enregistré — les identifiants déjà en place sur le serveur de
  l'utilisateur continuent de marcher sans ressaisie, migrés en douceur au
  prochain `PUT /gapscan/config`.
- **Nouvelle section `tracker` dans `rules.json`** (même niveau que
  `video`), regroupe tout ce qui varie par tracker mais pas par catégorie
  de média :
  ```json
  "tracker": {
    "display_name": "C411",
    "torznab_categories": {"anime": ["2060", "5070"], "documentaire": ["2070", "5080"]},
    "multi_language_whitelist": ["FR+EN", "EN+FR", "FR+JA", "JA+FR"],
    "min_request_interval_seconds": 4.5,
    "torrent_piece_sizes": [
      {"max_bytes": 1073741824, "piece_size": 1048576},
      {"max_bytes": 2147483648, "piece_size": 2097152},
      {"max_bytes": 3221225472, "piece_size": 4194304},
      {"max_bytes": 8589934592, "piece_size": 8388608},
      {"piece_size": 16777216}
    ]
  }
  ```
  (`torrent_piece_sizes` reprend telle quelle la table déjà documentée
  ci-dessus sous "Règles C411 de création de torrent" — dernière entrée
  sans `max_bytes` = barème au-delà de 8 Go.) `gapscan.py`,
  `torrent_builder.py` et `upload_prep.py` lisent cette section au lieu de
  constantes Python. L'env var `NFOGEN_C411_MIN_INTERVAL_SECONDS` reste
  lisible pour le profil `c411` (rétrocompat), mais devient un simple
  override déploiement de `min_request_interval_seconds` plutôt que
  l'unique source de vérité.
- **Renommage `c411_client.py` → `torznab_client.py`**
  (`C411Client`/`C411Error`/`C411Release` → `TorznabClient`/`TorznabError`/
  `TorznabRelease`), purement mécanique.
- **API** : `GET`/`PUT /gapscan/config` gagnent un paramètre `profile` ;
  réponse sans préfixe `c411_` (`tracker_configured`, `tracker_base_url`,
  `tracker_announce_url_configured`).
- **Frontend** : `GapScanPage.tsx` lit `display_name` du profil actif au
  lieu du texte en dur ("Scan C411" → "Scan {display_name}", etc.).
  `ProfileEditorPage.tsx` gagne un nouvel onglet **"Tracker"** (à côté de
  Règles/Template/Aperçu) pour éditer `display_name`/`torznab_categories`/
  `multi_language_whitelist`/`torrent_piece_sizes` en formulaire structuré,
  cohérent avec `CategoryRulesForm` existant.

**Pas dans ce sous-projet** (delta volontairement laissé de côté, YAGNI,
mais probable suite proche — même traitement que la Livraison 2 TMDB
mise de côté) : les regex de **détection** dans `name_proposal.py`
(saison/épisode, année, tag d'équipe, crochets) restent en dur en Python.
Elles supposent une convention scene déjà quasi-universelle (S01E01,
`-TEAM`, crochets) — aucun tracker connu n'en a besoin d'autres pour
l'instant. Motivation de l'utilisateur pour ne pas les négliger trop
longtemps : lisibilité du projet pour quelqu'un qui le découvre sur
GitHub sans connaître son historique — actuellement rien ne signale que
ces regex sont un point dur, câblé C411-implicite par convention plutôt
que par valeur. À rouvrir explicitement quand un deuxième tracker aux
conventions vraiment différentes se présente.

**Livré (2026-08-29)** — conforme à la conception ci-dessus, avec deux
écarts découverts en écrivant le plan d'implémentation (voir
[le plan](docs/superpowers/plans/2026-08-29-tracker-agnostic-generalization.md)
pour le détail tâche par tâche) :

- **Pas d'onglet "Tracker" dans l'éditeur de profil.** Le seul profil qui
  existe (`c411`) est livré avec sa section `tracker` déjà peuplée ;
  l'éditer se fait à la main (`rules.json`) ou via export/import `.zip`,
  déjà supportés. Une UI structurée est repoussée au jour où un second
  tracker doit réellement être créé depuis l'interface.
- **`tracker.audio_language_codes` remplace le `multi_language_whitelist`
  envisagé** — en relisant le vrai code (`upload_prep.py`), il n'existe
  aucune liste blanche de combinaisons ; seule une table `code MediaInfo
  → code court` (`fre`→`FR`, etc.) est réellement spécifique à C411.
- **Sélecteur de profil global dans l'en-tête** (`ProfileContext`,
  `App.tsx`), pas par page comme d'abord esquissé — remplace le "Scan
  C411" en dur dans la navigation ET le sélecteur déjà présent sur
  "Générer". Le panneau "Préparer l'upload" garde un **override local**
  (retour utilisateur, 2026-08-29 : "sélection de profil unitaire par
  média") — le profil global s'applique par défaut, mais un upload donné
  peut cibler un autre tracker sans changer le profil actif de
  l'application.
- **Correctif trouvé en testant** : `tracker_profile.py` plantait
  (`ProfileStoreError` non gérée) pour un nom de profil qui n'existe pas
  du tout (pas seulement un profil existant sans section `tracker`) —
  corrigé pour dégrader proprement dans les deux cas (jamais de
  supposition, jamais de plantage).

## Sous-projet 5 : Upload vers C411 (conception, 2026-08-28 → 2026-09-04)

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

**Livraison 1 (2026-08-28) — Livré.** Titre éditable dans le panneau
"Préparer l'upload", indépendant de toute intégration TMDB :
`title_override` enfilé de bout en bout (`name_proposal.propose_video_release_name`
→ `engine.propose_release_name` → `upload_prep.preview_upload` →
`POST /gapscan/prepare-upload/preview` → `UploadPrepPanel`). Ponctuation
naturelle (virgule, apostrophe...) retirée entièrement, jamais convertie
en point — confirmé auprès du support C411.

**Écart découvert juste après livraison (2026-08-28, cas réel "Les Fils
du vent")** : le champ partait vide par conception initiale, forçant une
saisie manuelle même quand `GapResult.title` (Sonarr/Radarr) contenait
déjà le bon titre — déjà affiché dans l'en-tête du panneau, jamais
réutilisé pour le nommage. Corrigé : le champ se pré-remplit désormais
avec ce titre déjà connu dès le chargement de l'aperçu (reste éditable si
même celui-là est faux, cf. cas "A Guy And A Girl" où le titre Sonarr
lui-même est erroné).

**Écart supplémentaire corrigé (2026-08-29)** : accents supprimés au lieu
d'être translittérés ("Célibataires... ou Presque" → "Clibataires...") et
absence de capitalisation par mot ("il faut sauver le soldat Ryan" au lieu
de "Il.Faut.Sauver.Le.Soldat.Ryan"). Corrigé dans
`name_proposal._normalize_title_text` (translittération NFKD + `\b\w`
capitalisé, casse existante jamais abaissée — un acronyme comme "FBI"
reste "FBI"). Panneau "Préparer l'upload" également corrigé pour ne plus
garder un état périmé quand on l'ouvre sur une ligne différente sans
fermer la précédente (`key` React sur les chemins locaux).

**Livraison 2 — mise de côté (2026-08-29).** Décision utilisateur : au vu
des résultats de la Livraison 1 + des corrections ci-dessus (accents,
capitalisation, pré-remplissage depuis `GapResult.title`), l'essentiel des
cas réels est déjà correct sans TMDB. L'intégration TMDB (client dédié,
`metadata_language` dans `rules.json`) reste utile pour les cas plus rares
où `GapResult.title` lui-même est faux (ex. "A Guy And A Girl"), mais
n'est plus jugée prioritaire — corrigeables à la main via le champ titre
en attendant. Décisions déjà prises ci-dessus (TMDB seul, Read Access
Token) restent valables si/quand ce chantier reprend ; aucun code écrit.

**Piste à approfondir (utilisateur, 2026-08-29, pas tranchée)** : au-delà du
sous-projet 4b (qui rend déclaratifs catégories/langues/pièces/identifiants),
l'appel d'upload lui-même (formulaire `/upload` de C411 — champs exacts,
méthode d'auth, structure de la requête) reste à concevoir. Question posée
sans réponse encore : faut-il un jeu de **règles API par tracker**
(gabarit de requête déclaratif dans le profil, un peu comme
`name_proposal.template`) plutôt que du code Python spécifique par
tracker pour la soumission elle-même ? Cohérent avec le principe
directeur, mais pas encore conçu — à trancher quand ce sous-projet sera
détaillé, pas avant.

**Piste à approfondir (utilisateur, 2026-08-30, pas tranchée) : séries
terminées — INTEGRALE vs par saison.** Constat en regardant le catalogue
C411 (cas réel, "Lucifer") : une série peut être uploadée soit saison par
saison (`Lucifer.2016.S01...`), soit en un seul pack `INTEGRALE`
regroupant toutes les saisons (`Lucifer.2016.INTEGRALE...`) une fois la
série terminée — les deux formes coexistent sur le tracker pour le même
show. Rien dans le pipeline actuel ne gère ce choix :

- **GapScan raisonne par saison** (`SonarrSeasonFile` → un `GapResult` par
  saison) — aucune notion de "série terminée" n'est récupérée depuis
  Sonarr (le champ existe côté API Sonarr, `series.status`, mais
  `sonarr_client.py` ne le lit pas aujourd'hui).
- **"Préparer l'upload" ne prend qu'une ligne à la fois** — pas de moyen
  de sélectionner plusieurs saisons d'une même série pour les combiner en
  un seul groupe/upload.
- **`name_proposal.py` ne connaît que `S{saison}`/`S{saison}E{episode}`**
  comme identifiant — aucun gabarit `INTEGRALE`.

Question posée par l'utilisateur, pas encore tranchée : quand une série
est terminée, faut-il proposer explicitement le choix (pack complet vs
saison par saison), ou est-ce toujours l'un des deux selon un critère à
définir ? Touche le modèle de données GapScan, l'UI de sélection, et le
gabarit de nommage — un vrai sous-projet à concevoir, pas un correctif.
Pas de code écrit, décisions à prendre quand ce chantier sera repris.

### Conception complète (2026-09-04)

**Doc API officielle obtenue de l'utilisateur (page "Guide complet des
intégrations", `c411.org/user/integrations`)** — résout la "Piste à
approfondir" ci-dessus sur les règles API par tracker, avec de vraies
données plutôt qu'une hypothèse :

- **Endpoint** : `POST https://c411.org/api/torrents`,
  `Authorization: Bearer <clé API>`, `multipart/form-data`.
- **Champs requis** : `torrent` (fichier, max 10 Mo), `nfo` (fichier, max
  5 Mo), `title` (3-200 car.), `description` (BBCode ou HTML, min 20
  car.), `categoryId`, `subcategoryId`.
- **Champs optionnels** : `descriptionFormat` (`standard` par défaut ou
  `html` — ce dernier nécessite la permission `torrent:use_html_prez`,
  réservée aux grades internes G0/G3, voir note du 2026-08-28 plus haut ;
  **toujours `standard`** pour nfogen), `options` (JSON,
  `{optionTypeId: optionValueId | [optionValueId, ...]}`), `uploaderNote`,
  `tmdbData`/`rawgData` (JSON, métadonnées affichées sur la page).
- **`GET /api/categories`** : catégories + sous-catégories.
  **`GET /api/categories/{subcategoryId}/options`** : types d'option +
  valeurs disponibles pour une sous-catégorie (dynamique — voir
  "Décisions" ci-dessous pour le choix de les figer dans le profil plutôt
  que de les requêter à chaque fois).
- **`GET /api/torrents/by-tmdb?tmdbId={id}&tmdbType={movie|tv}`** :
  releases déjà approuvées pour cet identifiant TMDB (10 max, 30
  requêtes/min) — vérification anti-doublon avant upload.
- **Brouillons** (`/api/user/drafts`, CRUD complet, 15 max/utilisateur) :
  **mécanisme retenu pour l'envoi** (voir décision 6) — un brouillon
  n'entre jamais en modération tout seul, la finalisation reste manuelle
  sur le site C411.

**Découverte qui change le périmètre attendu** : contrairement à
l'hypothèse du 2026-08-28 ("C411 se charge de tout via Généré
automatiquement"), l'API exige un champ `description` **rempli par
l'appelant** (BBCode réel, pas juste un ID TMDB à associer) — ce
comportement "Généré automatiquement" n'existe que côté **formulaire web**
(upload manuel), pas côté API. nfogen doit donc composer lui-même une
vraie description.

**Catégories/sous-catégories réelles (copiées par l'utilisateur,
2026-09-04)** — pertinentes pour nfogen (catégorie 1, "Films & Vidéos") :

| categoryId | subcategoryId | Nom |
|---|---|---|
| 1 | 1 | Animation (film) |
| 1 | 2 | Animation Série |
| 1 | 4 | Documentaire |
| 1 | 6 | Film |
| 1 | 7 | Série TV |

**Types d'option pertinents** (`GET /api/categories/{subcategoryId}/options`
donne la liste complète et à jour — table ci-dessous : valeurs observées,
figées dans le profil, voir "Décisions") :

| optionTypeId | Nom | Multi-select | Valeurs observées |
|---|---|---|---|
| 1 | Langue | oui | 1=Anglais, 2=Français (VFF), 3=Muet, 4=Multi (FR inclus), 5=Multi (QC inclus), 6=Québécois (VFQ), 7=VFSTFR, 8=VOSTFR, 422=Multi VF2 (FR+QC) |
| 2 | Qualité | non | 10=BluRay 4K, 11=BluRay Full, 12=BluRay Remux, 16=HDRip 1080, 24=WEB-DL, 25=WEB-DL 1080, 26=WEB-DL 4K, 413=Bluray.HDLight 1080 |
| 7 | Saison | non | 118=Série intégrale, 119=Hors saison, 120=Non communiqué, 121-150=Saison 01-30 |
| 6 | Épisode | non | 96=Saison complète, 97-116=Épisode 01-20, 117=Non communiqué |

**Décisions** :

1. **Métadonnées de présentation (synopsis, affiche, genres, réalisateur/
   casting) : réutiliser Radarr/Sonarr, pas un client TMDB dédié.**
   `RadarrMovieFile`/`SonarrSeasonFile` gagnent `overview`, `poster_url`,
   `genres`, `directors`, `cast` — Radarr/Sonarr interrogent déjà TMDB/
   TVDB pour leur propre usage et exposent ces champs sur leurs propres
   endpoints (`/api/v3/movie`, `/api/v3/series`), jamais extraits jusqu'ici
   côté `radarr_client.py`/`sonarr_client.py`. Confirme l'intuition de
   l'utilisateur du 2026-08-28 ("je suis sûr que via les API de radarr et
   sonarr on peut chopper les informations sans forcément taper l'API de
   TMDB en direct") : zéro nouveau secret, zéro nouvelle dépendance
   externe. La Livraison 2 TMDB (mise de côté, voir plus haut) reste
   pertinente uniquement pour les cas où `GapResult.title` lui-même est
   faux — sans rapport avec ce sous-projet.

2. **Gabarit de description BBCode, mécanisme parallèle aux `.nfo` — pas
   une 6ᵉ catégorie.** Un nouveau fichier
   `profiles/c411/templates/upload_description.j2` (Jinja2, comme les
   `.nfo` existants), rendu avec le contexte (titre, synopsis, affiche,
   genres, casting, infos qualité tirées de `video_metadata`). La
   description n'est pas un "type de média" comme `video`/`audio`/etc.
   (`CATEGORIES` dans `declarative_profile.py`) — plutôt qu'élargir cette
   liste pour un concept qui n'en est pas un, un petit rendu Jinja2
   dédié et autonome (nouvelle fonction, ex.
   `nfogen/upload_description.py:render_upload_description()`), en dehors
   du système `register`/`registry` par catégorie. Éditable comme
   n'importe quel template de profil, jamais de BBCode généré en dur en
   Python.

3. **Catégorie/sous-catégorie/options : déclaratifs dans le profil
   (`rules.json` → `tracker.upload`), pas requêtés dynamiquement à
   chaque envoi, pas câblés en Python.** Répond explicitement à la
   question ouverte du 2026-08-29 ("faut-il un jeu de règles API par
   tracker ?") : **oui**. Les valeurs de la table ci-dessus, figées dans
   le profil c411 :
   ```json
   "tracker": {
     ...,
     "upload": {
       "category_id": 1,
       "subcategory_id_by_media_type": {"movie": 6, "series": 7},
       "language_option_id": 1,
       "language_values": {
         "VFF": 2, "MULTI.VFF": 4, "VO": 1, "VOSTFR": 8
       },
       "quality_option_id": 2,
       "quality_values": {
         "BluRay.HDLight": 413, "BluRay": 11, "BluRay.REMUX": 12,
         "WEB": 25, "WEB.4K": 26
       },
       "season_option_id": 7,
       "season_values": {"INTEGRALE": 118, "S01": 121, "S02": 122, "S30": 150},
       "episode_option_id": 6,
       "full_season_episode_value": 96
     }
   }
   ```
   `language_values`/`quality_values` sont indexés par les mêmes chaînes
   que celles déjà produites par `name_proposal.py`
   (`language_aliases`/`source_aliases` — voir sous-projet 3), pas
   redéfinies séparément : `fields["language"]`/`fields["source"]` (+
   marqueur `HDLight` si présent, voir sous-projet 4b tout juste livré)
   servent directement de clé de correspondance. `GET /api/categories/*`
   reste utile en développement pour vérifier que la table n'a pas dérivé
   (voir "Pas dans ce sous-projet"), mais n'est jamais appelée au moment
   de l'envoi réel.
   **Non résolu, à vérifier avant d'écrire le mapping final** : la liste
   donnée par l'utilisateur n'a qu'UN SEUL "Documentaire" (subcategoryId
   4), pas de distinction film/série contrairement aux codes Torznab de
   recherche (2070 vs 5080, voir sous-projet 4b/GAPSCAN.md) — à confirmer
   via `GET /api/categories` en conditions réelles avant d'écrire cette
   partie du mapping (jamais deviner une correspondance).

4. **`nfogen/c411_upload_client.py` — délibérément *pas* générique,
   contrairement à `torznab_client.py`.** Cette API REST (endpoints,
   champs, format `options`) est propre à C411, sans standard équivalent
   partagé par d'autres trackers (rappel du principe directeur, sous-
   projet 4b : Torznab est un vrai standard partagé, ceci ne l'est pas).
   Reste nommé et pensé comme spécifique à ce tracker jusqu'à preuve du
   contraire (un deuxième tracker à intégrer un jour) — même discipline
   YAGNI déjà appliquée aux regex de détection de `name_proposal.py`.

5. **Vérification anti-doublon best-effort, jamais bloquante.**
   `GET /api/torrents/by-tmdb` juste avant l'envoi réel (pas pendant
   GapScan, qui a déjà son propre mécanisme via Torznab — sous-projet
   4b/GAPSCAN.md). Pour un film, `tmdb_id` est déjà connu
   (`RadarrMovieFile.tmdb_id`). **Pour une série, généralement absent**
   (`GapResult.tmdb_id` est toujours `None` côté série, seul `tvdb_id`
   est connu — voir `gapscan.py`) : la vérification est alors simplement
   sautée avec un avertissement explicite ("doublon non vérifiable, tmdb_id
   inconnu pour cette série"), jamais bloquant, jamais deviné.

6. **"Envoyer à C411" crée un BROUILLON (`POST /api/user/drafts`), jamais
   une soumission réelle.** Revu le 2026-09-04 (retour utilisateur) :
   contrairement à l'hypothèse initiale de ce sous-projet, un brouillon
   n'entre **jamais** en file de modération tout seul — c'est un objet
   privé, lié au compte, sans aucun effet sur le tracker tant que
   l'utilisateur ne le finalise pas **lui-même sur le site C411** (aucun
   endpoint "soumettre le brouillon" n'existe côté API — confirmé par
   l'utilisateur : "si draft, pas de soumission modération, c'est lié au
   compte user"). Ça simplifie et sécurise le flux prévu à l'origine (plus
   besoin d'un "second clic qui déclenche vraiment la modération" dans
   nfogen) :
   - "Confirmer" (sous-projet 4) reste strictement local (mise en scène +
     `.torrent`, aucun appel réseau externe).
   - Nouveau bouton **"Envoyer à C411"**, visible après une confirmation
     locale réussie : vérifie les doublons (décision 5), rend la
     description, puis `POST /api/user/drafts` avec `.torrent`/`.nfo`
     encodés en base64 dans le corps JSON (comportement documenté par
     C411 pour cet endpoint) + titre/description/catégorie/options.
   - Réponse affichée à l'utilisateur : lien direct vers le brouillon créé
     sur `c411.org` — **c'est lui qui le finalise et le soumet en
     modération**, à son rythme, avec une dernière relecture sur le vrai
     site avant que quoi que ce soit devienne public. nfogen ne tente
     jamais d'automatiser cette dernière étape.
   - Si un brouillon a déjà été créé pour ce groupe (nouvel essai après
     correction), `PATCH /api/user/drafts/{id}` avec l'`id` déjà connu
     plutôt qu'un nouveau `POST` — évite d'accumuler des doublons de
     brouillons vers la limite de 15. `id` conservé côté nfogen tant que
     le panneau "Préparer l'upload" reste ouvert (pas persisté au-delà,
     cohérent avec le reste de ce panneau).

7. **Gestion des réponses** : succès → nfogen affiche le lien du
   brouillon (`https://c411.org/...`, à confirmer sur la vraie réponse
   JSON de `POST /api/user/drafts`). **Limite réelle à gérer** : 15
   brouillons max par utilisateur (documenté) — une erreur à ce sujet doit
   pointer explicitement vers la page brouillons de C411 pour en
   supprimer, jamais un message générique. Erreur 401/403 → message
   explicite pointant vers le scope de la clé API (voir point à vérifier
   ci-dessous). Erreur 4xx de validation (champ manquant/trop court,
   catégorie invalide) → détail du message C411 remonté tel quel,
   jamais réinterprété.

**À vérifier avant le premier essai réel (utilisateur, pas de code
concerné)** : la clé API existante (déjà utilisée pour Torznab/RSS,
`gapscan_config_store.effective_tracker`) a-t-elle le **scope upload/
brouillons** sur `https://c411.org/user/integrations` ? La doc ne précise
le scope requis que pour l'endpoint anti-doublon ("Torznab/RSS, accordé
par défaut") — pas explicitement pour `POST /api/user/drafts`. Le code
utilisera la même clé existante par défaut et remontera clairement une
erreur 401/403 si elle manque de scope, plutôt que de supposer que ça
marche.

**Pas dans ce sous-projet** (delta volontairement laissé de côté, YAGNI) :
- **Gestion complète du CRUD brouillons** (`GET`/lister,
  `DELETE`/supprimer un brouillon existant depuis nfogen) — seule la
  création (`POST`, décision 6) est dans ce sous-projet ; nettoyer/
  reprendre un brouillon abandonné reste une action manuelle sur le site
  C411 pour l'instant (pas de cas d'usage identifié côté nfogen).
- **Requêter `GET /api/categories`/`GET /api/categories/{id}/options` en
  direct à l'exécution** — les valeurs sont figées dans le profil (voir
  décision 3) ; les requêter resterait utile en outil de diagnostic
  ponctuel (vérifier que la table n'a pas dérivé), pas dans le flux
  d'envoi normal.
- **Séries terminées, INTEGRALE vs par saison** — sous-projet séparé (voir
  note du 2026-08-30 ci-dessus), la valeur `season_values.INTEGRALE`
  existe déjà dans le mapping ci-dessus mais rien ne la déclenche encore.
- **File d'attente + email d'approbation** (sous-projet 7) — "Envoyer à
  C411" reste un clic manuel explicite pour l'instant, pas une file
  automatique.
