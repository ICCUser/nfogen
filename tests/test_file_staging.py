"""Tests de nfogen.file_staging (mise en scene avant creation d'un
.torrent -- jamais le fichier original, voir AUTOMATION.md, sous-projet 2)."""
from __future__ import annotations

import errno
import os

import pytest

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
