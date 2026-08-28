"""Tests de nfogen.gapscan (classification + orchestration).

Le client C411 est un double de test (pas de reseau) : seule la logique de
comparaison est visee ici, `test_c411_client.py`/`test_sonarr_client.py`/
`test_radarr_client.py` couvrent deja les clients HTTP eux-memes.
"""
from __future__ import annotations

import os
import time
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
    # Reponses par requete TEXTE exacte (query) -- necessaire pour tester le
    # repli par titre ALTERNATIF (voir tests dedies plus bas) sans perturber
    # title_movie_results, qui reste la reponse par defaut pour tout autre
    # titre non liste ici.
    query_results: dict[str, list[C411Release]] = field(default_factory=dict)
    tv_query_results: dict[str, list[C411Release]] = field(default_factory=dict)
    tv_results: list[C411Release] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)
    raises: Optional[Exception] = None

    def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
        self.calls.append(("movie", query, imdb_id, tmdb_id))
        if self.raises is not None:
            raise self.raises
        if query is not None and query in self.query_results:
            return self.query_results[query]
        if query is not None and self.title_movie_results is not None:
            return self.title_movie_results
        return self.movie_results

    def search_tv(self, query=None, imdb_id=None, tmdb_id=None, season=None, ep=None):
        self.calls.append(("tv", query, imdb_id, season))
        if self.raises is not None:
            raise self.raises
        if query is not None and query in self.tv_query_results:
            return self.tv_query_results[query]
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
# Resolution de chemin (AUTOMATION.md, sous-projet 1) : etant donne un
# chemin distant Sonarr/Radarr, obtenir et valider un chemin local reel.
# --------------------------------------------------------------------------- #
def test_scan_movie_resolves_and_validates_the_local_path(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    c411 = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    result = scan_movie(_movie(remote_path=str(f)), c411, path_mappings={})
    assert result.local_paths == [str(f)]
    assert result.path_resolved is True
    assert result.path_error is None


def test_scan_movie_reports_when_the_local_path_is_missing():
    c411 = FakeC411(movie_results=[])
    result = scan_movie(_movie(remote_path="/nope/absent.mkv"), c411, path_mappings={})
    assert result.path_resolved is False
    assert "introuvable" in result.path_error


def test_scan_movie_without_a_remote_path_reports_unresolved():
    c411 = FakeC411(movie_results=[])
    result = scan_movie(_movie(remote_path=None), c411)
    assert result.path_resolved is False
    assert result.local_paths == []


def test_scan_movie_applies_the_configured_path_mapping(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    c411 = FakeC411(movie_results=[])
    result = scan_movie(
        _movie(remote_path="/data/media/Matrix.mkv"), c411,
        path_mappings={"/data/media": str(tmp_path)},
    )
    # normpath : le prefixe distant litteral (style Linux, "/") mixe avec
    # tmp_path (separateurs natifs de la machine de dev) ne doit pas faire
    # dependre ce test de l'OS qui l'execute (voir test_path_mapping.py).
    assert os.path.normpath(result.local_paths[0]) == os.path.normpath(str(f))
    assert result.path_resolved is True


# --------------------------------------------------------------------------- #
# Mode incremental (`previous=`) : retour utilisateur du 2026-08-26, "je vais
# pas tout rescanner a chaque fois" -- un titre deja COVERED au scan
# precedent, dont la qualite locale n'a pas change depuis, doit etre repris
# tel quel sans reinterroger C411.
# --------------------------------------------------------------------------- #
def test_scan_movie_reuses_previous_result_when_covered_and_quality_unchanged():
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(), c411_first)
    assert previous.status == GapStatus.COVERED

    c411_second = FakeC411()  # si appele a tort, renverrait ABSENT (revelateur)
    result = scan_movie(_movie(), c411_second, previous=previous)

    # Le verdict C411 est repris tel quel (checked_at non rafraichi = pas
    # de reinterrogation reelle) -- mais plus le MEME objet Python : les
    # champs de chemin sont toujours recalcules a neuf (replace()), voir
    # test_scan_movie_reuse_still_refreshes_path_validation.
    assert result.status == previous.status
    assert result.checked_at == previous.checked_at
    assert c411_second.calls == []


def test_scan_movie_rescans_when_previous_was_not_covered():
    """Un gap non comble merite d'etre reverifie : C411 a pu se remplir
    depuis le dernier scan."""
    c411_first = FakeC411(movie_results=[])
    previous = scan_movie(_movie(), c411_first)
    assert previous.status == GapStatus.ABSENT

    c411_second = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    result = scan_movie(_movie(), c411_second, previous=previous)

    assert c411_second.calls != []
    assert result.status == GapStatus.COVERED


def test_scan_movie_rescans_when_local_quality_changed():
    """La bibliotheque locale a pu etre mise a niveau (Sonarr/Radarr a grabbe
    une meilleure version) depuis le scan precedent : la comparaison
    precedente n'est plus valable."""
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.1080p.BluRay.x265-QTZ")])
    previous = scan_movie(
        _movie(best_resolution=1080, scene_name="Matrix.1999.MULTI.VFF.1080p.BluRay.x265-QTZ"),
        c411_first,
    )
    assert previous.status == GapStatus.COVERED

    c411_second = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.1080p.BluRay.x265-QTZ")])
    result = scan_movie(_movie(), c411_second, previous=previous)  # 2160p par defaut, cf. _movie()

    assert c411_second.calls != []
    assert result.status == GapStatus.QUALITY_GAP


def test_scan_movie_does_not_reuse_a_stale_covered_result():
    """`max_age_seconds` (retour utilisateur, 2026-08-27 : "c411 enleve et
    ajoute assez souvent des torrents") : un resultat COVERED trop ancien
    est reverifie, meme si rien n'a change localement -- une release
    couvrante a pu disparaitre de C411 depuis."""
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(), c411_first)
    previous.checked_at = time.time() - 1000  # bien au-dela de max_age_seconds=10

    c411_second = FakeC411()  # si non reinterroge a tort, testerait le mauvais chemin
    result = scan_movie(_movie(), c411_second, previous=previous, max_age_seconds=10)

    assert c411_second.calls != []
    assert result.status == GapStatus.ABSENT  # reinterroge pour de vrai, plus repris tel quel


def test_scan_movie_reuses_a_fresh_covered_result_within_max_age():
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(), c411_first)

    c411_second = FakeC411()
    result = scan_movie(_movie(), c411_second, previous=previous, max_age_seconds=1000)

    assert c411_second.calls == []
    assert result.status == previous.status
    assert result.checked_at == previous.checked_at


def test_scan_movie_without_max_age_seconds_never_expires():
    """`max_age_seconds=None` (par defaut) : comportement historique,
    aucune limite d'age -- pour ne pas casser les appels existants qui ne
    s'en soucient pas."""
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(), c411_first)
    previous.checked_at = time.time() - 10_000_000

    c411_second = FakeC411()
    result = scan_movie(_movie(), c411_second, previous=previous)

    assert c411_second.calls == []
    assert result.status == previous.status
    assert result.checked_at == previous.checked_at


def test_scan_movie_missing_checked_at_is_treated_as_stale():
    """Resultat persiste avant l'ajout de `checked_at` (retro-compatibilite,
    voir gapscan_results_store.py) : reverifie par prudence des qu'une
    limite d'age est demandee, plutot que suppose "toujours frais"."""
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(), c411_first)
    previous.checked_at = None

    c411_second = FakeC411()
    scan_movie(_movie(), c411_second, previous=previous, max_age_seconds=1000)

    assert c411_second.calls != []


# --------------------------------------------------------------------------- #
# Titres alternatifs (VF) : C411 est un tracker francophone, un titre
# original en anglais peut y etre liste sous son titre de sortie/diffusion
# FR (ex. "Wild Card" -> "Joker", "White Collar" -> "FBI, duo tres special")
# -- retour utilisateur, 2026-08-27. Sonarr/Radarr connaissent en general
# ces titres alternatifs (`alternateTitles`).
# --------------------------------------------------------------------------- #
def test_scan_movie_falls_back_to_alternate_titles_when_primary_title_finds_nothing():
    c411 = FakeC411(
        movie_results=[],  # recherche par ID : rien
        title_movie_results=[],  # titre original ("Wild Card") : rien non plus
        query_results={"Joker": [_release("Joker.2015.MULTI.VFF.2160p.BluRay.x265-TEAM")]},
    )
    movie = _movie(
        title="Wild Card", year=2015, imdb_id="tt2321549", tmdb_id=228165,
        alternate_titles=["Joker"],
    )
    result = scan_movie(movie, c411)

    assert ("movie", "Wild Card", None, None) in c411.calls  # titre original tente d'abord
    assert ("movie", "Joker", None, None) in c411.calls  # PUIS le titre alternatif FR
    assert result.status == GapStatus.COVERED


def test_scan_movie_alternate_title_still_filtered_by_year():
    c411 = FakeC411(
        movie_results=[],
        title_movie_results=[],
        query_results={"Joker": [_release("Joker.2019.MULTI.VFF.2160p.BluRay.x265-TEAM")]},
    )
    movie = _movie(
        title="Wild Card", year=2015, imdb_id="tt2321549", tmdb_id=228165,
        alternate_titles=["Joker"],
    )
    result = scan_movie(movie, c411)
    assert result.status == GapStatus.ABSENT  # le "Joker" 2019 (DC) ne compte pas pour "Wild Card" 2015


def test_scan_movie_reuse_still_refreshes_path_validation(tmp_path):
    """Le mode incremental reprend le verdict C411, mais PAS le statut de
    chemin -- celui-ci doit toujours refleter l'etat reel du disque a
    l'instant du scan (AUTOMATION.md, sous-projet 1 : "valide a chaque
    scan"), meme quand le verdict C411 est repris tel quel."""
    f = tmp_path / "Matrix.mkv"
    f.write_text("x")
    c411_first = FakeC411(movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")])
    previous = scan_movie(_movie(remote_path=str(f)), c411_first, path_mappings={})
    assert previous.path_resolved is True

    f.unlink()  # le fichier disparait entre les deux scans
    c411_second = FakeC411()  # ne doit pas etre appele (reuse du verdict C411)
    result = scan_movie(_movie(remote_path=str(f)), c411_second, previous=previous, path_mappings={})

    assert c411_second.calls == []  # verdict C411 bien repris (COVERED)
    assert result.status == GapStatus.COVERED
    assert result.path_resolved is False  # mais le chemin est bien revalide
    assert "introuvable" in result.path_error


def test_scan_series_season_reuses_previous_result_when_covered_and_unchanged():
    c411_first = FakeC411(tv_results=[_release("Breaking.Bad.S01.MULTI.VFF.2160p.WEBRip.x265-SQUEEZE")])
    previous = scan_series_season(_season(), c411_first)
    assert previous.status == GapStatus.COVERED

    c411_second = FakeC411()
    result = scan_series_season(_season(), c411_second, previous=previous)

    assert result.status == previous.status
    assert result.checked_at == previous.checked_at
    assert c411_second.calls == []


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


def test_scan_series_season_resolves_and_validates_local_paths(tmp_path):
    f = tmp_path / "E01.mkv"
    f.write_text("x")
    c411 = FakeC411(tv_results=[_release("Breaking.Bad.S01.MULTI.VFF.2160p.WEBRip.x265-SQUEEZE")])
    result = scan_series_season(_season(remote_paths=[str(f)]), c411, path_mappings={})
    assert result.local_paths == [str(f)]
    assert result.path_resolved is True


def test_scan_series_season_reports_when_any_episode_path_is_missing(tmp_path):
    f = tmp_path / "E01.mkv"
    f.write_text("x")
    missing = str(tmp_path / "E02.mkv")
    c411 = FakeC411(tv_results=[])
    result = scan_series_season(_season(remote_paths=[str(f), missing]), c411, path_mappings={})
    assert result.path_resolved is False
    assert missing in result.path_error


def test_scan_series_season_falls_back_to_alternate_titles_when_primary_title_finds_nothing():
    """Incident reel : "White Collar" est diffuse en France sous le titre
    "FBI, duo tres special"."""
    c411 = FakeC411(
        tv_results=[],  # ID + titre original ("White Collar") : rien
        tv_query_results={
            "FBI, duo tres special": [
                _release("FBI.duo.tres.special.S01.MULTI.VFF.2160p.WEBRip.x265-TEAM")
            ],
        },
    )
    season = _season(title="White Collar", alternate_titles=["FBI, duo tres special"])
    result = scan_series_season(season, c411)

    assert ("tv", "White Collar", None, 1) in c411.calls
    assert ("tv", "FBI, duo tres special", None, 1) in c411.calls
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


def test_run_gapscan_only_movies_skips_series():
    """`only=` (retour utilisateur, 2026-08-27) : permet de scanner Radarr et
    Sonarr separement, pour repartir la charge sur plusieurs sessions
    (limite C411 confirmee : 15 requetes/min)."""
    c411 = FakeC411(movie_results=[], tv_results=[])
    results = run_gapscan(c411, radarr=_FakeRadarr(), sonarr=_FakeSonarr(), only="movies")
    assert {r.media_type for r in results} == {"movie"}
    assert not any(call[0] == "tv" for call in c411.calls)


def test_run_gapscan_only_series_skips_movies():
    c411 = FakeC411(movie_results=[], tv_results=[])
    results = run_gapscan(c411, radarr=_FakeRadarr(), sonarr=_FakeSonarr(), only="series")
    assert {r.media_type for r in results} == {"series"}
    assert not any(call[0] == "movie" for call in c411.calls)


def test_run_gapscan_reuses_previous_results_for_unchanged_covered_items():
    """Mode incremental de bout en bout : combine `previous_results` avec la
    bibliotheque Radarr+Sonarr (voir tests scan_movie/scan_series_season
    ci-dessus pour la logique unitaire)."""
    c411_first = FakeC411(
        movie_results=[_release("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ")], tv_results=[]
    )
    first_pass = run_gapscan(c411_first, radarr=_FakeRadarr(), sonarr=_FakeSonarr())

    c411_second = FakeC411()  # rien configure : un appel a tort renverrait ABSENT (revelateur)
    second_pass = run_gapscan(
        c411_second, radarr=_FakeRadarr(), sonarr=_FakeSonarr(), previous_results=first_pass
    )

    movie_result = next(r for r in second_pass if r.media_type == "movie")
    series_result = next(r for r in second_pass if r.media_type == "series")
    assert movie_result.status == GapStatus.COVERED  # repris tel quel, pas reinterroge
    assert ("movie", None, "tt0133093", "603") not in c411_second.calls
    assert series_result.status == GapStatus.ABSENT  # non couvert avant -> reinterroge normalement
    assert ("tv", None, "tt0903747", 1) in c411_second.calls


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
