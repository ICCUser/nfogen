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
