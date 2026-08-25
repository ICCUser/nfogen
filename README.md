# nfogen

[![CI](https://github.com/ICCUser/nfogen/actions/workflows/ci.yml/badge.svg)](https://github.com/ICCUser/nfogen/actions/workflows/ci.yml)
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

### En développement (manuel)

```bash
apt-get install libmediainfo0v5 mediainfo   # Debian/Ubuntu
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
# Generation : ouverte par defaut.
curl -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json

# Avec NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1 :
export NFOGEN_API_TOKEN=change-moi
export NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1
curl -H "Authorization: Bearer change-moi" \
     -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json
```

Erreurs : `400` (entrée invalide, message explicite) vs `500` (erreur
serveur, journalisée, message générique côté client).

```bash
# Upload d'un fichier vidéo -> NFO en text/plain
curl -F category=video -F files=@film.mkv http://localhost:8000/generate

# Album : plusieurs fichiers audio
curl -F category=audio -F files=@01.flac -F files=@02.flac \
     http://localhost:8000/generate

# Jeu : métadonnées seules
curl -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json

# Vidéo sans uploader : extraction locale du texte MediaInfo
RAW=$(mediainfo film.mkv)
jq -n --arg r "$RAW" '{category:"video",data:{raw_text:$r}}' \
  | curl -d @- -H 'Content-Type: application/json' \
         http://localhost:8000/generate/json
```

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

## GapScan (optionnel)

Compare ta bibliothèque Sonarr/Radarr au catalogue C411 pour repérer les
films/séries que tu possèdes mais qui ne sont pas (ou pas dans ta qualité)
sur le tracker — candidats à uploader avec `nfogen`. Extra pip dédié
(`pip install -e ".[api,gapscan]"`), configuration par variables
d'environnement (`NFOGEN_C411_API_KEY`, `NFOGEN_SONARR_URL`/`_API_KEY`,
`NFOGEN_RADARR_URL`/`_API_KEY` — voir `.env.example`), endpoints
`/gapscan/*` protégés comme `/profiles/store*`. Détail complet (API
Torznab C411, politique anti-doublon, architecture) : [GAPSCAN.md](GAPSCAN.md).

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
