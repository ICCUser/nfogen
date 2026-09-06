"""Historique persistant des titres deja traites par nfogen (Confirmer
et/ou Envoyer a C411) -- AUTOMATION.md, sous-projet 8.

Meme patron de persistance que `gapscan_results_store.py` : fichier JSON
optionnel (`NFOGEN_UPLOAD_HISTORY_FILE`), tolerant a un fichier absent ou
corrompu, jamais une erreur fatale pour le reste de nfogen.

Grandit indefiniment pour l'instant (pas de purge/expiration -- volume
attendu faible, un enregistrement par Confirmer/Envoi reussi, pas par
scan ; voir la spec, "Non-objectifs").

`processed_key` est VOLONTAIREMENT distincte de `gapscan.movie_key`/
`series_key` (cles bibliotheque/mode incremental, basees sur imdb/tmdb/
titre/annee) : les points d'appel de ce module (`commit_job_runner.py`,
`upload_prep.py:send_to_tracker`) n'ont que `radarr_movie_id`/
`sonarr_series_id` sous la main, deja suffisants pour identifier un titre
de facon stable sans plomberie supplementaire (imdb_id/tmdb_id/title/year
ne sont pas transmis a ces deux endroits)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def processed_key(
    media_type: str,
    radarr_movie_id: Optional[int],
    sonarr_series_id: Optional[int],
    season_number: Optional[int] = None,
) -> Optional[tuple]:
    """`None` si aucun identifiant Radarr/Sonarr utilisable -- jamais de
    cle devinee a partir d'autre chose (coherent avec "jamais deviner",
    voir la spec)."""
    if media_type == "movie" and radarr_movie_id is not None:
        return ("movie", radarr_movie_id)
    if media_type == "series" and sonarr_series_id is not None:
        return ("series", sonarr_series_id, season_number)
    return None


def key_str(key: tuple) -> str:
    """Serialisation JSON stable d'une cle -- reutilisee par
    gapscan_library.py pour serialiser la cle de SELECTION (movie_key/
    series_key, differente de processed_key) sur le fil HTTP."""
    return json.dumps(list(key))


def _path() -> Optional[Path]:
    root = os.environ.get("NFOGEN_UPLOAD_HISTORY_FILE")
    return Path(root) if root else None


def _load() -> dict[str, Any]:
    path = _path()
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _save(data: dict[str, Any]) -> None:
    path = _path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError:
        pass


def record(key: tuple, *, kind: str, release_name: str, at: Optional[float] = None) -> None:
    """Ajoute/met a jour une entree -- kind: "committed" (Confirmer reussi)
    ou "sent" (Envoyer a C411 reussi). Idempotent par cle+kind : un nouvel
    appel sur la meme cle+kind met a jour l'horodatage plutot que
    d'accumuler des doublons. N'ECHOUE JAMAIS (try/except large) : un
    Confirmer/Envoi par ailleurs reussi ne doit jamais etre bloque par un
    probleme d'ecriture de cet historique, purement informatif."""
    try:
        data = _load()
        entry = data.setdefault(key_str(key), {})
        entry[kind] = {"release_name": release_name, "at": at if at is not None else time.time()}
        _save(data)
    except Exception:  # noqa: BLE001 -- jamais propager, voir docstring
        pass


def is_processed(key: tuple) -> bool:
    return bool(_load().get(key_str(key)))


def last_processed_at(key: tuple) -> Optional[float]:
    entry = _load().get(key_str(key))
    if not entry:
        return None
    timestamps = [v["at"] for v in entry.values() if "at" in v]
    return max(timestamps) if timestamps else None
