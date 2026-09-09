# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnage [SemVer](https://semver.org/lang/fr/) (`MAJOR.MINOR.PATCH`).

`v0.1.0` (2026-06-28) avait été taggé une seule fois puis jamais tenu à
jour (70 commits sans version ni changelog derrière) — `2.0.0` marque le
vrai début du suivi de version, pas une continuité directe de `0.1.0`.

## [Non publié]

### Corrigé

- **Sécurité — lecture/écriture de fichier arbitraire via les chemins
  d'upload** (audit sécurité 2026-09-09) : `staged_name`/`source_path`
  (`POST /gapscan/prepare-upload/preview` et `/commit`) et `staged_path`
  (`/prepare-upload/send`, `/verify-integrity`) étaient des chaînes
  libres fournies par le client, jamais revalidées côté serveur — un
  `staged_name` absolu ou avec `..` pouvait faire écrire hors du dossier
  de mise en scène (l'opérateur `/` de `pathlib` ignore silencieusement
  le préfixe quand l'opérande droit est absolu), et un `source_path`
  arbitraire pouvait faire lire n'importe quel fichier lisible par le
  processus. Corrigé : `source_path` doit désormais avoir été
  effectivement retourné par un scan GapScan connu
  (`upload_prep._validate_known_source_paths`, contre
  `gapscan_runner.results()`) ; tout chemin dérivé de `staging_dir`
  (`staged_path`, `.nfo`, `.torrent`) est vérifié rester sous ce dossier
  via `upload_prep.validate_staged_path()` (résolution réelle du
  chemin, pas une simple concaténation).

### Modifié

- **Bannières de section en `.webp` (au lieu de `.png`)** (retour
  utilisateur, 2026-09-08 : "j'ai vue que les banniere de base sont des
  webp `[img]/images/banners/c411-informations.webp[/img]`" — les
  bannières natives de C411 sont servies en `.webp`). Test pour voir si
  le format fait partie des critères de rendu `[img]` de C411, en plus du
  domaine — `scripts/generate_upload_banners.py` régénère
  `assets/banners/*.webp` (lossless), `upload_prep.py` pointe dessus.
  **Si les bannières restent des liens texte malgré ce changement**, ça
  confirme un whitelist par domaine plutôt que par format — retour prévu
  vers des `[h2]` texte dans ce cas.

### Ajouté

- **Vérification approfondie du fichier vidéo avant un upload direct**
  (AUTOMATION.md, sous-projet 7, brainstorm 2026-09-08/09 : "il faut que
  le média soit sûr de respecter les règles du profil/tracker [...]
  meme si il ny a rien de marqué faut trouvé a la limite declanché une
  verifi hardcore") : nouveau `nfogen/video_integrity.py` — décode
  réellement le fichier (`ffmpeg -v error -f null -`), compare durée
  réelle/annoncée (troncature) et offsets audio/vidéo (désync), en plus
  des métadonnées déjà fournies par MediaInfo. Tourne en tâche de fond
  (`nfogen/integrity_job_runner.py`, même patron que la mise en scène)
  avant **tout** clic "Uploader directement" — jamais pour "Créer un
  brouillon". Échec ⇒ bloqué complètement (ni brouillon ni upload),
  signalé pour action manuelle — jamais de dégradation silencieuse.
  Nouvelle dépendance système : `ffmpeg` (déjà utilisé comme outil de
  test dans le projet, promu ici en dépendance d'exécution réelle).

- **Packs de saisons "INTÉGRALE"** (retour utilisateur, 2026-09-08, suite
  au tag d'équipe ci-dessous : "si toute les saison provienne de la meme
  team alors on peut faire un pack INTEGRALE d'une serie") :
  `detect_season_packs()` (`nfogen/gapscan_library.py`) détecte les runs
  de saisons consécutives d'une même série partageant la même équipe et
  un chemin local résolu, exposés par `GET /gapscan/library`
  (`season_packs`) et affichés dans un nouveau bloc "Packs disponibles"
  de la Bibliothèque. Le bouton "Préparer le pack" fusionne les saisons
  concernées et ouvre l'aperçu d'upload habituel (`UploadPrepPanel`,
  `POST /gapscan/prepare-upload/preview` gagne un champ `season_pack`) —
  mise en scène en un seul groupe multi-saisons, dossiers `Sxx/` par
  saison. Nommage `SxxSyy`/`INTÉGRALE` déclaratif via `rules.json`
  (`video.name_proposal.season_pack`, confirmé par le wiki C411
  "Nommage de l'upload") — jamais en dur en Python, cohérent avec le
  principe agnostique du projet. Limitation connue : une saison absente
  de la page/du filtre Bibliothèque courant désactive le bouton (les
  chemins locaux de cette saison ne sont pas résolvables sans elle).

- **Tag d'équipe dans la Bibliothèque** (retour utilisateur, 2026-09-08 :
  repérer d'un coup d'œil quelles saisons d'une même série partagent la
  même équipe, en vue d'un futur pack "INTÉGRALE") : `LibraryItem` gagne
  `team`, extrait du `scene_name` Radarr/Sonarr (`extract_team_tag()`,
  déjà utilisé dans `upload_prep.py`) — nouvelle colonne "Team" dans le
  tableau, `—` si aucun tag détecté.

- **Charte graphique nfogen + enrichissement TMDB de la description
  d'upload** (retour utilisateur, 2026-09-07, inspiré de la présentation
  auto-générée de C411 elle-même) :
  - Nouveau client TMDB (`nfogen/tmdb_client.py`) : ajoute Pays,
    Créateur(s) (séries), Note TMDB et lien IMDB — absents des deux API
    Radarr/Sonarr, confirmé par des dumps réels. Cle API TMDB globale,
    optionnelle (config "Réglages" ci-dessous) ; en son absence ou en cas
    d'échec de l'appel, ces champs disparaissent simplement de la
    description (jamais bloquant pour l'envoi).
  - Tableau BBCode détaillé par piste audio/sous-titres (canaux, codec,
    débit, sample rate, drapeau via flagcdn.com), à la place de la
    simple liste de langues — détail extrait de MediaInfo
    (`nfogen/extract.py`), langue→drapeau résolu par le nouveau module
    `nfogen/languages.py`.
  - 4 bannières de section ("Informations"/"Synopsis"/"Détails
    techniques"/"Téléchargement") aux couleurs réelles de l'appli nfogen
    (`#141d19`/`#6bc9b3`) avec crédit "nfogen.nfo", remplaçant les `[h2]`
    texte — assets statiques générés une fois
    (`scripts/generate_upload_banners.py`, dépendance dev-only Pillow) et
    hébergés via `raw.githubusercontent.com` (pas de bannières C411
    réutilisées : elles appartiennent à un autre utilisateur du tracker).

- **Ajout automatique à qBittorrent après un upload direct** (retour
  utilisateur, 2026-09-07 : "le torrent n'est jamais envoyé à qbit !!!!")
  : `send_to_tracker(direct=True)` ajoute désormais le `.torrent` déjà en
  scène à qBittorrent juste après un envoi réussi — le `.torrent` local
  porte déjà `source=C411` (voir plus haut), plus besoin du dépôt manuel
  dans "À mettre en seed" pour ce mode. Jamais pour un brouillon (reste
  privé tant que non finalisé). Best-effort : qBittorrent non configuré
  ou échec d'ajout → `SendResult.seed_warning`, jamais bloquant (l'upload
  C411 a déjà réussi à ce stade).

- **Conteneur et format HDR dans la description d'upload** (retour
  utilisateur, 2026-09-07, en construisant un template C411 personnel
  avec `{{CONTAINER}}`/`{{HDR}}`) : `extract_video_metadata()` gagne
  `container` (dérivé de l'extension du fichier mis en scène — fiable,
  jamais ambigu) et `hdr_format` (best-effort, MediaInfo). Ajoutés à la
  ligne vidéo (`x265 2160p (UHD BluRay) Dolby Vision`) et une nouvelle
  ligne "Conteneur" dans `upload_description.j2`.

- **Upload direct vers C411, distinct du brouillon** (retour d'un membre
  de l'équipe C411, 2026-09-07) : un vrai endpoint d'upload direct existe
  (`POST /api/torrents`, multipart, part réellement en modération) —
  jamais découvert lors de l'exploration initiale du sous-projet 5
  (2026-09-04), qui s'était arrêtée sur `/api/user/drafts`. Nouveau
  `C411UploadClient.upload_torrent()`, `send_to_tracker(direct=True)`,
  et dans "Préparer l'upload" un second bouton **"Uploader directement"**
  à côté de **"Créer un brouillon"** (renommé), avec confirmation avant
  l'envoi (irréversible côté C411, contrairement au brouillon). Forme
  exacte de la réponse pas encore confirmée en conditions réelles.

- **Avertissement si la présentation sera incomplète (clé TMDB manquante)**
  (retour C411, 2026-09-07 : "tous les éléments doivent y figurer... c'est
  obligatoire") : `SendResult`/`SendToTrackerResult` gagnent
  `presentation_warning`, affiché dans "Préparer l'upload" au même endroit
  que l'avertissement anti-doublon — signale que Pays/Créateur(s)/Note
  TMDB/lien IMDB manqueront tant que la clé API TMDB n'est pas configurée
  (voir Réglages). Jamais bloquant, comme le reste des avertissements.

- **Tag `source` dans le `.torrent` généré** (retour d'un membre de
  l'équipe C411, 2026-09-07) : `torrent_builder.build_torrent()` gagne un
  paramètre `source`, câblé depuis `tracker_profile.torrent_source()`
  (nouveau champ `rules.json` → `tracker.torrent_source`, `"C411"` pour
  le profil livré). Ce tag modifie le hash du torrent — mécanisme utilisé
  par la plupart des trackers privés pour reconnaître un torrent comme le
  leur. Piste de simplification pour la mise en seed (sous-projet 6), pas
  encore vérifiée en conditions réelles — le dépôt manuel du `.torrent`
  re-signé reste la voie documentée pour l'instant.

- **Configuration globale migrée vers Réglages** (retour utilisateur,
  2026-09-07) : le panneau "Configuration globale" (Sonarr/Radarr/
  qBittorrent/mise en scène/mappings de chemins, plus la nouvelle clé API
  TMDB) quitte la page Bibliothèque pour la page Réglages — ces réglages
  ne sont pas liés au profil de tracker actif. La page Bibliothèque garde
  uniquement le panneau "Configuration du profil" (clé/URL/adresse
  d'annonce du tracker, namespacées par profil).

- **Vérification SSL qBittorrent désactivable** (retour utilisateur,
  2026-09-07) : la connexion à un WebUI qBittorrent en HTTPS local
  échouait systématiquement (`certificate verify failed: self-signed
  certificate`) — httpx vérifie les certificats TLS par défaut, ce que
  ne satisfait jamais un certificat auto-signé, très courant sur un
  réseau domestique/privé. Nouvelle case à cocher "Vérifier le
  certificat SSL de qBittorrent" (activée par défaut — l'utilisateur
  l'assouplit explicitement pour SON instance, jamais désactivé
  silencieusement).

- **Description BBCode d'upload enrichie** (retour utilisateur, 2026-09-07)
  : le gabarit par défaut (`upload_description.j2`) affichait beaucoup
  moins d'informations que celles réellement disponibles — `audio_languages`
  était même câblé en dur à `[]`, jamais rempli. Ajout de la date de
  sortie, la durée, la classification, le studio/la chaîne (confirmés
  disponibles sur Radarr/Sonarr en conditions réelles, `releaseDate`/
  `runtime`/`certification`/`studio`/`network`), des vraies langues
  audio/sous-titres et du débit vidéo (extraits du fichier réel via
  MediaInfo, jamais utilisés jusqu'ici), et du nom de release/team/nombre
  de fichiers/taille totale. Pas de "pays de production" — absent des
  deux API, jamais deviné.

- **Généralisation tracker-agnostique** (AUTOMATION.md, sous-projet 4b) :
  les quatre dernières valeurs spécifiques à C411 câblées en Python
  (codes de catégorie Torznab, barème de taille de pièce torrent, codes
  de langue MediaInfo pour le préfixe MULTI, noms des champs
  d'identifiants) déménagent dans une nouvelle section `tracker` du
  profil (`rules.json`), lue par `nfogen/tracker_profile.py`. Les
  identifiants de tracker (`gapscan_config_store.py`) sont désormais
  namespacés par profil (compat ascendante sans script de migration :
  les anciens champs plats continuent de fonctionner pour `c411`).
  `c411_client.py` renommé en `torznab_client.py` (le protocole était
  déjà générique, seul le nom trompait). Côté frontend, un
  `ProfileContext` partagé pilote un **sélecteur de profil unique dans
  l'en-tête** (remplace le "Scan C411" en dur et le sélecteur local de
  "Générer") ; le panneau "Préparer l'upload" garde un override de
  profil propre à chaque média, indépendant du profil actif global.
- **Mise en scène de fichiers + création de `.torrent`**
  (`nfogen/file_staging.py`, `nfogen/torrent_builder.py`) : hardlink avec
  repli copie si périphérique différent (jamais de modification du fichier
  source), création de torrent conforme C411 via `torf` — deuxième brique
  du pipeline d'automatisation upload (voir [AUTOMATION.md](AUTOMATION.md)).
- **Proposition de `release_name` agnostique du tracker** : normalisation de
  la source et des codecs vidéo/audio entièrement pilotée par profil
  (`rules.json` — `source_aliases`/`video_codec_aliases`/
  `audio_codec_aliases`), plus aucun câblage spécifique à C411 dans
  `name_proposal.py` — troisième brique du pipeline.
- **Détection heuristique d'upscale** (`rules.py:upscale_warnings`) :
  avertit quand le débit réel (bits-par-pixel) est anormalement bas pour le
  codec annoncé dans le `release_name`, indice de source ré-encodée en une
  résolution supérieure sans vrai gain de détail. Seuils configurables par
  profil, jamais bloquant.
- **Orchestration nommage → mise en scène + `.torrent`**
  (`nfogen/upload_prep.py`) : à partir de chemins locaux résolus, calcule
  un nom de release par groupe (groupement automatique par tag d'équipe
  détecté — un pack assemblé depuis plusieurs releases devient plusieurs
  uploads distincts), avec un aperçu sans écriture disque avant toute mise
  en scène. Bouton "Préparer l'upload" sur la page GapScan. Quatrième
  brique du pipeline d'automatisation.
- **Génération du `.nfo` intégrée à "Préparer l'upload"** : `commit_upload`
  génère et met en scène un `.nfo` (un seul par groupe, même pour un pack
  multi-fichiers) à côté du média et du `.torrent`, en réutilisant le
  moteur `nfogen.generate()` existant — aucune génération manuelle
  séparée nécessaire.
- **Filtre Type + pagination serveur sur GapScan** : `GET /gapscan/results`
  accepte maintenant `media_type`/`genre` (Animé/Documentaire, dérivé de la
  catégorie C411 du match trouvé) en plus du filtre statut existant, avec
  pagination côté serveur (`page`/`page_size`) — supporte des
  bibliothèques de 1000+ titres sans tout charger d'un coup. Un seul menu
  "Type" côté frontend (Films, Séries, Films d'animation, Séries animées,
  Documentaires films/séries) plutôt que deux menus séparés à combiner.
- **Titre corrigeable dans "Préparer l'upload"** : le titre déduit du nom
  de fichier ne correspond pas toujours au titre officiel attendu par le
  tracker (ex. "A Guy And A Girl" au lieu de "Un Gars, Une Fille") — champ
  éditable + bouton "Recalculer" avant confirmation (`title_override`,
  jusqu'ici indisponible), **pré-rempli avec le titre déjà connu**
  (Sonarr/Radarr) plutôt que de repartir du nom de fichier. Ponctuation
  naturelle retirée entièrement à la normalisation, jamais convertie en
  point ; caractères accentués translittérés (`é` → `e`, pas supprimés) ;
  chaque mot du titre capitalisé (convention scene).

### Corrigé

- **Bibliothèque très lente** (retour utilisateur, 2026-09-08 : "5 à 10
  secondes" au chargement, "5 à 10 secondes de plus" à chaque frappe de
  recherche) — deux causes réelles cumulées, identifiées par débogage
  systématique (pas devinées) :
  - **Zéro debounce côté frontend** : le champ recherche relançait un
    appel `GET /gapscan/library` complet à **chaque frappe**. Recherche
    désormais debouncée (400ms, `LibraryPage.tsx`).
  - **Zéro cache côté backend, N+1 réel** : `gapscan_library.list_library()`
    recalculait tout depuis Radarr/Sonarr à chaque appel, et
    `SonarrClient.list_season_files()` fait un appel HTTP **par série**
    (`list_episode_files`) — coûteux sur une grosse bibliothèque. Nouveau
    cache en mémoire, courte durée (30s), invalidé immédiatement par un
    scan qui vient de se terminer (`nfogen/api.py:_cached_library_items`).

### Ajouté

- **AV1 reconnu comme codec vidéo** dans le profil c411
  (`video_codec_aliases`) : n'était pas listé, laissant le champ
  `video_codec` vide (et le champ manquant révélait au passage le bug du
  point traînant avant `-TEAM` corrigé ci-dessous).

### Ajouté

- **Avertissement "marqueur de qualité manquant"** (`rules.py:source_marker_warnings`,
  nouvelle clé `source_marker_checks` dans `rules.json`) : un BluRay dont
  le débit vidéo réel passe sous un seuil configuré (profil c411 : 8000
  kb/s) sans le marqueur attendu (`HDLight`) déjà présent dans le nom est
  signalé avant confirmation — incident réel, upload C411 refusé
  ("le débit vidéo … est inférieur au seuil … ajoute HDLight"). Jamais
  bloquant, même esprit que l'heuristique anti-upscale existante.

### Ajouté

- **Envoi vers C411 sous forme de brouillon** (AUTOMATION.md, sous-projet
  5) : nouveau bouton "Envoyer à C411" dans "Préparer l'upload", visible
  après confirmation locale (sous-projet 4) — crée (ou met à jour) un
  **brouillon** via `POST`/`PATCH /api/user/drafts`, jamais une
  soumission réelle : un brouillon reste privé, lié au compte, et
  nécessite une finalisation manuelle sur le site C411 (aucun endpoint
  "soumettre" n'existe côté API). Description BBCode générée depuis un
  nouveau gabarit (`upload_description.j2`) alimenté par des métadonnées
  Radarr/Sonarr récupérées **à la demande** (`get_movie_details`/
  `get_series_details`, jamais pendant le scan GapScan). Catégorie/
  sous-catégorie/options C411 calculées depuis le `release_name` déjà
  confirmé (réutilise `rules.captures()`) via un mapping déclaratif par
  profil (`rules.json` → `tracker.upload`). Vérification anti-doublon
  best-effort (`GET /api/torrents/by-tmdb`) avant l'envoi, jamais
  bloquante — dégrade en avertissement pour les séries (pas d'identifiant
  TMDB connu aujourd'hui) ou en cas d'échec réseau.
- **"Confirmer" s'exécute en tâche de fond avec suivi de progression**
  (AUTOMATION.md, sous-projet 4c) : la mise en scène (copie, quand le
  hardlink est impossible entre volumes différents) et la génération du
  `.torrent` (hash complet du contenu) pouvaient bloquer la page sans
  retour pendant plusieurs minutes sur un gros fichier — retour
  utilisateur, 2026-09-04. Désormais une tâche de fond suivie en
  pourcentage précis pour chaque étape (copie, `.nfo`, hash torrent),
  plusieurs tâches possibles en parallèle, annulable à tout moment.
  Nouvel encart "Transferts en cours" sur la page GapScan, indépendant du
  panneau d'upload — visible même après un rechargement de page.
- **Bibliothèque locale et scan ciblé** (AUTOMATION.md, sous-projet 8) :
  nouvelle vue "Bibliothèque" (`/library`), séparée de "Scan C411" —
  inventaire Sonarr/Radarr brut via `GET /gapscan/library`, **zéro appel
  tracker**, rechargement quasi instantané même sur une grosse
  bibliothèque. Filtres (recherche texte, type, genre **Radarr/Sonarr**,
  ajouté depuis N jours, déjà traité), sélection multiple, bouton
  "Vérifier sur le tracker (N sélectionnés)" qui lance un scan **restreint**
  à cette sélection (`POST /gapscan/run` gagne un champ `selection`, des
  clés stables `movie_key`/`series_key` réutilisées entre les deux
  fonctionnalités) — évite de rescanner toute la bibliothèque pour
  vérifier un seul titre ajouté récemment. Historique persistant des
  titres déjà confirmés/envoyés (`nfogen/upload_history_store.py`), jamais
  basé sur le contenu du dossier staging. Le scan bulk existant ("Lancer
  un scan") reste inchangé et coexiste avec le scan ciblé.
- **Fusion de "Scan C411" dans "Bibliothèque"** (retour utilisateur,
  2026-09-06 : "ça fait doublon") : une seule page (`/library`)
  désormais — elle affiche le statut du **dernier scan connu** pour
  chaque titre ("Non vérifié" sinon, sans jamais réinterroger le
  tracker juste pour l'afficher), garde tous les filtres des deux
  anciennes pages (recherche, type, genre bibliothèque **et** genre
  tracker — distincts —, statut, ajouté depuis, déjà traité), la
  configuration Sonarr/Radarr/tracker, le scan complet (bulk) et le scan
  ciblé (sélection) — qui reste désormais sur place au lieu de rediriger
  vers une autre page.
- **Intégration qBittorrent — mise en seed après upload** (AUTOMATION.md,
  sous-projet 6) : nouvelle file d'attente "À mettre en seed"
  (`/seed-queue`) pour les titres déjà envoyés à C411 en attente du
  `.torrent` re-signé (récupération confirmée impossible à automatiser —
  l'endpoint C411 exige une session navigateur, pas la clé API — import
  manuel donc). nfogen l'ajoute alors à qBittorrent, pointé sur le
  contenu déjà mis en scène (jamais un nouveau transfert), même
  longtemps après le Confirmer d'origine. La même page gagne une section
  **"En cours de seed"** (lecture seule, `GET /gapscan/seed-status`) :
  nom, taille, progression, ratio, état et vitesse d'envoi de chaque
  torrent actif sur qBittorrent (retour utilisateur, 2026-09-06 — "je
  voudrais s'avoir ce que je seed actuellement via mon qbit").
- **Journal en direct d'un scan** : sous la barre de progression,
  affichage des derniers titres traités (titre, statut) — ne se vide
  plus tout seul à la fin du scan (reste consultable après coup), seul
  un nouveau scan ou le bouton "Vider les logs" le réinitialise (retour
  utilisateur, 2026-09-06).

### Corrigé

- **"Débit vidéo" absent du `.nfo`, upload C411 rejeté** : `pymediainfo`
  faisait une analyse partielle (`parse_speed=0.5`, valeur par défaut) qui
  n'isole pas toujours la taille du flux vidéo seul sur un encodage CRF
  (HandBrake) à plusieurs pistes audio — le champ "Bit rate" de la section
  Video manquait alors totalement, faisant échouer la description
  "Générée automatiquement" de C411 côté modération. Analyse complète
  forcée (`parse_speed=1.0`) pour la génération de `.nfo` et l'extraction
  structurée (`video_bit_rate`, consommée par l'heuristique anti-upscale —
  qui pouvait rester silencieusement inactive pour la même raison).
- **Point trainant avant le tiret du tag d'équipe** quand un champ du
  gabarit de nom est vide (ex. codec vidéo non détecté dans le nom de
  fichier) : `...DTS.5.1.-LAZARUS` au lieu de `...DTS.5.1-LAZARUS`. C411
  attend le tag d'équipe collé directement au dernier champ, jamais
  précédé d'un point (`name_proposal.py`).
- **Titre/aperçu périmés en ouvrant "Préparer l'upload" sur une ligne
  différente sans fermer la précédente** : React réutilisait la même
  instance du panneau, gardant le titre corrigé et l'aperçu de la ligne
  d'avant au lieu de repartir de la nouvelle.
- **"Calcul de l'aperçu" jusqu'à ~10 minutes** : régression introduite par
  le correctif "Débit vidéo" ci-dessus — forcer `parse_speed=1.0`
  systématiquement faisait relire l'intégralité de chaque fichier à
  chaque extraction MediaInfo (coûteux sur un NAS pour un gros fichier),
  même quand l'analyse rapide (`0.5`, défaut) donnait déjà un débit vidéo
  exploitable. Corrigé : analyse rapide d'abord, analyse complète
  seulement si le débit vidéo manque réellement (retour utilisateur,
  2026-09-04).
- **GapScan classait à tort des titres en "Qualité supérieure
  disponible"** quand une release C411 strictement équivalente existait
  déjà (`quality.py:SOURCE_RANK`) : une version locale scene taguée
  `WEB-DL` était comparée à une release C411 taguée `WEB` comme si
  c'étaient deux sources différentes — alors que C411 normalise
  WEBDL/WEB-DL/WEBRip vers `WEB` à l'upload (voir `source_aliases`).
  Incident réel : Van Wilder 3 (2009), déjà uploadé par l'utilisateur
  lui-même, signalé comme gap.
- **Nom proposé sans tag de langue malgré des pistes FR/EN réelles dans le
  fichier** (`upload_prep.py`) : `preview_upload` déduit maintenant un
  indice de langue depuis les vraies pistes audio détectées par MediaInfo
  quand le nom de fichier n'en porte aucun (plusieurs langues → indice
  combiné pour déclencher le préfixe `MULTI` attendu par C411).
- **Un scan "Films seulement"/"Séries seulement" effaçait l'autre type**
  déjà scanné précédemment (`run_gapscan`) — `only` ne devait restreindre
  que ce qui est réinterrogé côté C411, jamais ce qui est conservé du
  dernier scan.
- **`scripts/install.sh` n'installait jamais l'extra `automation`** (le
  paquet `torf`, nécessaire pour générer le `.torrent`) — toute
  installation faite via ce script (ou `update.sh`, qui l'appelle)
  affichait "Génération de .torrent indisponible : pip install
  nfogen[automation]" dès qu'on cliquait sur "Confirmer" dans "Préparer
  l'upload", sans que rien ne le signale avant ce moment précis (retour
  utilisateur, 2026-09-06).
- **Aucun dossier de mise en scène écrivable par défaut** : sans
  configuration manuelle de `staging_dir`, rien n'empêchait de pointer par
  erreur vers le NAS source (accédé en LECTURE SEULE, voir AUTOMATION.md
  sous-projet 1) — `[Errno 30] Read-only file system` au moment de
  "Confirmer" (retour utilisateur, 2026-09-06). `scripts/install.sh` crée
  désormais `/var/lib/nfogen/staging` (même traitement que les profils :
  jamais touché par une mise à jour) et le pré-remplit dans
  `gapscan_config.json` UNIQUEMENT si aucun `staging_dir` n'est déjà
  choisi.
- **"Confirmer" plantait avec `[Errno 17] File exists`** quand un fichier
  restait dans le dossier de mise en scène après un essai précédent
  (retour utilisateur, 2026-09-06). `commit_upload()` s'appuie désormais
  sur l'historique "déjà traité" (sous-projet 8) pour décider : un titre
  jamais confirmé/envoyé avec succès est régénéré sans risque (toujours
  depuis la source locale déjà sur le NAS, **jamais un nouveau
  téléchargement**) ; un titre déjà confirmé/envoyé — potentiellement en
  cours de seed — fait lever un message d'erreur clair au lieu d'un
  écrasement silencieux (l'intégration qBittorrent/Transmission, sous-projet
  6, n'existe pas encore pour vérifier réellement l'état de seed).
- **Un fichier déjà mis en scène se faisait intégralement re-copier**
  depuis le NAS à chaque nouvelle tentative de "Confirmer" — régression
  du correctif ci-dessus : sur un montage réseau où le hardlink est
  impossible (repli copie complète), régénérer un dossier de mise en
  scène déjà présent rejouait la copie en entier, ressenti par
  l'utilisateur comme un re-téléchargement ("il me re télécharge les
  mkv", retour utilisateur, 2026-09-06). `stage_file`/`stage_files`
  reconnaissent désormais un fichier déjà en place et de la même taille
  que sa source : ni hardlink ni copie refaits dans ce cas, régénération
  réservée au vrai déchet (taille différente).
- **"Confirmer" plantait encore avec un `File exists` brut** quand le
  `.torrent` d'un essai précédent restait dans le dossier de mise en
  scène (retour utilisateur, 2026-09-06) — le correctif précédent ne
  protégeait que le fichier média mis en scène : `torf` (génération du
  `.torrent`) refuse nativement d'écraser un fichier existant
  (`torf.WriteError`), jamais intercepté jusqu'ici. `build_torrent()`
  gagne le même `overwrite` que `stage_file`, traduit désormais en
  message clair — un titre déjà confirmé/envoyé voit aussi son `.torrent`
  et son `.nfo` protégés (jamais retouchés), comme le fichier média.
- **"Envoyer à C411" n'attachait jamais `.torrent`/`.nfo` au brouillon**
  (retour utilisateur, 2026-09-06, quatre essais réels successifs,
  chacun vérifié en conditions réelles) : le corps JSON de `POST`/`PATCH
  /api/user/drafts` envoyait `.torrent`/`.nfo` sous les clés `torrent`/
  `nfo` (titre/description corrects, fichiers ignorés) ; un essai en
  `multipart/form-data` a tout cassé (titre compris — cet endpoint
  n'accepte pas le multipart, annulé) ; renommer les clés en
  `torrentFile`/`nfoFile` (déduites d'un brouillon vide relu via l'API)
  ne suffisait toujours pas, ni en simple chaîne base64, ni en objet
  `{"name": ..., "data": ...}` (déduit d'un brouillon web réel relu).
  **Format réel confirmé** : des champs **plats**
  `torrentFileName`/`torrentFileData` et `nfoFileName`/`nfoFileData` —
  l'API restructure ces champs plats en objets imbriqués à la lecture
  (asymétrie écriture/lecture jamais documentée). `create_draft()`/
  `update_draft()` gagnent `torrent_filename`/`nfo_filename`.
- **Brouillon toujours nommé "Brouillon sans titre" sur le site C411**
  (retour utilisateur, 2026-09-06) — le champ `name` (libellé affiché
  dans la liste des brouillons, distinct du `title`) n'était jamais
  envoyé, rendant les brouillons impossibles à distinguer entre eux.
  Aligné sur le titre de la release.
- **Vérification anti-doublon C411 jamais effectuée pour les séries** :
  l'avertissement "identifiant TMDB inconnu pour ce média" s'affichait
  systématiquement pour toute série (retour utilisateur, 2026-09-06).
  Supposé à tort être une limitation permanente de Sonarr (identification
  par TVDB) — **infirmé en conditions réelles** : Sonarr expose bien un
  `tmdbId` par cross-reference (confirmé sur une vraie instance,
  `"tmdbId": 63174` pour Lucifer, à côté de son `tvdbId`), simplement
  jamais lu par nfogen jusqu'ici. `sonarr_client.py`/`gapscan.py`/
  `gapscan_library.py` le récupèrent désormais — la vérification
  anti-doublon fonctionne pour une série comme pour un film.

### Modifié

- **Mise en page plus large** : le conteneur principal (toutes les pages)
  passe de 1024px à 1280px de large — évite les badges/actions qui
  retombaient à la ligne sur le tableau GapScan.

## [2.0.0] - 2026-08-27

Première version réellement suivie : capture l'état complet du projet à
ce jour, pas un delta depuis `0.1.0` (jamais tenu à jour). Bump majeur
pour marquer ce point de départ, pas une rupture de compatibilité isolée.

### Ajouté

- **Génération de NFO pilotée par profils** (`rules.json` + templates
  Jinja2) : vidéo (MediaInfo), audio, jeux, ebook, impression 3D. Profil
  C411 fourni par défaut, remplaçable/surchargeable.
- **Proposition automatique de `release_name`** à partir des noms de
  fichiers seuls (packs, tags de langue/équipe, résolution/codec/source).
- **Extraction vidéo côté navigateur** (WebAssembly, MediaInfo.js) : pas
  d'upload nécessaire pour générer un NFO vidéo.
- **API HTTP** (FastAPI) + **frontend** (React/Vite/Tailwind) : génération,
  gestion de profils (CRUD + export/import `.zip`), réglages.
- **Authentification** : token API partagé et/ou comptes nommés
  (PBKDF2-HMAC-SHA256, sessions cookie httpOnly, anti-bruteforce).
- **GapScan** : compare la bibliothèque Sonarr/Radarr au catalogue C411
  (API Torznab) pour repérer les candidats à l'upload — détection de gap
  par qualité/langue, repli par titre (y compris titres alternatifs FR),
  persistance des résultats sur disque, scan incrémental avec expiration,
  scan par catégorie (films/séries), export CSV.
- **Résolution de chemins NAS** (`nfogen/path_mapping.py`) : mapping de
  chemins distant/local par connexion Sonarr/Radarr, validation à chaque
  scan — première brique du pipeline d'automatisation upload (voir
  [AUTOMATION.md](AUTOMATION.md)).
- **Déploiement** : script natif Debian/Ubuntu (`scripts/install.sh`,
  idempotent, TLS optionnel via Caddy) et image Docker.
- **Sécurité** : plusieurs audits successifs (ReDoS, timing attacks,
  TOCTOU, fuite de clé API, CSRF, en-têtes HTTP) — historique complet
  dans [ROADMAP.md](ROADMAP.md).

## [0.1.0] - 2026-06-28

Tag initial, jamais suivi de mises à jour de version ni de changelog.
