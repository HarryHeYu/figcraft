"""Patch engine: all nine operations, transaction semantics, revision bookkeeping.

Includes constraint-6 tests: a failed patch must leave the on-disk file
byte-for-byte unchanged, and a successful patch must commit revision+1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papercanvas.core.document import FigureDocument
from papercanvas.core.errors import DocumentConflictError, PatchError
from papercanvas.core.models import Figure
from papercanvas.core.patch import PatchRequest, apply_patch


@pytest.fixture
def ir_file(tmp_path: Path, figure_dict: dict) -> Path:
    path = tmp_path / "fig.json"
    FigureDocument.create(path, Figure.model_validate(figure_dict))
    return path


def _apply(path: Path, *operations: dict, expected_revision: int | None = None):
    doc = FigureDocument.load(path)
    return apply_patch(
        doc, PatchRequest(operations=list(operations), expected_revision=expected_revision)
    )


# -- each of the nine operations -------------------------------------------


def test_add_node(ir_file: Path) -> None:
    result = _apply(
        ir_file,
        {
            "op": "add_node",
            "node": {"id": "c", "type": "rect", "label": "C", "x": 5, "y": 5, "w": 10, "h": 10},
        },
    )
    assert result.revision == 2
    fig = FigureDocument.load(ir_file).figure
    assert fig.node("c") is not None
    assert fig.revision == 2


def test_add_node_duplicate_id_rejected(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="already in use"):
        _apply(ir_file, {"op": "add_node", "node": {"id": "a", "x": 1, "y": 1, "w": 5, "h": 5}})


def test_update_node_partial(ir_file: Path) -> None:
    _apply(ir_file, {"op": "update_node", "id": "a", "x": 12.5, "label": "Alpha v2"})
    fig = FigureDocument.load(ir_file).figure
    node = fig.node("a")
    assert (node.x, node.w) == (12.5, 30.0)  # only requested fields moved
    assert node.label == "Alpha v2"


def test_update_node_bad_size_rejected(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="must be > 0"):
        _apply(ir_file, {"op": "update_node", "id": "a", "w": -2})


def test_set_style_merges_and_keeps_other_fields(ir_file: Path) -> None:
    _apply(ir_file, {"op": "set_style", "target": "a", "style": {"fill": "#FCE4CF"}})
    node = FigureDocument.load(ir_file).figure.node("a")
    assert node.style.fill == "#FCE4CF"
    assert node.style.stroke == "#4275C4"  # untouched by the merge


def test_set_style_with_palette_key(ir_file: Path) -> None:
    _apply(ir_file, {"op": "set_style", "target": "a", "style": {"fill": "accent"}})
    assert FigureDocument.load(ir_file).figure.node("a").style.fill == "accent"


def test_set_style_invalid_color_rejected_and_file_untouched(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    with pytest.raises(PatchError):
        _apply(ir_file, {"op": "set_style", "target": "a", "style": {"fill": "orange"}})
    assert ir_file.read_bytes() == before


def test_set_style_on_edge(ir_file: Path) -> None:
    _apply(
        ir_file,
        {"op": "set_style", "target": "e1", "style": {"stroke": "#FF0000", "arrow": "none"}},
    )
    edge = FigureDocument.load(ir_file).figure.edge("e1")
    assert edge.style.stroke == "#FF0000"
    assert edge.style.arrow == "none"


def test_set_style_edge_rejects_node_only_fields(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="no field"):
        _apply(ir_file, {"op": "set_style", "target": "e1", "style": {"fill": "#FF0000"}})


def test_add_edge(ir_file: Path) -> None:
    _apply(
        ir_file,
        {
            "op": "add_edge",
            "edge": {
                "id": "e2",
                "source": "b",
                "target": "a",
                "source_port": "top",
                "target_port": "bottom",
            },
        },
    )
    fig = FigureDocument.load(ir_file).figure
    assert fig.edge("e2").target_port == "bottom"


def test_add_edge_dangling_rejected(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="not a node"):
        _apply(ir_file, {"op": "add_edge", "edge": {"id": "e3", "source": "a", "target": "ghost"}})


def test_add_edge_self_loop_rejected(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="self-loop"):
        _apply(ir_file, {"op": "add_edge", "edge": {"id": "e3", "source": "a", "target": "a"}})


def test_remove_edge(ir_file: Path) -> None:
    _apply(ir_file, {"op": "remove_edge", "id": "e1"})
    assert FigureDocument.load(ir_file).figure.edge("e1") is None


def test_add_group(ir_file: Path) -> None:
    _apply(
        ir_file,
        {"op": "add_group", "group": {"id": "g1", "children": ["a"], "label": "Stage 1"}},
    )
    group = FigureDocument.load(ir_file).figure.group("g1")
    assert group.children == ["a"]
    assert group.style.stroke_dash == "dashed"  # default group styling


def test_add_group_double_claim_rejected(ir_file: Path) -> None:
    _apply(ir_file, {"op": "add_group", "group": {"id": "g1", "children": ["a"]}})
    with pytest.raises(PatchError, match="already claimed"):
        _apply(ir_file, {"op": "add_group", "group": {"id": "g2", "children": ["a"]}})


def test_update_label_node_and_group(ir_file: Path) -> None:
    _apply(
        ir_file,
        {"op": "update_label", "target": "a", "label": "Renamed"},
        {"op": "add_group", "group": {"id": "g1", "children": ["a"]}},
        {"op": "update_label", "target": "g1", "label": "The Group"},
    )
    fig = FigureDocument.load(ir_file).figure
    assert fig.node("a").label == "Renamed"
    assert fig.group("g1").label == "The Group"


def test_move_node(ir_file: Path) -> None:
    _apply(ir_file, {"op": "move_node", "id": "a", "x": 1.5, "y": 2.5})
    node = FigureDocument.load(ir_file).figure.node("a")
    assert (node.x, node.y) == (1.5, 2.5)


def test_remove_node_requires_explicit_edge_handling(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="remove_edges=true"):
        _apply(ir_file, {"op": "remove_node", "id": "a"})
    _apply(ir_file, {"op": "remove_node", "id": "a", "remove_edges": True})
    fig = FigureDocument.load(ir_file).figure
    assert fig.node("a") is None
    assert fig.edge("e1") is None  # the connected edge went with the node


def test_remove_node_in_group_rejected(ir_file: Path) -> None:
    _apply(ir_file, {"op": "add_group", "group": {"id": "g1", "children": ["a"]}})
    with pytest.raises(PatchError, match="group"):
        _apply(ir_file, {"op": "remove_node", "id": "a", "remove_edges": True})


# -- transaction semantics --------------------------------------------------


def test_failed_batch_leaves_file_byte_identical(ir_file: Path) -> None:
    """Constraint 6e: a patch that fails mid-batch writes nothing at all."""
    before = ir_file.read_bytes()
    with pytest.raises(PatchError, match="operation 1"):
        _apply(
            ir_file,
            {"op": "update_label", "target": "a", "label": "First op is fine"},
            {"op": "add_edge", "edge": {"id": "e_bad", "source": "a", "target": "ghost"}},
        )
    assert ir_file.read_bytes() == before
    fig = FigureDocument.load(ir_file).figure
    assert fig.revision == 1
    assert fig.node("a").label == "Alpha"


def test_expected_revision_conflict_rejected(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    with pytest.raises(DocumentConflictError, match="does not match"):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": 0, "y": 0}, expected_revision=99)
    assert ir_file.read_bytes() == before


def test_successful_patch_bumps_revision_on_disk(ir_file: Path) -> None:
    """Constraint 6b (patch side): success commits revision+1 to the file."""
    result = _apply(
        ir_file,
        {"op": "move_node", "id": "a", "x": 0, "y": 0},
        expected_revision=1,
    )
    assert result.revision == 2
    on_disk = json.loads(ir_file.read_bytes().decode("utf-8"))
    assert on_disk["revision"] == 2


def test_chained_patches_increment_revision(ir_file: Path) -> None:
    assert _apply(ir_file, {"op": "move_node", "id": "a", "x": 1, "y": 1}).revision == 2
    assert _apply(ir_file, {"op": "move_node", "id": "a", "x": 2, "y": 2}).revision == 3


def test_empty_patch_rejected(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="no operations"):
        _apply(ir_file)


def test_unknown_op_rejected(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    with pytest.raises(PatchError, match="unknown op"):
        _apply(ir_file, {"op": "teleport_node", "id": "a"})
    assert ir_file.read_bytes() == before


def test_unknown_field_in_op_rejected(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="unknown field"):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": 1, "y": 1, "z": 1})


# -- regression: malformed payloads must be clean PatchErrors, never corruption


def test_update_node_rejects_invalid_type_and_file_stays_loadable(ir_file: Path) -> None:
    """P0 regression: setattr must not bypass schema validation."""
    before = ir_file.read_bytes()
    with pytest.raises(PatchError, match="operation 0"):
        _apply(ir_file, {"op": "update_node", "id": "a", "type": "bogus"})
    assert ir_file.read_bytes() == before
    FigureDocument.load(ir_file)  # the file must still be a valid IR


def test_update_node_rejects_wrong_value_types(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    for bad in ({"x": [1, 2]}, {"label": 123}, {"x": True}):
        with pytest.raises(PatchError, match="operation 0"):
            _apply(ir_file, {"op": "update_node", "id": "a", **bad})
    assert ir_file.read_bytes() == before


def test_update_node_coerces_numeric_strings_like_add_node(ir_file: Path) -> None:
    """Same lax coercion on both write paths — no more behavioral split."""
    _apply(ir_file, {"op": "update_node", "id": "a", "x": "12.5"})
    assert FigureDocument.load(ir_file).figure.node("a").x == 12.5


def test_move_node_rejects_nan_and_booleans(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    with pytest.raises(PatchError):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": float("nan"), "y": 0})
    with pytest.raises(PatchError):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": True, "y": False})
    assert ir_file.read_bytes() == before


def test_add_node_bad_payload_is_clean_patch_error(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    with pytest.raises(PatchError, match="operation 0"):
        _apply(ir_file, {"op": "add_node", "node": {"id": "bad id", "x": 1, "y": 1}})
    with pytest.raises(PatchError, match="operation 0"):
        _apply(
            ir_file,
            {"op": "add_node", "node": {"id": "c", "type": "circle", "x": 1, "y": 1}},
        )
    with pytest.raises(PatchError, match="operation 0"):
        _apply(ir_file, {"op": "add_node", "node": "not-an-object"})
    assert ir_file.read_bytes() == before


def test_add_edge_and_group_bad_payloads_are_clean(ir_file: Path) -> None:
    with pytest.raises(PatchError):
        _apply(
            ir_file,
            {
                "op": "add_edge",
                "edge": {"id": "e9", "source": "a", "target": "b", "source_port": "diag"},
            },
        )
    with pytest.raises(PatchError):
        _apply(ir_file, {"op": "add_group", "group": {"id": "g9", "children": "a"}})


def test_remove_edges_string_is_not_truthy(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="remove_edges=true"):
        _apply(ir_file, {"op": "remove_node", "id": "a", "remove_edges": "yes"})
    assert FigureDocument.load(ir_file).figure.node("a") is not None


def test_expected_revision_must_be_an_integer(ir_file: Path) -> None:
    with pytest.raises(PatchError, match="expected_revision"):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": 0, "y": 0}, expected_revision="1")
    with pytest.raises(PatchError, match="expected_revision"):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": 0, "y": 0}, expected_revision=True)


def test_operations_container_is_validated(ir_file: Path) -> None:
    doc = FigureDocument.load(ir_file)
    with pytest.raises(PatchError, match="must be a list"):
        apply_patch(doc, PatchRequest(operations="move_node"))  # type: ignore[arg-type]
    with pytest.raises(PatchError, match="must be a JSON object"):
        mixed: list = [{"op": "move_node", "id": "a", "x": 0, "y": 0}, 5]
        apply_patch(doc, PatchRequest(operations=mixed))  # type: ignore[arg-type]


def test_set_style_nan_width_is_clean_error(ir_file: Path) -> None:
    before = ir_file.read_bytes()
    with pytest.raises(PatchError):
        _apply(ir_file, {"op": "set_style", "target": "a", "style": {"stroke_width": float("nan")}})
    assert ir_file.read_bytes() == before


# -- round-2 verification regressions ---------------------------------------


def test_move_node_rejects_oversized_integer(ir_file: Path) -> None:
    """A 400-digit JSON int must be a clean error, not an OverflowError traceback."""
    huge = 10**400
    with pytest.raises(PatchError, match="operation 0"):
        _apply(ir_file, {"op": "move_node", "id": "a", "x": huge, "y": 0})
    assert FigureDocument.load(ir_file).figure.node("a").x == 10.0  # untouched


def test_boolean_stroke_width_rejected(ir_file: Path) -> None:
    """Lax pydantic would coerce true→1.0; numeric fields refuse booleans."""
    with pytest.raises(PatchError):
        _apply(ir_file, {"op": "set_style", "target": "a", "style": {"stroke_width": True}})
    with pytest.raises(PatchError):
        _apply(
            ir_file,
            {"op": "add_node", "node": {"id": "c", "x": 1, "y": 1, "w": True, "h": 5}},
        )
