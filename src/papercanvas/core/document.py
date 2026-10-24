"""On-disk figure documents: load, hard-validate, and transactional atomic writes.

Write discipline (engineering constraint 3): every mutation of an IR file goes
through :meth:`FigureDocument.save_figure` under a sidecar lock (``O_EXCL``,
timeout -> error, stale locks are never stolen) with an ``expected_revision``
optimistic-concurrency check, writing to a temp file and ``os.replace`` into
place. Read-only operations (render / lint / inspect) must never write.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError as PydanticValidationError

from .errors import DocumentConflictError, DocumentLockError, FigureValidationError
from .models import Figure
from .validate import ensure_valid

if TYPE_CHECKING:
    from collections.abc import Iterator

LOCK_TIMEOUT_S = 10.0
LOCK_POLL_S = 0.05


def serialize_figure(fig: Figure) -> bytes:
    """Deterministic on-disk bytes for a figure (same IR -> same bytes)."""
    payload = json.dumps(
        fig.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (payload + "\n").encode("utf-8")


def lock_path_for(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


@contextmanager
def file_lock(
    path: Path, timeout: float = LOCK_TIMEOUT_S, poll: float = LOCK_POLL_S
) -> Iterator[None]:
    """Sidecar lock via ``O_CREAT | O_EXCL``.

    Stale locks are deliberately never stolen: on timeout we raise
    DocumentLockError and the user clears the ``.lock`` file manually.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise DocumentLockError(
                    f"lock {path} is held by another process "
                    f"(waited {timeout:g}s); if you are sure no process is "
                    f"writing, delete the .lock file manually"
                ) from None
            time.sleep(poll)
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    except OSError:
        pass  # diagnostics only
    try:
        yield
    finally:
        os.close(fd)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp file in the same dir + os.replace)."""
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def read_revision(path: Path) -> int | None:
    """Return the revision stored in the file at ``path``.

    The value is read through the same schema the loader uses, so a
    hand-written file without ``revision`` counts as 1 (the schema default)
    and lax coercions (e.g. ``"revision": "2"``) behave identically to a
    reload. Returns None only when the file is absent or schema-invalid.
    """
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        return None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    except RecursionError:
        return None
    try:
        return Figure.model_validate(data).revision
    except PydanticValidationError:
        return None


class FigureDocument:
    """A Figure IR bound to its on-disk location."""

    def __init__(self, path: Path, figure: Figure) -> None:
        self.path = path
        self.figure = figure

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> FigureDocument:
        p = Path(path)
        try:
            raw = p.read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"{p}: file not found") from exc
        try:
            # utf-8-sig transparently tolerates a UTF-8 BOM, which agents and
            # Windows editors occasionally emit
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FigureValidationError([f"{p}: not valid JSON: {exc}"]) from exc
        except RecursionError as exc:
            raise FigureValidationError(
                [f"{p}: JSON nesting too deep to parse"]
            ) from exc
        try:
            figure = Figure.model_validate(data)
        except PydanticValidationError as exc:
            lines = [f"{p}: Figure IR schema violation:"]
            for err in exc.errors():
                loc = ".".join(str(part) for part in err["loc"]) or "<root>"
                lines.append(f"  - {loc}: {err['msg']}")
            raise FigureValidationError(lines) from exc
        ensure_valid(figure)
        return cls(p, figure)

    @classmethod
    def create(cls, path: str | os.PathLike[str], figure: Figure) -> FigureDocument:
        """Create a new IR file; refuses to overwrite an existing file."""
        p = Path(path)
        if p.exists():
            raise DocumentConflictError(f"{p}: already exists; refusing to overwrite")
        ensure_valid(figure)
        doc = cls(p, figure)
        doc.save()
        return doc

    def save(
        self,
        *,
        expected_revision: int | None = None,
        timeout: float = LOCK_TIMEOUT_S,
    ) -> None:
        self.save_figure(self.figure, expected_revision=expected_revision, timeout=timeout)

    def save_figure(
        self,
        fig: Figure,
        *,
        expected_revision: int | None = None,
        timeout: float = LOCK_TIMEOUT_S,
    ) -> None:
        """Validate then atomically write ``fig`` to this document's path.

        ``expected_revision`` is checked against the file **on disk inside the
        lock**, so a writer who loaded revision N fails cleanly if another
        process has since committed revision N+1.
        """
        ensure_valid(fig)
        with file_lock(lock_path_for(self.path), timeout=timeout):
            if expected_revision is not None:
                disk_revision = read_revision(self.path)
                if disk_revision != expected_revision:
                    raise DocumentConflictError(
                        f"{self.path}: expected on-disk revision "
                        f"{expected_revision}, found {disk_revision}; "
                        f"reload the file and reapply"
                    )
            atomic_write(self.path, serialize_figure(fig))
