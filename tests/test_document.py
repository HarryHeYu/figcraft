"""Document IO: deterministic serialization, atomic writes, sidecar lock, revision guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papercanvas.core.document import (
    FigureDocument,
    file_lock,
    lock_path_for,
    read_revision,
    serialize_figure,
)
from papercanvas.core.errors import (
    DocumentConflictError,
    DocumentLockError,
    FigureValidationError,
)
from papercanvas.core.models import Figure


@pytest.fixture
def ir_file(tmp_path: Path, figure_dict: dict) -> Path:
    path = tmp_path / "fig.json"
    path.write_bytes(serialize_figure(Figure.model_validate(figure_dict)))
    return path


def test_load_and_roundtrip_is_byte_stable(ir_file: Path, figure_dict: dict) -> None:
    doc = FigureDocument.load(ir_file)
    assert doc.figure.id == "fig_test"
    assert doc.figure.revision == 1
    assert serialize_figure(doc.figure) == ir_file.read_bytes()
    assert figure_dict  # fixture untouched


def test_load_missing_file_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="file not found"):
        FigureDocument.load(tmp_path / "nope.json")


def test_load_broken_json_is_a_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_bytes(b"{ not json ")
    with pytest.raises(FigureValidationError, match="not valid JSON"):
        FigureDocument.load(path)


def test_load_schema_violation_lists_location(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(json.dumps({"schema_version": "0.1", "nodes": []}).encode())
    with pytest.raises(FigureValidationError) as excinfo:
        FigureDocument.load(path)
    assert any("id" in e for e in excinfo.value.errors)


def test_create_refuses_overwrite(ir_file: Path, figure_dict: dict) -> None:
    figure = Figure.model_validate(figure_dict)
    with pytest.raises(DocumentConflictError, match="refusing to overwrite"):
        FigureDocument.create(ir_file, figure)


def test_serialize_is_deterministic(figure_dict: dict) -> None:
    fig = Figure.model_validate(figure_dict)
    assert serialize_figure(fig) == serialize_figure(fig.model_copy(deep=True))


def test_expected_revision_conflict_leaves_file_untouched(
    ir_file: Path, figure_dict: dict
) -> None:
    doc = FigureDocument.load(ir_file)
    before = ir_file.read_bytes()

    # Simulate another process committing revision 2 behind our back.
    other = Figure.model_validate(figure_dict)
    other.revision = 2
    FigureDocument(ir_file, other).save()
    external = ir_file.read_bytes()
    assert external != before

    stale = doc.figure.model_copy(deep=True)
    stale.revision = 5  # pretend we edited based on the stale revision 1 read
    with pytest.raises(DocumentConflictError, match="expected on-disk revision 1"):
        doc.save_figure(stale, expected_revision=1)
    assert ir_file.read_bytes() == external


def test_save_creates_no_temp_litter(ir_file: Path) -> None:
    doc = FigureDocument.load(ir_file)
    doc.figure.revision = 7
    doc.save()
    siblings = list(ir_file.parent.iterdir())
    assert siblings == [ir_file]


def test_lock_blocks_concurrent_writer(ir_file: Path) -> None:
    doc = FigureDocument.load(ir_file)
    doc.figure.revision = 2
    with file_lock(lock_path_for(ir_file)):
        with pytest.raises(DocumentLockError, match="held by another process"):
            doc.save(timeout=0.2)
    # lock released -> save works now
    doc.save()
    assert read_revision(ir_file) == 2


def test_stale_lock_file_is_the_only_obstacle(tmp_path: Path) -> None:
    lock = tmp_path / "fig.json.lock"
    lock.write_bytes(b"999999\n")
    target = tmp_path / "fig.json"
    figure = Figure.model_validate(
        {
            "schema_version": "0.1",
            "id": "stale",
            "canvas": {"width": 10, "height": 10},
        }
    )
    with pytest.raises(DocumentLockError):
        FigureDocument.create(target, figure)
    # ...and the failed write must not have left a half-written file
    assert not target.exists()
    assert lock.exists()


def test_read_revision_tolerates_garbage(tmp_path: Path) -> None:
    assert read_revision(tmp_path / "absent.json") is None
    garbage = tmp_path / "garbage.json"
    garbage.write_bytes(b"{{{")
    assert read_revision(garbage) is None
    # a schema-valid object without a revision field counts as the default 1
    no_rev = tmp_path / "norev.json"
    no_rev.write_bytes(
        b'{"schema_version": "0.1", "id": "x", "canvas": {"width": 10, "height": 10}}'
    )
    assert read_revision(no_rev) == 1
    # lax coercion mirrors the loader: "2" loads as revision 2
    str_rev = tmp_path / "strrev.json"
    str_rev.write_bytes(
        b'{"schema_version": "0.1", "id": "x", "revision": "2", '
        b'"canvas": {"width": 10, "height": 10}}'
    )
    assert read_revision(str_rev) == 2


def test_load_tolerates_utf8_bom(tmp_path: Path, figure_dict: dict) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + serialize_figure(Figure.model_validate(figure_dict)))
    doc = FigureDocument.load(path)
    assert doc.figure.id == "fig_test"


def test_deeply_nested_json_is_a_clean_error(tmp_path: Path) -> None:
    """A legal but 60k-level nested JSON array must never leak a RecursionError.

    The failure mode differs by platform (CPython 3.14's json parser survives
    nesting that raises RecursionError on 3.12/Windows): either the parser
    raises RecursionError -> "too deep", or it parses and the schema rejects a
    non-dict root. Both must surface as FigureValidationError.
    """
    path = tmp_path / "deep.json"
    path.write_bytes(b"[" * 60000 + b"]" * 60000)
    with pytest.raises(FigureValidationError):
        FigureDocument.load(path)
    assert read_revision(path) is None


def test_string_revision_file_is_patchable(tmp_path: Path, figure_dict: dict) -> None:
    """A file with revision:"2" loads as revision 2 and stays patchable."""
    import json

    figure_dict["revision"] = "2"  # stays a string on disk
    path = tmp_path / "fig.json"
    path.write_bytes(json.dumps(figure_dict).encode("utf-8"))
    doc = FigureDocument.load(path)
    assert doc.figure.revision == 2

    from papercanvas.core.patch import PatchRequest, apply_patch

    result = apply_patch(
        doc,
        PatchRequest(operations=[{"op": "move_node", "id": "a", "x": 1, "y": 1}]),
    )
    assert result.revision == 3
