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


def test_undetected_video_codec_leaves_no_dangling_dot_before_team_tag():
    # AV1 n'est pas dans video_codec_aliases : le codec n'est pas detecte,
    # laissant le champ "video_codec" vide juste avant "-{team}" dans le
    # gabarit -- ne doit jamais laisser de point trainant devant le tiret
    # (cas reel : "Die.Hard.2...DTS.5.1.-LAZARUS" au lieu de
    # "...DTS.5.1-LAZARUS").
    files = ["Die Hard 2 (1990) [Bluray-1080p][DTS 5.1][AV1]-LAZARUS.mkv"]
    proposal = propose_video_release_name(files, CONFIG)
    assert proposal.name is not None
    assert ".-" not in proposal.name
    assert proposal.name.endswith("-LAZARUS")
    assert any("codec vidéo" in w.lower() for w in proposal.warnings)


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


# --------------------------------------------------------------------------- #
# Fonctions publiques reutilisees par l'orchestration (AUTOMATION.md,
# sous-projet 4) : group_by_team() a besoin de detecter le tag d'equipe
# et de retirer l'extension d'un nom de fichier, independamment d'un
# calcul complet de proposition.
# --------------------------------------------------------------------------- #
def test_extract_team_tag_is_public():
    from nfogen.name_proposal import extract_team_tag

    assert extract_team_tag("Mr.Robot.S01E01.1080p.WEB.H264-NTb") == "NTb"
    assert extract_team_tag("aucune-equipe-ici.txt") is None or extract_team_tag("sans_suffixe") is None


def test_strip_ext_is_public():
    from nfogen.name_proposal import strip_ext

    assert strip_ext("Movie.2020.1080p.mkv") == "Movie.2020.1080p"


# --------------------------------------------------------------------------- #
# title_override (AUTOMATION.md, sous-projet 5, Livraison 1) : le titre
# depuis le nom de fichier ne respecte pas toujours la convention C411 (ex.
# titre francais officiel different du titre de fichier Sonarr/Radarr,
# "A Guy And A Girl" au lieu de "Un Gars, Une Fille") -- override manuel en
# attendant TMDB (Livraison 2).
# --------------------------------------------------------------------------- #
def test_title_override_replaces_the_filename_derived_title():
    files = ["A.Guy.And.A.Girl.S02E01.1080p.WEB.AAC.2.0.h264-Valentin.mkv"]
    proposal = propose_video_release_name(files, CONFIG, title_override="Un Gars Une Fille")
    assert proposal.fields["title"] == "Un.Gars.Une.Fille"
    assert proposal.name.startswith("Un.Gars.Une.Fille.")


def test_title_override_strips_punctuation_never_converts_to_dots():
    """Confirme aupres du support C411 (2026-08-28) : la ponctuation
    naturelle (virgule, apostrophe...) doit etre retiree entierement, pas
    convertie en point -- "Un Gars, Une Fille" -> "Un.Gars.Une.Fille", pas
    "Un.Gars,.Une.Fille"."""
    files = ["A.Guy.And.A.Girl.S02E01.1080p.WEB.AAC.2.0.h264-Valentin.mkv"]
    proposal = propose_video_release_name(files, CONFIG, title_override="Un Gars, Une Fille")
    assert proposal.fields["title"] == "Un.Gars.Une.Fille"


def test_title_override_strips_apostrophes():
    """Retiree entierement, jamais convertie en point : "L'Associe" ->
    "LAssocie" (pas de separateur insere), coherent avec la confirmation
    du support C411. Chaque mot capitalise ("du" -> "Du")."""
    files = ["Movie.2020.1080p.WEB.x264-TEAM.mkv"]
    proposal = propose_video_release_name(files, CONFIG, title_override="L'Associe du Diable")
    assert proposal.fields["title"] == "LAssocie.Du.Diable"


def test_empty_title_override_falls_back_to_filename_derived_title():
    """Une chaine vide/blanche ne doit jamais ecraser le titre deduit --
    meme comportement que si le parametre n'etait pas fourni du tout."""
    proposal = propose_video_release_name(ONE_PIECE_FILES, CONFIG, title_override="   ")
    assert proposal.name == "One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG"


def test_title_override_applies_uniformly_to_a_whole_pack():
    proposal = propose_video_release_name(ONE_PIECE_FILES, CONFIG, title_override="Le Grand Voyage")
    assert proposal.name == "Le.Grand.Voyage.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG"


def test_title_override_transliterates_accents_instead_of_dropping_them():
    """Incident reel signale par l'utilisateur (2026-08-28) : les caracteres
    accentues etaient SUPPRIMES (encode ascii/ignore) au lieu d'etre
    translitteres -- "Celibataires... ou Presque" devenait "Clibataires.ou.Presque"
    (le "e" disparaissait completement)."""
    files = ["Movie.2020.1080p.WEB.x264-TEAM.mkv"]
    proposal = propose_video_release_name(files, CONFIG, title_override="Célibataires... ou Presque")
    assert proposal.fields["title"] == "Celibataires.Ou.Presque"


def test_title_override_capitalizes_each_word():
    """Convention scene : chaque mot du titre est capitalise, pas seulement
    le premier caractere -- "Il faut sauver le soldat Ryan" ->
    "Il.Faut.Sauver.Le.Soldat.Ryan" (incident reel, 2026-08-28)."""
    files = ["Movie.2020.1080p.WEB.x264-TEAM.mkv"]
    proposal = propose_video_release_name(files, CONFIG, title_override="Il faut sauver le soldat Ryan")
    assert proposal.fields["title"] == "Il.Faut.Sauver.Le.Soldat.Ryan"


def test_title_override_capitalization_preserves_internal_casing():
    """Ne doit jamais abaisser une casse deja correcte (acronymes) -- seule
    la premiere lettre de chaque mot est forcee en majuscule, jamais le
    reste force en minuscule (contrairement a str.title(), qui abaisserait
    "FBI" en "Fbi")."""
    files = ["Movie.2020.1080p.WEB.x264-TEAM.mkv"]
    proposal = propose_video_release_name(files, CONFIG, title_override="FBI Duo Tres Special")
    assert proposal.fields["title"] == "FBI.Duo.Tres.Special"
