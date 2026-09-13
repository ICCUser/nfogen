"""Calcule categorie/sous-categorie/options pour l'API d'upload C411
(POST/PATCH /api/user/drafts, voir AUTOMATION.md sous-projet 5) a partir
du release_name DEJA CONFIRME -- reutilise `rules.captures()`, deja
construit pour la validation du nom (sous-projet 4b), plutot que de
redemander au moteur de nommage ou de dupliquer sa logique. Pur, sans I/O :
un champ absent du mapping declaratif du profil (rules.json ->
tracker.upload) est simplement omis, jamais devine.
"""
from __future__ import annotations

from typing import Any, Optional

from . import tracker_profile


def build_category_ids(
    profile: str, media_type: str, genre: Optional[str]
) -> tuple[Optional[int], Optional[int]]:
    """`(category_id, subcategory_id)` pour ce media_type/genre, ou
    `(None, None)` si le profil n'a rien declare -- jamais devine. Cle de
    recherche `"{media_type}:{genre}"` (ex. "movie:anime") avec repli sur
    `media_type` seul si cette combinaison precise n'est pas mappee (ex.
    documentaire non distingue film/serie pour ce tracker)."""
    config = tracker_profile.upload_config(profile)
    category_id = config.get("category_id")
    subcategory_ids: dict[str, int] = config.get("subcategory_id", {})
    key = f"{media_type}:{genre}" if genre else media_type
    subcategory_id = subcategory_ids.get(key) or subcategory_ids.get(media_type)
    if category_id is None or subcategory_id is None:
        return None, None
    return category_id, subcategory_id


def build_options(
    profile: str,
    capture_values: dict[str, str],
    release_name: str,
    season_number: Optional[int] = None,
) -> dict[str, Any]:
    """Construit le JSON `options` (`{optionTypeId: optionValueId |
    [optionValueId, ...]}`, voir doc API C411) a partir des valeurs
    capturees dans le release_name confirme (`source`/`language`, voir
    rules.captures) et de la config declarative du profil. `season_number`
    (optionnel, series uniquement) ajoute les options Saison/Episode --
    toujours "saison complete" (`full_season_episode_value`), ce plan ne
    distingue pas un pack partiel (plusieurs equipes sur la meme saison,
    voir AUTOMATION.md "Pas dans ce sous-projet")."""
    config = tracker_profile.upload_config(profile)
    options: dict[str, Any] = {}

    language_option_id = config.get("language_option_id")
    language_values: dict[str, int] = config.get("language_values", {})
    language = capture_values.get("language")
    if language and language_option_id is not None and language in language_values:
        options[str(language_option_id)] = [language_values[language]]

    quality_option_id = config.get("quality_option_id")
    quality_values: dict[str, int] = config.get("quality_values", {})
    source = capture_values.get("source")
    if source:
        # Audit C411 2026-09-13 (point 3/4, prefixe "UHD." sur les versions
        # pures 2160p, voir name_proposal._apply_uhd_bluray_prefix) : ce
        # prefixe n'existe que dans le release_name, jamais dans
        # `quality_values` (un seul id C411 par source pure, peu importe la
        # resolution) -- retire-le UNIQUEMENT pour ce lookup, jamais pour le
        # reste de la fonction (season/langue...), qui n'en a pas besoin.
        lookup_source = source[len("UHD."):] if source.startswith("UHD.") else source
        if "hdlight" in release_name.lower():
            # HDLight est structurellement une variante basse qualite --
            # jamais 4K en pratique -- donc prioritaire sur la resolution.
            quality_key = f"{lookup_source}.HDLight"
        else:
            # Audit croisé code + pages d'aide C411 (table C411_reference,
            # 2026-09-13) : la qualite ne depend pas que de `source`, la
            # resolution compte aussi (ex. id 26 "WEB-DL 4K" vs id 25
            # "WEB-DL 1080", id 10 "BluRay 4K" vs id 11 "BluRay Full"). Pas
            # de variante ".4K" pour REMUX (id 12, toutes resolutions) --
            # essayer `f"{lookup_source}.4K"` d'abord et retomber sur
            # `lookup_source` si le profil ne l'a pas declare couvre ce cas
            # naturellement (c'est aussi ce qui couvre BDMV/ISO 2160p : pas
            # de variante ".4K" dediee, repli sur la cle simple, ex.
            # "BluRay.BDMV" -> id "BluRay 4K" si le profil l'y fait pointer).
            resolution = capture_values.get("resolution")
            is_4k = False
            if resolution is not None:
                try:
                    is_4k = int(resolution) >= 2160
                except ValueError:
                    is_4k = False
            quality_key = (
                f"{lookup_source}.4K" if is_4k and f"{lookup_source}.4K" in quality_values
                else lookup_source
            )
        if quality_option_id is not None and quality_key in quality_values:
            options[str(quality_option_id)] = quality_values[quality_key]

    if season_number is not None:
        season_option_id = config.get("season_option_id")
        season_values: dict[str, int] = config.get("season_values", {})
        season_key = f"S{int(season_number):02d}"
        if season_option_id is not None and season_key in season_values:
            options[str(season_option_id)] = season_values[season_key]

        episode_option_id = config.get("episode_option_id")
        full_season_value = config.get("full_season_episode_value")
        if episode_option_id is not None and full_season_value is not None:
            options[str(episode_option_id)] = full_season_value

    return options
