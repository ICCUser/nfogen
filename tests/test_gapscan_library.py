"""Tests de nfogen.gapscan_library (AUTOMATION.md, sous-projet 8) --
inventaire local, ZERO appel tracker."""
from __future__ import annotations

import pytest

from nfogen import gapscan_library, upload_history_store
from nfogen.gapscan import GapResult, GapStatus, movie_key, series_key
from nfogen.gapscan_library import detect_season_packs, find_result_by_key
from nfogen.quality import ReleaseQuality
from nfogen.radarr_client import RadarrMovieFile
from nfogen.sonarr_client import SonarrSeasonFile
from nfogen.torznab_client import TorznabRelease


class _FakeRadarr:
    def __init__(self, movies):
        self._movies = movies
        self.list_movie_files_called = 0

    def list_movie_files(self):
        self.list_movie_files_called += 1
        return self._movies


class _FakeSonarr:
    def __init__(self, seasons):
        self._seasons = seasons

    def list_season_files(self):
        return self._seasons


@pytest.fixture(autouse=True)
def history_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))


def test_list_library_never_touches_c411():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    radarr = _FakeRadarr([movie])
    items = gapscan_library.list_library(radarr=radarr, sonarr=None)
    assert len(items) == 1
    assert radarr.list_movie_files_called == 1


def test_list_library_builds_movie_item_with_selection_key():
    movie = RadarrMovieFile(
        movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1,
        genres=["Action"],
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    item = items[0]
    assert item.media_type == "movie"
    assert item.title == "Movie"
    assert item.genres == ["Action"]
    assert item.radarr_movie_id == 1
    assert item.key == upload_history_store.key_str(movie_key("tt001", "1", "Movie", 2020))


def test_list_library_exposes_size_bytes_for_movie_and_series():
    """Retour utilisateur, 2026-09-09 : colonne "Taille" manquante dans la
    Bibliotheque -- la donnee etait deja calculee (RadarrMovieFile.
    size_bytes / SonarrSeasonFile.size_bytes, ajoutes pour _compute_seed_match)
    mais jamais exposee sur LibraryItem lui-meme."""
    movie = RadarrMovieFile(
        movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1, size_bytes=4_500_000_000,
    )
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10, size_bytes=9_000_000_000,
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=_FakeSonarr([season]))
    movie_item = next(i for i in items if i.media_type == "movie")
    season_item = next(i for i in items if i.media_type == "series")
    assert movie_item.size_bytes == 4_500_000_000
    assert season_item.size_bytes == 9_000_000_000


def test_list_library_extracts_team_from_movie_scene_name():
    """Retour utilisateur, 2026-09-08 : afficher le tag d'equipe par ligne
    dans la Bibliotheque -- meme extraction que celle deja utilisee dans
    upload_prep.py (name_proposal.extract_team_tag)."""
    movie = RadarrMovieFile(
        movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1,
        scene_name="Movie.2020.MULTI.VFF.1080p.BluRay.x264-TEAM",
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].team == "TEAM"


def test_list_library_team_none_when_no_tag_detected():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].team is None


def test_list_library_extracts_team_from_series_scene_name():
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=5, episode_file_count=10,
        scene_name="Show.S05.MULTI.VFF.1080p.WEB.AAC.2.0.x265-Frosties",
    )
    items = gapscan_library.list_library(radarr=None, sonarr=_FakeSonarr([season]))
    assert items[0].team == "Frosties"


def test_list_library_marks_already_processed_movie():
    movie = RadarrMovieFile(movie_id=42, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    upload_history_store.record(
        upload_history_store.processed_key("movie", 42, None), kind="committed", release_name="r",
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].already_processed is True
    assert items[0].last_processed_at is not None


def test_list_library_marks_series_season_not_processed_by_default():
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    items = gapscan_library.list_library(radarr=None, sonarr=_FakeSonarr([season]))
    assert items[0].already_processed is False
    assert items[0].last_processed_at is None
    assert items[0].key == upload_history_store.key_str(series_key(99, None, "Show", 1))


def test_list_library_exposes_tmdb_id_for_series():
    """Sonarr expose un `tmdbId` par cross-reference (confirme en
    conditions reelles, 2026-09-06) : `tmdb_id=None` etait cable en dur
    ici a tort pour toute serie."""
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10, tmdb_id=63174,
    )
    items = gapscan_library.list_library(radarr=None, sonarr=_FakeSonarr([season]))
    assert items[0].tmdb_id == "63174"


def test_list_library_combines_movies_and_series():
    movie = RadarrMovieFile(movie_id=1, title="Movie", year=2020, imdb_id="tt001", tmdb_id=1)
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=_FakeSonarr([season]))
    assert len(items) == 2
    assert {i.media_type for i in items} == {"movie", "series"}


def test_list_library_empty_without_any_client():
    assert gapscan_library.list_library(radarr=None, sonarr=None) == []


# --------------------------------------------------------------------------- #
# Fusion Bibliotheque/Scan (AUTOMATION.md, sous-projet 8 -- retour utilisateur
# 2026-09-06 : les deux pages faisaient doublon) -- previous_results enrichit
# chaque item du statut tracker DEJA CONNU, sans jamais reinterroger C411 ici.
# --------------------------------------------------------------------------- #
def test_list_library_enriches_movie_with_known_tracker_status():
    movie = RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)
    previous = GapResult(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt0133093", tmdb_id="603", tvdb_id=None, status=GapStatus.ABSENT,
        local_quality=ReleaseQuality(raw=""), checked_at=1700000000.0,
        has_freeleech_alternative=True, has_double_upload_window=False,
        local_paths=["/media/matrix.mkv"], path_resolved=True,
    )

    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].status == "absent"
    assert items[0].checked_at == 1700000000.0
    assert items[0].has_freeleech_alternative is True
    assert items[0].local_paths == ["/media/matrix.mkv"]
    assert items[0].path_resolved is True


def test_list_library_status_is_none_when_never_scanned():
    movie = RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)
    items = gapscan_library.list_library(radarr=_FakeRadarr([movie]), sonarr=None)
    assert items[0].status is None
    assert items[0].checked_at is None
    assert items[0].has_freeleech_alternative is False
    assert items[0].local_paths == []
    assert items[0].path_resolved is False


def test_list_library_does_not_match_previous_result_of_a_different_title():
    movie = RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)
    previous = GapResult(
        media_type="movie", title="Inception", year=2010, season_number=None,
        imdb_id="tt1375666", tmdb_id="27205", tvdb_id=None, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(raw=""),
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )
    assert items[0].status is None


def test_list_library_enriches_series_season_with_known_tracker_status():
    season = SonarrSeasonFile(
        series_id=7, title="Show", year=2019, tvdb_id=99, imdb_id=None,
        season_number=1, episode_file_count=10,
    )
    previous = GapResult(
        media_type="series", title="Show", year=2019, season_number=1,
        imdb_id=None, tmdb_id=None, tvdb_id=99, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(raw=""),
    )
    items = gapscan_library.list_library(
        radarr=None, sonarr=_FakeSonarr([season]), previous_results=[previous],
    )
    assert items[0].status == "covered"


def test_list_library_computes_tracker_genre_from_matched_result(monkeypatch):
    """`tracker_genre` (categorie C411 du match trouve) est DISTINCT de
    `genres` (Radarr/Sonarr) -- les deux classifications restent
    independantes (voir la spec du sous-projet 8)."""
    from nfogen.torznab_client import TorznabRelease

    movie = RadarrMovieFile(movie_id=1, title="Naruto", year=2002, imdb_id="tt0409591", tmdb_id=46260)
    previous = GapResult(
        media_type="movie", title="Naruto", year=2002, season_number=None,
        imdb_id="tt0409591", tmdb_id="46260", tvdb_id=None, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(raw=""),
        c411_matches=[
            TorznabRelease(title="Naruto", guid="g", link="https://c411.org/x", category="anime-movie"),
        ],
    )
    monkeypatch.setattr(
        "nfogen.tracker_profile.torznab_categories",
        lambda profile: {"anime": ["anime-movie"], "documentaire": []},
    )

    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous], profile="c411",
    )

    assert items[0].tracker_genre == "anime"


# --------------------------------------------------------------------------- #
# detect_season_packs (retour utilisateur, 2026-09-08) : runs de saisons
# consecutives d'une meme serie partageant la meme equipe.
# --------------------------------------------------------------------------- #
def _series_item(
    season_number, team, sonarr_series_id=7, title="Lucifer", year=2016, path_resolved=True, key=None,
    already_processed=False,
):
    return gapscan_library.LibraryItem(
        media_type="series", title=title, year=year, season_number=season_number,
        imdb_id=None, tvdb_id=99, tmdb_id=None, genres=[], added_at=None,
        local_quality=ReleaseQuality(raw=""),
        radarr_movie_id=None, sonarr_series_id=sonarr_series_id,
        already_processed=already_processed, last_processed_at=None,
        key=key or f"key-{sonarr_series_id}-s{season_number}",
        path_resolved=path_resolved,
        local_paths=[f"/media/Show/S{season_number:02d}/ep1.mkv"] if path_resolved else [],
        team=team,
    )


def test_detect_season_packs_groups_consecutive_seasons_same_team():
    items = [_series_item(5, "Frosties"), _series_item(6, "Frosties")]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [5, 6]
    assert suggestions[0].team == "Frosties"
    assert suggestions[0].is_full_series is True  # seules saisons connues = 5,6


def test_detect_season_packs_breaks_run_on_different_team():
    items = [_series_item(1, "TeamA"), _series_item(2, "TeamA"), _series_item(3, "TeamB")]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [1, 2]
    assert suggestions[0].is_full_series is False  # saison 3 existe mais TeamB


def test_detect_season_packs_never_proposes_a_lone_season():
    items = [_series_item(1, "TEAM"), _series_item(3, "TEAM")]  # non consecutives
    suggestions = detect_season_packs(items)
    assert suggestions == []


def test_detect_season_packs_never_merges_different_series():
    items = [
        _series_item(1, "TEAM", sonarr_series_id=1, title="A", key="a1"),
        _series_item(1, "TEAM", sonarr_series_id=2, title="B", key="b1"),
    ]
    assert detect_season_packs(items) == []  # une seule saison chacune, jamais fusionnees entre series


def test_detect_season_packs_excludes_seasons_without_team_or_unresolved_path():
    items = [_series_item(1, None), _series_item(2, "TEAM"), _series_item(3, "TEAM")]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [2, 3]
    assert suggestions[0].is_full_series is False  # saison 1 existe (meme sans team), donc pas INTEGRALE


def test_detect_season_packs_excludes_already_processed_seasons():
    """Bug reel signale par l'utilisateur (2026-09-09) : un pack deja
    envoye au tracker (already_processed=True sur ses saisons) restait
    suggere indefiniment dans "Packs disponibles", sans jamais pouvoir
    disparaitre une fois traite."""
    items = [
        _series_item(1, "TEAM", already_processed=True),
        _series_item(2, "TEAM", already_processed=True),
    ]
    assert detect_season_packs(items) == []


def test_detect_season_packs_still_proposes_the_not_yet_processed_remainder():
    """Un pack partiellement traite (ex. S01-S02 deja envoyes) doit
    continuer a proposer les saisons RESTANTES (S03-S05), pas disparaitre
    entierement ni les regrouper avec les saisons deja traitees."""
    items = [
        _series_item(1, "TEAM", already_processed=True),
        _series_item(2, "TEAM", already_processed=True),
        _series_item(3, "TEAM", already_processed=False),
        _series_item(4, "TEAM", already_processed=False),
    ]
    suggestions = detect_season_packs(items)
    assert len(suggestions) == 1
    assert suggestions[0].season_numbers == [3, 4]


# --------------------------------------------------------------------------- #
# seed_match (retour utilisateur, 2026-09-09) : proposer un seed sans
# re-upload quand le fichier local correspond EXACTEMENT a une release
# C411 deja connue via un scan precedent (previous_results).
# --------------------------------------------------------------------------- #
def _covered_movie_previous(c411_matches):
    return GapResult(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt0133093", tmdb_id="603", tvdb_id=None, status=GapStatus.COVERED,
        local_quality=ReleaseQuality(
            raw="", resolution=1080, source="BLURAY", codec="X264", languages=["VFF"], multi=True,
        ),
        c411_matches=c411_matches,
        local_paths=["/data/movies/Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM.mkv"],
        path_resolved=True,
    )


def test_gapscan_library_exposes_seed_match_when_exact_candidate_found():
    """La taille locale vient de RadarrMovieFile.size_bytes (rapportee par
    Radarr), JAMAIS d'un os.path.getsize() sur le fichier -- incident reel
    de performance (retour utilisateur, 2026-09-09), voir _compute_seed_match.
    Ce test ne cree donc plus aucun fichier reel sur disque."""
    previous = _covered_movie_previous(
        c411_matches=[
            TorznabRelease(
                title="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM", guid="guid-1",
                link="https://c411.org/torrents/x", size=1_000_000,
            )
        ],
    )

    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        scene_name="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM", size_bytes=1_000_000,
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].seed_match == {
        "guid": "guid-1", "release_name": "Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM",
    }


def test_gapscan_library_seed_match_none_when_not_covered():
    previous = _covered_movie_previous(c411_matches=[])
    previous.status = GapStatus.ABSENT

    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        scene_name="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM",
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].seed_match is None


def test_gapscan_library_seed_match_none_when_path_not_resolved():
    previous = _covered_movie_previous(
        c411_matches=[
            TorznabRelease(
                title="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM", guid="guid-1",
                link="https://c411.org/torrents/x", size=1_000_000,
            )
        ],
    )
    previous.path_resolved = False

    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        scene_name="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM",
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].seed_match is None


def test_gapscan_library_seed_match_none_when_no_exact_candidate():
    local_paths = ["/data/movies/Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM.mkv"]
    previous = _covered_movie_previous(
        c411_matches=[
            TorznabRelease(
                title="Matrix.1999.MULTI.VFF.2160p.BluRay.x264-TEAM", guid="guid-1",
                link="https://c411.org/torrents/x", size=1_000_000,
            )
        ],
    )
    previous.local_paths = local_paths

    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        scene_name="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM", size_bytes=1_000_000,
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].seed_match is None


def test_gapscan_library_seed_match_none_when_size_unknown():
    """Radarr n'a pas rapporte de taille (`size_bytes` absent) : jamais de
    proposition de seed, meme si tout le reste correspondrait -- pas de
    fallback vers un stat() disque (voir _compute_seed_match)."""
    previous = _covered_movie_previous(
        c411_matches=[
            TorznabRelease(
                title="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM", guid="guid-1",
                link="https://c411.org/torrents/x", size=1_000_000,
            )
        ],
    )

    movie = RadarrMovieFile(
        movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603,
        scene_name="Matrix.1999.MULTI.VFF.1080p.BluRay.x264-TEAM",
    )
    items = gapscan_library.list_library(
        radarr=_FakeRadarr([movie]), sonarr=None, previous_results=[previous],
    )

    assert items[0].seed_match is None


def test_find_result_by_key_returns_matching_result():
    result = _covered_movie_previous(c411_matches=[])
    key = upload_history_store.key_str(movie_key("tt0133093", "603", "Matrix", 1999))
    assert find_result_by_key(key, [result]) is result


def test_find_result_by_key_returns_none_when_absent():
    assert find_result_by_key("does-not-exist", []) is None


# --------------------------------------------------------------------------- #
# sort_library_items (retour utilisateur, 2026-09-09) : tri sur toute la
# bibliotheque filtree, applique AVANT pagination cote endpoint.
# --------------------------------------------------------------------------- #
def _library_item(**overrides):
    base = dict(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt1", tvdb_id=None, tmdb_id="1", genres=[], added_at=None,
        local_quality=ReleaseQuality(raw=""), radarr_movie_id=1, sonarr_series_id=None,
        already_processed=False, last_processed_at=None, key="k1",
    )
    base.update(overrides)
    return gapscan_library.LibraryItem(**base)


def test_sort_library_items_by_title_ascending():
    b = _library_item(title="Beta", key="b")
    a = _library_item(title="Alpha", key="a")
    result = gapscan_library.sort_library_items([b, a], "title", "asc")
    assert [i.key for i in result] == ["a", "b"]


def test_sort_library_items_by_title_descending():
    a = _library_item(title="Alpha", key="a")
    b = _library_item(title="Beta", key="b")
    result = gapscan_library.sort_library_items([a, b], "title", "desc")
    assert [i.key for i in result] == ["b", "a"]


def test_sort_library_items_by_quality_uses_resolution():
    low = _library_item(key="low", local_quality=ReleaseQuality(raw="", resolution=1080))
    high = _library_item(key="high", local_quality=ReleaseQuality(raw="", resolution=2160))
    unknown = _library_item(key="unknown", local_quality=ReleaseQuality(raw="", resolution=None))
    result = gapscan_library.sort_library_items([high, low, unknown], "quality", "asc")
    assert [i.key for i in result] == ["unknown", "low", "high"]


def test_sort_library_items_by_added_at_none_first_ascending():
    known = _library_item(key="known", added_at=1_000_000.0)
    unknown = _library_item(key="unknown", added_at=None)
    result = gapscan_library.sort_library_items([known, unknown], "added_at", "asc")
    assert [i.key for i in result] == ["unknown", "known"]


def test_sort_library_items_by_size_bytes_unknown_first_ascending():
    small = _library_item(key="small", size_bytes=1_000_000)
    big = _library_item(key="big", size_bytes=9_000_000)
    unknown = _library_item(key="unknown", size_bytes=None)
    result = gapscan_library.sort_library_items([big, small, unknown], "size_bytes", "asc")
    assert [i.key for i in result] == ["unknown", "small", "big"]


def test_sort_library_items_unknown_sort_returns_items_unchanged():
    a = _library_item(key="a")
    b = _library_item(key="b")
    result = gapscan_library.sort_library_items([a, b], "bogus", "asc")
    assert result == [a, b]


def test_sort_library_items_none_sort_returns_items_unchanged():
    a = _library_item(key="a")
    b = _library_item(key="b")
    result = gapscan_library.sort_library_items([a, b], None, "asc")
    assert result == [a, b]
