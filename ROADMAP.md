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
- **`rules.json` : motifs regex admin-fournis sans timeout** (`nfogen/rules.py`,
  `re.search(token["pattern"], value)`) — un motif pathologique (ReDoS)
  bloquerait le processus. Accepté pour l'instant : écrire/modifier un
  `rules.json` exige déjà une authentification admin (`require_token`,
  token ou compte nommé), donc pas exploitable sans elle. Plusieurs comptes
  admin (voir ci-dessus) ne changent pas ce raisonnement (même rôle, même
  niveau de confiance) ; à revoir si des rôles moins fiables que "admin"
  sont introduits un jour.

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
