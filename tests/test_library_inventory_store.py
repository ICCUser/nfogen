"""Tests de nfogen.library_inventory_store (persistance de l'inventaire
Bibliotheque -- meme patron que gapscan_results_store.py, mais un fichier
separe : voir docs/superpowers/specs/2026-09-12-library-inventory-cache-design.md)."""
from __future__ import annotations

from nfogen.gapscan_library import LibraryItem
from nfogen.quality import ReleaseQuality


def _sample_item() -> LibraryItem:
    return LibraryItem(
        media_type="movie", title="Inception", year=2010, season_number=None,
        imdb_id="tt1375666", tvdb_id=None, tmdb_id="27205",
        genres=["Science-Fiction"], added_at=1700000000.0,
        local_quality=ReleaseQuality(raw="x", resolution=1080, source="BluRay", codec="x264",
                                      languages=["fr"], multi=False, pure=False),
        radarr_movie_id=42, sonarr_series_id=None,
        already_processed=False, last_processed_at=None,
        key="[\"movie\", \"tt1375666\", \"27205\", \"Inception\", 2010]",
        status="covered", checked_at=1700000001.0,
        has_freeleech_alternative=False, has_double_upload_window=False, error=None,
        local_paths=["/media/Inception.mkv"], path_resolved=True, path_error=None,
        tracker_genre=None, team="TEAM", seed_match={"guid": "g1", "release_name": "Inception.2010.TEAM"},
        size_bytes=21474836480,
    )


def test_save_then_load_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "library_inventory.json"))
    from nfogen import library_inventory_store

    item = _sample_item()
    library_inventory_store.save([item], synced_at=1700000123.0)

    loaded = library_inventory_store.load()
    assert loaded is not None
    items, synced_at = loaded
    assert synced_at == 1700000123.0
    assert items == [item]


def test_is_configured_reflects_env_var(monkeypatch, tmp_path):
    from nfogen import library_inventory_store

    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    assert library_inventory_store.is_configured() is False

    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "x.json"))
    assert library_inventory_store.is_configured() is True


def test_load_returns_none_when_not_configured(monkeypatch):
    from nfogen import library_inventory_store

    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    assert library_inventory_store.load() is None


def test_load_returns_none_when_file_absent(monkeypatch, tmp_path):
    from nfogen import library_inventory_store

    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(tmp_path / "does-not-exist.json"))
    assert library_inventory_store.load() is None


def test_load_returns_none_on_corrupted_json(monkeypatch, tmp_path):
    from nfogen import library_inventory_store

    path = tmp_path / "library_inventory.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_LIBRARY_INVENTORY_FILE", str(path))
    assert library_inventory_store.load() is None


def test_save_is_a_noop_when_not_configured(monkeypatch):
    from nfogen import library_inventory_store

    monkeypatch.delenv("NFOGEN_LIBRARY_INVENTORY_FILE", raising=False)
    library_inventory_store.save([_sample_item()], synced_at=1700000000.0)  # ne doit pas lever
    assert library_inventory_store.load() is None
