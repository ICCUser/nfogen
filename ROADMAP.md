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
- **Tests automatisés pour le frontend** : fait (Vitest + Testing Library,
  `frontend/README.md`). Démarrage ciblé sur la logique pure et testable
  sans risque (`src/api/*`, composants réutilisables génériques) plutôt
  qu'une couverture exhaustive des pages ; à étendre au fil de l'eau.
- Extraction côté navigateur (sans upload) limitée à la vidéo ; audio/jeux/
  ebook/3D passent encore par l'upload classique.
- `name_proposal.py` : saison/épisode déterminés en priorité par le nom de
  fichier (pas le tag `Title`) — à revoir si un cas contraire apparaît.
- **Profils comme extensions** : décision (2026-08-11) — C411 reste livré
  par défaut tant qu'aucun autre profil n'est disponible, à reconsidérer
  dès qu'un deuxième existe. Le `.zip` du profil reste disponible en plus
  (API et CLI, sans surcharge préalable).
- **`rules.json` : motifs regex admin sans timeout** : fait, exécution via RE2.
- **TLS non documenté sur le déploiement natif recommandé** : fait
  (2026-08-25). `NFOGEN_DOMAIN=...` (Caddy + Let's Encrypt, domaine public)
  ou `NFOGEN_LOCAL_TLS=1` (Caddy + certificat auto-signé, serveur local/LAN
  sans domaine ni Internet) ajoutés à `scripts/install.sh`, mutuellement
  exclusifs, persistés dans `nfogen.env`. `uvicorn` bascule sur `127.0.0.1`
  dans les deux cas (Caddy devient le seul point d'entrée réseau),
  `NFOGEN_COOKIE_SECURE=1` automatique. Voir README.md.
- **`rate_limit_generate` ignore les reverse proxy** : fait (2026-08-25).
  `NFOGEN_TRUST_PROXY_HEADERS=1` (désactivé par défaut) fait lire
  `_client_ip()` la valeur la plus a droite de `X-Forwarded-For` (celle
  ajoutee par le reverse proxy immediat, jamais falsifiable par le client
  qui peut pre-remplir l'en-tete lui-meme) au lieu de `request.client.host` —
  couvre a la fois `rate_limit_generate` et le verrou anti-bruteforce du
  login par token (meme fonction partagee). A n'activer que derriere un
  reverse proxy de confiance (Caddy ajoute par `NFOGEN_DOMAIN`/
  `NFOGEN_LOCAL_TLS`) : sans lui, n'importe quel client pourrait usurper
  l'IP de son choix via cet en-tete.
- **Pages frontend du parcours principal sans test d'intégration** : fait
  (2026-08-25). Un test chemin heureux + un test d'echec par page
  (`GeneratePage.test.tsx`, `SettingsPage.test.tsx`) : extraction WASM
  reussie vs repli sur upload classique ; connexion par token reussie vs
  token invalide. Verifies utiles (pas vacuous) par mutation manuelle du
  code avant de les committer : cassage delibere de chaque chemin, test
  correspondant bien mis en echec, puis code restaure.

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

## Correctif de déploiement (2026-08-11)

- **`scripts/install.sh` échouait sur `npm ci`** (`EACCES: /home/nfogen`) :
  l'utilisateur système `nfogen` est créé sans home (`useradd
  --no-create-home`), donc `$HOME` (`/home/nfogen`) n'existe pas et npm ne
  peut pas y écrire son cache. `pip install --no-cache-dir` évitait déjà le
  problème ; npm n'a pas d'équivalent. Corrigé : `HOME` pointe explicitement
  vers `${DATA_DIR}/home` (persistant, créé/chowné avant les étapes
  Python/npm) pour toutes les commandes lancées en tant que `nfogen`
  (`run_as_nfogen`, nouveau helper du script).
- **Page blanche au clic, déploiement natif (`NFOGEN_FRONTEND_DIST`)** :
  `frontend/src/api/settings.ts` défaut sur `/api`, mais `nfogen/api.py`
  monte ses routes SANS préfixe (`/profiles`, `/generate`...). En un seul
  processus (exactement ce que fait `scripts/install.sh`), `/api/profiles`
  tombait silencieusement sur le SPA fallback (`index.html`, 200 OK, mauvais
  contenu) au lieu du JSON attendu — `ProfilesListPage` plantait ensuite
  (`categories.join is not a function`), et sans error boundary, React
  démontait tout l'arbre : page blanche à chaque navigation. Corrigé :
  `DEFAULT_BASE_URL` vaut `""` (même origine) en build de production
  (`import.meta.env.DEV`), `/api` seulement en dev (proxy Vite). Ajout aussi
  d'un `ErrorBoundary` (`src/components/ErrorBoundary.tsx`, remonté à chaque
  changement de route) : un futur bug de rendu affichera un message au lieu
  d'une page blanche silencieuse.
- **CI cassée depuis le premier push de cette session (3 tests sur
  `_sweep_stale_entries`)** : `time.monotonic()` n'a pas de valeur absolue
  garantie (référence de départ arbitraire, ex. démarrage du conteneur) —
  les tests posaient `_last_sweep = 0.0` en supposant `now` "assez grand"
  pour dépasser `_SWEEP_INTERVAL_SECONDS` (300s), vrai sur une machine de dev
  avec de l'uptime, faux sur un runner CI fraîchement démarré (`now` ~118s).
  Corrigé : les tests neutralisent directement `_SWEEP_INTERVAL_SECONDS`
  plutôt que de deviner une valeur de `_last_sweep` "assez ancienne" —
  déterministe quelle que soit la machine. Trouvé via le log CI complet
  fourni par l'utilisateur (accès aux logs bruts impossible via l'API
  GitHub sans droits admin sur le dépôt).
- **`getBaseUrl()` : une URL vide explicitement enregistrée était ignorée** :
  `localStorage.getItem(...) || DEFAULT_BASE_URL` traitait `""` comme "rien
  n'est enregistré" (JS, chaîne vide falsy) et retombait sur le défaut —
  empêchait un utilisateur ayant encore `/api` enregistré (ancien défaut, cf.
  point précédent) de revenir manuellement à "même origine" depuis Réglages.
  Corrigé (`??` au lieu de `||`, `getItem` renvoie `null` — jamais `""` —
  quand la clé est réellement absente). Un ancien `/api` déjà enregistré
  dans le navigateur d'un utilisateur reste prioritaire sur le nouveau
  défaut tant qu'il n'est pas explicitement vidé dans Réglages ; c'est
  attendu (la valeur enregistrée est toujours prioritaire), mais ça peut
  surprendre juste après ce correctif si le navigateur avait déjà visité
  l'instance.

## Revue technique du 2026-08-25 — priorité 1 (dette identifiée par analyse)

Revue à froid (pas un audit de sécurité déclenché par un incident) : relance
complète de la suite de tests + lint + `pip-audit`/`npm audit` sur les deux
stacks (tout au vert), puis lecture ciblée de `nfogen/api.py`/`accounts.py`
et de la chaîne de déploiement. Trois correctifs à faible effort appliqués
immédiatement ; les constats plus coûteux (TLS, reverse proxy, tests
frontend) sont ajoutés à "Idées / prochaines pistes" ci-dessus plutôt que
traités dans la foulée.

- **Verrou anti-bruteforce du login par token partagé entre toutes les IP** :
  `_login_throttle_key(None)` renvoyait toujours la constante `"token"` —
  contrairement au login par compte nommé (verrouillé par identifiant), 5
  échecs sur `/login` en mode token, depuis n'importe quelle IP, verrouillait
  le login par token pour tout le monde pendant 30s. Corrigé : la clé de
  throttle du login par token inclut désormais l'IP cliente
  (`_login_throttle_key(username, client_ip)`), sur le modèle déjà utilisé
  par `rate_limit_generate`.
- **Pas de longueur minimale sur les mots de passe des comptes nommés** :
  `create_account()` ne rejetait qu'un mot de passe vide. Minimum de 8
  caractères ajouté (`accounts._MIN_PASSWORD_LENGTH`), message d'erreur
  explicite.
- **Canal temporel dans `accounts.authenticate()`** : un identifiant inconnu
  retournait immédiatement (`hashed is None`) sans exécuter les PBKDF2
  (~260 000 itérations), contrairement à un identifiant existant avec un
  mauvais mot de passe — écart de temps de réponse mesurable, qui aurait pu
  permettre d'énumérer les comptes existants. Corrigé : comparaison
  systématique contre un hash réel ou factice (`accounts._DUMMY_HASH`), coût
  constant dans les deux cas.

Revérifié sans correctif nécessaire à ce stade : `profile_store.py`,
`rules.py`, `render.py`, dépendances (0 CVE `pip-audit`/`npm audit`), lint
(`ruff`/`oxlint`) et build frontend.

## TLS sur le déploiement natif (2026-08-25) — priorité 2

Suite de la revue technique ci-dessus : `scripts/install.sh` exposait
`uvicorn` en HTTP nu sur le port 8000, sans reverse proxy, y compris pour le
chemin d'installation "recommandé" du README. Deux modes optionnels,
mutuellement exclusifs, ajoutés (aucun des deux : comportement inchangé,
HTTP nu comme avant) :

- **`NFOGEN_DOMAIN=mon-domaine.example`** : installe [Caddy](https://caddyserver.com/)
  (dépôt officiel, même logique que NodeSource déjà utilisée pour Node.js) en
  reverse proxy devant l'API, certificat Let's Encrypt obtenu et renouvelé
  automatiquement. Nécessite un domaine public déjà résolu vers le serveur et
  les ports 80/443 joignables depuis Internet — non vérifié par le script, une
  erreur ACME de Caddy (visible via `journalctl -u caddy`) le signalera sinon.
- **`NFOGEN_LOCAL_TLS=1`** : même reverse proxy Caddy, mais certificat
  auto-signé (`tls internal`, CA locale à Caddy) — aucun domaine public ni
  accès Internet requis, pensé pour un serveur local/LAN qui veut chiffrer le
  trafic sans dépendre de Let's Encrypt. Avertissement navigateur attendu tant
  que le certificat n'est pas importé manuellement côté client.

Dans les deux modes : `uvicorn` bascule de `0.0.0.0` à `127.0.0.1` (Caddy
devient le seul point d'entrée réseau), `NFOGEN_COOKIE_SECURE=1` écrit
automatiquement dans `nfogen.env`. Le choix est persisté dans ce même fichier
(jamais régénéré en entier, seules les clés `NFOGEN_DOMAIN`/
`NFOGEN_LOCAL_TLS`/`NFOGEN_COOKIE_SECURE` sont ajoutées/mises à jour) : `sudo
./scripts/update.sh`, qui ne repasse aucune variable, retrouve le mode déjà
configuré sans action de l'admin. `install.sh` gère `/etc/caddy/Caddyfile` en
entier (écrasé à chaque exécution) — non adapté à une machine où Caddy sert
déjà d'autres sites.

Effet de bord identifié et documenté ci-dessus ("Idées / prochaines
pistes") : une fois un de ces modes actif, `rate_limit_generate` (qui lit
`request.client.host`) voit systématiquement l'IP de Caddy plutôt que celle
du client réel — pas corrigé dans ce lot, volontairement laissé pour la
priorité 3 avec les tests d'intégration frontend.

Aucun test automatisé possible pour `install.sh` (script de provisioning
root, aucun test existant ne le couvre) : logique de résolution/persistance
TLS extraite et rejouée sur 7 scénarios (défaut, activation, relecture sans
variable comme le fait `update.sh`, bascule de mode, conflit des deux
variables, retour explicite au HTTP) dans un harnais isolé, sur le code réel
du script plutôt qu'une réécriture. `bash -n` propre.

## Priorité 3 : en-tête de proxy de confiance + tests frontend (2026-08-25)

Clôture des deux derniers constats de la revue technique.

- **`NFOGEN_TRUST_PROXY_HEADERS=1`** (désactivé par défaut) : `_client_ip()`
  (`nfogen/api.py`, partagée par `rate_limit_generate` et le verrou du login
  par token) lit désormais la valeur la plus à droite de `X-Forwarded-For`
  quand activé, au lieu de toujours utiliser `request.client.host` —
  redevenu nécessaire depuis Caddy (priorité 2), qui voit `127.0.0.1` pour
  tous les clients réels une fois `NFOGEN_DOMAIN`/`NFOGEN_LOCAL_TLS` actif.
  Seule la valeur la plus à droite compte (celle ajoutée par le reverse
  proxy immédiat), jamais un préfixe que le client pourrait fournir
  lui-même en pré-remplissant l'en-tête — testé explicitement (un préfixe
  différent ne doit pas créer un quota séparé). À n'activer que derrière un
  reverse proxy de confiance : sans lui, l'en-tête devient une usurpation
  d'IP triviale pour n'importe quel client direct.
- **Tests d'intégration `GeneratePage`/`SettingsPage`** :
  `GeneratePage.test.tsx` (extraction vidéo locale réussie → pas d'upload,
  vs échec de l'extraction → repli sur upload avec avertissement affiché) et
  `SettingsPage.test.tsx` (connexion par token réussie → "Connecté."
  affiché, vs token invalide → message d'erreur, formulaire toujours
  visible). Les deux fichiers passaient du premier coup (comportement
  existant déjà correct) : vérifiés non complaisants par mutation manuelle
  avant commit — cassage délibéré de chaque chemin testé (repli sur upload
  forcé sans condition ; erreur de connexion avalée silencieusement), test
  correspondant bien mis en échec dans les deux cas, code ensuite restauré
  à l'identique (`git diff` vide sur les deux fichiers de page).
