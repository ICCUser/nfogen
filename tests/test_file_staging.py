"""Tests de nfogen.file_staging (mise en scene avant creation d'un
.torrent -- jamais le fichier original, voir AUTOMATION.md, sous-projet 2)."""
from __future__ import annotations

import errno
import os
import threading

import pytest

from nfogen.cancellation import OperationCancelled
from nfogen.file_staging import stage_file, stage_files


def test_stage_file_creates_a_hardlink_when_possible(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"

    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_text() == "contenu"
    # meme inode = hardlink reel, pas une copie (0 octet supplementaire)
    assert target.stat().st_ino == source.stat().st_ino


def test_stage_file_falls_back_to_copy_on_exdev(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_text() == "contenu"


def test_stage_file_reraises_other_os_errors(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "link", fake_link)
    with pytest.raises(OSError):
        stage_file(str(source), str(target))


def test_stage_file_raises_file_exists_error_when_target_already_present(tmp_path):
    """Incident reel signale par l'utilisateur (2026-09-06) : un fichier
    laisse par un essai precedent faisait planter la mise en scene avec un
    OSError brut ('[Errno 17] File exists'). Toujours une erreur par
    defaut (sans `overwrite`), mais un type precis (FileExistsError,
    deja ce que Python leve nativement pour EEXIST) plutot qu'une
    exploration au cas par cas par l'appelant."""
    source = tmp_path / "source.mkv"
    source.write_text("nouveau contenu")
    target = tmp_path / "staged.mkv"
    target.write_text("ancien contenu (dechet)")

    with pytest.raises(FileExistsError):
        stage_file(str(source), str(target))

    assert target.read_text() == "ancien contenu (dechet)"  # jamais touche sans overwrite


def test_stage_file_skips_when_target_already_matches_source_size(tmp_path):
    """Incident reel (2026-09-06) : un pack deja entierement mis en scene
    lors d'un essai precedent se faisait integralement re-copier a chaque
    nouvelle tentative de Confirmer -- vecu comme un re-telechargement par
    l'utilisateur (source sur un montage reseau distinct du dossier de
    mise en scene, hardlink impossible -> copie complete). Une cible deja
    de la MEME TAILLE que la source est consideree deja en place : ni
    hardlink ni copie refaits, meme sans `overwrite`."""
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")  # 10 octets
    target = tmp_path / "staged.mkv"
    target.write_bytes(b"XXXXXXXXXX")  # 10 octets aussi, contenu different -- jamais touche

    result = stage_file(str(source), str(target))

    assert result == str(target)
    assert target.read_bytes() == b"XXXXXXXXXX"  # inchange : jamais relie/recopie
    assert target.stat().st_ino != source.stat().st_ino  # pas un hardlink (jamais tente)


def test_stage_file_skip_reports_full_progress(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")
    target = tmp_path / "staged.mkv"
    target.write_bytes(b"XXXXXXXXXX")
    calls: list[tuple[int, int]] = []

    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert calls == [(10, 10)]


def test_stage_files_skips_an_already_matching_file_in_a_pack(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 20)
    target_dir = tmp_path / "staged" / "Release.Name"
    target_dir.mkdir(parents=True)
    (target_dir / "E01.mkv").write_bytes(b"z" * 10)  # deja en place, meme taille

    results = stage_files([str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"])

    assert (target_dir / "E01.mkv").read_bytes() == b"z" * 10  # jamais retouche
    assert (target_dir / "E02.mkv").read_bytes() == b"b" * 20  # mis en scene normalement
    assert results == [str(target_dir / "E01.mkv"), str(target_dir / "E02.mkv")]


def test_stage_file_overwrite_replaces_an_existing_target(tmp_path):
    """`overwrite=True` (AUTOMATION.md, sous-projet 8 -- deja traite/pas
    encore traite) : supprime la cible existante puis refait le lien/la
    copie DEPUIS LA SOURCE LOCALE -- jamais un nouveau telechargement,
    la source Radarr/Sonarr n'est jamais touchee (voir docstring du
    module)."""
    source = tmp_path / "source.mkv"
    source.write_text("nouveau contenu")
    target = tmp_path / "staged.mkv"
    target.write_text("ancien contenu (dechet)")

    result = stage_file(str(source), str(target), overwrite=True)

    assert result == str(target)
    assert target.read_text() == "nouveau contenu"


def test_stage_file_overwrite_is_a_noop_when_target_absent(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"

    result = stage_file(str(source), str(target), overwrite=True)

    assert result == str(target)
    assert target.read_text() == "contenu"


def test_stage_files_overwrite_replaces_an_existing_target_in_a_pack(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_text("un (nouveau)")
    src2 = tmp_path / "e02.mkv"
    src2.write_text("deux")
    target_dir = tmp_path / "staged" / "Release.Name"
    target_dir.mkdir(parents=True)
    (target_dir / "E01.mkv").write_text("un (dechet)")

    results = stage_files(
        [str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"], overwrite=True
    )

    assert results == [str(target_dir / "E01.mkv"), str(target_dir / "E02.mkv")]
    assert (target_dir / "E01.mkv").read_text() == "un (nouveau)"
    assert (target_dir / "E02.mkv").read_text() == "deux"


def test_stage_files_stages_each_source_under_its_own_name(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_text("un")
    src2 = tmp_path / "e02.mkv"
    src2.write_text("deux")
    target_dir = tmp_path / "staged" / "Release.Name"

    results = stage_files([str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"])

    assert results == [str(target_dir / "E01.mkv"), str(target_dir / "E02.mkv")]
    assert (target_dir / "E01.mkv").read_text() == "un"
    assert (target_dir / "E02.mkv").read_text() == "deux"


def test_stage_file_hardlink_reports_progress_once(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_text("contenu")
    target = tmp_path / "staged" / "Release.Name.mkv"
    calls: list[tuple[int, int]] = []

    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert calls == [(len("contenu"), len("contenu"))]


def test_stage_file_copy_reports_progress_in_chunks(tmp_path, monkeypatch):
    import nfogen.file_staging as file_staging_module

    monkeypatch.setattr(file_staging_module, "_COPY_CHUNK_SIZE", 4)  # force plusieurs blocs
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")  # 10 octets, 4 par bloc -> 3 appels (4,4,2)
    target = tmp_path / "staged.mkv"
    calls: list[tuple[int, int]] = []

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    stage_file(str(source), str(target), on_progress=lambda done, total: calls.append((done, total)))

    assert target.read_bytes() == b"0123456789"
    assert calls == [(4, 10), (8, 10), (10, 10)]


def test_stage_file_copy_cancellation_removes_partial_file_and_raises(tmp_path, monkeypatch):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"0123456789")
    target = tmp_path / "staged.mkv"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        stage_file(str(source), str(target), cancel_event=cancel_event)

    assert not target.exists()


def test_stage_files_aggregates_progress_across_multiple_files(tmp_path):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 20)
    target_dir = tmp_path / "staged" / "Release.Name"
    calls: list[tuple[int, int]] = []

    stage_files(
        [str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"],
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls[-1] == (30, 30)  # tout copie a la fin (hardlink, meme volume ici -- 2 appels au total)
    assert all(done <= total == 30 for done, total in calls)


def test_stage_files_propagates_cancellation_from_a_file_mid_pack(tmp_path, monkeypatch):
    src1 = tmp_path / "e01.mkv"
    src1.write_bytes(b"a" * 10)
    src2 = tmp_path / "e02.mkv"
    src2.write_bytes(b"b" * 10)
    target_dir = tmp_path / "staged" / "Release.Name"

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fake_link)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        stage_files(
            [str(src1), str(src2)], str(target_dir), ["E01.mkv", "E02.mkv"], cancel_event=cancel_event
        )

    assert not (target_dir / "E01.mkv").exists()
    assert not (target_dir / "E02.mkv").exists()  # jamais tente, la boucle s'arrete au premier fichier


# manifest_dir -- retour utilisateur reel, 2026-09-12 : source sur un NAS
# distant relie en WireGuard site-to-site (montage reseau, donc TOUJOURS
# en repli copie complete cote hardlink -- jamais de hardlink direct
# possible avec la source). Un simple renommage cosmetique du fichier de
# mise en scene (ex. suite au fix de convention x265->H265) forcait une
# retransmission COMPLETE via le reseau distant alors que le contenu
# etait deja rapatrie sous l'ancien nom. Chaque test simule cette
# topologie : `os.link` echoue EXDEV UNIQUEMENT depuis la source d'origine
# (le "NAS distant"), jamais entre deux fichiers deja en scene (le
# "disque local"), pour bien distinguer les deux chemins de code.
def _fake_link_exdev_only_from(source_path: str):
    real_link = os.link

    def fake_link(src, dst):
        if src == source_path:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_link(src, dst)

    return fake_link


def test_stage_file_reuses_already_staged_copy_via_manifest_instead_of_recopying(tmp_path, monkeypatch):
    source = tmp_path / "remote" / "source.mkv"
    source.parent.mkdir()
    source.write_bytes(b"contenu couteux a retransmettre" * 1000)
    manifest_dir = tmp_path / "staging"
    manifest_dir.mkdir()
    old_target = manifest_dir / "Old.Name.mkv"
    new_target = manifest_dir / "New.Name.mkv"

    monkeypatch.setattr(os, "link", _fake_link_exdev_only_from(str(source)))

    # Premiere mise en scene : source "distante" -> seule la copie complete
    # fonctionne (EXDEV), comme attendu.
    stage_file(str(source), str(old_target), manifest_dir=str(manifest_dir))
    assert old_target.read_bytes() == source.read_bytes()

    # Deuxieme mise en scene : MEME source, nouveau nom -- ne doit PAS
    # repasser par la source distante (le fake `os.link` leverait EXDEV
    # si on retentait depuis `source`) : doit reutiliser `old_target` via
    # le manifest et faire un hardlink LOCAL.
    stage_file(str(source), str(new_target), manifest_dir=str(manifest_dir))

    assert new_target.read_bytes() == source.read_bytes()
    assert new_target.stat().st_ino == old_target.stat().st_ino  # hardlink reel, pas une recopie


def test_stage_file_without_manifest_dir_recopies_every_time(tmp_path, monkeypatch):
    """Comportement inchange sans `manifest_dir` (defaut `None`) -- pas de
    raccourci pris, meme scenario que ci-dessus."""
    source = tmp_path / "remote" / "source.mkv"
    source.parent.mkdir()
    source.write_bytes(b"contenu" * 1000)
    staging = tmp_path / "staging"
    staging.mkdir()
    old_target = staging / "Old.Name.mkv"
    new_target = staging / "New.Name.mkv"

    monkeypatch.setattr(os, "link", _fake_link_exdev_only_from(str(source)))

    stage_file(str(source), str(old_target))
    stage_file(str(source), str(new_target))  # sans manifest_dir : nouvelle copie complete, pas de crash

    assert new_target.read_bytes() == source.read_bytes()
    assert new_target.stat().st_ino != old_target.stat().st_ino  # deux copies distinctes


def test_stage_file_manifest_ignores_stale_entry_whose_staged_file_is_gone(tmp_path, monkeypatch):
    """Le manifest n'est qu'une optimisation best-effort : une entree
    perimee (fichier de mise en scene supprime depuis) ne doit jamais
    faire planter, seulement ne pas etre utilisee."""
    source = tmp_path / "remote" / "source.mkv"
    source.parent.mkdir()
    source.write_bytes(b"contenu" * 1000)
    manifest_dir = tmp_path / "staging"
    manifest_dir.mkdir()
    old_target = manifest_dir / "Old.Name.mkv"
    new_target = manifest_dir / "New.Name.mkv"

    monkeypatch.setattr(os, "link", _fake_link_exdev_only_from(str(source)))
    stage_file(str(source), str(old_target), manifest_dir=str(manifest_dir))
    old_target.unlink()  # l'ancienne mise en scene a disparu entre-temps

    stage_file(str(source), str(new_target), manifest_dir=str(manifest_dir))

    assert new_target.read_bytes() == source.read_bytes()  # retombe sur la copie complete, sans planter


def test_stage_files_forwards_manifest_dir_to_each_file_in_a_pack(tmp_path, monkeypatch):
    source = tmp_path / "remote" / "e01.mkv"
    source.parent.mkdir()
    source.write_bytes(b"contenu" * 1000)
    manifest_dir = tmp_path / "staging"
    old_target_dir = manifest_dir / "Old.Name"
    new_target_dir = manifest_dir / "New.Name"

    monkeypatch.setattr(os, "link", _fake_link_exdev_only_from(str(source)))

    stage_files([str(source)], str(old_target_dir), ["E01.mkv"], manifest_dir=str(manifest_dir))
    stage_files([str(source)], str(new_target_dir), ["E01.mkv"], manifest_dir=str(manifest_dir))

    old_target = old_target_dir / "E01.mkv"
    new_target = new_target_dir / "E01.mkv"
    assert new_target.stat().st_ino == old_target.stat().st_ino
