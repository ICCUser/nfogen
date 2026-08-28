"""Tests de la proposition de release_name (`nfogen/name_proposal.py`) : le
moteur travaille uniquement sur des NOMS de fichiers (jamais leur contenu),
c'est ce qui le rend utilisable instantanement avant tout upload."""
from __future__ import annotations

from nfogen.name_proposal import propose_video_release_name

TEMPLATE = "{title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}"
CONFIG = {
    "template": TEMPLATE,
    "language_aliases": {"FR+JA": "MULTI.VFF", "FR": "VFF"},
    "source_aliases": {
        "WEBDL": "WEB",
        "WEB-DL": "WEB",
        "WEBRip": "WEB",
        "BDRip": "BDRip",
        "BDRemux": "BluRay.REMUX",
        "BluRay": "BluRay",
        "HDTV": "HDTV",
        "DVDRip": "DVDRip",
        "DSNP": "WEB.DSNP",
        "NF": "WEB.NF",
        "AMZN": "WEB.AMZN",
    },
    "video_codec_aliases": {
        "x264": "x264",
        "x265": "x265",
        "H.264": "h.264",
        "H264": "h264",
        "H.265": "h.265",
        "H265": "h265",
        "HEVC": "hevc",
        "AVC": "avc",
        "MPEG-2": "mpeg-2",
        "MPEG2": "mpeg2",
    },
    "audio_codec_aliases": {
        "AC3": "AC3",
        "EAC3": "EAC3",
        "AAC": "AAC",
        "DTS-HD": "DTS-HD",
        "DTS": "DTS",
        "FLAC": "FLAC",
        "MP3": "MP3",
        "OPUS": "OPUS",
        "TRUEHD": "TRUEHD",
    },
}

ONE_PIECE_FILES = [
    "One Piece (1999) - S01E01 - 001 - Im Luffy! [WEBDL-1080p][AC3 2.0][FR+JA][x264 8bit].mkv",
    "One Piece (1999) - S01E02 - 002 - Enter Zoro! [WEBDL-1080p][AC3 2.0][FR+JA][x264 8bit].mkv",
]


def test_season_pack_real_world_case():
    proposal = propose_video_release_name(ONE_PIECE_FILES, CONFIG)
    assert proposal.name == "One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG"
    assert proposal.fields["identifier"] == "S01"
    assert any("équipe" in w for w in proposal.warnings)


def test_single_episode_keeps_episode_number():
    proposal = propose_video_release_name([ONE_PIECE_FILES[0]], CONFIG)
    assert proposal.fields["identifier"] == "S01E01"


def test_no_filenames_is_a_soft_warning_not_a_crash():
    proposal = propose_video_release_name([], CONFIG)
    assert proposal.name is None
    assert proposal.warnings


def test_missing_template_config_is_a_soft_warning():
    proposal = propose_video_release_name(ONE_PIECE_FILES, {})
    assert proposal.name is None
    assert "template" in proposal.warnings[0]


def test_mismatched_seasons_is_an_error():
    files = [
        "Show.S01E01.mkv",
        "Show.S02E01.mkv",
    ]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.name is None
    assert "saisons" in proposal.warnings[0]


def test_consistent_team_tag_is_reused():
    files = [
        "Mr.Robot.S01E01.1080p.WEB.H264-NTb.mkv",
        "Mr.Robot.S01E02.1080p.WEB.H264-NTb.mkv",
    ]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.fields["team"] == "NTb"
    assert not any("équipe" in w for w in proposal.warnings)


def test_mismatched_team_tags_is_an_error():
    files = [
        "Mr.Robot.S01E01.1080p.WEB.H264-NTb.mkv",
        "Mr.Robot.S01E02.1080p.WEB.H264-FLEET.mkv",
    ]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.name is None
    assert "équipe" in proposal.warnings[0]


def test_no_team_tag_falls_back_to_notag_placeholder():
    proposal = propose_video_release_name(ONE_PIECE_FILES, CONFIG)
    assert proposal.fields["team"] == "NOTAG"


def test_unconfigured_language_bracket_is_a_placeholder_with_warning():
    files = ["Movie (2020) [WEBDL-1080p][DE+EN][x264].mkv"]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.fields["language"] == "LANGINCONNU"
    assert any("DE+EN" in w for w in proposal.warnings)


def test_year_used_as_identifier_when_no_season_tag():
    files = ["Some.Movie.Title.2020.1080p.WEB.x264-TEAM.mkv"]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.fields["identifier"] == "2020"


def test_no_year_or_season_is_a_warning_not_a_blocker():
    files = ["random_clip.mkv"]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.fields["identifier"] == "IDENTIFIANT"
    assert any("identifiant" in w for w in proposal.warnings)


def test_bare_scene_style_filename_without_brackets_is_detected():
    """Limite historique levee : la resolution/le codec/la source ne sont
    plus restreints au contenu de crochets `[...]`, ils sont recherches dans
    tout le nom de fichier (utile pour les releases "scene" sans crochets)."""
    files = ["Show.Name.S01E01.1080p.WEB-DL.AC3.x264-TEAM.mkv"]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.fields["resolution"] == "1080"
    assert proposal.fields["video_codec"] == "x264"
    assert proposal.fields["source"] == "WEB"
    assert proposal.fields["team"] == "TEAM"


def test_title_hint_fills_gaps_left_by_generic_filename():
    """Cas reel signale par un utilisateur : le nom de fichier ne dit rien
    sur la resolution/le codec/l'equipe, mais le tag `Title` embarque dans le
    conteneur (ex. extrait via MediaInfo) si."""
    files = ["One Piece - S01E01 - 001 - Im Luffy!.mkv"]
    title_hints = ["One Piece S01 ''Arc Morgan'' WebDl 1080p x264 - Chris44"]
    proposal = propose_video_release_name(files, CONFIG, title_hints)
    assert proposal.fields["resolution"] == "1080"
    assert proposal.fields["video_codec"] == "x264"
    assert proposal.fields["source"] == "WEB"
    assert proposal.fields["team"] == "Chris44"
    assert proposal.fields["identifier"] == "S01E01"


def test_title_hint_takes_priority_over_filename_when_both_present():
    files = ["Show.S01E01.720p.WEBRip.x265-OLDTEAM.mkv"]
    title_hints = ["Show S01 1080p WebDl x264 - NewTeam"]
    proposal = propose_video_release_name(files, CONFIG, title_hints)
    assert proposal.fields["resolution"] == "1080"
    assert proposal.fields["video_codec"] == "x264"
    assert proposal.fields["source"] == "WEB"
    assert proposal.fields["team"] == "NewTeam"


def test_title_hints_wrong_length_is_ignored_silently():
    proposal = propose_video_release_name(ONE_PIECE_FILES, CONFIG, title_hints=["only one"])
    assert proposal.name == "One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG"


# --------------------------------------------------------------------------- #
# Agnosticisme du tracker (AUTOMATION.md, sous-projet 3) : la source et les
# codecs ne sont plus cables en dur -- un profil different de C411 peut
# choisir une autre normalisation sans toucher au code.
# --------------------------------------------------------------------------- #
def test_source_normalization_is_fully_configurable_per_profile():
    files = ["Movie.2020.WEBDL.1080p.mkv"]
    custom_config = {
        "template": "{title}.{identifier}.{resolution}p.{source}",
        "source_aliases": {"WEBDL": "WEB-CUSTOM"},
    }
    proposal = propose_video_release_name(files, custom_config)
    assert proposal.fields["source"] == "WEB-CUSTOM"


def test_video_codec_normalization_is_fully_configurable_per_profile():
    files = ["Movie.2020.1080p.x264.mkv"]
    custom_config = {
        "template": "{title}.{identifier}.{resolution}p.{video_codec}",
        "video_codec_aliases": {"x264": "H264-CUSTOM"},
    }
    proposal = propose_video_release_name(files, custom_config)
    assert proposal.fields["video_codec"] == "H264-CUSTOM"


def test_audio_codec_normalization_is_fully_configurable_per_profile():
    files = ["Movie.2020.1080p.AC3.mkv"]
    custom_config = {
        "template": "{title}.{identifier}.{resolution}p.{audio}",
        "audio_codec_aliases": {"AC3": "DOLBY-CUSTOM"},
    }
    proposal = propose_video_release_name(files, custom_config)
    assert proposal.fields["audio"] == "DOLBY-CUSTOM"
