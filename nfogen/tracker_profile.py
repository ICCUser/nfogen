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
    try:
        rules = profile_store.read_profile(profile)["rules"]
    except profile_store.ProfileStoreError:
        # Profil qui n'existe carrement pas (ni utilisateur, ni livre) --
        # meme repli neutre que "profil existant mais sans section
        # tracker" : jamais de plantage pour un nom de profil inconnu.
        return {}
    return rules.get("tracker", {})


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
