"""Tests de nfogen (profil C411).

Les tests video/audio necessitent ffmpeg + libmediainfo ; ils sont ignores
proprement si l'environnement ne les fournit pas.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import nfogen
from nfogen import formats

HAS_FFMPEG = shutil.which("ffmpeg") is not None
try:
    from pymediainfo import MediaInfo

    HAS_MEDIAINFO = MediaInfo.can_parse()
except Exception:
    HAS_MEDIAINFO = False


# --------------------------------------------------------------------------- #
# Formatage
# --------------------------------------------------------------------------- #
def test_human_sizes():
    assert formats.human_size_bin(3.97 * 1024**3).endswith("GiB")
    assert formats.human_size_dec(31_440_000_000) == "31.44 Go"


def test_alignment_helpers():
    assert formats.dotpad("Year", "2002", 35) == "Year" + "." * 31 + ": 2002"
    assert formats.colonpad("OS", "Win", 15) == "OS" + " " * 13 + ": Win"


def test_banner_width():
    b = formats.banner("X", width=44)
    lines = b.split("\n")
    assert len(lines[0]) == 44 and len(lines[2]) == 44


# --------------------------------------------------------------------------- #
# Registre
# --------------------------------------------------------------------------- #
def test_registry_lists_c411():
    av = nfogen.list_available()
    assert "video" in av["c411"]
    assert set(av["c411"]) >= {"audio", "game", "ebook", "print3d", "video"}


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        nfogen.generate(category="video", profile="inconnu", data={"raw_text": "x"})


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #
VALID_RELEASE_NAME = "Kaamelott.S05E01-E06.VFF.1080p.BluRay.AC3.5.1.x264-Dam"


def test_video_raw_text_passthrough():
    nfo = nfogen.generate(
        category="video",
        data={"raw_text": "General\nFormat : Matroska", "release_name": VALID_RELEASE_NAME},
    )
    assert nfo.startswith("General")
    assert nfo.endswith("\n")


def test_extract_video_text_uses_full_parse_speed(tmp_path: Path, monkeypatch):
    """Incident reel (2026-08-30) : le "Bit rate" de la piste Video est
    absent du rapport MediaInfo pour un fichier CRF (HandBrake) a plusieurs
    pistes audio, en analyse partielle (parse_speed par defaut de
    pymediainfo, 0.5) -- la meme commande avec --ParseSpeed=1.0 sur le
    fichier reel de l'utilisateur fait apparaitre la valeur. C411 rejette
    l'upload ("Champ non renseigne : Debit video") car sa description
    "Generee automatiquement" lit ce rapport. Corrige : analyse complete
    systematique."""
    from nfogen import extract

    mkv = tmp_path / "t.mkv"
    mkv.write_bytes(b"x")
    captured: dict = {}

    def fake_parse(path, **kwargs):
        captured.update(kwargs)
        return "General\nComplete name : orig.mkv\n"

    monkeypatch.setattr("pymediainfo.MediaInfo.parse", fake_parse)
    extract.extract_video_text(mkv)

    assert captured.get("parse_speed") == 1.0


def test_extract_video_metadata_uses_full_parse_speed(tmp_path: Path, monkeypatch):
    """Meme correctif que extract_video_text, pour les donnees structurees
    consommees par l'heuristique anti-upscale (rules.upscale_warnings) --
    un video_bit_rate manque a tort en analyse partielle laisse
    l'heuristique silencieusement inactive plutot que de devine."""
    from nfogen import extract

    mkv = tmp_path / "t.mkv"
    mkv.write_bytes(b"x")
    captured: dict = {}

    class _FakeTrack:
        track_type = "General"

    def fake_parse(path, **kwargs):
        captured.update(kwargs)

        class _Result:
            tracks = [_FakeTrack()]

        return _Result()

    monkeypatch.setattr("pymediainfo.MediaInfo.parse", fake_parse)
    extract.extract_video_metadata(mkv)

    assert captured.get("parse_speed") == 1.0


@pytest.mark.skipif(not (HAS_FFMPEG and HAS_MEDIAINFO), reason="ffmpeg/libmediainfo requis")
def test_video_from_file(tmp_path: Path):
    mkv = tmp_path / "t.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=24", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(mkv)], check=True,
    )
    nfo = nfogen.generate(source=mkv, data={"release_name": VALID_RELEASE_NAME})  # categorie auto-detectee
    assert "General" in nfo and "Video" in nfo and "Complete name" in nfo
    # alignement a la MediaInfo : ': ' apparait apres un label complete
    line = next(x for x in nfo.splitlines() if x.startswith("Format "))
    assert " : " in line.replace("  ", " ") or ": " in line


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_video_requires_release_name():
    """'release_name' est obligatoire pour le profil C411 : generation bloquee si absent."""
    with pytest.raises(ValueError, match="release_name"):
        nfogen.generate(category="video", data={"raw_text": "General\nFormat : Matroska"})


def test_video_rejects_non_conforming_release_name():
    """Un release_name qui ne respecte pas la convention C411 bloque la generation."""
    with pytest.raises(ValueError, match="convention C411"):
        nfogen.generate(
            category="video",
            data={"raw_text": "General\nFormat : Matroska", "release_name": "Kaamelott S05"},
        )


def test_no_warnings_for_raw_text_passthrough():
    """Avec un release_name conforme mais sans source, rien d'autre a valider."""
    warnings: list[str] = []
    nfogen.generate(
        category="video",
        data={"raw_text": "General\nFormat : Matroska", "release_name": VALID_RELEASE_NAME},
        warnings=warnings,
    )
    assert warnings == []


def test_no_warnings_when_no_validator_registered():
    """'game' n'a pas de validateur : la liste passee reste vide."""
    warnings: list[str] = []
    nfogen.generate(category="game", data={"title": "Mon Jeu"}, warnings=warnings)
    assert warnings == []


# --------------------------------------------------------------------------- #
# Regle de nommage du fichier NFO (register_filename)
# --------------------------------------------------------------------------- #
def test_filename_rule_for_video():
    """Le profil impose <release_name>.nfo comme nom de fichier pour 'video'."""
    filename: list[str] = []
    nfogen.generate(
        category="video",
        data={"raw_text": "General\nFormat : Matroska", "release_name": VALID_RELEASE_NAME},
        filename=filename,
    )
    assert filename == [f"{VALID_RELEASE_NAME}.nfo"]


def test_no_filename_rule_for_game():
    """'game' n'a pas de regle de nommage : la liste passee reste vide."""
    filename: list[str] = []
    nfogen.generate(category="game", data={"title": "Mon Jeu"}, filename=filename)
    assert filename == []


def test_cli_resolve_output_path_no_rule():
    """Sans regle de nommage, -o est utilise tel quel."""
    from nfogen.cli import _resolve_output_path

    assert _resolve_output_path("mon_nom.nfo", None) == "mon_nom.nfo"
    assert _resolve_output_path(None, None) is None


def test_cli_resolve_output_path_matching_name():
    from nfogen.cli import _resolve_output_path

    assert _resolve_output_path("Film.nfo", "Film.nfo") == "Film.nfo"


def test_cli_resolve_output_path_directory(tmp_path: Path):
    """-o pointant vers un dossier : nfogen choisit le nom impose par le profil."""
    from nfogen.cli import _resolve_output_path

    out = _resolve_output_path(str(tmp_path), "Film.nfo")
    assert out == str(tmp_path / "Film.nfo")


def test_cli_resolve_output_path_mismatch_blocks():
    """-o avec un nom different de celui impose par le profil : refus explicite."""
    from nfogen.cli import _resolve_output_path

    with pytest.raises(ValueError, match="non conforme"):
        _resolve_output_path("autre_nom.nfo", "Film.nfo")


def test_cross_check_works_without_source_file_via_video_metadata():
    """Les croisements release_name/fichier reel fonctionnent meme sans
    fichier source, si l'appelant fournit deja les metadonnees structurees
    (`data.video_metadata`) -- cas de l'extraction MediaInfo cote navigateur
    (WebAssembly, aucun upload), ou `ctx.source` est toujours None."""
    warnings: list[str] = []
    nfogen.generate(
        category="video",
        data={
            "raw_text": "General\nFormat : Matroska",
            "release_name": VALID_RELEASE_NAME,  # annonce 1080p/x264
            "video_metadata": {
                "video_height": 720,
                "video_format": "AVC",
                "audio_languages": [],
                "subtitle_languages": [],
            },
        },
        warnings=warnings,
    )
    assert any("1080p" in w and "720p" in w for w in warnings)


def test_upscale_warning_flags_abnormally_low_bitrate_for_real_c411_profile():
    """Cas reel signale par un utilisateur : un upload annonce 1080p/x264 mais
    le debit reel est trop bas pour que ce soit un vrai 1080p -- probable
    upscale. Prouve le cablage complet (rules.json -> declarative_profile ->
    rules.upscale_warnings), pas seulement la fonction isolee."""
    warnings: list[str] = []
    nfogen.generate(
        category="video",
        data={
            "raw_text": "General\nFormat : Matroska",
            "release_name": VALID_RELEASE_NAME,  # annonce 1080p/x264
            "video_metadata": {
                "video_height": 1080,
                "video_width": 1920,
                "video_format": "AVC",
                "video_bit_rate": 1_500_000,  # tres bas pour du vrai 1080p x264
                "frame_rate": 24.0,
                "audio_languages": [],
                "subtitle_languages": [],
            },
        },
        warnings=warnings,
    )
    assert any("upscale" in w.lower() for w in warnings)


def test_no_upscale_warning_for_a_comfortable_bitrate():
    warnings: list[str] = []
    nfogen.generate(
        category="video",
        data={
            "raw_text": "General\nFormat : Matroska",
            "release_name": VALID_RELEASE_NAME,
            "video_metadata": {
                "video_height": 1080,
                "video_width": 1920,
                "video_format": "AVC",
                "video_bit_rate": 6_000_000,
                "frame_rate": 24.0,
                "audio_languages": [],
                "subtitle_languages": [],
            },
        },
        warnings=warnings,
    )
    assert not any("upscale" in w.lower() for w in warnings)


@pytest.mark.skipif(not (HAS_FFMPEG and HAS_MEDIAINFO), reason="ffmpeg/libmediainfo requis")
def test_extract_video_metadata_includes_bitrate_width_and_framerate(tmp_path: Path):
    """Champs necessaires a l'heuristique upscale (rules.upscale_warnings) :
    prouve sur un vrai fichier encode par ffmpeg, pas seulement la forme du dict."""
    from nfogen import extract

    mkv = tmp_path / "sample.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=24", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(mkv)], check=True,
    )
    meta = extract.extract_video_metadata(mkv)
    assert meta["video_width"] == 320
    assert meta["video_height"] == 240
    assert meta["video_bit_rate"] and meta["video_bit_rate"] > 0
    assert meta["frame_rate"] == pytest.approx(24.0, abs=0.1)


@pytest.mark.skipif(not (HAS_FFMPEG and HAS_MEDIAINFO), reason="ffmpeg/libmediainfo requis")
def test_video_warns_on_missing_audio_language(tmp_path: Path):
    """Une piste audio sans tag de langue declenche un avertissement (non bloquant)."""
    mkv = tmp_path / "no_lang.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=24", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(mkv)], check=True,
    )
    warnings: list[str] = []
    nfo = nfogen.generate(
        source=mkv, data={"release_name": VALID_RELEASE_NAME}, warnings=warnings
    )
    assert "General" in nfo
    assert any("langue non declaree" in w for w in warnings)


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (HAS_FFMPEG and HAS_MEDIAINFO), reason="ffmpeg/libmediainfo requis")
def test_audio_album(tmp_path: Path):
    album = tmp_path / "album"
    album.mkdir()
    for i in (1, 2):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", f"sine=frequency={300+i*50}:duration={i+1}", "-c:a", "libmp3lame",
             "-b:a", "192k", "-metadata", "artist=Tester", "-metadata", f"title=Piste {i}",
             "-metadata", "album=Demo", "-metadata", f"track={i}", str(album / f"0{i}.mp3")],
            check=True,
        )
    nfo = nfogen.generate(category="audio", source=album, data={"genre": "Test", "year": 2024})
    assert "TRACKLIST" in nfo
    assert "01. Tester - Piste 1" in nfo
    assert "Playing Time" in nfo


# --------------------------------------------------------------------------- #
# Profils a base de templates (sans fichier)
# --------------------------------------------------------------------------- #
def test_game_json():
    nfo = nfogen.generate(
        category="game",
        data={
            "title": "Mon Jeu", "version": "1.0", "platform": "PC", "format": "ISO",
            "languages_audio": "FR", "languages_text": "FR",
            "requirements": {"OS": "Windows 10", "RAM": "8 Go"},
            "install_steps": ["Monter l'ISO", "Installer"],
        },
    )
    assert "CONFIGURATION REQUISE" in nfo
    assert "INSTALLATION" in nfo
    assert "1. Monter l'ISO" in nfo


def test_print3d_json():
    nfo = nfogen.generate(
        category="print3d",
        data={"name": "Test", "file_count": 2, "format": "STL", "total_size_dec": "5 Mo"},
    )
    assert "Nom du modele" in nfo
    assert nfo.rstrip().endswith("Enjoy")


def test_ebook_json():
    nfo = nfogen.generate(
        category="ebook",
        data={"title": "Livre", "author": "Auteur", "format": "EPUB",
              "language": "FR", "pages": 320, "total_size_dec": "4 Mo"},
    )
    assert "Auteur" in nfo and "EPUB" in nfo
