"""Tests de nfogen.video_integrity (AUTOMATION.md, sous-projet 7 --
verification approfondie du fichier video). Meme convention que
tests/test_c411.py pour les tests necessitant un vrai ffmpeg."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading

import pytest

from nfogen import video_integrity
from nfogen.cancellation import OperationCancelled

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_video_integrity_report_defaults_to_empty_lists():
    report = video_integrity.VideoIntegrityReport(passed=True)
    assert report.errors == []
    assert report.warnings == []


def test_has_ffmpeg_reflects_environment():
    assert video_integrity.has_ffmpeg() == HAS_FFMPEG


# --------------------------------------------------------------------------- #
# verify_video_file() -- logique mockee (subprocess.Popen/_probe_streams)
# --------------------------------------------------------------------------- #
def _fake_ffprobe_json(duration="10.000000", video_start="0.000000", audio_start="0.000000"):
    return json.dumps({
        "streams": [
            {"codec_type": "video", "start_time": video_start, "duration": duration},
            {"codec_type": "audio", "start_time": audio_start, "duration": duration},
        ],
        "format": {"duration": duration},
    })


class _FakePopen:
    """Simule subprocess.Popen pour l'appel ffmpeg -- stdout produit des
    lignes 'out_time_ms=' comme -progress pipe:1, stderr/returncode
    configurables par test."""

    def __init__(self, out_time_ms_lines, returncode=0, stderr=""):
        self.stdout = iter([f"out_time_ms={v}\n" for v in out_time_ms_lines])
        self._stderr_text = stderr
        self._returncode = returncode
        self.terminated = False

    class _Stderr:
        def __init__(self, text):
            self._text = text

        def read(self):
            return self._text

    @property
    def stderr(self):
        return self._Stderr(self._stderr_text)

    @stderr.setter
    def stderr(self, value):
        pass

    def wait(self):
        return self._returncode

    def terminate(self):
        self.terminated = True


def test_verify_video_file_passes_when_decode_is_clean(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: json.loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[5_000_000, 10_000_000], returncode=0),
    )

    report = video_integrity.verify_video_file("clean.mkv")
    assert report.passed is True
    assert report.errors == []


def test_verify_video_file_fails_when_ffprobe_cannot_read_file(monkeypatch):
    def _raise(path):
        raise RuntimeError("moov atom not found")

    monkeypatch.setattr("nfogen.video_integrity._probe_streams", _raise)

    report = video_integrity.verify_video_file("broken.mkv")
    assert report.passed is False
    assert "ffprobe" in report.errors[0]
    assert "moov atom not found" in report.errors[0]


def test_verify_video_file_fails_on_decode_error_stderr(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: json.loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(
            out_time_ms_lines=[10_000_000], returncode=1,
            stderr="Error while decoding stream #0:0\n",
        ),
    )

    report = video_integrity.verify_video_file("corrupt.mkv")
    assert report.passed is False
    assert any("Error while decoding" in e for e in report.errors)


def test_verify_video_file_fails_when_truncated(monkeypatch):
    # Duree annoncee 10s, mais le decodage s'arrete a 3s -- ecart > 5s (tolerance).
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: json.loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[3_000_000], returncode=0),
    )

    report = video_integrity.verify_video_file("truncated.mkv")
    assert report.passed is False
    assert any("tronqué" in e for e in report.errors)


def test_verify_video_file_fails_when_av_desync(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: json.loads(
            _fake_ffprobe_json(duration="10.000000", video_start="0.000000", audio_start="1.200000")
        ),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[10_000_000], returncode=0),
    )

    report = video_integrity.verify_video_file("desync.mkv")
    assert report.passed is False
    assert any("Décalage audio/vidéo" in e for e in report.errors)


def test_verify_video_file_reports_progress(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: json.loads(_fake_ffprobe_json(duration="10.000000")),
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: _FakePopen(out_time_ms_lines=[5_000_000, 10_000_000], returncode=0),
    )
    seen: list[float] = []

    video_integrity.verify_video_file("clean.mkv", on_progress=seen.append)
    assert seen == [50.0, 99.0]


def test_verify_video_file_cancellation_terminates_process(monkeypatch):
    monkeypatch.setattr(
        "nfogen.video_integrity._probe_streams",
        lambda path: json.loads(_fake_ffprobe_json(duration="10.000000")),
    )
    fake_proc = _FakePopen(out_time_ms_lines=[1_000_000, 2_000_000, 3_000_000], returncode=0)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: fake_proc)

    cancel_event = threading.Event()
    cancel_event.set()  # deja annule avant meme de lire la premiere ligne

    with pytest.raises(OperationCancelled):
        video_integrity.verify_video_file("clean.mkv", cancel_event=cancel_event)
    assert fake_proc.terminated is True


# --------------------------------------------------------------------------- #
# verify_video_file() -- integration reelle (clip synthetique ffmpeg)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe requis")
def test_verify_video_file_real_clean_clip_passes(tmp_path):
    clip = tmp_path / "clean.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
        check=True,
    )
    report = video_integrity.verify_video_file(str(clip))
    assert report.passed is True


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe requis")
def test_verify_video_file_real_truncated_clip_fails(tmp_path):
    clip = tmp_path / "truncated.mkv"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
        check=True,
    )
    # Coupe le fichier a la moitie de ses octets -- simule un
    # telechargement incomplet (le conteneur annonce toujours 3s).
    data = clip.read_bytes()
    clip.write_bytes(data[: len(data) // 2])

    report = video_integrity.verify_video_file(str(clip))
    assert report.passed is False


# --------------------------------------------------------------------------- #
# verify_staged_media() -- agregation fichier/dossier
# --------------------------------------------------------------------------- #
def test_verify_staged_media_single_file_delegates_to_verify_video_file(monkeypatch, tmp_path):
    movie = tmp_path / "Movie.mkv"
    movie.write_bytes(b"x")
    captured = {}

    def fake_verify(path, *, on_progress=None, cancel_event=None):
        captured["path"] = path
        return video_integrity.VideoIntegrityReport(passed=True)

    monkeypatch.setattr("nfogen.video_integrity.verify_video_file", fake_verify)

    report = video_integrity.verify_staged_media(str(movie))
    assert report.passed is True
    assert captured["path"] == str(movie)


def test_verify_staged_media_directory_aggregates_all_video_files(monkeypatch, tmp_path):
    (tmp_path / "S05").mkdir()
    ep1 = tmp_path / "S05" / "ep01.mkv"
    ep2 = tmp_path / "S05" / "ep02.mkv"
    ep1.write_bytes(b"x")
    ep2.write_bytes(b"x")
    (tmp_path / "S05" / "readme.txt").write_text("pas une video")

    def fake_verify(path, *, on_progress=None, cancel_event=None):
        if path.endswith("ep02.mkv"):
            return video_integrity.VideoIntegrityReport(passed=False, errors=["corrompu"])
        return video_integrity.VideoIntegrityReport(passed=True)

    monkeypatch.setattr("nfogen.video_integrity.verify_video_file", fake_verify)

    report = video_integrity.verify_staged_media(str(tmp_path))
    assert report.passed is False
    assert any("ep02.mkv" in e and "corrompu" in e for e in report.errors)


def test_verify_staged_media_no_video_files_found(tmp_path):
    (tmp_path / "notes.txt").write_text("rien a voir")
    report = video_integrity.verify_staged_media(str(tmp_path))
    assert report.passed is False
    assert "Aucun fichier vidéo trouvé" in report.errors[0]
