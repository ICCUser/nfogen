"""nfogen : generateur de fichiers NFO modulaire base sur des profils."""
from __future__ import annotations

from .engine import detect_category, generate, list_available
from .models import RenderContext
from .registry import (
    available,
    get_filename_rule,
    get_renderer,
    get_validator,
    register,
    register_filename,
    register_validator,
)

__version__ = "0.1.0"
__all__ = [
    "generate",
    "detect_category",
    "list_available",
    "RenderContext",
    "register",
    "get_renderer",
    "register_validator",
    "get_validator",
    "register_filename",
    "get_filename_rule",
    "available",
]
