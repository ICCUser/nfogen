"""Tests de nfogen.torrent_builder (creation du .torrent final, regles
C411 -- voir AUTOMATION.md, sous-projet 2)."""
from __future__ import annotations

import torf

from nfogen.torrent_builder import build_torrent, piece_size_for

_MO = 1024**2
_GO = 1024**3


def test_piece_size_for_under_1go():
    assert piece_size_for(500 * _MO) == 1 * _MO


def test_piece_size_for_under_2go():
    assert piece_size_for(1500 * _MO) == 2 * _MO


def test_piece_size_for_under_3go():
    assert piece_size_for(int(2.5 * _GO)) == 4 * _MO


def test_piece_size_for_under_8go():
    assert piece_size_for(5 * _GO) == 8 * _MO


def test_piece_size_for_8go_or_more():
    assert piece_size_for(10 * _GO) == 16 * _MO


def test_piece_size_for_exactly_at_a_threshold_uses_the_next_tier():
    # "< 1 Go" exclut 1 Go pile -- tombe dans le palier suivant.
    assert piece_size_for(1 * _GO) == 2 * _MO


def test_build_torrent_creates_a_valid_private_torrent(tmp_path):
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * 100)
    output = tmp_path / "output.torrent"

    build_torrent(str(staged), "https://c411.org/announce/SECRET", str(output))

    assert output.is_file()
    reloaded = torf.Torrent.read(str(output))
    assert reloaded.private is True
    assert any("https://c411.org/announce/SECRET" in tier for tier in reloaded.trackers)
    assert reloaded.piece_size == piece_size_for(100)


def test_build_torrent_supports_a_directory_for_multi_file_packs(tmp_path):
    staged_dir = tmp_path / "Release.Name"
    staged_dir.mkdir()
    (staged_dir / "E01.mkv").write_bytes(b"x" * 100)
    (staged_dir / "E02.mkv").write_bytes(b"y" * 100)
    output = tmp_path / "output.torrent"

    build_torrent(str(staged_dir), "https://c411.org/announce/SECRET", str(output))

    assert output.is_file()
    reloaded = torf.Torrent.read(str(output))
    assert reloaded.private is True
    assert reloaded.piece_size == piece_size_for(200)
