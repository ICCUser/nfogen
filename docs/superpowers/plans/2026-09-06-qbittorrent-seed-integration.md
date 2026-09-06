# Intégration qBittorrent (sous-projet 6) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une file d'attente "À mettre en seed" : l'utilisateur y dépose le `.torrent` re-signé par C411 (téléchargé manuellement — aucune API automatisée possible, vérifié en conditions réelles), nfogen l'ajoute à qBittorrent en le pointant sur le contenu déjà mis en scène, sans jamais retélécharger quoi que ce soit.

**Architecture:** Nouveau client HTTP `qbittorrent_client.py` (même patron que radarr_client.py/sonarr_client.py). `upload_history_store.py` persiste désormais le `staged_path` de chaque titre confirmé, pour le retrouver longtemps après (la modération C411 n'est pas immédiate) et exposer une file d'attente (`pending_seed_entries()`). Deux nouveaux endpoints API, une nouvelle page frontend.

**Tech Stack:** Python 3.11+ / FastAPI / httpx / pytest (backend), React 18 + TypeScript + Vite + Vitest (frontend). Aucune nouvelle dépendance.

**Spec:** [docs/superpowers/specs/2026-09-06-qbittorrent-seed-integration-design.md](../specs/2026-09-06-qbittorrent-seed-integration-design.md)

## Global Constraints

- Aucune récupération automatique du `.torrent` re-signé — confirmé impossible (l'endpoint C411 exige une session navigateur, pas la clé API). Import strictement manuel.
- `qbittorrent_client.py` ne retélécharge jamais le contenu — `add_torrent()` pointe uniquement sur un `save_path` déjà rempli.
- Aucun nettoyage automatique du dossier de mise en scène après ajout au seed (non-objectif explicite).
- Une seule configuration qBittorrent globale (pas namespacée par profil, pas multi-instance).
- `upload_history_store.record()` ne doit jamais faire échouer un appelant par ailleurs réussi (try/except large, déjà en place — préservé).
- Attribution de commit : `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Après chaque push, poller GitHub Actions jusqu'à un run terminé sur ce commit avant de considérer la tâche faite.

---

## Task 1: `nfogen/qbittorrent_client.py` (nouveau)

**Files:**
- Create: `nfogen/qbittorrent_client.py`
- Test: `tests/test_qbittorrent_client.py`

**Interfaces:**
- Produces: `QBittorrentError(RuntimeError)`, `QBittorrentClient(base_url, username, password, http_client=None, timeout=30.0)`, méthode `add_torrent(torrent_bytes: bytes, save_path: str, filename: str = "release.torrent") -> None`, `close()`.

- [ ] **Step 1: Écrire les tests**

Créer `tests/test_qbittorrent_client.py` :

```python
"""Tests de nfogen.qbittorrent_client (transport HTTP mocke, aucun reseau
reel). L'API qBittorrent v2 renvoie le texte brut "Ok." sur succes (login
et add_torrent) -- jamais verifie par ce projet avant ce sous-projet,
voir la spec, "Points a verifier"."""
from __future__ import annotations

import httpx
import pytest

from nfogen.qbittorrent_client import QBittorrentClient, QBittorrentError


def _client(handler) -> QBittorrentClient:
    return QBittorrentClient(
        base_url="http://qbittorrent.local:8080",
        username="admin",
        password="adminadmin",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_add_torrent_logs_in_then_adds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/auth/login":
            assert b"username=admin" in request.content
            assert b"password=adminadmin" in request.content
            return httpx.Response(200, text="Ok.")
        assert request.url.path == "/api/v2/torrents/add"
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.add_torrent(b"torrent bytes", "/data/staging", filename="Release.torrent")

    assert calls == ["/api/v2/auth/login", "/api/v2/torrents/add"]


def test_add_torrent_sends_savepath_and_file_content():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        captured["content"] = request.content
        return httpx.Response(200, text="Ok.")

    client = _client(handler)
    client.add_torrent(b"torrent bytes", "/data/staging", filename="Release.torrent")

    assert b"/data/staging" in captured["content"]
    assert b"torrent bytes" in captured["content"]
    assert b"Release.torrent" in captured["content"]


def test_login_failure_raises_qbittorrent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Fails.")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[Aa]uthentification"):
        client.add_torrent(b"x", "/data/staging")


def test_add_failure_raises_qbittorrent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, text="Fails.")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="refuse"):
        client.add_torrent(b"x", "/data/staging")


def test_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = _client(handler)
    with pytest.raises(QBittorrentError, match="[ée]chou"):
        client.add_torrent(b"x", "/data/staging")


def test_requires_base_url_username_and_password():
    with pytest.raises(QBittorrentError):
        QBittorrentClient(base_url="", username="a", password="b")
    with pytest.raises(QBittorrentError):
        QBittorrentClient(base_url="http://x", username="", password="b")
    with pytest.raises(QBittorrentError):
        QBittorrentClient(base_url="http://x", username="a", password="")
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_qbittorrent_client.py -v`
Expected: FAIL (`ModuleNotFoundError: nfogen.qbittorrent_client`).

- [ ] **Step 3: Implémenter**

Créer `nfogen/qbittorrent_client.py` :

```python
"""Client pour l'API Web de qBittorrent (v2) -- AUTOMATION.md, sous-projet
6. Utilise pour ajouter un .torrent RE-SIGNE par le tracker (recupere
MANUELLEMENT par l'utilisateur -- l'endpoint de telechargement C411 exige
une session navigateur, pas la cle API, verifie en conditions reelles
2026-09-06 : aucune automatisation possible cote recuperation) et le
pointer sur le contenu DEJA en scene par nfogen -- jamais retelecharge
par ce module, seulement verifie/seede par qBittorrent lui-meme.
"""
from __future__ import annotations

from typing import Optional

import httpx


class QBittorrentError(RuntimeError):
    """Erreur reseau, authentification ou reponse inattendue de l'API qBittorrent."""


class QBittorrentClient:
    """Client HTTP pour l'API Web v2 de qBittorrent."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not username or not password:
            raise QBittorrentError("URL, utilisateur ou mot de passe qBittorrent manquant.")
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None
        self._logged_in = False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "QBittorrentClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _login(self) -> None:
        try:
            response = self._client.post(
                f"{self._base_url}/api/v2/auth/login",
                data={"username": self._username, "password": self._password},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Connexion à qBittorrent échouée : {exc}") from exc
        if response.text.strip() != "Ok.":
            raise QBittorrentError("Authentification qBittorrent refusée (identifiants incorrects ?).")
        self._logged_in = True

    def add_torrent(self, torrent_bytes: bytes, save_path: str, filename: str = "release.torrent") -> None:
        """Ajoute un .torrent DEJA telecharge (voir docstring du module),
        pointe sur `save_path` -- le contenu doit deja s'y trouver. Leve
        `QBittorrentError` en cas d'echec (connexion, authentification,
        ou refus par qBittorrent)."""
        if not self._logged_in:
            self._login()
        try:
            response = self._client.post(
                f"{self._base_url}/api/v2/torrents/add",
                files={"torrents": (filename, torrent_bytes, "application/x-bittorrent")},
                data={"savepath": save_path},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QBittorrentError(f"Ajout du torrent à qBittorrent échoué : {exc}") from exc
        if response.text.strip() != "Ok.":
            raise QBittorrentError(f"qBittorrent a refusé le torrent : {response.text.strip()}")
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_qbittorrent_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nfogen/qbittorrent_client.py tests/test_qbittorrent_client.py
git commit -m "feat: client API qBittorrent (add_torrent, sous-projet 6)"
```

---

## Task 2: `nfogen/gapscan_config_store.py` — configuration qBittorrent

**Files:**
- Modify: `nfogen/gapscan_config_store.py`
- Test: `tests/test_gapscan_config_store.py`

**Interfaces:**
- Produces: `write(..., qbittorrent_url=None, qbittorrent_username=None, qbittorrent_password=None)`, `effective_qbittorrent() -> Optional[tuple[str, str, str]]`, `status()` gagne `qbittorrent_configured`/`qbittorrent_url`.

- [ ] **Step 1: Mettre à jour la fixture d'isolation des tests**

Dans `tests/test_gapscan_config_store.py`, la fixture `_config_file` (autouse) supprime déjà plusieurs variables d'environnement avant chaque test — ajouter les 3 nouvelles pour éviter toute pollution entre tests :

```python
@pytest.fixture(autouse=True)
def _config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(tmp_path / "gapscan_config.json"))
    for key in (
        "NFOGEN_C411_API_KEY", "NFOGEN_C411_BASE_URL",
        "NFOGEN_SONARR_URL", "NFOGEN_SONARR_API_KEY",
        "NFOGEN_RADARR_URL", "NFOGEN_RADARR_API_KEY",
        "NFOGEN_QBITTORRENT_URL", "NFOGEN_QBITTORRENT_USERNAME", "NFOGEN_QBITTORRENT_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
```

- [ ] **Step 2: Écrire les tests**

Ajouter à `tests/test_gapscan_config_store.py` :

```python
def test_effective_qbittorrent_none_when_nothing_configured():
    assert store.effective_qbittorrent() is None


def test_write_then_read_qbittorrent():
    store.write(
        qbittorrent_url="http://qbittorrent.local:8080",
        qbittorrent_username="admin", qbittorrent_password="secret",
    )
    assert store.effective_qbittorrent() == ("http://qbittorrent.local:8080", "admin", "secret")


def test_effective_qbittorrent_none_if_any_field_missing():
    store.write(qbittorrent_url="http://qbittorrent.local:8080", qbittorrent_username="admin")
    assert store.effective_qbittorrent() is None


def test_qbittorrent_falls_back_to_env_vars(monkeypatch):
    monkeypatch.setenv("NFOGEN_QBITTORRENT_URL", "http://from-env:8080")
    monkeypatch.setenv("NFOGEN_QBITTORRENT_USERNAME", "admin")
    monkeypatch.setenv("NFOGEN_QBITTORRENT_PASSWORD", "secret")
    assert store.effective_qbittorrent() == ("http://from-env:8080", "admin", "secret")


def test_status_includes_qbittorrent_configured_and_url():
    assert store.status()["qbittorrent_configured"] is False
    assert store.status()["qbittorrent_url"] is None
    store.write(
        qbittorrent_url="http://qbittorrent.local:8080",
        qbittorrent_username="admin", qbittorrent_password="secret",
    )
    status = store.status()
    assert status["qbittorrent_configured"] is True
    assert status["qbittorrent_url"] == "http://qbittorrent.local:8080"
```

- [ ] **Step 3: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_gapscan_config_store.py -v -k qbittorrent`
Expected: FAIL (`AttributeError: module 'nfogen.gapscan_config_store' has no attribute 'effective_qbittorrent'`).

- [ ] **Step 4: Implémenter**

Dans `nfogen/gapscan_config_store.py`, modifier `write()` :

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
    qbittorrent_url: Optional[str] = None,
    qbittorrent_username: Optional[str] = None,
    qbittorrent_password: Optional[str] = None,
) -> None:
    """... (docstring existant inchange) ..."""
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
        "qbittorrent_url": qbittorrent_url,
        "qbittorrent_username": qbittorrent_username,
        "qbittorrent_password": qbittorrent_password,
    }
    for key, value in top_level_updates.items():
        if value is not None:
            data[key] = value
    # (reste du corps inchange : tracker_updates, ecriture fichier, chmod)
```

Ajouter après `effective_staging_dir()` :

```python
def effective_qbittorrent() -> Optional[tuple[str, str, str]]:
    """`(url, utilisateur, mot de passe)`, ou `None` si l'un des trois
    manque. Configuration globale (pas namespacee par profil de tracker --
    un seul client de seed, voir AUTOMATION.md, sous-projet 6)."""
    url = _resolve("qbittorrent_url", "NFOGEN_QBITTORRENT_URL")
    username = _resolve("qbittorrent_username", "NFOGEN_QBITTORRENT_USERNAME")
    password = _resolve("qbittorrent_password", "NFOGEN_QBITTORRENT_PASSWORD")
    return (url, username, password) if url and username and password else None
```

Modifier `status()` :

```python
def status(profile: str = "c411") -> dict[str, Any]:
    tracker = effective_tracker(profile)
    sonarr = effective_sonarr()
    radarr = effective_radarr()
    qbittorrent = effective_qbittorrent()
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
        "qbittorrent_configured": qbittorrent is not None,
        "qbittorrent_url": qbittorrent[0] if qbittorrent else None,
    }
```

- [ ] **Step 5: Lancer les tests**

Run: `pytest tests/test_gapscan_config_store.py -v`
Expected: PASS (tous, y compris les tests existants non liés à qBittorrent).

- [ ] **Step 6: Commit**

```bash
git add nfogen/gapscan_config_store.py tests/test_gapscan_config_store.py
git commit -m "feat: configuration qBittorrent (gapscan_config_store, sous-projet 6)"
```

---

## Task 3: `nfogen/upload_history_store.py` — `staged_path` + `pending_seed_entries()`

**Files:**
- Modify: `nfogen/upload_history_store.py`
- Test: `tests/test_upload_history_store.py`

**Interfaces:**
- Produces: `record(key, *, kind, release_name, at=None, staged_path=None)`, `pending_seed_entries() -> list[dict[str, Any]]` (chaque dict : `key`, `media_type`, `release_name`, `staged_path`, `sent_at`).

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/test_upload_history_store.py` :

```python
def test_pending_seed_entries_lists_sent_without_seeding():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="R", staged_path="/staging/R.mkv")
    upload_history_store.record(key, kind="sent", release_name="R")

    entries = upload_history_store.pending_seed_entries()

    assert len(entries) == 1
    assert entries[0]["key"] == upload_history_store.key_str(key)
    assert entries[0]["media_type"] == "movie"
    assert entries[0]["release_name"] == "R"
    assert entries[0]["staged_path"] == "/staging/R.mkv"
    assert entries[0]["sent_at"] is not None


def test_pending_seed_entries_excludes_titles_never_sent():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="R", staged_path="/staging/R.mkv")
    assert upload_history_store.pending_seed_entries() == []


def test_pending_seed_entries_excludes_titles_already_seeding():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="R", staged_path="/staging/R.mkv")
    upload_history_store.record(key, kind="sent", release_name="R")
    upload_history_store.record(key, kind="seeding", release_name="R")
    assert upload_history_store.pending_seed_entries() == []


def test_pending_seed_entries_series_media_type_and_staged_path_none_when_absent():
    key = ("series", 7, 2)
    # Jamais de "committed" enregistre avec staged_path pour cette cle.
    upload_history_store.record(key, kind="sent", release_name="Show.S02")

    entries = upload_history_store.pending_seed_entries()

    assert entries[0]["media_type"] == "series"
    assert entries[0]["staged_path"] is None


def test_pending_seed_entries_empty_without_env_var(monkeypatch):
    monkeypatch.delenv("NFOGEN_UPLOAD_HISTORY_FILE", raising=False)
    assert upload_history_store.pending_seed_entries() == []
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_upload_history_store.py -v -k pending_seed`
Expected: FAIL (`AttributeError: module 'nfogen.upload_history_store' has no attribute 'pending_seed_entries'`).

- [ ] **Step 3: Implémenter**

Dans `nfogen/upload_history_store.py`, remplacer `record()` :

```python
def record(
    key: tuple, *, kind: str, release_name: str,
    at: Optional[float] = None, staged_path: Optional[str] = None,
) -> None:
    """Ajoute/met a jour une entree -- kind: "committed" (Confirmer reussi),
    "sent" (Envoyer a C411 reussi) ou "seeding" (ajoute a un client de
    seed, voir AUTOMATION.md sous-projet 6). Idempotent par cle+kind : un
    nouvel appel sur la meme cle+kind met a jour l'horodatage plutot que
    d'accumuler des doublons. N'ECHOUE JAMAIS (try/except large) : un
    Confirmer/Envoi/Ajout par ailleurs reussi ne doit jamais etre bloque
    par un probleme d'ecriture de cet historique, purement informatif.

    `staged_path` (optionnel, sous-projet 6) : chemin de mise en scene --
    enregistre avec l'entree "committed", permet de retrouver le contenu
    DEJA en scene bien apres le Confirmer d'origine (la moderation C411
    n'est pas immediate), meme apres un redemarrage du serveur nfogen.
    Voir pending_seed_entries()."""
    try:
        data = _load()
        entry = data.setdefault(key_str(key), {})
        value: dict[str, Any] = {"release_name": release_name, "at": at if at is not None else time.time()}
        if staged_path is not None:
            value["staged_path"] = staged_path
        entry[kind] = value
        _save(data)
    except Exception:  # noqa: BLE001 -- jamais propager, voir docstring
        pass
```

Ajouter à la fin du fichier :

```python
def pending_seed_entries() -> list[dict[str, Any]]:
    """Titres marques "sent" (Envoyer a C411 reussi) sans entree "seeding"
    correspondante -- utilise par GET /gapscan/seed-queue (AUTOMATION.md,
    sous-projet 6). Chaque entree : `key` (chaine opaque, a repasser telle
    quelle a l'ajout), `media_type` ("movie"/"series", deduit directement
    du premier element de la cle decodee), `release_name`, `staged_path`
    (depuis l'entree "committed" -- `None` si absente, ex. enregistree
    avant l'ajout de ce champ), `sent_at`."""
    data = _load()
    pending: list[dict[str, Any]] = []
    for key_string, entry in data.items():
        sent = entry.get("sent")
        if sent is None or "seeding" in entry:
            continue
        try:
            decoded = json.loads(key_string)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        committed = entry.get("committed") or {}
        pending.append(
            {
                "key": key_string,
                "media_type": decoded[0] if decoded else None,
                "release_name": sent.get("release_name"),
                "staged_path": committed.get("staged_path"),
                "sent_at": sent.get("at"),
            }
        )
    return pending
```

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_upload_history_store.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add nfogen/upload_history_store.py tests/test_upload_history_store.py
git commit -m "feat: upload_history_store persiste staged_path, expose pending_seed_entries"
```

---

## Task 4: `nfogen/commit_job_runner.py` — transmet `staged_path`

**Files:**
- Modify: `nfogen/commit_job_runner.py:110-123`
- Test: `tests/test_commit_job_runner.py`

**Interfaces:**
- Consumes: `upload_history_store.record(key, kind="committed", release_name=..., staged_path=...)` (Task 3), `upload_history_store.pending_seed_entries()` (Task 3).

- [ ] **Step 1: Écrire le test**

Ajouter à `tests/test_commit_job_runner.py` (réutiliser `_stub_resolve_staging_config`/`_wait_until_terminal` déjà présents) :

```python
def test_start_records_staged_path_for_later_seed_queue_lookup(monkeypatch, tmp_path):
    """AUTOMATION.md, sous-projet 6 : le chemin de mise en scene doit
    survivre bien apres le Confirmer d'origine, pour la file d'attente
    'A mettre en seed' (la moderation C411 n'est pas immediate)."""
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    _stub_resolve_staging_config(monkeypatch)

    def fake_commit_upload(release_name, files, profile, on_progress=None, cancel_event=None, **kwargs):
        return CommitResult(
            release_name=release_name, staged_path=str(tmp_path / "staging" / "R.mkv"),
            torrent_path="t", nfo_path="n",
        )

    monkeypatch.setattr("nfogen.commit_job_runner.upload_prep.commit_upload", fake_commit_upload)

    job_id = commit_job_runner.start("R", FILES, media_type="movie", radarr_movie_id=42)
    _wait_until_terminal(job_id)

    upload_history_store.record(
        upload_history_store.processed_key("movie", 42, None), kind="sent", release_name="R"
    )
    entries = upload_history_store.pending_seed_entries()
    assert entries[0]["staged_path"] == str(tmp_path / "staging" / "R.mkv")
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `pytest tests/test_commit_job_runner.py -v -k staged_path`
Expected: FAIL (`entries[0]["staged_path"] is None`, puisque `record()` n'est pas encore appelé avec `staged_path`).

- [ ] **Step 3: Implémenter**

Dans `nfogen/commit_job_runner.py`, modifier l'appel dans `_run()` :

```python
        key = upload_history_store.processed_key(
            media_type, radarr_movie_id, sonarr_series_id, season_number
        )
        if key is not None:
            upload_history_store.record(
                key, kind="committed", release_name=release_name, staged_path=result.staged_path
            )
```

(remplace le `upload_history_store.record(key, kind="committed", release_name=release_name)` existant).

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_commit_job_runner.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add nfogen/commit_job_runner.py tests/test_commit_job_runner.py
git commit -m "feat: commit_job_runner persiste staged_path (file d'attente de seed)"
```

---

## Task 5: `nfogen/api.py` — configuration qBittorrent via `PUT /gapscan/config`

**Files:**
- Modify: `nfogen/api.py` (import, `GapscanConfigWriteRequest`)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `gapscan_config_store.write(..., qbittorrent_url=, qbittorrent_username=, qbittorrent_password=)`, `gapscan_config_store.status()` (Task 2).

- [ ] **Step 1: Écrire le test**

Ajouter à `tests/test_api.py`, à côté des tests `test_gapscan_config_write_*` existants :

```python
def test_gapscan_config_write_then_read_back_qbittorrent(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={
            "qbittorrent_url": "http://qbittorrent.local:8080",
            "qbittorrent_username": "admin", "qbittorrent_password": "secret",
        },
    )
    assert put.status_code == 200

    body = client.get("/gapscan/config").json()
    assert body["qbittorrent_configured"] is True
    assert body["qbittorrent_url"] == "http://qbittorrent.local:8080"
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `pytest tests/test_api.py -v -k write_then_read_back_qbittorrent`
Expected: FAIL (`KeyError: 'qbittorrent_configured'` ou 422 si le champ n'existe pas sur le modèle Pydantic).

- [ ] **Step 3: Implémenter**

Dans `nfogen/api.py`, modifier `GapscanConfigWriteRequest` :

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
    qbittorrent_url: Optional[str] = None
    qbittorrent_username: Optional[str] = None
    qbittorrent_password: Optional[str] = None
```

(`gapscan_config_write()` transmet déjà tous les champs du modèle via `**fields` — aucun autre changement nécessaire dans cette fonction).

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_api.py -v -k gapscan_config`
Expected: PASS (tous, y compris les tests de configuration existants).

- [ ] **Step 5: Commit**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: PUT/GET /gapscan/config expose la configuration qBittorrent"
```

---

## Task 6: `nfogen/api.py` — `GET/POST /gapscan/seed-queue`

**Files:**
- Modify: `nfogen/api.py` (imports, nouveaux endpoints)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `upload_history_store.pending_seed_entries()`, `upload_history_store.record()` (Task 3), `upload_history_store.key_str()`, `QBittorrentClient`/`QBittorrentError` (Task 1), `gapscan_config_store.effective_qbittorrent()` (Task 2).
- Produces: `GET /gapscan/seed-queue` → `list[dict]`, `POST /gapscan/seed-queue/add` → `{"status": "added"}`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/test_api.py`, après la section `/gapscan/library` (réutiliser le patron `reload_api`/`TestClient`) :

```python
# --------------------------------------------------------------------------- #
# GET/POST /gapscan/seed-queue (AUTOMATION.md, sous-projet 6) : mise en seed
# apres upload -- import manuel du .torrent re-signe (aucune API C411 ne
# permet de le recuperer automatiquement, verifie en conditions reelles).
# --------------------------------------------------------------------------- #
class _FakeQBittorrentClient:
    instances: list["_FakeQBittorrentClient"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.added: list[tuple] = []
        _FakeQBittorrentClient.instances.append(self)

    def add_torrent(self, torrent_bytes, save_path, filename="release.torrent"):
        self.added.append((torrent_bytes, save_path, filename))

    def close(self):
        pass


def test_gapscan_seed_queue_lists_pending_entries(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_UPLOAD_HISTORY_FILE=str(tmp_path / "history.json"),
    )
    mod.upload_history_store.record(
        ("movie", 42), kind="committed", release_name="R", staged_path=str(tmp_path / "staging" / "R.mkv")
    )
    mod.upload_history_store.record(("movie", 42), kind="sent", release_name="R")
    client = TestClient(mod.app)

    resp = client.get("/gapscan/seed-queue")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["release_name"] == "R"


def test_gapscan_seed_queue_add_400_without_qbittorrent_configured(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_UPLOAD_HISTORY_FILE=str(tmp_path / "history.json"),
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    resp = client.post(
        "/gapscan/seed-queue/add",
        data={"key": '["movie",42]'},
        files={"torrent": ("R.torrent", b"data", "application/x-bittorrent")},
    )
    assert resp.status_code == 400


def _configure_qbittorrent(client: TestClient) -> None:
    put = client.put(
        "/gapscan/config",
        json={
            "qbittorrent_url": "http://qbittorrent.local:8080",
            "qbittorrent_username": "admin", "qbittorrent_password": "secret",
        },
    )
    assert put.status_code == 200


def test_gapscan_seed_queue_add_success(reload_api, monkeypatch, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_UPLOAD_HISTORY_FILE=str(tmp_path / "history.json"),
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    _configure_qbittorrent(client)

    staged_path = str(tmp_path / "staging" / "R.mkv")
    mod.upload_history_store.record(("movie", 42), kind="committed", release_name="R", staged_path=staged_path)
    mod.upload_history_store.record(("movie", 42), kind="sent", release_name="R")

    _FakeQBittorrentClient.instances.clear()
    monkeypatch.setattr(mod, "QBittorrentClient", _FakeQBittorrentClient)

    key = mod.upload_history_store.key_str(("movie", 42))
    resp = client.post(
        "/gapscan/seed-queue/add",
        data={"key": key},
        files={"torrent": ("R.torrent", b"torrent-bytes", "application/x-bittorrent")},
    )

    assert resp.status_code == 200
    assert _FakeQBittorrentClient.instances[0].added == [
        (b"torrent-bytes", str(tmp_path / "staging"), "R.torrent")
    ]
    # Marque "seeding" : disparait de la file d'attente.
    assert client.get("/gapscan/seed-queue").json() == []


def test_gapscan_seed_queue_add_404_unknown_key(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_UPLOAD_HISTORY_FILE=str(tmp_path / "history.json"),
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    _configure_qbittorrent(client)

    resp = client.post(
        "/gapscan/seed-queue/add",
        data={"key": '["movie",999]'},
        files={"torrent": ("R.torrent", b"x", "application/x-bittorrent")},
    )
    assert resp.status_code == 404


def test_gapscan_seed_queue_add_400_missing_staged_path(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_UPLOAD_HISTORY_FILE=str(tmp_path / "history.json"),
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    _configure_qbittorrent(client)
    # "sent" sans "committed" prealable -- staged_path introuvable.
    mod.upload_history_store.record(("movie", 42), kind="sent", release_name="R")
    key = mod.upload_history_store.key_str(("movie", 42))

    resp = client.post(
        "/gapscan/seed-queue/add",
        data={"key": key},
        files={"torrent": ("R.torrent", b"x", "application/x-bittorrent")},
    )
    assert resp.status_code == 400


def test_gapscan_seed_queue_add_400_on_qbittorrent_error(reload_api, monkeypatch, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_UPLOAD_HISTORY_FILE=str(tmp_path / "history.json"),
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    _configure_qbittorrent(client)

    staged_path = str(tmp_path / "staging" / "R.mkv")
    mod.upload_history_store.record(("movie", 42), kind="committed", release_name="R", staged_path=staged_path)
    mod.upload_history_store.record(("movie", 42), kind="sent", release_name="R")

    class _FailingQBittorrentClient:
        def __init__(self, *args, **kwargs):
            pass

        def add_torrent(self, *args, **kwargs):
            raise mod.QBittorrentError("connexion refusée")

        def close(self):
            pass

    monkeypatch.setattr(mod, "QBittorrentClient", _FailingQBittorrentClient)
    key = mod.upload_history_store.key_str(("movie", 42))

    resp = client.post(
        "/gapscan/seed-queue/add",
        data={"key": key},
        files={"torrent": ("R.torrent", b"x", "application/x-bittorrent")},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `pytest tests/test_api.py -v -k seed_queue`
Expected: FAIL (`404 Not Found` sur les deux routes, `AttributeError: module has no attribute 'upload_history_store'`/`'QBittorrentClient'` sur `mod.upload_history_store`/`mod.QBittorrentClient`).

- [ ] **Step 3: Implémenter**

Dans `nfogen/api.py`, étendre le bloc d'import GapScan :

```python
    from . import (
        commit_job_runner,
        gapscan,
        gapscan_config_store,
        gapscan_library,
        gapscan_runner,
        tracker_profile,
        upload_history_store,
        upload_prep,
    )
    from .qbittorrent_client import QBittorrentClient, QBittorrentError
    from .radarr_client import RadarrClient, RadarrError
    from .sonarr_client import SonarrClient, SonarrError
    from .torznab_client import TorznabClient, TorznabError
```

Ajouter les deux endpoints après `gapscan_library_endpoint` (avant la section "Preparation d'upload") :

```python
@app.get("/gapscan/seed-queue", dependencies=[Depends(require_token)])
def gapscan_seed_queue() -> list[dict[str, Any]]:
    """Titres envoyes a C411 (voir POST /gapscan/prepare-upload/send) mais
    pas encore ajoutes a un client de seed -- AUTOMATION.md, sous-projet
    6. Aucun appel reseau : lecture seule de l'historique local."""
    _require_gapscan_available()
    return upload_history_store.pending_seed_entries()


@app.post("/gapscan/seed-queue/add", dependencies=[Depends(require_token)])
async def gapscan_seed_queue_add(
    key: str = Form(...),
    torrent: UploadFile = File(...),
) -> dict[str, str]:
    """Ajoute le .torrent RE-SIGNE (deja telecharge manuellement par
    l'utilisateur -- voir AUTOMATION.md, sous-projet 6, aucune
    recuperation automatique possible) au client de seed configure,
    pointe sur le contenu DEJA en scene (jamais retelecharge)."""
    _require_gapscan_available()
    qbittorrent_config = gapscan_config_store.effective_qbittorrent()
    if qbittorrent_config is None:
        raise HTTPException(status_code=400, detail="qBittorrent non configuré (PUT /gapscan/config).")

    entries = {e["key"]: e for e in upload_history_store.pending_seed_entries()}
    entry = entries.get(key)
    if entry is None:
        raise HTTPException(
            status_code=404, detail="Titre inconnu ou déjà ajouté à un client de seed."
        )
    staged_path = entry.get("staged_path")
    if not staged_path:
        raise HTTPException(
            status_code=400,
            detail="Chemin de mise en scène inconnu pour ce titre (confirmé avant l'ajout de ce champ ?).",
        )

    save_path = str(Path(staged_path).parent)
    torrent_bytes = await torrent.read()
    qb = QBittorrentClient(*qbittorrent_config)
    try:
        qb.add_torrent(torrent_bytes, save_path, filename=torrent.filename or "release.torrent")
    except QBittorrentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        qb.close()

    decoded_key = tuple(json.loads(key))
    upload_history_store.record(decoded_key, kind="seeding", release_name=entry["release_name"])
    return {"status": "added"}
```

`Form`/`File`/`UploadFile` sont déjà importés en haut du fichier (voir `from fastapi import ...`) — aucun ajout d'import nécessaire pour ceux-ci. `Path` (de `pathlib`) est déjà importé également.

- [ ] **Step 4: Lancer les tests**

Run: `pytest tests/test_api.py -v -k seed_queue`
Expected: PASS (tous les 5 nouveaux tests).

- [ ] **Step 5: Lancer toute la suite backend**

Run: `pytest -q`
Expected: PASS (0 échec).

- [ ] **Step 6: Commit, push, vérifier la CI**

```bash
git add nfogen/api.py tests/test_api.py
git commit -m "feat: GET/POST /gapscan/seed-queue -- mise en seed manuelle (sous-projet 6)"
git push origin main
```

Poller `https://api.github.com/repos/ICCUser/nfogen/actions/runs?branch=main&per_page=5` jusqu'à ce que le run dont `head_sha` correspond au dernier commit poussé ait un `conclusion` non nul. Si échec, corriger avant de continuer.

---

## Task 7: Frontend `types.ts`/`client.ts` — configuration qBittorrent + file d'attente

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `SeedQueueEntry` (type), `seedQueue(): Promise<SeedQueueEntry[]>`, `addToSeedQueue(key: string, file: File): Promise<{status: string}>` ; `GapscanConfig` gagne `qbittorrent_configured`/`qbittorrent_url`, `GapscanConfigWrite` gagne `qbittorrent_url`/`qbittorrent_username`/`qbittorrent_password`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `frontend/src/api/client.test.ts` :

```ts
describe("seedQueue / addToSeedQueue (AUTOMATION.md, sous-projet 6)", () => {
  it("seedQueue GET /gapscan/seed-queue", async () => {
    const entries = [
      { key: '["movie",42]', media_type: "movie", release_name: "R", staged_path: "/staging/R.mkv", sent_at: 1700000000 },
    ];
    vi.mocked(fetch).mockResolvedValue(jsonResponse(entries));

    const result = await seedQueue();

    expect(result).toEqual(entries);
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/seed-queue");
  });

  it("addToSeedQueue POST en multipart avec key et torrent", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "added" }));
    const file = new File([new Uint8Array([1, 2, 3])], "R.torrent");

    const result = await addToSeedQueue('["movie",42]', file);

    expect(result).toEqual({ status: "added" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/gapscan/seed-queue/add");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
    const body = (init as RequestInit).body as FormData;
    expect(body.get("key")).toBe('["movie",42]');
    expect(body.get("torrent")).toBe(file);
  });
});
```

Ajouter aux imports en haut du fichier : `addToSeedQueue`, `seedQueue`.

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd frontend && npx vitest run src/api/client.test.ts -t "seedQueue"`
Expected: FAIL (`seedQueue is not a function`).

- [ ] **Step 3: Implémenter**

Dans `frontend/src/api/types.ts`, modifier `GapscanConfig`/`GapscanConfigWrite` (déjà existants) :

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
  tracker_announce_url_configured: boolean;
  staging_dir: string | null;
  qbittorrent_configured: boolean;
  qbittorrent_url: string | null;
}

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
  qbittorrent_url?: string;
  qbittorrent_username?: string;
  qbittorrent_password?: string;
}
```

Ajouter après `LibraryResultsPage` :

```ts
// --------------------------------------------------------------------------- //
// File d'attente de mise en seed (AUTOMATION.md, sous-projet 6) : titres
// envoyes a C411 mais pas encore ajoutes a un client de seed. Import
// manuel du .torrent re-signe -- aucune API C411 ne permet de le
// recuperer automatiquement (verifie en conditions reelles, 2026-09-06).
// --------------------------------------------------------------------------- //
export interface SeedQueueEntry {
  key: string;
  media_type: "movie" | "series";
  release_name: string;
  staged_path: string | null;
  sent_at: number | null;
}
```

Dans `frontend/src/api/client.ts`, ajouter après `libraryResults` :

```ts
/** GET /gapscan/seed-queue : titres envoyes a C411 mais pas encore
 * ajoutes a un client de seed (AUTOMATION.md, sous-projet 6). */
export function seedQueue(): Promise<SeedQueueEntry[]> {
  return request<SeedQueueEntry[]>("/gapscan/seed-queue");
}

/** POST /gapscan/seed-queue/add : ajoute le .torrent RE-SIGNE (deja
 * telecharge manuellement par l'utilisateur) au client de seed, pointe
 * sur le contenu deja en scene. */
export function addToSeedQueue(key: string, file: File): Promise<{ status: string }> {
  const formData = new FormData();
  formData.set("key", key);
  formData.set("torrent", file);
  return request<{ status: string }>("/gapscan/seed-queue/add", { method: "POST", body: formData });
}
```

Ajouter `SeedQueueEntry` à l'import de types en haut de `client.ts`.

- [ ] **Step 4: Lancer les tests**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS (tous, y compris les tests existants).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: client API pour la configuration qBittorrent et la file de seed"
```

---

## Task 8: Frontend `LibraryPage.tsx` — champs de configuration qBittorrent

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Test: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `GapscanConfig.qbittorrent_configured`/`qbittorrent_url`, `GapscanConfigWrite.qbittorrent_url`/`qbittorrent_username`/`qbittorrent_password` (Task 7).

- [ ] **Step 1: Écrire le test**

Ajouter à `frontend/src/pages/LibraryPage.test.tsx` (réutiliser `renderPage`/`CONFIGURED` déjà présents — étendre `CONFIGURED` avec `qbittorrent_configured: false, qbittorrent_url: null` pour rester un objet complet) :

```ts
it("enregistre la configuration qBittorrent via le formulaire de configuration", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanConfigWrite).mockResolvedValue({
    ...CONFIGURED, qbittorrent_configured: true, qbittorrent_url: "http://qbittorrent.local:8080",
  });

  renderPage();
  await user.click(await screen.findByRole("button", { name: /Configuration/ }));

  await user.type(screen.getByLabelText("URL qBittorrent"), "http://qbittorrent.local:8080");
  await user.type(screen.getByLabelText("Utilisateur qBittorrent"), "admin");
  await user.type(screen.getByLabelText("Mot de passe qBittorrent"), "secret");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));

  expect(gapscanConfigWrite).toHaveBeenCalledWith(
    expect.objectContaining({
      qbittorrent_url: "http://qbittorrent.local:8080",
      qbittorrent_username: "admin",
      qbittorrent_password: "secret",
    }),
    "c411",
  );
});
```

Mettre à jour la constante `CONFIGURED` du même fichier pour inclure les 2 nouveaux champs obligatoires du type `GapscanConfig` :

```ts
const CONFIGURED: GapscanConfig = {
  profile: "c411",
  tracker_configured: true,
  tracker_base_url: "https://c411.org",
  sonarr_configured: false,
  sonarr_url: null,
  radarr_configured: true,
  radarr_url: "http://radarr.local:7878",
  sonarr_path_mappings: {},
  radarr_path_mappings: {},
  tracker_announce_url_configured: false,
  staging_dir: null,
  qbittorrent_configured: false,
  qbittorrent_url: null,
};
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx`
Expected: FAIL (erreur de typage sur `CONFIGURED` incomplet dès la compilation, puis `getByLabelText("URL qBittorrent")` introuvable une fois le type corrigé).

- [ ] **Step 3: Implémenter**

Dans `frontend/src/pages/LibraryPage.tsx`, ajouter les états (à côté de `stagingDir`) :

```tsx
  const [qbittorrentUrl, setQbittorrentUrl] = useState("");
  const [qbittorrentUsername, setQbittorrentUsername] = useState("");
  const [qbittorrentPassword, setQbittorrentPassword] = useState("");
```

Dans l'effet qui charge la config (`gapscanConfig(profile).then((c) => {...})`), ajouter :

```tsx
        setQbittorrentUrl(c.qbittorrent_url ?? "");
```

(le mot de passe/utilisateur ne sont jamais renvoyés par l'API, comme les autres clés — restent vides tant que l'utilisateur ne les retape pas, même patron que `sonarrApiKey`/`trackerApiKey`).

Dans `handleSaveConfig()`, ajouter avant l'appel à `gapscanConfigWrite` :

```tsx
      if (qbittorrentUrl.trim()) fields.qbittorrent_url = qbittorrentUrl.trim();
      if (qbittorrentUsername.trim()) fields.qbittorrent_username = qbittorrentUsername.trim();
      if (qbittorrentPassword.trim()) fields.qbittorrent_password = qbittorrentPassword.trim();
```

et après la sauvegarde réussie, réinitialiser le mot de passe (même patron que `trackerApiKey`) :

```tsx
      setQbittorrentPassword("");
```

Dans le JSX du formulaire de configuration, ajouter trois champs dans la `<div className="grid grid-cols-2 gap-3">` existante (après le champ "Dossier de mise en scène") :

```tsx
              <label className="block text-sm font-medium text-ink-dim">
                URL qBittorrent
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  placeholder="http://qbittorrent.local:8080"
                  value={qbittorrentUrl}
                  onChange={(e) => setQbittorrentUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Utilisateur qBittorrent
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  value={qbittorrentUsername}
                  onChange={(e) => setQbittorrentUsername(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Mot de passe qBittorrent
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={config?.qbittorrent_configured ? "•••• (enregistré)" : ""}
                  value={qbittorrentPassword}
                  onChange={(e) => setQbittorrentPassword(e.target.value)}
                />
              </label>
```

- [ ] **Step 4: Lancer les tests**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat: LibraryPage expose la configuration qBittorrent"
```

---

## Task 9: Frontend `SeedQueuePage.tsx` (nouveau) + route + navigation

**Files:**
- Create: `frontend/src/pages/SeedQueuePage.tsx`
- Test: `frontend/src/pages/SeedQueuePage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `seedQueue()`, `addToSeedQueue(key, file)` (Task 7).

- [ ] **Step 1: Écrire le test de la page**

Créer `frontend/src/pages/SeedQueuePage.test.tsx` :

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  seedQueue: vi.fn(),
  addToSeedQueue: vi.fn(),
}));

import { addToSeedQueue, seedQueue } from "../api/client";
import SeedQueuePage from "./SeedQueuePage";
import type { SeedQueueEntry } from "../api/types";

const ENTRY: SeedQueueEntry = {
  key: '["movie",42]', media_type: "movie", release_name: "Movie.2020.1080p.x264-TEAM",
  staged_path: "/staging/Movie.2020.1080p.x264-TEAM.mkv", sent_at: 1700000000,
};

function renderPage() {
  return render(<SeedQueuePage />);
}

beforeEach(() => {
  vi.mocked(seedQueue).mockReset();
  vi.mocked(addToSeedQueue).mockReset();
});

describe("SeedQueuePage", () => {
  it("charge et affiche la file d'attente au montage", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    renderPage();
    expect(await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/)).toBeInTheDocument();
  });

  it("liste vide : message explicite", async () => {
    vi.mocked(seedQueue).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/Aucun titre en attente/i)).toBeInTheDocument();
  });

  it("depose un fichier puis clique Ajouter -- appelle addToSeedQueue, retire la ligne", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    vi.mocked(addToSeedQueue).mockResolvedValue({ status: "added" });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/);
    const file = new File([new Uint8Array([1, 2, 3])], "Movie.2020.1080p.x264-TEAM.torrent");
    const input = screen.getByLabelText(/torrent re-signé/i);
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: /Ajouter au client de seed/i }));

    await waitFor(() => {
      expect(addToSeedQueue).toHaveBeenCalledWith(ENTRY.key, file);
    });
    await waitFor(() => {
      expect(screen.queryByText(/Movie\.2020\.1080p\.x264-TEAM/)).not.toBeInTheDocument();
    });
  });

  it("erreur d'ajout : message affiche, la ligne reste presente", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    vi.mocked(addToSeedQueue).mockRejectedValue(new Error("qBittorrent injoignable"));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/);
    const file = new File([new Uint8Array([1, 2, 3])], "Movie.2020.1080p.x264-TEAM.torrent");
    await user.upload(screen.getByLabelText(/torrent re-signé/i), file);
    await user.click(screen.getByRole("button", { name: /Ajouter au client de seed/i }));

    expect(await screen.findByText(/injoignable/i)).toBeInTheDocument();
    expect(screen.getByText(/Movie\.2020\.1080p\.x264-TEAM/)).toBeInTheDocument();
  });

  it("le bouton Ajouter est desactive sans fichier choisi", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    renderPage();
    await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/);
    expect(screen.getByRole("button", { name: /Ajouter au client de seed/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run src/pages/SeedQueuePage.test.tsx`
Expected: FAIL (`Cannot find module './SeedQueuePage'`).

- [ ] **Step 3: Implémenter la page**

Créer `frontend/src/pages/SeedQueuePage.tsx` :

```tsx
import { useEffect, useState } from "react";
import { addToSeedQueue, seedQueue } from "../api/client";
import { ApiError } from "../api/types";
import type { SeedQueueEntry } from "../api/types";

/** Page "À mettre en seed" (AUTOMATION.md, sous-projet 6) : titres déjà
 * envoyés à C411 (voir "Envoyer à C411", sous-projet 5) en attente du
 * `.torrent` RE-SIGNÉ par le tracker une fois la modération terminée --
 * ce fichier ne peut être récupéré qu'en le téléchargeant soi-même
 * (aucune API ne le permet, vérifié en conditions réelles) : dépose-le
 * ici une fois en main, nfogen l'ajoute au client de seed pointé sur le
 * contenu déjà mis en scène (jamais un nouveau transfert). */
export default function SeedQueuePage() {
  const [entries, setEntries] = useState<SeedQueueEntry[] | null>(null);
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [adding, setAdding] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const list = await seedQueue();
      setEntries(list);
    } catch (e) {
      setEntries(null);
      setLoadError(e instanceof ApiError ? e.message : "File d'attente indisponible.");
    }
  }

  async function handleAdd(entry: SeedQueueEntry) {
    const file = files[entry.key];
    if (!file) return;
    setAdding(entry.key);
    setErrors((prev) => ({ ...prev, [entry.key]: "" }));
    try {
      await addToSeedQueue(entry.key, file);
      setEntries((prev) => (prev ? prev.filter((e) => e.key !== entry.key) : prev));
    } catch (e) {
      setErrors((prev) => ({
        ...prev,
        [entry.key]: e instanceof ApiError || e instanceof Error ? e.message : "Ajout impossible.",
      }));
    } finally {
      setAdding(null);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-xl font-semibold text-ink">À mettre en seed</h1>
        <p className="text-sm text-ink-dim">
          Titres déjà envoyés au tracker, en attente du <code>.torrent</code> re-signé une fois la
          modération terminée — télécharge-le depuis le site puis dépose-le ici.
        </p>
      </div>

      {loadError && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">{loadError}</div>
      )}

      {entries === null && !loadError && <p className="text-sm text-ink-faint">Chargement…</p>}
      {entries !== null && entries.length === 0 && (
        <p className="text-sm text-ink-faint">Aucun titre en attente de mise en seed.</p>
      )}

      {entries !== null && entries.length > 0 && (
        <ul className="space-y-3">
          {entries.map((entry) => (
            <li key={entry.key} className="space-y-2 rounded-md border border-line bg-surface p-4">
              <p className="font-mono text-sm font-medium text-ink">{entry.release_name}</p>
              <div className="flex items-center gap-3">
                <label className="block text-xs font-medium text-ink-dim">
                  Fichier .torrent re-signé
                  <input
                    aria-label="Fichier .torrent re-signé"
                    type="file"
                    accept=".torrent"
                    onChange={(e) => setFiles((prev) => ({ ...prev, [entry.key]: e.target.files?.[0] }))}
                    className="mt-1 block text-sm text-ink"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => handleAdd(entry)}
                  disabled={!files[entry.key] || adding === entry.key}
                  className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
                >
                  {adding === entry.key ? "Ajout…" : "Ajouter au client de seed"}
                </button>
              </div>
              {errors[entry.key] && <p className="text-xs text-crit">{errors[entry.key]}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Lancer les tests de la page**

Run: `cd frontend && npx vitest run src/pages/SeedQueuePage.test.tsx`
Expected: PASS (tous les 5 tests).

- [ ] **Step 5: Écrire le test de navigation**

Ajouter à `frontend/src/App.test.tsx` (réutiliser `libraryResults`/mocks déjà en place, ajouter `seedQueue: vi.fn()` au mock de `./api/client` avec `vi.mocked(seedQueue).mockResolvedValue([])` dans `beforeEach`) :

```tsx
it("affiche un lien de navigation vers la file de seed (AUTOMATION.md, sous-projet 6)", async () => {
  render(
    <MemoryRouter initialEntries={["/library"]}>
      <App />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("link", { name: /À mettre en seed/i })).toBeInTheDocument();
});
```

- [ ] **Step 6: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "file de seed"`
Expected: FAIL (lien introuvable).

- [ ] **Step 7: Implémenter la route et le lien de navigation**

Dans `frontend/src/App.tsx`, ajouter l'import :

```tsx
import SeedQueuePage from "./pages/SeedQueuePage";
```

Ajouter le lien de navigation (après "Bibliothèque", avant "Réglages") :

```tsx
            <NavLink to="/library" className={navClass}>
              Bibliothèque
            </NavLink>
            <NavLink to="/seed-queue" className={navClass}>
              À mettre en seed
            </NavLink>
            <NavLink to="/settings" className={navClass}>
```

Ajouter la route :

```tsx
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/seed-queue" element={<SeedQueuePage />} />
```

- [ ] **Step 8: Lancer toute la suite frontend**

Run: `cd frontend && npx vitest run`
Expected: PASS (0 échec).

- [ ] **Step 9: Typecheck, lint, build**

Run: `cd frontend && npx tsc -b --noEmit && npx oxlint src/ && npx vite build`
Expected: aucune erreur.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/SeedQueuePage.tsx frontend/src/pages/SeedQueuePage.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: page 'A mettre en seed' (import manuel du torrent re-signe, sous-projet 6)"
```

---

## Task 10: Push, CI, documentation

- [ ] **Step 1: Lancer la suite backend complète une dernière fois**

Run: `pytest -q`
Expected: PASS (0 échec).

- [ ] **Step 2: Push et poller GitHub Actions jusqu'à un run terminé**

```bash
git push origin main
```

Poller `https://api.github.com/repos/ICCUser/nfogen/actions/runs?branch=main&per_page=5` jusqu'à `conclusion` non nul pour le `head_sha` de ce commit. Si échec, corriger avant de continuer.

- [ ] **Step 3: Mettre à jour `AUTOMATION.md`**

Modifier la ligne du sous-projet 6 dans le tableau de décomposition (près de la ligne "État") :

```markdown
| 6 | Intégration qBittorrent (récupération du `.torrent` signé, mise en seed) | **Livré (2026-09-06)**, voir [le plan](docs/superpowers/plans/2026-09-06-qbittorrent-seed-integration.md) |
```

Ajouter une nouvelle section après la section du sous-projet 5 (ou celle du sous-projet 8, selon l'ordre actuel du fichier — chercher `## Sous-projet 8` et insérer juste avant si elle existe déjà, sinon en fin de fichier) :

```markdown
## Sous-projet 6 : Intégration qBittorrent (conception et livraison 2026-09-06)

**Récupération du `.torrent` re-signé : manuelle, confirmé impossible à
automatiser.** Test réel (2026-09-06) : `GET
https://c411.org/api/torrents/{infoHash}/download` avec la clé API
Bearer du compte renvoie `302` vers `/login?redirect=...` — cet endpoint
exige une session navigateur authentifiée, pas la clé API. Aucune
automatisation de la récupération n'est donc possible sans reproduire un
login complet (hors de portée de ce projet).

**Nouvelle file d'attente "À mettre en seed"** (`/seed-queue`) : liste
les titres déjà envoyés à C411 (voir sous-projet 5) mais pas encore
ajoutés à un client de seed (`GET /gapscan/seed-queue`, alimentée par
`upload_history_store.pending_seed_entries()`). Pour chaque titre,
l'utilisateur dépose le `.torrent` re-signé (téléchargé manuellement
depuis le site une fois la modération terminée) — nfogen l'ajoute à
qBittorrent (`nfogen/qbittorrent_client.py`, même patron httpx que
`radarr_client.py`/`sonarr_client.py`) pointé sur le contenu **déjà mis
en scène** (`upload_history_store` persiste désormais le `staged_path`
de chaque titre confirmé, pour le retrouver même longtemps après le
Confirmer d'origine — la modération C411 n'est pas immédiate). Jamais un
nouveau transfert, jamais un nouveau téléchargement.

Explicitement écarté : nettoyage automatique du dossier de mise en scène
après ajout au seed (qBittorrent "possède" le contenu du point de vue de
l'utilisateur une fois ajouté ; un nettoyage éventuel reste manuel, côté
qBittorrent) ; support Transmission (uniquement qBittorrent pour ce
sous-projet, même patron réutilisable plus tard si besoin).

Voir [docs/superpowers/specs/2026-09-06-qbittorrent-seed-integration-design.md](docs/superpowers/specs/2026-09-06-qbittorrent-seed-integration-design.md)
et [docs/superpowers/plans/2026-09-06-qbittorrent-seed-integration.md](docs/superpowers/plans/2026-09-06-qbittorrent-seed-integration.md).
```

- [ ] **Step 4: Mettre à jour `CHANGELOG.md`**

Ajouter une entrée sous la section `### Ajouté` la plus récente (sous `## [Non publié]`) :

```markdown
- **Intégration qBittorrent — mise en seed après upload** (AUTOMATION.md,
  sous-projet 6) : nouvelle file d'attente "À mettre en seed"
  (`/seed-queue`) pour les titres déjà envoyés à C411 en attente du
  `.torrent` re-signé (récupération confirmée impossible à automatiser —
  l'endpoint C411 exige une session navigateur, pas la clé API — import
  manuel donc). nfogen l'ajoute alors à qBittorrent, pointé sur le
  contenu déjà mis en scène (jamais un nouveau transfert), même
  longtemps après le Confirmer d'origine.
```

- [ ] **Step 5: Commit et push**

```bash
git add AUTOMATION.md CHANGELOG.md
git commit -m "docs: sous-projet 6 livre - AUTOMATION.md et CHANGELOG.md a jour"
git push origin main
```

Poller GitHub Actions une dernière fois jusqu'à `conclusion` non nul sur ce commit.

---

## Self-Review

**Couverture de la spec** : problème/non-objectifs (récupération manuelle confirmée, pas de cleanup automatique, qBittorrent seul) → reflétés dans Task 9's copy et le Global Constraints. Architecture (qbittorrent_client.py, staged_path persisté, GET/POST seed-queue, page frontend) → Tasks 1, 3, 4, 6, 9. Configuration qBittorrent (gapscan_config_store + PUT/GET config + formulaire) → Tasks 2, 5, 8. Gestion des erreurs (400 sans config, 404 clé inconnue, 400 staged_path manquant, 400 sur QBittorrentError) → Task 6. Tous les points de la section "Tests" de la spec ont une tâche correspondante.

**Cohérence des types** : `pending_seed_entries()` (Task 3) renvoie exactement les clés (`key`, `media_type`, `release_name`, `staged_path`, `sent_at`) consommées par `GET /gapscan/seed-queue` (Task 6) puis par `SeedQueueEntry` côté frontend (Task 7) et `SeedQueuePage.tsx` (Task 9) — mêmes noms de bout en bout. `QBittorrentClient.add_torrent(torrent_bytes, save_path, filename)` (Task 1) est appelé avec cette signature exacte dans `POST /gapscan/seed-queue/add` (Task 6).

**Aucun placeholder** : chaque étape contient du code réel ; les rares réutilisations de patron existant (`_stub_resolve_staging_config`, `reload_api`, `renderPage`) nomment explicitement le fichier où les retrouver plutôt que de les décrire vaguement.
