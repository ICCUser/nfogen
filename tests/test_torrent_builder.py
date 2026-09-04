"""Tests de nfogen.torrent_builder (creation du .torrent final -- voir
AUTOMATION.md, sous-projet 2). Le bareme de taille de piece est fourni par
l'appelant (voir tracker_profile.torrent_piece_sizes, sous-projet 4b) --
ce module reste agnostique du tracker, aucune table en dur ici."""
from __future__ import annotations

import threading

import pytest
import torf

from nfogen.cancellation import OperationCancelled
from nfogen.torrent_builder import build_torrent, piece_size_for

_MO = 1024**2
_GO = 1024**3

_C411_PIECE_SIZES = [
    {"max_bytes": 1 * _GO, "piece_size": 1 * _MO},
    {"max_bytes": 2 * _GO, "piece_size": 2 * _MO},
    {"max_bytes": 3 * _GO, "piece_size": 4 * _MO},
    {"max_bytes": 8 * _GO, "piece_size": 8 * _MO},
    {"piece_size": 16 * _MO},
]


def test_piece_size_for_under_1go():
    assert piece_size_for(500 * _MO, _C411_PIECE_SIZES) == 1 * _MO


def test_piece_size_for_under_2go():
    assert piece_size_for(1500 * _MO, _C411_PIECE_SIZES) == 2 * _MO


def test_piece_size_for_under_3go():
    assert piece_size_for(int(2.5 * _GO), _C411_PIECE_SIZES) == 4 * _MO


def test_piece_size_for_under_8go():
    assert piece_size_for(5 * _GO, _C411_PIECE_SIZES) == 8 * _MO


def test_piece_size_for_8go_or_more():
    assert piece_size_for(10 * _GO, _C411_PIECE_SIZES) == 16 * _MO


def test_piece_size_for_exactly_at_a_threshold_uses_the_next_tier():
    # "< 1 Go" exclut 1 Go pile -- tombe dans le palier suivant.
    assert piece_size_for(1 * _GO, _C411_PIECE_SIZES) == 2 * _MO


def test_piece_size_for_raises_on_an_empty_table():
    # Bareme non declare pour ce profil (tracker_profile.torrent_piece_sizes
    # renvoie []) : erreur claire plutot qu'une taille devinee.
    with pytest.raises(ValueError, match="[Bb]ar[eè]me"):
        piece_size_for(500 * _MO, [])


def test_build_torrent_creates_a_valid_private_torrent(tmp_path):
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * 100)
    output = tmp_path / "output.torrent"

    build_torrent(str(staged), "https://c411.org/announce/SECRET", str(output), _C411_PIECE_SIZES)

    assert output.is_file()
    reloaded = torf.Torrent.read(str(output))
    assert reloaded.private is True
    assert any("https://c411.org/announce/SECRET" in tier for tier in reloaded.trackers)
    assert reloaded.piece_size == piece_size_for(100, _C411_PIECE_SIZES)


def test_build_torrent_supports_a_directory_for_multi_file_packs(tmp_path):
    staged_dir = tmp_path / "Release.Name"
    staged_dir.mkdir()
    (staged_dir / "E01.mkv").write_bytes(b"x" * 100)
    (staged_dir / "E02.mkv").write_bytes(b"y" * 100)
    output = tmp_path / "output.torrent"

    build_torrent(str(staged_dir), "https://c411.org/announce/SECRET", str(output), _C411_PIECE_SIZES)

    assert output.is_file()
    reloaded = torf.Torrent.read(str(output))
    assert reloaded.private is True
    assert reloaded.piece_size == piece_size_for(200, _C411_PIECE_SIZES)


_MIN_PIECE_SIZE = 16 * 1024  # torf exige un multiple de 16 KiB


def test_build_torrent_reports_progress_as_pieces_are_hashed(tmp_path):
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * (4 * _MIN_PIECE_SIZE))  # exactement 4 pieces
    output = tmp_path / "output.torrent"
    calls: list[tuple[int, int]] = []

    build_torrent(
        str(staged), "https://c411.org/announce/SECRET", str(output), [{"piece_size": _MIN_PIECE_SIZE}],
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls  # au moins un appel
    assert calls[-1] == (4, 4)
    assert all(done <= total == 4 for done, total in calls)
    assert output.is_file()


def test_build_torrent_cancellation_stops_hashing_and_writes_nothing(tmp_path):
    """threads=1 (hachage sequentiel, une seule piece a la fois) rend
    l'annulation deterministe : sans ca, torf peut distribuer un petit
    nombre de pieces sur plusieurs threads et les hacher toutes avant le
    premier appel du callback -- flaky reel observe en CI (2026-09-04),
    le job se terminait "avec succes" malgre cancel_event deja positionne."""
    staged = tmp_path / "Release.Name.mkv"
    staged.write_bytes(b"x" * (16 * _MIN_PIECE_SIZE))  # assez de pieces pour laisser le temps d'intercepter
    output = tmp_path / "output.torrent"
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        build_torrent(
            str(staged), "https://c411.org/announce/SECRET", str(output), [{"piece_size": _MIN_PIECE_SIZE}],
            cancel_event=cancel_event, threads=1,
        )

    assert not output.exists()
