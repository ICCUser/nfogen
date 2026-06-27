"""Extraction des metadonnees depuis les fichiers/dossiers sources.

Chaque fonction renvoie des donnees brutes/normalisees ; la mise en forme
finale est laissee aux profils (voir profiles/). On separe ainsi l'extraction
(ce qu'on lit) du rendu (comment on l'ecrit), ce qui garde le coeur modulaire.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import formats

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac"}
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".wmv", ".m4v"}

_COMPLETE_NAME_RE = re.compile(r"^(Complete name\s*:\s*).*$", re.MULTILINE)


def _video_files(source: Path) -> list[Path]:
    return sorted(p for p in source.iterdir() if p.suffix.lower() in VIDEO_EXTS)


def extract_video_text(source: Path, *, full: bool = False) -> str:
    """Renvoie la sortie texte MediaInfo (vue par defaut) d'un fichier video.

    C'est exactement le format attendu par le profil 'Films & Videos' de C411,
    a une exception deliberee : le champ "Complete name" est reduit au seul
    nom de fichier (jamais le chemin complet local/temporaire) avant d'etre
    renvoye. Le chemin sur la machine qui genere le NFO (utilisateur Windows,
    arborescence de telechargement, dossier temporaire d'upload...) n'a
    aucune valeur informative pour qui lit le NFO et ne doit pas fuiter dans
    un fichier destine a etre partage publiquement.

    Necessite libmediainfo (paquet systeme).
    """
    from pymediainfo import MediaInfo

    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    text = MediaInfo.parse(str(source), output="", full=full)
    if not isinstance(text, str):  # garde-fou : selon la version
        text = str(text)
    text = text.replace("\r\n", "\n").strip("\n") + "\n"
    return _COMPLETE_NAME_RE.sub(lambda m: f"{m.group(1)}{source.name}", text, count=1)


def extract_video_dir_text(source: Path, *, full: bool = False) -> str:
    """Concatene la sortie texte MediaInfo de chaque video d'un dossier.

    Format des packs saison C411 (plusieurs episodes dans un seul NFO) : les
    blocs General/Video/Audio/Menu de chaque fichier se suivent, tries par
    nom de fichier, separes par une ligne vide.
    """
    source = Path(source)
    files = _video_files(source)
    if not files:
        raise ValueError(f"Aucun fichier video trouve dans : {source}")
    return "\n".join(extract_video_text(p, full=full) for p in files)


def extract_video_metadata(source: Path) -> dict[str, Any]:
    """Donnees video structurees (MediaInfo), pas le texte de rendu.

    Sert aux validateurs de profil pour comparer ce qu'annonce un
    release_name (langue, resolution, codec) a ce que le fichier contient
    reellement, meme quand le rendu video est un passthrough brut :
    - `video_height` / `video_format` : piste video (ex. 1080, "AVC").
    - `audio_languages` / `subtitle_languages` : une entree par piste, code
      de langue rapporte par MediaInfo ou None si la piste n'a pas ce tag.
    - `general_title` : tag `Title` du conteneur (piste General), souvent
      renseigne a la main par l'auteur de la release avec un descriptif
      complet (resolution, codec, equipe...) -- utile pour la proposition de
      `release_name` (`nfogen.name_proposal`) quand le nom de fichier seul
      n'est pas assez precis. None si absent.
    """
    from pymediainfo import MediaInfo

    source = Path(source)
    mi = MediaInfo.parse(str(source))
    video = next((t for t in mi.tracks if t.track_type == "Video"), None)
    general = next((t for t in mi.tracks if t.track_type == "General"), None)
    return {
        "video_height": video.height if video is not None else None,
        "video_format": video.format if video is not None else None,
        "audio_languages": [t.language for t in mi.tracks if t.track_type == "Audio"],
        "subtitle_languages": [t.language for t in mi.tracks if t.track_type == "Text"],
        "general_title": getattr(general, "title", None) if general is not None else None,
    }


def extract_video_dir_metadata(source: Path) -> list[dict[str, Any]]:
    """Comme `extract_video_metadata`, pour chaque fichier video d'un dossier
    (pack saison). Chaque dict a en plus une cle 'name' (nom du fichier), pour
    que les avertissements de validation puissent identifier l'episode concerne.
    """
    source = Path(source)
    out = []
    for p in _video_files(source):
        meta = extract_video_metadata(p)
        meta["name"] = p.name
        out.append(meta)
    return out


def _audio_track_info(path: Path) -> dict[str, Any]:
    """Tags + duree d'un fichier audio via mutagen (best effort)."""
    from mutagen import File as MutagenFile

    info: dict[str, Any] = {
        "path": path,
        "size": path.stat().st_size,
        "duration": 0.0,
        "artist": None,
        "title": None,
        "track_no": None,
    }
    try:
        mf = MutagenFile(str(path), easy=True)
    except Exception:
        mf = None
    if mf is not None:
        if getattr(mf, "info", None) is not None:
            info["duration"] = float(getattr(mf.info, "length", 0.0) or 0.0)
        tags = getattr(mf, "tags", None) or {}

        def first(key: str):
            val = tags.get(key)
            if isinstance(val, list):
                return val[0] if val else None
            return val

        info["artist"] = first("artist")
        info["title"] = first("title")
        tn = first("tracknumber")
        if tn:
            try:
                info["track_no"] = int(str(tn).split("/")[0])
            except ValueError:
                pass
    if not info["title"]:
        info["title"] = path.stem
    return info


def extract_album(source: Path) -> dict[str, Any]:
    """Construit le contexte d'un album a partir d'un dossier de fichiers audio.

    Renvoie un dict pret a alimenter le template audio (artiste, album, codec,
    tracklist, taille et duree totales...). Les champs editoriaux non lisibles
    dans les tags (genre, annee) peuvent etre completes par l'appelant.
    """
    source = Path(source)
    files = sorted(
        (p for p in source.iterdir() if p.suffix.lower() in AUDIO_EXTS),
        key=lambda p: p.name,
    ) if source.is_dir() else [source]
    if not files:
        raise ValueError(f"Aucun fichier audio trouve dans : {source}")

    tracks_raw = [_audio_track_info(p) for p in files]
    # On ordonne par numero de piste si disponible, sinon par nom.
    tracks_raw.sort(key=lambda t: (t["track_no"] is None, t["track_no"], t["path"].name))

    # Detail technique du 1er fichier (representatif de l'album) via MediaInfo.
    tech = _audio_tech(files[0])

    total_size = sum(t["size"] for t in tracks_raw)
    total_duration = sum(t["duration"] for t in tracks_raw)

    tracklist = []
    for i, t in enumerate(tracks_raw, start=1):
        artist = t["artist"] or tech.get("album_artist") or ""
        name = f"{artist} - {t['title']}" if artist else t["title"]
        tracklist.append(
            {
                "index": i,
                "name": name,
                "title": t["title"],
                "artist": artist,
                "size": t["size"],
                "duration": t["duration"],
            }
        )

    return {
        "artist": tech.get("album_artist") or (tracks_raw[0]["artist"] or ""),
        "album": tech.get("album") or source.name,
        "genre": tech.get("genre") or "",
        "year": tech.get("year") or "",
        "codec": tech.get("codec") or "",
        "format": tech.get("format") or "",
        "overall_bit_rate": tech.get("bit_rate") or "",
        "bit_rate_mode": tech.get("bit_rate_mode") or "",
        "channel": tech.get("channel") or "",
        "quality": tech.get("quality") or "",
        "writing_library": tech.get("writing_library") or "undefined",
        "encoding_settings": tech.get("encoding_settings") or "undefined",
        "tracklist": tracklist,
        "total_size": total_size,
        "total_duration": total_duration,
        "playing_time": formats.mmss(total_duration),
    }


def _audio_tech(path: Path) -> dict[str, Any]:
    """Detail technique audio via MediaInfo (codec, debit, canaux...)."""
    try:
        from pymediainfo import MediaInfo

        mi = MediaInfo.parse(str(path))
    except Exception:
        return {}
    g = next((t for t in mi.tracks if t.track_type == "General"), None)
    a = next((t for t in mi.tracks if t.track_type == "Audio"), None)
    out: dict[str, Any] = {}
    if g is not None:
        out["album"] = g.album
        out["album_artist"] = g.album_performer or g.performer
        out["genre"] = g.genre
        out["year"] = g.recorded_date or g.tagged_date
        out["overall"] = g.overall_bit_rate
    if a is not None:
        out["codec"] = a.format
        out["format"] = " / ".join(
            x for x in [a.format, a.format_version, a.format_profile] if x
        )
        out["bit_rate"] = f"{int(a.bit_rate) // 1000} kb/s" if a.bit_rate else ""
        out["bit_rate_mode"] = a.bit_rate_mode
        ch = f"{a.channel_s} channels" if a.channel_s else ""
        sr = f"{float(a.sampling_rate) / 1000:.1f} kHz" if a.sampling_rate else ""
        bd = f"{a.bit_depth} bits" if a.bit_depth else ""
        out["channel"] = " / ".join(x for x in [ch, sr, bd] if x)
        out["quality"] = a.compression_mode
        out["writing_library"] = a.writing_library
        out["encoding_settings"] = a.encoding_settings
    return {k: v for k, v in out.items() if v}


def scan_files(source: Path) -> dict[str, Any]:
    """Infos generiques d'un fichier/dossier : nombre, taille totale, formats.

    Utile aux profils Jeux / eBook / Impression 3D pour pre-remplir les champs
    derivables automatiquement, le reste etant fourni par l'appelant.
    """
    source = Path(source)
    if source.is_dir():
        files = [p for p in source.rglob("*") if p.is_file()]
    else:
        files = [source]
    total = sum(p.stat().st_size for p in files)
    formats_set = sorted({p.suffix.lstrip(".").upper() for p in files if p.suffix})
    return {
        "file_count": len(files),
        "total_size": total,
        "total_size_bin": formats.human_size_bin(total),
        "total_size_dec": formats.human_size_dec(total),
        "formats": formats_set,
        "format": " et ".join(formats_set),
    }
