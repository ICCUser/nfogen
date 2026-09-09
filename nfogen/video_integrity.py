"""Verification physique du fichier video avant un upload DIRECT C411
(jamais un brouillon) -- AUTOMATION.md, sous-projet 7 (repris
2026-09-09). Complementaire (pas un doublon) des verifications de
conformite tracker deja existantes (name_proposal.py, groupe
GroupProposal.blocked) : ici on verifie que le fichier lui-meme est
reellement lisible de bout en bout, pas les regles de nommage/categorie.

Necessite ffmpeg + ffprobe sur le PATH (voir has_ffmpeg()) -- deja
utilise comme outil de TEST dans tests/test_c411.py (HAS_FFMPEG), promu
ici en dependance d'execution reelle (voir Dockerfile/README).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field

DURATION_TOLERANCE_SECONDS = 5.0
AV_SYNC_TOLERANCE_SECONDS = 0.5


@dataclass
class VideoIntegrityReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
