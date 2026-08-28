# AUTOMATION sous-projet 3 : `name_proposal.py` agnostique du tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sortir la reconnaissance/normalisation des sources et codecs (vidéo/audio) de `name_proposal.py` (câblée en Python) vers `rules.json` (déclarative, par profil) — sans changer le moindre comportement observable pour le profil C411 existant.

**Architecture:** Un mécanisme générique unique `_detect_via_aliases(text, aliases)` remplace trois blocs de code dupliqués (regex + dict de normalisation câblés en dur) et est réutilisé pour les 4 champs concernés (langue — déjà déclarative, migrée vers ce mécanisme commun — source, codec vidéo, codec audio). La détection résolution/saison-épisode/année et la position du tag d'équipe restent en Python (conventions jugées universelles, décision utilisateur).

**Tech Stack:** Python 3.10+ (`re`, `dataclasses`), pytest.

**Spec:** [AUTOMATION.md](../../../AUTOMATION.md), section "Sous-projet 3 : Rendre `name_proposal.py` agnostique du tracker".

## Global Constraints

- **Zéro changement de comportement observable pour le profil C411** : toute proposition de nom que `propose_video_release_name()` produit aujourd'hui pour un fichier donné doit produire exactement la même chose après ce sous-projet — seule la provenance de la connaissance change (Python → `rules.json`).
- Reste câblé en Python (ne pas rendre configurable) : résolution (`1080p`), saison/épisode (`S01E01`), année, position du tag d'équipe (`-TEAM` en fin de nom) — conventions jugées quasi universelles dans l'écosystème des trackers.
- Passe en config (`rules.json -> video -> name_proposal`), même mécanisme que `language_aliases` existant (le plus long alias qui correspond l'emporte, insensible à la casse) : `source_aliases`, `video_codec_aliases`, `audio_codec_aliases`.
- TDD : pour un refactor qui préserve un comportement existant, la suite de tests existante (`tests/test_name_proposal.py`) sert de filet de non-régression — elle doit rester verte de bout en bout après migration de sa config. En complément, de nouveaux tests prouvent explicitement que la normalisation est désormais configurable (pas supposée).
- `pytest -q` et `ruff check .` propres avant chaque commit.
- Style du projet : commentaires en français, denses sur le "pourquoi" pas le "quoi", jamais de TODO laissé dans le code.

---

### Task 1: `nfogen/name_proposal.py` — mécanisme générique d'alias

**Files:**
- Modify: `nfogen/name_proposal.py`
- Modify: `tests/test_name_proposal.py`

**Interfaces:**
- Produces: `_detect_via_aliases(text: str, aliases: dict[str, str]) -> str` (fonction interne, mais testée indirectement via `propose_video_release_name`). `propose_video_release_name()` conserve exactement sa signature publique actuelle — seul ce que `config` peut contenir s'enrichit (`source_aliases`/`video_codec_aliases`/`audio_codec_aliases`, en plus de `template`/`language_aliases` déjà supportés).

- [ ] **Step 1: Mettre à jour `CONFIG` dans les tests existants (filet de non-régression)**

Dans `tests/test_name_proposal.py`, remplacer `CONFIG` pour reproduire **exactement** l'ancien comportement câblé en dur (avant refactor, ces valeurs n'ont aucun effet — normal, elles seront lues seulement après l'étape 3) :

```python
CONFIG = {
    "template": TEMPLATE,
    "language_aliases": {"FR+JA": "MULTI.VFF", "FR": "VFF"},
    "source_aliases": {
        "WEBDL": "WEB",
        "WEB-DL": "WEB",
        "WEBRip": "WEB",
        "BDRip": "BDRip",
        "BDRemux": "BluRay.REMUX",
        "BluRay": "BluRay",
        "HDTV": "HDTV",
        "DVDRip": "DVDRip",
        "DSNP": "WEB.DSNP",
        "NF": "WEB.NF",
        "AMZN": "WEB.AMZN",
    },
    "video_codec_aliases": {
        "x264": "x264",
        "x265": "x265",
        "H.264": "h.264",
        "H264": "h264",
        "H.265": "h.265",
        "H265": "h265",
        "HEVC": "hevc",
        "AVC": "avc",
        "MPEG-2": "mpeg-2",
        "MPEG2": "mpeg2",
    },
    "audio_codec_aliases": {
        "AC3": "AC3",
        "EAC3": "EAC3",
        "AAC": "AAC",
        "DTS-HD": "DTS-HD",
        "DTS": "DTS",
        "FLAC": "FLAC",
        "MP3": "MP3",
        "OPUS": "OPUS",
        "TRUEHD": "TRUEHD",
    },
}
```

Ajouter aussi, en fin de fichier, 3 nouveaux tests prouvant que la normalisation est désormais réellement configurable (pas supposée) :

```python
def test_source_normalization_is_fully_configurable_per_profile():
    """Preuve que la normalisation de la source n'est plus cablee en dur --
    un profil different de C411 peut choisir une autre sortie sans toucher
    au code (voir AUTOMATION.md, sous-projet 3)."""
    files = ["Movie.2020.WEBDL.1080p.mkv"]
    custom_config = {
        "template": "{title}.{identifier}.{resolution}p.{source}",
        "source_aliases": {"WEBDL": "WEB-CUSTOM"},
    }
    proposal = propose_video_release_name(files, custom_config)
    assert proposal.fields["source"] == "WEB-CUSTOM"


def test_video_codec_normalization_is_fully_configurable_per_profile():
    files = ["Movie.2020.1080p.x264.mkv"]
    custom_config = {
        "template": "{title}.{identifier}.{resolution}p.{video_codec}",
        "video_codec_aliases": {"x264": "H264-CUSTOM"},
    }
    proposal = propose_video_release_name(files, custom_config)
    assert proposal.fields["video_codec"] == "H264-CUSTOM"


def test_audio_codec_normalization_is_fully_configurable_per_profile():
    files = ["Movie.2020.1080p.AC3.mkv"]
    custom_config = {
        "template": "{title}.{identifier}.{resolution}p.{audio}",
        "audio_codec_aliases": {"AC3": "DOLBY-CUSTOM"},
    }
    proposal = propose_video_release_name(files, custom_config)
    assert proposal.fields["audio"] == "DOLBY-CUSTOM"
```

- [ ] **Step 2: Run the full existing suite to confirm nothing is broken yet**

Run: `pytest tests/test_name_proposal.py -v`
Expected: les tests existants PASSENT toujours (la nouvelle config ajoutée à `CONFIG` est ignorée par l'ancien code) ; les 3 nouveaux tests ÉCHOUENT (`assert "" == "WEB-CUSTOM"` etc. -- `source_aliases`/`video_codec_aliases`/`audio_codec_aliases` ne sont pas encore lus par `propose_video_release_name`)

- [ ] **Step 3: Write the implementation**

Dans `nfogen/name_proposal.py`, retirer ces constantes (remplacées par la config) :

```python
_VIDEO_CODEC_RE = re.compile(r"\b([xX]26[45]|HEVC|AVC|MPEG-?2|[Hh]\.?26[45])\b")
_AUDIO_CODEC_RE = re.compile(r"\b(AC3|EAC3|AAC|DTS(?:-HD)?|FLAC|MP3|OPUS|TRUEHD)\b", re.IGNORECASE)
_SOURCE_RE = re.compile(
    r"\b(WEB-?DL|WEBRip|BDRip|BDRemux|BluRay|HDTV|DVDRip|DSNP|NF|AMZN)\b", re.IGNORECASE
)
_SOURCE_ALIASES = {
    "webdl": "WEB", "web-dl": "WEB", "webrip": "WEB",
    "bdrip": "BDRip", "bdremux": "BluRay.REMUX", "bluray": "BluRay",
    "hdtv": "HDTV", "dvdrip": "DVDRip", "dsnp": "WEB.DSNP", "nf": "WEB.NF", "amzn": "WEB.AMZN",
}
```

Garder `_YEAR_RE`, `_SEASON_EP_RE`, `_SEASON_ONLY_RE`, `_BRACKETS_RE`, `_RESOLUTION_RE`, `_CHANNELS_RE`, `_TEAM_RE` inchangés (conventions jugées universelles, voir Global Constraints).

Ajouter, juste après les constantes regex restantes :

```python
def _detect_via_aliases(text: str, aliases: dict[str, str]) -> str:
    """Cherche le plus long alias (cle) de `aliases` present dans `text`
    (insensible a la casse), renvoie sa forme normalisee (valeur associee).
    Chaine vide si aucun alias ne correspond. Mecanisme generique reutilise
    pour la langue, la source et les codecs video/audio (voir
    AUTOMATION.md, sous-projet 3) -- vocabulaire ET normalisation
    entierement pilotes par le profil, aucun cablage specifique a un
    tracker dans ce module."""
    lowered = text.lower()
    for alias, normalized in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        if alias and alias.lower() in lowered:
            return normalized
    return ""
```

Remplacer `_extract_release_info()` (signature changée : un seul paramètre `alias_groups` au lieu de `language_aliases`) :

```python
def _extract_release_info(text: str, alias_groups: dict[str, dict[str, str]]) -> dict[str, str]:
    """Cherche resolution/codec video/audio/source/langue n'importe ou dans
    `text`. `alias_groups` : {"language": {...}, "source": {...},
    "video_codec": {...}, "audio_codec": {...}} -- vocabulaire et
    normalisation entierement pilotes par le profil."""
    info = {"language": "", "resolution": "", "video_codec": "", "audio": "", "source": ""}
    if not text:
        return info

    info["language"] = _detect_via_aliases(text, alias_groups["language"])

    match = _RESOLUTION_RE.search(text)
    if match:
        info["resolution"] = match.group(1)

    info["video_codec"] = _detect_via_aliases(text, alias_groups["video_codec"])

    audio_codec = _detect_via_aliases(text, alias_groups["audio_codec"])
    if audio_codec:
        info["audio"] = audio_codec
        channels_match = _CHANNELS_RE.search(text)
        if channels_match:
            info["audio"] += f".{channels_match.group(1)}"

    info["source"] = _detect_via_aliases(text, alias_groups["source"])

    return info
```

Dans `propose_video_release_name()`, remplacer la ligne `language_aliases: dict[str, str] = config.get("language_aliases", {})` par :

```python
    alias_groups = {
        "language": config.get("language_aliases", {}),
        "source": config.get("source_aliases", {}),
        "video_codec": config.get("video_codec_aliases", {}),
        "audio_codec": config.get("audio_codec_aliases", {}),
    }
```

Et remplacer les deux appels à `_extract_release_info` :

```python
    info_from_filename = _extract_release_info(stems[0], alias_groups)
    info_from_hint = _extract_release_info(hints[0], alias_groups)
```

(le reste de la fonction -- fusion `_merge_release_info`, avertissements, construction du `template.format(**fields)` -- ne change pas)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_name_proposal.py -v`
Expected: PASS (tous les tests, existants + les 3 nouveaux)

- [ ] **Step 5: Run the full backend suite (non-régression au-delà de ce fichier)**

Run: `pytest -q`
Expected: tout passe -- `test_api.py`/tout autre test qui exercerait indirectement `propose_video_release_name` (ex. `POST /propose-name`) doit rester vert sans modification, preuve que le refactor est bien transparent pour les appelants.

- [ ] **Step 6: Lint**

Run: `ruff check nfogen/name_proposal.py tests/test_name_proposal.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add nfogen/name_proposal.py tests/test_name_proposal.py
git commit -m "AUTOMATION sous-projet 3 (1/2) : name_proposal.py agnostique

_detect_via_aliases() remplace 3 blocs regex+dict cables en dur
(source, codec video, codec audio) par un mecanisme generique
reutilise aussi pour la langue (deja declarative). Comportement
inchange pour le profil C411 (verifie par la suite de tests
existante, migree sans que ses assertions changent) -- seule la
provenance de la connaissance passe de Python a rules.json. 3
nouveaux tests prouvent la configurabilite reelle avec un profil
different de C411."
```

---

### Task 2: `nfogen/profiles/c411/rules.json` — peuple les alias réels

**Files:**
- Modify: `nfogen/profiles/c411/rules.json`
- Modify: `nfogen/rules.schema.json` (`additionalProperties: false` sur `name_proposal` rejette les 3 nouvelles clés sans cette extension — voir Step 3)

**Interfaces:**
- Consumes: rien de nouveau (le profil existant gagne des clés supplémentaires dans `video -> name_proposal`).

- [ ] **Step 1: Write a failing end-to-end check**

Pas un test unitaire dédié (Task 1 couvre déjà la logique) — vérification directe que le profil livré produit la même sortie qu'avant, en lisant `rules.json` directement (pas besoin de passer par `nfogen.registry`, qui charge des renderers Python enregistrés par décorateur, pas la configuration `name_proposal` elle-même). Lancer, depuis la racine du dépôt :

Run:
```bash
python -c "
import json
from nfogen.name_proposal import propose_video_release_name

with open('nfogen/profiles/c411/rules.json', encoding='utf-8') as f:
    rules = json.load(f)
config = rules.get('video', {}).get('name_proposal', {})

files = [
    'One Piece (1999) - S01E01 - 001 - Im Luffy! [WEBDL-1080p][AC3 2.0][FR+JA][x264 8bit].mkv',
    'One Piece (1999) - S01E02 - 002 - Enter Zoro! [WEBDL-1080p][AC3 2.0][FR+JA][x264 8bit].mkv',
]
print(propose_video_release_name(files, config).name)
"
```

(adapter l'appel exact à `nfogen.registry` si les noms de fonctions diffèrent -- vérifier avec `grep -n "def load_builtin_profiles\|def get_rules" nfogen/registry.py` avant d'écrire la commande finale)

Expected AVANT l'étape 2 (`rules.json` du profil C411 pas encore mis à jour, `source_aliases`/`video_codec_aliases`/`audio_codec_aliases` absents donc `_detect_via_aliases` renvoie `""` pour ces 3 champs) : `One.Piece.S01.MULTI.VFF.1080p.-NOTAG` — source/audio/codec vidéo vides, dots consécutifs collapsés en un seul par le nettoyage final (`re.sub(r"\.{2,}", ".", name)`), PAS `None` (le nom se construit quand même, juste incomplet).

- [ ] **Step 2: Update `rules.json`**

Dans `nfogen/profiles/c411/rules.json`, le bloc `video -> name_proposal` actuel :

```json
"name_proposal": {
    "template": "{title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}",
    "language_aliases": {
      "FR": "VFF",
      "VF": "VFF",
      "FR+EN": "MULTI.VFF",
      "EN+FR": "MULTI.VFF",
      "FR+JA": "MULTI.VFF",
      "JA+FR": "MULTI.VFF",
      "VO": "VO",
      "VOSTFR": "VOSTFR",
      "EN+VOSTFR": "VOSTFR"
    }
  }
```

devient (ajout de 3 clés, `template`/`language_aliases` inchangés) :

```json
"name_proposal": {
    "template": "{title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}",
    "language_aliases": {
      "FR": "VFF",
      "VF": "VFF",
      "FR+EN": "MULTI.VFF",
      "EN+FR": "MULTI.VFF",
      "FR+JA": "MULTI.VFF",
      "JA+FR": "MULTI.VFF",
      "VO": "VO",
      "VOSTFR": "VOSTFR",
      "EN+VOSTFR": "VOSTFR"
    },
    "source_aliases": {
      "WEBDL": "WEB",
      "WEB-DL": "WEB",
      "WEBRip": "WEB",
      "BDRip": "BDRip",
      "BDRemux": "BluRay.REMUX",
      "BluRay": "BluRay",
      "HDTV": "HDTV",
      "DVDRip": "DVDRip",
      "DSNP": "WEB.DSNP",
      "NF": "WEB.NF",
      "AMZN": "WEB.AMZN"
    },
    "video_codec_aliases": {
      "x264": "x264",
      "x265": "x265",
      "H.264": "h.264",
      "H264": "h264",
      "H.265": "h.265",
      "H265": "h265",
      "HEVC": "hevc",
      "AVC": "avc",
      "MPEG-2": "mpeg-2",
      "MPEG2": "mpeg2"
    },
    "audio_codec_aliases": {
      "AC3": "AC3",
      "EAC3": "EAC3",
      "AAC": "AAC",
      "DTS-HD": "DTS-HD",
      "DTS": "DTS",
      "FLAC": "FLAC",
      "MP3": "MP3",
      "OPUS": "OPUS",
      "TRUEHD": "TRUEHD"
    }
  }
```

- [ ] **Step 3: Update `rules.schema.json`**

Confirmé en le lisant : `name_proposal`'s schema a `"additionalProperties": false` et ne déclare que `template`/`language_aliases` — les 3 nouvelles clés seraient **rejetées** par toute validation contre ce schéma sans cette étape (`nfogen/declarative_profile.py`/`profile_store.py` valident `rules.json` contre ce schéma à l'écriture). Dans `nfogen/rules.schema.json`, le bloc `name_proposal` (repérable via `grep -n '"name_proposal"' nfogen/rules.schema.json`) :

```json
    "name_proposal": {
      "type": "object",
      "description": "Proposition de release_name a partir des noms de fichiers (categorie video uniquement, cf. nfogen/name_proposal.py). Placeholders disponibles dans 'template' : {title} {identifier} {language} {resolution} {video_codec} {audio} {source} {team}.",
      "properties": {
        "template": { "type": "string" },
        "language_aliases": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        }
      },
      "additionalProperties": false
    },
```

devient :

```json
    "name_proposal": {
      "type": "object",
      "description": "Proposition de release_name a partir des noms de fichiers (categorie video uniquement, cf. nfogen/name_proposal.py). Placeholders disponibles dans 'template' : {title} {identifier} {language} {resolution} {video_codec} {audio} {source} {team}.",
      "properties": {
        "template": { "type": "string" },
        "language_aliases": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        },
        "source_aliases": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        },
        "video_codec_aliases": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        },
        "audio_codec_aliases": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        }
      },
      "additionalProperties": false
    },
```

- [ ] **Step 4: Re-run the end-to-end check**

Run: la même commande qu'à l'étape 1.
Expected: `One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG` (exactement la même valeur que celle attendue par `tests/test_name_proposal.py::test_season_pack_real_world_case`, qui utilise les mêmes fichiers).

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`
Expected: tout passe, y compris toute validation de `rules.json` contre `rules.schema.json` (le profil C411 doit continuer à se charger/valider sans erreur avec les 3 nouvelles clés).

- [ ] **Step 6: Lint**

Run: `ruff check .`
Expected: clean (JSON n'est pas linté par ruff, mais vérifie qu'aucun fichier Python n'a été affecté par erreur)

- [ ] **Step 7: Commit**

```bash
git add nfogen/profiles/c411/rules.json nfogen/rules.schema.json
git commit -m "AUTOMATION sous-projet 3 (2/2) : peuple les alias C411 reels

source_aliases/video_codec_aliases/audio_codec_aliases du profil
C411, reproduisant exactement les valeurs precedemment cablees en
dur dans name_proposal.py. rules.schema.json etendu (additionalProperties
false interdisait ces 3 nouvelles cles). Verifie qu'un cas reel
(One Piece, saison 1) produit exactement le meme nom qu'avant ce
sous-projet."
```

---

## Après ce plan

`name_proposal.py` est désormais entièrement piloté par `rules.json` pour
tout ce qui concerne le vocabulaire/la normalisation source et codecs — un
futur tracker différent de C411 n'aura qu'un nouveau profil à écrire, pas
de code Python à toucher. Mettre à jour `AUTOMATION.md` : sous-projet 3 de
"Conception ci-dessus" à "Livré". Sous-projet 4 (orchestration du nommage
dans le pipeline d'automatisation — utilise ce moteur + les sous-projets 1
et 2) à concevoir ensuite.
