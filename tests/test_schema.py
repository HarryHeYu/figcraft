"""Hard-error matrix for the Figure IR schema and semantic validation."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError as PydanticValidationError

from papercanvas.core.errors import FigureValidationError
from papercanvas.core.models import Figure
from papercanvas.core.validate import ensure_valid, validate_figure


def parse(figure_dict: dict) -> Figure:
    return Figure.model_validate(figure_dict)


def test_minimal_figure_is_valid(figure_dict: dict) -> None:
    fig = parse(figure_dict)
    assert validate_figure(fig) == []
    ensure_valid(fig)


def test_schema_version_must_be_supported(figure_dict: dict) -> None:
    figure_dict["schema_version"] = "9.9"
    errors = validate_figure(parse(figure_dict))
    assert any("schema_version" in e for e in errors)


def test_duplicate_node_ids_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][1]["id"] = "a"
    errors = validate_figure(parse(figure_dict))
    assert any("duplicate id" in e for e in errors)


def test_node_and_edge_id_collision_rejected(figure_dict: dict) -> None:
    figure_dict["edges"][0]["id"] = "a"
    errors = validate_figure(parse(figure_dict))
    assert any("duplicate id" in e for e in errors)


def test_node_and_group_id_collision_rejected(figure_dict: dict) -> None:
    figure_dict["groups"].append({"id": "a", "children": ["b"]})
    errors = validate_figure(parse(figure_dict))
    assert any("duplicate id" in e for e in errors)


def test_dangling_edge_source_rejected(figure_dict: dict) -> None:
    figure_dict["edges"][0]["source"] = "ghost"
    errors = validate_figure(parse(figure_dict))
    assert any("source 'ghost'" in e for e in errors)


def test_dangling_edge_target_rejected(figure_dict: dict) -> None:
    figure_dict["edges"][0]["target"] = "ghost"
    errors = validate_figure(parse(figure_dict))
    assert any("target 'ghost'" in e for e in errors)


def test_self_loop_rejected(figure_dict: dict) -> None:
    figure_dict["edges"][0]["target"] = "a"
    errors = validate_figure(parse(figure_dict))
    assert any("self-loop" in e for e in errors)


def test_illegal_port_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["edges"][0]["source_port"] = "diagonal"
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_node_width_zero_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["w"] = 0
    errors = validate_figure(parse(figure_dict))
    assert any("w must be > 0" in e for e in errors)


def test_node_height_negative_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["h"] = -1.0
    errors = validate_figure(parse(figure_dict))
    assert any("h must be > 0" in e for e in errors)


def test_canvas_size_rejected(figure_dict: dict) -> None:
    figure_dict["canvas"]["width"] = 0
    figure_dict["canvas"]["height"] = -5
    errors = validate_figure(parse(figure_dict))
    assert any("width must be > 0" in e for e in errors)
    assert any("height must be > 0" in e for e in errors)


def test_negative_margin_rejected(figure_dict: dict) -> None:
    figure_dict["canvas"]["margin"] = -0.1
    errors = validate_figure(parse(figure_dict))
    assert any("margin" in e for e in errors)


def test_illegal_color_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["style"]["fill"] = "orange"
    errors = validate_figure(parse(figure_dict))
    assert any("orange" in e and "palette" in e for e in errors)


def test_palette_key_color_is_valid(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["style"]["fill"] = "accent"
    assert validate_figure(parse(figure_dict)) == []


def test_unknown_palette_key_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["style"]["fill"] = "nope"
    errors = validate_figure(parse(figure_dict))
    assert any("nope" in e for e in errors)


def test_zero_stroke_width_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["style"]["stroke_width"] = 0
    errors = validate_figure(parse(figure_dict))
    assert any("stroke_width" in e for e in errors)


def test_palette_value_must_be_hex(figure_dict: dict) -> None:
    figure_dict["theme"]["palette"]["accent"] = "blue"
    errors = validate_figure(parse(figure_dict))
    assert any("palette" in e for e in errors)


def test_group_child_must_exist(figure_dict: dict) -> None:
    figure_dict["groups"].append({"id": "g1", "children": ["ghost"]})
    errors = validate_figure(parse(figure_dict))
    assert any("'ghost' is not a node" in e for e in errors)


def test_group_children_must_not_be_empty(figure_dict: dict) -> None:
    figure_dict["groups"].append({"id": "g1", "children": []})
    errors = validate_figure(parse(figure_dict))
    assert any("children must not be empty" in e for e in errors)


def test_node_claimed_by_two_groups_rejected(figure_dict: dict) -> None:
    figure_dict["groups"].append({"id": "g1", "children": ["a"]})
    figure_dict["groups"].append({"id": "g2", "children": ["a"]})
    errors = validate_figure(parse(figure_dict))
    assert any("already claimed by group" in e for e in errors)


def test_unsupported_unit_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["canvas"]["unit"] = "cm"
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_unknown_field_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["colour"] = "#FF0000"
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_nan_coordinate_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["x"] = math.nan
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_bad_id_format_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["id"] = "has space"
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_font_size_must_be_positive(figure_dict: dict) -> None:
    figure_dict["theme"]["font_size_pt"] = 0
    errors = validate_figure(parse(figure_dict))
    assert any("font_size_pt" in e for e in errors)


def test_boolean_numerics_rejected_at_schema_level(figure_dict: dict) -> None:
    """Lax pydantic would coerce true→1.0 everywhere; IR numeric fields refuse."""
    figure_dict["nodes"][0]["w"] = True
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_boolean_revision_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["revision"] = True
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_boolean_canvas_and_style_rejected_at_schema_level(figure_dict: dict) -> None:
    figure_dict["canvas"]["width"] = True
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)
    figure_dict["canvas"]["width"] = 100.0
    figure_dict["nodes"][0]["style"]["stroke_width"] = True
    with pytest.raises(PydanticValidationError):
        parse(figure_dict)


def test_oversized_dimensions_rejected(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["w"] = 2e7  # ceiling is 1e7 mm
    errors = validate_figure(parse(figure_dict))
    assert any("w must be <=" in e for e in errors)

    figure_dict["nodes"][0]["w"] = 30.0
    figure_dict["canvas"]["width"] = 2e7
    errors = validate_figure(parse(figure_dict))
    assert any("width must be <=" in e for e in errors)


def test_oversized_font_size_rejected(figure_dict: dict) -> None:
    figure_dict["theme"]["font_size_pt"] = 2000
    errors = validate_figure(parse(figure_dict))
    assert any("font_size_pt must be <=" in e for e in errors)


def test_ensure_valid_raises_with_all_messages(figure_dict: dict) -> None:
    figure_dict["edges"][0]["target"] = "ghost"
    figure_dict["nodes"][0]["w"] = -3
    with pytest.raises(FigureValidationError) as excinfo:
        ensure_valid(parse(figure_dict))
    assert len(excinfo.value.errors) == 2
