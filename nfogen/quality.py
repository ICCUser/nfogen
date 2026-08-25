"""Extraction et comparaison de la qualite/langue d'un `release_name`.

Reutilise la meme convention que le profil C411 (voir
`nfogen/profiles/c411/rules.json`) : point-separe, resolution `\\d{3,4}p`,
codec video en fin de nom, tag de langue optionnellement precede de
`MULTI`. Utilise a la fois pour les releases locales (Sonarr/Radarr) et
les releases trouvees sur C411 (`c411_client.py`), afin de les comparer
(`GapScan`, voir `gapscan.py` et `GAPSCAN.md`).

Chaine de comparaison basee sur la politique anti-doublon REELLE de C411
(collee dans GAPSCAN.md le 2026-08-25, "Regle Copie directement du site
c411" + "Copie des regles de la page cat-video") :

    1. Langue (gere a part, voir `language_tier`/`is_language_gap`)
    2. Resolution
    3. Source (REMUX/BDMV/ISO = "pur", au sommet)
    4. Type audio (lossless > lossy)
    5. Codec video
    6. Canaux audio
    7. Codec audio (compatibilite -- volontairement PAS modelise, cf. note)
    8. HDR/Dolby Vision

Deux limites assumees, faute de la page "Guide des slots" (referencee par
la politique mais jamais fournie) :
  - Les criteres 3/5/8 (source/codec video/HDR) sont "contextuels au slot"
    selon la politique reelle -- cette page listerait la valeur de repli
    exacte par slot. Sans elle, un ordre GENERAL raisonnable est utilise
    ici (pas un ordre par profil/slot). A affiner si la page devient
    disponible.
  - Le critere 7 (compatibilite de codec audio, "AAC > EAC3" ou l'inverse
    selon le profil) n'est pas modelise du tout : trop ambigu sans la
    table par slot pour departager un cas qui n'aurait pas deja ete
    tranche par un critere plus prioritaire.
  - La regle de poids specifique aux WEBRip (accepte seulement si plus
    leger que le WEB-DL/BluRay existant, sauf meilleure langue) n'est pas
    modelisee : demanderait de faire remonter la taille des fichiers
    depuis Sonarr/Radarr (absente de `SonarrSeasonFile`/`RadarrMovieFile`
    aujourd'hui), volontairement laisse pour un lot ulterieur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Ordre du meilleur au moins bon ; un rang plus bas (index) = meilleure source.
# REMUX reste distingue de BDMV/ISO ici (tous trois sont "purs", cf. `pure`
# ci-dessous, qui prime sur ce rang) uniquement pour departager REMUX vs
# BDMV/ISO entre eux si jamais necessaire.
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

# Rang de langue (plus haut = mieux), section "Priorite des langues" de la
# politique C411 : MULTI.VF2 (VO+VFF+VFQ) > VF2 (VFF+VFQ sans VO) > un seul
# tag FR (VFF/VFQ/VFI/VOF/TRUEFRENCH -- coexistence, AUCUNE ne supplante les
# autres) > VOSTFR > rien. "VF" : marqueur generique (repli Sonarr/Radarr,
# variante FR precise inconnue), traite au meme rang que les tags precis.
_LANGUAGE_TIER: dict[str, int] = {
    "VF2": 3,
    "VFF": 2,
    "VFQ": 2,
    "VFI": 2,
    "VOF": 2,
    "TRUEFRENCH": 2,
    "FRENCH": 2,
    "VF": 2,
    "VOSTFR": 1,
    "VO": 0,  # VO seul (sans piste FR) n'apporte aucune couverture FR
}
_COEXISTENCE_TIER = 2

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

# Type audio (lossless > lossy) -- section "Audio" de la politique C411.
# Verifie les motifs lossless AVANT lossy : "DTS.HD.MA"/"DTSX" contiennent
# "DTS", qui serait sinon detecte comme lossy (DTS core) en premier.
_LOSSLESS_RE = re.compile(r"\b(TRUEHD|DTS[.\s]?HD[.\s]?MA|DTSX|LPCM)\b", re.IGNORECASE)
_LOSSY_RE = re.compile(
    r"\b(AAC|OPUS|VORBIS|MP3|AC3|EAC3|DDP|DTS)\b", re.IGNORECASE
)

# Codec video : AV1/HEVC/x265 places au meme rang (l'ordre entre les deux
# est explicitement "contextuel au slot" dans la politique -- non tranche
# ici faute de la table par slot), tous deux au-dessus de AVC/x264, lui-meme
# au-dessus des codecs "a titre exceptionnel uniquement" (MPEG2/XVID/VC-1).
_VIDEO_CODEC_RANK: dict[str, int] = {
    "AV1": 2,
    "HEVC": 2,
    "H265": 2,
    "X265": 2,
    "AVC": 1,
    "H264": 1,
    "X264": 1,
    "MPEG2": 0,
    "XVID": 0,
    "H263": 0,
    "VC1": 0,
    "VC-1": 0,
}

# HDR/Dolby Vision -- combine (DV+HDR10[+]) prefere a HDR seul (fallback
# garanti sur les lecteurs non-DV), lui-meme prefere a DV seul (aucun
# fallback HDR pour les lecteurs non compatibles Dolby Vision).
_HDR_COMBINED_RE = re.compile(r"\bDV\.HDR10(?:PLUS)?\b", re.IGNORECASE)
_HDR10PLUS_RE = re.compile(r"\bHDR10PLUS\b", re.IGNORECASE)
_HDR10_RE = re.compile(r"\bHDR10?\b", re.IGNORECASE)
_DV_ONLY_RE = re.compile(r"\bDV\b")

_SOURCE_RE = re.compile(
    r"\b(REMUX|BluRay|BDRip|WEB-?DL|WEBRip|WEB|HDTV|DVDRip|DVD)\b", re.IGNORECASE
)
_PURE_RE = re.compile(r"\.(REMUX|BDMV|ISO)\.", re.IGNORECASE)
# \b (pas d'ancrage sur des points) : reutilisable aussi bien sur un
# `release_name` C411 ("...1080p...") que sur un nom de qualite Sonarr/Radarr
# ("WEBDL-1080p").
_RESOLUTION_RE = re.compile(r"\b(\d{3,4})p\b")
_CODEC_RE = re.compile(r"\.([xX]26[45]|[Hh]\.?26[45]|HEVC|AVC|MPEG2|AV1|XVID|VC-?1)-[A-Za-z0-9-]+$")
_LANGUAGE_RE = re.compile(
    r"\.(?:MULTI\.)?(VFF|VFQ|VF2|VFI|VOF|VO|VOSTFR|FRENCH|TRUEFRENCH)\.", re.IGNORECASE
)
_MULTI_RE = re.compile(r"\.MULTI\.", re.IGNORECASE)
_CHANNELS_RE = re.compile(r"\b(\d)\.(\d)\b")


@dataclass
class ReleaseQuality:
    """Qualite/langue extraites d'un `release_name`, source ou local."""

    raw: str
    resolution: Optional[int] = None
    source: Optional[str] = None
    codec: Optional[str] = None
    languages: list[str] = field(default_factory=list)
    multi: bool = False
    pure: bool = False  # REMUX/BDMV/ISO : structure "sans reencodage"

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
    def language_tier(self) -> int:
        """Meilleur rang de langue parmi les tags detectes (voir
        `_LANGUAGE_TIER`). `MULTI.VF2` (VO+VFF+VFQ) traite a part : rang
        strictement au-dessus de `VF2` seul (VFF+VFQ sans VO)."""
        if not self.languages:
            return 0
        tags = {lang.upper() for lang in self.languages}
        if self.multi and "VF2" in tags:
            return 4
        return max(_LANGUAGE_TIER.get(tag, 0) for tag in tags)

    @property
    def audio_type_rank(self) -> Optional[int]:
        """1 = lossless, 0 = lossy, `None` si aucun codec audio detecte."""
        if _LOSSLESS_RE.search(self.raw):
            return 1
        if _LOSSY_RE.search(self.raw):
            return 0
        return None

    @property
    def video_codec_rank(self) -> Optional[int]:
        if self.codec is None:
            return None
        return _VIDEO_CODEC_RANK.get(self.codec.upper().replace("-", ""))

    @property
    def audio_channels(self) -> Optional[float]:
        """Derniere occurrence de type 'N.N' dans le nom (canaux audio,
        ex. '5.1'/'7.1') -- convention de nommage C411, le motif apparait
        juste apres le codec audio. Best-effort : peut matcher un faux
        positif sur un nom atypique, jamais d'erreur levee."""
        matches = _CHANNELS_RE.findall(self.raw)
        if not matches:
            return None
        front, back = matches[-1]
        return float(f"{front}.{back}")

    @property
    def hdr_rank(self) -> Optional[int]:
        """2 = HDR10(+) combine avec Dolby Vision (fallback garanti), 1 =
        HDR seul (HDR10/HDR10+), 0 = Dolby Vision seul (aucun fallback
        HDR), `None` si aucun tag HDR/DV detecte."""
        if _HDR_COMBINED_RE.search(self.raw):
            return 2
        if _HDR10PLUS_RE.search(self.raw) or _HDR10_RE.search(self.raw):
            return 1
        if _DV_ONLY_RE.search(self.raw):
            return 0
        return None


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
        pure=bool(_PURE_RE.search(release_name)),
    )


def _compare(local_value: object, remote_value: object, higher_is_better: bool) -> int:
    """1 si `local` gagne ce critere, -1 si `remote` gagne, 0 si egaux ou si
    l'un des deux est inconnu (une caracteristique non detectee ne doit
    jamais faire pencher la comparaison)."""
    if local_value is None or remote_value is None or local_value == remote_value:
        return 0
    wins = local_value > remote_value if higher_is_better else local_value < remote_value
    return 1 if wins else -1


def is_quality_upgrade(local: ReleaseQuality, remote: ReleaseQuality) -> bool:
    """`True` si `local` est une version meilleure ou non couverte par
    `remote`, selon la chaine de priorite C411 (hors langue, geree a part
    par `is_language_gap`) : le premier critere qui differe l'emporte,
    exactement comme la politique reelle du site ("le premier critere qui
    differe determine le vainqueur")."""
    for local_value, remote_value, higher_is_better in (
        (local.resolution, remote.resolution, True),
        (local.pure, remote.pure, True),
        (local.source_rank, remote.source_rank, False),  # rang plus bas = meilleure source
        (local.audio_type_rank, remote.audio_type_rank, True),
        (local.video_codec_rank, remote.video_codec_rank, True),
        (local.audio_channels, remote.audio_channels, True),
        (local.hdr_rank, remote.hdr_rank, True),
    ):
        outcome = _compare(local_value, remote_value, higher_is_better)
        if outcome != 0:
            return outcome > 0
    return False


def is_language_gap(local: ReleaseQuality, remote: ReleaseQuality) -> bool:
    """`True` si `local` couvre une langue qu'aucune release comparable de
    `remote` ne couvre deja.

    Un rang de langue strictement superieur couvre tout rang inferieur
    (`VF2` contient de fait les pistes VFF+VFQ, `MULTI.VF2` contient tout).
    Au rang de coexistence (VFF/VFQ/VFI/VOF/TRUEFRENCH), seul un tag
    IDENTIQUE (ou le marqueur generique `VF`, cf. `language_groups_from_names`)
    couvre : ces variantes coexistent sans se remplacer, ce ne sont PAS des
    doublons l'une de l'autre (regle C411, section "Coexistences
    temporaires")."""
    local_tier = local.language_tier
    if local_tier == 0:
        return False
    remote_tier = remote.language_tier
    if remote_tier > local_tier:
        return False
    if remote_tier < local_tier:
        return True
    if local_tier != _COEXISTENCE_TIER:
        return False  # meme rang, hors coexistence (VOSTFR/VF2/MULTI.VF2) : suffisant
    local_tags = {lang.upper() for lang in local.languages}
    remote_tags = {lang.upper() for lang in remote.languages}
    if "VF" in local_tags or "VF" in remote_tags:
        return False  # marqueur generique : compatible avec n'importe quel tag precis
    return local_tags.isdisjoint(remote_tags)


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
