"""Exception hierarchy for PaperCanvas."""

from __future__ import annotations


class PaperCanvasError(Exception):
    """Base class for every error PaperCanvas raises on purpose."""


class FigureValidationError(PaperCanvasError):
    """The figure violates hard IR rules and must not be written or rendered."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__(
            "figure validation failed:\n" + "\n".join(f"  - {e}" for e in self.errors)
        )


class DocumentConflictError(PaperCanvasError):
    """The on-disk revision no longer matches expected_revision."""


class DocumentLockError(PaperCanvasError):
    """The sidecar file lock could not be acquired within the timeout."""


class PatchError(PaperCanvasError):
    """A semantic patch operation is invalid."""


class LayoutError(PaperCanvasError):
    """Automatic layout cannot proceed (e.g. a dependency cycle)."""


class RenderError(PaperCanvasError):
    """A renderer cannot produce output from the current figure state."""


class FontError(PaperCanvasError):
    """A requested font family cannot be resolved to a usable font file."""
