# Architecture

PaperCanvas turns a versioned **Figure IR** (JSON on disk) into deterministic,
editable SVG/PDF/PPTX. The IR is the single source of truth; every other
format is a build product. This document maps the real code (src-layout,
package `papercanvas`).

## Layers

```
Agent (CLI · MCP server · Python API)
        │  semantic patches: validate → transactional commit → revision+1
        ▼
service.py ────────────── the single business surface (JSON-safe dicts)
        ▼
core/ ──── Figure IR on disk
  document.py  FigureDocument: sidecar file lock (O_EXCL), expected_revision,
               atomic write (temp + os.replace), deterministic serialization
  patch.py     9 transactional operations; failure ⇒ zero writes
  validate.py  hard validation: invalid figures can never be written or rendered
  models.py    Pydantic v2 strict models (extra=forbid, no NaN/Inf)
  geometry.py  the only mm ↔ pt ↔ px ↔ EMU conversions
        │ explicit layout calls only (never at render time)
        ▼
layout/  linear / layered (simplified Sugiyama) · sizes (auto-fit from text)
  routing.py   orthogonal point sequences for all 16 port combinations
text/    text_metrics.py (Pillow FontMetrics) · text_layout.py (TextLayout)
        │ renderers consume coordinates + text layout; they never lay out
   ┌────┼──────────┐
SVG(lxml)   PDF(reportlab)   PPTX(python-pptx, native shapes)
        │
lint/    FC001–FC008 quality findings — read-only, never blocks
```

## Data flow

1. An agent expresses intent as **semantic patches** (9 operations) — never
   XML or PPTX internals.
2. `core/patch.py` validates each operation, applies the batch, and commits
   through `FigureDocument.save_figure()`: file lock → on-disk
   `expected_revision` check → serialize → atomic replace → `revision + 1`.
   Any failure leaves the file byte-identical.
3. `layout/` rewrites coordinates only when explicitly invoked
   (`linear-h`, `linear-v`, `layered`), re-routing edges and recomputing the
   canvas as content + margin, and commits the same way.
4. Renderers read the IR, resolve defaults once (`render/style.py`), and
   emit bytes. `render`, `lint`, `inspect` are strictly read-only.
5. Determinism contract: same IR + same fonts + same version ⇒ byte-identical
   output in all three formats (no timestamps, no set iteration, pinned
   zip/metadata).

## The six engineering constraints, mapped to code

| Constraint | Enforced by |
|---|---|
| 1. Naming unity (`papercanvas` everywhere) | `pyproject.toml`, CLI/MCP entry points |
| 2. TextLayout is the only wrapping point | `text/text_layout.py`; all three renderers + `layout/sizes.py` consume it |
| 3. Read/write discipline | `core/document.py` (lock, revision, atomic commit); CLI/MCP route writes only through patch/layout |
| 4. Routing point-list regime | `layout/routing.py` point sequences → SVG polylines; PPTX uses one native segment per routed segment |
| 5. Validation vs lint split | `core/validate.py` (hard errors, blocks writes/render) vs `lint/` (FC001–FC008, quality only) |
| 6. Mandatory regression tests | `tests/` — render read-only, revision+1, TextLayout/SVG line agreement, routing determinism, patch-failure byte stability |

## Key design decisions

- **Single business surface**: `service.py` is the only layer that knows the
  operations; CLI (`cli.py`), MCP (`integrations/mcp_server.py`) and the
  Python API call the same functions and get JSON-safe dicts back.
- **Routing points, not connectors**: edges are stored and rendered as
  orthogonal point sequences; no renderer invents geometry.
- **TextLayout owns wrapping**: font metrics (Pillow, 64× measurement) and
  line breaking happen in one place, so SVG/PDF/PPTX agree per line.
- **Lenient load is diagnostic-only**: `FigureDocument.load(lenient=True)`
  skips only the hard-rule pass — used by the read paths `get` and `lint` so
  broken figures can still be inspected and diagnosed; writes and renders
  always hard-validate.
- **Deterministic serialization**: `indent=2, ensure_ascii=False` + trailing
  newline, fields in declaration order; PDF/PPTX metadata and zip timestamps
  pinned.
- **Unit conversion lives once** (`core/geometry.py`); renderers never
  convert units themselves.

## Module map

| Module | Responsibility |
|---|---|
| `papercanvas/cli.py` | Typer CLI: `init`, `validate`, `patch`, `layout`, `render`, `build`, `lint`, `inspect` |
| `papercanvas/service.py` | Shared service layer; `ServiceContext` path policy (MCP root whitelist) |
| `papercanvas/core/models.py` | Figure IR v0.1 Pydantic models, color/palette resolution |
| `papercanvas/core/validate.py` | Hard validation (ids, references, sizes, colors, groups) |
| `papercanvas/core/document.py` | Load/save, sidecar lock, atomic write, deterministic bytes |
| `papercanvas/core/patch.py` | 9 patch operations, transactional batches |
| `papercanvas/core/geometry.py` | mm ↔ pt ↔ px ↔ EMU |
| `papercanvas/core/errors.py` | `PaperCanvasError` hierarchy (structured MCP errors) |
| `papercanvas/layout/linear.py` | `linear-h` / `linear-v` presets |
| `papercanvas/layout/layered.py` | Simplified Sugiyama layering; cycles are hard errors |
| `papercanvas/layout/routing.py` | Orthogonal point sequences, port geometry |
| `papercanvas/layout/sizes.py` | Auto-sizing unplaced nodes from label metrics |
| `papercanvas/text/text_metrics.py` | `FontMetrics`, font resolution (`resolve_font`) |
| `papercanvas/text/text_layout.py` | `TextLayout` — the only line-wrapping point |
| `papercanvas/render/svg.py` | SVG via lxml (editable `<text>`, no `<image>`) |
| `papercanvas/render/pdf.py` | PDF via reportlab (embedded TTF subsets) |
| `papercanvas/render/pptx.py` | PPTX via python-pptx (native shapes, named) |
| `papercanvas/render/style.py` | Shared visual defaults for all backends |
| `papercanvas/lint/engine.py`, `lint/rules.py` | FC001–FC008 findings, JSON output |
| `papercanvas/integrations/mcp_server.py` | `papercanvas-mcp` stdio server, 7 tools |

The Agent Skill (`skills/papercanvas/SKILL.md`) teaches agents the workflow;
see [docs/mcp.md](mcp.md) for the tool surface and
[docs/figure-ir.md](figure-ir.md) for the IR field reference.
