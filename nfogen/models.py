"""Modeles de donnees du coeur de nfogen.

Le coeur ne connait aucun tracker ni aucun format en particulier : il se
contente de transporter un contexte (`RenderContext`) entre la source et le
renderer choisi via le registre de profils.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class RenderContext:
    """Tout ce dont un renderer a besoin pour produire un NFO."""

    profile: str
    category: str
    source: Optional[Path] = None
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
