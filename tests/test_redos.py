"""Tests de la protection ReDoS des motifs regex admin (`rules.json ->
tokens[].pattern`), moteur RE2 (`nfogen/rules.py`).

Design (cf. ROADMAP.md, section audit) : plutot que de DETECTER un motif
pathologique a l'ecriture (heuristique par chronometrage, abandonnee -- trop
dependante de la machine et d'une entree de sonde choisie a l'avance, donc
potentiellement contournable), on REND l'explosion impossible en executant
TOUT motif admin via RE2 (moteur a automate, temps lineaire garanti, jamais de
backtracking exponentiel) -- aussi bien a la validation d'un profil qu'a
chaque generation. Consequence directe et volontaire : un motif comme
`(a+)+$` (ReDoS classique sous un moteur a backtracking) n'est PAS rejete ici,
il est simplement execute en temps lineaire, donc inoffensif. Seules les
constructions que RE2 ne supporte pas -- lookaround et back-references,
precisement ce qui permet le backtracking exponentiel -- sont rejetees.
"""
from __future__ import annotations

import time

import pytest

from nfogen import rules as rules_engine

# Motif representatif de C411 (ce qu'on veut ACCEPTER sans probleme).
SAFE_PATTERN = r"\.(?P<video_codec>[xX]26[45]|[Hh]\.?26[45]|HEVC|AVC|MPEG2)-[A-Za-z0-9-]+$"

# Motif ReDoS "classique" sous un moteur a backtracking (quantificateurs
# imbriques) : accepte par RE2 (syntaxiquement valide, pas de lookaround/
# back-reference) et execute en temps LINEAIRE, jamais exponentiel.
PATHOLOGICAL_UNDER_BACKTRACKING_PATTERN = r"^(a+)+$"

# Constructions que RE2 ne supporte PAS -- rejetees a la validation.
LOOKAHEAD_PATTERN = r"(?=foo)bar"
LOOKBEHIND_PATTERN = r"(?<=foo)bar"
BACKREFERENCE_PATTERN = r"(?P<x>a)\1"


def test_compile_safe_pattern_succeeds():
    rules_engine._compile_admin_pattern.cache_clear()
    rules_engine._compile_admin_pattern(SAFE_PATTERN)  # ne doit pas lever


def test_pathological_backtracking_pattern_is_accepted_and_fast():
    """Le motif qui ferait exploser un moteur a backtracking (`re` standard)
    est ACCEPTE par RE2 (aucune construction non supportee) -- et surtout, la
    recherche reste quasi instantanee meme sur une entree adversariale
    ('a' * N + caractere qui ne matche pas), la ou `re.search` serait bloque
    pendant des secondes/minutes. C'est la garantie centrale de ce design."""
    compiled = rules_engine._compile_admin_pattern(PATHOLOGICAL_UNDER_BACKTRACKING_PATTERN)
    adversarial_input = "a" * 500 + "X"  # 500 : trivial pour RE2, deja fatal pour `re`
    t0 = time.perf_counter()
    result = compiled.search(adversarial_input)
    elapsed = time.perf_counter() - t0
    assert result is None  # ne matche pas (le "X" final casse le motif)
    assert elapsed < 0.5, f"RE2 a mis {elapsed:.3f}s -- garantie de temps lineaire rompue ?"


@pytest.mark.parametrize(
    "pattern",
    [LOOKAHEAD_PATTERN, LOOKBEHIND_PATTERN, BACKREFERENCE_PATTERN],
    ids=["lookahead", "lookbehind", "backreference"],
)
def test_unsupported_construct_is_rejected(pattern):
    with pytest.raises(Exception):  # re2.error, propage tel quel par _compile_admin_pattern
        rules_engine._compile_admin_pattern.cache_clear()
        rules_engine._compile_admin_pattern(pattern)


def test_invalid_regex_syntax_raises():
    with pytest.raises(Exception):  # parenthese non fermee
        rules_engine._compile_admin_pattern("(non-fermee")


def test_validate_regex_patterns_accepts_safe_document():
    document = {"video": {"tokens": [{"name": "codec", "pattern": SAFE_PATTERN}]}}
    rules_engine.validate_regex_patterns(document)  # ne doit pas lever


def test_validate_regex_patterns_accepts_previously_pathological_pattern():
    """Confirme, au niveau du document complet (pas juste la primitive de
    compilation), que le design a bien change : un motif a quantificateurs
    imbriques n'est plus un motif de rejet."""
    document = {
        "video": {"tokens": [{"name": "ok", "pattern": PATHOLOGICAL_UNDER_BACKTRACKING_PATTERN}]}
    }
    rules_engine.validate_regex_patterns(document)  # ne doit pas lever


def test_validate_regex_patterns_rejects_lookahead():
    document = {"video": {"tokens": [{"name": "bad", "pattern": LOOKAHEAD_PATTERN}]}}
    with pytest.raises(ValueError, match="RE2"):
        rules_engine.validate_regex_patterns(document)


def test_validate_regex_patterns_locates_offending_token_in_message():
    """Le message doit nommer la categorie ET le token fautif, pour que
    l'admin sache lequel corriger (un profil peut declarer des dizaines de
    tokens)."""
    document = {
        "video": {
            "tokens": [
                {"name": "ok", "pattern": SAFE_PATTERN},
                {"name": "bad_token", "pattern": BACKREFERENCE_PATTERN},
            ]
        }
    }
    with pytest.raises(ValueError) as exc_info:
        rules_engine.validate_regex_patterns(document)
    msg = str(exc_info.value)
    assert "bad_token" in msg
    assert "video" in msg


def test_validate_regex_patterns_skips_non_dict_categories():
    """Un document peut contenir des valeurs non-dict (cas pathologique) :
    la validation regex doit les ignorer proprement, pas planter."""
    rules_engine.validate_regex_patterns({"video": "pas un dict"})
    rules_engine.validate_regex_patterns({"video": None})


def test_validate_regex_patterns_skips_non_string_patterns():
    """Defensif : un token sans 'pattern' (ou pattern non-string) ne doit pas
    faire planter -- le schema formel l'aurait deja rejete avant, mais on ne
    doit pas dependre de l'ordre des validations."""
    rules_engine.validate_regex_patterns({"video": {"tokens": [{"name": "x"}]}})


def test_validate_regex_patterns_handles_empty_document():
    rules_engine.validate_regex_patterns({})
    rules_engine.validate_regex_patterns({"video": {}})
    rules_engine.validate_regex_patterns({"video": {"tokens": []}})


def test_validate_rules_document_runs_regex_validation_too():
    """`validate_rules_document` (schema + regex) est le SEUL point d'entree
    attendu par tous les appelants (profile_store, chargement externe,
    declarative_profile) : verifie ici qu'un document par ailleurs valide au
    schema mais avec un motif non supporte par RE2 est bien rejete par cette
    seule fonction, sans appel separe a validate_regex_patterns."""
    document = {"video": {"requires_field": "release_name", "tokens": [
        {"name": "bad", "pattern": BACKREFERENCE_PATTERN}
    ]}}
    with pytest.raises(ValueError, match="RE2"):
        rules_engine.validate_rules_document(document)


# --------------------------------------------------------------------------- #
# Runtime : la garantie de temps lineaire s'applique aussi a `errors()` /
# `warnings()` / `captures()` (utilises a CHAQUE generation), pas seulement a
# la validation d'un profil a l'ecriture.
# --------------------------------------------------------------------------- #
def test_captures_stays_fast_on_pathological_pattern_and_adversarial_value():
    schema = {
        "tokens": [{"name": "x", "pattern": PATHOLOGICAL_UNDER_BACKTRACKING_PATTERN, "group": "g"}]
    }
    adversarial_value = "a" * 500 + "X"
    t0 = time.perf_counter()
    result = rules_engine.captures(adversarial_value, schema)
    elapsed = time.perf_counter() - t0
    assert result == {}
    assert elapsed < 0.5


# --------------------------------------------------------------------------- #
# Integration : la validation est branchee au niveau du profile_store (la ou
# un admin ecrit/importe un profil). Un profil avec une construction non
# supportee par RE2 doit etre rejete LA, avec un message 400 cote API, sans
# toucher au disque -- et un profil avec un motif a quantificateurs imbriques
# (autrefois rejete) doit maintenant etre ACCEPTE.
# --------------------------------------------------------------------------- #
def test_profile_store_write_rejects_unsupported_construct(tmp_path, monkeypatch):
    from nfogen import profile_store as ps

    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    with pytest.raises(ps.ProfileStoreError, match="RE2"):
        ps.write_profile(
            "evil",
            rules={"video": {"tokens": [{"name": "bad", "pattern": BACKREFERENCE_PATTERN}]}},
            templates={},
        )
    # Garde-fou : rien n'a ete ecrit sur disque (echec avant ecriture).
    assert not (tmp_path / "evil").exists()


def test_profile_store_write_accepts_previously_pathological_pattern(tmp_path, monkeypatch):
    from nfogen import profile_store as ps

    monkeypatch.setenv("NFOGEN_PROFILES_DIR", str(tmp_path))
    ps.write_profile(
        "nested-quantifiers",
        rules={
            "video": {"tokens": [{"name": "x", "pattern": PATHOLOGICAL_UNDER_BACKTRACKING_PATTERN}]}
        },
        templates={},
    )
    assert (tmp_path / "nested-quantifiers").is_dir()
