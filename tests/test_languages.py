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


def test_resolve_language_falls_back_to_title_when_code_is_absent():
    """Retour reel de moderation, 2026-09-13 (dump MediaInfo reel, fichier
    mkvmerge) : le champ Language formel d'une piste de sous-titres peut
    etre absent -- seul le `title` libre porte la langue."""
    assert resolve_language(None, "French forced") == ("Français", "fr")
    assert resolve_language(None, "English SDH") == ("Anglais", "gb")
    assert resolve_language("", "French") == ("Français", "fr")


def test_resolve_language_prefers_code_over_title_when_both_present():
    assert resolve_language("eng", "French forced") == ("Anglais", "gb")


def test_resolve_language_title_fallback_uses_whole_word_matching():
    """"en" ou "fr" ne doivent jamais matcher un sous-mot ordinaire du
    titre -- seuls les noms anglais COMPLETS des langues sont cherches
    (voir _TITLE_HINT_KEYS), a la frontiere du mot."""
    assert resolve_language(None, "Commentary track") == ("", None)


def test_resolve_language_returns_empty_when_neither_code_nor_title_help():
    assert resolve_language(None, None) == ("", None)
    assert resolve_language(None, "Track 1") == ("", None)


def test_flagcdn_url_builds_expected_url():
    assert flagcdn_url("fr") == "https://flagcdn.com/20x15/fr.png"
