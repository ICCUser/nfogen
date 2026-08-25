"""Configuration GapScan (URLs + cles Sonarr/Radarr/C411), modifiable a
chaud via `PUT /gapscan/config`.

Contrairement a `NFOGEN_API_TOKEN` (qui protege nfogen lui-meme, et n'a
volontairement aucune route d'ecriture), ces identifiants sont des
credentials SORTANTS vers des services tiers -- rien n'empeche l'admin de
vouloir les changer sans redemarrer le service, d'ou ce stockage fichier
(meme esprit que `accounts.py` : JSON sur disque, jamais les secrets
renvoyes en clair par une lecture API). Relu a chaque appel (pas de
cache), comme `accounts.py`.

Repli sur les variables d'environnement historiques
(`NFOGEN_C411_API_KEY`, etc., voir `.env.example`) si le fichier n'est pas
configure ou ne contient pas le champ demande -- utile pour un deploiement
non interactif (docker-compose, `.env` seul, jamais de `PUT`). Une valeur
enregistree dans le fichier est toujours prioritaire sur l'equivalent en
variable d'environnement.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_DEFAULT_C411_BASE_URL = "https://c411.org"


class GapscanConfigStoreError(ValueError):
    """Erreur utilisateur (pas de fichier configure) -- a traduire en HTTP 400."""


def is_configured() -> bool:
    return bool(os.environ.get("NFOGEN_GAPSCAN_CONFIG_FILE"))


def _path() -> Path:
    root = os.environ.get("NFOGEN_GAPSCAN_CONFIG_FILE")
    if not root:
        raise GapscanConfigStoreError(
            "NFOGEN_GAPSCAN_CONFIG_FILE n'est pas configuree : impossible d'enregistrer "
            "la configuration GapScan (les variables d'environnement NFOGEN_C411_API_KEY/"
            "NFOGEN_SONARR_*/NFOGEN_RADARR_* restent utilisables en lecture seule)."
        )
    return Path(root)


def _load() -> dict[str, Any]:
    if not is_configured():
        return {}
    path = _path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write(
    *,
    c411_api_key: Optional[str] = None,
    c411_base_url: Optional[str] = None,
    sonarr_url: Optional[str] = None,
    sonarr_api_key: Optional[str] = None,
    radarr_url: Optional[str] = None,
    radarr_api_key: Optional[str] = None,
) -> None:
    """Met a jour uniquement les champs fournis (`None` = inchange) --
    jamais une reecriture complete, un PUT partiel ne doit pas effacer le
    reste de la configuration deja enregistree."""
    path = _path()
    data = _load()
    updates = {
        "c411_api_key": c411_api_key,
        "c411_base_url": c411_base_url,
        "sonarr_url": sonarr_url,
        "sonarr_api_key": sonarr_api_key,
        "radarr_url": radarr_url,
        "radarr_api_key": radarr_api_key,
    }
    for key, value in updates.items():
        if value is not None:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve(file_key: str, env_key: str) -> Optional[str]:
    stored = _load().get(file_key)
    if stored:
        return stored
    return os.environ.get(env_key) or None


def effective_c411() -> Optional[tuple[str, str]]:
    """`(cle, base_url)`, ou `None` si aucune cle configuree (ni fichier, ni env)."""
    api_key = _resolve("c411_api_key", "NFOGEN_C411_API_KEY")
    if not api_key:
        return None
    base_url = _resolve("c411_base_url", "NFOGEN_C411_BASE_URL") or _DEFAULT_C411_BASE_URL
    return api_key, base_url


def effective_sonarr() -> Optional[tuple[str, str]]:
    """`(url, cle)`, ou `None` si l'un des deux manque."""
    url = _resolve("sonarr_url", "NFOGEN_SONARR_URL")
    api_key = _resolve("sonarr_api_key", "NFOGEN_SONARR_API_KEY")
    return (url, api_key) if url and api_key else None


def effective_radarr() -> Optional[tuple[str, str]]:
    url = _resolve("radarr_url", "NFOGEN_RADARR_URL")
    api_key = _resolve("radarr_api_key", "NFOGEN_RADARR_API_KEY")
    return (url, api_key) if url and api_key else None


def status() -> dict[str, Any]:
    """Etat effectif (fichier prioritaire, sinon variables d'environnement)
    -- jamais les cles elles-memes, seulement si chaque service est
    configure et son URL (non sensible)."""
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
    }
