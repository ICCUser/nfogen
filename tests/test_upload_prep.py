"""Tests de l'orchestration nommage -> mise en scene + torrent
(`nfogen/upload_prep.py`, AUTOMATION.md sous-projet 4)."""
from __future__ import annotations

from pathlib import Path as _Path
from unittest.mock import patch

import pytest

from nfogen.upload_prep import CommitResult, ProposedFile, commit_upload, group_by_team, preview_upload


def test_files_with_same_team_form_one_group():
    filenames = ["Show.S01E01.1080p.WEB.x264-TEAM.mkv", "Show.S01E02.1080p.WEB.x264-TEAM.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]


def test_files_with_different_teams_form_separate_groups():
    filenames = ["Show.S01E01.1080p.WEB.x264-TeamA.mkv", "Show.S01E02.1080p.WEB.x264-TeamB.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0], [1]]


def test_hint_takes_priority_over_filename_for_grouping():
    # Le hint donne "FromHint", different du nom de fichier -- ne doit pas
    # se retrouver mélangé avec un fichier qui, lui, n'a que "FromFilename".
    filenames = [
        "Show.S01E01.1080p.WEB.x264-FromFilename.mkv",
        "Show.S01E02.1080p.WEB.x264-FromFilename.mkv",
    ]
    hints = ["Show S01E01 1080p WebDl x264 - FromHint", None]
    groups = group_by_team(filenames, hints)
    assert groups == [[0], [1]]


def test_files_with_no_detectable_team_form_their_own_group():
    filenames = ["random_clip_one.mkv", "random_clip_two.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]  # les deux "None" forment un seul groupe ensemble


def test_group_order_matches_first_appearance():
    filenames = [
        "Show.S01E01.1080p.WEB.x264-TeamB.mkv",
        "Show.S01E02.1080p.WEB.x264-TeamA.mkv",
        "Show.S01E03.1080p.WEB.x264-TeamB.mkv",
    ]
    groups = group_by_team(filenames, [None, None, None])
    assert groups == [[0, 2], [1]]


def test_empty_input_returns_no_groups():
    assert group_by_team([], []) == []


def _fake_metadata(**overrides):
    base = {
        "video_height": None, "video_width": None, "video_format": None,
        "video_bit_rate": None, "frame_rate": None,
        "audio_languages": [], "subtitle_languages": [], "general_title": None,
    }
    base.update(overrides)
    return base


def test_single_movie_file_proposes_a_name_and_matching_staged_file():
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(["/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"])
    assert len(proposals) == 1
    group = proposals[0]
    assert group.blocked is False
    assert group.release_name is not None
    assert group.release_name.startswith("Kaamelott")
    assert len(group.files) == 1
    assert group.files[0].source_path == "/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"
    assert group.files[0].staged_name == f"{group.release_name}.mkv"


def test_season_pack_same_team_produces_one_group_with_per_file_names():
    paths = [
        "/media/One.Piece.S01E01.MULTI.VFF.1080p.WEB.AC3.x264-NOTAG.mkv",
        "/media/One.Piece.S01E02.MULTI.VFF.1080p.WEB.AC3.x264-NOTAG.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    group = proposals[0]
    assert group.release_name is not None
    assert ".S01." in group.release_name  # identifiant de pack, pas par-episode
    assert len(group.files) == 2
    assert "S01E01" in group.files[0].staged_name
    assert "S01E02" in group.files[1].staged_name
    # Le nom de pack sert de prefixe coherent sur chaque fichier individuel.
    assert group.files[0].staged_name.startswith("One.Piece")


def test_multi_team_pack_splits_into_separate_groups():
    paths = [
        "/media/Show.S01E01.1080p.WEB.x264-TeamA.mkv",
        "/media/Show.S01E02.1080p.WEB.x264-TeamB.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 2
    release_names = {p.release_name for p in proposals}
    assert any(name and name.endswith("-TeamA") for name in release_names)
    assert any(name and name.endswith("-TeamB") for name in release_names)


def test_ambiguous_group_is_blocked_with_no_files():
    """Deux saisons differentes AVEC le meme tag d'equipe : group_by_team ne
    les separe pas (meme equipe), mais name_proposal refuse toujours ce cas
    (saisons incoherentes) -- le groupe est marque bloque plutot que de
    deviner laquelle utiliser."""
    paths = ["/media/Show.S01E01.1080p.WEB.x264-TEAM.mkv", "/media/Show.S02E01.1080p.WEB.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert proposals[0].blocked is True
    assert proposals[0].release_name is None
    assert proposals[0].files == []
    assert any("saisons" in w for w in proposals[0].warnings)


def test_extraction_failure_for_one_file_does_not_crash():
    def fake_extract(source):
        if "corrupt" in str(source):
            raise RuntimeError("libmediainfo: fichier illisible")
        return _fake_metadata()

    paths = ["/media/corrupt.S01E01.1080p.WEB.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", side_effect=fake_extract):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert any("illisible" in w.lower() or "métadonnées" in w.lower() for w in proposals[0].warnings)
    assert proposals[0].release_name is not None  # l'echec d'extraction n'empeche pas le nommage


def test_upscale_warning_surfaces_through_real_c411_validator():
    """Preuve du cablage complet : preview_upload() reutilise le VRAI
    validateur du profil C411 (cross_checks + upscale_checks), sans aucune
    logique dupliquee ici."""
    meta = _fake_metadata(
        video_height=1080, video_width=1920, video_bit_rate=1_500_000, frame_rate=24.0,
    )
    paths = ["/media/Movie.2020.VFF.1080p.BluRay.AC3.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=meta):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert any("upscale" in w.lower() for w in proposals[0].warnings)
    assert proposals[0].blocked is False  # avertissement, jamais bloquant


def test_name_with_no_detectable_codec_is_blocked_by_real_validator():
    """Le nom propose ne respecte pas la convention C411 (codec video
    obligatoire absent) -- le vrai validateur du profil le refuse, le
    groupe est bloque plutot que mis en scene avec un nom invalide."""
    paths = ["/media/nom_totalement_generique.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert proposals[0].blocked is True


def test_empty_local_paths_returns_empty_list():
    assert preview_upload([]) == []


def _make_source(tmp_path, name: str, content: bytes = b"contenu de test") -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_commit_single_file_stages_and_builds_torrent(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_c411_announce_url",
        lambda: "https://c411.example/announce/abc123",
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files)

    assert isinstance(result, CommitResult)
    assert result.staged_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.mkv")
    assert _Path(result.staged_path).is_file()
    assert result.torrent_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.torrent")
    assert _Path(result.torrent_path).is_file()


def test_commit_multi_file_group_stages_into_a_folder(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_c411_announce_url",
        lambda: "https://c411.example/announce/abc123",
    )
    files = [
        ProposedFile(source_path=_make_source(tmp_path, "e01.mkv"), staged_name="Show.S01E01-TEAM.mkv"),
        ProposedFile(source_path=_make_source(tmp_path, "e02.mkv"), staged_name="Show.S01E02-TEAM.mkv"),
    ]

    result = commit_upload("Show.S01-TEAM", files)

    pack_dir = staging_dir / "Show.S01-TEAM"
    assert result.staged_path == str(pack_dir)
    assert (pack_dir / "Show.S01E01-TEAM.mkv").is_file()
    assert (pack_dir / "Show.S01E02-TEAM.mkv").is_file()
    assert _Path(result.torrent_path).is_file()


def test_commit_without_staging_dir_configured_raises(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: None)
    with pytest.raises(ValueError, match="scène"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


def test_commit_without_announce_url_configured_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_c411_announce_url", lambda: None
    )
    with pytest.raises(ValueError, match="annonce"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


def test_commit_without_automation_extra_raises(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep._TORRENT_BUILDER_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="automation"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])
