"""Tests de nfogen.gapscan_config_store.

Stocke les identifiants Sonarr/Radarr/C411 en JSON sur disque, modifiables
a chaud via PUT /gapscan/config (contrairement a NFOGEN_API_TOKEN : ce ne
sont pas des secrets qui protegent nfogen lui-meme, mais des identifiants
sortants vers des services tiers que l'admin doit pouvoir changer sans
redemarrer le service). Repli sur les variables d'environnement historiques
si le fichier n'est pas configure/vide -- pas une regression du lot
precedent (endpoints /gapscan/*), un complement.
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


def test_effective_c411_none_when_nothing_configured():
    assert store.effective_c411() is None


def test_write_then_read_c411():
    store.write(c411_api_key="secret", c411_base_url="https://c411.org")
    assert store.effective_c411() == ("secret", "https://c411.org")


def test_write_defaults_base_url_when_absent():
    store.write(c411_api_key="secret")
    assert store.effective_c411() == ("secret", "https://c411.org")


def test_partial_write_does_not_erase_other_fields():
    store.write(c411_api_key="secret", sonarr_url="http://sonarr.local", sonarr_api_key="sk")
    store.write(radarr_url="http://radarr.local", radarr_api_key="rk")

    assert store.effective_c411() == ("secret", "https://c411.org")
    assert store.effective_sonarr() == ("http://sonarr.local", "sk")
    assert store.effective_radarr() == ("http://radarr.local", "rk")


def test_write_overwrites_existing_field():
    store.write(c411_api_key="old")
    store.write(c411_api_key="new")
    assert store.effective_c411() == ("new", "https://c411.org")


def test_never_exposes_secrets_in_status():
    store.write(c411_api_key="secret", sonarr_url="http://sonarr.local", sonarr_api_key="sk")
    status = store.status()
    assert "secret" not in str(status)
    assert "sk" not in str(status)
    assert status["c411_configured"] is True
    assert status["sonarr_configured"] is True
    assert status["sonarr_url"] == "http://sonarr.local"


def test_falls_back_to_env_vars_when_file_not_configured(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    assert store.effective_c411() == ("from-env", "https://c411.org")


def test_falls_back_to_env_vars_when_file_empty(monkeypatch, tmp_path):
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_GAPSCAN_CONFIG_FILE", str(tmp_path / "empty.json"))
    monkeypatch.setenv("NFOGEN_SONARR_URL", "http://from-env.local")
    monkeypatch.setenv("NFOGEN_SONARR_API_KEY", "from-env-key")
    assert store.effective_sonarr() == ("http://from-env.local", "from-env-key")


def test_stored_value_takes_precedence_over_env_var(monkeypatch):
    monkeypatch.setenv("NFOGEN_C411_API_KEY", "from-env")
    store.write(c411_api_key="from-file")
    assert store.effective_c411() == ("from-file", "https://c411.org")


def test_status_falls_back_to_env_for_the_configured_flag(monkeypatch):
    monkeypatch.setenv("NFOGEN_RADARR_URL", "http://radarr.local")
    monkeypatch.setenv("NFOGEN_RADARR_API_KEY", "rk")
    status = store.status()
    assert status["radarr_configured"] is True
    assert status["radarr_url"] == "http://radarr.local"


def test_write_without_config_file_env_var_raises(monkeypatch):
    monkeypatch.delenv("NFOGEN_GAPSCAN_CONFIG_FILE", raising=False)
    with pytest.raises(store.GapscanConfigStoreError):
        store.write(c411_api_key="x")


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
    store.write(c411_api_key="secret")
    store.write(radarr_path_mappings={"/data/movies": "/mnt/nas/movies"})
    assert store.effective_c411() == ("secret", "https://c411.org")
    assert store.effective_radarr_path_mappings() == {"/data/movies": "/mnt/nas/movies"}


def test_status_includes_path_mappings():
    store.write(
        sonarr_path_mappings={"/data/tv": "/mnt/nas/tv"},
        radarr_path_mappings={"/data/movies": "/mnt/nas/movies"},
    )
    status = store.status()
    assert status["sonarr_path_mappings"] == {"/data/tv": "/mnt/nas/tv"}
    assert status["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}


def test_status_path_mappings_empty_by_default():
    status = store.status()
    assert status["sonarr_path_mappings"] == {}
    assert status["radarr_path_mappings"] == {}


@pytest.mark.skipif(sys.platform == "win32", reason="permissions POSIX non applicables sur Windows")
def test_write_sets_restrictive_permissions(tmp_path):
    """Contrairement a nfogen.env (chmod 600 explicite dans install.sh), ce
    fichier contient des cles API en clair (Sonarr/Radarr/C411) sans
    protection equivalente avant ce correctif -- lisible par n'importe quel
    utilisateur local du systeme (ex. un swizzin multi-utilisateurs)."""
    store.write(c411_api_key="secret")
    mode = stat.S_IMODE((tmp_path / "gapscan_config.json").stat().st_mode)
    assert mode == 0o600
