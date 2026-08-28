"""Tests de l'heuristique upscale (`rules.upscale_warnings`, AUTOMATION.md).

Avertit quand le debit reel est anormalement bas pour le codec/la resolution
annonces dans le release_name (indice d'upscale) -- jamais bloquant, et
silencieux des que l'information necessaire manque (mieux vaut se taire que
deviner)."""
from __future__ import annotations

from nfogen import rules as rules_engine

SCHEMA = {
    "upscale_checks": {
        "resolution_capture": "resolution",
        "video_codec_capture": "video_codec",
        "min_bits_per_pixel": {"x264": 0.05, "hevc": 0.03},
        "message": (
            "Débit ({bitrate} kb/s) anormalement bas pour du {codec} en {resolution}p "
            "({bpp} bit/pixel, seuil {threshold}) : upscale possible."
        ),
    }
}

CAPTURES = {"resolution": "1080", "video_codec": "x264"}

# 1920x1080 @ 24fps : seuil x264 (0.05 bpp) => ~2488 kb/s
LOW_BITRATE_METADATA = {
    "video_width": 1920,
    "video_height": 1080,
    "video_bit_rate": 1_500_000,
    "frame_rate": 24.0,
}
HIGH_BITRATE_METADATA = {
    "video_width": 1920,
    "video_height": 1080,
    "video_bit_rate": 6_000_000,
    "frame_rate": 24.0,
}


def test_warns_when_bitrate_is_far_below_threshold_for_the_announced_codec():
    found = rules_engine.upscale_warnings(CAPTURES, LOW_BITRATE_METADATA, SCHEMA)
    assert len(found) == 1
    assert "upscale possible" in found[0]


def test_message_placeholders_are_filled():
    found = rules_engine.upscale_warnings(CAPTURES, LOW_BITRATE_METADATA, SCHEMA)
    assert "1500 kb/s" in found[0]
    assert "x264" in found[0]
    assert "1080p" in found[0]
    assert "0.05" in found[0]


def test_no_warning_when_bitrate_is_comfortably_above_threshold():
    assert rules_engine.upscale_warnings(CAPTURES, HIGH_BITRATE_METADATA, SCHEMA) == []


def test_no_warning_when_profile_has_no_upscale_checks_configured():
    assert rules_engine.upscale_warnings(CAPTURES, LOW_BITRATE_METADATA, {}) == []


def test_no_warning_when_release_name_has_no_codec_capture():
    captures = {"resolution": "1080"}  # pas de video_codec captured
    assert rules_engine.upscale_warnings(captures, LOW_BITRATE_METADATA, SCHEMA) == []


def test_no_warning_when_codec_has_no_configured_threshold():
    """Un codec sans seuil dans min_bits_per_pixel (ex: MPEG2 non configure
    pour ce profil) est ignore plutot que traite comme 0 -- pas de faux
    positif sur un codec qu'on n'a pas etudie."""
    captures = {"resolution": "1080", "video_codec": "MPEG2"}
    assert rules_engine.upscale_warnings(captures, LOW_BITRATE_METADATA, SCHEMA) == []


def test_no_warning_when_metadata_is_missing_a_required_field():
    for missing in ("video_width", "video_height", "video_bit_rate", "frame_rate"):
        incomplete = {k: v for k, v in LOW_BITRATE_METADATA.items() if k != missing}
        assert rules_engine.upscale_warnings(CAPTURES, incomplete, SCHEMA) == [], missing


def test_codec_matching_is_case_and_dot_insensitive_like_codec_alias_comparator():
    captures = {"resolution": "1080", "video_codec": "X.264"}
    found = rules_engine.upscale_warnings(captures, LOW_BITRATE_METADATA, SCHEMA)
    assert len(found) == 1
