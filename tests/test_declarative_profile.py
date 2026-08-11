"""Tests du moteur de profil declaratif generique (`nfogen/declarative_profile.py`).

Le point a prouver : un profil "inconnu de c411" (rien dans le code, juste un
`rules.json` + un template) fonctionne a l'identique via le meme mecanisme
generique — c'est ce qui rend possible la gestion de profils utilisateur
(Phase 2) sans toucher au coeur."""
from __future__ import annotations

import pytest

import nfogen
from nfogen import rules as rules_engine
from nfogen.declarative_profile import register_declarative_profile
from nfogen.registry import unregister_profile

PROFILE = "testprofile"

RULES = {
    "game": {
        "requires_field": "release_name",
        "doc": "doc de test",
        "example": "Mon.Jeu-TEAM",
        "forbid_spaces": True,
        "tokens": [
            {"name": "team", "pattern": r"-[A-Z]+$", "level": "required", "error": "team manquante"},
        ],
        "filename_template": "{release_name}.nfo",
    }
}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    unregister_profile(PROFILE)


@pytest.fixture(autouse=True)
def _profile_templates(tmp_path, monkeypatch):
    """`render_template` est appele inconditionnellement par les renderers
    declaratifs : il faut donc toujours un template disponible pour le
    profil de test, meme quand le test ne porte que sur la validation ou le
    nommage. Un seul template generique (categorie 'game') suffit pour tous
    les tests de ce module."""
    (tmp_path / PROFILE).mkdir()
    template = "{{ title|default('') }} [{{ release_name }}]"
    (tmp_path / PROFILE / "game.j2").write_text(template, encoding="utf-8")
    monkeypatch.setenv("NFOGEN_TEMPLATES", str(tmp_path))
    from nfogen.render import _env

    _env.cache_clear()
    yield
    _env.cache_clear()


def test_register_creates_renderer_for_all_fixed_categories():
    register_declarative_profile(PROFILE, {})
    available = nfogen.list_available()
    assert set(available[PROFILE]) == {"video", "audio", "game", "ebook", "print3d"}


def test_render_uses_profile_specific_template():
    register_declarative_profile(PROFILE, RULES)
    nfo = nfogen.generate(
        profile=PROFILE, category="game", data={"title": "X", "release_name": "Mon.Jeu-TEAM"}
    )
    assert nfo == "X [Mon.Jeu-TEAM]\n"


def test_validator_blocks_non_conforming_value():
    register_declarative_profile(PROFILE, RULES)
    with pytest.raises(ValueError, match="non conforme"):
        nfogen.generate(profile=PROFILE, category="game", data={"release_name": "sans team"})


def test_filename_rule_uses_schema_template():
    register_declarative_profile(PROFILE, RULES)
    filename: list[str] = []
    nfogen.generate(
        profile=PROFILE,
        category="game",
        data={"release_name": "Mon.Jeu-TEAM"},
        filename=filename,
    )
    assert filename == ["Mon.Jeu-TEAM.nfo"]


def test_no_validator_for_category_without_requires_field():
    register_declarative_profile(PROFILE, {"game": {}})
    warnings: list[str] = []
    data = {"title": "X", "release_name": "peu importe"}
    nfogen.generate(profile=PROFILE, category="game", data=data, warnings=warnings)
    assert warnings == []


def test_unknown_category_key_in_rules_is_rejected():
    """Une cle racine qui n'est pas une des 5 categories fixes est REJETEE
    (schema strict, cf. rules.schema.json) plutot qu'ignoree silencieusement :
    sinon une typo ('viedo' au lieu de 'video') serait avalée sans bruit et la
    regle ratee decouverte seulement en production. La validation passe par le
    meme `validate_rules_document` que tout autre profil utilisateur."""
    with pytest.raises(ValueError):
        register_declarative_profile(PROFILE, {"categorie_inconnue": {"requires_field": "x"}})


def test_register_rejects_schema_violating_rules():
    with pytest.raises(ValueError):
        register_declarative_profile(PROFILE, {"game": {"unknown_key": True}})


def test_unregister_profile_removes_all_categories():
    register_declarative_profile(PROFILE, RULES)
    assert PROFILE in nfogen.list_available()
    unregister_profile(PROFILE)
    assert PROFILE not in nfogen.list_available()


def test_validate_rules_document_accepts_real_c411_rules():
    """Garde-fou : le rules.json livre avec C411 doit toujours etre conforme
    au schema formel (sinon la Phase 2 a introduit une regression silencieuse)."""
    import json
    from pathlib import Path

    c411_rules = json.loads(
        (Path(nfogen.__file__).parent / "profiles" / "c411" / "rules.json").read_text(encoding="utf-8")
    )
    rules_engine.validate_rules_document(c411_rules)  # ne doit pas lever


def test_external_profile_overrides_shipped_profile_of_same_name(tmp_path, monkeypatch):
    """Un profil utilisateur nomme 'c411' (meme nom qu'un profil livre) le
    remplace entierement, y compris apres un rechargement du module profils
    (simulant un redemarrage du processus) — sinon la surcharge serait
    silencieusement ignoree au prochain demarrage (collision dans le
    registre, avalee par le try/except de _load_external_profiles)."""
    import importlib

    import nfogen.profiles as profiles_pkg
    import nfogen.profiles.c411 as c411_module
    from nfogen.render import _env

    profile_dir = tmp_path / "c411" / "templates"
    profile_dir.mkdir(parents=True)
    (profile_dir / "video.j2").write_text("OVERRIDDEN: {{ raw_text }}", encoding="utf-8")
    (tmp_path / "c411" / "rules.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    _env.cache_clear()

    try:
        profiles_pkg._load_external_profiles()
        nfo = nfogen.generate(profile="c411", category="video", data={"raw_text": "x"})
        assert nfo.startswith("OVERRIDDEN:")
    finally:
        unregister_profile("c411")
        importlib.reload(c411_module)  # restaure le profil livre d'origine
        _env.cache_clear()
