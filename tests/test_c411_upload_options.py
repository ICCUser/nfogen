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
            "language_values": {"VFF": 2, "MULTI.VFF": 4},
            "quality_option_id": 2,
            "quality_values": {"BluRay": 11, "BluRay.HDLight": 413, "WEB": 25},
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
