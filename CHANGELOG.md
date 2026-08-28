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
