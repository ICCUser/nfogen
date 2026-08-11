# Roadmap nfogen

`nfogen` génère des fichiers NFO pilotés par des profils (génériques, un
profil = une convention de tracker), utilisable en CLI, en bibliothèque
Python, en API HTTP, ou via le frontend web. Profil d'exemple livré avec le
paquet : C411. Ce document liste les idées futures — pour l'historique
détaillé des changements, voir `git log`.

## Décisions verrouillées

| Sujet | Décision |
|---|---|
| Frontend | Édite `rules.json` + templates des profils existants (catégories fixes). Pas de moteur de rendu inédit. |
| Stockage des profils | Fichiers sur disque (`NFOGEN_PROFILES_DIR`), un profil = un dossier. Export/import `.zip`. Pas de base de données. |
| Authentification | Deux mécanismes au choix, combinables : un token API partagé (`NFOGEN_API_TOKEN`, via `Authorization: Bearer`) et/ou des comptes nommés (`NFOGEN_ACCOUNTS_FILE`, un seul rôle "admin", pas de permissions par profil — voir `nfogen/accounts.py`). Les deux passent par `POST /login`, qui pose un cookie de session `httpOnly` (jamais lisible en JS) ; `require_token` accepte ce cookie ou l'en-tête `Authorization`. Protège toujours `/profiles/store*` et `/accounts*` ; protège `/generate*`/`/propose-name` seulement si `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1` (génération ouverte à tous par défaut). Pas de base de données : comptes stockés en JSON (mots de passe hashés PBKDF2-HMAC-SHA256), sessions en mémoire (perdues au redémarrage), throttle anti-bruteforce par compte (5 essais / 30s). |
| Stack frontend | React + Vite (SPA), consomme l'API FastAPI existante. |
| Déploiement | Repo unique (front + back) ; script natif Debian/Ubuntu (`scripts/install.sh`) en priorité, image Docker tout-en-un en option. |

## Idées / prochaines pistes

- **Droits d'accès multi-utilisateurs** : fait. Décision (après discussion
  explicite sur l'intérêt d'une vraie BDD pour un déploiement multi-tenant) :
  scope réduit à plusieurs admins du **même** tracker, un seul rôle
  (admin oui/non, pas de permissions par profil), pas de base de données —
  cohérent avec l'architecture 100% fichiers du reste du projet. Comptes
  nommés (`NFOGEN_ACCOUNTS_FILE`, `nfogen/accounts.py`), amorçage du premier
  compte sans authentification uniquement si l'instance est entièrement
  ouverte, suppression d'un compte révoque immédiatement ses sessions
  actives, UI dédiée dans Réglages (`SettingsPage.tsx`). Pistes encore
  ouvertes si le besoin grandit : rôles différenciés, permissions par
  profil, multi-tenant (plusieurs trackers isolés sur une même instance) —
  nécessiterait alors de revisiter le refus de base de données ci-dessus.
- CLI : pas d'équivalent des routes `/profiles/store*` (gérer un profil
  utilisateur sans passer par l'API).
- Pas de verrou sur les écritures concurrentes de `profile_store.py` (deux
  `PUT` simultanés sur le même profil) — à revisiter si l'usage multi-
  utilisateurs s'intensifie.
- Pas de tests automatisés pour le frontend.
- Extraction côté navigateur (sans upload) limitée à la catégorie vidéo ;
  audio/jeux/ebook/3D passent encore par l'upload classique.
- `name_proposal.py` : la saison/l'épisode restent déterminés en priorité
  par le nom de fichier (pas le tag `Title` embarqué) — à revoir si un tag
  contenant une numérotation différente est rencontré en pratique.
- **Profils comme extensions** : à terme, considérer ne plus livrer C411
  avec le paquet par défaut (zéro ou peu de profils nativement), et le
  distribuer plutôt comme un `.zip` téléchargeable séparément (le mécanisme
  d'import existe déjà, `POST /profiles/store/{name}/import`) — pour bien
  marquer que c'est un exemple/point de départ, pas "le" profil de nfogen.
- **`rules.json` : motifs regex admin-fournis sans timeout** : fait (audit du
  2026-08-11, voir plus bas) — exécution via RE2, plus un risque accepté.

## Audit sécurité du 2026-06-28 (suite des alertes CodeQL)

À la demande explicite de prioriser la sécurité même au prix des bonnes
pratiques, relecture complète du backend, du frontend, des scripts de
déploiement et des bornes de dépendances. Corrigé :

- **Injection d'en-tête HTTP (`Content-Disposition`)** : Starlette ne filtre
  pas les valeurs d'en-tête (CRLF, guillemets) avant de les écrire ; seul
  uvicorn le fait (vérifié manuellement, protocole HTTP). Un `release_name`
  utilisateur pouvait devenir le nom de fichier d'un profil
  (`filename_template`) et finir directement dans l'en-tête. Ajout de
  `_header_safe()` (`nfogen/api.py`) : neutralise caractères de contrôle,
  guillemets et antislash avant toute utilisation dans un en-tête, sans
  dépendre du comportement d'un serveur ASGI particulier.
- **Upload multipart, nom de fichier `".."`/`"."`** : `Path("..").name`
  vaut littéralement `".."` (pas une chaîne vide) — un fichier uploadé
  nommé `".."` écrivait dans le PARENT du dossier temporaire
  (`IsADirectoryError` non rattrapée). Garde-fou explicite ajouté dans
  `generate_upload`.
- **Plafond d'upload contournable (`NFOGEN_MAX_UPLOAD_MB`)** : le middleware
  `_limit_upload_size` ne contrôlait que le `Content-Length` *déclaré* par
  le client — un client malhonnête (ou un transfert sans `Content-Length`)
  le contournait entièrement et pouvait saturer le disque. Le total des
  octets réellement écrits est désormais compté pendant le streaming dans
  `generate_upload` et compare à la même limite, indépendamment de l'en-tête.
- **Image Docker exécutée en root** : ajout d'un utilisateur système dédié
  (`USER nfogen` dans le `Dockerfile`), même logique que l'utilisateur de
  service de `scripts/install.sh` — réduit l'impact d'une éventuelle
  exécution de code dans le conteneur.
- **Plancher de version `jinja2`** relevé à `>=3.1.6` (`pyproject.toml`) :
  versions antérieures vulnérables à des contournements du
  `SandboxedEnvironment` utilisé par `nfogen/render.py` (CVE-2024-56326,
  CVE-2025-27516).

Revérifié sans correctif nécessaire : `nfogen/extract.py`, `nfogen/cli.py`,
`nfogen/registry.py` (pas d'entrée utilisateur non validée dans un contexte
sensible), le frontend (`frontend/src/`, aucun `innerHTML`/`eval`, WASM
mediainfo.js servi en local et non depuis un CDN), `scripts/install.sh` /
`update.sh` (déjà durcis : utilisateur système dédié, `chmod 600` sur
l'env file, hardening systemd), `npm audit` (0 vulnérabilité côté frontend).

Deux correctifs supplémentaires, après un rescan CodeQL post-push :

- **Faux positifs CodeQL persistants** (`py/path-injection`) sur les deux
  protections ci-dessus (`serve_frontend`, `write_profile`) : CodeQL ne
  modélise ni `Path.is_relative_to()` ni un contrôle d'appartenance à une
  liste fixe comme barrière de taint-tracking. Réécrits dans des idiomes
  plus largement reconnus : `os.path.realpath()` + préfixe avec séparateur
  final (`nfogen/api.py`), et table de correspondance figée
  `_TEMPLATE_FILENAMES` construite depuis `CATEGORIES` — `category` ne sert
  plus qu'à indexer cette table, jamais à composer une chaîne de chemin
  (`nfogen/profile_store.py`). Comportement inchangé (tests de régression
  existants), seulement la façon de le prouver statiquement.
- **Token API en `localStorage`** (alerte CodeQL "Clear text storage of
  sensitive information", ex-`frontend/src/api/settings.ts`) : **corrigé**.
  Vérifié au préalable que la suggestion Copilot Autofix (passer à
  `sessionStorage`) n'aurait pas fermé l'alerte (CodeQL modélise les deux
  comme sinks identiques, classe `WebStorageSink` — confirmé dans la source
  CodeQL). Vrai correctif à la place : `POST /login` vérifie le token et
  pose un cookie de session `httpOnly` (jamais lisible en JavaScript,
  `nfogen/api.py`) ; `require_token` accepte ce cookie en plus de l'en-tête
  `Authorization` (CLI/scripts inchangés) ; `GET /auth/status` /
  `POST /logout` complètent le flux. Frontend (`SettingsPage.tsx`) : vrai
  formulaire connexion/déconnexion, plus aucun token en `localStorage`.
  Vérifié dans un vrai navigateur (Playwright) : `localStorage` reste vide
  avant/après connexion, `document.cookie` ne révèle pas le cookie de
  session, génération NFO acceptée après connexion / refusée (401) sans.
  Nouvelles variables d'environnement : `NFOGEN_COOKIE_SECURE`,
  `NFOGEN_COOKIE_SAMESITE` (voir README.md).

## Audit sécurité + fonctionnel du 2026-08-11

Audit complet (backend, frontend, dépendances, CI) à la demande explicite de
prioriser la sécurité. Corrigé :

- **ReDoS sur les motifs regex admin (`rules.json -> tokens[].pattern`)** :
  l'item "accepté pour l'instant" ci-dessus est refermé, avec un changement
  d'approche par rapport à l'idée initialement explorée (détection
  heuristique par chronométrage à l'écriture, abandonnée : dépendante de la
  vitesse de la machine et d'une entrée de sonde choisie à l'avance, donc
  potentiellement contournable par un motif qui n'explose que sur une AUTRE
  forme d'entrée). Remplacée par l'exécution de tout motif admin via **RE2**
  (`google-re2`, moteur à automate fini, temps linéaire garanti quel que soit
  le motif, sans backtracking exponentiel possible par construction) —
  aussi bien à la validation d'un profil (écriture/import via
  `profile_store`, ou dépôt direct dans `NFOGEN_PROFILES_DIR`) qu'à
  **chaque génération** (`nfogen/rules.py: errors/warnings/captures`), pas
  seulement à l'écriture. Contrepartie assumée : RE2 ne supporte ni
  lookaround ni back-références (précisément ce qui permettrait un
  backtracking exponentiel) — vérifié : les 6 patterns du profil C411 fourni
  compilent tels quels sous RE2, aucune réécriture nécessaire. La validation
  regex (`validate_regex_patterns`) est désormais appelée depuis un seul
  point d'entrée (`validate_rules_document`), plutôt que dupliquée dans
  `profile_store.write_profile` et `profiles/__init__._load_external_profiles`
  séparément — évite qu'un futur chemin d'enregistrement de profil (ex. une
  commande CLI de gestion de profils, cf. idée ouverte ci-dessus) oublie ce
  contrôle.
- **Amorçage du premier compte admin, course possible (TOCTOU)** :
  `POST /accounts` exécute "vérifier qu'aucun compte n'existe" puis "en
  créer un" — FastAPI exécute les routes synchrones dans un threadpool, donc
  deux requêtes concurrentes pendant la fenêtre de bootstrap pouvaient
  toutes les deux passer le contrôle avant qu'une écriture n'ait eu lieu, et
  créer chacune un compte admin sans authentification. Verrouillé
  (`threading.Lock`, `nfogen/api.py`) ; régression couverte par un test qui
  élargit artificiellement la fenêtre de course pour la rendre
  déterministe (`tests/test_api.py::test_accounts_bootstrap_is_not_a_race`).
- **4 vulnérabilités high côté frontend** (`npm audit`) : `react-router`
  (CSRF-bypass), `postcss` (divulgation de fichier `.map` par traversée de
  chemin), `nanoid` — apparues depuis l'audit du 28/06 (dépendances
  transitives, pas un choix direct du projet). Corrigées par `npm audit fix`
  (bump de `package-lock.json` dans les plages semver déjà déclarées,
  aucun changement de `package.json` nécessaire) ; build (`vite build`) et
  lint (`oxlint`) revérifiés après coup.
- **`_LOGIN_ATTEMPTS`/`_SESSIONS` (`nfogen/api.py`) jamais purgés** : un
  attaquant anonyme pouvait faire grossir `_LOGIN_ATTEMPTS` indéfiniment
  (identifiants distincts sur `/login`, non authentifié par nature) ; une
  session n'expirait jamais côté serveur hors déconnexion/suppression de
  compte/redémarrage. Corrigé par deux mécanismes indépendants : expiration
  de session par inactivité glissante (`NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES`,
  défaut 24h) et par durée de vie absolue non glissante
  (`NFOGEN_SESSION_MAX_LIFETIME_HOURS`, défaut 7 jours — protège même un
  cookie volé réutilisé à intervalles réguliers) ; balayage périodique
  (`_sweep_stale_entries`, au plus une fois toutes les 5 min) qui purge aussi
  les tentatives de connexion inactives depuis plus d'1h. Comparaison du
  token en temps constant étendue à `POST /login` (déjà faite pour
  `require_token`, `hmac.compare_digest`) au passage. Voir README.md pour les
  deux nouvelles variables d'environnement.

Revérifié sans correctif nécessaire (relecture complète du backend, dont
`accounts.py`, `render.py`, `profile_store.py`, `name_proposal.py` — les
motifs de ce dernier sont fixes/non admin-fournis, donc hors du changement
RE2 ci-dessus) : les mêmes composants que l'audit du 28/06, plus `pip-audit`
(aucune CVE connue sur les dépendances backend).

Reste à traiter dans cette même passe (priorité 1, sécurité/robustesse) :
CI qui construit/lint/teste aussi le frontend, `dependabot.yml`, et une
décision sur le rate-limiting de `/generate*`. Voir la suite de cette section
une fois traités.
