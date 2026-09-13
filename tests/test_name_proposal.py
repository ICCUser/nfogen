"""Tests de la proposition de release_name (`nfogen/name_proposal.py`) : le
moteur travaille uniquement sur des NOMS de fichiers (jamais leur contenu),
c'est ce qui le rend utilisable instantanement avant tout upload."""
from __future__ import annotations

from nfogen.name_proposal import propose_season_pack_name, propose_video_release_name

TEMPLATE = "{title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}"
CONFIG = {
    "template": TEMPLATE,
    "language_aliases": {
        "FR+JA": "MULTI.VFF", "FR": "VFF",
        "FR+FRQ": "MULTI.VF2", "FRQ+FR": "MULTI.VF2", "FRQ": "VFQ",
        "FRQ+EN": "MULTI.VFQ", "EN+FRQ": "MULTI.VFQ",
    },
    "source_aliases": {
        "WEBDL": "WEB",
        "WEB-DL": "WEB",
        "WEBRip": "WEBRip",
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


# --------------------------------------------------------------------------- #
# VFQ / MULTI.VF2 -- audit de conformite C411, 2026-09-13, point 4. Le hint de
# langue ("FR+FRQ") vient ici du nom de fichier/hint (comme "[FR+JA]" pour
# ONE_PIECE_FILES ci-dessus), pas d'une vraie piste MediaInfo -- voir
# tests/test_upload_prep.py pour la construction du hint a partir des
# vraies pistes audio.
# --------------------------------------------------------------------------- #
def test_quebec_only_language_hint_maps_to_vfq():
    filenames = ["Movie.2020.1080p.WEB.[FRQ].x264-TEAM.mkv"]
    proposal = propose_video_release_name(filenames, CONFIG)
    assert "VFQ" in proposal.fields["language"]
    assert "MULTI" not in proposal.fields["language"]


def test_france_and_quebec_language_hint_maps_to_multi_vf2():
    filenames = ["Movie.2020.1080p.WEB.[FR+FRQ].x264-TEAM.mkv"]
    proposal = propose_video_release_name(filenames, CONFIG)
    assert proposal.fields["language"] == "MULTI.VF2"


def test_quebec_and_english_language_hint_maps_to_multi_vfq():
    # Cas reel confirme par l'utilisateur (2026-09-13) : une seule piste FR
    # (Quebec) + une piste EN -> MULTI.VFQ, distinct de MULTI.VF2 (qui exige
    # VFF+VFQ ensemble).
    filenames = ["Movie.2020.1080p.WEB.[FRQ+EN].x264-TEAM.mkv"]
    proposal = propose_video_release_name(filenames, CONFIG)
    assert proposal.fields["language"] == "MULTI.VFQ"


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


def test_c411_profile_recognizes_av1_video_codec():
    # Cas reel : "Die Hard 2 (1990) [Bluray-1080p][DTS 5.1][AV1]-LAZARUS" --
    # AV1 absent de video_codec_aliases faisait tomber le champ a vide.
    import json
    from pathlib import Path

    rules_path = Path(__file__).resolve().parent.parent / "nfogen" / "profiles" / "c411" / "rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    aliases = rules["video"]["name_proposal"]["video_codec_aliases"]
    assert "AV1" in aliases

    files = ["Die Hard 2 (1990) [Bluray-1080p][DTS 5.1][AV1]-LAZARUS.mkv"]
    config = rules["video"]["name_proposal"]
    proposal = propose_video_release_name(files, config)
    assert proposal.fields["video_codec"] == aliases["AV1"]
    assert not any("codec vidéo" in w.lower() for w in proposal.warnings)


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
    """Retour reel de moderation (2026-09-13, pack Lucifer S03) : le champ
    `Title` embarque dans un fichier .m4v peut porter le nom de la release
    ORIGINALE avant un reencodage (ex. x264-ARK01 avant reencodage Frosties
    en x265) -- un codec perime/mensonger, jamais fiable a 100% contrairement
    au nom de fichier REEL. Le hint garde la priorite pour resolution/equipe
    (texte libre, souvent absent d'un nom de fichier generique), mais plus
    pour le codec video : voir test_hint_never_overrides_a_codec_detected_
    in_the_filename ci-dessous."""
    files = ["Show.S01E01.720p.WEBRip.x265-OLDTEAM.mkv"]
    title_hints = ["Show S01 1080p WebDl x264 - NewTeam"]
    proposal = propose_video_release_name(files, CONFIG, title_hints)
    assert proposal.fields["resolution"] == "1080"
    assert proposal.fields["video_codec"] == "x265"
    assert proposal.fields["source"] == "WEB"
    assert proposal.fields["team"] == "NewTeam"


def test_hint_never_overrides_a_codec_detected_in_the_filename():
    """Cas reel (2026-09-13) : Lucifer S03, fichiers .m4v Frosties reencodes
    en x265 -- le nom de fichier REEL dit '[x265]', mais le tag `Title`
    embarque (retrouve via `mediainfo --Inform="General;%Title%"`) dit encore
    'Lucifer.S03E01.MULTi.1080p.AMZN.WEB-DL.x264-ARK01' (la release ORIGINALE
    avant reencodage, jamais mise a jour). Consequence en cascade avant ce
    fix : release_name genere avec 'H264' au lieu de 'H265', puis rejet de
    moderation ("Codec video annonce... different de celui du fichier")."""
    files = ["Lucifer (2016) - S03E01 - Theyre Back Arent They [WEBDL-1080p][AAC 2.0][x265]-Frosties.m4v"]
    title_hints = ["Lucifer.S03E01.MULTi.1080p.AMZN.WEB-DL.x264-ARK01"]
    proposal = propose_video_release_name(files, CONFIG, title_hints)
    assert proposal.fields["video_codec"] == "x265"


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


_SEASON_PACK_CONFIG = {**CONFIG, "season_pack": {
    "range_format": "S{start:02d}S{end:02d}",
    "integrale_tag": "INTEGRALE",
    "integrale_single_season_format": "S{season:02d}.{integrale_tag}",
}}


def test_propose_season_pack_name_partial_range():
    result = propose_season_pack_name(
        title="Lucifer", season_numbers=[5, 6], is_full_series=False, team="Frosties",
        representative_filename="Lucifer.S05E01.FR.1080p.WEBDL.x264-Frosties.mkv",
        config=_SEASON_PACK_CONFIG,
    )
    assert result.name is not None
    assert "S05S06" in result.name
    assert result.name.endswith("-Frosties")
    assert "VFF" in result.name
    assert "WEB" in result.name


def test_propose_season_pack_name_full_series_uses_integrale():
    result = propose_season_pack_name(
        title="Breaking Bad", season_numbers=[1, 2, 3], is_full_series=True, team="MiND",
        representative_filename="Breaking.Bad.S01E01.FR.720p.BluRay.AC3.x264-MiND.mkv",
        config=_SEASON_PACK_CONFIG,
    )
    assert result.name is not None
    assert "INTEGRALE" in result.name
    assert "S01" not in result.name  # pas de token saison pour une integrale multi-saisons


def test_propose_season_pack_name_single_season_integrale_keeps_season_token():
    result = propose_season_pack_name(
        title="Show", season_numbers=[1], is_full_series=True, team="TEAM",
        representative_filename="Show.S01E01.FR.1080p.WEBDL.x264-TEAM.mkv",
        config=_SEASON_PACK_CONFIG,
    )
    assert result.name is not None
    assert "S01.INTEGRALE" in result.name


def test_propose_season_pack_name_none_when_season_pack_not_configured():
    result = propose_season_pack_name(
        title="Show", season_numbers=[1, 2], is_full_series=False, team="TEAM",
        representative_filename="Show.S01E01.FR.1080p.WEBDL.x264-TEAM.mkv",
        config=CONFIG,  # sans season_pack
    )
    assert result.name is None
    assert "season_pack" in result.warnings[0]


def test_propose_season_pack_name_none_when_template_not_configured():
    result = propose_season_pack_name(
        title="Show", season_numbers=[1, 2], is_full_series=False, team="TEAM",
        representative_filename="Show.S01E01.mkv",
        config={},
    )
    assert result.name is None


# --------------------------------------------------------------------------- #
# web_video_codec_overrides (retour reel de moderation C411, 2026-09-10 --
# pack Lucifer S05) : "Une source WEB ne peut pas avoir ce CodecVideo [x265]
# [...] Remplace [X265] par [H265] dans le titre." Opt-in : sans cette cle
# dans la config du profil, aucun changement de comportement (voir CONFIG
# ci-dessus, sans cette cle, dans les tests plus haut).
# --------------------------------------------------------------------------- #
CONFIG_WITH_WEB_OVERRIDE = {**CONFIG, "web_video_codec_overrides": {"x264": "H264", "x265": "H265"}}


def test_web_source_x265_becomes_h265_when_override_configured():
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.WEBDL.AAC.x265-TEAM.mkv"], CONFIG_WITH_WEB_OVERRIDE,
    )
    assert result.name is not None
    assert ".H265-TEAM" in result.name
    assert "x265" not in result.name.lower()


def test_bluray_source_x265_unaffected_by_web_override():
    """La convention WEB ne s'applique PAS a une source BluRay -- x264/x265
    y restent la convention normale (nom d'encodeur, pas de codec)."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.BluRay.AAC.x265-TEAM.mkv"], CONFIG_WITH_WEB_OVERRIDE,
    )
    assert result.name is not None
    assert ".x265-TEAM" in result.name


def test_web_override_is_opt_in_absent_by_default():
    """Sans `web_video_codec_overrides` dans la config du profil (CONFIG,
    utilise par tous les autres tests de ce fichier) : comportement
    d'origine inchange, x265 reste x265 meme sur une source WEB."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.WEBDL.AAC.x265-TEAM.mkv"], CONFIG,
    )
    assert result.name is not None
    assert ".x265-TEAM" in result.name


def test_real_c411_profile_web_source_uses_h265_not_x265():
    """Bout-en-bout contre le VRAI profil livre (nfogen/profiles/c411/rules.json),
    pas seulement une config de test isolee."""
    from nfogen.profile_store import read_profile

    config = read_profile("c411")["rules"]["video"]["name_proposal"]
    result = propose_video_release_name(
        ["Lucifer.S05E01.MULTI.VFF.1080p.WEB.AAC.2.0.x265-Frosties.m4v"], config,
    )
    assert result.name is not None
    assert ".H265-Frosties" in result.name
    assert "x265" not in result.name.lower()


# --------------------------------------------------------------------------- #
# WEBRip vs WEB-DL/WEB (audit C411 2026-09-13, doc officielle "Films & Videos") :
# "x264 / x265 ... a utiliser pour les encodes (BluRay, WEBrip, DVDrip) et
# WEB-DL encodes" / "H264 / H265 ... a utiliser pour les WEB-DL untouched".
# Bug reel corrige ici : source_aliases collapsait "WEBRip" sur "WEB", donc
# _apply_web_codec_convention (declenchee par source.startswith("WEB"))
# s'appliquait a tort a un WEBRip, convertissant x264/x265 (correct pour un
# reencodage) en H264/H265 (reserve au WEB-DL untouched) -- l'inverse exact
# de la convention officielle.
# --------------------------------------------------------------------------- #
def test_webrip_source_x265_stays_x265_not_converted_to_h265():
    result = propose_video_release_name(
        ["Movie.2020.1080p.WEBRip.AAC.x265-TEAM.mkv"], CONFIG_WITH_WEB_OVERRIDE,
    )
    assert result.name is not None
    assert ".x265-TEAM" in result.name
    assert "h265" not in result.name.lower()


def test_webrip_source_field_stays_webrip_not_web():
    result = propose_video_release_name(
        ["Movie.2020.1080p.WEBRip.AAC.x265-TEAM.mkv"], CONFIG_WITH_WEB_OVERRIDE,
    )
    assert result.fields["source"] == "WEBRip"


def test_webdl_source_x265_still_becomes_h265_non_regression():
    result = propose_video_release_name(
        ["Movie.2020.1080p.WEBDL.AAC.x265-TEAM.mkv"], CONFIG_WITH_WEB_OVERRIDE,
    )
    assert result.name is not None
    assert ".H265-TEAM" in result.name
    assert "x265" not in result.name.lower()


def test_real_c411_profile_webrip_source_stays_x265_not_h265():
    """Bout-en-bout contre le VRAI profil livre (nfogen/profiles/c411/rules.json) :
    un WEBRip reel ne doit jamais voir son codec converti en H265."""
    from nfogen.profile_store import read_profile

    config = read_profile("c411")["rules"]["video"]["name_proposal"]
    result = propose_video_release_name(
        ["Movie.2020.1080p.WEBRip.AAC.2.0.x265-TEAM.mkv"], config,
    )
    assert result.name is not None
    assert ".x265-TEAM" in result.name
    assert "h265" not in result.name.lower()
    assert result.fields["source"] == "WEBRip"


# --------------------------------------------------------------------------- #
# pure_source_codec_overrides (audit de conformite C411, 2026-09-13, doc
# officielle "Films & Videos", section "2. Encodage") : "Le TAG AVC (et non
# H264) est obligatoire sur les versions pures (REMUX/ISO/BDMV)" / "Le TAG
# HEVC (et non H265) est obligatoire sur les versions pures (REMUX/ISO/BDMV)"
# / "x264 / x265 : TAG INTERDIT sur version Pure (REMUX/ISO/BDMV)". Mecanisme
# symetrique a web_video_codec_overrides, pour les sources pures detectables
# (BluRay.REMUX, BluRay.BDMV, BluRay.ISO) -- le prefixe UHD. volontairement
# hors perimetre de ce point, voir commit associe. Opt-in : sans ces cles
# dans la config du profil, aucun changement de comportement (voir CONFIG
# ci-dessus, sans ces cles, dans les tests plus haut).
# --------------------------------------------------------------------------- #
CONFIG_WITH_PURE_SOURCE_OVERRIDE = {
    **CONFIG,
    "source_aliases": {
        **CONFIG["source_aliases"],
        "BluRay.BDMV": "BluRay.BDMV",
        "BluRay.ISO": "BluRay.ISO",
    },
    "pure_sources": ["BluRay.REMUX", "BluRay.BDMV", "BluRay.ISO"],
    "pure_source_codec_overrides": {
        "x264": "AVC", "h264": "AVC", "avc": "AVC",
        "x265": "HEVC", "h265": "HEVC", "hevc": "HEVC",
    },
}


def test_remux_source_x265_becomes_hevc_when_override_configured():
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.BDRemux.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.name is not None
    assert ".HEVC-TEAM" in result.name
    assert "x265" not in result.name.lower()
    assert "h265" not in result.name.lower()


def test_remux_source_x264_becomes_avc_when_override_configured():
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.BDRemux.AAC.x264-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.name is not None
    assert ".AVC-TEAM" in result.name
    assert "x264" not in result.name.lower()
    assert "h264" not in result.name.lower()


def test_bdmv_source_x265_becomes_hevc_when_override_configured():
    """Alias 'BDMV' (source_aliases) detecte dans le nom de fichier ->
    BluRay.BDMV, egalement couvert par la convention pure."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.2160p.BluRay.BDMV.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.name is not None
    assert ".HEVC-TEAM" in result.name
    assert "x265" not in result.name.lower()


def test_iso_source_x265_becomes_hevc_when_override_configured():
    """Alias 'BluRay.ISO' (source_aliases, cle composee -- 'ISO' seul est
    delibrement absent, trop generique pour une detection fiable, voir
    docstring de _apply_pure_source_codec_convention), egalement couvert
    par la convention pure."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.2160p.BluRay.ISO.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.name is not None
    assert ".HEVC-TEAM" in result.name
    assert "x265" not in result.name.lower()


def test_plain_bluray_source_x265_unaffected_by_pure_source_override():
    """La convention pure ne s'applique PAS a un encode BluRay classique
    (ni REMUX ni BDMV) -- x264/x265 y restent la convention normale."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.BluRay.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.name is not None
    assert ".x265-TEAM" in result.name


def test_web_source_x265_unaffected_by_pure_source_override():
    """Les deux conventions (WEB et pure) ne s'interferent pas : une source
    WEB continue de suivre web_video_codec_overrides, jamais la convention
    pure."""
    config = {
        **CONFIG_WITH_PURE_SOURCE_OVERRIDE,
        "web_video_codec_overrides": {"x264": "H264", "x265": "H265"},
    }
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.WEBDL.AAC.x265-TEAM.mkv"], config,
    )
    assert result.name is not None
    assert ".H265-TEAM" in result.name
    assert "hevc" not in result.name.lower()


def test_pure_source_override_is_opt_in_absent_by_default():
    """Sans `pure_source_codec_overrides`/`pure_sources` dans la config du
    profil (CONFIG, utilise par tous les autres tests de ce fichier) :
    comportement d'origine inchange, x265 reste x265 meme sur un REMUX."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.BDRemux.AAC.x265-TEAM.mkv"], CONFIG,
    )
    assert result.name is not None
    assert ".x265-TEAM" in result.name


def test_real_c411_profile_remux_source_uses_hevc_not_x265():
    """Bout-en-bout contre le VRAI profil livre (nfogen/profiles/c411/rules.json),
    pas seulement une config de test isolee."""
    from nfogen.profile_store import read_profile

    config = read_profile("c411")["rules"]["video"]["name_proposal"]
    result = propose_video_release_name(
        ["Lucifer.S05E01.MULTI.VFF.1080p.BDRemux.AAC.2.0.x265-Frosties.m4v"], config,
    )
    assert result.name is not None
    assert ".HEVC-Frosties" in result.name
    assert "x265" not in result.name.lower()


def test_real_c411_profile_bdmv_source_uses_avc_not_x264():
    from nfogen.profile_store import read_profile

    config = read_profile("c411")["rules"]["video"]["name_proposal"]
    result = propose_video_release_name(
        ["Lucifer.S05E01.MULTI.VFF.2160p.BluRay.BDMV.AAC.2.0.x264-Frosties.m4v"], config,
    )
    assert result.name is not None
    assert ".AVC-Frosties" in result.name
    assert "x264" not in result.name.lower()


def test_real_c411_profile_iso_source_uses_hevc_not_x265():
    from nfogen.profile_store import read_profile

    config = read_profile("c411")["rules"]["video"]["name_proposal"]
    result = propose_video_release_name(
        ["Lucifer.S05E01.MULTI.VFF.2160p.BluRay.ISO.AAC.2.0.x265-Frosties.m4v"], config,
    )
    assert result.name is not None
    assert ".HEVC-Frosties" in result.name
    assert "x265" not in result.name.lower()
    # Prefixe "UHD." attendu ici (2160p, source pure) -- voir point 3/4,
    # _apply_uhd_bluray_prefix : mis a jour depuis "BluRay.ISO" simple.
    assert result.fields["source"] == "UHD.BluRay.ISO"


def test_propose_season_pack_name_remux_source_uses_hevc():
    result = propose_season_pack_name(
        title="Lucifer", season_numbers=[5, 6], is_full_series=False, team="Frosties",
        representative_filename="Lucifer.S05E01.FR.1080p.BDRemux.x265-Frosties.mkv",
        config={**_SEASON_PACK_CONFIG, "pure_sources": ["BluRay.REMUX", "BluRay.BDMV"],
                "pure_source_codec_overrides": {"x265": "HEVC", "x264": "AVC"}},
    )
    assert result.name is not None
    assert ".HEVC-Frosties" in result.name
    assert "x265" not in result.name.lower()


# --------------------------------------------------------------------------- #
# Prefixe "UHD." pour les sources pures (REMUX/BDMV/ISO) en 2160p (audit C411
# 2026-09-13, doc officielle "Films & Videos") : REMUX/BDMV/ISO 2160p
# TOUJOURS avec le prefixe UHD. devant BluRay (jamais pour un simple encode
# 2160p, qui reste BluRay sans prefixe -- exemple officiel Gladiator 2000).
# Reutilise la MEME liste `pure_sources` que _apply_pure_source_codec_convention
# (REMUX/BDMV/ISO restent purs peu importe la resolution) -- pas de nouvelle
# cle de config, aucun opt-in separe.
# --------------------------------------------------------------------------- #
def test_remux_1080p_has_no_uhd_prefix():
    result = propose_video_release_name(
        ["Show.S01E01.FR.1080p.BDRemux.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.fields["source"] == "BluRay.REMUX"


def test_remux_2160p_gets_uhd_prefix():
    result = propose_video_release_name(
        ["Show.S01E01.FR.2160p.BDRemux.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.fields["source"] == "UHD.BluRay.REMUX"
    assert result.name is not None
    assert "UHD.BluRay.REMUX" in result.name


def test_bdmv_2160p_gets_uhd_prefix():
    result = propose_video_release_name(
        ["Show.S01E01.FR.2160p.BluRay.BDMV.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.fields["source"] == "UHD.BluRay.BDMV"


def test_iso_2160p_gets_uhd_prefix():
    result = propose_video_release_name(
        ["Show.S01E01.FR.2160p.BluRay.ISO.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.fields["source"] == "UHD.BluRay.ISO"


def test_plain_bluray_2160p_has_no_uhd_prefix():
    """Un encode BluRay normal en 2160p n'est PAS une version pure -- jamais
    de prefixe UHD (exemple officiel Gladiator 2000, 2160p, BluRay simple,
    x265 -- pas de UHD.)."""
    result = propose_video_release_name(
        ["Show.S01E01.FR.2160p.BluRay.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.fields["source"] == "BluRay"


def test_uhd_prefix_no_crash_when_resolution_missing():
    result = propose_video_release_name(
        ["Show.S01E01.FR.BDRemux.AAC.x265-TEAM.mkv"], CONFIG_WITH_PURE_SOURCE_OVERRIDE,
    )
    assert result.fields["source"] == "BluRay.REMUX"


def test_real_c411_profile_remux_2160p_gets_uhd_prefix():
    """Bout-en-bout contre le VRAI profil livre (nfogen/profiles/c411/rules.json)."""
    from nfogen.profile_store import read_profile

    config = read_profile("c411")["rules"]["video"]["name_proposal"]
    result = propose_video_release_name(
        ["Lucifer.S05E01.MULTI.VFF.2160p.BDRemux.AAC.2.0.x265-Frosties.m4v"], config,
    )
    assert result.name is not None
    assert result.fields["source"] == "UHD.BluRay.REMUX"
    assert "UHD.BluRay.REMUX" in result.name
    assert ".HEVC-Frosties" in result.name


def test_propose_season_pack_name_remux_2160p_gets_uhd_prefix():
    result = propose_season_pack_name(
        title="Lucifer", season_numbers=[5, 6], is_full_series=False, team="Frosties",
        representative_filename="Lucifer.S05E01.FR.2160p.BDRemux.x265-Frosties.mkv",
        config={**_SEASON_PACK_CONFIG, "pure_sources": ["BluRay.REMUX", "BluRay.BDMV", "BluRay.ISO"],
                "pure_source_codec_overrides": {"x265": "HEVC", "x264": "AVC"}},
    )
    assert result.name is not None
    assert result.fields["source"] == "UHD.BluRay.REMUX"
    assert ".HEVC-Frosties" in result.name
