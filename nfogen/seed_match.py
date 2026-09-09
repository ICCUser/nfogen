"""Detection d'une correspondance EXACTE entre un fichier local
(status GapStatus.COVERED) et UNE release C411 deja existante -- si
trouvee, permet de recuperer/seeder ce torrent au lieu de re-uploader
un fichier deja present a l'identique sur le tracker (retour
utilisateur, 2026-09-09).

Portee volontairement limitee a ce qui est parsable depuis un nom de
release TEXTE (resolution/source/codec video/langues, voir
quality.parse_release_name -- deja utilise pour TorznabRelease.quality)
+ tag d'equipe (name_proposal.extract_team_tag) + taille exacte en
octets. Le codec/canaux AUDIO ne sont PAS compares ici (jamais parses
depuis un simple nom de fichier dans ce projet) -- la verification
reelle des pieces par qBittorrent (voir seed_match_job_runner.py) reste
la seule preuve definitive d'une correspondance parfaite.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .name_proposal import extract_team_tag
from .quality import ReleaseQuality
from .torznab_client import TorznabRelease


@dataclass
class SeedMatchCandidate:
    guid: str
    release_name: str


def _quality_matches(a: ReleaseQuality, b: ReleaseQuality) -> bool:
    return (
        a.resolution == b.resolution
        and a.source == b.source
        and a.codec == b.codec
        and a.languages == b.languages
        and a.multi == b.multi
    )


def find_seed_match(
    local_quality: ReleaseQuality,
    local_team: Optional[str],
    local_size: int,
    matches: list[TorznabRelease],
) -> Optional[SeedMatchCandidate]:
    """`local_team` absent (aucun tag d'equipe detecte localement) ->
    jamais de correspondance proposee, trop peu de signal pour etre
    surs. Zero ou plusieurs candidats -> None, jamais un choix devine."""
    if local_team is None:
        return None
    candidates = [
        m for m in matches
        if m.size == local_size
        and extract_team_tag(m.title) == local_team
        and _quality_matches(local_quality, m.quality)
    ]
    if len(candidates) != 1:
        return None
    winner = candidates[0]
    return SeedMatchCandidate(guid=winner.guid, release_name=winner.title)
