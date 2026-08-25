"""Extraction et comparaison de la qualite/langue d'un `release_name`.

Reutilise la meme convention que le profil C411 (voir
`nfogen/profiles/c411/rules.json`) : point-separe, resolution `\\d{3,4}p`,
codec video en fin de nom, tag de langue optionnellement precede de
`MULTI`. Utilise a la fois pour les releases locales (Sonarr/Radarr) et
les releases trouvees sur C411 (`c411_client.py`), afin de les comparer
(`GapScan`, voir `gapscan.py` et `GAPSCAN.md`).

Hierarchies par defaut (source/resolution) : a ajuster des que la
politique anti-doublon reelle de C411 est connue (voir "Encore a fournir"
dans `GAPSCAN.md`). Volontairement isolees ici pour rester faciles a
corriger sans toucher a `gapscan.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Ordre du meilleur au moins bon ; un rang plus bas (index) = meilleure source.
SOURCE_RANK: list[str] = [
    "REMUX",
    "BLURAY",
    "BDRIP",
    "WEB-DL",
    "WEBDL",
    "WEBRIP",
    "WEB",
    "HDTV",
    "DVDRIP",
    "DVD",
    "SDTV",
]

# Groupes de langues considerees equivalentes pour le matching (meme intention
# linguistique), a affiner avec la vraie regle C411.
LANGUAGE_EQUIVALENTS: dict[str, str] = {
    "VFF": "VF",
    "VFQ": "VF",
    "VF2": "VF",
    "VFI": "VF",
    "VOF": "VF",
    "FRENCH": "VF",
    "TRUEFRENCH": "VF",
    "VO": "VO",
    "VOSTFR": "VOSTFR",
}

# Sonarr/Radarr n'exposent que des noms de langue generiques (pas de
# distinction VFF/VFQ) : repli utilise seulement quand aucun `release_name`
# exploitable n'est disponible (voir `build_quality`).
LANGUAGE_NAME_TO_GROUP: dict[str, str] = {
    "FRENCH": "VF",
    "FRANÇAIS": "VF",
    "FRANCAIS": "VF",
    "ENGLISH": "VO",
    "ORIGINAL": "VO",
}

_SOURCE_RE = re.compile(
    r"\b(REMUX|BluRay|BDRip|WEB-?DL|WEBRip|WEB|HDTV|DVDRip|DVD)\b", re.IGNORECASE
)
# \b (pas d'ancrage sur des points) : reutilisable aussi bien sur un
# `release_name` C411 ("...1080p...") que sur un nom de qualite Sonarr/Radarr
# ("WEBDL-1080p").
_RESOLUTION_RE = re.compile(r"\b(\d{3,4})p\b")
_CODEC_RE = re.compile(r"\.([xX]26[45]|[Hh]\.?26[45]|HEVC|AVC|MPEG2)-[A-Za-z0-9-]+$")
_LANGUAGE_RE = re.compile(
    r"\.(?:MULTI\.)?(VFF|VFQ|VF2|VFI|VOF|VO|VOSTFR|FRENCH|TRUEFRENCH)\."
)
_MULTI_RE = re.compile(r"\.MULTI\.")


@dataclass
class ReleaseQuality:
    """Qualite/langue extraites d'un `release_name`, source ou local."""

    raw: str
    resolution: Optional[int] = None
    source: Optional[str] = None
    codec: Optional[str] = None
    languages: list[str] = field(default_factory=list)
    multi: bool = False

    @property
    def source_rank(self) -> Optional[int]:
        """Plus bas = meilleure source. `None` si source non reconnue."""
        if self.source is None:
            return None
        try:
            return SOURCE_RANK.index(self.source.upper())
        except ValueError:
            return None

    @property
    def language_groups(self) -> set[str]:
        return {LANGUAGE_EQUIVALENTS.get(lang.upper(), lang.upper()) for lang in self.languages}


def parse_release_name(release_name: str) -> ReleaseQuality:
    """Extrait resolution/source/codec/langues d'un `release_name` C411.

    Best-effort : chaque champ non trouve reste `None`/vide, jamais d'erreur
    levee (une release mal nommee ne doit pas casser un scan complet).
    """
    resolution_match = _RESOLUTION_RE.search(release_name)
    source_match = _SOURCE_RE.search(release_name)
    codec_match = _CODEC_RE.search(release_name)
    languages = [m.upper() for m in _LANGUAGE_RE.findall(release_name)]

    return ReleaseQuality(
        raw=release_name,
        resolution=int(resolution_match.group(1)) if resolution_match else None,
        source=source_match.group(1).upper() if source_match else None,
        codec=codec_match.group(1).upper() if codec_match else None,
        languages=languages,
        multi=bool(_MULTI_RE.search(release_name)),
    )


def is_quality_upgrade(local: ReleaseQuality, remote: ReleaseQuality) -> bool:
    """`True` si `local` est une version meilleure ou non couverte par `remote`.

    Heuristique par defaut (voir hierarchies ci-dessus) : source d'abord
    (si les deux sont reconnues), puis resolution en departage. Une source
    ou resolution non reconnue ne bloque jamais la comparaison (traitee
    comme "inconnue", ni superieure ni inferieure).
    """
    local_rank, remote_rank = local.source_rank, remote.source_rank
    if local_rank is not None and remote_rank is not None and local_rank != remote_rank:
        return local_rank < remote_rank  # rang plus bas = meilleure source
    if local.resolution is not None and remote.resolution is not None:
        return local.resolution > remote.resolution
    return False


def is_language_gap(local: ReleaseQuality, remote: ReleaseQuality) -> bool:
    """`True` si `local` couvre un groupe de langue absent de `remote`."""
    if not local.language_groups:
        return False
    return not local.language_groups.issubset(remote.language_groups)


def language_groups_from_names(names: Iterable[str]) -> set[str]:
    """Normalise des noms de langue generiques (Sonarr/Radarr) en groupes.

    Un nom inconnu est conserve tel quel (en majuscules) plutot que jete :
    mieux vaut un groupe non reconnu explicite qu'une langue silencieusement
    perdue.
    """
    groups: set[str] = set()
    for name in names:
        if not name:
            continue
        key = name.strip().upper()
        groups.add(LANGUAGE_NAME_TO_GROUP.get(key, key))
    return groups


def build_quality(
    raw_name: Optional[str],
    fallback_resolution: Optional[int] = None,
    fallback_source: Optional[str] = None,
    fallback_language_names: Optional[Iterable[str]] = None,
) -> ReleaseQuality:
    """Qualite locale au mieux : parse `raw_name` s'il ressemble a un
    `release_name` (scene/tracker), sinon retombe sur les champs structures
    de Sonarr/Radarr (resolution/source numeriques, langues generiques).

    La distinction fine VFF/VFQ/VOSTFR n'existe que dans un `release_name`
    au format C411 : Sonarr/Radarr ne connaissent que "French"/"English"
    generiques, d'ou ce repli en dernier recours (voir `GAPSCAN.md`).
    """
    if raw_name and (_SOURCE_RE.search(raw_name) or _RESOLUTION_RE.search(raw_name)):
        quality = parse_release_name(raw_name)
        if not quality.languages and fallback_language_names:
            quality.languages = sorted(language_groups_from_names(fallback_language_names))
        return quality
    return ReleaseQuality(
        raw=raw_name or "",
        resolution=fallback_resolution,
        source=fallback_source.upper() if fallback_source else None,
        languages=sorted(language_groups_from_names(fallback_language_names or [])),
    )
