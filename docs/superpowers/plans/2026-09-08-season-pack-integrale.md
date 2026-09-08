# Pack multi-saisons / INTEGRALE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (pas de subagents sur ce projet — preference utilisateur etablie). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detecter les runs de saisons consecutives d'une meme equipe dans la Bibliotheque, les proposer a l'utilisateur, et permettre de les uploader en un seul pack (`SxxSyy` ou `INTEGRALE`) via le flux "Preparer l'upload" existant.

**Architecture:** Trois couches : detection pure (`gapscan_library.py`), nommage declaratif via `rules.json` (`name_proposal.py`, nouvelle fonction separee de la proposition par-fichier existante), assemblage/upload (extension de `upload_prep.preview_upload()` — `commit_upload()` ne change PAS, il accepte deja des `staged_name` avec sous-dossiers).

**Tech Stack:** Python (FastAPI/pydantic backend), React/TypeScript (frontend) — aucune nouvelle dependance.

**Spec:** [docs/superpowers/specs/2026-09-08-season-pack-integrale-design.md](../specs/2026-09-08-season-pack-integrale-design.md)

## Global Constraints

- Jamais de convention de nommage C411 codee en dur en Python — `SxxSyy`/`INTEGRALE` viennent de `rules.json -> video -> name_proposal.season_pack`, absent = fonctionnalite desactivee pour ce profil.
- Jamais de mélange d'équipes dans un même pack — un run s'arrête net à toute frontière d'équipe (ou saison sans équipe détectée).
- Une saison isolée (pas de voisine consécutive même équipe) n'est jamais proposée en pack.
- `is_full_series` (déclenche `INTEGRALE`) se calcule sur **toutes les saisons connues localement pour cette série** (présentes dans la Bibliothèque), pas seulement celles éligibles au regroupement — une saison sans équipe détectée compte quand même comme "connue", donc bloque `INTEGRALE` si elle n'est pas dans le run.
- `commit_upload()` et son endpoint HTTP restent **inchangés** — `file_staging.stage_files()` accepte déjà des `staged_name` avec sous-dossier (`Path(target_dir) / name`, confirmé dans le code).

---

### Task 1 : Config déclarative `season_pack` (rules.json + schema)

**Files:**
- Modify: `nfogen/rules.schema.json`
- Modify: `nfogen/profiles/c411/rules.json`
- Test: `tests/test_rules.py` (ou fichier équivalent testant la validation du schéma — vérifier le nom exact avant d'écrire le test, ne pas le deviner)

**Interfaces:**
- Produces: `rules.json -> video -> name_proposal.season_pack` = `{"range_format": str, "integrale_tag": str, "integrale_single_season_format": str}` (les trois sous-champs optionnels, absents = comportement par défaut défini dans Task 2).

- [ ] **Step 1: Localiser le fichier de test qui valide déjà `rules.schema.json`**

Run: `grep -rn "rules.schema.json\|validate_rules_document" tests/*.py`

Repère le fichier qui teste déjà la validation d'un `rules.json` complet
(probablement `tests/test_rules.py` ou `tests/test_profile_store.py`) —
utilise le MÊME mécanisme pour le test de cette tâche, ne le réinvente
pas.

- [ ] **Step 2: Write the failing test**

Dans le fichier repéré à l'étape 1, ajoute (adapte le nom de fonction
d'écriture de profil déjà utilisé dans ce fichier — `profile_store.write_profile`
ou équivalent) :

```python
def test_season_pack_config_is_valid_in_schema():
    rules = {
        "video": {
            "name_proposal": {
                "template": "{title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}",
                "season_pack": {
                    "range_format": "S{start:02d}S{end:02d}",
                    "integrale_tag": "INTEGRALE",
                    "integrale_single_season_format": "S{season:02d}.{integrale_tag}",
                },
            }
        }
    }
    # Ne doit pas lever ValueError (voir rules_engine.validate_rules_document).
    ps.write_profile("season-pack-test", rules=rules, templates={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rules.py -k season_pack -v`
Expected: FAIL (`ValueError: ... 'season_pack' was unexpected` ou similaire)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/rules.schema.json`, section `$defs.name_proposal.properties`,
ajoute :

```json
"season_pack": {
  "type": "object",
  "description": "Convention de nommage pour un pack multi-saisons (voir gapscan_library.detect_season_packs) -- propre au tracker, jamais codee en dur en Python. Absent : fonctionnalite pack desactivee pour ce profil.",
  "properties": {
    "range_format": { "type": "string" },
    "integrale_tag": { "type": "string" },
    "integrale_single_season_format": { "type": "string" }
  },
  "additionalProperties": false
}
```

Dans `nfogen/profiles/c411/rules.json`, section `video.name_proposal`,
ajoute :

```json
"season_pack": {
  "range_format": "S{start:02d}S{end:02d}",
  "integrale_tag": "INTEGRALE",
  "integrale_single_season_format": "S{season:02d}.{integrale_tag}"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rules.py -k season_pack -v`
Expected: PASS

- [ ] **Step 5: Run full backend suite (le profil c411 livré change)**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tout passe (aucune régression sur les tests qui lisent déjà
`nfogen/profiles/c411/rules.json`).

- [ ] **Step 6: Commit**

```bash
git add nfogen/rules.schema.json nfogen/profiles/c411/rules.json tests/test_rules.py
git commit -m "feat: config declarative season_pack (rules.json) pour le nommage des packs"
```

---

### Task 2 : `name_proposal.propose_season_pack_name()`

**Files:**
- Modify: `nfogen/name_proposal.py`
- Test: `tests/test_name_proposal.py`

**Interfaces:**
- Consumes: `_extract_release_info(text, alias_groups)`, `_normalize_title_text(text)` (déjà privées dans ce module, réutilisées telles quelles).
- Produces: `propose_season_pack_name(*, title: str, season_numbers: list[int], is_full_series: bool, team: str, representative_filename: str, config: dict[str, Any]) -> NameProposal`.

- [ ] **Step 1: Write the failing tests**

Ajoute dans `tests/test_name_proposal.py` (regarde d'abord le début du
fichier pour repérer le nom exact de la fixture de config déjà utilisée
par les tests de `propose_video_release_name` — probablement une
constante `CONFIG`/`FULL_CONFIG` avec `template`/`*_aliases` — réutilise-la
et étends-la avec `season_pack`, ne recrée pas une config from scratch) :

```python
def test_propose_season_pack_name_partial_range():
    config = {
        **CONFIG,  # config existante du fichier, deja avec template + aliases
        "season_pack": {"range_format": "S{start:02d}S{end:02d}", "integrale_tag": "INTEGRALE"},
    }
    result = name_proposal.propose_season_pack_name(
        title="Lucifer", season_numbers=[5, 6], is_full_series=False, team="Frosties",
        representative_filename="Lucifer.S05E01.MULTI.VFF.1080p.WEB.AAC.2.0.x265-Frosties.mkv",
        config=config,
    )
    assert result.name == "Lucifer.S05S06.MULTI.1080p.WEB.AAC.2.0.x265-Frosties"


def test_propose_season_pack_name_full_series_uses_integrale():
    config = {
        **CONFIG,
        "season_pack": {"range_format": "S{start:02d}S{end:02d}", "integrale_tag": "INTEGRALE"},
    }
    result = name_proposal.propose_season_pack_name(
        title="Breaking Bad", season_numbers=[1, 2, 3], is_full_series=True, team="MiND",
        representative_filename="Breaking.Bad.S01E01.MULTI.VFF.720p.BluRay.AC3.5.1.x264-MiND.mkv",
        config=config,
    )
    assert result.name is not None
    assert "INTEGRALE" in result.name
    assert "S01" not in result.name  # pas de token saison pour une integrale multi-saisons


def test_propose_season_pack_name_single_season_integrale_keeps_season_token():
    config = {
        **CONFIG,
        "season_pack": {
            "range_format": "S{start:02d}S{end:02d}", "integrale_tag": "INTEGRALE",
            "integrale_single_season_format": "S{season:02d}.{integrale_tag}",
        },
    }
    result = name_proposal.propose_season_pack_name(
        title="Show", season_numbers=[1], is_full_series=True, team="TEAM",
        representative_filename="Show.S01E01.VFF.1080p.WEB.AAC.2.0.x264-TEAM.mkv",
        config=config,
    )
    assert result.name is not None
    assert "S01.INTEGRALE" in result.name


def test_propose_season_pack_name_none_when_season_pack_not_configured():
    result = name_proposal.propose_season_pack_name(
        title="Show", season_numbers=[1, 2], is_full_series=False, team="TEAM",
        representative_filename="Show.S01E01.VFF.1080p.WEB.AAC.2.0.x264-TEAM.mkv",
        config=CONFIG,  # sans season_pack
    )
    assert result.name is None
    assert "season_pack" in result.warnings[0]
```

Vérifie que `CONFIG` (ou le nom réel de la fixture) contient bien des
alias reconnaissant `MULTI`/`WEB`/`AAC`/`x265`/`BluRay`/`AC3`/`x264` dans
les tests existants du fichier — si les alias diffèrent, adapte les
noms de fichiers représentatifs ci-dessus pour matcher les alias
RÉELLEMENT déclarés dans la fixture (ne pas deviner un vocabulaire qui
n'existe pas dans la config de test).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -k season_pack -v`
Expected: FAIL (`AttributeError: module 'nfogen.name_proposal' has no attribute 'propose_season_pack_name'`)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/name_proposal.py`, ajoute (après `propose_video_release_name`) :

```python
def propose_season_pack_name(
    *,
    title: str,
    season_numbers: list[int],
    is_full_series: bool,
    team: str,
    representative_filename: str,
    config: dict[str, Any],
) -> NameProposal:
    """Construit un release_name pour un pack MULTI-SAISONS deja valide
    par l'appelant (memes equipe garantie, saisons consecutives -- voir
    gapscan_library.detect_season_packs). Delibrement separee de
    `propose_video_release_name` : celle-ci detecte saison/equipe en
    PARSANT des noms de fichiers et REJETTE explicitement plusieurs
    saisons detectees (comportement correct pour un groupe de fichiers
    ordinaire, jamais pour un pack assemble deliberement). `season_numbers`
    doit deja etre trie et consecutif. `is_full_series` : True -> tag
    INTEGRALE (rules.json -> video -> name_proposal.season_pack.integrale_tag,
    ou season_pack.integrale_single_season_format si une seule saison) ;
    False -> intervalle (season_pack.range_format). Absence de
    `season_pack` dans `config` : fonctionnalite desactivee pour ce
    profil, echec explicite plutot qu'une convention devinee."""
    template = config.get("template")
    if not template:
        return NameProposal(
            None, {}, ["Aucun modèle de proposition configuré pour ce profil (rules.json -> video -> name_proposal.template)."]
        )
    season_pack_config = config.get("season_pack")
    if not season_pack_config:
        return NameProposal(
            None, {},
            ["Pack multi-saisons non configuré pour ce profil (rules.json -> video -> name_proposal.season_pack)."],
        )

    integrale_tag = season_pack_config.get("integrale_tag", "INTEGRALE")
    if is_full_series:
        if len(season_numbers) == 1:
            single_format = season_pack_config.get(
                "integrale_single_season_format", "S{season:02d}.{integrale_tag}"
            )
            identifier = single_format.format(season=season_numbers[0], integrale_tag=integrale_tag)
        else:
            identifier = integrale_tag
    else:
        range_format = season_pack_config.get("range_format", "S{start:02d}S{end:02d}")
        identifier = range_format.format(start=season_numbers[0], end=season_numbers[-1])

    alias_groups: dict[str, dict[str, str]] = {
        "language": config.get("language_aliases", {}),
        "source": config.get("source_aliases", {}),
        "video_codec": config.get("video_codec_aliases", {}),
        "audio_codec": config.get("audio_codec_aliases", {}),
    }
    info = _extract_release_info(representative_filename, alias_groups)

    fields = {
        "title": _normalize_title_text(title),
        "identifier": identifier,
        "language": info["language"],
        "resolution": info["resolution"],
        "video_codec": info["video_codec"],
        "audio": info["audio"],
        "source": info["source"],
        "team": team,
    }
    try:
        name = template.format(**fields)
    except KeyError as exc:
        return NameProposal(None, fields, [f"Champ manquant dans le modèle de proposition : {exc}"])

    name = re.sub(r"\.{2,}", ".", name).strip(".")
    name = re.sub(r"\.-", "-", name)
    return NameProposal(name, fields, [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_name_proposal.py -v`
Expected: PASS (tous les tests existants ET les nouveaux)

- [ ] **Step 5: Commit**

```bash
git add nfogen/name_proposal.py tests/test_name_proposal.py
git commit -m "feat: propose_season_pack_name -- nommage SxxSyy/INTEGRALE declaratif"
```

---

### Task 3 : `gapscan_library.detect_season_packs()`

**Files:**
- Modify: `nfogen/gapscan_library.py`
- Test: `tests/test_gapscan_library.py`

**Interfaces:**
- Consumes: `LibraryItem` (déjà défini, gagne `team` depuis le sous-projet 1 précédent).
- Produces: `SeasonPackSuggestion` (dataclass), `detect_season_packs(items: list[LibraryItem]) -> list[SeasonPackSuggestion]`.

- [ ] **Step 1: Write the failing tests**

Ajoute dans `tests/test_gapscan_library.py` :

```python
from nfogen.gapscan_library import SeasonPackSuggestion, detect_season_packs


def _series_item(season_number, team, sonarr_series_id=7, title="Lucifer", year=2016, path_resolved=True):
    return gapscan_library.LibraryItem(
        media_type="series", title=title, year=year, season_number=season_number,
        imdb_id=None, tvdb_id=99, tmdb_id=None, genres=[], added_at=None,
        local_quality=ReleaseQuality(raw="", resolution=None, source=None, codec=None, languages=[], multi=False, pure=False),
        radarr_movie_id=None, sonarr_series_id=sonarr_series_id, already_processed=False, last_processed_at=None,
        key=f"key-s{season_number}", path_resolved=path_resolved,
        local_paths=[f"/media/Lucifer/S{season_number:02d}/ep1.mkv"] if path_resolved else [],
        team=team,
    )


def test_detect_season_packs_groups_consecutive_seasons_same_team():
    items = [_series_item(5, "Frosties"), _series_item(6, "Frosties")]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [5, 6]
    assert suggestions[0].team == "Frosties"
    assert suggestions[0].is_full_series is True  # seules saisons connues = 5,6


def test_detect_season_packs_breaks_run_on_different_team():
    items = [_series_item(1, "TeamA"), _series_item(2, "TeamA"), _series_item(3, "TeamB")]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [1, 2]
    assert suggestions[0].is_full_series is False  # saison 3 existe mais TeamB


def test_detect_season_packs_never_proposes_a_lone_season():
    items = [_series_item(1, "TEAM"), _series_item(3, "TEAM")]  # non consecutives
    suggestions = detect_season_packs(items)
    assert suggestions == []


def test_detect_season_packs_never_merges_different_series():
    items = [
        _series_item(1, "TEAM", sonarr_series_id=1, title="A"),
        _series_item(1, "TEAM", sonarr_series_id=2, title="B"),
    ]
    assert detect_season_packs(items) == []  # une seule saison chacune, jamais fusionnees entre series


def test_detect_season_packs_excludes_seasons_without_team_or_unresolved_path():
    items = [_series_item(1, None), _series_item(2, "TEAM"), _series_item(3, "TEAM")]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [2, 3]
    assert suggestions[0].is_full_series is False  # saison 1 existe (meme sans team), donc pas INTEGRALE
```

Vérifie le nom exact de l'import `ReleaseQuality` déjà utilisé en tête de
ce fichier de test (déjà importé, voir les tests existants) avant
d'écrire `_series_item` — ne duplique pas un import déjà présent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_library.py -k detect_season_packs -v`
Expected: FAIL (`ImportError: cannot import name 'detect_season_packs'`)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/gapscan_library.py`, ajoute (après la classe `LibraryItem`) :

```python
@dataclass
class SeasonPackSuggestion:
    """Groupe de saisons consecutives d'UNE serie, meme equipe, propose en
    pack (retour utilisateur, 2026-09-08). Voir detect_season_packs."""

    sonarr_series_id: int
    title: str
    year: Optional[int]
    team: str
    season_numbers: list[int]  # trie, consecutif
    is_full_series: bool  # True -> INTEGRALE, False -> intervalle SxxSyy
    item_keys: list[str]  # LibraryItem.key des saisons du groupe, meme ordre


def detect_season_packs(items: list[LibraryItem]) -> list[SeasonPackSuggestion]:
    """Sur la bibliotheque COMPLETE (non filtree/non paginee) : groupe les
    items serie par sonarr_series_id, repere les runs MAXIMAUX de saisons
    CONSECUTIVES partageant la MEME equipe (jamais None, jamais mixte).
    Un run de longueur 1 n'est jamais propose. `is_full_series` : True si
    le run couvre TOUTES les saisons CONNUES LOCALEMENT pour cette serie
    (y compris celles sans equipe detectee/chemin non resolu -- une
    saison "vue" mais pas eligible au regroupement bloque quand meme
    INTEGRALE, elle n'est simplement pas dans le run)."""
    all_seasons_by_series: dict[int, set[int]] = {}
    eligible_by_series: dict[int, list[LibraryItem]] = {}
    for item in items:
        if item.media_type != "series" or item.sonarr_series_id is None or item.season_number is None:
            continue
        all_seasons_by_series.setdefault(item.sonarr_series_id, set()).add(item.season_number)
        if item.team and item.path_resolved and item.local_paths:
            eligible_by_series.setdefault(item.sonarr_series_id, []).append(item)

    suggestions: list[SeasonPackSuggestion] = []
    for series_id, series_items in eligible_by_series.items():
        series_items.sort(key=lambda i: i.season_number)  # type: ignore[arg-type]
        all_seasons = all_seasons_by_series.get(series_id, set())

        def flush(run: list[LibraryItem]) -> None:
            if len(run) < 2:
                return
            season_numbers = [i.season_number for i in run]  # type: ignore[misc]
            suggestions.append(
                SeasonPackSuggestion(
                    sonarr_series_id=series_id,
                    title=run[0].title,
                    year=run[0].year,
                    team=run[0].team,  # type: ignore[arg-type]
                    season_numbers=season_numbers,
                    is_full_series=set(season_numbers) == all_seasons,
                    item_keys=[i.key for i in run],
                )
            )

        run: list[LibraryItem] = []
        for item in series_items:
            if run and item.team == run[-1].team and item.season_number == (run[-1].season_number or 0) + 1:
                run.append(item)
            else:
                flush(run)
                run = [item]
        flush(run)

    return suggestions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_library.py -v`
Expected: PASS (tous les tests du fichier)

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_library.py tests/test_gapscan_library.py
git commit -m "feat: detect_season_packs -- runs de saisons consecutives meme equipe"
```

---

### Task 4 : `GET /gapscan/library` expose `season_packs`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `gapscan_library.detect_season_packs(items)` (Task 3), `_cached_library_items()` (déjà existant, résultat BRUT non filtré).
- Produces: réponse JSON de `GET /gapscan/library` gagne la clé `season_packs: list[dict]` (sérialisation `asdict(SeasonPackSuggestion)`).

- [ ] **Step 1: Write the failing test**

Ajoute dans `tests/test_api.py`, à côté des tests `/gapscan/library`
existants (réutilise `_FakeGapscanSonarr` du fichier — vérifie qu'il
expose déjà `scene_name`/team-compatible ; sinon ajoute une variante
locale au test comme déjà fait pour `_FakeGapscanRadarrThreeMovies`) :

```python
class _FakeGapscanSonarrTwoSeasonsSameTeam:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def list_season_files(self):
        return [
            SonarrSeasonFile(
                series_id=7, title="Lucifer", year=2016, tvdb_id=99, imdb_id=None,
                season_number=5, episode_file_count=10,
                scene_name="Lucifer.S05.MULTI.VFF.1080p.WEB.AAC.2.0.x265-Frosties",
            ),
            SonarrSeasonFile(
                series_id=7, title="Lucifer", year=2016, tvdb_id=99, imdb_id=None,
                season_number=6, episode_file_count=10,
                scene_name="Lucifer.S06.MULTI.VFF.1080p.WEB.AAC.2.0.x265-Frosties",
            ),
        ]

    def close(self):
        self.closed = True


def test_gapscan_library_exposes_season_packs(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_SONARR_URL="http://sonarr.local", NFOGEN_SONARR_API_KEY="y",
    )
    monkeypatch.setattr(mod, "SonarrClient", _FakeGapscanSonarrTwoSeasonsSameTeam)
    client = TestClient(mod.app)

    body = client.get("/gapscan/library").json()
    assert len(body["season_packs"]) == 1
    assert body["season_packs"][0]["team"] == "Frosties"
    assert body["season_packs"][0]["season_numbers"] == [5, 6]
    assert body["season_packs"][0]["is_full_series"] is True
```

Vérifie l'import de `SonarrSeasonFile` déjà présent en tête de
`tests/test_api.py` (déjà utilisé par d'autres fakes Sonarr existants).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k exposes_season_packs -v`
Expected: FAIL (`KeyError: 'season_packs'`)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/api.py`, ajoute l'import :

```python
from .gapscan_library import detect_season_packs  # a cote de l'import gapscan_library existant, ou en plus si gapscan_library est deja importe comme module
```

(si `gapscan_library` est déjà importé comme module entier dans ce
fichier — vérifie avec `grep -n "^from \.gapscan_library\|^from nfogen.gapscan_library\|import gapscan_library" nfogen/api.py` — utilise alors
`gapscan_library.detect_season_packs(...)` directement sans nouvel
import, cohérent avec le style déjà en place.)

Dans `gapscan_library_endpoint`, juste après le calcul de `items` (avant
le filtrage `q`/`media_type`/etc.) :

```python
    season_packs = gapscan_library.detect_season_packs(items)
```

Et dans le `return` final de l'endpoint, ajoute la clé :

```python
    return {
        "items": [asdict(i) for i in page_items], "total": total,
        "season_packs": [asdict(p) for p in season_packs],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "gapscan_library" -v`
Expected: PASS (tous les tests `/gapscan/library`, y compris les
existants sur le cache — `season_packs` calculé sur le résultat brut mis
en cache, pas de nouvel appel Radarr/Sonarr).

- [ ] **Step 5: Run full backend suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tout passe.

- [ ] **Step 6: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: GET /gapscan/library expose season_packs"
```

---

### Task 5 : `upload_prep.preview_upload(season_pack=...)`

**Files:**
- Modify: `nfogen/upload_prep.py`
- Test: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: `name_proposal.propose_season_pack_name` (Task 2), `extract.extract_video_metadata` (déjà utilisé ailleurs dans ce fichier pour `_extraction_warning`), `read_profile` (déjà importé).
- Produces: nouvelle dataclass `SeasonPackSeasonFiles(season_number: int, local_paths: list[str])`, `SeasonPackRequest(title: str, team: str, is_full_series: bool, seasons: list[SeasonPackSeasonFiles])` ; `preview_upload(local_paths, profile="c411", title_override=None, season_pack: Optional[SeasonPackRequest] = None) -> list[GroupProposal]` — quand `season_pack` est fourni, `local_paths` est ignoré, la fonction renvoie TOUJOURS une liste à un seul élément.

- [ ] **Step 1: Write the failing tests**

Ajoute dans `tests/test_upload_prep.py` (regarde d'abord comment
`test_files_with_same_team_form_one_group` ou un test `preview_upload`
existant mocke `extract.extract_video_metadata` via `monkeypatch`/`patch`
— réutilise exactement ce mécanisme) :

```python
from nfogen.upload_prep import SeasonPackRequest, SeasonPackSeasonFiles


def test_preview_upload_season_pack_produces_one_group_with_prefixed_staged_names():
    season_pack = SeasonPackRequest(
        title="Lucifer", team="Frosties", is_full_series=True,
        seasons=[
            SeasonPackSeasonFiles(season_number=5, local_paths=["/media/S05/ep1.mkv", "/media/S05/ep2.mkv"]),
            SeasonPackSeasonFiles(season_number=6, local_paths=["/media/S06/ep1.mkv"]),
        ],
    )
    with patch(
        "nfogen.upload_prep.extract.extract_video_metadata",
        return_value={"audio_languages": [], "subtitle_languages": []},
    ):
        proposals = preview_upload([], profile="c411", season_pack=season_pack)

    assert len(proposals) == 1
    group = proposals[0]
    assert group.release_name is not None
    assert "INTEGRALE" in group.release_name
    assert len(group.files) == 3
    assert group.files[0].staged_name == "S05/ep1.mkv"
    assert group.files[1].staged_name == "S05/ep2.mkv"
    assert group.files[2].staged_name == "S06/ep1.mkv"


def test_preview_upload_season_pack_warns_when_season_pack_not_configured():
    season_pack = SeasonPackRequest(
        title="Show", team="TEAM", is_full_series=False,
        seasons=[
            SeasonPackSeasonFiles(season_number=1, local_paths=["/media/S01/ep1.mkv"]),
            SeasonPackSeasonFiles(season_number=2, local_paths=["/media/S02/ep1.mkv"]),
        ],
    )
    with patch(
        "nfogen.upload_prep.extract.extract_video_metadata",
        return_value={"audio_languages": [], "subtitle_languages": []},
    ):
        # profil "bare" (aucun profil utilisateur cree pour ce test) --
        # aucune section video.name_proposal.season_pack declaree.
        proposals = preview_upload([], profile="does-not-exist", season_pack=season_pack)

    assert len(proposals) == 1
    assert proposals[0].release_name is None
    assert proposals[0].blocked is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -k season_pack -v`
Expected: FAIL (`ImportError: cannot import name 'SeasonPackRequest'`)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/upload_prep.py`, ajoute les imports/dataclasses (après
`ProposedFile`/`GroupProposal` existants) :

```python
from .name_proposal import extract_team_tag, propose_season_pack_name, strip_ext
```

(remplace la ligne d'import existante `from .name_proposal import extract_team_tag, strip_ext` par celle-ci — ajoute juste `propose_season_pack_name`.)

```python
@dataclass
class SeasonPackSeasonFiles:
    """Fichiers d'UNE saison du pack -- garde l'association fichier/saison
    explicite (jamais devinee depuis le chemin), voir SeasonPackRequest."""

    season_number: int
    local_paths: list[str]


@dataclass
class SeasonPackRequest:
    """Pack multi-saisons DEJA VALIDE par l'appelant (voir
    gapscan_library.detect_season_packs : memes equipe garantie, saisons
    consecutives) -- transmis tel quel par l'API (voir api.py)."""

    title: str
    team: str
    is_full_series: bool
    seasons: list[SeasonPackSeasonFiles]  # ordonne par season_number croissant
```

Modifie la signature de `preview_upload` :

```python
def preview_upload(
    local_paths: list[str], profile: str = "c411", title_override: Optional[str] = None,
    season_pack: Optional[SeasonPackRequest] = None,
) -> list[GroupProposal]:
```

Juste après la docstring existante de `preview_upload` (ne touche pas au
corps existant), insère au tout début du corps de la fonction :

```python
    if season_pack is not None:
        return [_preview_season_pack(season_pack, profile)]

```

(le `if not local_paths: return []` existant reste APRÈS ce nouveau
bloc, inchangé — un appel avec `season_pack` fourni n'a jamais besoin de
`local_paths`.)

Ajoute la fonction privée (avant `preview_upload`, ou juste après —
peu importe, cohérent avec le style du fichier qui met les helpers
privés avant leur premier usage) :

```python
def _preview_season_pack(season_pack: SeasonPackRequest, profile: str) -> GroupProposal:
    """Un pack multi-saisons DEJA VALIDE (voir SeasonPackRequest) donne
    TOUJOURS un seul GroupProposal -- jamais de group_by_team() ici (les
    fichiers de plusieurs saisons portent des tokens SxxExx differents,
    group_by_team n'a pas de sens pour ce cas). Le premier fichier de la
    premiere saison sert de representant pour extraire langue/resolution/
    codec/source (memes alias que la proposition standard, voir
    propose_season_pack_name)."""
    warnings: list[str] = []
    files: list[ProposedFile] = []
    representative_filename: Optional[str] = None
    for season in season_pack.seasons:
        for source_path in season.local_paths:
            filename = Path(source_path).name
            if representative_filename is None:
                representative_filename = filename
            try:
                extract.extract_video_metadata(Path(source_path))
            except Exception:
                warnings.append(_extraction_warning(filename))
            files.append(
                ProposedFile(source_path=source_path, staged_name=f"S{season.season_number:02d}/{filename}")
            )

    if not files or representative_filename is None:
        return GroupProposal(release_name=None, files=[], warnings=["Aucun fichier fourni pour ce pack."], blocked=True)

    config = read_profile(profile)["rules"].get("video", {}).get("name_proposal", {})
    season_numbers = [s.season_number for s in season_pack.seasons]
    proposal = propose_season_pack_name(
        title=season_pack.title, season_numbers=season_numbers, is_full_series=season_pack.is_full_series,
        team=season_pack.team, representative_filename=representative_filename, config=config,
    )
    warnings = warnings + list(proposal.warnings)

    if proposal.name is None:
        return GroupProposal(release_name=None, files=[], warnings=warnings, blocked=True)

    return GroupProposal(release_name=proposal.name, files=files, warnings=warnings, blocked=False)
```

**Note** : `extract_video_metadata` ici sert uniquement à détecter un
fichier illisible (même best-effort que `preview_upload` existant,
voir `_extraction_warning`) — son résultat n'est pas utilisé pour le
nommage (`propose_season_pack_name` travaille sur le NOM de fichier
représentatif, pas sur MediaInfo, cohérent avec le reste du moteur de
nommage). Pas de validateur (`registry.get_validator`) appelé pour un
pack — hors périmètre de ce sous-projet (voir spec, "Hors périmètre").

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -v`
Expected: PASS (tous les tests du fichier, y compris les existants —
`preview_upload` sans `season_pack` doit rester 100% inchangé).

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "feat: preview_upload(season_pack=...) -- pack multi-saisons en un seul GroupProposal"
```

---

### Task 6 : `POST /gapscan/prepare-upload/preview` accepte `season_pack`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `upload_prep.preview_upload(..., season_pack=...)`, `SeasonPackRequest`/`SeasonPackSeasonFiles` (Task 5).
- Produces: `PrepareUploadPreviewRequest.season_pack: Optional[SeasonPackRequestModel]` (nouveau modèle pydantic), transmis à `preview_upload`.

- [ ] **Step 1: Write the failing test**

Ajoute dans `tests/test_api.py`, à côté des tests
`/gapscan/prepare-upload/preview` existants (cherche
`prepare-upload/preview` dans le fichier pour repérer le style/la
fixture déjà utilisée) :

```python
def test_prepare_upload_preview_season_pack(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(
        mod.upload_prep, "extract",
        type("F", (), {"extract_video_metadata": staticmethod(lambda path: {})})(),
    )
    client = TestClient(mod.app)

    resp = client.post(
        "/gapscan/prepare-upload/preview",
        json={
            "profile": "c411",
            "season_pack": {
                "title": "Lucifer", "team": "Frosties", "is_full_series": True,
                "seasons": [
                    {"season_number": 5, "local_paths": ["/media/S05/ep1.mkv"]},
                    {"season_number": 6, "local_paths": ["/media/S06/ep1.mkv"]},
                ],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "INTEGRALE" in body[0]["release_name"]
    assert body[0]["files"][0]["staged_name"] == "S05/ep1.mkv"
```

Si `monkeypatch.setattr(mod.upload_prep, "extract", ...)` ne fonctionne
pas proprement avec ce style (`extract` est un MODULE importé, pas un
objet à patcher ainsi) — utilise plutôt
`monkeypatch.setattr(mod.upload_prep.extract, "extract_video_metadata", lambda path: {})`,
cohérent avec le mécanisme déjà utilisé dans
`tests/test_upload_prep.py` (`patch("nfogen.upload_prep.extract.extract_video_metadata", ...)`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k prepare_upload_preview_season_pack -v`
Expected: FAIL (422 — champ `season_pack` non reconnu par le modèle pydantic actuel, ou 400/500 selon la validation)

- [ ] **Step 3: Write minimal implementation**

Dans `nfogen/api.py`, ajoute les imports nécessaires (à côté de l'import
`upload_prep` existant) et deux modèles pydantic juste avant
`PrepareUploadPreviewRequest` :

```python
class SeasonPackSeasonFilesRequest(BaseModel):
    season_number: int
    local_paths: list[str]


class SeasonPackRequestModel(BaseModel):
    title: str
    team: str
    is_full_series: bool
    seasons: list[SeasonPackSeasonFilesRequest]


class PrepareUploadPreviewRequest(BaseModel):
    local_paths: list[str] = []
    profile: str = "c411"
    title_override: Optional[str] = None
    season_pack: Optional[SeasonPackRequestModel] = None
```

Modifie `gapscan_prepare_upload_preview` :

```python
@app.post("/gapscan/prepare-upload/preview", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_preview(req: PrepareUploadPreviewRequest) -> list[dict[str, Any]]:
    _require_gapscan_available()
    season_pack = None
    if req.season_pack is not None:
        season_pack = upload_prep.SeasonPackRequest(
            title=req.season_pack.title, team=req.season_pack.team,
            is_full_series=req.season_pack.is_full_series,
            seasons=[
                upload_prep.SeasonPackSeasonFiles(season_number=s.season_number, local_paths=s.local_paths)
                for s in req.season_pack.seasons
            ],
        )
    proposals = _run_upload_prep(
        upload_prep.preview_upload, req.local_paths, profile=req.profile,
        title_override=req.title_override, season_pack=season_pack,
    )
    return [asdict(p) for p in proposals]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "prepare_upload_preview" -v`
Expected: PASS (le nouveau test ET les tests preview existants, sans
régression — `season_pack` optionnel, défaut `None`).

- [ ] **Step 5: Run full backend suite + ruff (repo entier, pas juste nfogen/+tests/)**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q && .venv/Scripts/python.exe -m ruff check .`
Expected: tout passe.

- [ ] **Step 6: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: POST /gapscan/prepare-upload/preview accepte season_pack"
```

---

### Task 7 : Frontend — types + bloc "Packs disponibles"

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `season_packs` dans la réponse de `GET /gapscan/library` (Task 4).
- Produces: type `SeasonPackSuggestion`, `LibraryResultsPage.season_packs: SeasonPackSuggestion[]`, état `activeSeasonPack` sur `LibraryPage` (consommé par Task 8).

- [ ] **Step 1: Ajouter le type**

Dans `frontend/src/api/types.ts`, à côté de `LibraryResultsPage` :

```typescript
/** Groupe de saisons consecutives d'une meme serie, meme equipe, propose
 * en pack (retour utilisateur, 2026-09-08). Voir
 * gapscan_library.detect_season_packs. */
export interface SeasonPackSuggestion {
  sonarr_series_id: number;
  title: string;
  year: number | null;
  team: string;
  season_numbers: number[];
  is_full_series: boolean;
  item_keys: string[];
}

export interface LibraryResultsPage {
  items: LibraryItem[];
  total: number;
  season_packs: SeasonPackSuggestion[];
}
```

(remplace l'interface `LibraryResultsPage` existante — elle n'avait que
`items`/`total`.)

- [ ] **Step 2: Verify with tsc (des fixtures vont echouer, normal)**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: erreurs dans les fichiers de test qui construisent un
`LibraryResultsPage`/mock `libraryResults` sans `season_packs` — corrigé
à l'étape suivante.

- [ ] **Step 3: Ajouter l'état et l'affichage dans LibraryPage.tsx**

Dans `frontend/src/pages/LibraryPage.tsx`, ajoute un état pour stocker
les suggestions reçues (`useState` à côté de `items`/`total`) :

```typescript
  const [seasonPacks, setSeasonPacks] = useState<SeasonPackSuggestion[]>([]);
```

Dans `load()`, après `setItems(res.items); setTotal(res.total);` :

```typescript
      setSeasonPacks(res.season_packs);
```

Importe le type en haut du fichier :

```typescript
import type { GapscanConfig, GapscanConfigWrite, GapscanStatus, GapStatus, LibraryItem, SeasonPackSuggestion } from "../api/types";
```

JSX : insère un nouveau bloc juste avant la table (`{items !== null && items.length > 0 && (<table ...`), affiché seulement si `seasonPacks.length > 0` :

```tsx
      {seasonPacks.length > 0 && (
        <div className="space-y-2 rounded-md border border-line bg-surface p-4">
          <p className="text-sm font-medium text-ink-dim">Packs disponibles</p>
          {seasonPacks.map((pack) => (
            <div key={`${pack.sonarr_series_id}-${pack.season_numbers.join("-")}`} className="flex items-center justify-between text-sm">
              <span>
                {pack.title} — {pack.is_full_series ? "INTEGRALE" : `S${String(pack.season_numbers[0]).padStart(2, "0")}S${String(pack.season_numbers[pack.season_numbers.length - 1]).padStart(2, "0")}`}{" "}
                ({pack.team})
              </span>
              {/* onClick cable a la Task 8 -- pour l'instant, bouton sans action */}
              <button
                type="button"
                className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2"
              >
                Préparer le pack
              </button>
            </div>
          ))}
        </div>
      )}
```

- [ ] **Step 4: Corriger les fixtures de test cassees par tsc**

Dans `frontend/src/pages/LibraryPage.test.tsx`, chaque
`vi.mocked(libraryResults).mockResolvedValue({...})` gagne `season_packs: []`
(sauf le nouveau test de l'étape 5, qui en fournit un réel).

- [ ] **Step 5: Write the failing test then implement (ordre TDD respecte : le test precede deja l'implementation JSX de l'etape 3 dans l'esprit, mais ecrit ici pour verifier le rendu)**

```typescript
it("affiche le bloc 'Packs disponibles' quand la bibliotheque en detecte", async () => {
  vi.mocked(libraryResults).mockResolvedValue({
    items: [MATRIX_ITEM], total: 1,
    season_packs: [
      { sonarr_series_id: 7, title: "Lucifer", year: 2016, team: "Frosties", season_numbers: [5, 6], is_full_series: true, item_keys: ["k1", "k2"] },
    ],
  });
  renderPage();
  expect(await screen.findByText("Packs disponibles")).toBeInTheDocument();
  expect(screen.getByText(/Lucifer — INTEGRALE \(Frosties\)/)).toBeInTheDocument();
});

it("n'affiche pas le bloc 'Packs disponibles' si aucune suggestion", async () => {
  vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });
  renderPage();
  await screen.findByText(/Matrix \(1999\)/);
  expect(screen.queryByText("Packs disponibles")).not.toBeInTheDocument();
});
```

- [ ] **Step 6: Run frontend tests, typecheck, lint**

```bash
cd frontend
npx vitest run src/pages/LibraryPage.test.tsx
npx tsc -b --noEmit
npx oxlint
```
Expected: tout passe.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat(frontend): bloc 'Packs disponibles' dans la Bibliotheque"
```

---

### Task 8 : Frontend — "Préparer le pack" ouvre UploadPrepPanel avec les saisons fusionnées

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/UploadPrepPanel.tsx`
- Modify: `frontend/src/components/UploadPrepPanel.test.tsx`
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `SeasonPackSuggestion` (Task 7), backend `season_pack` sur `POST /gapscan/prepare-upload/preview` (Task 6).
- Produces: `prepareUploadPreview()` gagne un paramètre `seasonPack` optionnel ; `UploadPrepPanel` gagne une prop `seasonPack` optionnelle.

- [ ] **Step 1: Etendre prepareUploadPreview (client.ts)**

Dans `frontend/src/api/client.ts`, modifie la signature et le corps de
`prepareUploadPreview` :

```typescript
export function prepareUploadPreview(
  localPaths: string[],
  profile = "c411",
  titleOverride?: string,
  seasonPack?: {
    title: string;
    team: string;
    isFullSeries: boolean;
    seasons: { seasonNumber: number; localPaths: string[] }[];
  },
): Promise<UploadGroupProposal[]> {
  return request<UploadGroupProposal[]>("/gapscan/prepare-upload/preview", {
    method: "POST",
    body: JSON.stringify({
      local_paths: localPaths,
      profile,
      title_override: titleOverride,
      ...(seasonPack
        ? {
            season_pack: {
              title: seasonPack.title,
              team: seasonPack.team,
              is_full_series: seasonPack.isFullSeries,
              seasons: seasonPack.seasons.map((s) => ({
                season_number: s.seasonNumber, local_paths: s.localPaths,
              })),
            },
          }
        : {}),
    }),
  });
}
```

- [ ] **Step 2: UploadPrepPanel accepte une prop seasonPack optionnelle**

Dans `frontend/src/components/UploadPrepPanel.tsx`, ajoute la prop dans
la signature du composant (à côté de `seasonNumber`) :

```typescript
  seasonPack,
}: {
  localPaths: string[];
  title: string;
  mediaType: "movie" | "series";
  radarrMovieId: number | null;
  sonarrSeriesId: number | null;
  tmdbId: number | null;
  tvdbId: number | null;
  genre: "anime" | "documentaire" | null;
  seasonNumber: number | null;
  seasonPack?: {
    title: string;
    team: string;
    isFullSeries: boolean;
    seasons: { seasonNumber: number; localPaths: string[] }[];
  };
  onClose: () => void;
}) {
```

Modifie `loadPreview` pour transmettre `seasonPack` :

```typescript
  async function loadPreview(override?: string, profileOverride: string = profile) {
    setRecalculating(true);
    setLoadError(null);
    try {
      const g = await prepareUploadPreview(localPaths, profileOverride, override || undefined, seasonPack);
      setGroups(g);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Aperçu indisponible.");
    } finally {
      setRecalculating(false);
    }
  }
```

Le reste du composant (Confirmer/Envoyer/etc.) fonctionne déjà pour un
groupe unique sans changement — un pack produit exactement 1
`GroupProposal`, comme n'importe quel groupe standard.

- [ ] **Step 3: LibraryPage cable le bouton "Préparer le pack"**

Dans `frontend/src/pages/LibraryPage.tsx`, le state `activeUpload`
existant (déjà utilisé par les lignes individuelles) gagne un champ
optionnel `seasonPack` — cherche la définition actuelle de
`activeUpload` (`useState<{...} | null>`) et ajoute :

```typescript
    seasonPack?: {
      title: string;
      team: string;
      isFullSeries: boolean;
      seasons: { seasonNumber: number; localPaths: string[] }[];
    };
```

Pour construire `seasons`, il faut retrouver les `local_paths` de
CHAQUE saison du groupe à partir de `pack.item_keys` — ajoute une
fonction utilitaire juste avant le rendu du bloc "Packs disponibles" :

```typescript
  function seasonsForPack(pack: SeasonPackSuggestion): { seasonNumber: number; localPaths: string[] }[] {
    if (!items) return [];
    return pack.item_keys
      .map((key) => items.find((i) => i.key === key))
      .filter((i): i is LibraryItem => i !== undefined && i.season_number !== null)
      .map((i) => ({ seasonNumber: i.season_number as number, localPaths: i.local_paths }));
  }
```

**Attention** : `items` est la page COURANTE (filtrée/paginée) — une
saison du pack peut ne pas y figurer si elle est hors de la page/filtre
actif. Accepte cette limite pour cette tâche (documente-le dans un
commentaire au-dessus de la fonction) plutôt que de complexifier avec un
second appel API dédié — hors périmètre de ce plan (voir spec, la
détection elle-même tourne bien sur la bibliothèque complète côté
backend, seule la RÉCUPÉRATION des chemins ici est limitée à la page
affichée). Si `seasonsForPack` renvoie moins d'entrées que
`pack.season_numbers`, le bouton reste cliquable mais le pack résultant
sera incomplet -- acceptable pour une première version, à améliorer
plus tard si l'utilisateur le signale.

Branche le bouton "Préparer le pack" (Task 7, actuellement sans action) :

```tsx
              <button
                type="button"
                onClick={() =>
                  setActiveUpload({
                    title: pack.title,
                    localPaths: seasonsForPack(pack).flatMap((s) => s.localPaths),
                    mediaType: "series",
                    radarrMovieId: null,
                    sonarrSeriesId: pack.sonarr_series_id,
                    tmdbId: null,
                    tvdbId: null,
                    genre: null,
                    seasonNumber: null,
                    seasonPack: {
                      title: pack.title, team: pack.team, isFullSeries: pack.is_full_series,
                      seasons: seasonsForPack(pack),
                    },
                  })
                }
                className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2"
              >
                Préparer le pack
              </button>
```

Et transmets `seasonPack` à `<UploadPrepPanel>` dans le JSX existant qui
le rend (`{activeUpload && (<UploadPrepPanel ... />)}`) :

```tsx
          seasonPack={activeUpload.seasonPack}
```

- [ ] **Step 4: Write the failing tests**

Dans `frontend/src/components/UploadPrepPanel.test.tsx` :

```typescript
it("transmet seasonPack a prepareUploadPreview quand fourni", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  renderPanel({
    localPaths: ["/media/S05/ep1.mkv", "/media/S06/ep1.mkv"], title: "Lucifer", onClose: vi.fn(),
    mediaType: "series", radarrMovieId: null, sonarrSeriesId: 7, tmdbId: null, tvdbId: null,
    genre: null, seasonNumber: null,
    seasonPack: {
      title: "Lucifer", team: "Frosties", isFullSeries: true,
      seasons: [
        { seasonNumber: 5, localPaths: ["/media/S05/ep1.mkv"] },
        { seasonNumber: 6, localPaths: ["/media/S06/ep1.mkv"] },
      ],
    },
  });

  await waitFor(() => expect(prepareUploadPreview).toHaveBeenCalled());
  expect(prepareUploadPreview).toHaveBeenCalledWith(
    ["/media/S05/ep1.mkv", "/media/S06/ep1.mkv"], "c411", undefined,
    {
      title: "Lucifer", team: "Frosties", isFullSeries: true,
      seasons: [
        { seasonNumber: 5, localPaths: ["/media/S05/ep1.mkv"] },
        { seasonNumber: 6, localPaths: ["/media/S06/ep1.mkv"] },
      ],
    },
  );
});
```

Vérifie que `renderPanel` (helper déjà défini dans ce fichier de test)
transmet bien toutes les props passées en argument au composant — sinon
étends `renderPanel` pour accepter et transmettre `seasonPack`.

Dans `frontend/src/pages/LibraryPage.test.tsx` :

```typescript
it("le bouton 'Preparer le pack' ouvre UploadPrepPanel avec les saisons du groupe fusionnees", async () => {
  const user = userEvent.setup();
  vi.mocked(libraryResults).mockResolvedValue({
    items: [
      { ...SHOW_ITEM, key: "k1", season_number: 5, team: "Frosties", local_paths: ["/media/S05/ep1.mkv"], path_resolved: true },
      { ...SHOW_ITEM, key: "k2", season_number: 6, team: "Frosties", local_paths: ["/media/S06/ep1.mkv"], path_resolved: true },
    ],
    total: 2,
    season_packs: [
      { sonarr_series_id: 7, title: "Show", year: 2020, team: "Frosties", season_numbers: [5, 6], is_full_series: true, item_keys: ["k1", "k2"] },
    ],
  });
  renderPage();

  await user.click(await screen.findByRole("button", { name: "Préparer le pack" }));

  expect(await screen.findByText(/Panneau upload pour Show/)).toBeInTheDocument();
});
```

(réutilise le mock `UploadPrepPanel` déjà défini en tête de
`LibraryPage.test.tsx`, style `<p>Panneau upload pour {props.title}</p>`
— vérifie son nom exact avant d'écrire l'assertion.)

- [ ] **Step 5: Run tests to verify they fail, then run again after implementing**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx src/pages/LibraryPage.test.tsx`
Expected d'abord FAIL, puis PASS une fois les Steps 1-3 en place (si pas
déjà fait avant d'écrire ces tests — dans ce plan, l'implémentation
précède les tests de cette étape pour rester lisible, mais applique
quand même la discipline TDD complète : écris le test, vérifie qu'il
échoue AVANT toute implémentation, si ce n'est pas déjà le cas à ce
stade de ta lecture du plan).

- [ ] **Step 6: Full frontend suite, typecheck, lint**

```bash
npx vitest run
npx tsc -b --noEmit
npx oxlint
```
Expected: tout passe.

- [ ] **Step 7: Full backend suite + ruff (aucun changement backend dans cette tache, mais discipline de fin de plan)**

Run (depuis la racine du repo) : `.venv/Scripts/python.exe -m pytest tests/ -q && .venv/Scripts/python.exe -m ruff check .`
Expected: tout passe.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/UploadPrepPanel.tsx frontend/src/components/UploadPrepPanel.test.tsx frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat(frontend): Preparer le pack -- ouvre UploadPrepPanel avec les saisons fusionnees"
```

---

### Task 9 : Documentation

**Files:**
- Modify: `AUTOMATION.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Mettre a jour**

`CHANGELOG.md` : nouvelle entrée décrivant la détection de packs
multi-saisons/INTEGRALE (tag d'équipe consécutif, nommage déclaratif
`rules.json -> video -> name_proposal.season_pack`, bloc "Packs
disponibles", limite connue : la récupération des chemins d'un pack se
limite à la page actuellement affichée dans la Bibliothèque).

`AUTOMATION.md` : ajoute une sous-section au sous-projet 8
(Bibliothèque) ou 4 (préparation d'upload, selon où le sous-projet 8 est
déjà documenté — cherche `grep -n "sous-projet 8"` pour trouver
l'endroit exact) décrivant la fonctionnalité et son fondement (doc
"Nommage de l'upload" du wiki C411, confirmée par l'utilisateur le
2026-09-08).

- [ ] **Step 2: Commit + push final**

```bash
git add AUTOMATION.md CHANGELOG.md
git commit -m "docs: pack multi-saisons / INTEGRALE"
git push origin main
```

Puis suivre la discipline habituelle du projet : interroger
`https://api.github.com/repos/ICCUser/nfogen/actions/runs?branch=main&per_page=5`
jusqu'à ce que le run correspondant au dernier `head_sha` poussé affiche
`status: completed`, et vérifier `conclusion: success` avant de
considérer le travail terminé.

---

## Self-Review

- **Couverture spec** : Section A (détection + nommage) -> Tasks 1-3 ;
  Section B (affichage) -> Tasks 4, 7 ; Section C (mise en scène/upload
  combiné) -> Tasks 5-6, 8. Tout couvert.
- **`commit_upload()` inchangé** : confirmé — aucune tâche ne le
  modifie, conforme à la Global Constraint (`file_staging.stage_files()`
  accepte déjà des `staged_name` avec sous-dossier).
- **Cohérence des types** : `SeasonPackRequest`/`SeasonPackSeasonFiles`
  (Task 5, dataclasses Python) <-> `SeasonPackRequestModel`/
  `SeasonPackSeasonFilesRequest` (Task 6, pydantic) <-> `seasonPack`/
  `seasons` (Task 8, TypeScript, camelCase côté JS converti en
  snake_case dans le corps JSON) — noms de champs vérifiés cohérents à
  travers les 3 couches.
- **`season_number=None` pour l'historique "déjà traité"** : un pack
  n'est PAS passé à `commit_upload()`/`send_to_tracker()` avec un
  `season_number` précis dans ce plan (le frontend n'envoie pas
  `seasonNumber` dans `identifiers` pour un pack, cohérent avec
  `prepareUploadCommit`'s `seasonNumber` déjà optionnel) — accepté
  comme simplification explicite (voir Task 8, limite documentée) :
  deux packs différents de la même série partageraient la même clé
  d'historique `("series", sonarr_series_id, None)`. Rare en pratique
  (action manuelle, occasionnelle), pas de nouvelle tâche dédiée à ce
  stade.
- **Pas de placeholder** : chaque step contient du code complet ou une
  instruction explicite de vérifier un mécanisme EXISTANT avant de
  réutiliser son nom exact (fixtures de test, noms d'import) — jamais
  une convention devinée sans vérification.
