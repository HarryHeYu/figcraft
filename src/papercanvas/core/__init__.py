"""Core layer: Figure IR models, hard validation, document IO, patch engine, units."""

from papercanvas.core.document import FigureDocument
from papercanvas.core.errors import (
    DocumentConflictError,
    DocumentLockError,
    FigureValidationError,
    LayoutError,
    PaperCanvasError,
    PatchError,
    RenderError,
)
from papercanvas.core.models import Figure
from papercanvas.core.patch import PatchRequest, apply_patch
from papercanvas.core.validate import ensure_valid, validate_figure

__all__ = [
    "DocumentConflictError",
    "DocumentLockError",
    "Figure",
    "FigureDocument",
    "FigureValidationError",
    "LayoutError",
    "PaperCanvasError",
    "PatchError",
    "PatchRequest",
    "RenderError",
    "apply_patch",
    "ensure_valid",
    "validate_figure",
]
