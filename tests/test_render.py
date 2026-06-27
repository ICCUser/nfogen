"""Tests du moteur de rendu (`nfogen/render.py`).

Verifie specifiquement la decouverte des templates embarques par profil via
le `PrefixLoader` (`profiles/<profil>/templates/`), independamment de toute
variable d'environnement `NFOGEN_TEMPLATES`.
"""
from __future__ import annotations

import pytest

from nfogen.render import render_template


@pytest.fixture(autouse=True)
def _no_external_templates(monkeypatch):
    """S'assure qu'aucun NFOGEN_TEMPLATES/NFOGEN_PROFILES_DIR residuel ne
    fausse le test : on veut bien verifier les templates *embarques*, pas une
    surcharge externe (sauf dans les tests qui la configurent eux-memes)."""
    monkeypatch.delenv("NFOGEN_TEMPLATES", raising=False)
    monkeypatch.delenv("NFOGEN_PROFILES_DIR", raising=False)
    render_template.__globals__["_env"].cache_clear()
    yield
    render_template.__globals__["_env"].cache_clear()


def test_embedded_template_video_passthrough():
    """video.j2 (profil c411) est trouve via le PrefixLoader embarque, sans
    aucun dossier externe configure."""
    nfo = render_template("c411", "video", {"raw_text": "General\nFormat : Matroska"})
    assert nfo == "General\nFormat : Matroska\n"


def test_embedded_template_game_structure():
    """Un template structure (pas un simple passthrough) est lui aussi
    trouve via le PrefixLoader embarque."""
    nfo = render_template(
        "c411",
        "game",
        {
            "title": "Mon Jeu", "version": "1.0", "platform": "PC", "format": "ISO",
            "languages_audio": "", "languages_text": "", "requirements": {}, "install_steps": [],
        },
    )
    assert "Mon Jeu" in nfo


def test_unknown_profile_template_raises():
    from jinja2 import TemplateNotFound

    with pytest.raises(TemplateNotFound):
        render_template("inconnu", "video", {"raw_text": "x"})


def test_sandbox_blocks_unsafe_attribute_access(tmp_path):
    """L'environnement Jinja2 est sandboxe : un template (ex. fourni via un
    dossier externe) ne peut pas remonter vers des attributs internes Python
    (`__class__`...). Indispensable des que des templates ne sont plus tous
    livres avec le code (NFOGEN_TEMPLATES, futurs profils utilisateur)."""
    from jinja2.exceptions import SecurityError

    profile_dir = tmp_path / "evil"
    profile_dir.mkdir()
    (profile_dir / "video.j2").write_text("{{ raw_text.__class__ }}", encoding="utf-8")

    with pytest.raises(SecurityError):
        render_template("evil", "video", {"raw_text": "x"}, extra_dirs=[str(tmp_path)])


def test_external_profiles_dir_template_is_discovered(tmp_path, monkeypatch):
    """NFOGEN_PROFILES_DIR suit la meme structure qu'un profil embarque
    (`<profil>/templates/<categorie>.j2`), pas celle de NFOGEN_TEMPLATES."""
    profile_dir = tmp_path / "monprofil" / "templates"
    profile_dir.mkdir(parents=True)
    (profile_dir / "game.j2").write_text("Externe : {{ title }}", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    render_template.__globals__["_env"].cache_clear()

    nfo = render_template("monprofil", "game", {"title": "X"})
    assert nfo == "Externe : X\n"


def test_external_profiles_dir_takes_priority_over_embedded(tmp_path, monkeypatch):
    """Un profil utilisateur nomme 'c411' (cas limite) prime sur le profil
    embarque du meme nom : NFOGEN_PROFILES_DIR est consulte avant le paquet."""
    profile_dir = tmp_path / "c411" / "templates"
    profile_dir.mkdir(parents=True)
    (profile_dir / "video.j2").write_text("Surcharge externe", encoding="utf-8")
    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    render_template.__globals__["_env"].cache_clear()

    nfo = render_template("c411", "video", {"raw_text": "ignore"})
    assert nfo == "Surcharge externe\n"
