"""Configuration GapScan (URLs + cles Sonarr/Radarr + identifiants de
tracker namespaces par profil, voir AUTOMATION.md sous-projet 4b),
modifiable a chaud via `PUT /gapscan/config`.

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
    # Contrairement a nfogen.env (chmod 600 explicite dans install.sh), ce
    # fichier contient des cles API en clair (Sonarr/Radarr/tracker) : sans
    # ceci il herite du umask par defaut du processus, potentiellement
    # lisible par d'autres utilisateurs du systeme (ex. un serveur
    # multi-utilisateurs). os.chmod est un no-op inoffensif sur Windows.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # systeme de fichiers qui ne supporte pas chmod (rare) : tant pis, pas fatal


def _resolve(file_key: str, env_key: str) -> Optional[str]:
    stored = _load().get(file_key)
    if stored:
        return stored
    return os.environ.get(env_key) or None


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


def effective_sonarr() -> Optional[tuple[str, str]]:
    """`(url, cle)`, ou `None` si l'un des deux manque."""
    url = _resolve("sonarr_url", "NFOGEN_SONARR_URL")
    api_key = _resolve("sonarr_api_key", "NFOGEN_SONARR_API_KEY")
    return (url, api_key) if url and api_key else None


def effective_radarr() -> Optional[tuple[str, str]]:
    url = _resolve("radarr_url", "NFOGEN_RADARR_URL")
    api_key = _resolve("radarr_api_key", "NFOGEN_RADARR_API_KEY")
    return (url, api_key) if url and api_key else None


def effective_sonarr_path_mappings() -> dict[str, str]:
    """Table de mapping {prefixe distant: prefixe local} pour Sonarr --
    vide par defaut (deploiement a chemins identiques). Pas de repli sur
    une variable d'environnement : uniquement configurable via le fichier
    (pas de cas d'usage non interactif identifie pour l'instant, contrairement
    aux cles/URLs)."""
    return _load().get("sonarr_path_mappings") or {}


def effective_radarr_path_mappings() -> dict[str, str]:
    return _load().get("radarr_path_mappings") or {}


def effective_staging_dir() -> Optional[str]:
    """Dossier ou nfogen met en scene les fichiers avant creation d'un
    .torrent -- pas un secret, `None` si non configure."""
    return _load().get("staging_dir") or None


def status(profile: str = "c411") -> dict[str, Any]:
    """Etat effectif pour CE profil (fichier prioritaire, sinon variables
    d'environnement pour `c411`) -- jamais les cles/secrets eux-memes.
    Sonarr/Radarr/mappings/staging_dir sont globaux, pas filtres par
    `profile`."""
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
