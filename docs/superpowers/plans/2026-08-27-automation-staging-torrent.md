# AUTOMATION sous-projet 2 : mise en scène + génération du `.torrent` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deux briques réutilisables et testées : mettre un fichier à disposition sans jamais toucher l'original (hardlink, repli sur copie), et construire un `.torrent` privé conforme aux règles C411 à partir d'un contenu mis en scène.

**Architecture:** `nfogen/file_staging.py` (pur filesystem, aucune dépendance externe) et `nfogen/torrent_builder.py` (utilise `torf`) sont deux modules indépendants, sans dépendance l'un envers l'autre — le second consomme la sortie du premier par convention (un chemin), pas par appel direct. Config étendue (`gapscan_config_store.py`) avec deux nouveaux champs traités selon leur sensibilité : `c411_announce_url` comme un secret (jamais renvoyé en clair), `staging_dir` comme une simple donnée de config (renvoyé tel quel, comme les URLs Sonarr/Radarr).

**Tech Stack:** Python 3.10+ (`os.link`/`shutil.copy2`, `pathlib`), [`torf`](https://github.com/rndusr/torf) (création de `.torrent`), FastAPI, React + TypeScript, pytest, Vitest.

**Spec:** [AUTOMATION.md](../../../AUTOMATION.md), section "Sous-projet 2 : Mise en scène du fichier (hardlink/copie) + génération du `.torrent`".

## Global Constraints

- Le fichier média original n'est **jamais** modifié, déplacé ou supprimé — `file_staging.py` ne fait que créer une nouvelle entrée (hardlink) ou une copie séparée.
- Barème de taille de pièce C411 (jamais "Auto") : `< 1 Go → 1 Mo`, `< 2 Go → 2 Mo`, `< 3 Go → 4 Mo`, `< 8 Go → 8 Mo`, `≥ 8 Go → 16 Mo`.
- Tout `.torrent` produit est **privé** (`private=True`) avec une seule adresse d'annonce (celle du compte).
- `c411_announce_url` est un secret (contient le passkey, le régénérer casse tous les seeds en cours) : jamais renvoyé en clair par une lecture API, même traitement que `c411_api_key`. `staging_dir` n'est pas un secret : renvoyé tel quel, comme `sonarr_url`/`radarr_url`.
- Le nom de sortie voulu (nommage réel) n'est **pas** calculé dans ce sous-projet — accepté en paramètre explicite, calculé par le sous-projet 3.
- `torf` va dans un extra pip dédié `automation`, **pas** `gapscan` (GapScan seul garde son empreinte minimale).
- TDD strict : test en échec confirmé (RED) avant chaque implémentation. `pytest -q` et `ruff check .` propres avant chaque commit ; `npx vitest run`, `npx tsc --noEmit -p tsconfig.app.json` (**pas** `tsc --noEmit` seul — vérifié en sous-projet 1, la racine `tsconfig.json` n'a pas de `include` et ne vérifie rien), `npm run lint` propres avant chaque commit touchant `frontend/`.
- Style du projet : commentaires en français, denses sur le "pourquoi" pas le "quoi", jamais de TODO laissé dans le code.

---

### Task 1: Dépendance `torf` (extra `automation`)

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `torf` importable dans l'environnement de dev et en CI. Consommé par la Task 3.

- [ ] **Step 1: Ajouter l'extra dans `pyproject.toml`**

Après le bloc `gapscan = [...]` (ligne ~42) :

```toml
gapscan = [
    "httpx>=0.27",  # c411_client.py / sonarr_client.py / radarr_client.py (voir GAPSCAN.md)
]
automation = [
    "torf>=4.0",  # torrent_builder.py (voir AUTOMATION.md, sous-projet 2) -- extra separe de gapscan, pas necessaire pour la seule detection de gap
]
```

- [ ] **Step 2: Mettre à jour la CI**

Dans `.github/workflows/ci.yml`, la ligne d'installation (déjà `.[api,gapscan,dev]` depuis l'audit du 2026-08-27) devient :

```yaml
      - name: Installer nfogen (+ extras api, gapscan, automation et dev)
        run: pip install -e ".[api,gapscan,automation,dev]"
```

- [ ] **Step 3: Installer localement**

Run: `pip install -e ".[api,gapscan,automation,dev]"` (depuis le venv du projet)
Expected: `torf` installé sans erreur.

- [ ] **Step 4: Vérifier l'import**

Run: `python -c "import torf; print(torf.__version__)"`
Expected: affiche un numéro de version, pas d'erreur.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml
git commit -m "AUTOMATION sous-projet 2 (1/7) : ajoute torf (extra automation)

Extra pip dedie, separe de gapscan -- GapScan seul (detection de gap
sans automatisation d'upload) n'en a pas besoin. Voir AUTOMATION.md."
```

---

### Task 2: `nfogen/file_staging.py` — mise en scène (hardlink, repli sur copie)

**Files:**
- Create: `nfogen/file_staging.py`
- Test: `tests/test_file_staging.py`

**Interfaces:**
- Produces: `stage_file(source_path: str, target_path: str) -> str`, `stage_files(source_paths: list[str], target_dir: str, names: list[str]) -> list[str]`. Consommés plus tard par le sous-projet 3 (nommage réel) — pas encore appelés depuis `gapscan.py`/`api.py` dans ce sous-projet.

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_file_staging.py` :

```python
"""Tests de nfogen.file_staging (mise en scene avant creation d'un
.torrent -- jamais le fichier original, voir AUTOMATION.md, sous-projet 2)."""
from __future__ import annotations

import errno
import os

import pytest

from nfogen.file_staging import stage_file, stage_files


def test_stage_file_creates_a_hardlink_when_possible(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"

    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_text() == "contenu"
    # meme inode = hardlink reel, pas une copie (0 octet supplementaire)
    assert target.stat().st_ino == source.stat().st_ino


def test_stage_file_falls_back_to_copy_on_exdev(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_text() == "contenu"


def test_stage_file_reraises_other_os_errors(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "link", fake_link)
    with pytest.raises(OSError):
        stage_file(str(source), str(target))


def test_stage_files_stages_each_source_under_its_own_name(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_text("un")
    src2 = tmp_path / "e02.mkv"
    src2.write_text("deux")
    target_dir = tmp_path / "staged" / "Release.Name"

    results = stage_files([str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"])

    assert results == [str(target_dir / "E01.mkv"), str(target_dir / "E02.mkv")]
    assert (target_dir / "E01.mkv").read_text() == "un"
    assert (target_dir / "E02.mkv").read_text() == "deux"
```

Le premier test (`test_stage_file_creates_a_hardlink_when_possible`) couvre déjà la création des dossiers parents (`target` y est sous un sous-dossier `staged/` inexistant) — pas de test séparé dédié à ce cas.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_file_staging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.file_staging'`

- [ ] **Step 3: Write the implementation**

Créer `nfogen/file_staging.py` :

```python
"""Mise en scene de fichiers avant creation d'un .torrent -- jamais le
fichier original (voir AUTOMATION.md, sous-projet 2) : cree un hardlink
sous le nom voulu (0 octet supplementaire), avec repli automatique sur
une copie complete si la cible n'est pas sur le meme systeme de fichiers
(EXDEV) -- meme detection que celle deja utilisee ailleurs dans le
projet pour ce cas.

Important pour les consommateurs de ce module (ex. torrent_builder.py) :
un hardlink partage le meme contenu que l'original -- n'ECRIRE JAMAIS
dans un chemin mis en scene, seulement le lire.
"""
from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path


def stage_file(source_path: str, target_path: str) -> str:
    """Met `source_path` a disposition sous `target_path` : hardlink si
    possible, copie complete en repli (systemes de fichiers differents).
    Cree les dossiers parents de `target_path` si besoin. Renvoie
    `target_path`."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source_path, target_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copy2(source_path, target_path)
    return target_path


def stage_files(source_paths: list[str], target_dir: str, names: list[str]) -> list[str]:
    """Met en scene plusieurs fichiers d'un coup (ex. un pack de saison) --
    un nom de sortie par source, meme ordre. Renvoie les chemins finaux,
    dans le meme ordre."""
    return [
        stage_file(source, str(Path(target_dir) / name))
        for source, name in zip(source_paths, names)
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_file_staging.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint**

Run: `ruff check nfogen/file_staging.py tests/test_file_staging.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add nfogen/file_staging.py tests/test_file_staging.py
git commit -m "AUTOMATION sous-projet 2 (2/7) : nfogen/file_staging.py

Hardlink avec repli automatique sur copie (EXDEV) -- jamais le
fichier original modifie. stage_file (un fichier) + stage_files
(plusieurs, pour un pack de saison). Voir AUTOMATION.md."
```

---

### Task 3: `nfogen/torrent_builder.py` — barème de taille de pièce + création via `torf`

**Files:**
- Create: `nfogen/torrent_builder.py`
- Test: `tests/test_torrent_builder.py`

**Interfaces:**
- Consumes: `torf.Torrent` (constructeur `path=`, `trackers=`, `private=`, `piece_size=` ; méthodes `.generate()`, `.write(chemin)`, classmethod `.read(chemin)`).
- Produces: `piece_size_for(total_bytes: int) -> int`, `build_torrent(staged_path: str, announce_url: str, output_path: str) -> None`. Pas encore appelés depuis `gapscan.py`/`api.py` dans ce sous-projet.

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_torrent_builder.py` :

```python
"""Tests de nfogen.torrent_builder (creation du .torrent final, regles
C411 -- voir AUTOMATION.md, sous-projet 2)."""
from __future__ import annotations

import torf

from nfogen.torrent_builder import build_torrent, piece_size_for

_MO = 1024**2
_GO = 1024**3


def test_piece_size_for_under_1go():
    assert piece_size_for(500 * _MO) == 1 * _MO


def test_piece_size_for_under_2go():
    assert piece_size_for(1500 * _MO) == 2 * _MO


def test_piece_size_for_under_3go():
    assert piece_size_for(int(2.5 * _GO)) == 4 * _MO


def test_piece_size_for_under_8go():
    assert piece_size_for(5 * _GO) == 8 * _MO


def test_piece_size_for_8go_or_more():
    assert piece_size_for(10 * _GO) == 16 * _MO


def test_piece_size_for_exactly_at_a_threshold_uses_the_next_tier():
    # "< 1 Go" exclut 1 Go pile -- tombe dans le palier suivant.
    assert piece_size_for(1 * _GO) == 2 * _MO


def test_build_torrent_creates_a_valid_private_torrent(tmp_path):
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * 100)
    output = tmp_path / "output.torrent"

    build_torrent(str(staged), "https://c411.org/announce/SECRET", str(output))

    assert output.is_file()
    reloaded = torf.Torrent.read(str(output))
    assert reloaded.private is True
    assert any("https://c411.org/announce/SECRET" in tier for tier in reloaded.trackers)
    assert reloaded.piece_size == piece_size_for(100)


def test_build_torrent_supports_a_directory_for_multi_file_packs(tmp_path):
    staged_dir = tmp_path / "Release.Name"
    staged_dir.mkdir()
    (staged_dir / "E01.mkv").write_bytes(b"x" * 100)
    (staged_dir / "E02.mkv").write_bytes(b"y" * 100)
    output = tmp_path / "output.torrent"

    build_torrent(str(staged_dir), "https://c411.org/announce/SECRET", str(output))

    assert output.is_file()
    reloaded = torf.Torrent.read(str(output))
    assert reloaded.private is True
    assert reloaded.piece_size == piece_size_for(200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_torrent_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nfogen.torrent_builder'`

- [ ] **Step 3: Write the implementation**

Créer `nfogen/torrent_builder.py` :

```python
"""Construction du fichier .torrent final, conforme aux regles C411 (voir
AUTOMATION.md, sous-projet 2) : bareme de taille de piece par poids
total, tracker prive, une seule adresse d'annonce (celle du compte,
jamais journalisee/exposee -- voir gapscan_config_store.py).
"""
from __future__ import annotations

from pathlib import Path

import torf

# Bareme C411 (voir AUTOMATION.md) : jamais "Auto", toujours une valeur
# explicite -- un .torrent de plus de 16 Mo risque d'etre rejete/mal gere.
_PIECE_SIZE_TABLE: list[tuple[int, int]] = [
    (1 * 1024**3, 1 * 1024**2),   # < 1 Go -> 1 Mo
    (2 * 1024**3, 2 * 1024**2),   # < 2 Go -> 2 Mo
    (3 * 1024**3, 4 * 1024**2),   # < 3 Go -> 4 Mo
    (8 * 1024**3, 8 * 1024**2),   # < 8 Go -> 8 Mo
]
_DEFAULT_PIECE_SIZE = 16 * 1024**2  # >= 8 Go -> 16 Mo


def piece_size_for(total_bytes: int) -> int:
    """Taille de piece (en octets) recommandee par C411 pour un contenu de
    `total_bytes`. Fonction pure, testable sans fichier reel."""
    for threshold, size in _PIECE_SIZE_TABLE:
        if total_bytes < threshold:
            return size
    return _DEFAULT_PIECE_SIZE


def _total_size(path: str) -> int:
    p = Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def build_torrent(staged_path: str, announce_url: str, output_path: str) -> None:
    """Construit un .torrent prive a partir de `staged_path` (fichier ou
    dossier -- un dossier pour un pack multi-fichiers -- deja mis en scene
    par file_staging.py, jamais le fichier original) et l'ecrit dans
    `output_path`. Taille de piece choisie selon le bareme C411 a partir
    du poids total du contenu."""
    total_bytes = _total_size(staged_path)
    torrent = torf.Torrent(
        path=staged_path,
        trackers=[announce_url],
        private=True,
        piece_size=piece_size_for(total_bytes),
    )
    torrent.generate()
    torrent.write(output_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_torrent_builder.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint**

Run: `ruff check nfogen/torrent_builder.py tests/test_torrent_builder.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add nfogen/torrent_builder.py tests/test_torrent_builder.py
git commit -m "AUTOMATION sous-projet 2 (3/7) : nfogen/torrent_builder.py

Bareme de taille de piece C411 (fonction pure, testee sans I/O) +
construction du .torrent via torf (prive, un seul tracker). API torf
verifiee dans son code source avant d'ecrire ce module (Torrent(path=,
trackers=, private=, piece_size=), .generate(), .write(), .read()
classmethod). Voir AUTOMATION.md."
```

---

### Task 4: `nfogen/gapscan_config_store.py` — `c411_announce_url` + `staging_dir`

**Files:**
- Modify: `nfogen/gapscan_config_store.py`
- Test: `tests/test_gapscan_config_store.py`
- Test: `tests/test_api.py` (un test existant en dict exact casse dès cette task — voir Step 5, même situation qu'au sous-projet 1)

**Interfaces:**
- Produces: `write(..., c411_announce_url: Optional[str] = None, staging_dir: Optional[str] = None)`, `effective_c411_announce_url() -> Optional[str]`, `effective_staging_dir() -> Optional[str]`. `status()` gagne `c411_announce_url_configured: bool` (jamais l'URL elle-même) et `staging_dir: Optional[str]` (pas un secret, renvoyé tel quel).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_gapscan_config_store.py`, avant `test_write_sets_restrictive_permissions` :

```python
def test_c411_announce_url_defaults_to_none():
    assert store.effective_c411_announce_url() is None


def test_write_then_read_c411_announce_url():
    store.write(c411_announce_url="https://c411.org/announce/SECRET")
    assert store.effective_c411_announce_url() == "https://c411.org/announce/SECRET"


def test_staging_dir_defaults_to_none():
    assert store.effective_staging_dir() is None


def test_write_then_read_staging_dir():
    store.write(staging_dir="/data/staging")
    assert store.effective_staging_dir() == "/data/staging"


def test_status_exposes_announce_url_as_a_flag_not_the_secret_itself():
    store.write(c411_announce_url="https://c411.org/announce/SECRET")
    status = store.status()
    assert status["c411_announce_url_configured"] is True
    assert "SECRET" not in str(status)


def test_status_announce_url_flag_false_by_default():
    assert store.status()["c411_announce_url_configured"] is False


def test_status_includes_staging_dir():
    store.write(staging_dir="/data/staging")
    assert store.status()["staging_dir"] == "/data/staging"


def test_status_staging_dir_none_by_default():
    assert store.status()["staging_dir"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gapscan_config_store.py -v -k "announce_url or staging_dir"`
Expected: FAIL — `AttributeError: module 'nfogen.gapscan_config_store' has no attribute 'effective_c411_announce_url'` (et similaire pour les autres)

- [ ] **Step 3: Write the implementation**

Dans `nfogen/gapscan_config_store.py`, modifier `write()` :

```python
def write(
    *,
    c411_api_key: Optional[str] = None,
    c411_base_url: Optional[str] = None,
    c411_announce_url: Optional[str] = None,
    sonarr_url: Optional[str] = None,
    sonarr_api_key: Optional[str] = None,
    radarr_url: Optional[str] = None,
    radarr_api_key: Optional[str] = None,
    sonarr_path_mappings: Optional[dict[str, str]] = None,
    radarr_path_mappings: Optional[dict[str, str]] = None,
    staging_dir: Optional[str] = None,
) -> None:
    """Met a jour uniquement les champs fournis (`None` = inchange) --
    jamais une reecriture complete, un PUT partiel ne doit pas effacer le
    reste de la configuration deja enregistree."""
    path = _path()
    data = _load()
    updates = {
        "c411_api_key": c411_api_key,
        "c411_base_url": c411_base_url,
        "c411_announce_url": c411_announce_url,
        "sonarr_url": sonarr_url,
        "sonarr_api_key": sonarr_api_key,
        "radarr_url": radarr_url,
        "radarr_api_key": radarr_api_key,
        "sonarr_path_mappings": sonarr_path_mappings,
        "radarr_path_mappings": radarr_path_mappings,
        "staging_dir": staging_dir,
    }
```

(le reste de `write()` -- boucle `for key, value in updates.items()`, écriture du fichier, `chmod` -- ne change pas)

Ajouter après `effective_radarr_path_mappings()` :

```python
def effective_c411_announce_url() -> Optional[str]:
    """URL d'annonce privee complete (passkey inclus) -- secret au meme
    titre que c411_api_key, jamais renvoyee en clair par status(). `None`
    si non configuree. Pas de repli sur une variable d'environnement :
    uniquement configurable via le fichier."""
    return _load().get("c411_announce_url") or None


def effective_staging_dir() -> Optional[str]:
    """Dossier ou nfogen met en scene les fichiers avant creation d'un
    .torrent -- pas un secret, `None` si non configure."""
    return _load().get("staging_dir") or None
```

Modifier `status()` :

```python
def status() -> dict[str, Any]:
    """Etat effectif (fichier prioritaire, sinon variables d'environnement)
    -- jamais les cles/secrets eux-memes, seulement si chaque service est
    configure et son URL (non sensible). Les mappings de chemins et
    staging_dir ne sont pas des secrets : renvoyes en entier."""
    c411 = effective_c411()
    sonarr = effective_sonarr()
    radarr = effective_radarr()
    return {
        "c411_configured": c411 is not None,
        "c411_base_url": c411[1] if c411 else None,
        "sonarr_configured": sonarr is not None,
        "sonarr_url": sonarr[0] if sonarr else None,
        "radarr_configured": radarr is not None,
        "radarr_url": radarr[0] if radarr else None,
        "sonarr_path_mappings": effective_sonarr_path_mappings(),
        "radarr_path_mappings": effective_radarr_path_mappings(),
        "c411_announce_url_configured": effective_c411_announce_url() is not None,
        "staging_dir": effective_staging_dir(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gapscan_config_store.py -v`
Expected: PASS (tous les tests du fichier, existants + nouveaux)

- [ ] **Step 5: Fix the now-broken exact-dict test in `test_api.py`**

Même situation qu'au sous-projet 1 : `GET /gapscan/config` renvoie déjà `status()` tel quel, donc `test_gapscan_config_reports_which_services_are_configured` casse dès cette task. Mettre à jour l'assertion :

```python
    assert resp.json() == {
        "c411_configured": True,
        "c411_base_url": "https://c411.org",
        "sonarr_configured": False,
        "sonarr_url": None,
        "radarr_configured": True,
        "radarr_url": "http://radarr.local",
        "sonarr_path_mappings": {},
        "radarr_path_mappings": {},
        "c411_announce_url_configured": False,
        "staging_dir": None,
    }
```

- [ ] **Step 6: Lint + full suite**

Run: `ruff check nfogen/gapscan_config_store.py tests/test_gapscan_config_store.py tests/test_api.py`
Run: `pytest -q`
Expected: clean, tous les tests passent

- [ ] **Step 7: Commit**

```bash
git add nfogen/gapscan_config_store.py tests/test_gapscan_config_store.py tests/test_api.py
git commit -m "AUTOMATION sous-projet 2 (4/7) : c411_announce_url + staging_dir

c411_announce_url traite comme un secret (status() n'expose qu'un
booleen 'configured', jamais l'URL -- contient le passkey, le
regenerer casse tous les seeds en cours). staging_dir n'est pas un
secret, renvoye tel quel comme sonarr_url/radarr_url. Corrige au
passage le test API en dict exact (meme situation qu'au sous-projet 1)."
```

---

### Task 5: `nfogen/api.py` — exposition via `PUT`/`GET /gapscan/config`

**Files:**
- Modify: `nfogen/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `gapscan_config_store.write(..., c411_announce_url=, staging_dir=)` (Task 4).
- Produces: `PUT /gapscan/config` accepte `c411_announce_url`/`staging_dir`. `GET /gapscan/config` les renvoie (`c411_announce_url_configured`, `staging_dir`).

**Note** : `gapscan_config_write()` (la fonction FastAPI) appelle déjà `gapscan_config_store.write(**req.model_dump())` de façon générique — aucun changement de code nécessaire dans cette fonction elle-même, seulement dans le modèle `GapscanConfigWriteRequest` (Step 3).

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_api.py`, après `test_gapscan_config_write_then_read_back_path_mappings` :

```python
def test_gapscan_config_write_then_read_back_announce_url_and_staging_dir(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={
            "c411_announce_url": "https://c411.org/announce/SECRET",
            "staging_dir": "/data/staging",
        },
    )
    assert put.status_code == 200
    assert put.json()["c411_announce_url_configured"] is True
    assert put.json()["staging_dir"] == "/data/staging"
    assert "SECRET" not in put.text  # jamais l'URL en clair, meme dans la reponse du PUT

    status = client.get("/gapscan/config").json()
    assert status["c411_announce_url_configured"] is True
    assert status["staging_dir"] == "/data/staging"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v -k announce_url_and_staging_dir`
Expected: FAIL — les deux champs sont silencieusement ignorés par Pydantic (pas dans `GapscanConfigWriteRequest`), `put.json()` ne contient donc pas `c411_announce_url_configured`/`staging_dir` avec les valeurs attendues (`KeyError` ou assertion sur `None`/absent)

- [ ] **Step 3: Write the implementation**

Dans `nfogen/api.py`, modifier `GapscanConfigWriteRequest` :

```python
class GapscanConfigWriteRequest(BaseModel):
    c411_api_key: Optional[str] = None
    c411_base_url: Optional[str] = None
    c411_announce_url: Optional[str] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    sonarr_path_mappings: Optional[dict[str, str]] = None
    radarr_path_mappings: Optional[dict[str, str]] = None
    staging_dir: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py -v -k gapscan`
Expected: PASS (tous les tests gapscan de `test_api.py`)

- [ ] **Step 5: Lint + full suite**

Run: `ruff check nfogen/api.py tests/test_api.py`
Run: `pytest -q`
Expected: clean, tout passe

- [ ] **Step 6: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "AUTOMATION sous-projet 2 (5/7) : expose c411_announce_url/staging_dir

PUT/GET /gapscan/config accepte et renvoie les deux nouveaux champs.
gapscan_config_write() n'a pas change (deja generique via
req.model_dump()), seul le modele Pydantic gagne les champs."
```

---

### Task 6: Frontend — types

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/GapScanPage.test.tsx` (littéraux `GapscanConfig` à mettre à jour)

**Interfaces:**
- Produces: `GapscanConfig.c411_announce_url_configured: boolean`, `GapscanConfig.staging_dir: string | null`, `GapscanConfigWrite.c411_announce_url?: string`, `GapscanConfigWrite.staging_dir?: string`.

- [ ] **Step 1: Update the types**

Dans `frontend/src/api/types.ts`, modifier `GapscanConfig` et `GapscanConfigWrite` :

```typescript
export interface GapscanConfig {
  c411_configured: boolean;
  c411_base_url: string | null;
  sonarr_configured: boolean;
  sonarr_url: string | null;
  radarr_configured: boolean;
  radarr_url: string | null;
  sonarr_path_mappings: Record<string, string>;
  radarr_path_mappings: Record<string, string>;
  /** true si une adresse d'annonce C411 est enregistree -- jamais la
   * valeur elle-meme (contient le passkey du compte). */
  c411_announce_url_configured: boolean;
  staging_dir: string | null;
}

/** PUT /gapscan/config : chaque champ omis reste inchange cote serveur. */
export interface GapscanConfigWrite {
  c411_api_key?: string;
  c411_base_url?: string;
  c411_announce_url?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_path_mappings?: Record<string, string>;
  radarr_path_mappings?: Record<string, string>;
  staging_dir?: string;
}
```

- [ ] **Step 2: Check the correct tsc command, run it**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json` (**pas** `tsc --noEmit` seul, voir Global Constraints)
Expected: erreurs sur les littéraux `CONFIGURED`/objets `GapscanConfig` de `GapScanPage.test.tsx` qui n'ont pas les 2 nouveaux champs requis.

- [ ] **Step 3: Fix the test literals**

Dans `frontend/src/pages/GapScanPage.test.tsx`, chercher chaque objet littéral typé `GapscanConfig` (`grep -n "c411_configured" frontend/src/pages/GapScanPage.test.tsx` pour les localiser tous) et ajouter à chacun :

```typescript
  c411_announce_url_configured: false,
  staging_dir: null,
```

- [ ] **Step 4: Run tsc again to verify it passes**

Run: `npx tsc --noEmit -p tsconfig.app.json`
Expected: clean

- [ ] **Step 5: Run the frontend suite**

Run: `npx vitest run`
Expected: PASS (tous les tests)

- [ ] **Step 6: Lint**

Run: `npm run lint`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/pages/GapScanPage.test.tsx
git commit -m "AUTOMATION sous-projet 2 (6/7) : types frontend

GapscanConfig(Write).c411_announce_url_configured/staging_dir. Miroir
du backend -- c411_announce_url_configured est un booleen (pas le
secret lui-meme), staging_dir une simple chaine."
```

---

### Task 7: Frontend — UI de configuration (`c411_announce_url` + `staging_dir`)

**Files:**
- Modify: `frontend/src/pages/GapScanPage.tsx`
- Modify: `frontend/src/pages/GapScanPage.test.tsx`

**Interfaces:**
- Consumes: `GapscanConfig.c411_announce_url_configured`/`staging_dir` (Task 6).

- [ ] **Step 1: Write the failing test**

Ajouter à `frontend/src/pages/GapScanPage.test.tsx`, après le test `"enregistre un mapping de chemin Radarr via le formulaire de configuration"` :

```typescript
  it("enregistre l'adresse d'annonce C411 et le dossier de mise en scene", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED,
      c411_announce_url_configured: true,
      staging_dir: "/data/staging",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration/ }));

    await user.type(screen.getByLabelText("Adresse d'annonce C411"), "https://c411.org/announce/SECRET");
    await user.type(screen.getByLabelText("Dossier de mise en scène"), "/data/staging");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({
        c411_announce_url: "https://c411.org/announce/SECRET",
        staging_dir: "/data/staging",
      }),
    );
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx -t "annonce C411"`
Expected: FAIL — `Unable to find a label with the text of: Adresse d'annonce C411` (le champ n'existe pas encore)

- [ ] **Step 3: Write the implementation**

Dans `frontend/src/pages/GapScanPage.tsx`, ajouter deux nouveaux états, après `const [radarrPathMappings, setRadarrPathMappings] = useState<Record<string, string>>({});` :

```typescript
  const [c411AnnounceUrl, setC411AnnounceUrl] = useState("");
  const [stagingDir, setStagingDir] = useState("");
```

Dans le `useEffect` de chargement de la config, ajouter :

```typescript
        setStagingDir(c.staging_dir ?? "");
```

(juste après `setRadarrPathMappings(c.radarr_path_mappings);` -- pas d'équivalent pour `c411AnnounceUrl`, un secret n'est jamais prérempli depuis la config chargée, comme `c411ApiKey`/`sonarrApiKey`/`radarrApiKey`)

Dans `handleSaveConfig()`, ajouter :

```typescript
      if (c411AnnounceUrl.trim()) fields.c411_announce_url = c411AnnounceUrl.trim();
      if (stagingDir.trim()) fields.staging_dir = stagingDir.trim();
```

(juste après `if (c411BaseUrl.trim()) fields.c411_base_url = c411BaseUrl.trim();` -- avant les lignes `fields.sonarr_path_mappings = ...`/`fields.radarr_path_mappings = ...` déjà présentes)

Et réinitialiser le champ secret après sauvegarde, comme les autres clés :

```typescript
      setC411AnnounceUrl("");
```

(à ajouter dans le bloc `try` de `handleSaveConfig()`, juste après `setC411ApiKey("");`)

Dans le JSX du formulaire, dans la `<div className="grid grid-cols-2 gap-3">` existante, ajouter deux nouveaux champs après le bloc "Clé API C411" (dernier champ de la grille) :

```tsx
              <label className="block text-sm font-medium text-ink-dim">
                Adresse d'annonce C411
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={config?.c411_announce_url_configured ? "•••• (enregistrée)" : ""}
                  value={c411AnnounceUrl}
                  onChange={(e) => setC411AnnounceUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Dossier de mise en scène
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  placeholder="/data/staging"
                  value={stagingDir}
                  onChange={(e) => setStagingDir(e.target.value)}
                />
              </label>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/GapScanPage.test.tsx`
Expected: PASS (tous les tests du fichier)

- [ ] **Step 5: Update the exact-payload config test**

Le test `"enregistre Sonarr/Radarr via le formulaire de configuration"` fait un `toHaveBeenCalledWith({...})` en dict EXACT — vérifier qu'il passe toujours tel quel (aucun des deux nouveaux champs n'y est rempli dans ce test, donc `fields.c411_announce_url`/`fields.staging_dir` ne sont jamais ajoutés — pas de changement attendu ici, contrairement à `sonarr_path_mappings`/`radarr_path_mappings` au sous-projet 1 qui étaient TOUJOURS envoyés). Si ce test échoue malgré tout, relire `handleSaveConfig()` : `c411_announce_url`/`staging_dir` doivent rester conditionnels (`if (...trim())`), jamais envoyés à vide contrairement aux mappings de chemins.

- [ ] **Step 6: Run full frontend + backend checks**

Run: `npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npm run lint && npm run build`
Run (depuis la racine) : `pytest -q && ruff check .`
Expected: tout propre

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/GapScanPage.tsx frontend/src/pages/GapScanPage.test.tsx
git commit -m "AUTOMATION sous-projet 2 (7/7) : UI config annonce C411 + staging_dir

Champ 'Adresse d'annonce C411' en mot de passe (secret, jamais
prerempli depuis la config chargee, comme les autres cles). 'Dossier
de mise en scene' en texte simple. Termine le sous-projet 2
(AUTOMATION.md) cote configuration -- file_staging.py/torrent_builder.py
restent des briques non encore appelees depuis un flux utilisateur
(sous-projet 3 : nommage, les connectera)."
```

---

## Après ce plan

Sous-projet 2 livré : deux modules testés (`file_staging.py`, `torrent_builder.py`) et leur configuration exposée de bout en bout, mais **pas encore appelés** depuis un flux déclenchable par l'utilisateur — ils attendent le sous-projet 3 (nommage réel selon le profil/tracker) pour être orchestrés ensemble. Mettre à jour `AUTOMATION.md` : passer la ligne "Mise en scène du fichier..." de "Conception ci-dessus" à "Livré (2026-08-XX)", noter les écarts éventuels entre conception et implémentation réelle (comme fait pour le sous-projet 1). Sous-projet 3 à concevoir ensuite.
