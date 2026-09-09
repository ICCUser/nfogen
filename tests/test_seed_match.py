"""Tests de nfogen.seed_match (detection de correspondance exacte avec
une release C411 existante, en vue d'un seed sans re-upload)."""
from __future__ import annotations

from nfogen.quality import ReleaseQuality
from nfogen.seed_match import SeedMatchCandidate, find_seed_match
from nfogen.torznab_client import TorznabRelease


def _release(guid="guid-1", title="Movie.2020.VFF.1080p.BluRay.x264-TEAM", size=1_000_000):
    return TorznabRelease(title=title, guid=guid, link="https://c411.org/torrents/x", size=size)


LOCAL_QUALITY = ReleaseQuality(
    raw="Movie.2020.VFF.1080p.BluRay.x264-TEAM", resolution=1080, source="BLURAY",
    codec="X264", languages=["VFF"], multi=False, pure=False,
)


def test_finds_a_single_exact_candidate():
    release = _release()
    candidate = find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release])
    assert candidate == SeedMatchCandidate(guid="guid-1", release_name=release.title)


def test_no_match_when_size_differs():
    release = _release(size=2_000_000)
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release]) is None


def test_no_match_when_team_differs():
    release = _release(title="Movie.2020.VFF.1080p.BluRay.x264-OTHER")
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release]) is None


def test_no_match_when_resolution_differs():
    release = _release(title="Movie.2020.VFF.2160p.BluRay.x264-TEAM")
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release]) is None


def test_no_match_when_local_team_is_none():
    release = _release()
    assert find_seed_match(LOCAL_QUALITY, None, 1_000_000, [release]) is None


def test_no_match_when_ambiguous_multiple_candidates():
    release_a = _release(guid="guid-a")
    release_b = _release(guid="guid-b")
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, [release_a, release_b]) is None


def test_no_match_when_no_releases():
    assert find_seed_match(LOCAL_QUALITY, "TEAM", 1_000_000, []) is None
