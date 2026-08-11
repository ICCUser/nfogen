"""Tests de la gestion de profils utilisateur en CLI (`nfogen/cli.py`,
`--profile-store-*`) : equivalent CLI des routes `/profiles/store*` de
l'API (`nfogen/profile_store.py`), pour gerer un profil sans lancer
uvicorn -- notamment produire le `.zip` d'un profil (ex. C411) sans faire
tourner l'API du tout.
"""
from __future__ import annotations

import json

import pytest

from nfogen import cli
from nfogen import profile_store as ps
from nfogen.registry import unregister_profile

RULES = {
    "game": {
        "requires_field": "release_name",
        "tokens": [{"name": "team", "pattern": r"-[A-Z]+$", "level": "required", "error": "team manquante"}],
        "filename_template": "{release_name}.nfo",
    }
}


@pytest.fixture(autouse=True)
def _profiles_dir(tmp_path, monkeypatch):
    # Sous-dossier DEDIE (pas tmp_path lui-meme) : les tests deposent aussi
    # des fichiers source (rules.json, templates/*.j2) sous tmp_path pour
    # alimenter --rules-file/--templates-dir -- s'ils partageaient le meme
    # dossier que NFOGEN_PROFILES_DIR, `list_profiles()` (qui liste TOUT
    # sous-dossier direct) les confondrait avec de vrais profils.
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(profiles_dir))
    yield profiles_dir
    try:
        names = ps.list_profiles()
    except ps.ProfileStoreError:
        names = []
    for name in names:
        unregister_profile(name)


def _write_json(path, data) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_profile_store_list_empty(capsys):
    assert cli.main(["--profile-store-list"]) == 0
    assert capsys.readouterr().out == ""


def test_profile_store_write_and_show_round_trip(tmp_path, capsys):
    rules_file = _write_json(tmp_path / "rules.json", RULES)
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "game.j2").write_text("{{ release_name }}", encoding="utf-8")

    exit_code = cli.main(
        [
            "--profile-store-write", "mon_tracker",
            "--rules-file", rules_file,
            "--templates-dir", str(templates_dir),
        ]
    )
    assert exit_code == 0
    capsys.readouterr()  # vide le buffer (message ecrit sur stderr)

    assert cli.main(["--profile-store-list"]) == 0
    assert capsys.readouterr().out.strip() == "mon_tracker"

    assert cli.main(["--profile-store-show", "mon_tracker"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["rules"] == RULES
    assert shown["templates"] == {"game": "{{ release_name }}"}


def test_profile_store_write_without_rules_file_uses_no_rules(tmp_path):
    """--rules-file est optionnel : un profil peut n'avoir que des templates,
    sans regle de nommage (comme documente pour rules.json absent)."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "game.j2").write_text("libre", encoding="utf-8")

    assert cli.main(["--profile-store-write", "libre", "--templates-dir", str(templates_dir)]) == 0
    assert ps.read_profile("libre")["rules"] == {}


def test_profile_store_delete(capsys):
    assert cli.main(["--profile-store-write", "a-supprimer"]) == 0
    capsys.readouterr()
    assert cli.main(["--profile-store-delete", "a-supprimer"]) == 0
    assert cli.main(["--profile-store-list"]) == 0
    assert capsys.readouterr().out == ""


def test_profile_store_export_then_import_round_trip(tmp_path, capsys):
    rules_file = _write_json(tmp_path / "r.json", RULES)
    assert cli.main(["--profile-store-write", "original", "--rules-file", rules_file]) == 0
    capsys.readouterr()

    zip_path = tmp_path / "original.zip"
    assert cli.main(["--profile-store-export", "original", "-o", str(zip_path)]) == 0
    assert zip_path.is_file()

    assert cli.main(["--profile-store-import", "copie", "--zip-file", str(zip_path)]) == 0
    assert ps.read_profile("copie")["rules"] == RULES


def test_profile_store_export_can_produce_the_shipped_c411_zip_without_the_api(tmp_path):
    """Cas d'usage central de cette commande : produire le `.zip` du profil
    C411 livre avec le paquet SANS lancer l'API (cf. ROADMAP.md, "Profils
    comme extensions") -- C411 est lisible/exportable meme sans avoir ete
    surcharge dans NFOGEN_PROFILES_DIR (cf. `profile_store._resolve_readable_dir`)."""
    zip_path = tmp_path / "c411.zip"
    assert cli.main(["--profile-store-export", "c411", "-o", str(zip_path)]) == 0
    assert zip_path.stat().st_size > 0

    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "rules.json" in names
    assert "templates/video.j2" in names
    assert "__init__.py" not in names  # jamais le code source du profil, cf. export_profile_zip


def test_profile_store_export_requires_out():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--profile-store-export", "c411"])
    assert exc_info.value.code == 2


def test_profile_store_import_requires_zip_file():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--profile-store-import", "x"])
    assert exc_info.value.code == 2


def test_profile_store_show_unknown_profile_returns_error(capsys):
    assert cli.main(["--profile-store-show", "n-existe-pas"]) == 1
    assert "Erreur" in capsys.readouterr().err


def test_profile_store_delete_unknown_profile_returns_error(capsys):
    assert cli.main(["--profile-store-delete", "n-existe-pas"]) == 1
    assert "Erreur" in capsys.readouterr().err


def test_profile_store_write_invalid_templates_dir_returns_error(capsys):
    assert cli.main(["--profile-store-write", "x", "--templates-dir", "/chemin/inexistant"]) == 1
    assert "Erreur" in capsys.readouterr().err


def test_profile_store_flags_take_priority_over_generation():
    """Un flag --profile-store-* ne doit jamais tomber dans le chemin de
    generation normale (qui exigerait --in/--data) : verifie qu'aucun des
    deux n'est requis quand un flag de gestion de profil est fourni."""
    assert cli.main(["--profile-store-list"]) == 0  # ne doit pas lever via parser.error
