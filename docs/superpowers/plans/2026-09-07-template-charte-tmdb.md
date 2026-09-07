# Enrichissement template upload + charte graphique nfogen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (pas de subagents sur ce projet — preference utilisateur etablie). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrichir `upload_description.j2` (Pays/Createur(s)/Note TMDB/IMDB via un nouveau client TMDB, tableau audio/sous-titres par piste avec drapeaux, bannieres de section aux couleurs de l'appli) et migrer la config globale (Sonarr/Radarr/qBittorrent/TMDB) de `LibraryPage` vers `SettingsPage`.

**Architecture:** Nouveau module `nfogen/tmdb_client.py` (meme style que radarr/sonarr_client.py), nouveau module `nfogen/languages.py` (mapping langue -> drapeau), extension de `nfogen/extract.py` (details par piste MediaInfo), 4 bannieres PNG statiques generees une fois par un script dev-only et commitees dans `assets/banners/`, refonte de `upload_description.j2` et de `upload_prep.send_to_tracker()` pour assembler tout ce contexte, migration frontend du panneau de config globale.

**Tech Stack:** Python 3.10+, httpx (deja present), pymediainfo (deja present), Pillow (nouvelle dependance **dev-only**, generation d'assets hors runtime), Jinja2 (deja present), React/TypeScript (frontend existant).

**Spec:** [docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md](../specs/2026-09-07-template-charte-tmdb-design.md)

## Global Constraints

- Toute nouvelle donnee (TMDB ou MediaInfo par piste) reste optionnelle : son absence n'interrompt jamais `send_to_tracker()` ni le rendu du template.
- Cle API TMDB : globale (pas namespacee par profil), stockee comme les autres cles dans `gapscan_config_store` (fichier JSON + repli variable d'environnement `NFOGEN_TMDB_API_KEY`).
- `TMDBClient` leve `TMDBError` sur toute erreur — c'est **l'appelant** (`send_to_tracker`) qui attrape et degrade silencieusement, jamais le client lui-meme.
- Bannieres : assets statiques pre-generes une seule fois (pas de generation a la volee), commitees dans `assets/banners/`, servies via `https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/<nom>.png`.
- Couleurs bannieres : fond `#141d19`, texte/icone `#6bc9b3` (valeurs reelles de `frontend/src/index.css`, theme sombre).
- Pillow est une dependance **dev-only** (`[project.optional-dependencies].dev`), jamais requise pour faire tourner nfogen normalement.
- `LibraryPage.tsx` garde uniquement le panneau "Configuration du profil" ; le panneau "Configuration globale" (avec le nouveau champ TMDB) migre integralement vers `SettingsPage.tsx`.

---

### Task 1 : Cle API TMDB dans la config globale (backend)

**Files:**
- Modify: `nfogen/gapscan_config_store.py`
- Modify: `nfogen/api.py`
- Test: `tests/test_gapscan_config_store.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `gapscan_config_store.effective_tmdb_api_key() -> Optional[str]`, `write(..., tmdb_api_key: Optional[str] = None)`, `status()["tmdb_configured"]: bool`.

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_gapscan_config_store.py`, ajoute (adapte au pattern des tests existants de ce fichier pour `qbittorrent_verify_ssl`/`sonarr_api_key`, meme fixture `tmp_path`/`monkeypatch` que le reste du fichier) :

```python
def test_write_and_read_tmdb_api_key(config_file, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(config_file))
    gapscan_config_store.write(tmdb_api_key="tmdb-secret-key")
    assert gapscan_config_store.effective_tmdb_api_key() == "tmdb-secret-key"


def test_effective_tmdb_api_key_falls_back_to_env_var(config_file, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("NFOGEN_TMDB_API_KEY", "env-tmdb-key")
    assert gapscan_config_store.effective_tmdb_api_key() == "env-tmdb-key"


def test_status_reports_tmdb_configured_without_leaking_key(config_file, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(config_file))
    gapscan_config_store.write(tmdb_api_key="tmdb-secret-key")
    status = gapscan_config_store.status()
    assert status["tmdb_configured"] is True
    assert "tmdb-secret-key" not in json.dumps(status)
```

Verifie d'abord les noms exacts de fixtures deja utilisees dans ce fichier de test (`config_file` est un exemple probable — reprends le nom REEL de la fixture existante utilisee par `test_write_and_read_sonarr_url` ou equivalent, ne l'invente pas).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_config_store.py -k tmdb -v`
Expected: FAIL (`effective_tmdb_api_key` n'existe pas encore).

- [ ] **Step 3: Implement**

Dans `nfogen/gapscan_config_store.py`, ajoute `tmdb_api_key: Optional[str] = None` a la signature de `write()` et a `top_level_updates` :

```python
    qbittorrent_verify_ssl: Optional[bool] = None,
    tmdb_api_key: Optional[str] = None,
) -> None:
    ...
    top_level_updates = {
        ...
        "qbittorrent_verify_ssl": qbittorrent_verify_ssl,
        "tmdb_api_key": tmdb_api_key,
    }
```

Ajoute la fonction (a cote de `effective_qbittorrent`) :

```python
def effective_tmdb_api_key() -> Optional[str]:
    """Cle API TMDB (v3, parametre de requete `api_key`) -- GLOBALE, pas
    namespacee par profil de tracker (voir tmdb_client.py). `None` si non
    configuree : l'enrichissement TMDB du template reste best-effort."""
    return _resolve("tmdb_api_key", "NFOGEN_TMDB_API_KEY")
```

Dans `status()`, ajoute :

```python
    return {
        ...
        "qbittorrent_verify_ssl": qbittorrent[3] if qbittorrent else True,
        "tmdb_configured": effective_tmdb_api_key() is not None,
    }
```

Dans `nfogen/api.py`, `GapscanConfigWriteRequest` gagne :

```python
    tmdb_api_key: Optional[str] = None
```

(pas d'autre changement necessaire — `gapscan_config_write` transmet deja tous les champs via `**fields`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_config_store.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nfogen/gapscan_config_store.py nfogen/api.py tests/test_gapscan_config_store.py tests/test_api.py
git commit -m "feat: cle API TMDB dans la config globale (gapscan_config_store)"
```

---

### Task 2 : Mapping langue -> drapeau (`nfogen/languages.py`, nouveau)

**Files:**
- Create: `nfogen/languages.py`
- Test: `tests/test_languages.py`

**Interfaces:**
- Produces: `resolve_language(code: str) -> tuple[str, Optional[str]]` (nom affiche FR, code drapeau ISO 3166-1 alpha-2 ou `None`), `flagcdn_url(flag_code: str) -> str`.
- Consumes: rien (module autonome).

- [ ] **Step 1: Write the failing test**

```python
"""Tests de nfogen.languages (mapping code MediaInfo -> nom affiche +
drapeau, utilise par upload_prep.py pour le tableau audio/sous-titres)."""
from __future__ import annotations

from nfogen.languages import flagcdn_url, resolve_language


def test_resolve_language_known_codes():
    assert resolve_language("fre") == ("Français", "fr")
    assert resolve_language("fr") == ("Français", "fr")
    assert resolve_language("eng") == ("Anglais", "gb")
    assert resolve_language("jpn") == ("Japonais", "jp")


def test_resolve_language_is_case_insensitive():
    assert resolve_language("FRE") == ("Français", "fr")


def test_resolve_language_unknown_code_returns_raw_with_no_flag():
    assert resolve_language("und") == ("und", None)
    assert resolve_language("") == ("", None)


def test_flagcdn_url_builds_expected_url():
    assert flagcdn_url("fr") == "https://flagcdn.com/20x15/fr.png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_languages.py -v`
Expected: FAIL (`ModuleNotFoundError: nfogen.languages`)

- [ ] **Step 3: Implement**

```python
"""Mapping code langue MediaInfo -> (nom affiche FR, code drapeau ISO
3166-1 alpha-2) -- utilise par upload_prep.py pour construire le tableau
BBCode audio/sous-titres (voir upload_description.j2). Couverture
volontairement restreinte aux langues courantes d'upload -- une langue
non reconnue est affichee telle quelle, sans drapeau (jamais une
supposition)."""
from __future__ import annotations

from typing import Optional

LANGUAGE_INFO: dict[str, tuple[str, str]] = {
    "fr": ("Français", "fr"), "fre": ("Français", "fr"), "fra": ("Français", "fr"),
    "french": ("Français", "fr"),
    "en": ("Anglais", "gb"), "eng": ("Anglais", "gb"), "english": ("Anglais", "gb"),
    "ja": ("Japonais", "jp"), "jpn": ("Japonais", "jp"), "japanese": ("Japonais", "jp"),
    "es": ("Espagnol", "es"), "spa": ("Espagnol", "es"), "spanish": ("Espagnol", "es"),
    "de": ("Allemand", "de"), "ger": ("Allemand", "de"), "deu": ("Allemand", "de"),
    "german": ("Allemand", "de"),
    "it": ("Italien", "it"), "ita": ("Italien", "it"), "italian": ("Italien", "it"),
    "pt": ("Portugais", "pt"), "por": ("Portugais", "pt"), "portuguese": ("Portugais", "pt"),
    "nl": ("Néerlandais", "nl"), "dut": ("Néerlandais", "nl"), "nld": ("Néerlandais", "nl"),
    "ru": ("Russe", "ru"), "rus": ("Russe", "ru"), "russian": ("Russe", "ru"),
    "ko": ("Coréen", "kr"), "kor": ("Coréen", "kr"), "korean": ("Coréen", "kr"),
    "zh": ("Chinois", "cn"), "chi": ("Chinois", "cn"), "zho": ("Chinois", "cn"),
}


def resolve_language(code: Optional[str]) -> tuple[str, Optional[str]]:
    """`(nom affiche, code drapeau)` -- code brut et `None` si la langue
    n'est pas reconnue (jamais de plantage, jamais de drapeau invente)."""
    if not code:
        return code or "", None
    info = LANGUAGE_INFO.get(code.strip().lower())
    return info if info else (code, None)


def flagcdn_url(flag_code: str) -> str:
    """URL du drapeau (service public flagcdn.com, meme taille/service que
    l'exemple de reference C411)."""
    return f"https://flagcdn.com/20x15/{flag_code}.png"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_languages.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nfogen/languages.py tests/test_languages.py
git commit -m "feat: mapping langue -> drapeau (nfogen/languages.py)"
```

---

### Task 3 : Client TMDB (`nfogen/tmdb_client.py`, nouveau)

**Files:**
- Create: `nfogen/tmdb_client.py`
- Test: `tests/test_tmdb_client.py`

**Interfaces:**
- Produces: `TMDBError(RuntimeError)`, `TMDBExtraDetails(country, vote_average, creators)`, `TMDBClient(api_key, http_client=None, timeout=30.0)` avec `get_movie_extra(tmdb_id: int) -> TMDBExtraDetails` et `get_series_extra(tmdb_id: int) -> TMDBExtraDetails`.
- Consumes : rien (module autonome, meme style que `radarr_client.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests de nfogen.tmdb_client (transport HTTP mocke, aucun reseau reel) --
enrichissement best-effort du template d'upload (Pays/Createur(s)/Note),
voir docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md."""
from __future__ import annotations

import httpx
import pytest

from nfogen.tmdb_client import TMDBClient, TMDBError


def _client(handler) -> TMDBClient:
    return TMDBClient(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


MOVIE_RESPONSE = {
    "production_countries": [{"name": "United States of America"}],
    "vote_average": 8.365,
    "created_by": [],
}

SERIES_RESPONSE = {
    "production_countries": [{"name": "United States of America"}],
    "vote_average": 8.4,
    "created_by": [{"name": "Tom Kapinos"}],
}


def test_get_movie_extra_parses_country_and_rating():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/movie/603"
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json=MOVIE_RESPONSE)

    client = _client(handler)
    extra = client.get_movie_extra(603)
    assert extra.country == "United States of America"
    assert extra.vote_average == 8.4  # arrondi a 1 decimale
    assert extra.creators == []


def test_get_series_extra_parses_creators():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/tv/63174"
        return httpx.Response(200, json=SERIES_RESPONSE)

    client = _client(handler)
    extra = client.get_series_extra(63174)
    assert extra.creators == ["Tom Kapinos"]
    assert extra.country == "United States of America"


def test_missing_production_countries_leaves_country_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"production_countries": [], "vote_average": 0})

    client = _client(handler)
    extra = client.get_movie_extra(1)
    assert extra.country is None
    assert extra.vote_average is None  # 0 traite comme "jamais note" -> absent


def test_http_error_raises_tmdb_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status_message": "Invalid API key"})

    client = _client(handler)
    with pytest.raises(TMDBError):
        client.get_movie_extra(1)


def test_network_error_raises_tmdb_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(TMDBError):
        client.get_series_extra(1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tmdb_client.py -v`
Expected: FAIL (`ModuleNotFoundError: nfogen.tmdb_client`)

- [ ] **Step 3: Implement**

```python
"""Client pour l'API TMDB (v3, auth par parametre `api_key`), lecture
seule -- complete Radarr/Sonarr pour les 3 champs absents des deux API
(confirme par des dumps reels, voir docs/superpowers/specs/
2026-09-07-template-charte-tmdb-design.md) : pays de production,
createur(s) (series), note TMDB. Best-effort par construction : toute
erreur leve `TMDBError`, a l'appelant (upload_prep.send_to_tracker) de
l'attraper et de continuer sans ces champs -- jamais silencieux ici."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

_BASE_URL = "https://api.themoviedb.org/3"


class TMDBError(RuntimeError):
    """Erreur reseau, authentification ou reponse inattendue de l'API TMDB."""


@dataclass
class TMDBExtraDetails:
    country: Optional[str] = None
    vote_average: Optional[float] = None
    creators: list[str] = field(default_factory=list)


class TMDBClient:
    """Client HTTP pour l'API v3 de TMDB."""

    def __init__(
        self,
        api_key: str,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise TMDBError("Clé API TMDB manquante.")
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TMDBClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.get(
                f"{_BASE_URL}{path}", params={"api_key": self._api_key}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TMDBError(f"Appel TMDB échoué ({path}) : {exc}") from exc
        return response.json()

    @staticmethod
    def _country(data: dict[str, Any]) -> Optional[str]:
        countries = data.get("production_countries") or []
        return countries[0].get("name") if countries else None

    @staticmethod
    def _vote_average(data: dict[str, Any]) -> Optional[float]:
        value = data.get("vote_average")
        return round(value, 1) if value else None  # 0/None traites comme "jamais note"

    def get_movie_extra(self, tmdb_id: int) -> TMDBExtraDetails:
        data = self._get(f"/movie/{tmdb_id}")
        return TMDBExtraDetails(country=self._country(data), vote_average=self._vote_average(data))

    def get_series_extra(self, tmdb_id: int) -> TMDBExtraDetails:
        data = self._get(f"/tv/{tmdb_id}")
        creators = [c["name"] for c in data.get("created_by", []) if c.get("name")]
        return TMDBExtraDetails(
            country=self._country(data), vote_average=self._vote_average(data), creators=creators
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tmdb_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nfogen/tmdb_client.py tests/test_tmdb_client.py
git commit -m "feat: client TMDB (pays/createurs/note) -- nfogen/tmdb_client.py"
```

---

### Task 4 : IMDB id dans les details Radarr/Sonarr

**Files:**
- Modify: `nfogen/radarr_client.py`
- Modify: `nfogen/sonarr_client.py`
- Test: `tests/test_radarr_client.py`
- Test: `tests/test_sonarr_client.py`

**Interfaces:**
- Produces: `RadarrMovieDetails.imdb_id: Optional[str]`, `SonarrSeriesDetails.imdb_id: Optional[str]` (utilises par Task 7 pour construire le lien IMDB — pas besoin d'appel TMDB pour ca).

- [ ] **Step 1: Write the failing tests**

Dans `tests/test_radarr_client.py`, etend le test existant
`test_get_movie_details_parses_overview_poster_genres_credits` (ou ajoute
un test dedie, reprends le JSON de fixture deja utilise par ce test dans
le fichier et ajoute `"imdbId": "tt1375666"`) :

```python
def test_get_movie_details_parses_imdb_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"imdbId": "tt1375666"})

    client = _client(handler)
    details = client.get_movie_details(1)
    assert details.imdb_id == "tt1375666"
```

Dans `tests/test_sonarr_client.py`, meme principe :

```python
def test_get_series_details_parses_imdb_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"imdbId": "tt4052886"})

    client = _client(handler)
    details = client.get_series_details(1)
    assert details.imdb_id == "tt4052886"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_radarr_client.py tests/test_sonarr_client.py -k imdb -v`
Expected: FAIL (`AttributeError: 'RadarrMovieDetails' object has no attribute 'imdb_id'`)

- [ ] **Step 3: Implement**

Dans `nfogen/radarr_client.py`, `RadarrMovieDetails` gagne (apres `certification`) :
```python
    imdb_id: Optional[str] = None
```
Dans `get_movie_details()`, ajoute a la construction du retour :
```python
        return RadarrMovieDetails(
            ...
            certification=movie.get("certification") or None,
            imdb_id=movie.get("imdbId") or None,
        )
```

Meme changement symetrique dans `nfogen/sonarr_client.py` :
```python
    imdb_id: Optional[str] = None
```
```python
        return SonarrSeriesDetails(
            ...
            certification=series.get("certification") or None,
            imdb_id=series.get("imdbId") or None,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_radarr_client.py tests/test_sonarr_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nfogen/radarr_client.py nfogen/sonarr_client.py tests/test_radarr_client.py tests/test_sonarr_client.py
git commit -m "feat: imdb_id dans RadarrMovieDetails/SonarrSeriesDetails"
```

---

### Task 5 : Extraction MediaInfo par piste (audio/sous-titres)

**Files:**
- Modify: `nfogen/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Produces: `extract_video_metadata()` gagne les cles `"audio_tracks": list[dict]` (`language`, `channels`, `codec`, `bit_rate_kbps`, `sampling_khz`) et `"subtitle_tracks": list[dict]` (`language`, `forced: bool`) — les cles existantes `audio_languages`/`subtitle_languages` restent inchangees (utilisees ailleurs).

- [ ] **Step 1: Write the failing test**

Regarde d'abord comment `tests/test_extract.py` mocke `pymediainfo.MediaInfo`
(cherche `MediaInfo.parse` ou une classe `_FakeTrack`/`_FakeMediaInfo`
existante dans ce fichier et reutilise EXACTEMENT le meme mecanisme —
ne cree pas un deuxieme systeme de mock en parallele). En t'appuyant sur
ce mecanisme existant, ajoute :

```python
def test_extract_video_metadata_returns_audio_tracks_detail(monkeypatch, tmp_path):
    # Adapte le mock de piste Audio existant pour porter en plus
    # channel_s="5.1", format="AC-3", bit_rate=448000, sampling_rate=48000,
    # language="fre" -- reprends le nom des attributs deja mockes ailleurs
    # dans ce fichier pour une piste Audio (pas de nouvel attribut invente).
    ...
    meta = extract.extract_video_metadata(video_path)
    assert meta["audio_tracks"] == [
        {"language": "fre", "channels": "5.1", "codec": "AC-3",
         "bit_rate_kbps": 448, "sampling_khz": 48.0},
    ]


def test_extract_video_metadata_returns_subtitle_tracks_detail(monkeypatch, tmp_path):
    # Piste Text avec language="fre", forced="Yes"
    ...
    meta = extract.extract_video_metadata(video_path)
    assert meta["subtitle_tracks"] == [{"language": "fre", "forced": True}]


def test_extract_video_metadata_subtitle_not_forced_defaults_false(monkeypatch, tmp_path):
    # Piste Text SANS attribut forced (absent, pas juste "No")
    ...
    meta = extract.extract_video_metadata(video_path)
    assert meta["subtitle_tracks"][0]["forced"] is False
```

**Important** : ce fichier de test mocke deja `pymediainfo.MediaInfo` avec
un systeme de fixtures (probablement une classe `_Track`/`_FakeMediaInfo`
avec `track_type`, et des attributs lus via `getattr`). Lis
`tests/test_extract.py` en entier avant d'ecrire ces tests pour reprendre
EXACTEMENT ce mecanisme (noms de classes, attributs, `parse_speed`) —
ne le devine pas depuis ce plan seul.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_extract.py -k "audio_tracks or subtitle_tracks" -v`
Expected: FAIL (cle absente du dict retourne)

- [ ] **Step 3: Implement**

Dans `nfogen/extract.py`, `extract_video_metadata()`, ajoute au dict
retourne (apres `subtitle_languages`) :

```python
        "audio_tracks": [
            {
                "language": t.language,
                "channels": t.channel_s,
                "codec": t.format,
                "bit_rate_kbps": round(int(t.bit_rate) / 1000) if t.bit_rate else None,
                "sampling_khz": round(int(t.sampling_rate) / 1000, 1) if t.sampling_rate else None,
            }
            for t in mi.tracks if t.track_type == "Audio"
        ],
        "subtitle_tracks": [
            {"language": t.language, "forced": getattr(t, "forced", None) == "Yes"}
            for t in mi.tracks if t.track_type == "Text"
        ],
```

`extract_video_dir_metadata()` n'a pas besoin de modification : elle
appelle deja `extract_video_metadata()` par fichier et propage tout le
dict tel quel (`meta["name"] = p.name` en plus, le reste passe sans
changement de forme).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_extract.py -v`
Expected: PASS (tous les tests existants ET les nouveaux)

- [ ] **Step 5: Commit**

```bash
git add nfogen/extract.py tests/test_extract.py
git commit -m "feat: extraction MediaInfo par piste audio/sous-titre (channels/codec/bitrate/sample rate/forced)"
```

---

### Task 6 : Bannieres nfogen.nfo (assets statiques)

**Files:**
- Create: `scripts/generate_upload_banners.py`
- Create (generes par le script, commites) : `assets/banners/informations.png`, `assets/banners/synopsis.png`, `assets/banners/details-techniques.png`, `assets/banners/telechargement.png`
- Modify: `pyproject.toml` (ajoute `Pillow` a `dev`)

**Interfaces:**
- Produces : 4 fichiers PNG commites, servis (une fois pousses sur `main`)
  via `https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/<nom>.png`
  — URLs codees en constantes dans Task 7 (`upload_prep.py`).

- [ ] **Step 1: Ajouter Pillow aux dependances dev**

Dans `pyproject.toml` :
```toml
dev = ["pytest>=8.0", "ruff>=0.4", "httpx>=0.27", "Pillow>=10.0"]
```

Installe-la dans le venv du projet :
```bash
.venv/Scripts/python.exe -m pip install "Pillow>=10.0"
```

- [ ] **Step 2: Ecrire le script de generation**

```python
"""Genere les 4 bannieres de section du template d'upload nfogen
(voir nfogen/profiles/c411/templates/upload_description.j2) -- SCRIPT
DEV-ONLY, jamais execute au runtime nfogen. A relancer manuellement si la
charte graphique change ; le resultat (assets/banners/*.png) est commite
dans le repo et servi via raw.githubusercontent.com (voir
docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 460, 56
BG_COLOR = "#141d19"
ACCENT_COLOR = "#6bc9b3"
CREDIT_COLOR = "#4d5c53"
OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "banners"

BANNERS = [
    ("informations", "🎬  INFORMATIONS"),
    ("synopsis", "📖  SYNOPSIS"),
    ("details-techniques", "⚙️  DÉTAILS TECHNIQUES"),
    ("telechargement", "📥  TÉLÉCHARGEMENT"),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    # Police systeme generique (DejaVu Sans Bold, livree avec Pillow) --
    # pas de fichier de police externe a gerer.
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def generate() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    title_font = _font(22)
    credit_font = _font(11)
    for filename, label in BANNERS:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw.text((18, 14), label, font=title_font, fill=ACCENT_COLOR)
        draw.text((WIDTH - 92, HEIGHT - 16), "nfogen.nfo", font=credit_font, fill=CREDIT_COLOR)
        path = OUT_DIR / f"{filename}.png"
        img.save(path, "PNG")
        print(f"Écrit : {path}")


if __name__ == "__main__":
    generate()
```

- [ ] **Step 3: Executer le script et verifier visuellement**

```bash
.venv/Scripts/python.exe scripts/generate_upload_banners.py
```

Ouvre au moins `assets/banners/informations.png` avec l'outil Read (image)
pour verifier visuellement : texte lisible, couleurs correctes
(`#141d19` fond / `#6bc9b3` texte), credit "nfogen.nfo" visible en bas a
droite. Si la police DejaVu Sans Bold n'est pas trouvee par Pillow sur la
machine d'execution, `ImageFont.load_default()` degrade vers une police
bitmap minuscule illisible a cette taille — dans ce cas, remplace
`_font()` par un chemin de police explicite disponible sur le systeme
(ex. `C:/Windows/Fonts/segoeuib.ttf` sur Windows) plutot que de livrer un
rendu illisible.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml scripts/generate_upload_banners.py assets/banners/*.png
git commit -m "feat: bannieres de section nfogen.nfo (assets statiques generes)"
git push origin main
```

Le `push` ici est necessaire AVANT la Task 7 : les URLs
`raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/*.png`
codees dans `upload_prep.py` ne resolvent qu'une fois ce commit sur
`main` sur le remote (les tests de Task 7 ne verifient que la PRESENCE de
l'URL dans le rendu, pas qu'elle repond reellement — aucune dependance
reseau dans les tests).

---

### Task 7 : Assemblage dans `send_to_tracker()` + refonte du template

**Files:**
- Modify: `nfogen/upload_prep.py`
- Modify: `nfogen/profiles/c411/templates/upload_description.j2`
- Test: `tests/test_upload_prep.py`
- Test: `tests/test_upload_description.py`

**Interfaces:**
- Consumes: `TMDBClient`/`TMDBError`/`TMDBExtraDetails` (Task 3),
  `gapscan_config_store.effective_tmdb_api_key()` (Task 1),
  `resolve_language`/`flagcdn_url` (Task 2), `RadarrMovieDetails.imdb_id`/
  `SonarrSeriesDetails.imdb_id` (Task 4), `audio_tracks`/`subtitle_tracks`
  de `extract_video_metadata()` (Task 5), les 4 URLs de bannieres (Task 6).
- Produces: contexte de `render_upload_description()` etendu avec
  `country`, `creators`, `tmdb_rating`, `imdb_url`, `audio_rows`,
  `subtitle_rows`, `banner_informations`, `banner_synopsis`,
  `banner_details_techniques`, `banner_telechargement`.

- [ ] **Step 1: Write the failing tests (upload_prep)**

Dans `tests/test_upload_prep.py`, trouve le test existant qui verifie
l'appel a `RadarrClient.get_movie_details` (deja present depuis
l'enrichissement precedent) et ajoute, en suivant le MEME mecanisme de
mock (`monkeypatch.setattr` sur la classe client, pas un vrai reseau) :

```python
def test_send_to_tracker_calls_tmdb_when_key_configured_and_tmdb_id_present(monkeypatch, tmp_path):
    # Reprend le setup existant d'un test send_to_tracker pour un FILM
    # (radarr_movie_id, staged file, tracker configure...), puis :
    monkeypatch.setattr(
        gapscan_config_store, "effective_tmdb_api_key", lambda: "tmdb-secret",
    )
    calls = []

    class FakeTMDBClient:
        def __init__(self, api_key, **kwargs):
            calls.append(api_key)

        def get_movie_extra(self, tmdb_id):
            return TMDBExtraDetails(country="France", vote_average=7.8, creators=[])

    monkeypatch.setattr(upload_prep, "TMDBClient", FakeTMDBClient)

    result = upload_prep.send_to_tracker(..., tmdb_id=603)  # complete avec les autres kwargs deja utilises par les tests voisins de ce fichier

    assert calls == ["tmdb-secret"]


def test_send_to_tracker_skips_tmdb_when_key_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(gapscan_config_store, "effective_tmdb_api_key", lambda: None)
    called = []
    monkeypatch.setattr(
        upload_prep, "TMDBClient",
        lambda *a, **k: called.append(True) or pytest.fail("ne doit pas etre instancie"),
    )
    upload_prep.send_to_tracker(..., tmdb_id=603)
    assert called == []


def test_send_to_tracker_tmdb_failure_does_not_block_send(monkeypatch, tmp_path):
    monkeypatch.setattr(gapscan_config_store, "effective_tmdb_api_key", lambda: "tmdb-secret")

    class FailingTMDBClient:
        def __init__(self, api_key, **kwargs):
            pass

        def get_movie_extra(self, tmdb_id):
            raise TMDBError("boom")

    monkeypatch.setattr(upload_prep, "TMDBClient", FailingTMDBClient)
    # Ne doit pas lever -- la description se genere sans country/creators/tmdb_rating.
    result = upload_prep.send_to_tracker(..., tmdb_id=603)
    assert result.draft_id is not None
```

Reprends EXACTEMENT le setup (mocks Radarr/Sonarr/C411UploadClient,
fichiers stages, `tmp_path`) des tests `send_to_tracker` deja presents
dans ce fichier — ne le reinvente pas, complete les `...` ci-dessus avec
les memes valeurs que les tests voisins pour rester coherent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py -k tmdb -v`
Expected: FAIL (`upload_prep.TMDBClient` n'existe pas encore comme nom importe)

- [ ] **Step 3: Implement (upload_prep.py)**

Ajoute l'import en tete de `nfogen/upload_prep.py` :
```python
from .languages import flagcdn_url, resolve_language
from .tmdb_client import TMDBClient, TMDBError
```

Constantes bannieres (juste sous les imports) :
```python
_BANNER_BASE_URL = "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners"
_BANNER_INFORMATIONS = f"{_BANNER_BASE_URL}/informations.png"
_BANNER_SYNOPSIS = f"{_BANNER_BASE_URL}/synopsis.png"
_BANNER_DETAILS_TECHNIQUES = f"{_BANNER_BASE_URL}/details-techniques.png"
_BANNER_TELECHARGEMENT = f"{_BANNER_BASE_URL}/telechargement.png"
```

Dans `send_to_tracker()`, remplace le bloc de recuperation Radarr/Sonarr
existant (celui qui peuple `overview, poster_url, genres, ...`) pour
capturer aussi `imdb_id`, et ajoute juste apres l'appel TMDB best-effort :

```python
    overview, poster_url, genres, directors, cast = "", None, [], [], []
    release_date, runtime_minutes, distributor, certification = None, None, None, None
    imdb_id: Optional[str] = None
    if media_type == "movie" and radarr_movie_id is not None:
        radarr_config = gapscan_config_store.effective_radarr()
        if radarr_config:
            radarr = RadarrClient(*radarr_config)
            try:
                details = radarr.get_movie_details(radarr_movie_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
                release_date, runtime_minutes = details.release_date, details.runtime_minutes
                distributor, certification = details.studio, details.certification
                imdb_id = details.imdb_id
            finally:
                radarr.close()
    elif media_type == "series" and sonarr_series_id is not None:
        sonarr_config = gapscan_config_store.effective_sonarr()
        if sonarr_config:
            sonarr = SonarrClient(*sonarr_config)
            try:
                details = sonarr.get_series_details(sonarr_series_id)
                overview, poster_url = details.overview, details.poster_url
                genres, directors, cast = details.genres, details.directors, details.cast
                release_date, runtime_minutes = details.release_date, details.runtime_minutes
                distributor, certification = details.network, details.certification
                imdb_id = details.imdb_id
            finally:
                sonarr.close()

    # Enrichissement TMDB best-effort (Pays/Createur(s)/Note) -- absent des
    # deux API Radarr/Sonarr, confirme par des dumps reels (voir
    # docs/superpowers/specs/2026-09-07-template-charte-tmdb-design.md).
    # Silencieux sur toute erreur : ne bloque jamais l'envoi (decision
    # utilisateur, 2026-09-07).
    country, tmdb_rating, creators = None, None, []
    tmdb_api_key = gapscan_config_store.effective_tmdb_api_key()
    if tmdb_api_key and tmdb_id:
        try:
            tmdb_client = TMDBClient(tmdb_api_key)
            try:
                extra = (
                    tmdb_client.get_movie_extra(int(tmdb_id)) if media_type == "movie"
                    else tmdb_client.get_series_extra(int(tmdb_id))
                )
            finally:
                tmdb_client.close()
            country, tmdb_rating, creators = extra.country, extra.vote_average, extra.creators
        except TMDBError:
            pass

    imdb_url = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else None
```

Remplace le bloc `audio_languages`/`subtitle_languages`/`video_bit_rate`
(garde `audio_languages`/`subtitle_languages` tels quels — utilises
ailleurs — mais AJOUTE la construction des lignes de tableau) :

```python
    audio_languages = [lang for lang in first_metadata.get("audio_languages", []) if lang]
    subtitle_languages = [lang for lang in first_metadata.get("subtitle_languages", []) if lang]
    video_bit_rate = first_metadata.get("video_bit_rate")

    audio_rows = []
    for t in first_metadata.get("audio_tracks", []):
        name, flag_code = resolve_language(t.get("language"))
        audio_rows.append({
            "flag": flagcdn_url(flag_code) if flag_code else None,
            "language": name, "channels": t.get("channels"),
            "codec": t.get("codec"), "bit_rate_kbps": t.get("bit_rate_kbps"),
            "sampling_khz": t.get("sampling_khz"),
        })
    subtitle_rows = []
    for t in first_metadata.get("subtitle_tracks", []):
        name, flag_code = resolve_language(t.get("language"))
        subtitle_rows.append({
            "flag": flagcdn_url(flag_code) if flag_code else None,
            "language": name, "forced": t.get("forced", False),
        })
```

Etend enfin le contexte passe a `render_upload_description()` :
```python
    description = render_upload_description(
        profile,
        {
            "title": release_name, "overview": overview, "poster_url": poster_url,
            "genres": genres, "directors": directors, "cast": cast,
            "country": country, "creators": creators, "tmdb_rating": tmdb_rating,
            "imdb_url": imdb_url,
            "resolution": capture_values.get("resolution", ""),
            "source": capture_values.get("source", ""),
            "video_codec": capture_values.get("video_codec", ""),
            "audio_rows": audio_rows, "subtitle_rows": subtitle_rows,
            "video_bit_rate_kbps": video_bit_rate_kbps,
            "release_date": release_date, "runtime_display": runtime_display,
            "distributor": distributor, "certification": certification,
            "release_name": release_name, "team": team,
            "file_count": file_count, "total_size_bytes": total_size_bytes,
            "banner_informations": _BANNER_INFORMATIONS,
            "banner_synopsis": _BANNER_SYNOPSIS,
            "banner_details_techniques": _BANNER_DETAILS_TECHNIQUES,
            "banner_telechargement": _BANNER_TELECHARGEMENT,
        },
    )
```

- [ ] **Step 4: Refonte du template**

Remplace entierement `nfogen/profiles/c411/templates/upload_description.j2` par :

```jinja2
[center][size=150]{{ title }}[/size][/center]

{% if poster_url %}[center][img]{{ poster_url }}[/img][/center]

{% endif %}[img]{{ banner_informations }}[/img]
{% if genres %}[b]Genres :[/b] {{ genres|join(", ") }}
{% endif %}{% if country %}[b]Pays :[/b] {{ country }}
{% endif %}{% if release_date %}[b]Date de sortie :[/b] {{ release_date }}
{% endif %}{% if runtime_display %}[b]Durée :[/b] {{ runtime_display }}
{% endif %}{% if certification %}[b]Classification :[/b] {{ certification }}
{% endif %}{% if distributor %}[b]Studio/Chaîne :[/b] {{ distributor }}
{% endif %}{% if creators %}[b]Créateur(s) :[/b] {{ creators|join(", ") }}
{% endif %}{% if directors %}[b]Réalisateur(s) :[/b] {{ directors|join(", ") }}
{% endif %}{% if tmdb_rating %}[b]Note TMDB :[/b] {{ tmdb_rating }}/10
{% endif %}{% if imdb_url %}[b]IMDB :[/b] [url={{ imdb_url }}]Fiche[/url]
{% endif %}{% if cast %}[b]Acteurs :[/b] {{ cast|join(", ") }}
{% endif %}
[img]{{ banner_synopsis }}[/img]
{% if overview %}{{ overview }}{% else %}(synopsis non disponible){% endif %}

[img]{{ banner_details_techniques }}[/img]
[list]
[*]Vidéo : {{ video_codec }} {{ resolution }}p ({{ source }})
{% if video_bit_rate_kbps %}[*]Débit vidéo : {{ video_bit_rate_kbps }} kb/s
{% endif %}[/list]
{% if audio_rows %}[table][tr][th]#[/th][th]Langue[/th][th]Canaux[/th][th]Codec[/th][th]Débit[/th][th]Sample Rate[/th][/tr]
{% for a in audio_rows %}[tr][td]{{ loop.index }}[/td][td]{% if a.flag %}[img=20x15]{{ a.flag }}[/img] {% endif %}{{ a.language }}[/td][td]{{ a.channels }}[/td][td]{{ a.codec }}[/td][td]{{ a.bit_rate_kbps }} kb/s[/td][td]{{ a.sampling_khz }} kHz[/td][/tr]
{% endfor %}[/table]
{% endif %}{% if subtitle_rows %}[table][tr][th]#[/th][th]Langue[/th][th]Type[/th][/tr]
{% for s in subtitle_rows %}[tr][td]{{ loop.index }}[/td][td]{% if s.flag %}[img=20x15]{{ s.flag }}[/img] {% endif %}{{ s.language }}[/td][td]{{ "FORCÉ" if s.forced else "COMPLET" }}[/td][/tr]
{% endfor %}[/table]
{% endif %}
[img]{{ banner_telechargement }}[/img]
[b]Release :[/b] {{ release_name }}
{% if team %}[b]Team :[/b] {{ team }}
{% endif %}[b]Nombre de fichier(s) :[/b] {{ file_count }}
[b]Taille totale :[/b] {{ total_size_bytes|human_bin }}

[i]Généré par nfogen.nfo[/i]
```

- [ ] **Step 5: Rewrite `tests/test_upload_description.py`**

Remplace `FULL_CONTEXT` et les assertions pour coller au nouveau
contexte (garde le meme style/organisation que le fichier actuel) :

```python
FULL_CONTEXT = {
    "title": "Inception",
    "overview": "Dom Cobb est un voleur experimente...",
    "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
    "genres": ["Science-Fiction", "Action"],
    "directors": ["Christopher Nolan"],
    "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt"],
    "country": "United States of America",
    "creators": [],
    "tmdb_rating": 8.4,
    "imdb_url": "https://www.imdb.com/title/tt1375666/",
    "resolution": "2160",
    "source": "BluRay",
    "video_codec": "hevc",
    "audio_rows": [
        {"flag": "https://flagcdn.com/20x15/fr.png", "language": "Français",
         "channels": "5.1", "codec": "AC-3", "bit_rate_kbps": 448, "sampling_khz": 48.0},
    ],
    "subtitle_rows": [
        {"flag": "https://flagcdn.com/20x15/fr.png", "language": "Français", "forced": True},
    ],
    "video_bit_rate_kbps": 12000,
    "release_date": "2010-07-15",
    "runtime_display": "2h28min",
    "distributor": "Warner Bros.",
    "certification": "PG-13",
    "release_name": "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM",
    "team": "TEAM",
    "file_count": 1,
    "total_size_bytes": 21474836480,
    "banner_informations": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/informations.png",
    "banner_synopsis": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/synopsis.png",
    "banner_details_techniques": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/details-techniques.png",
    "banner_telechargement": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/telechargement.png",
}

_ALWAYS_PRESENT = {
    "release_name": "X.2020.1080p.BluRay-TEAM", "file_count": 1, "total_size_bytes": 1_000_000_000,
    "banner_informations": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/informations.png",
    "banner_synopsis": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/synopsis.png",
    "banner_details_techniques": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/details-techniques.png",
    "banner_telechargement": "https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/telechargement.png",
}


def test_renders_banners():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/informations.png" in out
    assert "raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/telechargement.png" in out


def test_renders_country_creators_rating_imdb():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "United States of America" in out
    assert "8.4/10" in out
    assert "https://www.imdb.com/title/tt1375666/" in out


def test_renders_audio_and_subtitle_tables_with_flags():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "[table]" in out
    assert "flagcdn.com/20x15/fr.png" in out
    assert "5.1" in out and "AC-3" in out and "448 kb/s" in out and "48.0 kHz" in out
    assert "FORCÉ" in out


def test_renders_release_date_runtime_certification_distributor():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "2010-07-15" in out
    assert "2h28min" in out
    assert "PG-13" in out
    assert "Warner Bros." in out


def test_renders_release_name_team_file_count_and_size():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM" in out
    assert "TEAM" in out
    assert "20.0" in out or "20 " in out


def test_renders_without_optional_fields():
    minimal = {
        **_ALWAYS_PRESENT,
        "title": "Inception", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [], "country": None,
        "creators": [], "tmdb_rating": None, "imdb_url": None,
        "resolution": "2160", "source": "BluRay", "video_codec": "hevc",
        "audio_rows": [], "subtitle_rows": [], "video_bit_rate_kbps": None,
        "release_date": None, "runtime_display": None,
        "distributor": None, "certification": None, "team": None,
    }
    out = render_upload_description("c411", minimal)
    assert "Inception" in out
    assert "[table]" not in out
    assert len(out) >= 20


def test_output_meets_c411_minimum_length():
    minimal = {
        **_ALWAYS_PRESENT,
        "title": "X", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [], "country": None,
        "creators": [], "tmdb_rating": None, "imdb_url": None,
        "resolution": "1080", "source": "WEB", "video_codec": "x264",
        "audio_rows": [], "subtitle_rows": [], "video_bit_rate_kbps": None,
        "release_date": None, "runtime_display": None,
        "distributor": None, "certification": None, "team": None,
    }
    out = render_upload_description("c411", minimal)
    assert len(out) >= 20
```

- [ ] **Step 6: Run all affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_upload_prep.py tests/test_upload_description.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add nfogen/upload_prep.py nfogen/profiles/c411/templates/upload_description.j2 tests/test_upload_prep.py tests/test_upload_description.py
git commit -m "feat: enrichit la description d'upload (TMDB, tableau langues, bannieres nfogen.nfo)"
```

---

### Task 8 : Frontend — types + champ TMDB dans le contrat API

**Files:**
- Modify: `frontend/src/api/types.ts`

**Interfaces:**
- Produces: `GapscanConfig.tmdb_configured: boolean`, `GapscanConfigWrite.tmdb_api_key?: string`.

- [ ] **Step 1: Implement**

Dans `GapscanConfig` :
```typescript
  qbittorrent_verify_ssl: boolean;
  tmdb_configured: boolean;
```
Dans `GapscanConfigWrite` :
```typescript
  qbittorrent_verify_ssl?: boolean;
  tmdb_api_key?: string;
```

- [ ] **Step 2: Verify with tsc**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: pas d'erreur (des fixtures de test vont echouer a la prochaine
etape tant que Task 9 n'a pas ajoute `tmdb_configured` partout — normal,
regle par Task 9).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/types.ts
git commit -m "feat(frontend): types tmdb_configured/tmdb_api_key"
```

---

### Task 9 : Migration du panneau "Configuration globale" vers Réglages + champ TMDB

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/pages/LibraryPage.test.tsx`
- Create: `frontend/src/pages/SettingsPage.test.tsx` (si absent — verifie
  d'abord s'il existe deja, sinon cree-le avec le meme pattern de mock
  `vi.mock("../api/client", ...)` que `LibraryPage.test.tsx`)
- Modify: `frontend/src/App.test.tsx` (fixture `gapscanConfig` gagne
  `tmdb_configured: false`)

**Interfaces:**
- Consumes: `GapscanConfig.tmdb_configured`, `GapscanConfigWrite.tmdb_api_key` (Task 8), `gapscanConfigWrite`/`gapscanConfig` (deja existants dans `frontend/src/api/client.ts`), `useProfile()` (deja global, `frontend/src/ProfileContext.tsx`), `KeyValueEditor` (`frontend/src/components/ListEditor.tsx`).

- [ ] **Step 1: Retirer le panneau "Configuration globale" de `LibraryPage.tsx`**

Supprime entierement : les 4 etats
`showGlobalConfigForm`/`globalConfigSaving`/`globalConfigSaved`/
`globalConfigError`, les etats de champs qui n'appartiennent QU'a ce
panneau (`sonarrUrl`, `sonarrApiKey`, `radarrUrl`, `radarrApiKey`,
`sonarrPathMappings`, `radarrPathMappings`, `stagingDir`,
`qbittorrentUrl`, `qbittorrentUsername`, `qbittorrentPassword`,
`qbittorrentVerifySsl`), les lignes correspondantes du `useEffect` de
chargement (`setSonarrUrl`, `setRadarrUrl`,
`setSonarrPathMappings`/`setRadarrPathMappings`, `setStagingDir`,
`setQbittorrentUrl`, `setQbittorrentVerifySsl`,
`setShowGlobalConfigForm(true)` conditionnel), la fonction
`handleSaveGlobalConfig`, et le bloc JSX entier du second panneau
(`"Configuration globale (Sonarr, Radarr, qBittorrent)"`, avec ses
`KeyValueEditor` de mappings).

Garde intact : `showProfileConfigForm`/`profileConfigSaving`/
`profileConfigSaved`/`profileConfigError`, `trackerBaseUrl`/
`trackerApiKey`/`trackerAnnounceUrl`, `handleSaveProfileConfig`, le
premier panneau JSX ("Configuration du profil ..."). Le `useEffect` garde
uniquement `setTrackerBaseUrl` et la logique `if (!c.tracker_configured)
setShowProfileConfigForm(true)`.

- [ ] **Step 2: Ajouter le panneau a `SettingsPage.tsx`**

Ajoute les imports necessaires en tete de fichier :
```typescript
import { gapscanConfig, gapscanConfigWrite } from "../api/client";
import type { GapscanConfig, GapscanConfigWrite } from "../api/types";
import { KeyValueEditor } from "../components/ListEditor";
import { useProfile } from "../ProfileContext";
```

Ajoute les etats (dans le corps du composant `SettingsPage`) :
```typescript
  const { profile } = useProfile();
  const [gConfig, setGConfig] = useState<GapscanConfig | null>(null);
  const [showGlobalConfigForm, setShowGlobalConfigForm] = useState(false);
  const [globalConfigSaving, setGlobalConfigSaving] = useState(false);
  const [globalConfigSaved, setGlobalConfigSaved] = useState(false);
  const [globalConfigError, setGlobalConfigError] = useState<string | null>(null);
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [sonarrPathMappings, setSonarrPathMappings] = useState<Record<string, string>>({});
  const [radarrPathMappings, setRadarrPathMappings] = useState<Record<string, string>>({});
  const [stagingDir, setStagingDir] = useState("");
  const [qbittorrentUrl, setQbittorrentUrl] = useState("");
  const [qbittorrentUsername, setQbittorrentUsername] = useState("");
  const [qbittorrentPassword, setQbittorrentPassword] = useState("");
  const [qbittorrentVerifySsl, setQbittorrentVerifySsl] = useState(true);
  const [tmdbApiKey, setTmdbApiKey] = useState("");

  useEffect(() => {
    gapscanConfig(profile)
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setGConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setSonarrPathMappings(c.sonarr_path_mappings);
        setRadarrPathMappings(c.radarr_path_mappings);
        setStagingDir(c.staging_dir ?? "");
        setQbittorrentUrl(c.qbittorrent_url ?? "");
        setQbittorrentVerifySsl(c.qbittorrent_verify_ssl ?? true);
        if (!c.sonarr_configured && !c.radarr_configured) setShowGlobalConfigForm(true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  async function handleSaveGlobalConfig() {
    setGlobalConfigSaving(true);
    setGlobalConfigError(null);
    setGlobalConfigSaved(false);
    try {
      const fields: GapscanConfigWrite = {};
      if (sonarrUrl.trim()) fields.sonarr_url = sonarrUrl.trim();
      if (sonarrApiKey.trim()) fields.sonarr_api_key = sonarrApiKey.trim();
      if (radarrUrl.trim()) fields.radarr_url = radarrUrl.trim();
      if (radarrApiKey.trim()) fields.radarr_api_key = radarrApiKey.trim();
      if (stagingDir.trim()) fields.staging_dir = stagingDir.trim();
      if (qbittorrentUrl.trim()) fields.qbittorrent_url = qbittorrentUrl.trim();
      if (qbittorrentUsername.trim()) fields.qbittorrent_username = qbittorrentUsername.trim();
      if (qbittorrentPassword.trim()) fields.qbittorrent_password = qbittorrentPassword.trim();
      if (tmdbApiKey.trim()) fields.tmdb_api_key = tmdbApiKey.trim();
      fields.qbittorrent_verify_ssl = qbittorrentVerifySsl;
      fields.sonarr_path_mappings = sonarrPathMappings;
      fields.radarr_path_mappings = radarrPathMappings;

      const updated = await gapscanConfigWrite(fields, profile);
      setGConfig(updated);
      setSonarrApiKey("");
      setRadarrApiKey("");
      setQbittorrentPassword("");
      setTmdbApiKey("");
      setGlobalConfigSaved(true);
      setTimeout(() => setGlobalConfigSaved(false), 2000);
    } catch (e) {
      setGlobalConfigError(e instanceof ApiError ? e.message : "Enregistrement impossible.");
    } finally {
      setGlobalConfigSaving(false);
    }
  }
```

JSX (a inserer comme nouvelle section, apres celle "Authentification" et
avant "Comptes administrateurs" — ou en derniere section, peu importe
l'ordre exact tant que c'est un bloc `<div className="space-y-3
border-t border-line pt-4">` coherent avec le reste de la page) :
identique dans sa structure au panneau retire de `LibraryPage.tsx`
(memes labels/inputs pour Sonarr/Radarr/qBittorrent/staging/mappings), en
ajoutant un champ juste avant le bouton "Enregistrer" :

```tsx
              <label className="block text-sm font-medium text-ink-dim">
                Clé API TMDB
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={gConfig?.tmdb_configured ? "•••• (enregistrée)" : ""}
                  value={tmdbApiKey}
                  onChange={(e) => setTmdbApiKey(e.target.value)}
                />
              </label>
```

Reprends le JSX complet du panneau retire a l'etape 1 (copie-le avant de
le supprimer de `LibraryPage.tsx`) pour ne rien perdre en cours de route
(placeholders `config?.xxx_configured` deviennent `gConfig?.xxx_configured`).

- [ ] **Step 3: Migrer les tests**

Dans `frontend/src/pages/LibraryPage.test.tsx`, retire les 4 tests du
panneau global (`"enregistre Sonarr via le formulaire de configuration"`,
`"enregistre la configuration qBittorrent..."`,
`"decoche la verification SSL..."`, et le test
`"enregistre la config du profil tracker separement..."` GARDE, lui, il
teste le panneau PROFIL qui reste sur cette page). Retire aussi
`getByLabelText("URL Sonarr")` du test `"service non configure..."`
(ce champ n'est plus sur cette page) — remplace-le par une assertion sur
`getByLabelText(/URL de base/)` (champ du panneau profil, toujours
present).

Cree/etend `frontend/src/pages/SettingsPage.test.tsx` avec les 4 tests
deplaces (adapte-les au mock `gapscanConfig`/`gapscanConfigWrite` — verifie
d'abord si ce fichier mocke deja `../api/client`, sinon ajoute
`vi.mock("../api/client", () => ({ gapscanConfig: vi.fn(), gapscanConfigWrite: vi.fn(), ... })`
en tete, en conservant toutes les autres fonctions deja mockees pour
l'auth/comptes) :

```typescript
it("enregistre Sonarr via le formulaire de configuration globale", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanConfig).mockResolvedValue({ ...CONFIGURED });
  vi.mocked(gapscanConfigWrite).mockResolvedValue({
    ...CONFIGURED, sonarr_configured: true, sonarr_url: "http://sonarr.local:8989",
  });

  render(<SettingsPage />);
  await user.click(await screen.findByRole("button", { name: /Configuration globale/ }));
  await user.type(screen.getByLabelText("URL Sonarr"), "http://sonarr.local:8989");
  await user.type(screen.getByLabelText("Clé API Sonarr"), "sk-123");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));

  expect(gapscanConfigWrite).toHaveBeenCalledWith(
    expect.objectContaining({ sonarr_url: "http://sonarr.local:8989", sonarr_api_key: "sk-123" }),
    "c411",
  );
});

it("enregistre la cle API TMDB via le formulaire de configuration globale", async () => {
  const user = userEvent.setup();
  vi.mocked(gapscanConfig).mockResolvedValue({ ...CONFIGURED });
  vi.mocked(gapscanConfigWrite).mockResolvedValue({ ...CONFIGURED, tmdb_configured: true });

  render(<SettingsPage />);
  await user.click(await screen.findByRole("button", { name: /Configuration globale/ }));
  await user.type(screen.getByLabelText("Clé API TMDB"), "tmdb-secret");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));

  expect(gapscanConfigWrite).toHaveBeenCalledWith(
    expect.objectContaining({ tmdb_api_key: "tmdb-secret" }),
    "c411",
  );
});
```

Reprends une constante `CONFIGURED` coherente avec celle de
`LibraryPage.test.tsx` (avec `tmdb_configured: false` par defaut).

Dans `frontend/src/App.test.tsx`, ajoute `tmdb_configured: false` a la
fixture `gapscanConfig.mockResolvedValue({...})` existante.

- [ ] **Step 4: Run frontend tests, typecheck, lint**

```bash
cd frontend
npx vitest run
npx tsc -b --noEmit
npx oxlint
```
Expected: tout passe.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LibraryPage.tsx frontend/src/pages/SettingsPage.tsx frontend/src/pages/LibraryPage.test.tsx frontend/src/pages/SettingsPage.test.tsx frontend/src/App.test.tsx
git commit -m "refactor(frontend): migre la config globale (Sonarr/Radarr/qBittorrent/TMDB) vers Reglages"
```

---

### Task 10 : Documentation

**Files:**
- Modify: `AUTOMATION.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Mettre a jour**

`CHANGELOG.md` : ajoute une entree decrivant l'enrichissement TMDB
(Pays/Createur(s)/Note/IMDB), le tableau audio/sous-titres avec drapeaux,
les bannieres nfogen.nfo, et la migration de la config globale vers
Réglages.

`AUTOMATION.md` : dans la section du sous-projet concerne (description
d'upload), documente la nouvelle cle API TMDB (optionnelle, config
globale) et le fait que Pays/Créateur(s)/Note TMDB disparaissent
silencieusement si elle n'est pas configurée.

- [ ] **Step 2: Commit + push final**

```bash
git add AUTOMATION.md CHANGELOG.md
git commit -m "docs: enrichissement template upload + migration config globale vers Reglages"
git push origin main
```

Puis suivre la discipline habituelle du projet : interroger
`https://api.github.com/repos/ICCUser/nfogen/actions/runs?branch=main&per_page=5`
jusqu'a ce que le run correspondant au dernier `head_sha` pousse affiche
`status: completed`, et verifier `conclusion: success` avant de
considerer le travail termine.

---

## Self-Review

- **Couverture spec** : (A) migration config globale -> Task 9, (B)
  client TMDB -> Task 3 + integration Task 7, (C) extraction MediaInfo
  par piste + drapeaux -> Task 5 + Task 2 + integration Task 7, (D)
  bannieres + refonte template -> Task 6 + Task 7. Tout couvert.
- **imdb_url** : ajoute a Task 4 (source Radarr/Sonarr, pas TMDB) +
  cable dans Task 7 — coherent avec la spec (`imdb_id` deja disponible,
  pas besoin d'appel TMDB dedie).
- **Coherence des types** : `TMDBExtraDetails(country, vote_average,
  creators)` (Task 3) utilise identiquement dans Task 7
  (`extra.country`/`extra.vote_average`/`extra.creators`).
  `resolve_language`/`flagcdn_url` (Task 2) consommes tels quels par
  Task 7. `audio_tracks`/`subtitle_tracks` (Task 5, cles de dict) consommes
  tels quels par Task 7 (`t.get("language")`/`t.get("channels")`/...).
- **Pas de placeholder** : chaque step contient soit du code complet,
  soit une instruction explicite de "reprendre le mecanisme existant"
  avec le nom exact du fichier a lire d'abord (Task 5 et Task 9
  s'appuient sur des patterns de test deja presents dans le repo,
  volontairement non recopiees en double pour eviter une divergence avec
  le code reel au moment de l'execution).
