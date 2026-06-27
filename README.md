# nfogen

[![CI](https://github.com/ICCUser/nfogen/actions/workflows/ci.yml/badge.svg)](https://github.com/ICCUser/nfogen/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Générateur de fichiers **NFO** modulaire, piloté par des **profils**.
Profil livré par défaut : **C411** (Films & Vidéos, Audio, Jeux/Applications,
eBook, Impression 3D).

L'outil sépare nettement trois responsabilités, ce qui le rend extensible
sans toucher au cœur :

1. **Extraction** (`extract.py`) — lire les métadonnées d'un fichier/dossier
   (vidéo via *libmediainfo*, audio via *mutagen*, scan générique).
2. **Profils** (`profiles/`) — décrire *comment* écrire le NFO. Un profil est
   **100% déclaratif** : un `rules.json` (règles de nommage par catégorie) et
   des templates Jinja2 (`templates/<cat>.j2`), interprétés par un moteur
   générique ([`nfogen/declarative_profile.py`](nfogen/declarative_profile.py))
   qui ne connaît aucun tracker en particulier. C411 (livré avec le paquet) et
   les profils utilisateur (gérés à chaud, voir plus bas) passent par
   *exactement* le même mécanisme.
3. **Cœur** (`engine.py`, `registry.py`) — orchestrer, sans rien connaître
   d'un tracker en particulier.

> Le NFO « Films & Vidéos » de C411 **est** la sortie texte par défaut de
> MediaInfo. Le template `video.j2` se contente donc de la reproduire
> fidèlement (`{{ raw_text }}`, sans aucune mise en forme), ce qui garantit
> la conformité quelle que soit l'évolution des conventions — tout en
> passant par le même `render_template()` que les 4 autres catégories.
> Seule exception délibérée : le champ `Complete name` est réduit au seul
> nom de fichier (jamais le chemin complet local/temporaire, qui peut
> révéler un nom d'utilisateur ou une arborescence de dossiers — sans
> intérêt pour qui lit un NFO partagé publiquement).

## Installation

### Sur un serveur (Debian/Ubuntu, recommandé)

Installe tout (Python, Node.js, libmediainfo), build le frontend, et lance
l'API + l'interface comme service `systemd` :

```bash
git clone https://github.com/ICCUser/nfogen.git
cd nfogen
sudo ./scripts/install.sh
```

Le script affiche l'URL et le token API généré à la fin. Pour mettre à jour
plus tard, depuis le même dossier :

```bash
sudo ./scripts/update.sh
```

Le code applicatif est remplacé, mais le token API et les profils créés via
l'interface ne sont **jamais perdus** (stockés à part, dans `/etc/nfogen` et
`/var/lib/nfogen`).

### Avec Docker (autres distributions)

```bash
docker build -t nfogen .
docker run -p 8000:8000 -e NFOGEN_API_TOKEN=change-moi nfogen
# Interface + API sur http://localhost:8000
```

### En développement (manuel)

```bash
apt-get install libmediainfo0v5 mediainfo   # Debian/Ubuntu
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api]"
```

Pour le frontend (rechargement à chaud), voir
[frontend/README.md](frontend/README.md).

## Utilisation en ligne de commande

```bash
nfogen --list                              # profils & catégories
nfogen -i film.mkv                         # catégorie auto-détectée -> stdout
nfogen -c video -i film.mkv -o film.nfo
nfogen -c audio -i /chemin/album -o album.nfo
nfogen -c game  --data examples/game.json -o jeu.nfo
```

`--data fichier.json` fournit les champs non extractibles automatiquement
(synopsis, config requise, étapes d'installation…). Ces valeurs **complètent
ou surchargent** ce qui est extrait de la source.

### Exigences obligatoires (validation) — moteur de regles declaratif

Les exigences de nommage d'un profil ne sont **pas codees en dur en Python**.
Elles vivent dans un fichier JSON par profil (ex.
[`profiles/c411/rules.json`](nfogen/profiles/c411/rules.json)), interprete
par un moteur generique ([`nfogen/rules.py`](nfogen/rules.py)) qui ne connaît
aucun tracker en particulier. **Modifier une regle existante, ou en ajouter
une, se fait en editant le JSON — jamais en touchant a `rules.py`,
`engine.py`, `registry.py` ni un quelconque `__init__.py` de profil.**

Tout `rules.json` (livre avec le paquet ou utilisateur) est valide contre un
schema formel ([`nfogen/rules.schema.json`](nfogen/rules.schema.json)) avant
d'etre enregistre — un fichier malforme est rejete avec un message explicite
plutot que de provoquer une erreur confuse plus tard.

Principe (inspire des conventions de nommage par variables de Sonarr/Radarr) :
un profil declare des **tokens nommes** (regex avec groupes nommes Python
`(?P<nom>...)`), chacun `required` (bloquant), `recommended` (avertissement),
ou membre d'un `group` (au moins un du groupe doit matcher). L'ordre exact
des tokens n'est jamais impose : on verifie leur *presence*, pas une
sequence figee, pour absorber les sous-formats tres variables d'une vraie
convention (Films, Series, Collections, HDR, REMUX/BDMV/ISO...).

Pour la categorie `video` du profil C411, le champ `release_name` est
**obligatoire** et doit respecter la convention C411 (wiki "Le Nommage de
l'upload") : separateur point uniquement (pas d'espace/accent), terminer
par un codec video reconnu (x264/x265/H264/H265/HEVC/AVC/MPEG2) suivi de
`-TEAM`, et contenir une annee, un tag de saison/episode (`SXX`/`SXXEXX`) ou
`COLLECTION`/`INTEGRALE`. Exemples conformes :

```
Mr.Robot.S01.MULTI.VFF.1080p.WEB.EAC3.5.1.H264-FW
Breaking.Bad.INTEGRALE.MULTI.VFF.1080p.WEB.EAC3.5.1.H265-BTT
Le.Comte.de.Monte.Cristo.2024.VOF.2160p.UHD.BluRay.REMUX.DV.HDR10PLUS.TrueHD.Atmos.7.1.HEVC-ZEKEY
```

Sans `release_name`, ou s'il ne respecte pas ces regles, `nfogen` **refuse
de generer** le NFO (erreur explicite, message tire du JSON). D'autres
controles sont informatifs et n'empechent pas la generation : absence de
tag de langue (`recommended`, normal pour les clips/concerts) ou de
resolution (admis sous 720p), incoherence entre ce que `release_name`
annonce et ce que MediaInfo lit reellement dans le fichier (resolution,
codec, via les `cross_checks` du JSON), et piste audio/sous-titres sans tag
de langue dans les metadonnees du fichier source.

### Proposition automatique de `release_name`

Plutot que de taper le `release_name` a la main, `nfogen` peut en **proposer
un** a partir des seuls NOMS de fichiers (jamais leur contenu : aucune
lecture/upload necessaire, instantane meme pour des fichiers de plusieurs
centaines de Go) :

```bash
nfogen --propose-name -c video -i "One Piece/Season 01"
# -> One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG
```

- Plusieurs fichiers de la **meme saison** -> pack saison (`S01`, sans
  episode) ; un seul fichier -> episode (`S01E04`) ; sinon annee si presente.
- Le **tag d'equipe** (`-TEAM`) est recupere s'il est identique sur tous les
  fichiers, sinon `NOTAG` (placeholder a corriger) ; des tags differents
  entre fichiers d'un meme lot sont une erreur (lot ambigu), pas une devinette.
- Les **tags de langue** des noms scrapes (ex. `FR+JA`) sont convertis via une
  table de correspondance configurable par profil (`rules.json -> video ->
  name_proposal.language_aliases`, ex. `"FR+JA": "MULTI.VFF"`), modifiable
  aussi depuis l'editeur de profil du frontend.
- La resolution/le codec video/le codec audio/la source/l'equipe sont
  recherches n'importe ou dans le nom de fichier (pas seulement entre
  crochets `[...]`) : un nom "scene" comme `Show.S01E01.1080p.WEB.x264-TEAM`
  fonctionne aussi bien qu'un nom a crochets.
- Optionnellement, le tag **`Title`** du conteneur video (piste General,
  souvent renseigne a la main par l'auteur de la release avec un descriptif
  complet, ex. `One Piece S01 ''Arc Morgan'' WebDl 1080p x264 - Chris44`)
  peut etre transmis via `title_hints` (CLI : lu automatiquement depuis les
  fichiers locaux ; frontend : extrait cote navigateur via mediainfo.js, sans
  upload) — il est prioritaire sur le nom de fichier pour la resolution/le
  codec/la source/l'equipe, car c'est une indication ecrite par l'auteur de
  la release et donc souvent plus fiable qu'un nom de fichier generique. La
  saison/l'episode restent determines en priorite par le nom de fichier (plus
  fiable pour la numerotation precise).
- C'est une **proposition a relire**, jamais une valeur appliquee a
  l'aveugle : les champs non determinables ont un placeholder explicite et
  chaque avertissement (langue inconnue, tag d'equipe absent...) est renvoye
  pour etre corrige avant generation.
- Disponible aussi en API (`POST /propose-name`, JSON, voir plus bas) et dans
  le frontend (pre-rempli automatiquement a la selection des fichiers, page
  « Generer »). Un profil sans `name_proposal` dans son `rules.json` n'a
  simplement pas cette fonctionnalite (pas une erreur).

### Génération vidéo côté navigateur, sans upload

La page « Générer » du frontend analyse les fichiers **vidéo directement
dans le navigateur**, via une compilation WebAssembly de MediaInfoLib
([`mediainfo.js`](https://github.com/buzz/mediainfo.js)) : elle lit
seulement les plages d'octets nécessaires (`Blob.slice()`), jamais le
fichier entier, et n'envoie au serveur que le texte résultant
(`data.raw_text` et les métadonnées structurées `data.video_metadata`) via
`POST /generate/json` — quelques Ko, jamais les fichiers source. Résultat :
un pack saison de plusieurs Go se génère en une fraction de seconde plutôt
qu'en dizaines de secondes d'upload.

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

`video_metadata` (objet pour un fichier, liste pour un pack saison — voir
`extract.extract_video_metadata`/`extract_video_dir_metadata` pour la forme
exacte) permet aux `cross_checks`/`track_language_checks` du profil de
fonctionner **sans fichier source côté serveur** : c'est ce qui préserve les
avertissements existants (résolution/codec annoncés vs réels, langues
manquantes) malgré l'absence d'upload. Si l'extraction locale échoue
(navigateur sans WebAssembly...), le frontend retombe automatiquement sur
l'upload classique (`POST /generate`, multipart).

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
uvicorn nfogen.api:app --host 0.0.0.0 --port 8000
```

| Endpoint | Auth | Usage |
|---|---|---|
| `GET /health` | non | sonde de supervision |
| `GET /profiles` | non | liste profils/catégories (registre complet, y compris C411) |
| `POST /generate` | si `NFOGEN_API_TOKEN` définie | multipart : envoi de fichier(s) → NFO |
| `POST /generate/json` | si `NFOGEN_API_TOKEN` définie | JSON : métadonnées → NFO (sans fichier) |
| `POST /propose-name` | si `NFOGEN_API_TOKEN` définie | JSON : noms de fichiers (+ `title_hints` optionnels) → suggestion de `release_name` (aucun upload) |
| `GET /profiles/store` | si `NFOGEN_API_TOKEN` définie | liste des profils **utilisateur** (`NFOGEN_PROFILES_DIR`) |
| `GET /profiles/store/{name}` | idem | règles + templates d'un profil utilisateur |
| `PUT /profiles/store/{name}` | idem | crée/remplace un profil utilisateur |
| `DELETE /profiles/store/{name}` | idem | supprime un profil utilisateur |
| `GET /profiles/store/{name}/export` | idem | archive `.zip` du profil |
| `POST /profiles/store/{name}/import` | idem | dépose un `.zip` (crée/remplace) |

### Configuration (variables d'environnement, toutes optionnelles)

| Variable | Effet |
|---|---|
| `NFOGEN_API_TOKEN` | Si définie, `/generate`, `/generate/json` et toutes les routes `/profiles/store*` exigent l'en-tête `Authorization: Bearer <token>`. Sans elle, ces routes restent ouvertes — à définir explicitement pour exposer l'API publiquement. |
| `NFOGEN_CORS_ORIGINS` | Origines autorisées en cross-origin, séparées par des virgules (ex. `http://localhost:5173`). Aucun CORS n'est activé par défaut. |
| `NFOGEN_MAX_UPLOAD_MB` | Taille maximale acceptée par requête, en Mo. **Illimitée par défaut** (variable absente) — les fichiers sources (vidéo, jeux, scans...) peuvent légitimement peser plusieurs centaines de Go ; ils sont écrits sur disque par blocs, jamais chargés entièrement en mémoire. Définir une valeur pour appliquer un plafond (utile si l'API est exposée publiquement) ; au-delà, réponse `413`. |
| `NFOGEN_PROFILES_DIR` | Dossier de profils **utilisateur**, gérables à chaud via `/profiles/store*` (voir section suivante). Sans elle, ces routes renvoient une erreur 400 explicite. |
| `NFOGEN_FRONTEND_DIST` | Dossier du build frontend (`frontend/dist`, après `npm run build`). Si définie, l'API sert aussi le frontend (fichiers statiques + repli sur `index.html` pour les routes React Router) sur le **même** processus/port — c'est ce que font `scripts/install.sh` et l'image Docker. Absente par défaut : l'API reste API-only (usage en développement, avec `vite dev` séparé). |

```bash
export NFOGEN_API_TOKEN=change-moi
curl -H "Authorization: Bearer change-moi" \
     -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json
```

> Les réponses d'erreur distinguent **400** (entrée invalide : profil/catégorie
> inconnue, nommage non conforme — message explicite) et **500** (erreur
> serveur inattendue, journalisée côté serveur, message générique côté
> client pour ne pas exposer de détails internes).

Exemples :

```bash
# Upload d'un fichier vidéo -> NFO renvoyé en text/plain
curl -F category=video -F files=@film.mkv http://localhost:8000/generate

# Album : plusieurs fichiers audio (catégorie audio auto)
curl -F category=audio -F files=@01.flac -F files=@02.flac \
     http://localhost:8000/generate

# Jeu : métadonnées seules
curl -H 'Content-Type: application/json' \
     -d '{"category":"game","data":{"title":"X","platform":"PC"}}' \
     http://localhost:8000/generate/json

# Vidéo SANS uploader plusieurs Go : le client extrait localement le texte
# MediaInfo et le poste (champ data.raw_text).
RAW=$(mediainfo film.mkv)
jq -n --arg r "$RAW" '{category:"video",data:{raw_text:$r}}' \
  | curl -d @- -H 'Content-Type: application/json' \
         http://localhost:8000/generate/json
```

Ajouter `?download=1` renvoie le NFO en pièce jointe (`Content-Disposition`).

## Gérer des profils utilisateur (sans toucher au code)

Un profil est 100% déclaratif : un `rules.json` (optionnel) + des templates
`.j2`. Pour en créer un sans redémarrer le processus ni écrire de Python,
deux options.

**Sur disque, directement** — déposez un dossier dans `NFOGEN_PROFILES_DIR`
avec la même structure qu'un profil embarqué :

```text
$NFOGEN_PROFILES_DIR/
└── mon_tracker/
    ├── rules.json          # optionnel : regles de nommage par categorie
    └── templates/
        ├── video.j2
        └── game.j2
```

Le profil est chargé au démarrage du processus (`import nfogen` / lancement
de l'API ou de la CLI).

**Via l'API** (création/édition/suppression à chaud, sans redémarrage) :

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
     -H "Authorization: Bearer change-moi" -o mon_tracker.zip   # partage/sauvegarde

curl -X DELETE http://localhost:8000/profiles/store/mon_tracker \
     -H "Authorization: Bearer change-moi"
```

`rules.json` est validé contre [`nfogen/rules.schema.json`](nfogen/rules.schema.json)
avant toute écriture : un schéma invalide est rejeté (`400`) sans toucher au
disque ni casser les autres profils.

Par défaut, C411 (livré avec le paquet) est en lecture seule dans
l'interface — mais rien ne l'empêche d'être *surchargé* : un profil
utilisateur portant le même nom (`PUT /profiles/store/c411`, ou un dossier
`c411/` dans `NFOGEN_PROFILES_DIR`) prend le dessus sur la version livrée,
y compris après un redémarrage. Exactement le même principe que
`NFOGEN_TEMPLATES` pour les templates seuls, mais pour le profil entier
(règles + templates).

Le `.zip` exporté a la même structure que sur disque (`rules.json` +
`templates/*.j2`) : il peut être partagé tel quel, ou versionné dans un
dépôt git séparé pour profiter de l'historique/rollback gratuitement.

### Interface graphique (frontend)

Plutôt que `curl`, [`frontend/`](frontend/) fournit une interface web (React +
Vite + Tailwind) pour les mêmes opérations : lister les profils (avec
distinction lecture seule / éditable), éditer les règles via un formulaire
dédié, éditer les templates, prévisualiser un rendu en direct, exporter/
importer un `.zip`. Voir [`frontend/README.md`](frontend/README.md).

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, proxy /api -> localhost:8000
```

## Surcharger un template embarqué, ou écrire un profil 100% Python

**Surcharger un template** sans toucher au code ni à `NFOGEN_PROFILES_DIR` :
pointez `NFOGEN_TEMPLATES` vers un dossier contenant `c411/audio.j2` (ou un
autre couple profil/cat). Prioritaire sur les templates embarqués.

```bash
export NFOGEN_TEMPLATES=/chemin/mes_templates
```

**Profil avec une logique de rendu inédite** (pas juste des règles/templates
sur les 5 catégories fixes) : c'est le seul cas qui demande encore du Python,
via les 3 mêmes décorateurs que `nfogen.declarative_profile` utilise en
interne — le cœur (`engine.py`/`registry.py`) ne connaît jamais un tracker en
particulier :

| Décorateur | Signature | Rôle |
|---|---|---|
| `@register(profil, cat)` | `(ctx) -> str` | Obligatoire : produit le texte du NFO |
| `@register_validator(profil, cat)` | `(ctx, nfo) -> list[str]` | Optionnel : lève une exception pour bloquer la génération (règle obligatoire), ou renvoie des avertissements non bloquants |
| `@register_filename(profil, cat)` | `(ctx) -> str` | Optionnel : impose le nom du fichier `.nfo` final (ex. `f"{release_name}.nfo"`) |

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

Puis importez le paquet dans `profiles/__init__.py`. Pour le cas courant
(règles de nommage + templates sur les 5 catégories fixes), préférez la
gestion déclarative ci-dessus : voir
[`nfogen/declarative_profile.py`](nfogen/declarative_profile.py) et l'exemple
concret [`profiles/c411/__init__.py`](nfogen/profiles/c411/__init__.py) (6
lignes, aucune logique propre à C411).

## Catégories du profil C411

| Catégorie | Source auto | Rendu |
|---|---|---|
| `video` | fichier vidéo (libmediainfo) | texte MediaInfo (passthrough) |
| `audio` | dossier d'album (mutagen) | bannières + tracklist |
| `game`  | scan fichiers (taille/nb) | template (config, install…) |
| `ebook` | scan fichiers | template |
| `print3d` | scan fichiers | template |

Les catégories `gps` et `adulte` de C411 suivent les règles d'autres
catégories (Jeux/Vidéo/eBook) : réutilisez le renderer correspondant.

## Tests

```bash
pip install -e ".[dev]" httpx
pytest -q
ruff check .          # lint, execute aussi en CI
```

## Avertissement

`nfogen` ne produit que des fichiers de **métadonnées** (texte). Il ne
télécharge, n'héberge et ne distribue aucun contenu. L'usage qui en est fait
relève de la responsabilité de l'utilisateur.
