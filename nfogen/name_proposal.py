"""Proposition automatique d'un release_name a partir des noms de fichiers
sources (vise les packs saison/episodes video, ex. C411).

Base uniquement sur les noms de fichiers et, en complement optionnel, le tag
`Title` embarque dans le conteneur video (pas le contenu du fichier) : utilisable
instantanement, meme pour des fichiers de plusieurs centaines de Go. C'est
une PROPOSITION a relire, jamais une valeur appliquee a l'aveugle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_YEAR_RE = re.compile(r"[(.](?P<year>(?:19|20)\d{2})[).]")
_SEASON_EP_RE = re.compile(r"[Ss](\d{2})[Ee](\d{2})")
_SEASON_ONLY_RE = re.compile(r"[Ss](\d{2})(?![Ee\d])")
_BRACKETS_RE = re.compile(r"\[([^\]]+)\]")
_RESOLUTION_RE = re.compile(r"\b(\d{3,4})p\b", re.IGNORECASE)
_CHANNELS_RE = re.compile(r"\b(\d(?:\.\d))\b")
_TEAM_RE = re.compile(r"-\s*([A-Za-z0-9]+)\s*$")
# Resolution/saison-episode/annee/position du tag d'equipe : conventions
# jugees quasi universelles dans l'ecosysteme des trackers, restent cablees
# ici. Vocabulaire/normalisation des sources et codecs, eux, varient d'un
# tracker a l'autre : entierement pilotes par le profil (voir
# _detect_via_aliases, AUTOMATION.md sous-projet 3).


@dataclass
class NameProposal:
    """`name` est None si la proposition est impossible (ambiguite reelle)."""

    name: str | None
    fields: dict[str, str]
    warnings: list[str] = field(default_factory=list)


def _strip_ext(filename: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,4}$", "", filename)


def _clean_title(stem: str) -> str:
    cut_points = [m.start() for rgx in (_YEAR_RE, _SEASON_EP_RE, _SEASON_ONLY_RE, _BRACKETS_RE)
                  for m in [rgx.search(stem)] if m]
    title_part = stem[: min(cut_points)] if cut_points else stem
    title_part = title_part.strip(" -._")
    ascii_title = title_part.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[\s_]+", ".", ascii_title.strip())
    return re.sub(r"\.+", ".", cleaned).strip(".")


def _extract_team(text: str) -> str | None:
    without_brackets = _BRACKETS_RE.sub("", text).strip()
    match = _TEAM_RE.search(without_brackets)
    return match.group(1) if match else None


def _find_season(text: str) -> tuple[str | None, str | None]:
    """(saison, episode) ; episode est None pour un tag de saison seule (pack)."""
    match = _SEASON_EP_RE.search(text)
    if match:
        return match.group(1), match.group(2)
    match = _SEASON_ONLY_RE.search(text)
    if match:
        return match.group(1), None
    return None, None


def _detect_via_aliases(text: str, aliases: dict[str, str]) -> str:
    """Cherche le plus long alias (cle) de `aliases` present dans `text`
    (insensible a la casse), renvoie sa forme normalisee (valeur associee).
    Chaine vide si aucun alias ne correspond. Mecanisme generique reutilise
    pour la langue, la source et les codecs video/audio (voir
    AUTOMATION.md, sous-projet 3) -- vocabulaire ET normalisation
    entierement pilotes par le profil, aucun cablage specifique a un
    tracker dans ce module."""
    lowered = text.lower()
    for alias, normalized in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        if alias and alias.lower() in lowered:
            return normalized
    return ""


def _extract_release_info(text: str, alias_groups: dict[str, dict[str, str]]) -> dict[str, str]:
    """Cherche resolution/codec video/audio/source/langue n'importe ou dans
    `text`. `alias_groups` : {"language": {...}, "source": {...},
    "video_codec": {...}, "audio_codec": {...}} -- vocabulaire et
    normalisation entierement pilotes par le profil."""
    info = {"language": "", "resolution": "", "video_codec": "", "audio": "", "source": ""}
    if not text:
        return info

    info["language"] = _detect_via_aliases(text, alias_groups["language"])

    match = _RESOLUTION_RE.search(text)
    if match:
        info["resolution"] = match.group(1)

    info["video_codec"] = _detect_via_aliases(text, alias_groups["video_codec"])

    audio_codec = _detect_via_aliases(text, alias_groups["audio_codec"])
    if audio_codec:
        info["audio"] = audio_codec
        channels_match = _CHANNELS_RE.search(text)
        if channels_match:
            info["audio"] += f".{channels_match.group(1)}"

    info["source"] = _detect_via_aliases(text, alias_groups["source"])

    return info


def _merge_release_info(primary: dict[str, str], fallback: dict[str, str]) -> dict[str, str]:
    """`primary` (typiquement le tag `Title`) l'emporte sur `fallback` (nom de fichier)."""
    return {key: primary.get(key) or fallback.get(key, "") for key in fallback}


def propose_video_release_name(
    filenames: list[str],
    config: dict[str, Any],
    title_hints: list[str | None] | None = None,
) -> NameProposal:
    """Construit une proposition de `release_name` (1 fichier = episode/film,
    plusieurs = pack saison). `config` vient de `rules.json -> video ->
    name_proposal` (`template`, `language_aliases`). `title_hints`, optionnel
    (meme ordre/longueur que `filenames`), est prioritaire sur le nom de
    fichier pour resolution/codec/source/equipe."""
    if not filenames:
        return NameProposal(None, {}, ["Aucun fichier fourni."])

    template = config.get("template")
    if not template:
        return NameProposal(
            None,
            {},
            [
                "Aucun modele de proposition configure pour ce profil "
                "(rules.json -> video -> name_proposal.template)."
            ],
        )
    alias_groups: dict[str, dict[str, str]] = {
        "language": config.get("language_aliases", {}),
        "source": config.get("source_aliases", {}),
        "video_codec": config.get("video_codec_aliases", {}),
        "audio_codec": config.get("audio_codec_aliases", {}),
    }

    warnings: list[str] = []
    stems = [_strip_ext(f) for f in filenames]
    raw_hints = title_hints if title_hints and len(title_hints) == len(filenames) else None
    hints: list[str] = [h or "" for h in (raw_hints or [None] * len(filenames))]

    title = _clean_title(stems[0])
    if not title:
        warnings.append("Titre indéterminable depuis le nom de fichier : à compléter manuellement.")

    seasons: set[str] = set()
    has_single_episode = len(stems) == 1
    episode = None
    for stem, hint in zip(stems, hints):
        season, ep = _find_season(stem)
        if season is None and hint:
            season, ep = _find_season(hint)
        if season is not None:
            seasons.add(season)
            if has_single_episode and ep:
                episode = ep

    if len(seasons) > 1:
        return NameProposal(
            None,
            {},
            [
                "Plusieurs saisons détectées ({}) : impossible de proposer un nom de pack unique, "
                "vérifiez la sélection de fichiers.".format(", ".join(sorted(seasons)))
            ],
        )

    years = {
        m.group("year")
        for stem, hint in zip(stems, hints)
        for text in (stem, hint)
        for m in [_YEAR_RE.search(text)] if m
    }

    if seasons:
        season = next(iter(seasons))
        identifier = f"S{season}E{episode}" if episode else f"S{season}"
    elif years:
        if len(years) > 1:
            warnings.append(
                "Plusieurs années détectées ({}), '{}' utilisée.".format(
                    ", ".join(sorted(years)), sorted(years)[0]
                )
            )
        identifier = sorted(years)[0]
    else:
        identifier = "IDENTIFIANT"
        warnings.append("Aucune année ni tag de saison détecté : identifiant à compléter manuellement.")

    info_from_filename = _extract_release_info(stems[0], alias_groups)
    info_from_hint = _extract_release_info(hints[0], alias_groups)
    info = _merge_release_info(info_from_hint, info_from_filename)

    if not info["language"]:
        for bracket in _BRACKETS_RE.findall(stems[0]) + _BRACKETS_RE.findall(hints[0]):
            if re.fullmatch(r"[A-Za-z]{2,4}(?:\+[A-Za-z]{2,4})*", bracket):
                warnings.append(
                    f"Tag de langue '{bracket}' sans correspondance configurée "
                    "(rules.json -> video -> name_proposal.language_aliases) : à compléter."
                )
                info["language"] = "LANGINCONNU"
                break

    if not info["resolution"]:
        warnings.append("Résolution non détectée dans le nom de fichier.")
    if not info["video_codec"]:
        warnings.append("Codec vidéo non détecté dans le nom de fichier.")

    teams = set()
    for stem, hint in zip(stems, hints):
        team = (_extract_team(hint) if hint else None) or _extract_team(stem)
        if team:
            teams.add(team)
    if len(teams) > 1:
        return NameProposal(
            None,
            {},
            [
                "Tags d'équipe différents détectés ({}) sur les fichiers sélectionnés : vérifiez "
                "qu'ils appartiennent bien à la même release.".format(", ".join(sorted(teams)))
            ],
        )
    if teams:
        team = next(iter(teams))
    else:
        team = "NOTAG"
        warnings.append("Aucun tag d'équipe détecté dans les noms de fichiers : 'NOTAG' à remplacer.")

    fields = {
        "title": title or "TITRE",
        "identifier": identifier,
        "language": info["language"],
        "resolution": info["resolution"],
        "video_codec": info["video_codec"],
        "audio": info["audio"],
        "source": info["source"],
        "team": team,
    }

    try:
        name = template.format(**fields)
    except KeyError as exc:
        msg = f"Champ manquant dans le modèle de proposition : {exc}"
        return NameProposal(None, fields, warnings + [msg])

    name = re.sub(r"\.{2,}", ".", name).strip(".")
    return NameProposal(name, fields, warnings)
