"""Tests de nfogen.video_integrity (AUTOMATION.md, sous-projet 7 --
verification approfondie du fichier video). Meme convention que
tests/test_c411.py pour les tests necessitant un vrai ffmpeg."""
from __future__ import annotations

import shutil

import pytest

from nfogen import video_integrity

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_video_integrity_report_defaults_to_empty_lists():
    report = video_integrity.VideoIntegrityReport(passed=True)
    assert report.errors == []
    assert report.warnings == []


def test_has_ffmpeg_reflects_environment():
    assert video_integrity.has_ffmpeg() == HAS_FFMPEG
