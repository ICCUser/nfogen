"""Tests de nfogen.languages (mapping code MediaInfo -> nom affiche +
drapeau, utilise par upload_prep.py pour le tableau audio/sous-titres)."""
from __future__ import annotations

from nfogen.languages import flagcdn_url, resolve_language


def test_resolve_language_known_codes():
    assert resolve_language("fre") == ("Français", "fr")
    assert resolve_language("fr") == ("Français", "fr")
    assert resolve_language("eng") == ("Anglais", "gb")
    assert resolve_language("jpn") == ("Japonais", "jp")


def test_resolve_language_is_case_insensitive():
    assert resolve_language("FRE") == ("Français", "fr")


def test_resolve_language_unknown_code_returns_raw_with_no_flag():
    assert resolve_language("und") == ("und", None)
    assert resolve_language("") == ("", None)
    assert resolve_language(None) == ("", None)


def test_flagcdn_url_builds_expected_url():
    assert flagcdn_url("fr") == "https://flagcdn.com/20x15/fr.png"
