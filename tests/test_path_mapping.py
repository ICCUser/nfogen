"""Tests de nfogen.path_mapping (resolution de chemins Sonarr/Radarr vers un
chemin local, meme principe que les "Remote Path Mappings" de Sonarr/Radarr
eux-memes -- voir AUTOMATION.md, sous-projet 1)."""
from __future__ import annotations

import os

from nfogen.path_mapping import resolve_and_validate, resolve_path


def test_resolve_path_without_mapping_returns_input_unchanged():
    assert resolve_path("/data/media/Matrix.mkv", {}) == "/data/media/Matrix.mkv"


def test_resolve_path_substitutes_matching_prefix():
    mappings = {"/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media/Matrix.mkv", mappings) == "/mnt/nas/media/Matrix.mkv"


def test_resolve_path_uses_the_longest_matching_prefix():
    mappings = {"/data": "/mnt/wrong", "/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media/Matrix.mkv", mappings) == "/mnt/nas/media/Matrix.mkv"


def test_resolve_path_does_not_confuse_a_sibling_directory():
    """'/data/media2' ne doit pas matcher le prefixe '/data/media' juste
    parce qu'il commence par la meme chaine -- limite de repertoire."""
    mappings = {"/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media2/Matrix.mkv", mappings) == "/data/media2/Matrix.mkv"


def test_resolve_path_matches_the_prefix_exactly():
    mappings = {"/data/media": "/mnt/nas/media"}
    assert resolve_path("/data/media", mappings) == "/mnt/nas/media"


def test_resolve_and_validate_returns_error_when_no_remote_paths():
    resolved, ok, error = resolve_and_validate([], {})
    assert resolved == []
    assert ok is False
    assert "Aucun chemin" in error


def test_resolve_and_validate_ok_when_file_exists_and_readable(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("contenu")
    resolved, ok, error = resolve_and_validate([str(f)], {})
    assert resolved == [str(f)]
    assert ok is True
    assert error is None


def test_resolve_and_validate_fails_when_file_missing(tmp_path):
    missing = str(tmp_path / "absent.mkv")
    resolved, ok, error = resolve_and_validate([missing], {})
    assert ok is False
    assert "introuvable" in error
    assert missing in error


def test_resolve_and_validate_applies_mapping_before_checking(tmp_path):
    f = tmp_path / "Matrix.mkv"
    f.write_text("contenu")
    mappings = {"/data/media": str(tmp_path)}
    resolved, ok, error = resolve_and_validate(["/data/media/Matrix.mkv"], mappings)
    # normpath cote test uniquement : le prefixe "distant" litteral (style
    # Linux, "/") mixe avec tmp_path (separateurs natifs de la machine de
    # dev) ne doit pas faire dependre ce test de l'OS qui l'execute.
    assert os.path.normpath(resolved[0]) == os.path.normpath(str(f))
    assert ok is True


def test_resolve_and_validate_stops_at_the_first_missing_file(tmp_path):
    f = tmp_path / "E01.mkv"
    f.write_text("contenu")
    missing = str(tmp_path / "E02.mkv")
    resolved, ok, error = resolve_and_validate([str(f), missing], {})
    assert ok is False
    assert missing in error
