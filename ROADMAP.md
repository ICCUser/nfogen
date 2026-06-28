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
| Authentification | Token API simple (`NFOGEN_API_TOKEN`). À revoir pour un usage multi-utilisateurs (voir idées ci-dessous). |
| Stack frontend | React + Vite (SPA), consomme l'API FastAPI existante. |
| Déploiement | Repo unique (front + back) ; script natif Debian/Ubuntu (`scripts/install.sh`) en priorité, image Docker tout-en-un en option. |

## Idées / prochaines pistes

- **Droits d'accès multi-utilisateurs** (priorité actuelle) : génération de
  NFO ouverte à tous, gestion des profils réservée aux admins. Le token
  unique actuel ne distingue pas ces deux niveaux — il faudra des rôles
  (admin / standard), probablement plusieurs tokens ou de vrais comptes.
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
- **Token API en `localStorage`** (alerte CodeQL "Clear text storage of
  sensitive information", `frontend/src/api/settings.ts`) : accepté pour
  l'instant — aucune faille XSS présente dans le code actuel (pas de
  `dangerouslySetInnerHTML`/`innerHTML`/`eval`) donc pas de vecteur de vol
  démontré, et un vrai correctif (cookie de session `httpOnly` posé par le
  serveur) demande un flux de login qui n'existe pas encore. À traiter en
  même temps que les droits d'accès multi-utilisateurs ci-dessus, pas
  séparément.
- **`rules.json` : motifs regex admin-fournis sans timeout** (`nfogen/rules.py`,
  `re.search(token["pattern"], value)`) — un motif pathologique (ReDoS)
  bloquerait le processus. Accepté pour l'instant : écrire/modifier un
  `rules.json` exige déjà le token API (`require_token`), donc pas exploitable
  sans lui. À revoir avec les droits d'accès multi-utilisateurs (un rôle
  "admin" moins fiable qu'aujourd'hui changerait l'évaluation du risque).

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
