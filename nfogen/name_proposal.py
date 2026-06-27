"""Proposition automatique d'un release_name a partir des noms de fichiers
sources (vise les packs saison/episodes video, ex. C411).

Volontairement base UNIQUEMENT sur les noms de fichiers (et, en complement
optionnel, le tag `Title` embarque dans le conteneur video par l'auteur de la
release) : pas besoin de lire le CONTENU des fichiers pour obtenir une
suggestion a partir du nom seul, ce qui la rend utilisable instantanement
depuis le navigateur meme pour des fichiers de plusieurs centaines de Go (cf.
page "Generer" du frontend). Le tag `Title`, quand il est fourni, est traite
en priorite : c'est une indication ecrite par l'auteur de la release, donc
plus fiable qu'un nom de fichier parfois generique (ex. packs ou le nom de
fichier ne contient pas la resolution/le codec, mais le tag embarque oui).

C'est une PROPOSITION a relire avant generation, jamais une valeur appliquee
a l'aveugle : les champs non determinables (titre, identifiant, equipe...)
recoivent un placeholder explicite plutot qu'une valeur inventee, et chaque
ambiguite reelle (saisons ou equipes differentes dans le meme lot) est une
erreur plutot qu'un choix arbitraire.
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
_VIDEO_CODEC_RE = re.compile(r"\b([xX]26[45]|HEVC|AVC|MPEG-?2|[Hh]\.?26[45])\b")
_AUDIO_CODEC_RE = re.compile(r"\b(AC3|EAC3|AAC|DTS(?:-HD)?|FLAC|MP3|OPUS|TRUEHD)\b", re.IGNORECASE)
_CHANNELS_RE = re.compile(r"\b(\d(?:\.\d))\b")
# Tag d'equipe en fin de chaine, ex. "...x264-TEAM" ou "...x264 - Team44"
# (espaces autour du tiret tolerees : frequent dans les tags `Title` embarques,
# ecrits a la main, par opposition aux noms de fichiers generes automatiquement).
_TEAM_RE = re.compile(r"-\s*([A-Za-z0-9]+)\s*$")
_SOURCE_RE = re.compile(
    r"\b(WEB-?DL|WEBRip|BDRip|BDRemux|BluRay|HDTV|DVDRip|DSNP|NF|AMZN)\b", re.IGNORECASE
)
_SOURCE_ALIASES = {
    "webdl": "WEB", "web-dl": "WEB", "webrip": "WEB",
    "bdrip": "BDRip", "bdremux": "BluRay.REMUX", "bluray": "BluRay",
    "hdtv": "HDTV", "dvdrip": "DVDRip", "dsnp": "WEB.DSNP", "nf": "WEB.NF", "amzn": "WEB.AMZN",
}


@dataclass
class NameProposal:
    """Resultat d'une proposition : `name` est None si elle est impossible
    (ambiguite reelle, pas seulement une donnee manquante) ; `fields` donne
    la decomposition utilisee (utile pour deboguer/ajuster le template) ;
    `warnings` signale les champs devines/placeholder a relire avant generation."""

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
    """Retourne (saison, episode) si trouves dans `text`, episode est None
    pour un tag de saison seule (pack)."""
    match = _SEASON_EP_RE.search(text)
    if match:
        return match.group(1), match.group(2)
    match = _SEASON_ONLY_RE.search(text)
    if match:
        return match.group(1), None
    return None, None


def _extract_release_info(text: str, language_aliases: dict[str, str]) -> dict[str, str]:
    """Recherche resolution/codec video/audio/source/langue n'importe ou dans
    `text` (pas seulement dans des crochets `[...]`) : couvre aussi bien les
    noms de fichiers "scene" sans crochets que le tag `Title` embarque dans le
    conteneur, qui est du texte libre separe par des espaces."""
    info = {"language": "", "resolution": "", "video_codec": "", "audio": "", "source": ""}
    if not text:
        return info

    # Les alias les plus longs sont testes en premier (ex. "FR+JA" avant "FR")
    # pour qu'un alias plus court ne "gagne" pas juste parce qu'il est aussi
    # une sous-chaine litterale d'un alias plus specifique present dans le texte.
    for alias, normalized in sorted(language_aliases.items(), key=lambda kv: -len(kv[0])):
        if alias and alias in text:
            info["language"] = normalized
            break

    match = _RESOLUTION_RE.search(text)
    if match:
        info["resolution"] = match.group(1)

    match = _VIDEO_CODEC_RE.search(text)
    if match:
        info["video_codec"] = match.group(1).lower()

    match = _AUDIO_CODEC_RE.search(text)
    if match:
        info["audio"] = match.group(1).upper()
        channels_match = _CHANNELS_RE.search(text)
        if channels_match:
            info["audio"] += f".{channels_match.group(1)}"

    match = _SOURCE_RE.search(text)
    if match:
        info["source"] = _SOURCE_ALIASES.get(match.group(1).lower(), match.group(1))

    return info


def _merge_release_info(primary: dict[str, str], fallback: dict[str, str]) -> dict[str, str]:
    """`primary` (typiquement le tag `Title` embarque) l'emporte sur
    `fallback` (le nom de fichier) champ par champ, des qu'il a trouve une
    valeur."""
    return {key: primary.get(key) or fallback.get(key, "") for key in fallback}


def propose_video_release_name(
    filenames: list[str],
    config: dict[str, Any],
    title_hints: list[str | None] | None = None,
) -> NameProposal:
    """Construit une proposition de `release_name` pour la categorie video a
    partir des noms de fichiers (1 fichier = episode/film, plusieurs = pack
    saison). `config` est le contenu de `rules.json -> video -> name_proposal`
    (`template`, `language_aliases`) ; sans `template`, aucune proposition
    n'est possible pour ce profil (retourne un avertissement explicite, pas
    une erreur bloquante).

    `title_hints`, optionnel, donne pour chaque fichier (meme ordre/longueur
    que `filenames`) le tag `Title` du conteneur video s'il est connu (ex.
    extrait via MediaInfo cote navigateur) : quand il est present, il est
    prioritaire sur le nom de fichier pour la resolution/le codec/la
    source/l'equipe, car c'est une indication ecrite par l'auteur de la
    release. `None` ou liste de longueur differente : ignore silencieusement
    (proposition basee sur les noms de fichiers seuls, comme avant)."""
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
    language_aliases: dict[str, str] = config.get("language_aliases", {})

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
        # Le nom de fichier est prioritaire pour la saison/l'episode : c'est
        # generalement la convention de nommage la plus fiable et la plus
        # precise (le tag `Title` embarque, texte libre, omet parfois le
        # numero d'episode meme pour un fichier unique).
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

    info_from_filename = _extract_release_info(stems[0], language_aliases)
    info_from_hint = _extract_release_info(hints[0], language_aliases)
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
