# Pack multi-saisons / INTEGRALE — Design

## Contexte

Retour utilisateur, 2026-09-08 (suite au sous-projet 1 "tag d'équipe par
ligne", déjà livré) : quand plusieurs saisons consécutives d'une même
série proviennent de la même équipe, l'utilisateur veut pouvoir les
regrouper en **un seul upload** au lieu d'un par saison — moins de
travail, moins d'entrées séparées sur le tracker.

Convention de nommage confirmée via la doc "Le Nommage de l'upload" du
wiki C411 (collée par l'utilisateur, 2026-09-08) :

- **Pack saisons multiples** (sous-ensemble, saisons consécutives
  disponibles) : `Nom.SxxSyy.Langue.Résolution.Source.CodecAudio.CodecVidéo-TEAM`
  (ex. `Berzerk.S01S03...`, `Doctor.Who.2005.S01S05...`).
- **Pack INTEGRALE** (littéralement **toutes** les saisons connues de la
  série) : `Nom.INTEGRALE.Langue.Résolution.Source.CodecAudio.CodecVidéo-TEAM`
  — sauf saison unique, où le token `S01` est conservé à côté
  (`Serie.S01.INTEGRALE...`), sinon les stacks *arr ne peuvent plus
  identifier la saison.
- **Jamais de mélange d'équipes dans un même pack** (voir "Le DETAG et
  Manipulation de NFO") — confirmé explicitement par l'utilisateur :
  "le pack avec des team différente est bien refusé".

**Rappel du principe directeur du projet** (déjà appliqué à
`torznab_categories`/`torrent_source`/`name_proposal.template`, etc.) :
rien de spécifique à un tracker en dur en Python — la convention
`SxxSyy`/`INTEGRALE` ci-dessus est propre à C411, donc **déclarative
dans `rules.json`**, jamais codée en dur.

## Objectif

1. Détecter, dans la Bibliothèque, les runs de saisons **consécutives**
   d'une même série partageant la **même équipe** (jamais de mélange).
2. Proposer ces groupes à l'utilisateur (nouveau bloc "Packs
   disponibles" au-dessus du tableau).
3. Permettre de préparer et d'uploader un pack combiné (un seul
   `.torrent`, un seul envoi C411) à partir d'un groupe détecté, en
   réutilisant le flux "Préparer l'upload" existant.

## Hors périmètre (explicitement)

- Détection inter-séries (le regroupement reste toujours à l'intérieur
  d'UNE série, jamais entre deux séries différentes).
- Correction manuelle du tag d'équipe détecté (si `team` est erroné pour
  une saison, ça reste un problème du sous-projet 1, pas de ce
  sous-projet).
- Gestion des séries dont TOUTES les saisons ne sont pas encore
  localement disponibles au moment du pack — "INTEGRALE" ne porte que
  sur les saisons **connues localement** (voir Section A), pas sur le
  nombre réel de saisons de la série sur TMDB/TVDB (hors de portée : un
  pack INTEGRALE ne peut être proposé que quand nfogen n'a plus de trou
  dans ce qu'il connaît, jamais une promesse sur le futur de la série).

## Architecture — vue d'ensemble

Trois morceaux, backend puis frontend :

- **A. Détection & nommage** (`nfogen/gapscan_library.py` + nouveau
  `nfogen/name_proposal.py:propose_season_pack_name()`).
- **B. Affichage** (`GET /gapscan/library`, `LibraryPage.tsx`).
- **C. Mise en scène & upload combiné** (`nfogen/upload_prep.py`,
  `UploadPrepPanel.tsx` ou équivalent).

## A. Détection & nommage

### A.1 Détection des groupes (nouvelle fonction pure)

```python
@dataclass
class SeasonPackSuggestion:
    series_key: str          # tvdb_id ou cle stable de la serie
    title: str
    year: Optional[int]
    team: str
    season_numbers: list[int]   # ordre croissant, toujours consecutifs
    is_full_series: bool        # True -> INTEGRALE, False -> SxxSyy
    item_keys: list[str]        # LibraryItem.key des saisons du groupe
    sonarr_series_id: int


def detect_season_packs(items: list[LibraryItem]) -> list[SeasonPackSuggestion]:
    """Sur la bibliotheque COMPLETE (non filtree/non paginee, deja en
    cache -- voir api.py:_cached_library_items) : groupe les items
    media_type == "series" par sonarr_series_id, trie par season_number,
    repere les runs MAXIMAUX de saisons consecutives partageant le MEME
    `team` (jamais None, jamais mixte). Un run de longueur 1 (saison
    isolee) n'est jamais propose. `is_full_series` : True si le run
    couvre TOUTES les saisons connues localement pour cette serie (pas
    de saison manquante dans local_paths/season_number en dehors du
    run)."""
```

Pure fonction, testable sans I/O (prend une liste de `LibraryItem` déjà
récupérée). Aucun nouvel appel Radarr/Sonarr.

### A.2 Nommage déclaratif (`rules.json`)

Nouveau champ optionnel sous `video.name_proposal` (voir
`rules.schema.json`, `$defs.name_proposal`) :

```json
"name_proposal": {
  "template": "{title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}",
  "season_pack": {
    "range_format": "S{start:02d}S{end:02d}",
    "integrale_tag": "INTEGRALE",
    "integrale_single_season_format": "S{season:02d}.{integrale_tag}"
  }
}
```

Profil sans section `season_pack` déclarée : la fonctionnalité pack
reste **désactivée** pour ce profil (aucune suggestion affichée) — même
discipline que `torrent_piece_sizes`/`torznab_categories` vides.

### A.3 Nouvelle fonction de proposition de nom

```python
def propose_season_pack_name(
    *,
    title: str,
    season_numbers: list[int],
    is_full_series: bool,
    team: str,
    quality_fields: dict[str, str],   # language/resolution/source/video_codec/audio
    config: dict[str, Any],           # video.name_proposal du profil
) -> NameProposal:
```

**Délibérément séparée** de `propose_release_name()` existant : celui-ci
détecte saison/équipe en PARSANT des noms de fichiers, et **rejette
explicitement** plusieurs saisons détectées (`name_proposal.py:220-228`,
"impossible de proposer un nom de pack unique") — comportement correct
pour son cas d'usage (un seul groupe de fichiers, jamais un pack
multi-saisons délibéré). `propose_season_pack_name()` part au contraire
d'informations **déjà connues et validées** (saisons du groupe, équipe
unique déjà garantie par `detect_season_packs`), calcule `identifier`
via `season_pack.range_format`/`integrale_tag`/
`integrale_single_season_format` du profil, puis réutilise le même
`template.format(**fields)` que l'existant. `quality_fields` vient d'un
fichier représentatif du groupe (le premier fichier de la première
saison, même logique que `first_metadata` dans
`upload_prep.send_to_tracker` — extraction MediaInfo réelle, pas
devinée).

## B. Affichage

`GET /gapscan/library` (déjà en cache, voir
`api.py:_cached_library_items`) gagne un champ `season_packs:
list[SeasonPackSuggestion]` dans sa réponse — calculé sur le résultat
BRUT (avant filtre `q`/pagination), donc jamais masqué par un filtre
actif. Frontend (`LibraryPage.tsx`) : nouveau bloc **"Packs
disponibles"** juste au-dessus du tableau (visible seulement si
`season_packs` non vide), une ligne par groupe :

```
Lucifer — S05S06 (Frosties)              [Préparer le pack]
Lucifer — INTEGRALE, saisons 1-4 (MiND)  [Préparer le pack]
```

Le bouton "Préparer le pack" ouvre le panneau "Préparer l'upload"
existant (`UploadPrepPanel`), avec les `local_paths` fusionnés du
groupe (voir Section C) au lieu d'une seule saison.

## C. Mise en scène & upload combiné

### C.1 Fusion des chemins locaux

Les `local_paths` de chaque `LibraryItem` du groupe (déjà résolus par le
mapping de chemins existant, sous-projet 1) sont concaténés. Chaque
fichier reçoit un nom de mise en scène préfixé par sa saison :
`S{season:02d}/{nom_de_fichier_original}` — **aucun changement requis**
à `file_staging.stage_files()`, qui joint déjà `target_dir` et `name`
via `Path(target_dir) / name` (supporte nativement les sous-dossiers,
confirmé en lisant `file_staging.py:103`).

### C.2 Flux `preview_upload`/`commit_upload`

`upload_prep.preview_upload()` prend aujourd'hui une simple liste de
chemins et un `profile` — nouveau paramètre optionnel `season_pack:
Optional[SeasonPackRequest]` (titre, saisons, team, is_full_series, déjà
calculés côté frontend/endpoint dédié) qui, s'il est fourni, **court-
circuite** `group_by_team()`/`propose_release_name()` habituels et
appelle directement `propose_season_pack_name()` (Section A.3) pour tout
le groupe fusionné, comme un seul et unique `GroupProposal`. Le reste de
`commit_upload()` (mise en scène, `.nfo`, `.torrent`) fonctionne déjà
pour un dossier multi-fichiers (cas pack saison unique existant) — un
pack multi-saisons n'est qu'un dossier avec plus de fichiers et une
structure de sous-dossiers, rien de nouveau à ce niveau.

### C.3 `.nfo` du pack

`engine.generate()` (déjà utilisé par `commit_upload`) prend le
`raw_text` MediaInfo du contenu mis en scène — pour un pack
multi-saisons, `extract.extract_video_dir_text()` (déjà utilisé pour un
pack saison unique) fonctionne tel quel sur l'arborescence
`S01/`, `S02/`, ... (parcours récursif déjà en place, à vérifier lors de
l'implémentation — pas un nouveau composant si c'est déjà le cas).

## Gestion d'erreur

| Cas | Comportement |
|---|---|
| Profil sans `season_pack` déclaré | Aucune suggestion affichée, comportement actuel inchangé |
| Équipes différentes entre saisons voisines | Jamais regroupées (le run s'arrête net à la frontière d'équipe) |
| Saison isolée (pas de voisine consécutive même équipe) | Pas de suggestion pour elle, upload normal saison par saison |
| Une des saisons du groupe a `local_paths` non résolu | Le groupe entier est exclu de la suggestion (mieux vaut rien proposer qu'un pack incomplet) |

## Tests

- `tests/test_gapscan_library.py` : `detect_season_packs()` — runs
  consécutifs même équipe, coupure sur changement d'équipe, saison
  isolée jamais proposée, `is_full_series` correct (couvre vs ne couvre
  pas toutes les saisons locales connues), jamais de fusion inter-séries.
- `tests/test_name_proposal.py` : `propose_season_pack_name()` — rendu
  `SxxSyy`, rendu `INTEGRALE`, cas spécial saison unique + INTEGRALE
  (`S01.INTEGRALE`), profil sans `season_pack` déclaré.
- `tests/test_api.py` : `GET /gapscan/library` expose `season_packs`,
  calculé sur la bibliothèque non filtrée.
- `tests/test_upload_prep.py` : `preview_upload(..., season_pack=...)`
  produit un `GroupProposal` unique avec tous les fichiers fusionnés,
  noms préfixés par saison ; `commit_upload()` met en scène la structure
  de sous-dossiers correctement.
- Frontend : `LibraryPage.test.tsx` (bloc "Packs disponibles" affiché/
  masqué selon `season_packs`), test du panneau "Préparer l'upload"
  ouvert avec les chemins fusionnés.
