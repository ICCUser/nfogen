"""Tests de nfogen.c411_upload_options (AUTOMATION.md, sous-projet 5) :
calcule categorie/sous-categorie/options a partir du release_name DEJA
CONFIRME (reutilise rules.captures, deja construit pour la validation) et
de la config declarative du profil -- pur, sans I/O, sans reseau."""
from __future__ import annotations

import pytest

from nfogen import c411_upload_options as options_engine
from nfogen import profile_store as ps
from nfogen.registry import unregister_profile


@pytest.fixture(autouse=True)
def _profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    yield tmp_path
    try:
        names = ps.list_profiles()
    except ps.ProfileStoreError:
        names = []
    for name in names:
        unregister_profile(name)


UPLOAD_RULES = {
    "tracker": {
        "upload": {
            "category_id": 1,
            "subcategory_id": {
                "movie": 6, "movie:anime": 1, "movie:documentaire": 4,
                "series": 7, "series:anime": 2,
            },
            "language_option_id": 1,
            "language_values": {"VFF": 2, "MULTI.VFF": 4, "VFQ": 6, "MULTI.VF2": 422},
            "quality_option_id": 2,
            "quality_values": {
                "BluRay": 11, "BluRay.4K": 10, "BluRay.HDLight": 413,
                "BluRay.REMUX": 12, "WEB": 25, "WEB.4K": 26,
            },
            "season_option_id": 7,
            "season_values": {"INTEGRALE": 118, "S01": 121, "S02": 122},
            "episode_option_id": 6,
            "full_season_episode_value": 96,
        }
    }
}


def test_build_category_ids_for_plain_movie():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    assert options_engine.build_category_ids("up", "movie", None) == (1, 6)


def test_build_category_ids_for_anime_series():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    assert options_engine.build_category_ids("up", "series", "anime") == (1, 2)


def test_build_category_ids_falls_back_to_media_type_when_genre_not_mapped():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    # "series:documentaire" n'est pas dans le mapping de test -- repli sur "series".
    assert options_engine.build_category_ids("up", "series", "documentaire") == (1, 7)


def test_build_category_ids_none_when_profile_has_no_upload_config():
    ps.write_profile("bare", rules={}, templates={})
    assert options_engine.build_category_ids("bare", "movie", None) == (None, None)


def test_build_options_for_bluray_hdlight_movie():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "MULTI.VFF"}
    release_name = "Joker.2015.MULTI.VFF.1080p.BluRay.HDLight.AC3.5.1.x264-NOTAG"
    result = options_engine.build_options("up", captures, release_name)
    assert result == {"1": [4], "2": 413}


def test_build_options_plain_bluray_without_hdlight_marker():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFF"}
    release_name = "Movie.2020.VFF.1080p.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result == {"1": [2], "2": 11}


def test_build_options_includes_season_and_full_season_episode_for_series():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "WEB", "language": "MULTI.VFF"}
    release_name = "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name, season_number=1)
    assert result == {"1": [4], "2": 25, "7": 121, "6": 96}


def test_build_options_omits_unmapped_fields_rather_than_guessing():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "HDTV", "language": "VOSTFR"}  # ni l'un ni l'autre dans le mapping de test
    release_name = "Movie.2020.VOSTFR.1080p.HDTV.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result == {}


def test_build_options_empty_dict_when_profile_has_no_upload_config():
    ps.write_profile("bare", rules={}, templates={})
    result = options_engine.build_options("bare", {"source": "BluRay"}, "Movie.2020.BluRay-TEAM")
    assert result == {}


# --- VFQ / MULTI.VF2 -- audit de conformite C411, 2026-09-13, point 4 ------ #
def test_build_options_quebec_only_language_uses_vfq_id():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFQ"}
    release_name = "Movie.2020.VFQ.1080p.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["1"] == [6]


def test_build_options_france_and_quebec_language_uses_multi_vf2_id():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "MULTI.VF2"}
    release_name = "Movie.2020.MULTI.VF2.1080p.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["1"] == [422]


# --- Bug du 2026-09-13 : la qualite ne doit pas ignorer la resolution ------
# Audit croisé code + pages d'aide C411 (table C411_reference, quality_option
# id 2) : 10=BluRay 4K, 11=BluRay Full (1080p), 12=BluRay Remux (toutes
# resolutions, pas de variante 4K séparée), 25=WEB-DL 1080, 26=WEB-DL 4K.
# `quality_key` ne dependait que de `source` -- un WEB-DL 2160p envoyait
# l'id "WEB-DL 1080" au lieu de "WEB-DL 4K", et un BluRay 2160p pur n'avait
# meme pas d'id configure.

def test_build_options_web_2160p_uses_4k_quality_id():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "WEB", "language": "VFF", "resolution": "2160"}
    release_name = "Movie.2020.VFF.2160p.WEB.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 26


def test_build_options_web_1080p_still_uses_plain_web_quality_id():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "WEB", "language": "VFF", "resolution": "1080"}
    release_name = "Movie.2020.VFF.1080p.WEB.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 25


def test_build_options_bluray_2160p_pure_uses_4k_quality_id():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFF", "resolution": "2160"}
    release_name = "Movie.2020.VFF.2160p.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 10


def test_build_options_bluray_1080p_pure_still_uses_plain_bluray_quality_id():
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFF", "resolution": "1080"}
    release_name = "Movie.2020.VFF.1080p.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 11


def test_build_options_bluray_remux_2160p_has_no_4k_variant():
    # Piege : il n'existe PAS de "BluRay.REMUX.4K" dans la doc officielle --
    # meme a 2160p, un REMUX doit rester sur la cle REMUX simple.
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay.REMUX", "language": "VFF", "resolution": "2160"}
    release_name = "Movie.2020.VFF.2160p.BluRay.REMUX.DTS.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 12


def test_build_options_bluray_hdlight_stays_hdlight_even_if_resolution_says_2160():
    # HDLight est structurellement une variante basse qualite -- jamais 4K en
    # pratique, mais le marqueur HDLight doit rester prioritaire sur toute
    # logique de resolution meme si `resolution` est incoherente/absente.
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFF", "resolution": "2160"}
    release_name = "Movie.2020.VFF.2160p.BluRay.HDLight.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 413


def test_build_options_quality_without_resolution_falls_back_to_plain_key():
    # `resolution` absent de capture_values -- comportement inchange, pas de
    # crash, repli sur la cle simple.
    ps.write_profile("up", rules=UPLOAD_RULES, templates={})
    captures = {"source": "BluRay", "language": "VFF"}
    release_name = "Movie.2020.VFF.BluRay.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 11


def test_build_options_2160p_falls_back_to_plain_key_when_4k_variant_not_configured():
    # Profil de test qui ne declare pas de variante ".4K" pour cette source --
    # repli propre sur la cle simple, jamais de crash ni d'omission a tort.
    rules_without_4k = {
        "tracker": {
            "upload": {
                "quality_option_id": 2,
                "quality_values": {"HDTV": 30},
            }
        }
    }
    ps.write_profile("up", rules=rules_without_4k, templates={})
    captures = {"source": "HDTV", "language": "VFF", "resolution": "2160"}
    release_name = "Movie.2020.VFF.2160p.HDTV.AC3.x264-TEAM"
    result = options_engine.build_options("up", captures, release_name)
    assert result["2"] == 30
