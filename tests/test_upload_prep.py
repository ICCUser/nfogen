"""Tests de l'orchestration nommage -> mise en scene + torrent
(`nfogen/upload_prep.py`, AUTOMATION.md sous-projet 4)."""
from __future__ import annotations

from nfogen.upload_prep import group_by_team


def test_files_with_same_team_form_one_group():
    filenames = ["Show.S01E01.1080p.WEB.x264-TEAM.mkv", "Show.S01E02.1080p.WEB.x264-TEAM.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]


def test_files_with_different_teams_form_separate_groups():
    filenames = ["Show.S01E01.1080p.WEB.x264-TeamA.mkv", "Show.S01E02.1080p.WEB.x264-TeamB.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0], [1]]


def test_hint_takes_priority_over_filename_for_grouping():
    filenames = ["Show.S01E01.1080p.WEB.x264-FromFilename.mkv"]
    hints = ["Show S01E01 1080p WebDl x264 - FromHint"]
    groups = group_by_team(filenames, hints)
    # Le hint donne "FromHint", different du nom de fichier -- ne doit pas
    # se retrouver mélangé avec un fichier qui, lui, n'a que "FromFilename".
    other = ["Show.S01E02.1080p.WEB.x264-FromFilename.mkv"]
    combined = group_by_team(filenames + other, hints + [None])
    assert combined == [[0], [1]]


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
