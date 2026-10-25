"""Independent agent end-to-end test over the MCP protocol.

A coding agent builds the video-unlearning figure from scratch using ONLY
the seven papercanvas_* tools, applies three rounds of local edits, and the
test verifies after every round that untouched objects stayed byte-equal.
Mirrors docs/m3-e2e-log.md but drives the real MCP protocol instead of the CLI.
"""

from __future__ import annotations

from pathlib import Path


def _untouched_violations(
    before: dict, after: dict, touched_nodes: set, touched_edges: set
) -> list[str]:
    """Return ids of un-touched objects that changed between two get() dumps."""
    violations = []
    for node in before["nodes"]:
        if node["id"] in touched_nodes:
            continue
        counterpart = next(n for n in after["nodes"] if n["id"] == node["id"])
        if counterpart != node:
            violations.append(node["id"])
    for edge in before["edges"]:
        if edge["id"] in touched_edges:
            continue
        counterpart = next(e for e in after["edges"] if e["id"] == edge["id"])
        if counterpart != edge:
            violations.append(edge["id"])
    return violations


def test_agent_mcp_end_to_end_three_rounds(mcp, tmp_path: Path) -> None:
    # -- creation ----------------------------------------------------------
    created = mcp.call("papercanvas_create", {"path": "u.json", "figure_id": "unlearning"})
    assert created["ok"] and created["revision"] == 1

    node_specs = [
        {"id": "visual_encoder", "type": "rounded_rect", "label": "Visual Encoder"},
        {"id": "connector", "type": "rounded_rect", "label": "Connector"},
        {"id": "llm", "type": "rounded_rect", "label": "LLM"},
        {"id": "forget_head", "type": "rect", "label": "Forget Head"},
        {"id": "retain_head", "type": "rect", "label": "Retain Head"},
        {"id": "gated_output", "type": "rounded_rect", "label": "Gated Output"},
    ]
    edge_specs = [
        ("e1", "visual_encoder", "connector"),
        ("e2", "connector", "llm"),
        ("e3", "llm", "forget_head"),
        ("e4", "llm", "retain_head"),
        ("e5", "forget_head", "gated_output"),
        ("e6", "retain_head", "gated_output"),
    ]
    filled = mcp.call(
        "papercanvas_patch",
        {
            "path": "u.json",
            "operations": [
                {"op": "add_node", "node": spec}
                for spec in node_specs
            ]
            + [
                {"op": "add_edge", "edge": {"id": eid, "source": src, "target": dst}}
                for eid, src, dst in edge_specs
            ],
            "expected_revision": 1,
        },
    )
    assert filled["ok"] and filled["revision"] == 2

    laid = mcp.call("papercanvas_layout", {"path": "u.json", "preset": "layered"})
    assert laid["ok"] and laid["revision"] == 3

    baseline = mcp.call("papercanvas_get", {"path": "u.json"})
    assert baseline["hard_errors"] == []

    # -- round 1: recolor both branches + group them -----------------------
    round1 = mcp.call(
        "papercanvas_patch",
        {
            "path": "u.json",
            "operations": [
                {
                    "op": "set_style",
                    "target": "forget_head",
                    "style": {"fill": "#FCE4CF", "stroke": "#C17C43"},
                },
                {
                    "op": "set_style",
                    "target": "retain_head",
                    "style": {"fill": "#E8F0FE", "stroke": "#4275C4"},
                },
                {
                    "op": "add_group",
                    "group": {
                        "id": "heads",
                        "children": ["forget_head", "retain_head"],
                        "label": "Unlearning Heads",
                    },
                },
            ],
            "expected_revision": 3,
        },
    )
    assert round1["ok"] and round1["revision"] == 4
    after1 = mcp.call("papercanvas_get", {"path": "u.json"})
    assert _untouched_violations(baseline, after1, {"forget_head", "retain_head"}, set()) == []

    # -- round 2: rename the connector + widen the LLM ---------------------
    round2 = mcp.call(
        "papercanvas_patch",
        {
            "path": "u.json",
            "operations": [
                {"op": "update_label", "target": "connector", "label": "Cross-Modal Connector"},
                {"op": "update_node", "id": "llm", "w": 34.0},
            ],
            "expected_revision": 4,
        },
    )
    assert round2["ok"] and round2["revision"] == 5
    after2 = mcp.call("papercanvas_get", {"path": "u.json"})
    assert _untouched_violations(after1, after2, {"connector", "llm"}, set()) == []

    # -- round 3: re-route one edge + bolden the output --------------------
    round3 = mcp.call(
        "papercanvas_patch",
        {
            "path": "u.json",
            "operations": [
                {"op": "remove_edge", "id": "e5"},
                {
                    "op": "add_edge",
                    "edge": {
                        "id": "e5",
                        "source": "forget_head",
                        "target": "gated_output",
                        "source_port": "top",
                        "target_port": "bottom",
                    },
                },
                {"op": "set_style", "target": "gated_output", "style": {"stroke_width": 0.8}},
            ],
            "expected_revision": 5,
        },
    )
    assert round3["ok"] and round3["revision"] == 6
    after3 = mcp.call("papercanvas_get", {"path": "u.json"})
    violations = _untouched_violations(after2, after3, set(), {"e5"})
    # gated_output is the requested target of this round
    assert [v for v in violations if v != "gated_output"] == []

    # -- lint loop: the rename made the connector label overflow (FC003) ---
    linted = mcp.call("papercanvas_lint", {"path": "u.json"})
    assert linted["ok"]
    fixed = mcp.call(
        "papercanvas_patch",
        {
            "path": "u.json",
            "operations": [{"op": "update_node", "id": "connector", "w": 26.0}],
            "expected_revision": 6,
        },
    )
    assert fixed["ok"] and fixed["revision"] == 7
    linted_after = mcp.call("papercanvas_lint", {"path": "u.json"})
    assert linted_after["summary"]["errors"] == 0
    assert not [
        f
        for f in linted_after["findings"]
        if f["rule_id"] == "FC003" and f["object_id"] == "connector"
    ]

    # -- export all three formats over the protocol ------------------------
    rendered = mcp.call(
        "papercanvas_render", {"path": "u.json", "formats": ["svg", "pdf", "pptx"]}
    )
    assert rendered["ok"]
    for file_info in rendered["files"]:
        artifact = tmp_path / Path(file_info["path"]).name
        assert artifact.exists() and artifact.stat().st_size > 0

    # -- final state: revision history and untouched-object integrity ------
    final = mcp.call("papercanvas_get", {"path": "u.json"})
    assert final["revision"] == 7
    assert final["hard_errors"] == []
    assert (
        _untouched_violations(
            baseline,
            final,
            {"forget_head", "retain_head", "connector", "llm", "gated_output"},
            {"e5"},
        )
        == []
    )
    detail_args = {"path": "u.json", "object_id": "gated_output"}
    inspect_detail = mcp.call("papercanvas_inspect", detail_args)
    assert inspect_detail["object"]["style"]["stroke_width"] == 0.8
