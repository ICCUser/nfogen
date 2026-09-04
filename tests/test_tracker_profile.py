"""Tests de nfogen.tracker_profile : lecture de la section "tracker" d'un
profil (rules.json), separee des identifiants (gapscan_config_store.py) --
voir AUTOMATION.md, sous-projet 4b."""
from __future__ import annotations

import pytest

from nfogen import profile_store as ps
from nfogen import tracker_profile
from nfogen.registry import unregister_profile

FULL_TRACKER_RULES = {
    "tracker": {
        "display_name": "Test Tracker",
        "torznab_categories": {"anime": ["2060", "5070"], "documentaire": ["2070"]},
        "audio_language_codes": {"fre": "FR", "eng": "EN", "jpn": "JA"},
        "min_request_interval_seconds": 4.5,
        "torrent_piece_sizes": [
            {"max_bytes": 1073741824, "piece_size": 1048576},
            {"piece_size": 16777216},
        ],
    }
}


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


def test_reads_every_declared_field():
    ps.write_profile("full", rules=FULL_TRACKER_RULES, templates={})
    assert tracker_profile.display_name("full") == "Test Tracker"
    assert tracker_profile.torznab_categories("full") == {
        "anime": ["2060", "5070"], "documentaire": ["2070"]
    }
    assert tracker_profile.audio_language_codes("full") == {"fre": "FR", "eng": "EN", "jpn": "JA"}
    assert tracker_profile.min_request_interval_seconds("full") == 4.5
    assert tracker_profile.torrent_piece_sizes("full") == [
        {"max_bytes": 1073741824, "piece_size": 1048576},
        {"piece_size": 16777216},
    ]


def test_display_name_falls_back_to_the_profile_name_when_undeclared():
    ps.write_profile("bare", rules={}, templates={})
    assert tracker_profile.display_name("bare") == "bare"


def test_torznab_categories_empty_dict_when_undeclared():
    ps.write_profile("bare2", rules={}, templates={})
    assert tracker_profile.torznab_categories("bare2") == {}


def test_audio_language_codes_empty_dict_when_undeclared():
    ps.write_profile("bare3", rules={}, templates={})
    assert tracker_profile.audio_language_codes("bare3") == {}


def test_min_request_interval_seconds_zero_when_undeclared():
    ps.write_profile("bare4", rules={}, templates={})
    assert tracker_profile.min_request_interval_seconds("bare4") == 0.0


def test_torrent_piece_sizes_empty_list_when_undeclared():
    ps.write_profile("bare5", rules={}, templates={})
    assert tracker_profile.torrent_piece_sizes("bare5") == []


def test_degrades_gracefully_for_a_profile_that_does_not_exist_at_all():
    # Pas juste "sans section tracker" (cas ci-dessus) -- un nom de profil
    # qui n'existe carrement pas (ni utilisateur, ni livre) ne doit jamais
    # faire planter (ProfileStoreError non geree) : meme repli neutre.
    assert tracker_profile.torznab_categories("does-not-exist") == {}
    assert tracker_profile.audio_language_codes("does-not-exist") == {}
    assert tracker_profile.min_request_interval_seconds("does-not-exist") == 0.0
    assert tracker_profile.torrent_piece_sizes("does-not-exist") == []
    assert tracker_profile.display_name("does-not-exist") == "does-not-exist"


# --------------------------------------------------------------------------- #
# Profil c411 livre avec le paquet : verifie les VRAIES valeurs, pas un profil
# de test synthetique. Pas de NFOGEN_PROFILES_DIR necessaire (profile_store
# retombe sur le profil livre, voir sa docstring).
# --------------------------------------------------------------------------- #
def test_c411_display_name():
    assert tracker_profile.display_name("c411") == "C411"


def test_c411_torznab_categories_match_gapscan_md():
    # Verifiees en direct le 2026-08-28 via GET https://c411.org/api?t=caps
    # (voir GAPSCAN.md) -- memes valeurs que l'ancien gapscan._ANIME_CATEGORIES
    # / _DOCUMENTARY_CATEGORIES, deplacees ici.
    assert tracker_profile.torznab_categories("c411") == {
        "anime": ["2060", "5070"],
        "documentaire": ["2070", "5080"],
    }


def test_c411_audio_language_codes_match_upload_prep_history():
    assert tracker_profile.audio_language_codes("c411") == {
        "fr": "FR", "fre": "FR", "fra": "FR", "french": "FR",
        "en": "EN", "eng": "EN", "english": "EN",
        "ja": "JA", "jpn": "JA", "japanese": "JA",
    }


def test_c411_min_request_interval_seconds():
    # Limite confirmee par les admins C411 (2026-08-27) : 15 requetes/min
    # -> 4.5s par defaut (marge de securite), voir GAPSCAN.md.
    assert tracker_profile.min_request_interval_seconds("c411") == 4.5


def test_c411_torrent_piece_sizes():
    assert tracker_profile.torrent_piece_sizes("c411") == [
        {"max_bytes": 1073741824, "piece_size": 1048576},
        {"max_bytes": 2147483648, "piece_size": 2097152},
        {"max_bytes": 3221225472, "piece_size": 4194304},
        {"max_bytes": 8589934592, "piece_size": 8388608},
        {"piece_size": 16777216},
    ]


# --------------------------------------------------------------------------- #
# tracker.upload (AUTOMATION.md, sous-projet 5) -- valeurs reelles C411,
# donnees par l'utilisateur le 2026-09-04.
# --------------------------------------------------------------------------- #
def test_c411_upload_category_and_subcategory_ids():
    upload = tracker_profile.upload_config("c411")
    assert upload["category_id"] == 1
    assert upload["subcategory_id"] == {
        "movie": 6, "movie:anime": 1, "movie:documentaire": 4,
        "series": 7, "series:anime": 2, "series:documentaire": 4,
    }


def test_c411_upload_language_values():
    upload = tracker_profile.upload_config("c411")
    assert upload["language_option_id"] == 1
    assert upload["language_values"] == {"VFF": 2, "MULTI.VFF": 4, "VO": 1, "VOSTFR": 8}


def test_c411_upload_quality_values():
    upload = tracker_profile.upload_config("c411")
    assert upload["quality_option_id"] == 2
    assert upload["quality_values"] == {
        "BluRay.HDLight": 413, "BluRay": 11, "BluRay.REMUX": 12, "WEB": 25, "WEB.4K": 26,
    }


def test_c411_upload_season_values_cover_s01_to_s30():
    upload = tracker_profile.upload_config("c411")
    assert upload["season_option_id"] == 7
    assert upload["season_values"]["INTEGRALE"] == 118
    assert upload["season_values"]["S01"] == 121
    assert upload["season_values"]["S02"] == 122
    assert upload["season_values"]["S30"] == 150
    assert len(upload["season_values"]) == 31  # INTEGRALE + S01..S30


def test_c411_upload_episode_values():
    upload = tracker_profile.upload_config("c411")
    assert upload["episode_option_id"] == 6
    assert upload["full_season_episode_value"] == 96


def test_upload_config_empty_when_not_declared():
    assert tracker_profile.upload_config("does-not-exist") == {}
