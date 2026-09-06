"""Tests de nfogen.upload_history_store (AUTOMATION.md, sous-projet 8)."""
from __future__ import annotations

import json

import pytest

from nfogen import upload_history_store


@pytest.fixture(autouse=True)
def history_file(tmp_path, monkeypatch):
    path = tmp_path / "upload_history.json"
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(path))
    return path


def test_processed_key_for_movie():
    assert upload_history_store.processed_key("movie", 42, None) == ("movie", 42)


def test_processed_key_for_series_includes_season():
    assert upload_history_store.processed_key("series", None, 7, season_number=3) == ("series", 7, 3)


def test_processed_key_returns_none_without_usable_identifier():
    assert upload_history_store.processed_key("movie", None, None) is None
    assert upload_history_store.processed_key("series", None, None, season_number=1) is None


def test_record_then_is_processed():
    key = ("movie", 42)
    assert not upload_history_store.is_processed(key)
    upload_history_store.record(key, kind="committed", release_name="Movie.2020-TEAM")
    assert upload_history_store.is_processed(key)


def test_record_is_idempotent_by_key_and_kind_updates_timestamp():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="Movie.2020-TEAM", at=1000.0)
    upload_history_store.record(key, kind="committed", release_name="Movie.2020-TEAM", at=2000.0)
    assert upload_history_store.last_processed_at(key) == 2000.0


def test_last_processed_at_takes_most_recent_across_kinds():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="r", at=1000.0)
    upload_history_store.record(key, kind="sent", release_name="r", at=2000.0)
    assert upload_history_store.last_processed_at(key) == 2000.0


def test_last_processed_at_none_for_unknown_key():
    assert upload_history_store.last_processed_at(("movie", 999)) is None


def test_key_str_is_stable_json_serialization():
    assert upload_history_store.key_str(("movie", 42)) == json.dumps(["movie", 42])


def test_not_configured_without_env_var(monkeypatch):
    monkeypatch.delenv("NFOGEN_UPLOAD_HISTORY_FILE", raising=False)
    # No-op silencieux : jamais d'exception, is_processed reste False.
    upload_history_store.record(("movie", 1), kind="committed", release_name="r")
    assert not upload_history_store.is_processed(("movie", 1))


def test_record_never_raises_on_write_failure(monkeypatch, history_file):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    # Ne doit jamais lever -- un Confirmer/Envoi reussi ne doit jamais
    # echouer a cause de l'ecriture de l'historique (spec, "Gestion des erreurs").
    upload_history_store.record(("movie", 1), kind="committed", release_name="r")


def test_load_tolerates_corrupt_file(history_file):
    history_file.write_text("not json", encoding="utf-8")
    assert not upload_history_store.is_processed(("movie", 1))


# --------------------------------------------------------------------------- #
# staged_path + pending_seed_entries (AUTOMATION.md, sous-projet 6) : mise en
# seed apres upload -- retrouver le contenu deja en scene bien apres le
# Confirmer d'origine (la moderation C411 n'est pas immediate).
# --------------------------------------------------------------------------- #
def test_pending_seed_entries_lists_sent_without_seeding():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="R", staged_path="/staging/R.mkv")
    upload_history_store.record(key, kind="sent", release_name="R")

    entries = upload_history_store.pending_seed_entries()

    assert len(entries) == 1
    assert entries[0]["key"] == upload_history_store.key_str(key)
    assert entries[0]["media_type"] == "movie"
    assert entries[0]["release_name"] == "R"
    assert entries[0]["staged_path"] == "/staging/R.mkv"
    assert entries[0]["sent_at"] is not None


def test_pending_seed_entries_excludes_titles_never_sent():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="R", staged_path="/staging/R.mkv")
    assert upload_history_store.pending_seed_entries() == []


def test_pending_seed_entries_excludes_titles_already_seeding():
    key = ("movie", 42)
    upload_history_store.record(key, kind="committed", release_name="R", staged_path="/staging/R.mkv")
    upload_history_store.record(key, kind="sent", release_name="R")
    upload_history_store.record(key, kind="seeding", release_name="R")
    assert upload_history_store.pending_seed_entries() == []


def test_pending_seed_entries_series_media_type_and_staged_path_none_when_absent():
    key = ("series", 7, 2)
    # Jamais de "committed" enregistre avec staged_path pour cette cle.
    upload_history_store.record(key, kind="sent", release_name="Show.S02")

    entries = upload_history_store.pending_seed_entries()

    assert entries[0]["media_type"] == "series"
    assert entries[0]["staged_path"] is None


def test_pending_seed_entries_empty_without_env_var(monkeypatch):
    monkeypatch.delenv("NFOGEN_UPLOAD_HISTORY_FILE", raising=False)
    assert upload_history_store.pending_seed_entries() == []
