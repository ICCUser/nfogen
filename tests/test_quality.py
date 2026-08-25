"""Tests de nfogen.quality (extraction/comparaison qualite-langue)."""
from __future__ import annotations

from nfogen.quality import (
    build_quality,
    is_language_gap,
    is_quality_upgrade,
    language_groups_from_names,
    parse_release_name,
)


def test_parse_release_name_full():
    q = parse_release_name("Matrix.1999.MULTI.VFF.2160p.BluRay.4KLight.HDR.DTS.5.1.x265-QTZ")
    assert q.resolution == 2160
    assert q.source == "BLURAY"
    assert q.codec == "X265"
    assert q.languages == ["VFF"]
    assert q.multi is True


def test_parse_release_name_no_language_is_not_an_error():
    q = parse_release_name("Some.Clip.2020.1080p.WEB.H264-TEAM")
    assert q.languages == []
    assert q.resolution == 1080


def test_source_rank_orders_remux_above_webrip():
    remux = parse_release_name("Film.2020.MULTI.VFF.1080p.REMUX.DTS.5.1.x264-TEAM")
    webrip = parse_release_name("Film.2020.MULTI.VFF.1080p.WEBRip.AAC.5.1.x264-TEAM")
    assert remux.source_rank < webrip.source_rank  # rang plus bas = meilleur


def test_is_quality_upgrade_by_source():
    local = parse_release_name("Film.2020.MULTI.VFF.1080p.REMUX.DTS.5.1.x264-TEAM")
    remote = parse_release_name("Film.2020.MULTI.VFF.1080p.WEBRip.AAC.5.1.x264-TEAM")
    assert is_quality_upgrade(local, remote) is True
    assert is_quality_upgrade(remote, local) is False


def test_is_quality_upgrade_by_resolution_when_source_unknown():
    local = parse_release_name("Film.2020.MULTI.VFF.2160p.x264-TEAM")
    remote = parse_release_name("Film.2020.MULTI.VFF.1080p.x264-TEAM")
    assert is_quality_upgrade(local, remote) is True


def test_is_quality_upgrade_false_when_nothing_comparable():
    local = parse_release_name("Film.2020.MULTI.VFF.x264-TEAM")
    remote = parse_release_name("Film.2020.MULTI.VFF.x265-AUTRE")
    assert is_quality_upgrade(local, remote) is False


def test_language_groups_equivalence():
    vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    vfq = parse_release_name("Film.2020.VFQ.1080p.WEB.x264-TEAM")
    assert vff.language_groups == vfq.language_groups == {"VF"}


def test_is_language_gap_true_when_missing():
    local = parse_release_name("Film.2020.VOSTFR.1080p.WEB.x264-TEAM")
    remote = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert is_language_gap(local, remote) is True


def test_is_language_gap_false_when_no_local_language():
    local = parse_release_name("Film.2020.1080p.WEB.x264-TEAM")
    remote = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert is_language_gap(local, remote) is False


def test_language_groups_from_names_maps_generic_names():
    assert language_groups_from_names(["French", "English"]) == {"VF", "VO"}


def test_language_groups_from_names_keeps_unknown():
    assert language_groups_from_names(["Klingon"]) == {"KLINGON"}


def test_build_quality_prefers_parseable_release_name():
    q = build_quality(
        "Film.2020.VFQ.1080p.BluRay.x264-TEAM",
        fallback_resolution=720,
        fallback_language_names=["English"],
    )
    assert q.resolution == 1080  # vient du release_name, pas du fallback
    assert q.languages == ["VFQ"]  # langue trouvee dans le nom : le fallback est ignore


def test_build_quality_falls_back_to_structured_fields():
    q = build_quality(
        None, fallback_resolution=1080, fallback_source="webdl", fallback_language_names=["French"]
    )
    assert q.resolution == 1080
    assert q.source == "WEBDL"
    assert q.languages == ["VF"]
