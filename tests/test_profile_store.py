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


def test_write_rejects_unknown_root_category():
    """Schema strict (rules.schema.json) : une cle racine qui n'est pas une des
    5 categories fixes (video/audio/game/ebook/print3d) est REJETEE. Sans cela,
    une typo ('viedo' au lieu de 'video') serait acceptee silencieusement et la
    regle ratee decouverte seulement en production."""
    with pytest.raises(ps.ProfileStoreError):
        ps.write_profile(
            "monprofil",
            rules={"viedo": {"requires_field": "release_name"}},
            templates={},
        )


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


# --------------------------------------------------------------------------- #
# Section "tracker" (AUTOMATION.md, sous-projet 4b) : reglages propres au
# tracker (pas a une categorie de media), separee des categories existantes.
# --------------------------------------------------------------------------- #
TRACKER_RULES = {
    "tracker": {
        "display_name": "Test Tracker",
        "torznab_categories": {"anime": ["2060"], "documentaire": ["2070"]},
        "audio_language_codes": {"fre": "FR", "eng": "EN"},
        "min_request_interval_seconds": 4.5,
        "torrent_piece_sizes": [
            {"max_bytes": 1073741824, "piece_size": 1048576},
            {"piece_size": 16777216},
        ],
    }
}


def test_tracker_is_a_valid_top_level_key():
    ps.write_profile("trackertest", rules=TRACKER_RULES, templates={})
    read = ps.read_profile("trackertest")
    assert read["rules"]["tracker"]["display_name"] == "Test Tracker"


def test_tracker_and_a_category_can_coexist():
    combined = {**TRACKER_RULES, **RULES}
    ps.write_profile("trackertest2", rules=combined, templates=TEMPLATES)
    read = ps.read_profile("trackertest2")
    assert "tracker" in read["rules"]
    assert "game" in read["rules"]


def test_tracker_upload_section_is_valid():
    rules = {
        "tracker": {
            "upload": {
                "category_id": 1,
                "subcategory_id": {"movie": 6, "series": 7},
                "language_option_id": 1,
                "language_values": {"VFF": 2, "MULTI.VFF": 4},
                "quality_option_id": 2,
                "quality_values": {"BluRay": 11, "BluRay.HDLight": 413},
                "season_option_id": 7,
                "season_values": {"S01": 121},
                "episode_option_id": 6,
                "full_season_episode_value": 96,
            }
        }
    }
    ps.write_profile("uploadtest", rules=rules, templates={})
    read = ps.read_profile("uploadtest")
    assert read["rules"]["tracker"]["upload"]["category_id"] == 1


def test_unknown_top_level_key_still_rejected():
    # Regression : le schema ne doit pas devenir "tout accepte" en ouvrant
    # "tracker" -- une cle inconnue reste une erreur (voir rules.schema.json).
    with pytest.raises(ps.ProfileStoreError):
        ps.write_profile("bogus", rules={"totally_unknown_key": {}}, templates={})


def test_concurrent_writes_to_same_profile_never_corrupt_it():
    """`write_profile` fait `shutil.rmtree()` puis recree le dossier fichier
    par fichier (rules.json, puis chaque template) : sans verrou (`ps._LOCK`),
    deux PUT concurrents sur le MEME profil (deux administrateurs, ou un
    double-clic dans le frontend) pouvaient s'entrelacer -- une ecriture
    supprimant ce que l'autre venait de creer (FileNotFoundError), ou une
    lecture tombant sur un dossier partiellement ecrit. Deux threads
    ecrivent chacun une variante distincte du meme profil en boucle ; le
    resultat final doit toujours etre l'UNE des deux variantes entiere,
    jamais un melange, et aucune ecriture ne doit lever d'exception."""
    from concurrent.futures import ThreadPoolExecutor

    errors: list[Exception] = []

    def write_variant(marker: str) -> None:
        rules_variant = {
            "game": {
                "requires_field": "release_name",
                "tokens": [{"name": "team", "pattern": r"-[A-Z]+$", "level": "required", "error": "x"}],
            }
        }
        for _ in range(20):
            try:
                ps.write_profile("concurrent", rules=rules_variant, templates={"game": f"MARKER-{marker}"})
            except Exception as exc:  # noqa: BLE001 -- capture large pour le diagnostic du test
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(write_variant, "A")
        f2 = pool.submit(write_variant, "B")
        f1.result()
        f2.result()

    assert errors == [], f"ecriture(s) concurrente(s) en echec : {errors}"
    template = ps.read_profile("concurrent")["templates"]["game"]
    assert template in ("MARKER-A", "MARKER-B")
