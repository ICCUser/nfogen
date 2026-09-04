"""Tests de `rules.source_marker_warnings` (AUTOMATION.md) : avertit quand
une source (ex. BluRay) a un debit reel sous le seuil attendu par le
tracker pour cette source, sans le marqueur de qualite correspondant deja
present dans le nom (ex. 'HDLight') -- incident reel, upload C411 refuse
('le debit video est inferieur au seuil ... ajoute HDLight'). Jamais
bloquant, silencieux des que l'info necessaire manque."""
from __future__ import annotations

from nfogen import rules as rules_engine

SCHEMA = {
    "source_marker_checks": [
        {
            "sources": ["BluRay"],
            "max_bit_rate_kbps": 8000,
            "marker": "HDLight",
            "message": (
                "Débit ({bitrate} kb/s) < {threshold} kb/s pour une source {source} : "
                "ajoute '{marker}' après '{source}' dans le titre."
            ),
        }
    ]
}

CAPTURES = {"source": "BluRay"}
LOW_BITRATE_METADATA = {"video_bit_rate": 1_619_000}  # cas reel (Joker/Wild Card 2015)
HIGH_BITRATE_METADATA = {"video_bit_rate": 12_000_000}
RELEASE_NAME_WITHOUT_MARKER = "Joker.2015.MULTI.VFF.1080p.BluRay.AC3.5.1.x264-NOTAG"
RELEASE_NAME_WITH_MARKER = "Joker.2015.MULTI.VFF.1080p.BluRay.HDLight.AC3.5.1.x264-NOTAG"


def test_warns_when_bitrate_below_threshold_for_matching_source():
    found = rules_engine.source_marker_warnings(
        RELEASE_NAME_WITHOUT_MARKER, CAPTURES, LOW_BITRATE_METADATA, SCHEMA
    )
    assert len(found) == 1
    assert "HDLight" in found[0]


def test_message_placeholders_are_filled():
    found = rules_engine.source_marker_warnings(
        RELEASE_NAME_WITHOUT_MARKER, CAPTURES, LOW_BITRATE_METADATA, SCHEMA
    )
    assert "1619 kb/s" in found[0]
    assert "8000 kb/s" in found[0]
    assert "BluRay" in found[0]


def test_no_warning_when_bitrate_at_or_above_threshold():
    assert (
        rules_engine.source_marker_warnings(
            RELEASE_NAME_WITHOUT_MARKER, CAPTURES, HIGH_BITRATE_METADATA, SCHEMA
        )
        == []
    )


def test_no_warning_when_marker_already_present_in_name():
    assert (
        rules_engine.source_marker_warnings(
            RELEASE_NAME_WITH_MARKER, CAPTURES, LOW_BITRATE_METADATA, SCHEMA
        )
        == []
    )


def test_marker_presence_check_is_case_insensitive():
    lowercase = RELEASE_NAME_WITH_MARKER.replace("HDLight", "hdlight")
    assert (
        rules_engine.source_marker_warnings(lowercase, CAPTURES, LOW_BITRATE_METADATA, SCHEMA) == []
    )


def test_no_warning_when_source_does_not_match_any_check():
    captures = {"source": "WEB"}
    assert (
        rules_engine.source_marker_warnings(
            RELEASE_NAME_WITHOUT_MARKER, captures, LOW_BITRATE_METADATA, SCHEMA
        )
        == []
    )


def test_no_warning_when_profile_has_no_source_marker_checks_configured():
    assert (
        rules_engine.source_marker_warnings(RELEASE_NAME_WITHOUT_MARKER, CAPTURES, LOW_BITRATE_METADATA, {})
        == []
    )


def test_no_warning_when_release_name_has_no_source_capture():
    assert (
        rules_engine.source_marker_warnings(RELEASE_NAME_WITHOUT_MARKER, {}, LOW_BITRATE_METADATA, SCHEMA)
        == []
    )


def test_no_warning_when_bit_rate_metadata_missing():
    assert (
        rules_engine.source_marker_warnings(RELEASE_NAME_WITHOUT_MARKER, CAPTURES, {}, SCHEMA) == []
    )
