"""Tests de nfogen.gapscan_results_store.

Persiste le dernier scan GapScan termine sur disque, pour qu'un redemarrage
du processus (ex. `scripts/update.sh`) ne fasse pas perdre des heures de
scan -- retour utilisateur (2026-08-26) : "a chaque MAJ je vais devoir
refaire un scan ? ... je vais pas tout rescanner c'est pas fou". Fichier
optionnel (NFOGEN_GAPSCAN_RESULTS_FILE, meme convention que
NFOGEN_GAPSCAN_CONFIG_FILE) : la persistance est une commodite, jamais un
motif d'echec pour le scan lui-meme.
"""
from __future__ import annotations

import stat
import sys

import pytest

from nfogen import gapscan_results_store as store
from nfogen.c411_client import C411Release
from nfogen.gapscan import GapResult, GapStatus
from nfogen.quality import build_quality


@pytest.fixture(autouse=True)
def _results_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_RESULTS_FILE", str(tmp_path / "gapscan_results.json"))


def _result(**overrides) -> GapResult:
    base = dict(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt0133093", tmdb_id="603", tvdb_id=None,
        status=GapStatus.COVERED,
        local_quality=build_quality("Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ"),
        c411_matches=[
            C411Release(
                title="Matrix.1999.MULTI.VFF.2160p.BluRay.x265-QTZ",
                guid="g1", link="https://c411.org/x", imdb_id="tt0133093",
                download_volume_factor=0.0,
            )
        ],
        has_freeleech_alternative=True,
    )
    base.update(overrides)
    return GapResult(**base)


def test_load_returns_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("NFOGEN_GAPSCAN_RESULTS_FILE", raising=False)
    assert store.load() is None


def test_load_returns_none_when_never_saved():
    assert store.load() is None


def test_save_then_load_roundtrips_results():
    saved = [_result()]
    store.save(saved)

    loaded = store.load()
    assert loaded is not None
    results, saved_at = loaded
    assert saved_at > 0
    assert len(results) == 1
    r = results[0]
    assert r.title == "Matrix"
    assert r.status == GapStatus.COVERED
    assert r.local_quality.resolution == 2160
    assert r.local_quality.languages == ["VF"] or r.local_quality.languages  # extrait du nom
    assert len(r.c411_matches) == 1
    assert r.c411_matches[0].imdb_id == "tt0133093"
    assert r.c411_matches[0].is_freeleech is True  # recalculee depuis download_volume_factor
    assert r.has_freeleech_alternative is True


def test_save_is_a_noop_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("NFOGEN_GAPSCAN_RESULTS_FILE", raising=False)
    store.save([_result()])  # ne doit pas lever, meme sans fichier configure
    assert list(tmp_path.iterdir()) == []


def test_save_overwrites_previous_content():
    store.save([_result(title="Old")])
    store.save([_result(title="New")])

    results, _ = store.load()
    assert [r.title for r in results] == ["New"]


def test_error_status_roundtrips():
    error_result = _result(status=GapStatus.ERROR, c411_matches=[], error="429 Too Many Requests")
    store.save([error_result])

    results, _ = store.load()
    assert results[0].status == GapStatus.ERROR
    assert results[0].error == "429 Too Many Requests"


@pytest.mark.skipif(sys.platform == "win32", reason="permissions POSIX non applicables sur Windows")
def test_save_sets_restrictive_permissions(tmp_path):
    store.save([_result()])
    mode = stat.S_IMODE((tmp_path / "gapscan_results.json").stat().st_mode)
    assert mode == 0o600
