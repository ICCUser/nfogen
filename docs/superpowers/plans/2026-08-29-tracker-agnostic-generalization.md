# Généralisation tracker-agnostique (sous-projet 4b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the four C411-specific values currently hard-coded in Python (Torznab category codes, tracker credential field names, torrent piece-size table, MediaInfo→language-code map) by moving them into a new `tracker` section of the profile's `rules.json`, and namespace stored tracker credentials by profile — so a second tracker profile could be added later without touching Python.

**Architecture:** A new pure-read module `nfogen/tracker_profile.py` becomes the single place that reads a profile's `tracker` section (with safe, non-guessing defaults). `gapscan.py`, `torrent_builder.py`, and `upload_prep.py` read from it instead of module-level Python constants. `gapscan_config_store.py` gains a `trackers.<profile>.*` namespace for credentials (separate concern from `rules.json`: secrets vs. declared policy), with a same-file fallback to the old flat `c411_*` keys so nothing already configured on a live server breaks. `nfogen/c411_client.py` is renamed to `nfogen/torznab_client.py` (pure rename, the protocol was already generic). The API gains an explicit `profile` parameter threaded through GapScan's config/run/results endpoints. On the frontend, a new `ProfileContext` (React context, provided once in `App.tsx`) becomes the single source of truth for "which profile is active" — a selector lives in the app's `<header>` (not per-page), shared by "Générer" and "Scan GapScan"; the "Préparer l'upload" panel defaults to that same active profile but can override it just for one upload (per-media exception — user request, 2026-08-29).

**Tech Stack:** Python (FastAPI, `jsonschema`, `httpx`), TypeScript/React/Vite, pytest, Vitest.

**Spec:** [AUTOMATION.md, section "Sous-projet 4b"](../../../AUTOMATION.md) (already approved by the user, 2026-08-29).

## Global Constraints

- TDD strictly: write the failing test, confirm it fails for the right reason, then implement.
- One commit per task (or per logical sub-step inside a task where noted). Run the **full** backend suite (`pytest`) and `ruff check` before moving to the next task, not just the task's own test file — several tasks touch shared modules (`gapscan_config_store.py`, `c411_client.py`) with many existing callers.
- Never guess a tracker-specific value when a profile hasn't declared it: every new `tracker_profile.py` accessor returns an empty/neutral default (`{}`, `[]`, `0.0`) rather than falling back to a C411-shaped guess — consistent with the rest of this codebase's "jamais deviner" discipline.
- Backward compatibility is at the **storage** layer only (the on-disk `gapscan_config.json` a real server already has), never at the API layer — frontend and backend deploy together in this project (established precedent, see CHANGELOG.md), so API request/response shapes can change freely as long as both sides of a task update together.
- Two scope cuts made while writing this plan (flag both to the user when reporting completion):
  1. **No "Tracker" tab in the profile editor UI** (was mentioned in the AUTOMATION.md design). The only profile that exists today (`c411`) ships the `tracker` section pre-populated; editing it means hand-editing `rules.json` (or export‑zip → edit → import‑zip, both already supported). A structured editing UI is deferred until a second tracker profile actually needs to be authored through the UI.
  2. **The "MULTI language whitelist" field is not a whitelist of combos.** Reading the real code (`upload_prep.py:_AUDIO_LANGUAGE_CODE`) showed there's no combo-whitelist check — it's a MediaInfo-language-string → 2-letter-code lookup table (`fr`/`fre`/`fra`/`french` → `FR`, etc.), and *that* table is what's C411-scoped (limited to the languages C411's own MULTI convention covers). This plan generalizes it as `tracker.audio_language_codes` (a flat string→string map), not `multi_language_whitelist` (a list of combo strings) as originally sketched in AUTOMATION.md.

---

### Task 1: Allow a `tracker` section in `rules.json`

**Files:**
- Modify: `nfogen/rules.schema.json`
- Test: `tests/test_profile_store.py`

**Interfaces:**
- Produces: a valid `rules.json` document may now have a top-level `"tracker"` key, schema-validated by `nfogen/rules.py:validate_rules_document()` (used by `profile_store.write_profile()`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_store.py`:

```python
TRACKER_RULES = {
    "tracker": {
        "display_name": "Test Tracker",
        "torznab_categories": {"anime": ["2060"], "documentaire": ["2070"]},
        "audio_language_codes": {"fre": "FR", "eng": "EN"},
        "min_request_interval_seconds": 4.5,
        "torrent_piece_sizes": [
            {"max_bytes": 1073741824, "piece_size": 1048576},
            {"piece_size": 16777216},
        ],
    }
}


def test_tracker_is_a_valid_top_level_key(_profiles_dir):
    ps.write_profile("trackertest", rules=TRACKER_RULES, templates={})
    read = ps.read_profile("trackertest")
    assert read["rules"]["tracker"]["display_name"] == "Test Tracker"


def test_tracker_and_a_category_can_coexist(_profiles_dir):
    combined = {**TRACKER_RULES, **RULES}
    ps.write_profile("trackertest2", rules=combined, templates=TEMPLATES)
    read = ps.read_profile("trackertest2")
    assert "tracker" in read["rules"]
    assert "game" in read["rules"]


def test_unknown_top_level_key_still_rejected(_profiles_dir):
    # Regression : le schema ne doit pas devenir "tout accepte" en ouvrant
    # "tracker" -- une cle inconnue reste une erreur (voir rules.schema.json).
    with pytest.raises(ps.ProfileStoreError):
        ps.write_profile("bogus", rules={"totally_unknown_key": {}}, templates={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_profile_store.py -k tracker -v`
Expected: FAIL — `jsonschema.exceptions.ValidationError` / `ProfileStoreError` about `'tracker' was unexpected` (the current schema's `additionalProperties: false` rejects it), surfacing as a raised `ProfileStoreError` from `write_profile`.

- [ ] **Step 3: Extend the schema**

In `nfogen/rules.schema.json`, change the top-level `propertyNames`/`patternProperties` and add a `tracker` definition:

```json
  "propertyNames": {
    "enum": ["video", "audio", "game", "ebook", "print3d", "tracker"]
  },
  "patternProperties": {
    "^(video|audio|game|ebook|print3d)$": { "$ref": "#/$defs/category" },
    "^tracker$": { "$ref": "#/$defs/tracker" }
  },
  "additionalProperties": false,
```

Add a new `$defs.tracker` entry (alongside the existing `$defs.category`, `$defs.name_proposal`, etc.):

```json
    "tracker": {
      "type": "object",
      "description": "Reglages propres a CE tracker, pas a une categorie de media (voir AUTOMATION.md, sous-projet 4b) : categories Torznab pour le filtre genre, bareme de taille de piece torrent, codes de langue MediaInfo reconnus, delai minimal entre requetes, nom d'affichage.",
      "properties": {
        "display_name": { "type": "string" },
        "torznab_categories": {
          "type": "object",
          "additionalProperties": { "type": "array", "items": { "type": "string" } }
        },
        "audio_language_codes": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        },
        "min_request_interval_seconds": { "type": "number" },
        "torrent_piece_sizes": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "max_bytes": { "type": "integer" },
              "piece_size": { "type": "integer" }
            },
            "required": ["piece_size"],
            "additionalProperties": false
          }
        }
      },
      "additionalProperties": false
    }
```

Update the schema's top-level `description` (line 4) to mention `tracker` alongside the media categories, since it currently says "Chaque cle de premier niveau DOIT etre un nom de categorie connu du coeur (video/audio/game/ebook/print3d...)" — no longer accurate:

```json
  "description": "Schema generique d'un fichier de regles de profil nfogen. Chaque cle de premier niveau DOIT etre soit un nom de categorie de media connu du coeur (video/audio/game/ebook/print3d), soit 'tracker' (reglages propres au tracker, pas a une categorie) -- une cle inconnue (typo, futur nom non encore supporte...) est REJETEE ici plutot qu'ignoree silencieusement.",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_profile_store.py -v`
Expected: all PASS, including the 3 new tests and every pre-existing test in the file (the schema change is additive).

- [ ] **Step 5: Full suite + lint, then commit**

```bash
pytest
ruff check nfogen/ tests/
git add nfogen/rules.schema.json tests/test_profile_store.py
git commit -m "feat: autorise une section 'tracker' dans rules.json"
```

---

### Task 2: `nfogen/tracker_profile.py` — read a profile's tracker policy

**Files:**
- Create: `nfogen/tracker_profile.py`
- Test: `tests/test_tracker_profile.py`

**Interfaces:**
- Consumes: `profile_store.read_profile(name) -> dict[str, Any]` (existing, `{"name", "rules", "templates"}`).
- Produces (consumed by Tasks 6, 7, 8, 10):
  - `display_name(profile: str) -> str`
  - `torznab_categories(profile: str) -> dict[str, list[str]]`
  - `audio_language_codes(profile: str) -> dict[str, str]`
  - `min_request_interval_seconds(profile: str) -> float`
  - `torrent_piece_sizes(profile: str) -> list[dict[str, int]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tracker_profile.py`:

```python
"""Tests de nfogen.tracker_profile : lecture de la section "tracker" d'un
profil (rules.json), separee des identifiants (gapscan_config_store.py) --
voir AUTOMATION.md, sous-projet 4b."""
from __future__ import annotations

import pytest

from nfogen import profile_store as ps
from nfogen import tracker_profile
from nfogen.registry import unregister_profile

FULL_TRACKER_RULES = {
    "tracker": {
        "display_name": "Test Tracker",
        "torznab_categories": {"anime": ["2060", "5070"], "documentaire": ["2070"]},
        "audio_language_codes": {"fre": "FR", "eng": "EN", "jpn": "JA"},
        "min_request_interval_seconds": 4.5,
        "torrent_piece_sizes": [
            {"max_bytes": 1073741824, "piece_size": 1048576},
            {"piece_size": 16777216},
        ],
    }
}


@pytest.fixture(autouse=True)
def _profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    yield tmp_path
    try:
        names = ps.list_profiles()
    except ps.ProfileStoreError:
        names = []
    for name in names:
        unregister_profile(name)


def test_reads_every_declared_field():
    ps.write_profile("full", rules=FULL_TRACKER_RULES, templates={})
    assert tracker_profile.display_name("full") == "Test Tracker"
    assert tracker_profile.torznab_categories("full") == {
        "anime": ["2060", "5070"], "documentaire": ["2070"]
    }
    assert tracker_profile.audio_language_codes("full") == {"fre": "FR", "eng": "EN", "jpn": "JA"}
    assert tracker_profile.min_request_interval_seconds("full") == 4.5
    assert tracker_profile.torrent_piece_sizes("full") == [
        {"max_bytes": 1073741824, "piece_size": 1048576},
        {"piece_size": 16777216},
    ]


def test_display_name_falls_back_to_the_profile_name_when_undeclared():
    ps.write_profile("bare", rules={}, templates={})
    assert tracker_profile.display_name("bare") == "bare"


def test_torznab_categories_empty_dict_when_undeclared():
    ps.write_profile("bare2", rules={}, templates={})
    assert tracker_profile.torznab_categories("bare2") == {}


def test_audio_language_codes_empty_dict_when_undeclared():
    ps.write_profile("bare3", rules={}, templates={})
    assert tracker_profile.audio_language_codes("bare3") == {}


def test_min_request_interval_seconds_zero_when_undeclared():
    ps.write_profile("bare4", rules={}, templates={})
    assert tracker_profile.min_request_interval_seconds("bare4") == 0.0


def test_torrent_piece_sizes_empty_list_when_undeclared():
    ps.write_profile("bare5", rules={}, templates={})
    assert tracker_profile.torrent_piece_sizes("bare5") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tracker_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nfogen.tracker_profile'`.

- [ ] **Step 3: Write the implementation**

Create `nfogen/tracker_profile.py`:

```python
"""Lecture des reglages TRACKER d'un profil (rules.json -> "tracker"),
separee de `gapscan_config_store.py` (identifiants/secrets, stockes a part
-- voir AUTOMATION.md, sous-projet 4b) : categories Torznab pour le filtre
genre, bareme de taille de piece torrent, codes de langue MediaInfo
reconnus pour le prefixe MULTI, delai minimal entre requetes, nom
d'affichage. Rien ici n'est specifique a un tracker en particulier -- ce
module ne fait que lire ce qu'UN profil donne a declare, avec des valeurs
par defaut qui degradent proprement (jamais de supposition) pour un profil
qui n'a pas encore de section "tracker"."""
from __future__ import annotations

from typing import Any

from . import profile_store


def _tracker_section(profile: str) -> dict[str, Any]:
    return profile_store.read_profile(profile)["rules"].get("tracker", {})


def display_name(profile: str) -> str:
    """Nom lisible du tracker (affiche cote frontend) -- repli sur le nom
    du profil lui-meme si non declare."""
    return _tracker_section(profile).get("display_name") or profile


def torznab_categories(profile: str) -> dict[str, list[str]]:
    """{"anime": [...], "documentaire": [...]} : codes de categorie
    Torznab propres a CE tracker (voir gapscan.genre_of). Dictionnaire
    vide si non declare -- aucun genre n'est alors jamais classifie,
    jamais devine."""
    return _tracker_section(profile).get("torznab_categories", {})


def audio_language_codes(profile: str) -> dict[str, str]:
    """Codes de langue MediaInfo (piste audio reelle) -> code court
    reconnu par les alias de langue du profil (voir upload_prep.py).
    Dictionnaire vide si non declare -- aucun indice de langue depuis
    l'audio, jamais devine."""
    return _tracker_section(profile).get("audio_language_codes", {})


def min_request_interval_seconds(profile: str) -> float:
    """Delai minimal (secondes) entre deux requetes de recherche -- voir
    torznab_client.TorznabClient. 0.0 (aucune limite) si non declare :
    jamais de limite supposee pour un tracker dont on ne sait rien."""
    return float(_tracker_section(profile).get("min_request_interval_seconds", 0.0))


def torrent_piece_sizes(profile: str) -> list[dict[str, int]]:
    """Bareme de taille de piece torrent (voir
    torrent_builder.piece_size_for) -- liste vide si non declare
    (torrent_builder leve alors une erreur claire plutot que de deviner
    une taille)."""
    return _tracker_section(profile).get("torrent_piece_sizes", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tracker_profile.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
pytest
ruff check nfogen/ tests/
git add nfogen/tracker_profile.py tests/test_tracker_profile.py
git commit -m "feat: nfogen/tracker_profile.py - lecture de la section tracker d'un profil"
```

---

### Task 3: Populate the `c411` profile's `tracker` section

**Files:**
- Modify: `nfogen/profiles/c411/rules.json`
- Test: `tests/test_tracker_profile.py` (new tests against the real built-in profile, no fixture needed)

**Interfaces:**
- Consumes: Task 2's `tracker_profile.*` functions.
- Produces: the real, exact values every later task (6, 7, 8, 10) will read for `profile="c411"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tracker_profile.py` (outside the `_profiles_dir` fixture's temp-profile tests — these read the real built-in `c411` profile, no `NFOGEN_PROFILES_DIR` needed, matching how `profile_store._resolve_readable_dir` falls back to `BUILTIN_PROFILE_DIRS`):

```python
def test_c411_display_name():
    assert tracker_profile.display_name("c411") == "C411"


def test_c411_torznab_categories_match_gapscan_md():
    # Verifiees en direct le 2026-08-28 via GET https://c411.org/api?t=caps
    # (voir GAPSCAN.md) -- memes valeurs que l'ancien gapscan._ANIME_CATEGORIES
    # / _DOCUMENTARY_CATEGORIES, deplacees ici.
    assert tracker_profile.torznab_categories("c411") == {
        "anime": ["2060", "5070"],
        "documentaire": ["2070", "5080"],
    }


def test_c411_audio_language_codes_match_upload_prep_history():
    assert tracker_profile.audio_language_codes("c411") == {
        "fr": "FR", "fre": "FR", "fra": "FR", "french": "FR",
        "en": "EN", "eng": "EN", "english": "EN",
        "ja": "JA", "jpn": "JA", "japanese": "JA",
    }


def test_c411_min_request_interval_seconds():
    # Limite confirmee par les admins C411 (2026-08-27) : 15 requetes/min
    # -> 4.5s par defaut (marge de securite), voir GAPSCAN.md.
    assert tracker_profile.min_request_interval_seconds("c411") == 4.5


def test_c411_torrent_piece_sizes():
    assert tracker_profile.torrent_piece_sizes("c411") == [
        {"max_bytes": 1073741824, "piece_size": 1048576},
        {"max_bytes": 2147483648, "piece_size": 2097152},
        {"max_bytes": 3221225472, "piece_size": 4194304},
        {"max_bytes": 8589934592, "piece_size": 8388608},
        {"piece_size": 16777216},
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tracker_profile.py -v`
Expected: the 5 new tests FAIL (empty dict/list/0.0, since `nfogen/profiles/c411/rules.json` has no `tracker` key yet); the 6 tests from Task 2 still PASS.

- [ ] **Step 3: Add the `tracker` section**

Read `nfogen/profiles/c411/rules.json` first to find the exact top-level structure (it currently has a single `"video"` key). Add a new top-level `"tracker"` key as a sibling of `"video"`:

```json
{
  "tracker": {
    "display_name": "C411",
    "torznab_categories": {
      "anime": ["2060", "5070"],
      "documentaire": ["2070", "5080"]
    },
    "audio_language_codes": {
      "fr": "FR", "fre": "FR", "fra": "FR", "french": "FR",
      "en": "EN", "eng": "EN", "english": "EN",
      "ja": "JA", "jpn": "JA", "japanese": "JA"
    },
    "min_request_interval_seconds": 4.5,
    "torrent_piece_sizes": [
      {"max_bytes": 1073741824, "piece_size": 1048576},
      {"max_bytes": 2147483648, "piece_size": 2097152},
      {"max_bytes": 3221225472, "piece_size": 4194304},
      {"max_bytes": 8589934592, "piece_size": 8388608},
      {"piece_size": 16777216}
    ]
  },
  "video": {
    ... (contenu existant, inchange)
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tracker_profile.py -v`
Expected: all 11 PASS.

- [ ] **Step 5: Full suite + lint, then commit**

```bash
pytest
ruff check nfogen/ tests/
git add nfogen/profiles/c411/rules.json tests/test_tracker_profile.py
git commit -m "feat: peuple la section tracker du profil c411"
```

---

### Task 4: Per-profile tracker credentials in `gapscan_config_store.py`

**Files:**
- Modify: `nfogen/gapscan_config_store.py`
- Test: `tests/test_gapscan_config_store.py` (rewritten)

**Interfaces:**
- Produces (consumed by Task 10's `api.py` rewrite and Task 8's `upload_prep.py` update):
  - `write(*, profile: str = "c411", tracker_api_key=None, tracker_base_url=None, tracker_announce_url=None, sonarr_url=None, sonarr_api_key=None, radarr_url=None, radarr_api_key=None, sonarr_path_mappings=None, radarr_path_mappings=None, staging_dir=None) -> None`
  - `effective_tracker(profile: str = "c411") -> Optional[tuple[str, str]]` (replaces `effective_c411`)
  - `effective_tracker_announce_url(profile: str = "c411") -> Optional[str]` (replaces `effective_c411_announce_url`)
  - `status(profile: str = "c411") -> dict[str, Any]` (keys renamed: `tracker_configured`, `tracker_base_url`, `tracker_announce_url_configured`, plus `"profile": profile`)
  - `effective_sonarr()`, `effective_radarr()`, `effective_sonarr_path_mappings()`, `effective_radarr_path_mappings()`, `effective_staging_dir()` unchanged (Sonarr/Radarr/staging stay global, not per-profile — see AUTOMATION.md).

- [ ] **Step 1: Write the failing tests (full rewrite of the file)**

Replace `tests/test_gapscan_config_store.py` entirely:

```python
"""Tests de nfogen.gapscan_config_store.

Identifiants Sonarr/Radarr GLOBAUX (une seule bibliotheque media,
independante du tracker cible) + identifiants de TRACKER namespaces par
PROFIL (chaque profil garde les siens -- voir AUTOMATION.md, sous-projet
4b), le tout en JSON sur disque, modifiable a chaud via PUT /gapscan/config.
Repli sur les variables d'environnement historiques si le fichier n'est
pas configure/vide.
"""
from __future__ import annotations

import stat
import sys

import pytest

from nfogen import gapscan_config_store as store


@pytest.fixture(autouse=True)
def _config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(tmp_path / "gapscan_config.json"))
    for key in (
        "NFOGEN_C411_API_KEY", "NFOGEN_C411_BASE_URL",
        "NFOGEN_SONARR_URL", "NFOGEN_SONARR_API_KEY",
        "NFOGEN_RADARR_URL", "NFOGEN_RADARR_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_effective_tracker_none_when_nothing_configured():
    assert store.effective_tracker("c411") is None


def test_write_then_read_tracker():
    store.write(profile="c411", tracker_api_key="secret", tracker_base_url="https://c411.org")
    assert store.effective_tracker("c411") == ("secret", "https://c411.org")


def test_write_defaults_base_url_when_absent_for_c411():
    store.write(profile="c411", tracker_api_key="secret")
    assert store.effective_tracker("c411") == ("secret", "https://c411.org")


def test_no_default_base_url_for_a_non_c411_profile():
    # Aucune URL par defaut connue pour un tracker qu'on ne connait pas.
    store.write(profile="ygg", tracker_api_key="secret")
    assert store.effective_tracker("ygg") is None


def test_two_profiles_keep_separate_credentials():
    store.write(profile="c411", tracker_api_key="c411-key", tracker_base_url="https://c411.org")
    store.write(profile="ygg", tracker_api_key="ygg-key", tracker_base_url="https://ygg.example")
    assert store.effective_tracker("c411") == ("c411-key", "https://c411.org")
    assert store.effective_tracker("ygg") == ("ygg-key", "https://ygg.example")


def test_partial_write_does_not_erase_other_fields():
    store.write(profile="c411", tracker_api_key="secret", sonarr_url="http://sonarr.local", sonarr_api_key="sk")
    store.write(radarr_url="http://radarr.local", radarr_api_key="rk")

    assert store.effective_tracker("c411") == ("secret", "https://c411.org")
    assert store.effective_sonarr() == ("http://sonarr.local", "sk")
    assert store.effective_radarr() == ("http://radarr.local", "rk")


def test_write_overwrites_existing_field():
    store.write(profile="c411", tracker_api_key="old")
    store.write(profile="c411", tracker_api_key="new")
    assert store.effective_tracker("c411") == ("new", "https://c411.org")


def test_never_exposes_secrets_in_status():
    store.write(profile="c411", tracker_api_key="secret", sonarr_url="http://sonarr.local", sonarr_api_key="sk")
    status = store.status("c411")
    assert "secret" not in str(status)
    assert "sk" not in str(status)
    assert status["tracker_configured"] is True
    assert status["sonarr_configured"] is True
    assert status["sonarr_url"] == "http://sonarr.local"


def test_status_includes_the_requested_profile():
    assert store.status("c411")["profile"] == "c411"
    assert store.status("ygg")["profile"] == "ygg"


def test_falls_back_to_env_vars_when_file_not_configured_for_c411(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    assert store.effective_tracker("c411") == ("from-env", "https://c411.org")


def test_env_var_fallback_never_applies_to_a_non_c411_profile(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    assert store.effective_tracker("ygg") is None


def test_falls_back_to_env_vars_when_file_empty(monkeypatch, tmp_path):
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(tmp_path / "empty.json"))
    monkeypatch.setenv("NFOGEN_SONARR_URL", "http://from-env.local")
    monkeypatch.setenv("NFOGEN_SONARR_API_KEY", "from-env-key")
    assert store.effective_sonarr() == ("http://from-env.local", "from-env-key")


def test_stored_value_takes_precedence_over_env_var(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    store.write(profile="c411", tracker_api_key="from-file")
    assert store.effective_tracker("c411") == ("from-file", "https://c411.org")


def test_legacy_flat_c411_fields_still_read_when_no_namespaced_entry_exists(tmp_path):
    # Retrocompat sans script de migration (AUTOMATION.md, sous-projet 4b) :
    # un fichier ecrit par l'ANCIEN code (avant le namespacage par profil)
    # doit continuer a fonctionner tel quel.
    config_path = tmp_path / "gapscan_config.json"
    config_path.write_text(
        '{"c411_api_key": "legacy-key", "c411_base_url": "https://c411.org", '
        '"c411_announce_url": "https://c411.org/announce/LEGACY"}',
        encoding="utf-8",
    )
    assert store.effective_tracker("c411") == ("legacy-key", "https://c411.org")
    assert store.effective_tracker_announce_url("c411") == "https://c411.org/announce/LEGACY"


def test_namespaced_entry_takes_precedence_over_legacy_flat_fields(tmp_path):
    config_path = tmp_path / "gapscan_config.json"
    config_path.write_text(
        '{"c411_api_key": "legacy-key", "trackers": {"c411": {"api_key": "new-key", '
        '"base_url": "https://c411.org"}}}',
        encoding="utf-8",
    )
    assert store.effective_tracker("c411") == ("new-key", "https://c411.org")


def test_write_without_config_file_env_var_raises(monkeypatch):
    monkeypatch.delenv("NFOGEN_GAPSCAN_CONFIG_FILE", raising=False)
    with pytest.raises(store.GapscanConfigStoreError):
        store.write(profile="c411", tracker_api_key="x")


def test_path_mappings_default_to_empty_dict():
    assert store.effective_sonarr_path_mappings() == {}
    assert store.effective_radarr_path_mappings() == {}


def test_write_then_read_sonarr_path_mappings():
    store.write(sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"})
    assert store.effective_sonarr_path_mappings() == {"/data/tv": "/mnt/nas/tv"}


def test_write_then_read_radarr_path_mappings():
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_write_path_mappings_does_not_erase_other_fields():
    store.write(profile="c411", tracker_api_key="secret")
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_tracker("c411") == ("secret", "https://c411.org")
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_status_includes_path_mappings():
    store.write(
        sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"},
        radarr_path_mappings={"/data/movies": "/mnt/nas/movies"},
    )
    status = store.status("c411")
    assert status["sonarr_path_mappings"] == {"/data/tv": "/mnt/nas/tv"}
    assert status["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}


def test_status_path_mappings_empty_by_default():
    status = store.status("c411")
    assert status["sonarr_path_mappings"] == {}
    assert status["radarr_path_mappings"] == {}


def test_tracker_announce_url_defaults_to_none():
    assert store.effective_tracker_announce_url("c411") is None


def test_write_then_read_tracker_announce_url():
    store.write(profile="c411", tracker_announce_url="https://c411.org/announce/SECRET")
    assert store.effective_tracker_announce_url("c411") == "https://c411.org/announce/SECRET"


def test_staging_dir_defaults_to_none():
    assert store.effective_staging_dir() is None


def test_write_then_read_staging_dir():
    store.write(staging_dir="/data/staging")
    assert store.effective_staging_dir() == "/data/staging"


def test_status_exposes_announce_url_as_a_flag_not_the_secret_itself():
    store.write(profile="c411", tracker_announce_url="https://c411.org/announce/SECRET")
    status = store.status("c411")
    assert status["tracker_announce_url_configured"] is True
    assert "SECRET" not in str(status)


def test_status_announce_url_flag_false_by_default():
    assert store.status("c411")["tracker_announce_url_configured"] is False


def test_status_includes_staging_dir():
    store.write(staging_dir="/data/staging")
    assert store.status("c411")["staging_dir"] == "/data/staging"


def test_status_staging_dir_none_by_default():
    assert store.status("c411")["staging_dir"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="permissions POSIX non applicables sur Windows")
def test_write_sets_restrictive_permissions(tmp_path):
    store.write(profile="c411", tracker_api_key="secret")
    mode = stat.S_IMODE((tmp_path / "gapscan_config.json").stat().st_mode)
    assert mode == 0o600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gapscan_config_store.py -v`
Expected: FAIL — `write()`/`effective_tracker()`/`effective_tracker_announce_url()`/`status(profile)` don't exist yet with this signature (`TypeError`/`AttributeError`).

- [ ] **Step 3: Rewrite the implementation**

Replace `nfogen/gapscan_config_store.py`'s `write`/`effective_c411`/`effective_c411_announce_url`/`status` (keep `_load`, `_path`, `is_configured`, `_resolve`, `effective_sonarr`, `effective_radarr`, `effective_sonarr_path_mappings`, `effective_radarr_path_mappings`, `effective_staging_dir`, `GapscanConfigStoreError`, `_DEFAULT_C411_BASE_URL` unchanged):

```python
def write(
    *,
    profile: str = "c411",
    tracker_api_key: Optional[str] = None,
    tracker_base_url: Optional[str] = None,
    tracker_announce_url: Optional[str] = None,
    sonarr_url: Optional[str] = None,
    sonarr_api_key: Optional[str] = None,
    radarr_url: Optional[str] = None,
    radarr_api_key: Optional[str] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
    staging_dir: Optional[str] = None,
) -> None:
    """Met a jour uniquement les champs fournis (`None` = inchange) -- jamais
    une reecriture complete. `profile` : les identifiants de TRACKER
    (`tracker_*`) sont namespaces par profil (`trackers.<profile>.*`) --
    Sonarr/Radarr/staging_dir restent globaux (une seule bibliotheque
    media, independante du tracker cible). Voir AUTOMATION.md, sous-projet
    4b."""
    path = _path()
    data = _load()
    top_level_updates = {
        "sonarr_url": sonarr_url,
        "sonarr_api_key": sonarr_api_key,
        "radarr_url": radarr_url,
        "radarr_api_key": radarr_api_key,
        "sonarr_path_mappings": sonarr_path_mappings,
        "radarr_path_mappings": radarr_path_mappings,
        "staging_dir": staging_dir,
    }
    for key, value in top_level_updates.items():
        if value is not None:
            data[key] = value

    tracker_updates = {
        "api_key": tracker_api_key,
        "base_url": tracker_base_url,
        "announce_url": tracker_announce_url,
    }
    if any(value is not None for value in tracker_updates.values()):
        trackers = data.setdefault("trackers", {})
        bucket = trackers.setdefault(profile, {})
        for key, value in tracker_updates.items():
            if value is not None:
                bucket[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def effective_tracker(profile: str = "c411") -> Optional[tuple[str, str]]:
    """`(cle, base_url)` pour CE profil, ou `None` si aucune cle configuree
    (fichier namespace, fichier legacy, ou environnement -- dans cet ordre
    de priorite). Le repli sur les champs plats `c411_*` et les variables
    d'environnement `NFOGEN_C411_*` ne s'applique QU'au profil `c411` --
    c'est le seul qui existait avant le namespacage par profil
    (retrocompat sans script de migration, AUTOMATION.md sous-projet 4b) ;
    un futur second profil n'a par definition rien a migrer."""
    data = _load()
    bucket = (data.get("trackers") or {}).get(profile, {})
    api_key = bucket.get("api_key")
    base_url = bucket.get("base_url")
    if profile == "c411":
        api_key = api_key or data.get("c411_api_key")
        base_url = base_url or data.get("c411_base_url")
        api_key = api_key or os.environ.get("NFOGEN_C411_API_KEY")
        base_url = base_url or os.environ.get("NFOGEN_C411_BASE_URL")
    if not api_key:
        return None
    if not base_url and profile == "c411":
        base_url = _DEFAULT_C411_BASE_URL
    if not base_url:
        return None
    return api_key, base_url


def effective_tracker_announce_url(profile: str = "c411") -> Optional[str]:
    """URL d'annonce privee complete (passkey inclus) pour CE profil --
    aussi sensible qu'une cle API, jamais renvoyee en clair par `status()`.
    `None` si non configuree. Pas de repli sur une variable d'environnement
    (jamais eu, meme avant le namespacage)."""
    data = _load()
    bucket = (data.get("trackers") or {}).get(profile, {})
    url = bucket.get("announce_url")
    if not url and profile == "c411":
        url = data.get("c411_announce_url")
    return url or None


def status(profile: str = "c411") -> dict[str, Any]:
    """Etat effectif pour CE profil (fichier prioritaire, sinon
    variables d'environnement pour `c411`) -- jamais les cles/secrets
    eux-memes. Sonarr/Radarr/mappings/staging_dir sont globaux, pas
    filtres par `profile`."""
    tracker = effective_tracker(profile)
    sonarr = effective_sonarr()
    radarr = effective_radarr()
    return {
        "profile": profile,
        "tracker_configured": tracker is not None,
        "tracker_base_url": tracker[1] if tracker else None,
        "sonarr_configured": sonarr is not None,
        "sonarr_url": sonarr[0] if sonarr else None,
        "radarr_configured": radarr is not None,
        "radarr_url": radarr[0] if radarr else None,
        "sonarr_path_mappings": effective_sonarr_path_mappings(),
        "radarr_path_mappings": effective_radarr_path_mappings(),
        "tracker_announce_url_configured": effective_tracker_announce_url(profile) is not None,
        "staging_dir": effective_staging_dir(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan_config_store.py -v`
Expected: all PASS. (`nfogen/api.py` and `nfogen/upload_prep.py` still call the old `effective_c411`/`effective_c411_announce_url`/`status()` names at this point — they will fail to import/run; that's expected and fixed in Tasks 8 and 10. Confirm with `pytest tests/test_gapscan_config_store.py -v` specifically, not the full suite yet.)

- [ ] **Step 5: Commit (without running the full suite yet — later tasks fix the callers)**

```bash
git add nfogen/gapscan_config_store.py tests/test_gapscan_config_store.py
git commit -m "feat: identifiants de tracker namespaces par profil dans gapscan_config_store.py"
```

---

### Task 5: Rename `c411_client.py` → `torznab_client.py`

**Files:**
- Create: `nfogen/torznab_client.py` (moved content of `nfogen/c411_client.py`)
- Delete: `nfogen/c411_client.py`
- Modify: `nfogen/gapscan.py`, `nfogen/gapscan_runner.py`
- Test: rename `tests/test_c411_client.py` → `tests/test_torznab_client.py`

**Interfaces:**
- Produces: `TorznabClient`, `TorznabError`, `TorznabRelease`, `parse_torznab_response` — same members, same signatures as the old `C411Client`/`C411Error`/`C411Release`, pure rename.

- [ ] **Step 1: Move and rename the module**

```bash
git mv nfogen/c411_client.py nfogen/torznab_client.py
git mv tests/test_c411_client.py tests/test_torznab_client.py
```

In `nfogen/torznab_client.py`, rename every occurrence:
- `class C411Error` → `class TorznabError`
- `class C411Release` → `class TorznabRelease`
- `class C411Client` → `class TorznabClient`
- `-> list[C411Release]` → `-> list[TorznabRelease]` (both in `parse_torznab_response` and `_parse_item`)
- Every `raise C411Error(...)` → `raise TorznabError(...)`
- Every `-> "C411Client"` (the `__enter__` return type) → `-> "TorznabClient"`
- Docstring on line 1 stays accurate as-is (already describes it as Torznab-generic); update only the class/line references to the tracker name, not the prose.

In `tests/test_torznab_client.py`, rename every occurrence:
- `from nfogen.c411_client import C411Client, C411Error, parse_torznab_response` → `from nfogen.torznab_client import TorznabClient, TorznabError, parse_torznab_response`
- Every `C411Client(` → `TorznabClient(`
- Every `C411Error` → `TorznabError`
- Function names that mention `c411` (e.g. `test_c411_client_...`) stay as-is unless they explicitly reference the class name in a way that's now wrong — check each with `grep -n "c411\|C411" tests/test_torznab_client.py` and fix mentions of the renamed identifiers only (not the tracker's own name in prose/fixtures, which stays `c411` since the fixtures are real C411 API responses).

- [ ] **Step 2: Update importers**

In `nfogen/gapscan.py`, change:
```python
from .c411_client import C411Client, C411Error, C411Release
```
to:
```python
from .torznab_client import TorznabClient, TorznabError, TorznabRelease
```
Then rename every use of `C411Client`/`C411Error`/`C411Release` in the file's type hints and `except C411Error` clauses to `TorznabClient`/`TorznabError`/`TorznabRelease`. Leave `GapResult.c411_matches` and all prose/comments mentioning "C411" untouched — this task renames the CLIENT module only, not GapScan's own vocabulary (that's addressed incidentally by later tasks where it overlaps, e.g. Task 7's `genre_of`).

In `nfogen/gapscan_runner.py`, change:
```python
from .c411_client import C411Client
```
to:
```python
from .torznab_client import TorznabClient
```
and rename the `c411: C411Client` parameter type hints in `_run()`/`start()` to `c411: TorznabClient` (keep the parameter NAME `c411` for now — Task 10 renames call-site variable names in `api.py` when it threads `profile` through; renaming the parameter name here too is unnecessary churn for this task).

- [ ] **Step 3: Run the affected tests**

Run: `pytest tests/test_torznab_client.py tests/test_gapscan.py tests/test_gapscan_runner.py -v`
Expected: all PASS (pure rename, no behavior change).

Note: `nfogen/api.py` still does `from .c411_client import C411Client, C411Error` at this point — it will fail to import. That's expected; Task 10 updates `api.py`. Do not run the full suite or `tests/test_api.py` yet.

- [ ] **Step 4: Commit**

```bash
git add nfogen/torznab_client.py nfogen/gapscan.py nfogen/gapscan_runner.py tests/test_torznab_client.py
git rm nfogen/c411_client.py tests/test_c411_client.py 2>/dev/null || true
git commit -m "refactor: renomme c411_client.py en torznab_client.py (protocole deja generique)"
```

---

### Task 6: `torrent_builder.py` reads the piece-size table from a parameter, not a constant

**Files:**
- Modify: `nfogen/torrent_builder.py`
- Test: `tests/test_torrent_builder.py`

**Interfaces:**
- Consumes: `tracker_profile.torrent_piece_sizes(profile)` (Task 2) — resolved by the CALLER (Task 8's `upload_prep.py`), not by this module (`torrent_builder.py` stays profile-agnostic and pure, no dependency on `profile_store`).
- Produces: `piece_size_for(total_bytes: int, piece_sizes: list[dict[str, int]]) -> int`, `build_torrent(staged_path: str, announce_url: str, output_path: str, piece_sizes: list[dict[str, int]]) -> None` (both gain a required `piece_sizes` parameter, no default — the whole point of this task is that no C411-shaped table exists in this file anymore).

- [ ] **Step 1: Write the failing tests (rewrite the piece-size assertions)**

In `tests/test_torrent_builder.py`, add a shared fixture table near the top (after the `_MO`/`_GO` constants) and update every `piece_size_for`/`build_torrent` call to pass it:

```python
_C411_PIECE_SIZES = [
    {"max_bytes": 1 * _GO, "piece_size": 1 * _MO},
    {"max_bytes": 2 * _GO, "piece_size": 2 * _MO},
    {"max_bytes": 3 * _GO, "piece_size": 4 * _MO},
    {"max_bytes": 8 * _GO, "piece_size": 8 * _MO},
    {"piece_size": 16 * _MO},
]


def test_piece_size_for_under_1go():
    assert piece_size_for(500 * _MO, _C411_PIECE_SIZES) == 1 * _MO


def test_piece_size_for_under_2go():
    assert piece_size_for(1500 * _MO, _C411_PIECE_SIZES) == 2 * _MO


def test_piece_size_for_under_3go():
    assert piece_size_for(int(2.5 * _GO), _C411_PIECE_SIZES) == 4 * _MO


def test_piece_size_for_under_8go():
    assert piece_size_for(5 * _GO, _C411_PIECE_SIZES) == 8 * _MO


def test_piece_size_for_8go_or_more():
    assert piece_size_for(10 * _GO, _C411_PIECE_SIZES) == 16 * _MO


def test_piece_size_for_exactly_at_a_threshold_uses_the_next_tier():
    assert piece_size_for(1 * _GO, _C411_PIECE_SIZES) == 2 * _MO


def test_piece_size_for_raises_on_an_empty_table():
    # Bareme non declare pour ce profil (tracker_profile.torrent_piece_sizes
    # renvoie []) : erreur claire plutot qu'une taille devinee.
    with pytest.raises(ValueError, match="[Bb]ar[eè]me"):
        piece_size_for(500 * _MO, [])
```

Then, in the existing `test_build_torrent_creates_a_valid_private_torrent` test (and any other `build_torrent(...)` call in the file), add `_C411_PIECE_SIZES` as the fourth positional argument. Add `import pytest` at the top of the file if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_torrent_builder.py -v`
Expected: FAIL — `TypeError: piece_size_for() missing 1 required positional argument: 'piece_sizes'` (current signature only takes `total_bytes`).

- [ ] **Step 3: Update the implementation**

Replace in `nfogen/torrent_builder.py` — remove `_PIECE_SIZE_TABLE`/`_DEFAULT_PIECE_SIZE` module constants and the comment above them, replace `piece_size_for`:

```python
def piece_size_for(total_bytes: int, piece_sizes: list[dict[str, int]]) -> int:
    """Taille de piece (en octets) pour un contenu de `total_bytes`, d'apres
    le bareme `piece_sizes` du profil (rules.json -> tracker.torrent_piece_sizes,
    voir tracker_profile.py) -- plus aucune valeur specifique a un tracker
    en dur ici. Chaque entree : `{"max_bytes": N, "piece_size": P}` (piece
    P pour tout contenu < N octets), sauf la DERNIERE entree qui peut
    omettre `max_bytes` (piece par defaut au-dela de tous les seuils).
    Fonction pure, testable sans I/O."""
    for entry in piece_sizes:
        max_bytes = entry.get("max_bytes")
        if max_bytes is None or total_bytes < max_bytes:
            return entry["piece_size"]
    raise ValueError(
        "Barème de taille de pièce vide ou mal terminé (attendu : une dernière "
        "entrée sans 'max_bytes', voir rules.json -> tracker.torrent_piece_sizes)."
    )
```

And update `build_torrent`:

```python
def build_torrent(
    staged_path: str, announce_url: str, output_path: str, piece_sizes: list[dict[str, int]]
) -> None:
    """Construit un .torrent prive a partir de `staged_path` (fichier ou
    dossier -- un dossier pour un pack multi-fichiers -- deja mis en scene
    par file_staging.py, jamais le fichier original) et l'ecrit dans
    `output_path`. Taille de piece choisie via `piece_size_for` a partir du
    bareme `piece_sizes` du profil (voir tracker_profile.torrent_piece_sizes)."""
    total_bytes = _total_size(staged_path)
    torrent = torf.Torrent(
        path=staged_path,
        trackers=[announce_url],
        private=True,
        piece_size=piece_size_for(total_bytes, piece_sizes),
    )
    torrent.generate()
    torrent.write(output_path)
```

Also update the module docstring at the top of the file (currently says "conforme aux regles C411") to reflect that the rules now come from the caller, not this file — replace with:

```python
"""Construction du fichier .torrent final (voir AUTOMATION.md, sous-projet
2) : tracker prive, une seule adresse d'annonce (celle du compte, jamais
journalisee/exposee -- voir gapscan_config_store.py), taille de piece
choisie selon le bareme fourni par l'appelant (voir tracker_profile.py --
ce module reste agnostique du tracker, aucune table en dur ici)."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_torrent_builder.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

Note: `nfogen/upload_prep.py` still calls `torrent_builder.build_torrent(staged_path, announce_url, torrent_path)` with 3 args at this point — it will break at runtime (not at import time, since Python doesn't check arg counts until called). This is fixed in Task 8. Do not run the full suite yet.

```bash
git add nfogen/torrent_builder.py tests/test_torrent_builder.py
git commit -m "refactor: piece_size_for/build_torrent recoivent le bareme en parametre"
```

---

### Task 7: `gapscan.py:genre_of` reads categories from the profile

**Files:**
- Modify: `nfogen/gapscan.py`
- Test: `tests/test_gapscan.py`

**Interfaces:**
- Consumes: `tracker_profile.torznab_categories(profile)` (Task 2/3).
- Produces: `genre_of(result: GapResult, profile: str = "c411") -> Optional[str]` (gains a `profile` parameter with the same default as everywhere else in this codebase).

- [ ] **Step 1: Write the failing tests**

In `tests/test_gapscan.py`, find the existing `genre_of` tests (`test_genre_of_returns_none_when_no_c411_matches`, `test_genre_of_anime_for_movie_category`, `test_genre_of_anime_for_series_category`, `test_genre_of_documentaire_for_movie_and_series_categories`, `test_genre_of_none_for_standard_film_or_series_category`, `test_genre_of_uses_the_first_match_when_several_exist`) and add two new ones alongside them (these still pass `profile="c411"` implicitly via the default, so none of the 6 existing tests need to change):

```python
def test_genre_of_uses_the_given_profile_not_always_c411(monkeypatch):
    from nfogen import tracker_profile

    monkeypatch.setattr(
        tracker_profile, "torznab_categories",
        lambda profile: {"anime": ["9999"]} if profile == "other" else {},
    )
    result = _result(category="9999")
    assert genre_of(result, profile="other") == "anime"
    assert genre_of(result, profile="c411") is None


def test_genre_of_none_when_profile_has_no_torznab_categories_declared(monkeypatch):
    from nfogen import tracker_profile

    monkeypatch.setattr(tracker_profile, "torznab_categories", lambda profile: {})
    result = _result(category="2060")  # code anime C411 reel
    assert genre_of(result, profile="c411") is None
```

(`_result(category=...)` is the existing test helper in `tests/test_gapscan.py` used by the pre-existing genre tests — reuse it as-is; check its exact signature in the file before writing these two tests, since the plan author has not read every line of `tests/test_gapscan.py` and the helper's exact keyword name may differ slightly, e.g. `category=` vs positional.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gapscan.py -k genre_of -v`
Expected: the 2 new tests FAIL (`genre_of` doesn't accept a `profile` kwarg yet); the 6 existing ones still PASS unchanged.

- [ ] **Step 3: Update the implementation**

In `nfogen/gapscan.py`, remove the `_ANIME_CATEGORIES`/`_DOCUMENTARY_CATEGORIES` module constants and the comment block above them, add an import, and rewrite `genre_of`:

```python
from . import tracker_profile
```

```python
def genre_of(result: GapResult, profile: str = "c411") -> Optional[str]:
    """'anime'/'documentaire' d'apres la categorie du PREMIER match trouve
    (deja trie par pertinence cote tracker) et les codes de categorie
    Torznab declares par CE profil (rules.json -> tracker.torznab_categories,
    voir tracker_profile.py) ; `None` si ce match est un film/serie
    standard, si le profil n'a rien declare, OU si aucun match n'existe du
    tout -- un titre "absent" n'a par definition aucune categorie, jamais
    classifiable par genre fin (voir GAPSCAN.md, limite assumee)."""
    if not result.c411_matches:
        return None
    category = result.c411_matches[0].category
    categories = tracker_profile.torznab_categories(profile)
    if category in categories.get("anime", []):
        return "anime"
    if category in categories.get("documentaire", []):
        return "documentaire"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan.py -v`
Expected: all PASS, including the 6 pre-existing `genre_of` tests (they rely on `profile="c411"`'s default resolving to the real `c411` profile's `torznab_categories`, populated in Task 3).

- [ ] **Step 5: Commit**

Note: `nfogen/api.py` and `nfogen/gapscan_runner.py` call `gapscan.genre_of(r)` without a `profile` argument — that keeps working unchanged (the new parameter has a default). Full suite is safe to run for this task alone, but `tests/test_api.py` will still fail because of Task 5's unresolved `c411_client` import in `api.py` — run only the targeted test file.

```bash
git add nfogen/gapscan.py tests/test_gapscan.py
git commit -m "feat: genre_of lit les categories Torznab du profil au lieu de constantes"
```

---

### Task 8: `upload_prep.py` reads announce URL, piece sizes, and language codes from the profile

**Files:**
- Modify: `nfogen/upload_prep.py`
- Test: `tests/test_upload_prep.py`

**Interfaces:**
- Consumes: `gapscan_config_store.effective_tracker_announce_url(profile)` (Task 4), `tracker_profile.torrent_piece_sizes(profile)` and `tracker_profile.audio_language_codes(profile)` (Task 2/3), `torrent_builder.build_torrent(..., piece_sizes)` (Task 6).
- Produces: `_language_hint_from_audio_tracks(audio_languages: list[str], language_codes: dict[str, str]) -> str` (gains a required `language_codes` parameter, no more module-level `_AUDIO_LANGUAGE_CODE` constant); `commit_upload()`'s behavior otherwise unchanged from the caller's point of view.

- [ ] **Step 1: Write the failing tests**

In `tests/test_upload_prep.py`, find the existing `_language_hint_from_audio_tracks` tests and update every call site to pass a language-codes table as the second argument. Add this fixture near the top of the file (after imports):

```python
_C411_AUDIO_LANGUAGE_CODES = {
    "fr": "FR", "fre": "FR", "fra": "FR", "french": "FR",
    "en": "EN", "eng": "EN", "english": "EN",
    "ja": "JA", "jpn": "JA", "japanese": "JA",
}
```

```python
def test_single_recognized_language():
    assert _language_hint_from_audio_tracks(["fre"], _C411_AUDIO_LANGUAGE_CODES) == "FR"


def test_two_recognized_languages_combined_with_plus():
    assert _language_hint_from_audio_tracks(["fre", "eng"], _C411_AUDIO_LANGUAGE_CODES) == "FR+EN"


def test_duplicate_language_not_repeated():
    assert _language_hint_from_audio_tracks(["fre", "fre"], _C411_AUDIO_LANGUAGE_CODES) == "FR"


def test_unrecognized_language_ignored():
    assert _language_hint_from_audio_tracks(["fre", "klingon"], _C411_AUDIO_LANGUAGE_CODES) == "FR"


def test_no_tracks_or_all_unrecognized_returns_empty_string():
    assert _language_hint_from_audio_tracks([], _C411_AUDIO_LANGUAGE_CODES) == ""
    assert _language_hint_from_audio_tracks(["klingon"], _C411_AUDIO_LANGUAGE_CODES) == ""


def test_empty_language_codes_table_never_produces_a_hint():
    # Profil sans audio_language_codes declare : jamais d'indice devine.
    assert _language_hint_from_audio_tracks(["fre", "eng"], {}) == ""
```

(These replace the pre-existing versions of the same test names — update in place rather than duplicating.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_upload_prep.py -k language_hint -v`
Expected: FAIL — `TypeError: _language_hint_from_audio_tracks() missing 1 required positional argument`.

- [ ] **Step 3: Update the implementation**

In `nfogen/upload_prep.py`:

1. Remove the module-level `_AUDIO_LANGUAGE_CODE` dict and its comment block.
2. Add `from . import tracker_profile` to the imports.
3. Rewrite `_language_hint_from_audio_tracks`:

```python
def _language_hint_from_audio_tracks(audio_languages: list[str], language_codes: dict[str, str]) -> str:
    """Construit un indice de langue a partir des VRAIES pistes audio du
    fichier (`extract_video_metadata`), jamais du nom de fichier -- comble
    un ecart reel (nom de fichier sans tag de langue, alors que le fichier
    a bien des pistes FR/EN detectees). `language_codes` (voir
    tracker_profile.audio_language_codes) : mapping code/nom MediaInfo ->
    code court reconnu par les alias de langue du profil -- vide si le
    profil n'en declare aucun, jamais de supposition au-dela. Plusieurs
    langues sont combinees avec '+' (ex. 'FR+EN') pour que le profil
    detecte le prefixe MULTI attendu sur les releases multi-langues."""
    codes: list[str] = []
    for lang in audio_languages:
        if not lang:
            continue
        code = language_codes.get(lang.strip().lower())
        if code and code not in codes:
            codes.append(code)
    return "+".join(codes)
```

4. Update the call site inside `preview_upload()`:

```python
    language_codes = tracker_profile.audio_language_codes(profile)
    hints: list[Optional[str]] = []
    for m in metas:
        title_tag = m.get("general_title") or ""
        audio_hint = _language_hint_from_audio_tracks(m.get("audio_languages") or [], language_codes)
        combined = " ".join(part for part in (title_tag, audio_hint) if part)
        hints.append(combined or None)
```

5. Update `commit_upload()` — replace the announce-URL lookup and the `build_torrent` call:

```python
    announce_url = gapscan_config_store.effective_tracker_announce_url(profile)
    if not announce_url:
        raise ValueError(
            f"Adresse d'annonce non configurée pour le profil '{profile}' "
            "(PUT /gapscan/config, champ tracker_announce_url)."
        )
```

(replaces the old `effective_c411_announce_url()` call and its error message)

```python
    torrent_path = str(Path(staging_dir) / f"{release_name}.torrent")
    piece_sizes = tracker_profile.torrent_piece_sizes(profile)
    torrent_builder.build_torrent(staged_path, announce_url, torrent_path, piece_sizes)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_upload_prep.py -v`
Expected: all PASS, including the existing `test_multi_prefix_from_real_audio_tracks_not_just_filename` (or similarly-named) end-to-end test that exercises `preview_upload()` against the real `c411` profile — it now resolves `audio_language_codes` from `nfogen/profiles/c411/rules.json` (Task 3) instead of the removed constant, same values, so its assertion (`"MULTI.VFF" in proposals[0].release_name`) is unaffected.

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_prep.py tests/test_upload_prep.py
git commit -m "feat: upload_prep.py lit announce_url/bareme de piece/codes de langue du profil"
```

---

### Task 9: `gapscan_runner.py:results` threads `profile` to `genre_of`

**Files:**
- Modify: `nfogen/gapscan_runner.py`
- Test: `tests/test_gapscan_runner.py`

**Interfaces:**
- Consumes: `gapscan.genre_of(result, profile)` (Task 7).
- Produces: `results(status_filter=None, media_type_filter=None, genre_filter=None, profile: str = "c411") -> list[GapResult]`.

- [ ] **Step 1: Write the failing test**

In `tests/test_gapscan_runner.py`, find the existing genre-filter tests and add:

```python
def test_results_genre_filter_uses_the_given_profile(monkeypatch):
    from nfogen import tracker_profile

    monkeypatch.setattr(
        tracker_profile, "torznab_categories",
        lambda profile: {"anime": ["9999"]} if profile == "other" else {},
    )
    # Reutilise le mecanisme de construction de resultat deja present dans
    # ce fichier de test pour produire un GapResult dont le premier match a
    # category="9999" (voir les tests genre_of existants dans
    # tests/test_gapscan.py pour le helper equivalent si ce fichier n'en a
    # pas deja un local).
    ...
```

(This step's exact assertion body depends on how `tests/test_gapscan_runner.py` currently constructs a `GapResult`/seeds `gapscan_runner._results` for its existing genre-filter tests — read that file's existing `test_results_filters_by_genre`-style test immediately before writing this one, and mirror its setup exactly, replacing only the final assertion to call `runner.results(genre_filter="anime", profile="other")` and assert the seeded result is included, then `runner.results(genre_filter="anime", profile="c411")` and assert it is excluded.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gapscan_runner.py -k profile -v`
Expected: FAIL — `results()` doesn't accept a `profile` kwarg yet.

- [ ] **Step 3: Update the implementation**

In `nfogen/gapscan_runner.py`, update `results()`:

```python
def results(
    status_filter: Optional[str] = None,
    media_type_filter: Optional[str] = None,
    genre_filter: Optional[str] = None,
    profile: str = "c411",
) -> list[GapResult]:
    """Resultats du dernier scan termine. `status_filter` : une valeur de
    `GapStatus` (ex. "absent"). `media_type_filter` : "movie" ou "series".
    `genre_filter` : "anime" ou "documentaire", evalue contre les
    categories Torznab DU PROFIL `profile` (voir `gapscan.genre_of` /
    `tracker_profile.torznab_categories`) -- un titre sans match C411 ne
    correspond jamais a un genre_filter."""
    with _lock:
        items = list(_results)
    if status_filter is not None:
        items = [r for r in items if r.status.value == status_filter]
    if media_type_filter is not None:
        items = [r for r in items if r.media_type == media_type_filter]
    if genre_filter is not None:
        items = [r for r in items if genre_of(r, profile) == genre_filter]
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan_runner.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_runner.py tests/test_gapscan_runner.py
git commit -m "feat: gapscan_runner.results() accepte un parametre profile pour le filtre genre"
```

---

### Task 10: `api.py` — profile-aware GapScan config/run/results endpoints

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 4–9 (`gapscan_config_store.write/effective_tracker/status`, `TorznabClient/TorznabError`, `gapscan_runner.results(profile=)`, `gapscan.genre_of(r, profile)`).
- Produces: `GET/PUT /gapscan/config`, `POST /gapscan/run`, `GET /gapscan/results`, `GET /gapscan/results/export.csv` all accept `profile` (query param on GETs/POST, body field on the PUT), defaulting to `"c411"` everywhere so an unmodified frontend request still works during a rolling deploy.

- [ ] **Step 1: Write the failing tests**

In `tests/test_api.py`, locate the existing GapScan config/run/results tests (search for `/gapscan/config`, `/gapscan/run`, `/gapscan/results`). This step cannot enumerate every existing test's exact fixture setup without reading the file in full — but the required NEW assertions are:

```python
def test_gapscan_config_write_uses_tracker_field_names(client, gapscan_env):
    resp = client.put(
        "/gapscan/config",
        json={"profile": "c411", "tracker_api_key": "secret", "tracker_base_url": "https://c411.org"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["tracker_configured"] is True
    assert "secret" not in resp.text


def test_gapscan_config_get_defaults_to_c411_profile(client, gapscan_env):
    resp = client.get("/gapscan/config", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["profile"] == "c411"


def test_gapscan_config_get_accepts_a_profile_query_param(client, gapscan_env):
    resp = client.get("/gapscan/config?profile=ygg", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["profile"] == "ygg"


def test_gapscan_run_accepts_a_profile_query_param(client, gapscan_env):
    resp = client.put(
        "/gapscan/config",
        json={"profile": "ygg", "tracker_api_key": "k", "tracker_base_url": "https://ygg.example",
              "sonarr_url": "http://sonarr.local", "sonarr_api_key": "sk"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    resp = client.post("/gapscan/run?profile=ygg", headers=AUTH_HEADERS)
    assert resp.status_code in (200, 409)  # 409 si un scan tournait deja d'un test precedent
```

(Fixture names `client`/`gapscan_env`/`AUTH_HEADERS` are placeholders for whatever `tests/test_api.py` already uses for its other `/gapscan/*` tests — read the file's existing GapScan test block immediately before writing these, copy its exact fixture/header pattern, and rename every EXISTING test that constructs a `PUT /gapscan/config` body with `c411_api_key`/`c411_base_url`/`c411_announce_url` keys to use `tracker_api_key`/`tracker_base_url`/`tracker_announce_url` instead, and every assertion reading `resp.json()["c411_configured"]`/`["c411_base_url"]`/`["c411_announce_url_configured"]` to read `["tracker_configured"]`/`["tracker_base_url"]`/`["tracker_announce_url_configured"]` instead — this is a mechanical rename across the existing GapScan config test block, not new coverage, and must happen in this same step so the suite isn't red for the wrong reason afterward.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -k gapscan_config -v`
Expected: FAIL — current `GapscanConfigWriteRequest` still has `c411_api_key`/`c411_base_url`/`c411_announce_url` fields (extra fields silently ignored by Pydantic by default, so `tracker_api_key` sent by the new tests is dropped, and `resp.json()` still has the old `c411_configured` key, not `tracker_configured`).

- [ ] **Step 3: Update the implementation**

In `nfogen/api.py`:

1. Change the import (paired with Task 5's rename):
```python
from .torznab_client import TorznabClient, TorznabError
```
(update every other reference to `C411Client`/`C411Error` in this file to `TorznabClient`/`TorznabError` — `except (ValueError, C411Error, SonarrError, RadarrError)` clauses, etc.)

2. Add an import for the new module:
```python
from . import tracker_profile
```

3. Replace `gapscan_config`:
```python
@app.get("/gapscan/config", dependencies=[Depends(require_token)])
def gapscan_config(profile: str = Query("c411")) -> dict[str, Any]:
    """Jamais les cles elles-memes, seulement si chaque service est
    configure (+ son URL, non sensible)."""
    _require_gapscan_available()
    return gapscan_config_store.status(profile)
```

4. Replace `GapscanConfigWriteRequest` and `gapscan_config_write`:
```python
class GapscanConfigWriteRequest(BaseModel):
    profile: str = "c411"
    tracker_api_key: Optional[str] = None
    tracker_base_url: Optional[str] = None
    tracker_announce_url: Optional[str] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    sonarr_path_mappings: Optional[dict[str, str]] = None
    radarr_path_mappings: Optional[dict[str, str]] = None
    staging_dir: Optional[str] = None


@app.put("/gapscan/config", dependencies=[Depends(require_token)])
def gapscan_config_write(req: GapscanConfigWriteRequest) -> dict[str, Any]:
    """Met a jour uniquement les champs fournis (les autres restent
    inchanges) -- voir gapscan_config_store.write()."""
    _require_gapscan_available()
    fields = req.model_dump()
    profile = fields.pop("profile")
    try:
        gapscan_config_store.write(profile=profile, **fields)
    except gapscan_config_store.GapscanConfigStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return gapscan_config_store.status(profile)
```

5. Add a small helper (placed just above `_build_gapscan_clients`) for the rate-limit resolution, replacing the inline `os.environ.get("NFOGEN_C411_MIN_INTERVAL_SECONDS", "4.5")`:
```python
def _min_request_interval(profile: str) -> float:
    """Delai minimal entre deux requetes -- source de verite : le profil
    (rules.json -> tracker.min_request_interval_seconds, voir
    tracker_profile.py). L'ancienne variable d'environnement reste lisible
    comme un simple override de deploiement, UNIQUEMENT pour le profil
    c411 (c'est le seul qui existait quand cette variable a ete introduite
    -- voir AUTOMATION.md, sous-projet 4b)."""
    default = tracker_profile.min_request_interval_seconds(profile)
    if profile == "c411":
        return float(os.environ.get("NFOGEN_C411_MIN_INTERVAL_SECONDS", str(default)))
    return default
```

6. Rewrite `_build_gapscan_clients` to take `profile` and use the renamed store functions/client:
```python
def _build_gapscan_clients(profile: str) -> tuple[Any, Any, Any, dict[str, str], dict[str, str]]:
    """Construit les clients GapScan pour CE profil depuis
    gapscan_config_store (fichier ou environnement), plus les mappings de
    chemins configures (globaux, pas par profil). Leve ValueError (-> 400)
    si la configuration necessaire manque."""
    tracker_config = gapscan_config_store.effective_tracker(profile)
    if tracker_config is None:
        raise ValueError(
            f"Clé API du tracker '{profile}' non configurée "
            "(NFOGEN_C411_API_KEY si profile=c411, ou PUT /gapscan/config) : voir GAPSCAN.md."
        )
    tracker_key, tracker_base_url = tracker_config
    min_interval = _min_request_interval(profile)
    tracker_client = TorznabClient(
        tracker_key, base_url=tracker_base_url.rstrip("/") + "/api", min_interval_seconds=min_interval
    )

    sonarr_config = gapscan_config_store.effective_sonarr()
    sonarr = SonarrClient(*sonarr_config) if sonarr_config else None

    radarr_config = gapscan_config_store.effective_radarr()
    radarr = RadarrClient(*radarr_config) if radarr_config else None

    if sonarr is None and radarr is None:
        tracker_client.close()
        raise ValueError(
            "Aucune instance Sonarr ni Radarr configuree "
            "(NFOGEN_SONARR_URL/_API_KEY et/ou NFOGEN_RADARR_URL/_API_KEY, ou PUT /gapscan/config)."
        )
    return (
        tracker_client, sonarr, radarr,
        gapscan_config_store.effective_sonarr_path_mappings(),
        gapscan_config_store.effective_radarr_path_mappings(),
    )
```

7. Update `gapscan_run` to accept and thread `profile`, and rename its local `c411` variable to `tracker_client` throughout its body (every occurrence: the `try` unpacking, both `only == "movies"`/`only == "series"` error branches' `c411.close()`, and the final `not started` cleanup branch):
```python
@app.post("/gapscan/run", dependencies=[Depends(require_token)])
def gapscan_run(
    incremental: bool = Query(False),
    only: Optional[str] = Query(None),
    profile: str = Query("c411"),
) -> dict[str, str]:
    _require_gapscan_available()
    if only not in (None, "movies", "series"):
        raise HTTPException(status_code=400, detail="only doit valoir 'movies' ou 'series'.")
    try:
        tracker_client, sonarr, radarr, sonarr_path_mappings, radarr_path_mappings = (
            _build_gapscan_clients(profile)
        )
    except (ValueError, TorznabError, SonarrError, RadarrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if only == "movies" and radarr is None:
        tracker_client.close()
        if sonarr is not None:
            sonarr.close()
        raise HTTPException(status_code=400, detail="only=movies demande, mais Radarr n'est pas configure.")
    if only == "series" and sonarr is None:
        tracker_client.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(status_code=400, detail="only=series demande, mais Sonarr n'est pas configure.")

    max_age_days = float(os.environ.get("NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS", "7"))
    max_age_seconds = max_age_days * 86400 if incremental else None
    started = gapscan_runner.start(
        tracker_client, radarr=radarr, sonarr=sonarr, incremental=incremental,
        only=only, max_age_seconds=max_age_seconds,
        sonarr_path_mappings=sonarr_path_mappings, radarr_path_mappings=radarr_path_mappings,
    )
    if not started:
        tracker_client.close()
        if sonarr is not None:
            sonarr.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(status_code=409, detail="Un scan GapScan est deja en cours.")
    return {"status": "started"}
```

8. Update `gapscan_results` and `gapscan_results_export_csv` to accept `profile` and thread it to `gapscan_runner.results()`/`gapscan.genre_of()`:
```python
@app.get("/gapscan/results", dependencies=[Depends(require_token)])
def gapscan_results(
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    profile: str = Query("c411"),
) -> dict[str, Any]:
    _require_gapscan_available()
    items = gapscan_runner.results(
        status_filter=status, media_type_filter=media_type, genre_filter=genre, profile=profile
    )
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    serialized: list[dict[str, Any]] = []
    for r in page_items:
        d = asdict(r)
        d["genre"] = gapscan.genre_of(r, profile)
        serialized.append(d)
    return {"items": serialized, "total": total}


@app.get("/gapscan/results/export.csv", dependencies=[Depends(require_token)])
def gapscan_results_export_csv(
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    profile: str = Query("c411"),
) -> Response:
    _require_gapscan_available()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for r in gapscan_runner.results(
        status_filter=status, media_type_filter=media_type, genre_filter=genre, profile=profile
    ):
        writer.writerow(
            [
                r.media_type, r.title, r.year, r.season_number, r.status.value,
                gapscan.genre_of(r, profile) or "",
                r.imdb_id, r.tmdb_id, r.tvdb_id,
                r.local_quality.resolution, r.local_quality.source,
                "+".join(r.local_quality.languages),
                r.has_freeleech_alternative, r.has_double_upload_window, r.error or "",
            ]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="gapscan.csv"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Full backend suite + lint, then commit**

```bash
pytest
ruff check nfogen/ tests/
git add nfogen/api.py tests/test_api.py
git commit -m "feat: endpoints GapScan (config/run/results) acceptent un parametre profile"
```

At this point the **entire backend** is done — the full `pytest` run (all files, not just GapScan-related ones) must be green and `ruff check nfogen/ tests/` clean before starting the frontend tasks.

---

### Task 11: Frontend `types.ts` + `client.ts` — renamed fields, `profile` threading

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `GapscanConfig` (renamed fields: `tracker_configured`, `tracker_base_url`, `tracker_announce_url_configured`, plus `profile: string`), `GapscanConfigWrite` (renamed fields: `tracker_api_key?`, `tracker_base_url?`, `tracker_announce_url?`, plus `profile?: string`), `gapscanConfig(profile?: string)`, `gapscanConfigWrite(fields, profile?: string)`, `gapscanRun(incremental?, only?, profile?: string)`, `gapscanResults(opts)`/`gapscanExportCsv(opts)` gain `profile?: string` in their `opts`.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/api/client.test.ts`, find the existing `gapscanConfig`/`gapscanConfigWrite`/`gapscanRun`/`gapscanResults` tests and update their expected request bodies/URLs and mocked response shapes to the new field names, then add:

```ts
it("gapscanConfig defaults to the c411 profile", async () => {
  mockFetchOnce({ profile: "c411", tracker_configured: true } as never);
  await gapscanConfig();
  expect(lastFetchUrl()).toContain("/gapscan/config");
  expect(lastFetchUrl()).not.toContain("profile=");
});

it("gapscanConfig passes a profile query param when given", async () => {
  mockFetchOnce({ profile: "ygg", tracker_configured: false } as never);
  await gapscanConfig("ygg");
  expect(lastFetchUrl()).toContain("profile=ygg");
});

it("gapscanConfigWrite sends tracker_* field names and profile", async () => {
  mockFetchOnce({ profile: "c411", tracker_configured: true } as never);
  await gapscanConfigWrite({ tracker_api_key: "k", tracker_base_url: "https://c411.org" }, "c411");
  const body = JSON.parse(lastFetchBody());
  expect(body.tracker_api_key).toBe("k");
  expect(body.profile).toBe("c411");
});

it("gapscanRun passes a profile query param when given", async () => {
  mockFetchOnce({ status: "started" } as never);
  await gapscanRun(false, undefined, "ygg");
  expect(lastFetchUrl()).toContain("profile=ygg");
});

it("gapscanResults passes a profile query param when given", async () => {
  mockFetchOnce({ items: [], total: 0 } as never);
  await gapscanResults({ profile: "ygg" });
  expect(lastFetchUrl()).toContain("profile=ygg");
});
```

(`mockFetchOnce`/`lastFetchUrl`/`lastFetchBody` are placeholders for whatever mocking helpers `frontend/src/api/client.test.ts` already uses for its other tests in this file — read the file's existing `gapscanConfig`/`gapscanRun` tests immediately before writing these, and copy their exact mocking pattern, updating pre-existing assertions that reference `c411_api_key`/`c411_base_url`/`c411_configured`/etc. to the renamed `tracker_*` equivalents in the same pass.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — current functions don't accept a `profile` parameter, and `GapscanConfigWrite` has no `tracker_api_key` field (TypeScript compile error surfaced by Vitest's esbuild transform, or a runtime assertion failure on the sent body/URL).

- [ ] **Step 3: Update the implementation**

In `frontend/src/api/types.ts`, replace `GapscanConfig` and `GapscanConfigWrite`:

```ts
export interface GapscanConfig {
  profile: string;
  tracker_configured: boolean;
  tracker_base_url: string | null;
  sonarr_configured: boolean;
  sonarr_url: string | null;
  radarr_configured: boolean;
  radarr_url: string | null;
  sonarr_path_mappings: Record<string, string>;
  radarr_path_mappings: Record<string, string>;
  /** true si une adresse d'annonce est enregistree pour ce profil -- jamais
   * la valeur elle-meme (contient le passkey du compte). */
  tracker_announce_url_configured: boolean;
  staging_dir: string | null;
}

/** PUT /gapscan/config : chaque champ omis reste inchange cote serveur.
 * `tracker_*` sont namespaces par `profile` (voir AUTOMATION.md, sous-projet 4b). */
export interface GapscanConfigWrite {
  profile?: string;
  tracker_api_key?: string;
  tracker_base_url?: string;
  tracker_announce_url?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_path_mappings?: Record<string, string>;
  radarr_path_mappings?: Record<string, string>;
  staging_dir?: string;
}
```

In `frontend/src/api/client.ts`, update the GapScan section:

```ts
export function gapscanConfig(profile = "c411"): Promise<GapscanConfig> {
  const params = new URLSearchParams();
  if (profile !== "c411") params.set("profile", profile);
  const qs = params.toString();
  return request<GapscanConfig>(`/gapscan/config${qs ? `?${qs}` : ""}`);
}

/** Enregistre cote serveur (fichier NFOGEN_GAPSCAN_CONFIG_FILE) : seuls les
 * champs fournis changent, les autres restent inchanges. Les cles ne sont
 * jamais renvoyees, meme dans la reponse de cet appel. */
export function gapscanConfigWrite(fields: GapscanConfigWrite, profile = "c411"): Promise<GapscanConfig> {
  return request<GapscanConfig>("/gapscan/config", {
    method: "PUT",
    body: JSON.stringify({ ...fields, profile }),
  });
}

export function gapscanRun(
  incremental = false,
  only?: "movies" | "series",
  profile = "c411",
): Promise<{ status: string }> {
  const params = new URLSearchParams();
  if (incremental) params.set("incremental", "true");
  if (only) params.set("only", only);
  if (profile !== "c411") params.set("profile", profile);
  const qs = params.toString();
  return request(`/gapscan/run${qs ? `?${qs}` : ""}`, { method: "POST" });
}
```

Update `gapscanResults`/`gapscanExportCsv` option types and query building:

```ts
export function gapscanResults(
  opts: {
    status?: string;
    mediaType?: "movie" | "series";
    genre?: "anime" | "documentaire";
    page?: number;
    pageSize?: number;
    profile?: string;
  } = {},
): Promise<GapscanResultsPage> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  if (opts.profile) params.set("profile", opts.profile);
  return request<GapscanResultsPage>(`/gapscan/results?${params.toString()}`);
}

export async function gapscanExportCsv(
  opts: {
    status?: string;
    mediaType?: "movie" | "series";
    genre?: "anime" | "documentaire";
    profile?: string;
  } = {},
): Promise<Blob> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  if (opts.profile) params.set("profile", opts.profile);
  const qs = params.toString();
  const resp = await safeFetch(`${getBaseUrl()}/gapscan/results/export.csv${qs ? `?${qs}` : ""}`, {
    credentials: "include",
  });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return resp.blob();
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: all PASS.

- [ ] **Step 5: `tsc` + full frontend suite, then commit**

Note: `GapScanPage.tsx` still references the OLD field names (`c411Configured`, `config.c411_base_url`, etc.) at this point — `tsc` will fail on that file. Run `npx tsc --noEmit -p .` and confirm the ONLY errors are in `GapScanPage.tsx`/`GapScanPage.test.tsx` (fixed in Task 12), then commit this task alone:

```bash
cd frontend && npx vitest run src/api/client.test.ts
git add src/api/types.ts src/api/client.ts src/api/client.test.ts
git commit -m "feat: client API gapscan generique (tracker_* + parametre profile)"
```

---

### Task 12: `ProfileContext` — shared active-profile state

**Files:**
- Create: `frontend/src/ProfileContext.tsx`
- Test: `frontend/src/ProfileContext.test.tsx`

**Interfaces:**
- Consumes: `listAllProfiles()`, `readManagedProfile(name)` (existing, `../api/client`).
- Produces (consumed by Tasks 13, 14, 15):
  - `<ProfileProvider>` (wraps the app once, in `App.tsx`)
  - `useProfile(): { profile: string; setProfile: (p: string) => void; profiles: Record<string, string[]>; displayName: string }`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/ProfileContext.test.tsx`. Read `frontend/src/pages/GeneratePage.test.tsx` first for this project's established `vi.mock("./api/client", ...)` pattern and mirror it exactly (module path adjusted since this file lives at `src/` root, not `src/pages/`):

```tsx
import { render, renderHook, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileProvider, useProfile } from "./ProfileContext";
import { listAllProfiles, readManagedProfile } from "./api/client";

vi.mock("./api/client");

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"], ygg: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  } as never);
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <ProfileProvider>{children}</ProfileProvider>;
}

describe("useProfile", () => {
  it("defaults to c411 when nothing was previously chosen", async () => {
    const { result } = renderHook(() => useProfile(), { wrapper });
    await waitFor(() => expect(result.current.displayName).toBe("C411"));
    expect(result.current.profile).toBe("c411");
  });

  it("loads the profile list", async () => {
    const { result } = renderHook(() => useProfile(), { wrapper });
    await waitFor(() => expect(result.current.profiles).toEqual({ c411: ["video"], ygg: ["video"] }));
  });

  it("falls back to the profile name when display_name is not declared", async () => {
    vi.mocked(readManagedProfile).mockResolvedValue({ name: "ygg", rules: {}, templates: {} } as never);
    const { result } = renderHook(() => useProfile(), { wrapper });
    act(() => result.current.setProfile("ygg"));
    await waitFor(() => expect(result.current.displayName).toBe("ygg"));
  });

  it("persists the chosen profile across remounts (localStorage)", async () => {
    const { result, unmount } = renderHook(() => useProfile(), { wrapper });
    await waitFor(() => expect(result.current.profile).toBe("c411"));
    act(() => result.current.setProfile("ygg"));
    unmount();
    const { result: result2 } = renderHook(() => useProfile(), { wrapper });
    expect(result2.current.profile).toBe("ygg");
  });

  it("throws a clear error when used outside the provider", () => {
    expect(() => renderHook(() => useProfile())).toThrow(/ProfileProvider/);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/ProfileContext.test.tsx`
Expected: FAIL with `Cannot find module './ProfileContext'`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/ProfileContext.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { listAllProfiles, readManagedProfile } from "./api/client";

const STORAGE_KEY = "nfogen.activeProfile";

interface ProfileContextValue {
  profile: string;
  setProfile: (profile: string) => void;
  profiles: Record<string, string[]>;
  /** Nom lisible du profil actif (rules.json -> tracker.display_name),
   * repli sur le nom du profil lui-meme si non declare. */
  displayName: string;
}

const ProfileContext = createContext<ProfileContextValue | null>(null);

/** Etat du "profil actif" partage par toute l'application (entete de
 * App.tsx, page GapScan, page Generer) : "je charge un profil, il
 * definit les regles, le reste de l'appli marche pareil" (retour
 * utilisateur, 2026-08-29) -- un seul selecteur global, pas un par page.
 * Persiste le dernier choix (localStorage) pour ne pas le reperdre a
 * chaque rechargement ; non bloquant si le stockage est indisponible
 * (navigation privee...). */
export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setProfileState] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || "c411";
    } catch {
      return "c411";
    }
  });
  const [profiles, setProfiles] = useState<Record<string, string[]>>({});
  const [displayName, setDisplayName] = useState(profile);

  useEffect(() => {
    listAllProfiles()
      .then(setProfiles)
      .catch(() => setProfiles({}));
  }, []);

  useEffect(() => {
    readManagedProfile(profile)
      .then((p) => setDisplayName(p.rules.tracker?.display_name ?? profile))
      .catch(() => setDisplayName(profile));
  }, [profile]);

  function setProfile(next: string) {
    setProfileState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // stockage indisponible : le choix ne survit juste pas a un rechargement.
    }
  }

  return (
    <ProfileContext.Provider value={{ profile, setProfile, profiles, displayName }}>
      {children}
    </ProfileContext.Provider>
  );
}

export function useProfile(): ProfileContextValue {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error("useProfile doit être utilisé à l'intérieur de <ProfileProvider>.");
  return ctx;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/ProfileContext.test.tsx`
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/ProfileContext.tsx src/ProfileContext.test.tsx
git commit -m "feat: ProfileContext - etat du profil actif partage par toute l'application"
```

---

### Task 13: `App.tsx` + `GeneratePage.tsx` — global profile selector in the header

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/pages/GeneratePage.tsx`
- Test: `frontend/src/App.test.tsx` (create if it doesn't exist), `frontend/src/pages/GeneratePage.test.tsx`

**Interfaces:**
- Consumes: `useProfile()`, `<ProfileProvider>` (Task 12).
- Produces: the app's `<header>` carries the one-and-only profile `<select>`; `GeneratePage.tsx` no longer owns its own profile state.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/pages/GeneratePage.test.tsx`, find every existing render call and wrap it with `<ProfileProvider>` (since the page now requires the context — read the file's existing render helper, e.g. a local `renderPage()` function, and add the wrapper there once rather than at every call site). Add:

```tsx
it("resets the selected category when the active profile changes", async () => {
  // ... rend GeneratePage (via le helper de rendu du fichier) avec le
  // profil "c411" actif, choisit une categorie, puis change le profil
  // actif via useProfile() dans un composant de test enveloppant, et
  // verifie que la categorie selectionnee est revenue a "" (auto-detectee).
});
```

(This test's exact body depends on the render helper already established in `frontend/src/pages/GeneratePage.test.tsx` — read that file's existing category-selection test immediately before writing this one and mirror its setup for selecting a category, then drive a profile change through a `useProfile()`-consuming wrapper component and assert the category `<select>` reverts to its default option.)

If `frontend/src/App.test.tsx` does not exist yet, create it with a minimal smoke test (this project's other page test files establish the `render`/`screen` import pattern — mirror it):

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { listAllProfiles, readManagedProfile } from "./api/client";

vi.mock("./api/client");

it("renders one profile selector in the header, not per-page", async () => {
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  } as never);
  render(
    <MemoryRouter initialEntries={["/gapscan"]}>
      <App />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("combobox", { name: /profil/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/App.test.tsx src/pages/GeneratePage.test.tsx`
Expected: FAIL — `useProfile` throws (`GeneratePage` not wrapped in `<ProfileProvider>` yet in its tests), and `App.tsx` has no profile `<select>` in its header yet.

- [ ] **Step 3: Update the implementation**

In `frontend/src/App.tsx`, split the component so `useProfile()` (which needs to run inside the provider) is called from a child, and add the header selector + generic nav label:

```tsx
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import GapScanPage from "./pages/GapScanPage";
import GeneratePage from "./pages/GeneratePage";
import ProfilesListPage from "./pages/ProfilesListPage";
import ProfileEditorPage from "./pages/ProfileEditorPage";
import SettingsPage from "./pages/SettingsPage";
import { ProfileProvider, useProfile } from "./ProfileContext";

function navClass({ isActive }: { isActive: boolean }) {
  return `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? "bg-accent text-surface" : "text-ink-dim hover:bg-surface-2 hover:text-ink"
  }`;
}

function ProfileSelect() {
  const { profile, setProfile, profiles } = useProfile();
  return (
    <select
      value={profile}
      onChange={(e) => setProfile(e.target.value)}
      aria-label="Profil actif"
      className="rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink"
    >
      {Object.keys(profiles).length === 0 && <option value="c411">c411</option>}
      {Object.keys(profiles).map((p) => (
        <option key={p} value={p}>
          {p}
        </option>
      ))}
    </select>
  );
}

function AppShell() {
  const { displayName } = useProfile();
  return (
    <div className="min-h-screen bg-bg font-sans text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3">
          <span className="font-display text-lg font-bold text-ink">
            nfogen<span className="font-mono text-sm text-accent">.nfo</span>
          </span>
          <nav className="flex gap-1">
            <NavLink to="/" className={navClass} end>
              Générer
            </NavLink>
            <NavLink to="/profils" className={navClass}>
              Profils
            </NavLink>
            <NavLink to="/gapscan" className={navClass}>
              Scan {displayName}
            </NavLink>
            <NavLink to="/settings" className={navClass}>
              Réglages
            </NavLink>
          </nav>
          <ProfileSelect />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <ErrorBoundary key={useLocation().pathname}>
          <Routes>
            <Route path="/" element={<GeneratePage />} />
            <Route path="/profils" element={<ProfilesListPage />} />
            <Route path="/profiles/new" element={<ProfileEditorPage mode="create" />} />
            <Route path="/profiles/:name" element={<ProfileEditorPage mode="edit" />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/gapscan" element={<GapScanPage />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ProfileProvider>
      <AppShell />
    </ProfileProvider>
  );
}
```

In `frontend/src/pages/GeneratePage.tsx`:

1. Remove the local `profiles`/`profile` state and their `listAllProfiles()` effect (lines shown in the excerpt read earlier: `const [profiles, setProfiles] = useState...`, `const [profile, setProfile] = useState("c411")`, and the `useEffect(() => { listAllProfiles()... }, [])`).
2. Add the import and consume the context instead:
```ts
import { useProfile } from "../ProfileContext";
```
```ts
  const { profile, profiles } = useProfile();
```
3. Add an effect that reproduces the old "changing profile resets category" behavior (previously inlined in the removed `<select>`'s `onChange`):
```ts
  useEffect(() => {
    setCategory("");
  }, [profile]);
```
4. Remove the "Profil" `<label>`/`<select>` block from the JSX (shown in the excerpt read earlier, lines 222–239) — keep the "Catégorie" label/select as the sole child of that `grid grid-cols-2` container, changed to a single column since there's only one field left:
```tsx
      <div className="rounded-md border border-line bg-surface p-4">
        <label className="block text-sm font-medium text-ink-dim">
          Catégorie
          <select
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">(auto-détectée depuis le fichier)</option>
            {categories.map((c) => (
              ... (contenu existant inchange, ne pas retaper — seul le conteneur parent change)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/App.test.tsx src/pages/GeneratePage.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

Note: `GapScanPage.tsx` (Task 14) still has its own now-redundant local profile handling at this point and doesn't yet render inside a route that necessarily has `<ProfileProvider>` in its own test file — `tsc`/its own test suite may show unrelated pre-existing failures until Task 14 lands. Confirm with `npx tsc --noEmit -p .` that no NEW errors appear outside `GapScanPage.tsx`/its test, then commit this task alone:

```bash
cd frontend
npx vitest run src/App.test.tsx src/pages/GeneratePage.test.tsx
git add src/App.tsx src/App.test.tsx src/pages/GeneratePage.tsx src/pages/GeneratePage.test.tsx
git commit -m "feat: selecteur de profil global dans l'entete, Generer consomme ProfileContext"
```

---

### Task 14: `GapScanPage.tsx` consumes the shared profile context

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Test: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `useProfile()` (Task 12), `gapscanConfig(profile)`/`gapscanConfigWrite(fields, profile)`/`gapscanRun(incremental, only, profile)`/`gapscanResults({..., profile})`/`gapscanExportCsv({..., profile})` (Task 11).

- [ ] **Step 1: Write the failing tests**

In `frontend/src/pages/GapScanPage.test.tsx`, wrap every existing render call with `<ProfileProvider>` (same as Task 13 did for `GeneratePage.test.tsx` — read that file's render helper first and mirror the same wrapping approach here). Update every existing mock/assertion referencing `c411_configured`/`c411_base_url`/`c411_announce_url_configured`/`c411ApiKey`-style state or the literal text `"C411"`/`"Scan C411"` to the generic equivalents. Add:

```tsx
it("shows the tracker's display_name from the shared profile context, not a hard-coded name", async () => {
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "Mon Tracker" } }, templates: {},
  } as never);
  render(<GapScanPage />, { wrapper: ProfileProviderWrapper });
  expect(await screen.findByText(/Scan Mon Tracker/)).toBeInTheDocument();
});

it("has no profile selector of its own (lives in the app header, Task 13)", async () => {
  render(<GapScanPage />, { wrapper: ProfileProviderWrapper });
  expect(screen.queryByLabelText(/profil \(tracker\)/i)).not.toBeInTheDocument();
});
```

(`ProfileProviderWrapper` is a placeholder for whatever wrapper helper Task 13 established in `GeneratePage.test.tsx` — reuse the exact same one, extracted to a shared test helper if it wasn't already.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: FAIL — the page still renders the literal text "Scan C411" and its own local profile `<select>`.

- [ ] **Step 3: Update the implementation**

In `frontend/src/pages/GapScanPage.tsx`:

1. Remove `useState`-based `profiles`/`profile` and the local profile `<select>` — this page never introduces its own profile state or control; it only reads the global one.
2. Add the import and consume the context:
```ts
import { useProfile } from "../ProfileContext";
```
```ts
  const { profile, displayName: trackerDisplayName } = useProfile();
```
3. Thread `profile` into the existing config-loading effect, `loadResults`, `handleRun`, `handleSaveConfig`, `handleExportCsv` — identical wiring to what was drafted for the (now superseded) local-selector version of this task:
```ts
    gapscanConfig(profile)
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setTrackerBaseUrl(c.tracker_base_url ?? "");
        setSonarrPathMappings(c.sonarr_path_mappings);
        setRadarrPathMappings(c.radarr_path_mappings);
        setStagingDir(c.staging_dir ?? "");
        if (!c.tracker_configured || (!c.sonarr_configured && !c.radarr_configured)) {
          setShowConfigForm(true);
        }
      });
```
(add `profile` to that effect's dependency array, and to the `[filter, typeGenreFilter, page]` effect that calls `loadResults()` — becomes `[filter, typeGenreFilter, page, profile]`)
```ts
      const res = await gapscanResults({
        status: filter || undefined,
        mediaType: selectedTypeGenre.mediaType,
        genre: selectedTypeGenre.genre,
        page,
        pageSize: PAGE_SIZE,
        profile,
      });
```
```ts
      await gapscanRun(hasPreviousScan && incremental, only || undefined, profile);
```
```ts
      const fields: GapscanConfigWrite = {};
      if (sonarrUrl.trim()) fields.sonarr_url = sonarrUrl.trim();
      if (sonarrApiKey.trim()) fields.sonarr_api_key = sonarrApiKey.trim();
      if (radarrUrl.trim()) fields.radarr_url = radarrUrl.trim();
      if (radarrApiKey.trim()) fields.radarr_api_key = radarrApiKey.trim();
      if (trackerApiKey.trim()) fields.tracker_api_key = trackerApiKey.trim();
      if (trackerBaseUrl.trim()) fields.tracker_base_url = trackerBaseUrl.trim();
      if (trackerAnnounceUrl.trim()) fields.tracker_announce_url = trackerAnnounceUrl.trim();
      if (stagingDir.trim()) fields.staging_dir = stagingDir.trim();
      fields.sonarr_path_mappings = sonarrPathMappings;
      fields.radarr_path_mappings = radarrPathMappings;

      const updated = await gapscanConfigWrite(fields, profile);
```
```ts
      const blob = await gapscanExportCsv({
        status: filter || undefined,
        mediaType: selectedTypeGenre.mediaType,
        genre: selectedTypeGenre.genre,
        profile,
      });
```
4. Rename every `c411*` state variable and form field to `tracker*`: `c411ApiKey`→`trackerApiKey`, `c411BaseUrl`→`trackerBaseUrl`, `c411AnnounceUrl`→`trackerAnnounceUrl`, and their setters, throughout the component.
5. Replace hard-coded "C411" text with `trackerDisplayName`, identically to the wording drafted earlier: the `<h1>`/description paragraph, the "Clé API … non configurée" banner, "Configuration (Sonarr, Radarr, …)", "URL de base …", "Clé API …", "Adresse d'annonce …" labels.
6. Parameterize `STATUS_LABEL` into a `statusLabel(status, trackerName)` function and move `FILTERS` into the component body (both depend on `trackerDisplayName`), exactly as drafted earlier:
```ts
function statusLabel(status: GapStatus, trackerName: string): string {
  const labels: Record<GapStatus, string> = {
    absent: `Absent de ${trackerName}`,
    quality_gap: "Qualité supérieure disponible",
    language_gap: `Langue manquante sur ${trackerName}`,
    covered: "Déjà couvert",
    error: `Non vérifié (erreur ${trackerName})`,
  };
  return labels[status];
}
```
```ts
  const FILTERS: { value: GapStatus | ""; label: string }[] = [
    { value: "", label: "Tous les statuts" },
    { value: "absent", label: statusLabel("absent", trackerDisplayName) },
    { value: "quality_gap", label: statusLabel("quality_gap", trackerDisplayName) },
    { value: "language_gap", label: statusLabel("language_gap", trackerDisplayName) },
    { value: "covered", label: statusLabel("covered", trackerDisplayName) },
    { value: "error", label: statusLabel("error", trackerDisplayName) },
  ];
```
(update the results-table badge's `{STATUS_LABEL[r.status]}` to `{statusLabel(r.status, trackerDisplayName)}`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd frontend
npx vitest run src/pages/GapScanPage.test.tsx
git add src/pages/GapScanPage.tsx src/pages/GapScanPage.test.tsx
git commit -m "feat: page GapScan consomme le profil actif partage (ProfileContext)"
```

---

### Task 15: `UploadPrepPanel.tsx` — per-media profile override

**Files:**
- Modify: `frontend/src/components/UploadPrepPanel.tsx`
- Test: `frontend/src/components/UploadPrepPanel.test.tsx`

**Interfaces:**
- Consumes: `useProfile()` (Task 12) for the default value + the profile list to populate its own override `<select>`.
- Produces: the panel calls `prepareUploadPreview`/its commit function with a LOCAL `profile` value, defaulting to the app's active profile but changeable just for this one upload (user request, 2026-08-29 — "sélection de profil unitaire par média").

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/UploadPrepPanel.test.tsx`, wrap every existing render call with `<ProfileProvider>` (same helper pattern as Tasks 13/14). Add:

```tsx
it("defaults to the globally active profile", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue([]);
  render(
    <UploadPrepPanel localPaths={["/media/Movie.mkv"]} title="Movie" onClose={() => {}} />,
    { wrapper: ProfileProviderWrapper },
  );
  await waitFor(() => expect(prepareUploadPreview).toHaveBeenCalledWith(
    ["/media/Movie.mkv"], "c411", "Movie",
  ));
});

it("lets the user override the profile for this one upload without changing the global active profile", async () => {
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"], ygg: ["video"] });
  vi.mocked(prepareUploadPreview).mockResolvedValue([]);
  render(
    <UploadPrepPanel localPaths={["/media/Movie.mkv"]} title="Movie" onClose={() => {}} />,
    { wrapper: ProfileProviderWrapper },
  );
  const select = await screen.findByLabelText(/profil pour cet upload/i);
  fireEvent.change(select, { target: { value: "ygg" } });
  await waitFor(() => expect(prepareUploadPreview).toHaveBeenCalledWith(
    ["/media/Movie.mkv"], "ygg", "Movie",
  ));
});
```

(`ProfileProviderWrapper`, `screen`, `fireEvent`, `waitFor` per this file's existing imports/conventions — read the file's current top-of-file setup before writing these two, and reuse rather than reintroduce a different pattern.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: FAIL — `useProfile()` throws (no provider in the existing render calls yet), and there's no "profil pour cet upload" control.

- [ ] **Step 3: Update the implementation**

In `frontend/src/components/UploadPrepPanel.tsx`:

1. Add the import and read the global default:
```ts
import { useProfile } from "../ProfileContext";
```
```ts
  const { profile: globalProfile, profiles } = useProfile();
  const [profile, setProfile] = useState(globalProfile);
```
(`UploadPrepPanelProps` does NOT gain a `profile` field — the panel is self-sufficient via context, nothing new for `GapScanPage.tsx` to pass.)

2. Replace every call to `prepareUploadPreview(localPaths, ...)` / the commit function's profile argument (currently a hard-coded `"c411"` or the client function's own default — find the exact existing call sites, `loadPreview()` and the commit handler) with the local `profile` state instead.

3. Make changing the override re-trigger the preview, mirroring how the existing title-override "Recalculer" flow already calls `loadPreview()`:
```ts
  function handleProfileChange(next: string) {
    setProfile(next);
    loadPreview(titleOverride, next);
  }
```
(adjust `loadPreview`'s signature to accept an optional profile override parameter, defaulting to the current `profile` state, consistent with how it already accepts an optional title override — read the existing `loadPreview` definition first to match its exact current parameter style before adding this one.)

4. Add the override `<select>` in the panel's header area, next to the title field:
```tsx
        <label className="block text-sm font-medium text-ink-dim">
          Profil pour cet upload
          <select
            aria-label="Profil pour cet upload"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={profile}
            onChange={(e) => handleProfileChange(e.target.value)}
          >
            {Object.keys(profiles).length === 0 && <option value="c411">c411</option>}
            {Object.keys(profiles).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Full frontend suite + `tsc`, then commit**

```bash
cd frontend
npx vitest run
npx tsc --noEmit -p .
git add src/components/UploadPrepPanel.tsx src/components/UploadPrepPanel.test.tsx
git commit -m "feat: UploadPrepPanel - profil de l'upload independant du profil actif global"
```

At this point, run the full backend suite (`pytest`, `ruff check nfogen/ tests/`) AND the full frontend suite (`npx vitest run`, `npx tsc --noEmit -p .`) one final time together — this is the "merged result" check before handing off to `finishing-a-development-branch`.

---

## Post-implementation documentation (not a TDD task, do last)

- [ ] Update `AUTOMATION.md`'s "Sous-projet 4b" section: change its status from "En conception" to "Livré (\<date\>)", and add a short "Écarts par rapport à la conception" note listing the two scope cuts from Global Constraints above (no Tracker tab, `audio_language_codes` instead of `multi_language_whitelist`) plus a link to this plan file, matching the pattern used for sous-projets 1–4.
- [ ] Update the sous-projet 5 row's "État" in the decomposition table from "À concevoir (dépend du 4b)" to "À concevoir" (4b no longer blocking).
- [ ] Add a `CHANGELOG.md` `### Modifié`/`### Corrigé` entry: per-profile tracker credentials, `tracker` section in `rules.json`, `c411_client.py` → `torznab_client.py` rename, global profile selector in the app header (`ProfileContext`, replacing the hard-coded "Scan C411" nav label and each page's own ad-hoc profile state), and the per-media profile override in "Préparer l'upload".
- [ ] `.env.example`: confirm `NFOGEN_C411_API_KEY`/`NFOGEN_C411_BASE_URL`/`NFOGEN_C411_MIN_INTERVAL_SECONDS` are still documented as valid (they remain legacy-compatible env vars for `profile=c411` specifically) — add a one-line note if not already clear that they apply only to that profile.
- [ ] `GAPSCAN.md`: update the "Catégories" section (categories now live in the profile, not hard-coded) and any mention of `c411_client.py`/`C411Client` to `torznab_client.py`/`TorznabClient`.
