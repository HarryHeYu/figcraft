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


# -- data safety: crashes, stale locks, temp litter --------------------------


def test_crash_between_temp_write_and_replace_leaves_original_intact(
    ir_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the process dies after writing the temp file but before os.replace,
    the on-disk IR must be untouched and no temp litter may remain."""
    before = ir_file.read_bytes()
    doc = FigureDocument.load(ir_file)
    doc.figure.revision = 9

    def exploding_replace(src, dst, **kwargs):
        raise OSError("simulated crash right before the atomic swap")

    monkeypatch.setattr("papercanvas.core.document.os.replace", exploding_replace)
    with pytest.raises(OSError, match="simulated crash"):
        doc.save()

    monkeypatch.undo()
    assert ir_file.read_bytes() == before  # the old revision survives
    assert [p for p in ir_file.parent.iterdir() if ".tmp-" in p.name] == []

    doc.save()  # a healthy retry then succeeds
    assert read_revision(ir_file) == 9


def test_stale_lock_error_names_the_holding_pid(tmp_path: Path, figure_dict: dict) -> None:
    """A crashed writer leaves the .lock sidecar behind; the error must tell
    the user which process held it and that manual cleanup is possible."""
    import json as _json

    target = tmp_path / "fig.json"
    target.write_text(_json.dumps(figure_dict), encoding="utf-8")
    lock = lock_path_for(target)
    lock.write_bytes(b"424242\n")  # pid of the "crashed" writer

    doc = FigureDocument.load(target)
    doc.figure.revision = 2
    with pytest.raises(DocumentLockError) as excinfo:
        doc.save(timeout=0.2)
    assert "424242" in str(excinfo.value)
    assert "delete the .lock" in str(excinfo.value)

    # the failed attempt changed nothing and did not steal the lock
    assert _json.loads(target.read_text(encoding="utf-8"))["revision"] == 1
    assert lock.exists()

    lock.unlink()  # the documented manual cleanup
    doc.save()
    assert read_revision(target) == 2
    assert not lock.exists()  # a successful save releases its own lock


def test_failed_save_leaves_no_temp_litter(
    ir_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = ir_file.read_bytes()
    doc = FigureDocument.load(ir_file)

    def exploding_fsync(fh):
        raise OSError("disk went away mid-fsync")

    monkeypatch.setattr("papercanvas.core.document.os.fsync", exploding_fsync)
    with pytest.raises(OSError, match="mid-fsync"):
        doc.save()

    monkeypatch.undo()
    assert ir_file.read_bytes() == before
    assert sorted(p.name for p in ir_file.parent.iterdir()) == [ir_file.name]


def test_lock_survives_reader_traffic(ir_file: Path) -> None:
    """Loading (read-only) never blocks on or removes a concurrent lock."""
    import json as _json

    lock = lock_path_for(ir_file)
    lock.write_bytes(b"999\n")
    doc = FigureDocument.load(ir_file)  # read path is lock-free
    assert doc.figure.revision == 1
    assert lock.exists()  # untouched by the reader
    assert _json.loads(_json.dumps(doc.figure.model_dump(mode="json")))["revision"] == 1
    lock.unlink()


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
