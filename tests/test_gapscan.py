"""Tests de nfogen.gapscan (classification + orchestration).

Le client C411 est un double de test (pas de reseau) : seule la logique de
comparaison est visee ici, `test_c411_client.py`/`test_sonarr_client.py`/
`test_radarr_client.py` couvrent deja les clients HTTP eux-memes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from nfogen.c411_client import C411Error, C411Release
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
    """Retourne des resultats fixes, indexes par le type d'appel recu.

    `title_movie_results`, si fourni, distingue la reponse a un repli par
    TITRE (query non None) de celle a une recherche par ID -- necessaire
    pour tester le repli sans exigence externe (voir tests dedies plus
    bas)."""

    movie_results: list[C411Release] = field(default_factory=list)
    title_movie_results: Optional[list[C411Release]] = None
    tv_results: list[C411Release] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)
    raises: Optional[Exception] = None

    def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
        self.calls.append(("movie", query, imdb_id, tmdb_id))
        if self.raises is not None:
            raise self.raises
        if query is not None and self.title_movie_results is not None:
            return self.title_movie_results
        return self.movie_results

    def search_tv(self, query=None, imdb_id=None, tmdb_id=None, season=None, ep=None):
        self.calls.append(("tv", query, imdb_id, season))
        if self.raises is not None:
            raise self.raises
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


def test_scan_movie_falls_back_to_title_even_when_id_search_finds_nothing():
    """Incident reel (retour utilisateur, 'Joker') : torznab:attr imdbid/
    tmdbid ne sont PAS systematiquement presents sur les releases C411 (cf.
    GAPSCAN.md) -- une recherche par ID peut donc echouer alors que le
    titre existe bel et bien sur le tracker. Le repli par titre doit avoir
    lieu meme quand un ID externe est connu, pas seulement en son absence."""
    c411 = FakeC411(
        movie_results=[],  # la recherche par ID (imdb/tmdb) ne trouve rien
        title_movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")],
    )
    result = scan_movie(_movie(), c411)  # imdb_id/tmdb_id bien fournis ici
    assert ("movie", None, "tt0133093", "603") in c411.calls  # recherche par ID tentee
    assert ("movie", "Matrix", None, None) in c411.calls  # PUIS repli par titre
    assert result.status == GapStatus.COVERED  # le repli a bien trouve la release


def test_scan_movie_title_fallback_discards_a_different_year():
    """Le repli par titre est plus permissif (simple recherche texte) : sans
    filtre, une release homonyme d'un AUTRE millesime (plusieurs films
    s'appellent 'Joker' a des annees differentes) serait prise pour une
    couverture valide. Filtre par annee quand elle est connue localement."""
    c411 = FakeC411(
        movie_results=[],
        title_movie_results=[_release("Joker.2019.MULTI.VFF.2160p.BluRay.x265-TEAM")],
    )
    result = scan_movie(_movie(title="Joker", year=2015, imdb_id="tt0000000", tmdb_id=1), c411)
    assert ("movie", "Joker", None, None) in c411.calls  # le repli a bien eu lieu...
    assert result.status == GapStatus.ABSENT  # ...mais le match 2019 ne compte pas pour un film de 2015
    assert result.c411_matches == []


def test_scan_movie_title_fallback_keeps_a_matching_year():
    c411 = FakeC411(
        movie_results=[],
        title_movie_results=[_release("Joker.2019.MULTI.VFF.2160p.BluRay.x265-TEAM")],
    )
    result = scan_movie(_movie(title="Joker", year=2019, imdb_id="tt0000000", tmdb_id=1), c411)
    assert result.status == GapStatus.COVERED


def test_scan_movie_title_fallback_keeps_releases_without_a_parseable_year():
    """Un titre sans annee explicite dans le nom n'est pas ecarte par
    prudence -- mieux vaut un match ambigu remonte a l'utilisateur qu'une
    couverture reelle silencieusement ignoree."""
    c411 = FakeC411(
        movie_results=[],
        title_movie_results=[_release("Joker.MULTI.VFF.2160p.BluRay.x265-TEAM")],
    )
    result = scan_movie(_movie(title="Joker", year=2015, imdb_id="tt0000000", tmdb_id=1), c411)
    assert result.status == GapStatus.COVERED


def test_scan_movie_flags_freeleech_alternative():
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.1080p.WEBRip.x264-TEAM", dvf=0.0)])
    result = scan_movie(_movie(), c411)
    assert result.has_freeleech_alternative is True


def test_scan_movie_returns_error_status_when_c411_lookup_fails():
    """Incident reel (2026-08-25, 429/520 C411) : une erreur cote C411 pour
    UN titre ne doit pas empecher de savoir au moins ce qu'on sait deja
    localement (qualite/langue), et surtout pas planter tout le scan --
    voir test_run_gapscan_continues_after_a_single_item_failure."""
    c411 = FakeC411(raises=C411Error("Appel a l'API C411 echoue (movie) : 429 Too Many Requests"))
    result = scan_movie(_movie(), c411)
    assert result.status == GapStatus.ERROR
    assert "429" in result.error
    assert result.title == "Matrix"
    assert result.local_quality.resolution == 2160  # connu localement, sans avoir contacte C411
    assert result.c411_matches == []


def test_scan_series_season_returns_error_status_when_c411_lookup_fails():
    c411 = FakeC411(raises=C411Error("boom"))
    result = scan_series_season(_season(), c411)
    assert result.status == GapStatus.ERROR
    assert result.error == "boom"
    assert result.season_number == 1


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


def test_run_gapscan_reports_progress():
    """`on_progress` (optionnel) : necessaire a /gapscan/status pour
    afficher une progression sans devoir re-derouler la boucle ailleurs."""
    c411 = FakeC411(movie_results=[], tv_results=[])
    calls: list[tuple[int, int]] = []

    run_gapscan(
        c411, radarr=_FakeRadarr(), sonarr=_FakeSonarr(),
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls == [(1, 2), (2, 2)]


def test_run_gapscan_without_progress_callback_still_works():
    c411 = FakeC411(movie_results=[])
    results = run_gapscan(c411, radarr=_FakeRadarr())
    assert len(results) == 1


class _FakeRadarrTwoMovies:
    def list_movie_files(self):
        return [_movie(title="A"), _movie(title="B")]


def test_run_gapscan_continues_after_a_single_item_failure():
    """Le coeur du correctif de resilience : UNE erreur C411 sur un titre
    (429, 520, timeout...) ne doit PAS interrompre le scan des titres
    suivants -- avant ce correctif, toute la progression deja faite sur
    une grosse bibliotheque etait perdue au premier accroc reseau."""

    class FlakyC411:
        def __init__(self):
            self.calls = 0

        def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
            self.calls += 1
            if self.calls == 1:
                raise C411Error("520 (transitoire)")
            return []

    c411 = FlakyC411()
    results = run_gapscan(c411, radarr=_FakeRadarrTwoMovies())

    assert len(results) == 2  # les DEUX titres ont un resultat, pas d'exception propagee
    assert results[0].status == GapStatus.ERROR
    assert results[1].status == GapStatus.ABSENT  # le 2e titre a bien ete traite normalement


def test_run_gapscan_still_reports_progress_after_an_item_failure():
    class FlakyC411:
        def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
            raise C411Error("boom")

    calls: list[tuple[int, int]] = []
    run_gapscan(
        FlakyC411(), radarr=_FakeRadarrTwoMovies(),
        on_progress=lambda done, total: calls.append((done, total)),
    )
    assert calls == [(1, 2), (2, 2)]


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
