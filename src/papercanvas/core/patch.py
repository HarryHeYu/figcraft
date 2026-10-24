"""Semantic patch engine — the only way agents modify a figure.

Nine operations, applied as one transaction to an in-memory copy and committed
in a single atomic, locked, revision-checked write. Any failure leaves the
on-disk file byte-for-byte unchanged (engineering constraint 6).

Supported operations:
    add_node / remove_node / update_node / set_style / add_edge /
    remove_edge / add_group / update_label / move_node
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .document import FigureDocument
from .errors import DocumentConflictError, FigureValidationError, PatchError
from .models import Edge, EdgeStyle, Figure, Group, Node, Style
from .validate import ensure_valid

UPDATE_NODE_FIELDS = ("type", "label", "x", "y", "w", "h")


@dataclass
class PatchRequest:
    operations: list[dict[str, Any]]
    expected_revision: int | None = None


@dataclass
class PatchResult:
    revision: int
    applied: list[str] = field(default_factory=list)


def apply_patch(doc: FigureDocument, request: PatchRequest) -> PatchResult:
    """Apply ``request.operations`` to ``doc`` as one all-or-nothing transaction.

    The batch is validated against whole-figure hard rules before the file is
    touched. ``expected_revision`` (when given) must match the revision the
    document was loaded at.
    """
    if not request.operations:
        raise PatchError("patch contains no operations")
    if not isinstance(request.operations, list):
        raise PatchError("'operations' must be a list")
    for index, operation in enumerate(request.operations):
        if not isinstance(operation, dict):
            raise PatchError(f"operation {index}: must be a JSON object")
    if request.expected_revision is not None and (
        isinstance(request.expected_revision, bool)
        or not isinstance(request.expected_revision, int)
    ):
        raise PatchError("expected_revision must be an integer")

    base_revision = doc.figure.revision
    if (
        request.expected_revision is not None
        and request.expected_revision != base_revision
    ):
        raise DocumentConflictError(
            f"expected_revision {request.expected_revision} does not match "
            f"document revision {base_revision}; reload and reapply"
        )

    working = doc.figure.model_copy(deep=True)
    applied: list[str] = []
    for index, operation in enumerate(request.operations):
        try:
            applied.append(_apply_operation(working, operation))
        except PatchError as exc:
            raise PatchError(f"operation {index}: {exc}") from exc
        except (
            PydanticValidationError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ) as exc:
            # malformed payloads (bad ids, unknown enum values, wrong types,
            # NaN/Infinity, oversized integers, pathological nesting) must
            # surface as clean patch errors, never as tracebacks — and the
            # file stays untouched either way
            raise PatchError(f"operation {index}: {exc}") from exc

    working.revision = base_revision + 1
    # Hard-validate the fully patched figure before it may touch disk.
    try:
        ensure_valid(working)
    except FigureValidationError as exc:
        raise PatchError(f"patched figure fails hard validation:\n{exc}") from exc

    doc.save_figure(working, expected_revision=base_revision)
    doc.figure = working  # commit in memory only after the file commit succeeded
    return PatchResult(revision=working.revision, applied=applied)


# --------------------------------------------------------------------------
# operation handlers (each returns a human-readable summary)
# --------------------------------------------------------------------------


def _apply_operation(fig: Figure, op: Any) -> str:
    if not isinstance(op, dict):
        raise PatchError("operation must be a JSON object")
    kind = op.get("op")
    handler = _HANDLERS.get(kind)
    if handler is None:
        raise PatchError(f"unknown op {kind!r}; supported: {sorted(_HANDLERS)}")
    return handler(fig, op)


_HANDLERS: dict[str, Any] = {}


def _handler(name: str):
    def register(fn):
        _HANDLERS[name] = fn
        return fn

    return register


def _require(op: dict[str, Any], key: str) -> Any:
    if key not in op:
        raise PatchError(f"missing required field {key!r}")
    return op[key]


def _reject_unknown(op: dict[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(op) - set(allowed))
    if unknown:
        raise PatchError(f"unknown field(s) {unknown}; allowed: {list(allowed)}")


@_handler("add_node")
def _op_add_node(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "node"))
    node = Node.model_validate(_require(op, "node"))
    if fig.style_target(node.id) is not None:
        raise PatchError(f"id {node.id!r} is already in use")
    fig.nodes.append(node)
    return f"add_node {node.id}"


@_handler("remove_node")
def _op_remove_node(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "id", "remove_edges"))
    node_id = _require(op, "id")
    node = fig.node(node_id)
    if node is None:
        raise PatchError(f"node {node_id!r} does not exist")
    owning_groups = [g.id for g in fig.groups if node_id in g.children]
    if owning_groups:
        raise PatchError(
            f"node {node_id!r} is a member of group(s) {owning_groups}; "
            f"update or remove the group(s) first"
        )
    connected = [e.id for e in fig.edges if e.source == node_id or e.target == node_id]
    if connected and op.get("remove_edges") is not True:
        raise PatchError(
            f"node {node_id!r} still has connected edges {connected}; "
            f"pass remove_edges=true to delete them explicitly"
        )
    fig.nodes.remove(node)
    fig.edges = [e for e in fig.edges if e.source != node_id and e.target != node_id]
    return f"remove_node {node_id} (edges removed: {len(connected)})"


@_handler("update_node")
def _op_update_node(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "id", *UPDATE_NODE_FIELDS))
    node_id = _require(op, "id")
    node = fig.node(node_id)
    if node is None:
        raise PatchError(f"node {node_id!r} does not exist")
    changed: list[str] = []
    for name in UPDATE_NODE_FIELDS:
        if name not in op:
            continue
        value = op[name]
        if name in ("x", "y", "w", "h"):
            if isinstance(value, bool):
                raise PatchError(f"{name} must be a number, not a boolean")
        if (
            name in ("w", "h")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value <= 0
        ):
            raise PatchError(f"{name} must be > 0, got {value}")
        # assignment validation on IrModel rejects wrong types / NaN here
        setattr(node, name, value)
        changed.append(name)
    if not changed:
        raise PatchError("update_node sets nothing")
    return f"update_node {node_id} ({', '.join(changed)})"


@_handler("set_style")
def _op_set_style(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "target", "style"))
    target_id = _require(op, "target")
    style_patch = _require(op, "style")
    if not isinstance(style_patch, dict) or not style_patch:
        raise PatchError("'style' must be a non-empty object")
    target = fig.style_target(target_id)
    if target is None:
        raise PatchError(f"target {target_id!r} does not exist")

    if isinstance(target, Edge):
        allowed = set(EdgeStyle.model_fields)
        unknown = sorted(set(style_patch) - allowed)
        if unknown:
            raise PatchError(
                f"edge style has no field(s) {unknown}; allowed: {sorted(allowed)}"
            )
        merged = target.style.model_dump() | style_patch
        target.style = EdgeStyle.model_validate(merged)
    elif isinstance(target, (Node, Group)):
        allowed = set(Style.model_fields)
        unknown = sorted(set(style_patch) - allowed)
        if unknown:
            raise PatchError(
                f"node/group style has no field(s) {unknown}; allowed: {sorted(allowed)}"
            )
        merged = target.style.model_dump() | style_patch
        target.style = Style.model_validate(merged)
    else:  # pragma: no cover - style_target only returns these three
        raise PatchError(f"target {target_id!r} cannot be styled")
    return f"set_style {target_id} ({', '.join(sorted(style_patch))})"


@_handler("add_edge")
def _op_add_edge(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "edge"))
    edge = Edge.model_validate(_require(op, "edge"))
    if fig.style_target(edge.id) is not None:
        raise PatchError(f"id {edge.id!r} is already in use")
    node_ids = fig.node_ids()
    if edge.source not in node_ids:
        raise PatchError(f"source {edge.source!r} is not a node")
    if edge.target not in node_ids:
        raise PatchError(f"target {edge.target!r} is not a node")
    if edge.source == edge.target:
        raise PatchError("self-loops are hard errors in v0.1")
    fig.edges.append(edge)
    return f"add_edge {edge.id} ({edge.source} -> {edge.target})"


@_handler("remove_edge")
def _op_remove_edge(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "id"))
    edge_id = _require(op, "id")
    edge = fig.edge(edge_id)
    if edge is None:
        raise PatchError(f"edge {edge_id!r} does not exist")
    fig.edges.remove(edge)
    return f"remove_edge {edge_id}"


@_handler("add_group")
def _op_add_group(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "group"))
    group = Group.model_validate(_require(op, "group"))
    if fig.style_target(group.id) is not None:
        raise PatchError(f"id {group.id!r} is already in use")
    node_ids = fig.node_ids()
    if not group.children:
        raise PatchError("group children must not be empty")
    claimed = {c: g.id for g in fig.groups for c in g.children}
    for child in group.children:
        if child not in node_ids:
            raise PatchError(f"child {child!r} is not a node")
        if child in claimed:
            raise PatchError(
                f"node {child!r} is already claimed by group {claimed[child]!r}"
            )
    fig.groups.append(group)
    return f"add_group {group.id} ({len(group.children)} children)"


@_handler("update_label")
def _op_update_label(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "target", "label"))
    target_id = _require(op, "target")
    label = _require(op, "label")
    if not isinstance(label, str):
        raise PatchError("'label' must be a string")
    target = fig.node(target_id) or fig.group(target_id)
    if target is None:
        raise PatchError(
            f"target {target_id!r} is not a node or group (edges have no label)"
        )
    target.label = label
    kind = "node" if fig.node(target_id) else "group"
    return f"update_label {kind} {target_id}"


@_handler("move_node")
def _op_move_node(fig: Figure, op: dict[str, Any]) -> str:
    _reject_unknown(op, ("op", "id", "x", "y"))
    node_id = _require(op, "id")
    node = fig.node(node_id)
    if node is None:
        raise PatchError(f"node {node_id!r} does not exist")
    x, y = _require(op, "x"), _require(op, "y")
    for name, value in (("x", x), ("y", y)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PatchError(
                f"'{name}' must be a number (mm), got {type(value).__name__}"
            )
    # assignment validation on IrModel rejects NaN/Infinity here
    node.x, node.y = float(x), float(y)
    return f"move_node {node_id} -> ({node.x:g}, {node.y:g})"
