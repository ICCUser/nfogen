# Roadmap nfogen

`nfogen` génère des fichiers NFO pilotés par des profils, utilisable en CLI,
bibliothèque Python, API HTTP ou frontend web. Profil d'exemple livré :
C411. Historique détaillé des changements : `git log`.

## Décisions verrouillées

| Sujet | Décision |
|---|---|
| Frontend | Édite `rules.json` + templates des profils existants (catégories fixes). Pas de moteur de rendu inédit. |
| Stockage des profils | Fichiers sur disque (`NFOGEN_PROFILES_DIR`), un profil = un dossier. Export/import `.zip`. Pas de base de données. |
| Authentification | Token API partagé (`NFOGEN_API_TOKEN`) et/ou comptes nommés (`NFOGEN_ACCOUNTS_FILE`, rôle admin unique, `nfogen/accounts.py`). `POST /login` pose un cookie httpOnly ; `require_token` accepte ce cookie ou l'en-tête `Authorization`. Protège toujours `/profiles/store*`/`/accounts*` ; protège `/generate*` seulement si `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1`. Pas de base de données : comptes en JSON (PBKDF2-HMAC-SHA256), sessions en mémoire, throttle anti-bruteforce (5 essais/30s). |
| Stack frontend | React + Vite (SPA), consomme l'API FastAPI existante. |
| Déploiement | Repo unique (front + back) ; script natif Debian/Ubuntu (`scripts/install.sh`) en priorité, image Docker en option. |

## Idées / prochaines pistes

- **Droits d'accès multi-utilisateurs** : fait. Scope réduit à plusieurs
  admins du même tracker, un seul rôle, pas de base de données. Comptes
  nommés (`nfogen/accounts.py`), amorçage du premier compte sans auth
  uniquement si l'instance est entièrement ouverte, suppression révoque les
  sessions actives. Ouvert si le besoin grandit : rôles différenciés,
  permissions par profil, multi-tenant.
- **CLI pour `/profiles/store*`** : fait (`nfogen --profile-store-*`, voir
  README.md).
- **Verrou sur les écritures concurrentes de `profile_store.py`** : fait
  (`_LOCK`, couvre aussi les lectures).
- Pas de tests automatisés pour le frontend.
- Extraction côté navigateur (sans upload) limitée à la vidéo ; audio/jeux/
  ebook/3D passent encore par l'upload classique.
- `name_proposal.py` : saison/épisode déterminés en priorité par le nom de
  fichier (pas le tag `Title`) — à revoir si un cas contraire apparaît.
- **Profils comme extensions** : décision (2026-08-11) — C411 reste livré
  par défaut tant qu'aucun autre profil n'est disponible, à reconsidérer
  dès qu'un deuxième existe. Le `.zip` du profil reste disponible en plus
  (API et CLI, sans surcharge préalable).
- **`rules.json` : motifs regex admin sans timeout** : fait, exécution via RE2.

## Audit sécurité du 2026-06-28 (suite des alertes CodeQL)

- **Injection d'en-tête HTTP** (`Content-Disposition`) : `release_name`
  utilisateur pouvait atteindre un en-tête HTTP sans normalisation.
  `_header_safe()` neutralise caractères de contrôle/guillemets/antislash.
- **Upload multipart, nom de fichier `".."`** : `Path("..").name == ".."`,
  écrivait dans le parent du dossier temporaire. Garde-fou ajouté.
- **Plafond d'upload contournable** : `NFOGEN_MAX_UPLOAD_MB` ne vérifiait
  que le `Content-Length` déclaré. Le total réellement écrit est compté
  pendant le streaming.
- **Image Docker en root** : utilisateur système dédié (`USER nfogen`).
- **`jinja2`** relevé à `>=3.1.6` (contournements de sandbox connus).
- **Faux positifs CodeQL** (`py/path-injection`) : réécrits en idiomes
  reconnus (`os.path.realpath()` + préfixe, table de correspondance figée).
- **Token API en `localStorage`** : remplacé par cookie de session httpOnly
  (`POST /login`), `require_token` accepte le cookie en plus du header.

Revérifié sans correctif nécessaire : `extract.py`, `cli.py`, `registry.py`,
le frontend (aucun `innerHTML`/`eval`, WASM local), les scripts de
déploiement, `npm audit` (0 vulnérabilité à l'époque).

## Audit sécurité + fonctionnel du 2026-08-11

- **ReDoS sur les motifs regex admin** (`rules.json -> tokens[].pattern`) :
  exécution via RE2 (temps linéaire garanti) au lieu d'une heuristique par
  chronométrage. Validation centralisée dans `validate_rules_document`.
- **Course sur l'amorçage du premier compte admin (TOCTOU)** : deux
  requêtes concurrentes pouvaient chacune créer un compte sans
  authentification. Verrouillé (`threading.Lock`).
- **4 vulnérabilités high côté frontend** (`react-router`, `postcss`,
  `nanoid`) : corrigées par `npm audit fix`.
- **`_LOGIN_ATTEMPTS`/`_SESSIONS` jamais purgés** : expiration de session
  par inactivité (`NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES`, défaut 24h) et
  durée de vie absolue (`NFOGEN_SESSION_MAX_LIFETIME_HOURS`, défaut 7j),
  balayage périodique des deux dicts. Comparaison du token en temps
  constant étendue à `POST /login`.
- **CI backend uniquement** : job `frontend` ajouté (`npm ci`/`lint`/`build`).
- **Pas de détection automatique des CVE** : `.github/dependabot.yml`
  (pip, npm, github-actions, hebdomadaire).
- **Pas de protection contre le volume de requêtes sur `/generate*`** :
  `NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE` (défaut illimité), plafond par IP
  partagé entre les 3 routes de génération.

Revérifié sans correctif : `accounts.py`, `render.py`, `profile_store.py`,
`name_proposal.py`, `pip-audit` (aucune CVE backend).

Priorité 1 close. Priorité 2 : voir "Idées / prochaines pistes" ci-dessus.
