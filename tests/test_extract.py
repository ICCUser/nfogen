"""Tests de nfogen.extract.extract_video_metadata (mediainfo mocke via
`pymediainfo.MediaInfo.parse`, aucun fichier/reseau reel)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from nfogen import extract


class _FakeTrack:
    def __init__(self, track_type: str, **attrs: Any) -> None:
        self.track_type = track_type
        for key, value in attrs.items():
            setattr(self, key, value)

    def __getattr__(self, name: str) -> Optional[Any]:
        # pymediainfo renvoie None (pas d'AttributeError) pour un attribut
        # absent de la piste -- meme comportement ici.
        return None


class _FakeMediaInfo:
    def __init__(self, tracks: list[_FakeTrack]) -> None:
        self.tracks = tracks


def _video_track() -> _FakeTrack:
    # bit_rate ET frame_rate presents : l'analyse rapide suffit, pas de
    # deuxieme parse en analyse complete (voir _needs_full_scan).
    return _FakeTrack("Video", bit_rate=8000000, frame_rate="23.976", height=1080, width=1920, format="HEVC")


def _mock_parse(monkeypatch: pytest.MonkeyPatch, tracks: list[_FakeTrack]) -> None:
    fake = _FakeMediaInfo(tracks)
    monkeypatch.setattr("pymediainfo.MediaInfo.parse", lambda *a, **k: fake)


def test_extract_video_metadata_returns_audio_tracks_detail(monkeypatch):
    audio = _FakeTrack(
        "Audio", language="fre", channel_s="5.1", format="AC-3",
        bit_rate=448000, sampling_rate=48000,
    )
    _mock_parse(monkeypatch, [_video_track(), audio])

    meta = extract.extract_video_metadata(Path("fake.mkv"))

    assert meta["audio_tracks"] == [
        {"language": "fre", "channels": "5.1", "codec": "AC-3", "bit_rate_kbps": 448, "sampling_khz": 48.0},
    ]


def test_extract_video_metadata_returns_subtitle_tracks_detail(monkeypatch):
    subtitle = _FakeTrack("Text", language="fre", forced="Yes")
    _mock_parse(monkeypatch, [_video_track(), subtitle])

    meta = extract.extract_video_metadata(Path("fake.mkv"))

    assert meta["subtitle_tracks"] == [{"language": "fre", "forced": True}]


def test_extract_video_metadata_subtitle_not_forced_defaults_false(monkeypatch):
    subtitle = _FakeTrack("Text", language="eng")  # pas d'attribut `forced` du tout
    _mock_parse(monkeypatch, [_video_track(), subtitle])

    meta = extract.extract_video_metadata(Path("fake.mkv"))

    assert meta["subtitle_tracks"] == [{"language": "eng", "forced": False}]


def test_extract_video_metadata_no_audio_or_subtitle_tracks(monkeypatch):
    _mock_parse(monkeypatch, [_video_track()])

    meta = extract.extract_video_metadata(Path("fake.mkv"))

    assert meta["audio_tracks"] == []
    assert meta["subtitle_tracks"] == []
