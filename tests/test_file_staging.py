"""Tests de nfogen.file_staging (mise en scene avant creation d'un
.torrent -- jamais le fichier original, voir AUTOMATION.md, sous-projet 2)."""
from __future__ import annotations

import errno
import os
import threading

import pytest

from nfogen.cancellation import OperationCancelled
from nfogen.file_staging import stage_file, stage_files


def test_stage_file_creates_a_hardlink_when_possible(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"

    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_text() == "contenu"
    # meme inode = hardlink reel, pas une copie (0 octet supplementaire)
    assert target.stat().st_ino == source.stat().st_ino


def test_stage_file_falls_back_to_copy_on_exdev(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_text() == "contenu"


def test_stage_file_reraises_other_os_errors(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "link", fake_link)
    with pytest.raises(OSError):
        stage_file(str(source), str(target))


def test_stage_files_stages_each_source_under_its_own_name(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_text("un")
    src2 = tmp_path / "e02.mkv"
    src2.write_text("deux")
    target_dir = tmp_path / "staged" / "Release.Name"

    results = stage_files([str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"])

    assert results == [str(target_dir / "E01.mkv"), str(target_dir / "E02.mkv")]
    assert (target_dir / "E01.mkv").read_text() == "un"
    assert (target_dir / "E02.mkv").read_text() == "deux"


def test_stage_file_hardlink_reports_progress_once(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"
    calls: list[tuple[int, int]] = []

    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert calls == [(len("contenu"), len("contenu"))]


def test_stage_file_copy_reports_progress_in_chunks(tmp_path, monkeypatch):
    import nfogen.file_staging as file_staging_module

    monkeypatch.setattr(file_staging_module, "_COPY_CHUNK_SIZE", 4)  # force plusieurs blocs
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")  # 10 octets, 4 par bloc -> 3 appels (4,4,2)
    target = tmp_path / "staged.mkv"
    calls: list[tuple[int, int]] = []

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert target.read_bytes() == b"0123456789"
    assert calls == [(4, 10), (8, 10), (10, 10)]


def test_stage_file_copy_cancellation_removes_partial_file_and_raises(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        stage_file(str(source), str(target), cancel_event=cancel_event)

    assert not target.exists()


def test_stage_files_aggregates_progress_across_multiple_files(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 20)
    target_dir = tmp_path / "staged" / "Release.Name"
    calls: list[tuple[int, int]] = []

    stage_files(
        [str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"],
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls[-1] == (30, 30)  # tout copie a la fin (hardlink, meme volume ici -- 2 appels au total)
    assert all(done <= total == 30 for done, total in calls)


def test_stage_files_propagates_cancellation_from_a_file_mid_pack(tmp_path, monkeypatch):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 10)
    target_dir = tmp_path / "staged" / "Release.Name"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        stage_files(
            [str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"], cancel_event=cancel_event
        )

    assert not (target_dir / "E01.mkv").exists()
    assert not (target_dir / "E02.mkv").exists()  # jamais tente, la boucle s'arrete au premier fichier
