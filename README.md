# nfogen

[![CI](https://github.com/ICCUser/nfogen/actions/workflows/ci.yml/badge.svg)](https://github.com/ICCUser/nfogen/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ICCUser/nfogen)](https://github.com/ICCUser/nfogen/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Générateur de fichiers **NFO** générique, piloté par des **profils** : un
profil décrit la convention de nommage et la mise en forme d'un tracker,
sans toucher au code.

Trois responsabilités séparées :

1. **Extraction** (`extract.py`) — métadonnées d'un fichier/dossier (vidéo
   via *libmediainfo*, audio via *mutagen*, scan générique).
2. **Profils** (`profiles/`) — un `rules.json` (règles de nommage) et des
   templates Jinja2 (`templates/<cat>.j2`), interprétés par
   [`nfogen/declarative_profile.py`](nfogen/declarative_profile.py).
3. **Cœur** (`engine.py`, `registry.py`) — orchestre, sans connaître aucun tracker.

Le paquet est livré avec **un seul profil d'exemple, C411** (Films & Vidéos,
Audio, Jeux/Applications, eBook, Impression 3D). Il peut être ignoré,
surchargé ou supprimé comme n'importe quel profil (voir [Gérer des profils
utilisateur](#gérer-des-profils-utilisateur-sans-toucher-au-code)). Un profil
se partage en `.zip` (export/import intégrés).

## Installation et démarrage

Trois façons d'installer nfogen ; chacune démarre (et redémarre) différemment.

### Sur un serveur (Debian/Ubuntu, recommandé)

Installe tout (Python, Node.js, libmediainfo), build le frontend, et
**démarre automatiquement** l'API + l'interface comme service `systemd` :

```bash
git clone https://github.com/ICCUser/nfogen.git
cd nfogen
sudo ./scripts/install.sh
```

Affiche l'URL et le token API généré à la fin — rien d'autre à lancer.
Ensuite, le service se gère avec les commandes `systemctl` standard :

```bash
sudo systemctl status nfogen    # est-ce lancé ?
sudo systemctl restart nfogen   # apres avoir modifié /etc/nfogen/nfogen.env
sudo systemctl stop nfogen
journalctl -u nfogen -f         # logs en direct
```

Mise à jour (remplace le code, garde le token API et les profils utilisateur) :

```bash
sudo ./scripts/update.sh
```

#### TLS (recommandé avant d'exposer l'instance publiquement)

Par défaut, `install.sh` sert du HTTP en clair sur le port 8000 — adapté à un
serveur local/LAN de confiance, mais pas à une instance joignable depuis
Internet (identifiants et cookie de session transiteraient sans
chiffrement). Deux modes optionnels, mutuellement exclusifs, ajoutent un
reverse proxy [Caddy](https://caddyserver.com/) devant l'API :

```bash
# Domaine public : certificat Let's Encrypt automatique (DNS deja en place,
# ports 80/443 joignables depuis Internet)
sudo NFOGEN_DOMAIN=nfo.mon-domaine.example ./scripts/install.sh

# Serveur local/LAN, sans domaine public ni acces Internet : certificat
# auto-signe (a accepter/importer manuellement dans chaque navigateur)
sudo NFOGEN_LOCAL_TLS=1 ./scripts/install.sh
```

Le choix est persisté dans `/etc/nfogen/nfogen.env` : `sudo
./scripts/update.sh` seul (sans variable) le reprend automatiquement à
chaque mise à jour. Dans les deux modes, `uvicorn` n'écoute plus que sur
`127.0.0.1` (Caddy devient le seul point d'entrée réseau) et
`NFOGEN_COOKIE_SECURE` passe à `1`. `install.sh` gère `/etc/caddy/Caddyfile`
en entier (écrasé à chaque exécution) : si Caddy sert déjà d'autres sites
sur cette machine, configurez le reverse proxy vers nfogen à la main plutôt
que d'utiliser ces variables.

### Avec Docker (autres distributions)

```bash
docker build -t nfogen .
docker run -d --name nfogen -p 8000:8000 -e NFOGEN_API_TOKEN=change-moi nfogen
# Interface + API sur http://localhost:8000
```

```bash
docker stop nfogen && docker start nfogen   # arreter / redemarrer
docker logs -f nfogen                       # logs en direct
```

#### Sous Windows

Les mêmes commandes fonctionnent telles quelles, dans un terminal PowerShell,
à condition d'avoir [Docker Desktop](https://www.docker.com/products/docker-desktop/)
installé avec le **backend WSL2** (activé par défaut sur une installation
récente — vérifiable dans Docker Desktop via *Settings → General → Use the
WSL 2 based engine*). Sans WSL2 (backend Hyper-V, obsolète), les performances
disque du conteneur sont nettement dégradées.

```powershell
docker build -t nfogen .
docker run -d --name nfogen -p 8000:8000 -e NFOGEN_API_TOKEN=change-moi nfogen
# Interface + API sur http://localhost:8000
```

Par défaut, tout ce que le conteneur écrit (profils, config/résultats
GapScan si l'extra est ajouté — voir plus bas) est perdu à sa suppression
(`docker rm`). Pour persister ces données sur l'hôte Windows, montez un
volume avec `-v` (chemin Windows à gauche, chemin dans le conteneur à
droite) :

```powershell
docker run -d --name nfogen -p 8000:8000 `
  -e NFOGEN_API_TOKEN=change-moi `
  -v C:\nfogen-data:/data `
  -e NFOGEN_PROFILES_DIR=/data/profiles `
  nfogen
```

L'image Docker n'installe que l'extra `api` (voir plus bas, section
« Pipeline d'automatisation GapScan ») : le pipeline C411/Sonarr/Radarr n'y
est pas disponible sans reconstruire l'image avec `pip install -e
".[api,gapscan,automation]"` dans le `Dockerfile`.

### En développement (manuel)

```bash
apt-get install libmediainfo0v5 mediainfo ffmpeg   # Debian/Ubuntu
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api]"
nfogen serve
# API (+ interface si NFOGEN_FRONTEND_DIST est definie) sur http://localhost:8000
```

`nfogen serve` (équivalent de `uvicorn nfogen.api:app`, voir [Service
HTTP](#service-http-automatisation)) accepte `--host`/`--port` (par défaut
`0.0.0.0:8000`) ; `Ctrl+C` pour arrêter. Frontend en rechargement à chaud
(hors `NFOGEN_FRONTEND_DIST`) : [frontend/README.md](frontend/README.md).

## Utilisation en ligne de commande

```bash
nfogen --list                              # profils & catégories
nfogen -i film.mkv                         # catégorie auto-détectée -> stdout
nfogen -c video -i film.mkv -o film.nfo
nfogen -c audio -i /chemin/album -o album.nfo
nfogen -c game  --data examples/game.json -o jeu.nfo
```

`--data fichier.json` fournit les champs non extractibles automatiquement
(synopsis, config requise, étapes d'installation…), complète ou surcharge
ce qui est extrait de la source.

### Exigences obligatoires (validation)

Les exigences de nommage vivent dans un fichier JSON par profil (ex.
[`profiles/c411/rules.json`](nfogen/profiles/c411/rules.json)), interprété
par [`nfogen/rules.py`](nfogen/rules.py). Modifier/ajouter une règle se fait
en éditant le JSON, jamais `rules.py`/`engine.py`/`registry.py`.

Tout `rules.json` est validé contre [`nfogen/rules.schema.json`](nfogen/rules.schema.json)
avant d'être enregistré (erreur explicite si malformé).

Un profil déclare des **tokens nommés** (regex avec groupes nommés
`(?P<nom>...)`), chacun `required` (bloquant), `recommended` (avertissement),
ou membre d'un `group` (au moins un du groupe doit matcher). L'ordre des
tokens n'est jamais imposé, seule leur présence compte.

Un `required` non satisfait bloque la génération ; un `recommended` ou un
`cross_check` (cohérence release_name / MediaInfo réel) ne produit qu'un
avertissement.

<details>
<summary>Exemple concret : la convention du profil C411 fourni</summary>

Pour `video`, `release_name` doit respecter la convention C411 (wiki "Le
Nommage de l'upload") : séparateur point uniquement, terminer par un codec
vidéo reconnu suivi de `-TEAM`, et contenir une année, un tag saison/épisode
ou `COLLECTION`/`INTEGRALE`. Exemples conformes :

```
Mr.Robot.S01.MULTI.VFF.1080p.WEB.EAC3.5.1.H264-FW
Breaking.Bad.INTEGRALE.MULTI.VFF.1080p.WEB.EAC3.5.1.H265-BTT
Le.Comte.de.Monte.Cristo.2024.VOF.2160p.UHD.BluRay.REMUX.DV.HDR10PLUS.TrueHD.Atmos.7.1.HEVC-ZEKEY
```

Un autre profil déclare ses propres tokens, sans rapport avec celle-ci.

</details>

### Proposition automatique de `release_name`

À partir des seuls NOMS de fichiers (jamais leur contenu, instantané même
pour des fichiers de plusieurs centaines de Go) :

```bash
nfogen --propose-name -c video -i "One Piece/Season 01"
# -> One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG
```

- Même saison sur plusieurs fichiers -> pack (`S01`) ; un seul fichier ->
  épisode (`S01E04`) ; sinon année si présente.
- Tag d'équipe (`-TEAM`) repris s'il est identique sur tous les fichiers,
  sinon `NOTAG` ; des tags différents dans un même lot sont une erreur.
- Tags de langue (ex. `FR+JA`) convertis via une table configurable par
  profil (`rules.json -> video -> name_proposal.language_aliases`).
- Résolution/codec/source/équipe recherchés n'importe où dans le nom (pas
  seulement entre crochets).
- Le tag `Title` du conteneur video, s'il est fourni via `title_hints`, est
  prioritaire sur le nom de fichier pour résolution/codec/source/équipe
  (saison/épisode restent déterminés par le nom de fichier).
- Toujours une proposition à relire : champs indéterminables en placeholder
  explicite, chaque ambiguïté renvoyée en avertissement.
- Disponible en API (`POST /propose-name`) et dans le frontend. Un profil
  sans `name_proposal` dans `rules.json` n'a simplement pas la fonctionnalité.

### Génération vidéo côté navigateur, sans upload

La page « Générer » du frontend analyse les fichiers vidéo dans le
navigateur via WebAssembly ([`mediainfo.js`](https://github.com/buzz/mediainfo.js)) :
lit seulement les octets nécessaires, n'envoie que le texte résultant
(`data.raw_text`, `data.video_metadata`) via `POST /generate/json`.

```json
{
  "profile": "c411",
  "category": "video",
  "data": {
    "release_name": "...",
    "raw_text": "General\nComplete name ...",
    "video_metadata": {
      "video_height": 1080, "video_format": "AVC",
      "audio_languages": ["fr"], "subtitle_languages": [null]
    }
  }
}
```

`video_metadata` (objet ou liste pour un pack, voir
`extract.extract_video_metadata`/`extract_video_dir_metadata`) permet aux
`cross_checks`/`track_language_checks` de fonctionner sans fichier côté
serveur. Repli automatique sur l'upload classique (`POST /generate`) si
l'extraction locale échoue.

## Utilisation comme bibliothèque

```python
import nfogen

# Vidéo : extraction automatique
nfo = nfogen.generate(source="film.mkv")            # catégorie auto

# Jeu : 100 % métadonnées fournies
nfo = nfogen.generate(category="game", data={
    "title": "Mon Jeu", "version": "1.0", "platform": "PC", "format": "ISO",
    "requirements": {"OS": "Windows 10", "RAM": "8 Go"},
    "install_steps": ["Monter l'ISO", "Installer"],
})
```

## Service HTTP (automatisation)

```bash
nfogen serve                                          # ou directement :
uvicorn nfogen.api:app --host 0.0.0.0 --port 8000
```

| Endpoint | Auth | Usage |
|---|---|---|
| `GET /health` | non | sonde de supervision |
| `GET /profiles` | non | liste profils/catégories |
| `GET /auth/status` | non | état d'authentification |
| `POST /login` | non | `{"token"}` ou `{"username","password"}` -> cookie de session httpOnly |
| `POST /logout` | non | efface le cookie de session |
| `GET /accounts` | oui | identifiants des comptes nommés |
| `POST /accounts` | non seulement en amorçage, sinon oui | crée un compte admin |
| `DELETE /accounts/{username}` | oui | supprime un compte (refusé pour le dernier) |
| `POST /generate` | si `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1` | multipart -> NFO |
| `POST /generate/json` | si `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1` | JSON -> NFO |
| `POST /propose-name` | si `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1` | noms de fichiers -> `release_name` |
| `GET /profiles/store` | oui | profils utilisateur |
| `GET /profiles/store/{name}` | oui | règles + templates |
| `PUT /profiles/store/{name}` | oui | crée/remplace |
| `DELETE /profiles/store/{name}` | oui | supprime la surcharge |
| `GET /profiles/store/{name}/export` | oui | `.zip` du profil |
| `POST /profiles/store/{name}/import` | oui | dépose un `.zip` |

**"oui"** = `NFOGEN_API_TOKEN` (`Authorization: Bearer <token>`) ou compte
nommé valide (`NFOGEN_ACCOUNTS_FILE`, `POST /login` -> cookie de session).

Le profil C411 ajoute des dizaines d'endpoints `/gapscan/*` (protégés
comme `/profiles/store*`) pour tout le pipeline décrit plus bas —
Bibliothèque, scan, préparation d'upload, seed. Non listés ici (trop
nombreux) : voir [GAPSCAN.md](GAPSCAN.md) et [AUTOMATION.md](AUTOMATION.md).

### Comptes administrateurs nommés (alternative au token unique)

Définir `NFOGEN_ACCOUNTS_FILE` pour distinguer/révoquer un accès individuel
sans changer le secret partagé. Un seul rôle : mêmes droits que le token.

- Le tout premier compte peut être créé sans authentification, uniquement si
  rien ne protège encore l'instance. À faire avant d'exposer l'instance.
- Créer/supprimer un compte exige ensuite d'être authentifié.
- Supprimer un compte révoque immédiatement ses sessions actives.
- Anti-bruteforce : verrouillage 30s après 5 échecs consécutifs par compte.

### Configuration (variables d'environnement, toutes optionnelles)

| Variable | Effet |
|---|---|
| `NFOGEN_API_TOKEN` | Protège `/profiles/store*` et `/accounts*`. N'affecte pas `/generate*` (voir `NFOGEN_REQUIRE_AUTH_FOR_GENERATE`). Absente : tout ouvert. |
| `NFOGEN_ACCOUNTS_FILE` | Comptes admin nommés, alternative au token — voir ci-dessus. |
| `NFOGEN_REQUIRE_AUTH_FOR_GENERATE` | `1` pour protéger aussi `/generate`, `/generate/json`, `/propose-name`. Désactivé par défaut. |
| `NFOGEN_CORS_ORIGINS` | Origines cross-origin autorisées, séparées par des virgules. Aucun CORS par défaut. |
| `NFOGEN_COOKIE_SECURE` | `1` pour cookie `Secure` (HTTPS uniquement). `0` par défaut. |
| `NFOGEN_COOKIE_SAMESITE` | `lax` par défaut ; `none` si frontend sur un autre domaine (exige `NFOGEN_COOKIE_SECURE=1`). |
| `NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES` | Expiration de session par inactivité (glissante). Défaut `1440` (24h). |
| `NFOGEN_SESSION_MAX_LIFETIME_HOURS` | Durée de vie absolue d'une session. Défaut `168` (7 jours). |
| `NFOGEN_MAX_UPLOAD_MB` | Taille max par requête. Illimitée par défaut ; au-delà, `413`. |
| `NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE` | Plafond de requêtes/minute par IP sur `/generate*`. Illimité par défaut ; au-delà, `429`. |
| `NFOGEN_PROFILES_DIR` | Dossier de profils utilisateur, gérables via `/profiles/store*`. Sans elle, ces routes renvoient `400`. |
| `NFOGEN_FRONTEND_DIST` | Si définie, l'API sert aussi le frontend build (même processus/port). |

```bash
# Generation : ouverte par defaut -- jeu, metadonnees seules.
curl -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json

# Avec NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1, le meme appel exige le token :
export NFOGEN_API_TOKEN=change-moi
export NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1
curl -H "Authorization: Bearer change-moi" \
     -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json

# Upload d'un fichier video -> NFO en text/plain
curl -F category=video -F files=@film.mkv http://localhost:8000/generate

# Album : plusieurs fichiers audio
curl -F category=audio -F files=@01.flac -F files=@02.flac \
     http://localhost:8000/generate

# Video sans uploader : extraction locale du texte MediaInfo
RAW=$(mediainfo film.mkv)
jq -n --arg r "$RAW" '{category:"video",data:{raw_text:$r}}' \
  | curl -d @- -H 'Content-Type: application/json' \
         http://localhost:8000/generate/json
```

Erreurs : `400` (entrée invalide, message explicite) vs `500` (erreur
serveur, journalisée, message générique côté client).

`?download=1` renvoie le NFO en pièce jointe (`Content-Disposition`).

## Gérer des profils utilisateur (sans toucher au code)

Un profil est 100% déclaratif : un `rules.json` (optionnel) + des templates
`.j2`. Trois façons de le créer, sans redémarrer le processus.

**Sur disque, directement** — déposez un dossier dans `NFOGEN_PROFILES_DIR` :

```text
$NFOGEN_PROFILES_DIR/
└── mon_tracker/
    ├── rules.json          # optionnel
    └── templates/
        ├── video.j2
        └── game.j2
```

Chargé au démarrage du processus.

**Via la CLI** (sans lancer l'API) :

```bash
export NFOGEN_PROFILES_DIR=/chemin/profils

nfogen --profile-store-list
nfogen --profile-store-show c411
nfogen --profile-store-write mon_tracker \
       --rules-file rules.json --templates-dir templates/
nfogen --profile-store-export c411 -o c411.zip
nfogen --profile-store-import mon_tracker --zip-file mon_tracker.zip
nfogen --profile-store-delete mon_tracker
```

Fonctionne aussi sur un profil livré avec le paquet (C411), sans surcharge préalable.

**Via l'API** (à chaud) :

```bash
export NFOGEN_PROFILES_DIR=/chemin/profils
export NFOGEN_API_TOKEN=change-moi

curl -X PUT http://localhost:8000/profiles/store/mon_tracker \
     -H "Authorization: Bearer change-moi" -H 'Content-Type: application/json' \
     -d '{
           "rules": {"game": {"filename_template": "{title}.nfo"}},
           "templates": {"game": "{{ title }}"}
         }'

curl http://localhost:8000/profiles/store/mon_tracker/export \
     -H "Authorization: Bearer change-moi" -o mon_tracker.zip

curl -X DELETE http://localhost:8000/profiles/store/mon_tracker \
     -H "Authorization: Bearer change-moi"
```

`rules.json` validé contre [`nfogen/rules.schema.json`](nfogen/rules.schema.json)
avant écriture (`400` si invalide, rien touché au disque).

Un profil livré (C411) est en lecture seule par défaut, mais peut être
surchargé : un profil utilisateur du même nom (`PUT /profiles/store/c411`,
ou un dossier `c411/`) prend le dessus, y compris après redémarrage.

Le `.zip` exporté a la même structure que sur disque, partageable ou
versionnable dans un dépôt git.

### Interface graphique (frontend)

[`frontend/`](frontend/) (React + Vite + Tailwind) : lister les profils,
éditer règles/templates, prévisualiser, exporter/importer. Voir
[`frontend/README.md`](frontend/README.md).

Le bouton « Gérer » est disponible sur tous les profils, y compris C411 : le
modifier crée la surcharge correspondante ; le supprimer restaure l'original.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, proxy /api -> localhost:8000
```

## Surcharger un template embarqué, ou écrire un profil 100% Python

**Surcharger un template** sans toucher au code : `NFOGEN_TEMPLATES` pointe
vers un dossier contenant `c411/audio.j2` (ou un autre couple profil/cat),
prioritaire sur les templates embarqués.

```bash
export NFOGEN_TEMPLATES=/chemin/mes_templates
```

**Profil avec une logique de rendu inédite** : seul cas qui demande encore
du Python, via 3 décorateurs (le cœur ne connaît jamais un tracker en particulier) :

| Décorateur | Signature | Rôle |
|---|---|---|
| `@register(profil, cat)` | `(ctx) -> str` | Obligatoire : produit le texte du NFO |
| `@register_validator(profil, cat)` | `(ctx, nfo) -> list[str]` | Optionnel : lève pour bloquer, ou renvoie des avertissements |
| `@register_filename(profil, cat)` | `(ctx) -> str` | Optionnel : impose le nom du fichier `.nfo` |

```python
# nfogen/profiles/mon_tracker/__init__.py
from ...registry import register
from ...render import render_template
from ...models import RenderContext

@register("mon_tracker", "video")
def video(ctx: RenderContext) -> str:
    from ... import extract
    return extract.extract_video_text(ctx.source)
```

Puis importez le paquet dans `profiles/__init__.py`. Pour le cas courant,
préférez la gestion déclarative ci-dessus : voir
[`nfogen/declarative_profile.py`](nfogen/declarative_profile.py) et
[`profiles/c411/__init__.py`](nfogen/profiles/c411/__init__.py).

## Catégories disponibles

| Catégorie | Source auto | Rendu |
|---|---|---|
| `video` | fichier vidéo (libmediainfo) | texte MediaInfo (passthrough) |
| `audio` | dossier d'album (mutagen) | bannières + tracklist |
| `game`  | scan fichiers (taille/nb) | template (config, install…) |
| `ebook` | scan fichiers | template |
| `print3d` | scan fichiers | template |

Pour une catégorie hors de ces cinq, réutilisez le renderer d'une catégorie
proche (comme fait le profil C411 fourni).

## Pipeline d'automatisation GapScan (optionnel, profil C411)

Au-delà de la génération de `.nfo`, le profil C411 fourni pilote un
pipeline complet — de "je remarque qu'un média me manque sur le
tracker" jusqu'à "il est en seed" — accessible depuis la page
**Bibliothèque** du frontend :

- **Bibliothèque** — inventaire Sonarr/Radarr local, zéro appel tracker
  par défaut (rechargement quasi instantané), annoté du statut du
  dernier scan connu dès qu'il existe. Recherche, filtres (type, genre,
  statut, ajouté depuis N jours, déjà traité), sélection multiple.
- **Scan** (bulk ou restreint à une sélection) — compare chaque titre
  possédé au catalogue C411 (API Torznab) : absent, qualité
  supérieure disponible, langue manquante, ou déjà couvert. Mode
  incrémental (ne réinterroge que ce qui a changé), respecte le
  débit limite du tracker.
- **Proposition de nom + mise en scène + `.torrent`** — depuis un
  gap détecté (ou un pack de saisons complet, `SxxSyy`/`INTÉGRALE`
  détecté automatiquement quand plusieurs saisons consécutives
  partagent la même équipe), génère le nom de release, met en scène
  le fichier (hardlink si même volume, copie sinon) et construit le
  `.torrent`, en tâche de fond avec suivi de progression.
- **Vérification approfondie avant un upload direct** — décodage
  réel du fichier (détecte la corruption qu'un en-tête de conteneur
  valide peut masquer), durée réelle vs annoncée, synchronisation
  audio/vidéo — jamais pour un simple brouillon.
- **Envoi au tracker** — brouillon (reste privé, à finaliser
  manuellement) ou upload direct (`POST /api/torrents`, part
  réellement en modération), description enrichie automatiquement
  (TMDB, pistes audio/sous-titres, container/HDR).
- **Seed** — un upload direct ajoute automatiquement le `.torrent` à
  qBittorrent. Pour un titre déjà présent sur C411 mais identique à
  ton fichier local (même taille/équipe/qualité), récupère et vérifie
  le `.torrent` existant au lieu de re-uploader.

Installé par défaut sur le déploiement natif (`scripts/install.sh`
installe les extras `gapscan`+`automation` et configure
`NFOGEN_GAPSCAN_CONFIG_FILE`/`NFOGEN_GAPSCAN_RESULTS_FILE` sous
`/var/lib/nfogen/`) ; **absent de l'image Docker** (`Dockerfile`
n'installe que l'extra `api`) — `pip install -e ".[api,gapscan,automation]"`
pour l'activer ailleurs (ajoute aussi `ffmpeg`, requis pour la
vérification d'intégrité vidéo). `501` sur `/gapscan/*` si l'extra n'est
pas installé ; `400` si l'extra est bien là mais qu'aucune clé C411 /
instance Sonarr-Radarr n'est encore configurée. Configuration (URLs +
clés Sonarr/Radarr/C411/qBittorrent/TMDB) modifiable à chaud depuis la
page **Réglages** du frontend (`NFOGEN_GAPSCAN_CONFIG_FILE` requis, déjà
réglé par `install.sh`), ou par variables d'environnement en lecture
seule sinon (voir [`.env.example`](.env.example)). Endpoints
`/gapscan/*` protégés comme `/profiles/store*`.

Historique de conception détaillé (API Torznab C411, politique
anti-doublon, décisions d'architecture) : [GAPSCAN.md](GAPSCAN.md) pour
la détection de gap, [AUTOMATION.md](AUTOMATION.md) pour tout ce qui
vient après (mise en scène, upload, seed).

## Tests

```bash
pip install -e ".[api,dev]"
pytest -q
ruff check .          # lint, execute aussi en CI
```

## Avertissement

`nfogen` ne produit que des fichiers de métadonnées (texte). Il ne
télécharge, n'héberge et ne distribue aucun contenu. L'usage qui en est fait
relève de la responsabilité de l'utilisateur.
