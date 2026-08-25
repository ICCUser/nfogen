"""Tests de nfogen.gapscan (classification + orchestration).

Le client C411 est un double de test (pas de reseau) : seule la logique de
comparaison est visee ici, `test_c411_client.py`/`test_sonarr_client.py`/
`test_radarr_client.py` couvrent deja les clients HTTP eux-memes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from nfogen.c411_client import C411Release
from nfogen.gapscan import (
    GapStatus,
    run_gapscan,
    scan_movie,
    scan_series_season,
    sort_by_priority,
)
from nfogen.radarr_client import RadarrMovieFile
from nfogen.sonarr_client import SonarrSeasonFile


def _release(title: str, imdb_id: Optional[str] = None, dvf: float = 1.0, uvf: float = 1.0) -> C411Release:
    return C411Release(title=title, guid=title, link="https://c411.org/x", imdb_id=imdb_id,
                        download_volume_factor=dvf, upload_volume_factor=uvf)


@dataclass
class FakeC411:
    """Retourne des resultats fixes, indexes par le type d'appel recu."""

    movie_results: list[C411Release] = field(default_factory=list)
    tv_results: list[C411Release] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)

    def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
        self.calls.append(("movie", query, imdb_id, tmdb_id))
        return self.movie_results

    def search_tv(self, query=None, imdb_id=None, tmdb_id=None, season=None, ep=None):
        self.calls.append(("tv", query, imdb_id, season))
        return self.tv_results


# --------------------------------------------------------------------------- #
# scan_movie
# --------------------------------------------------------------------------- #
def _movie(**overrides) -> RadarrMovieFile:
    base = dict(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        best_resolution=2160, quality_name="Bluray-2160p",
        scene_name="Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ", language_names=["French"],
    )
    base.update(overrides)
    return RadarrMovieFile(**base)


def test_scan_movie_absent_when_no_c411_match():
    c411 = FakeC411(movie_results=[])
    result = scan_movie(_movie(), c411)
    assert result.status == GapStatus.ABSENT
    assert result.media_type == "movie"
    assert ("movie", None, "tt0133093", "603") in c411.calls


def test_scan_movie_quality_gap_when_local_is_better():
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.1080p.WEBRip.x264-TEAM")])
    result = scan_movie(_movie(), c411)
    assert result.status == GapStatus.QUALITY_GAP


def test_scan_movie_covered_when_equal_or_better_and_same_language():
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    result = scan_movie(_movie(), c411)
    assert result.status == GapStatus.COVERED


def test_scan_movie_language_gap_when_quality_ok_but_language_missing():
    c411 = FakeC411(movie_results=[_release("Matrix.1999.VOSTFR.2160p.BluRay.x265-QTZ")])
    result = scan_movie(_movie(), c411)
    assert result.status == GapStatus.LANGUAGE_GAP


def test_scan_movie_falls_back_to_title_query_without_external_ids():
    c411 = FakeC411(movie_results=[])
    scan_movie(_movie(imdb_id=None, tmdb_id=None), c411)
    assert ("movie", "Matrix", None, None) in c411.calls


def test_scan_movie_flags_freeleech_alternative():
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.1080p.WEBRip.x264-TEAM", dvf=0.0)])
    result = scan_movie(_movie(), c411)
    assert result.has_freeleech_alternative is True


def test_scan_movie_flags_double_upload_window():
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.1080p.WEBRip.x264-TEAM", uvf=2.0)])
    result = scan_movie(_movie(), c411)
    assert result.has_double_upload_window is True


# --------------------------------------------------------------------------- #
# scan_series_season
# --------------------------------------------------------------------------- #
def _season(**overrides) -> SonarrSeasonFile:
    base = dict(
        series_id=1, title="Breaking Bad", year=2008, tvdb_id=81189, imdb_id="tt0903747",
        season_number=1, episode_file_count=7,
        best_resolution=2160, quality_name="WEBRip-2160p",
        scene_name="Breaking.Bad.S01.MULTI.VFF.2160p.WEBRip.x265-SQUEEZE", language_names=["French"],
    )
    base.update(overrides)
    return SonarrSeasonFile(**base)


def test_scan_series_season_absent_when_no_match():
    c411 = FakeC411(tv_results=[])
    result = scan_series_season(_season(), c411)
    assert result.status == GapStatus.ABSENT
    assert result.media_type == "series"
    assert result.season_number == 1


def test_scan_series_season_covered():
    c411 = FakeC411(tv_results=[_release("Breaking.Bad.S01.MULTI.VFF.2160p.WEBRip.x265-SQUEEZE")])
    result = scan_series_season(_season(), c411)
    assert result.status == GapStatus.COVERED


# --------------------------------------------------------------------------- #
# run_gapscan / sort_by_priority
# --------------------------------------------------------------------------- #
class _FakeRadarr:
    def list_movie_files(self):
        return [_movie()]


class _FakeSonarr:
    def list_season_files(self):
        return [_season()]


def test_run_gapscan_combines_radarr_and_sonarr():
    c411 = FakeC411(movie_results=[], tv_results=[])
    results = run_gapscan(c411, radarr=_FakeRadarr(), sonarr=_FakeSonarr())
    assert {r.media_type for r in results} == {"movie", "series"}


def test_run_gapscan_with_only_radarr():
    c411 = FakeC411(movie_results=[])
    results = run_gapscan(c411, radarr=_FakeRadarr())
    assert len(results) == 1
    assert results[0].media_type == "movie"


def test_sort_by_priority_orders_gaps_before_covered():
    c411 = FakeC411()
    absent = scan_movie(_movie(title="Z Absent"), c411)
    c411_covered = FakeC411(movie_results=[_release("A.Covered.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    covered = scan_movie(_movie(title="A Covered"), c411_covered)

    ordered = sort_by_priority([covered, absent])
    assert [r.status for r in ordered] == [GapStatus.ABSENT, GapStatus.COVERED]


def test_sort_by_priority_prefers_freeleech_at_equal_status():
    c411_fl = FakeC411(movie_results=[_release("B.1999.MULTI.VFF.1080p.WEBRip.x264-TEAM", dvf=0.0)])
    fl_result = scan_movie(_movie(title="B"), c411_fl)
    c411_plain = FakeC411(movie_results=[_release("A.1999.MULTI.VFF.1080p.WEBRip.x264-TEAM")])
    plain_result = scan_movie(_movie(title="A"), c411_plain)

    ordered = sort_by_priority([plain_result, fl_result])
    assert ordered[0] is fl_result  # meme statut (quality_gap) : FL passe devant malgre l'ordre alphabetique
