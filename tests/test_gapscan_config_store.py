"""Tests de nfogen.gapscan_config_store.

Identifiants Sonarr/Radarr GLOBAUX (une seule bibliotheque media,
independante du tracker cible) + identifiants de TRACKER namespaces par
PROFIL (chaque profil garde les siens -- voir AUTOMATION.md, sous-projet
4b), le tout en JSON sur disque, modifiable a chaud via PUT /gapscan/config.
Repli sur les variables d'environnement historiques si le fichier n'est
pas configure/vide.
"""
from __future__ import annotations

import stat
import sys

import pytest

from nfogen import gapscan_config_store as store


@pytest.fixture(autouse=True)
def _config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(tmp_path / "gapscan_config.json"))
    for key in (
        "NFOGEN_C411_API_KEY", "NFOGEN_C411_BASE_URL",
        "NFOGEN_SONARR_URL", "NFOGEN_SONARR_API_KEY",
        "NFOGEN_RADARR_URL", "NFOGEN_RADARR_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_effective_tracker_none_when_nothing_configured():
    assert store.effective_tracker("c411") is None


def test_write_then_read_tracker():
    store.write(profile="c411", tracker_api_key="secret", tracker_base_url="https://c411.org")
    assert store.effective_tracker("c411") == ("secret", "https://c411.org")


def test_write_defaults_base_url_when_absent_for_c411():
    store.write(profile="c411", tracker_api_key="secret")
    assert store.effective_tracker("c411") == ("secret", "https://c411.org")


def test_no_default_base_url_for_a_non_c411_profile():
    # Aucune URL par defaut connue pour un tracker qu'on ne connait pas.
    store.write(profile="ygg", tracker_api_key="secret")
    assert store.effective_tracker("ygg") is None


def test_two_profiles_keep_separate_credentials():
    store.write(profile="c411", tracker_api_key="c411-key", tracker_base_url="https://c411.org")
    store.write(profile="ygg", tracker_api_key="ygg-key", tracker_base_url="https://ygg.example")
    assert store.effective_tracker("c411") == ("c411-key", "https://c411.org")
    assert store.effective_tracker("ygg") == ("ygg-key", "https://ygg.example")


def test_partial_write_does_not_erase_other_fields():
    store.write(
        profile="c411", tracker_api_key="secret", sonarr_url="http://sonarr.local", sonarr_api_key="sk"
    )
    store.write(radarr_url="http://radarr.local", radarr_api_key="rk")

    assert store.effective_tracker("c411") == ("secret", "https://c411.org")
    assert store.effective_sonarr() == ("http://sonarr.local", "sk")
    assert store.effective_radarr() == ("http://radarr.local", "rk")


def test_write_overwrites_existing_field():
    store.write(profile="c411", tracker_api_key="old")
    store.write(profile="c411", tracker_api_key="new")
    assert store.effective_tracker("c411") == ("new", "https://c411.org")


def test_never_exposes_secrets_in_status():
    store.write(
        profile="c411", tracker_api_key="secret", sonarr_url="http://sonarr.local", sonarr_api_key="sk"
    )
    status = store.status("c411")
    assert "secret" not in str(status)
    assert "sk" not in str(status)
    assert status["tracker_configured"] is True
    assert status["sonarr_configured"] is True
    assert status["sonarr_url"] == "http://sonarr.local"


def test_status_includes_the_requested_profile():
    assert store.status("c411")["profile"] == "c411"
    assert store.status("ygg")["profile"] == "ygg"


def test_falls_back_to_env_vars_when_file_not_configured_for_c411(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    assert store.effective_tracker("c411") == ("from-env", "https://c411.org")


def test_env_var_fallback_never_applies_to_a_non_c411_profile(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    assert store.effective_tracker("ygg") is None


def test_falls_back_to_env_vars_when_file_empty(monkeypatch, tmp_path):
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(tmp_path / "empty.json"))
    monkeypatch.setenv("NFOGEN_SONARR_URL", "http://from-env.local")
    monkeypatch.setenv("NFOGEN_SONARR_API_KEY", "from-env-key")
    assert store.effective_sonarr() == ("http://from-env.local", "from-env-key")


def test_stored_value_takes_precedence_over_env_var(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    store.write(profile="c411", tracker_api_key="from-file")
    assert store.effective_tracker("c411") == ("from-file", "https://c411.org")


def test_legacy_flat_c411_fields_still_read_when_no_namespaced_entry_exists(tmp_path):
    # Retrocompat sans script de migration (AUTOMATION.md, sous-projet 4b) :
    # un fichier ecrit par l'ANCIEN code (avant le namespacage par profil)
    # doit continuer a fonctionner tel quel.
    config_path = tmp_path / "gapscan_config.json"
    config_path.write_text(
        '{"c411_api_key": "legacy-key", "c411_base_url": "https://c411.org", '
        '"c411_announce_url": "https://c411.org/announce/LEGACY"}',
        encoding="utf-8",
    )
    assert store.effective_tracker("c411") == ("legacy-key", "https://c411.org")
    assert store.effective_tracker_announce_url("c411") == "https://c411.org/announce/LEGACY"


def test_namespaced_entry_takes_precedence_over_legacy_flat_fields(tmp_path):
    config_path = tmp_path / "gapscan_config.json"
    config_path.write_text(
        '{"c411_api_key": "legacy-key", "trackers": {"c411": {"api_key": "new-key", '
        '"base_url": "https://c411.org"}}}',
        encoding="utf-8",
    )
    assert store.effective_tracker("c411") == ("new-key", "https://c411.org")


def test_write_without_config_file_env_var_raises(monkeypatch):
    monkeypatch.delenv("NFOGEN_GAPSCAN_CONFIG_FILE", raising=False)
    with pytest.raises(store.GapscanConfigStoreError):
        store.write(profile="c411", tracker_api_key="x")


def test_path_mappings_default_to_empty_dict():
    assert store.effective_sonarr_path_mappings() == {}
    assert store.effective_radarr_path_mappings() == {}


def test_write_then_read_sonarr_path_mappings():
    store.write(sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"})
    assert store.effective_sonarr_path_mappings() == {"/data/tv": "/mnt/nas/tv"}


def test_write_then_read_radarr_path_mappings():
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_write_path_mappings_does_not_erase_other_fields():
    store.write(profile="c411", tracker_api_key="secret")
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_tracker("c411") == ("secret", "https://c411.org")
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_status_includes_path_mappings():
    store.write(
        sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"},
        radarr_path_mappings={"/data/movies": "/mnt/nas/movies"},
    )
    status = store.status("c411")
    assert status["sonarr_path_mappings"] == {"/data/tv": "/mnt/nas/tv"}
    assert status["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}


def test_status_path_mappings_empty_by_default():
    status = store.status("c411")
    assert status["sonarr_path_mappings"] == {}
    assert status["radarr_path_mappings"] == {}


def test_tracker_announce_url_defaults_to_none():
    assert store.effective_tracker_announce_url("c411") is None


def test_write_then_read_tracker_announce_url():
    store.write(profile="c411", tracker_announce_url="https://c411.org/announce/SECRET")
    assert store.effective_tracker_announce_url("c411") == "https://c411.org/announce/SECRET"


def test_staging_dir_defaults_to_none():
    assert store.effective_staging_dir() is None


def test_write_then_read_staging_dir():
    store.write(staging_dir="/data/staging")
    assert store.effective_staging_dir() == "/data/staging"


def test_status_exposes_announce_url_as_a_flag_not_the_secret_itself():
    store.write(profile="c411", tracker_announce_url="https://c411.org/announce/SECRET")
    status = store.status("c411")
    assert status["tracker_announce_url_configured"] is True
    assert "SECRET" not in str(status)


def test_status_announce_url_flag_false_by_default():
    assert store.status("c411")["tracker_announce_url_configured"] is False


def test_status_includes_staging_dir():
    store.write(staging_dir="/data/staging")
    assert store.status("c411")["staging_dir"] == "/data/staging"


def test_status_staging_dir_none_by_default():
    assert store.status("c411")["staging_dir"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="permissions POSIX non applicables sur Windows")
def test_write_sets_restrictive_permissions(tmp_path):
    store.write(profile="c411", tracker_api_key="secret")
    mode = stat.S_IMODE((tmp_path / "gapscan_config.json").stat().st_mode)
    assert mode == 0o600
