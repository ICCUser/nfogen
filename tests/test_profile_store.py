"""Tests de la persistance disque des profils utilisateur (`nfogen/profile_store.py`).

Toujours nettoyer le registre apres coup (`unregister_profile`) : ces tests
enregistrent reellement des profils dans le coeur, comme le ferait l'API.
"""
from __future__ import annotations

import json

import pytest

import nfogen
from nfogen import profile_store as ps
from nfogen.registry import unregister_profile

RULES = {
    "game": {
        "requires_field": "release_name",
        "doc": "doc de test",
        "example": "Mon.Jeu-TEAM",
        "tokens": [{"name": "team", "pattern": r"-[A-Z]+$", "level": "required", "error": "team manquante"}],
        "filename_template": "{release_name}.nfo",
    }
}
TEMPLATES = {"game": "{{ title }} - {{ release_name }}"}


@pytest.fixture(autouse=True)
def _profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    yield tmp_path
    try:
        names = ps.list_profiles()
    except ps.ProfileStoreError:
        names = []  # un test a retire NFOGEN_PROFILES_DIR lui-meme : rien a nettoyer
    for name in names:
        unregister_profile(name)


def test_write_then_read_round_trip():
    ps.write_profile("monprofil", rules=RULES, templates=TEMPLATES)
    data = ps.read_profile("monprofil")
    assert data["rules"] == RULES
    assert data["templates"] == TEMPLATES


def test_write_persists_files_on_disk(tmp_path):
    ps.write_profile("monprofil", rules=RULES, templates=TEMPLATES)
    assert json.loads((tmp_path / "monprofil" / "rules.json").read_text(encoding="utf-8")) == RULES
    assert (tmp_path / "monprofil" / "templates" / "game.j2").read_text(encoding="utf-8") == TEMPLATES["game"]


def test_write_immediately_usable_for_generation():
    ps.write_profile("monprofil", rules=RULES, templates=TEMPLATES)
    nfo = nfogen.generate(
        profile="monprofil", category="game", data={"title": "X", "release_name": "Mon.Jeu-TEAM"}
    )
    assert nfo == "X - Mon.Jeu-TEAM\n"


def test_write_rejects_invalid_rules_schema():
    with pytest.raises(ps.ProfileStoreError):
        ps.write_profile("monprofil", rules={"game": {"unknown_key": True}}, templates={})


def test_write_rejects_invalid_profile_name():
    with pytest.raises(ps.ProfileStoreError):
        ps.write_profile("../escape", rules={}, templates={})


def test_write_rejects_unknown_template_category():
    with pytest.raises(ps.ProfileStoreError):
        ps.write_profile("monprofil", rules={}, templates={"pas_une_categorie": "x"})


def test_write_replaces_existing_profile_entirely():
    ps.write_profile("monprofil", rules=RULES, templates=TEMPLATES)
    new_rules = {"game": {"filename_template": "{title}.nfo"}}
    ps.write_profile("monprofil", rules=new_rules, templates={"game": "juste {{ title }}"})
    data = ps.read_profile("monprofil")
    assert data["rules"] == new_rules
    assert "team" not in json.dumps(data)  # l'ancien schema n'a pas survecu


def test_delete_removes_files_and_registration(tmp_path):
    ps.write_profile("monprofil", rules=RULES, templates=TEMPLATES)
    ps.delete_profile("monprofil")
    assert not (tmp_path / "monprofil").exists()
    assert "monprofil" not in nfogen.list_available()


def test_delete_unknown_profile_raises():
    with pytest.raises(ps.ProfileStoreError):
        ps.delete_profile("inexistant")


def test_export_then_import_round_trip():
    ps.write_profile("monprofil", rules=RULES, templates=TEMPLATES)
    blob = ps.export_profile_zip("monprofil")

    ps.import_profile_zip("clone", blob)
    cloned = ps.read_profile("clone")
    assert cloned["rules"] == RULES
    assert cloned["templates"] == TEMPLATES


def test_import_invalid_zip_raises():
    with pytest.raises(ps.ProfileStoreError):
        ps.import_profile_zip("monprofil", b"pas un zip")


def test_requires_profiles_dir_configured(monkeypatch):
    monkeypatch.delenv("NFOGEN_PROFILES_DIR", raising=False)
    with pytest.raises(ps.ProfileStoreError):
        ps.list_profiles()


# --------------------------------------------------------------------------- #
# Profils livres avec le paquet (C411) : lisibles, exportables, et
# modifiables comme un profil utilisateur normal (surcharge du meme nom).
# --------------------------------------------------------------------------- #
def test_read_builtin_profile_without_override():
    data = ps.read_profile("c411")
    assert "video" in data["rules"]
    assert "video" in data["templates"]
    assert "c411" not in ps.list_profiles()  # pas (encore) un profil GERE


def test_read_builtin_profile_without_profiles_dir_configured(monkeypatch):
    monkeypatch.delenv("NFOGEN_PROFILES_DIR", raising=False)
    data = ps.read_profile("c411")
    assert "video" in data["rules"]


def test_write_profile_overrides_builtin_c411():
    try:
        ps.write_profile("c411", rules=RULES, templates=TEMPLATES)
        assert ps.read_profile("c411")["rules"] == RULES
        assert "c411" in ps.list_profiles()  # devenu un profil GERE
        nfo = nfogen.generate(
            profile="c411", category="game", data={"title": "X", "release_name": "Mon.Jeu-TEAM"}
        )
        assert nfo == "X - Mon.Jeu-TEAM\n"
    finally:
        ps.delete_profile("c411")  # restaure le profil livre (cf. test ci-dessous)


def test_delete_override_restores_builtin_c411():
    original = ps.read_profile("c411")["rules"]
    ps.write_profile("c411", rules=RULES, templates=TEMPLATES)
    assert ps.read_profile("c411")["rules"] == RULES

    ps.delete_profile("c411")

    assert "c411" not in ps.list_profiles()
    assert ps.read_profile("c411")["rules"] == original
    # Le profil livre redevient utilisable pour generer (pas seulement lisible).
    assert "video" in nfogen.list_available()["c411"]


def test_export_builtin_profile_excludes_package_files():
    blob = ps.export_profile_zip("c411")
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = zf.namelist()
    assert "rules.json" in names
    assert any(n.startswith("templates/") and n.endswith(".j2") for n in names)
    assert "__init__.py" not in names
    assert not any("__pycache__" in n for n in names)


def test_read_unknown_profile_still_raises():
    with pytest.raises(ps.ProfileStoreError):
        ps.read_profile("ni-gere-ni-livre")
