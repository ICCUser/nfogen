# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnage [SemVer](https://semver.org/lang/fr/) (`MAJOR.MINOR.PATCH`).

`v0.1.0` (2026-06-28) avait été taggé une seule fois puis jamais tenu à
jour (70 commits sans version ni changelog derrière) — `2.0.0` marque le
vrai début du suivi de version, pas une continuité directe de `0.1.0`.

## [Non publié]

### Ajouté

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
  point.

### Corrigé

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
