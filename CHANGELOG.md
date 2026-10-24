# Changelog

All notable changes to PaperCanvas are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/); versioning: SemVer.

## [Unreleased]

### Added — M0 (project skeleton & Figure IR)

- Pydantic v2 Figure IR v0.1 (`Figure`/`Canvas`/`Node`/`Edge`/`Group`/`Theme`/`Style`)
  with strict parsing (`extra=forbid`, non-finite numbers rejected).
- Hard validation (`core/validate.py`): schema version, global id uniqueness,
  dangling edges, self-loops, non-positive sizes, unresolvable colors, group
  child rules. Hard errors block every write and render.
- `FigureDocument` load/save with sidecar `O_EXCL` file lock, timeout (stale
  locks are never stolen), `expected_revision` optimistic concurrency checked
  against the on-disk file inside the lock, and atomic writes
  (temp file + `os.replace`).
- Deterministic serialization (same IR → same bytes).
- Semantic patch engine: 9 operations (`add_node`, `remove_node`,
  `update_node`, `set_style`, `add_edge`, `remove_edge`, `add_group`,
  `update_label`, `move_node`), transactional batches, failure leaves the
  file byte-identical, success commits `revision + 1`.
- CLI: `papercanvas init` / `validate`.
- Engineering hygiene: ruff, GitHub Actions matrix (3.12/3.14 ×
  ubuntu/windows/macos), AGENTS.md with the six hard constraints.

### Added — M1 (drawing engine)

- Text layer (constraint 2): Pillow-backed `FontMetrics` (BASIC layout engine,
  64× measurement scale, cached resolution) and `TextLayout` — the only place
  that wraps lines, computes line height and positions baselines.
- Layouts: `linear-h`, `linear-v`, and a simplified Sugiyama `layered`
  (longest-path layering + stable IR-order within layers; cycles are hard
  errors). Auto-sizing of unplaced nodes from label metrics; canvas
  recomputed as content + margin on every layout.
- Orthogonal routing (`layout/routing.py`): deterministic axis-aligned point
  sequences for all 16 port combinations; SVG consumes them as polylines.
- SVG renderer (lxml): mm viewBox, editable `<text>` per TextLayout line,
  arrow markers per stroke color, palette color resolution, no `<image>`,
  no scripts, no timestamps; byte-identical output for identical input.
- CLI: `layout`, `render`, `patch`, `build` (layout+render in one command).
- Example `examples/basic_pipeline.json` + rendered
  `examples/basic_pipeline.svg` (M1 acceptance artifact).
- Test suite: 143 tests covering the constraint-6 classes (render is
  read-only; layout commits revision+1; TextLayout/SVG line-count agreement;
  routing determinism; patch-failure byte stability) plus the schema
  hard-error matrix and CLI end-to-end flows.

### Fixed — multi-agent verification round (2026-10-24)

Three parallel verification agents (constraint audit, adversarial probing,
SVG-vs-IR geometry verification, 1105 assertions) found and the following
fixes closed:

- **[P0] `update_node` silently bypassed schema validation** via bare
  `setattr` (no `validate_assignment`): `type:"bogus"` / `x:"abc"` committed
  successfully and produced IR files that could never be loaded again.
  `IrModel` now validates assignments; malformed payloads surface as clean
  `PatchError`s and the file stays byte-identical and loadable.
- **[P1] Traceback leaks**: pydantic `ValidationError`/`TypeError`/
  `ValueError` from malformed patch payloads (bad ids, unknown enum values,
  NaN coordinates, `operations: 5`, non-object ops) now normalize to clean
  `PatchError`s; `papercanvas init` with an invalid `--id` errors cleanly.
- **[P1] NaN/Infinity coordinates** in `move_node`/`update_node` crashed at
  serialization; now rejected at assignment with a clean error.
- **[P2] `move_node`/`update_node` accepted booleans** as coordinates
  (`true` → `1.0`); now rejected explicitly.
- **[P2] Node-level `stroke_dash` was accepted by the IR but silently
  dropped by the SVG renderer**; nodes now render `stroke-dasharray`.
- **[P2] `render`/`build --out` could overwrite the IR file itself**
  (destroying the single source of truth); now refused with a clear error.
- **[P2] `_require_placed_children` crashed with `AttributeError`** on a
  group referencing a missing node via the Python API; reports a clean
  `RenderError` now.
- **[P2] Constraint-6c test was structurally weak** (near-tautological);
  now asserts exact total `<text>` count == TextLayout lines across all
  nodes and groups, plus a forced multi-line label checked line by line.
- [P3] `remove_edges` truthiness (`"yes"` no longer deletes edges);
  `expected_revision` type-validated; `operations` container validated;
  string-revision files no longer patch-deadlocked (`read_revision` reads
  through the same schema as the loader); UTF-8 BOM files load; numeric
  strings coerce identically on `add_node` and `update_node`; word-wrap no
  longer leaves trailing spaces on broken lines.

### Added — M2 (publication-grade exports + lint)

- **PDF renderer** (`render/pdf.py`, reportlab): direct vector output — no
  SVG conversion, no rasterization. Embedded TTF subsets, mm→pt via
  core.geometry, y-axis flip, dash patterns, arrowhead triangles matching
  the SVG marker geometry, `invariant=1` + pinned metadata for
  byte-deterministic output.
- **PPTX renderer** (`render/pptx.py`, python-pptx): fully editable native
  shapes — rectangles / rounded rects with adjustments, one STRAIGHT
  connector per routed segment (constraint 4: never a single elbow),
  arrowheads set on `a:ln` in schema order, one textbox per TextLayout line
  (word wrap disabled so PowerPoint re-wraps nothing), named shapes
  (`node:<id>`, `edge:<id>#seg<i>`) for tooling. Slide sizes honor the
  OOXML 1-inch floor (smaller canvases get padding, coordinates unchanged).
  Zip entries carry pinned timestamps and core properties are fixed ->
  byte-deterministic files.
- **Figure Lint** (`lint/`): FC001 canvas bounds (error), FC002 invalid
  structure (error), FC003 label overflow via font metrics (error), FC004
  unexpected node overlap (warning), FC005 font size threshold (warning,
  configurable), FC006 arrow through unrelated node via Liang-Barsky
  (warning), FC007 font substitution (warning), FC008 undeclared raster
  images in rendered output (warning). Machine-readable JSON output
  (`lint --format json`); lint loads leniently so it can diagnose figures
  that hard validation would reject; strictly read-only.
- **CLI**: `render`/`build` now accept `--format svg|pdf|pptx|all`; new
  `lint` command with `--min-font-size` and text/JSON output.
- Cross-format consistency: node geometry agrees across SVG/PDF/PPTX
  within ~4×10⁻⁵ mm (independently verified; the acceptance bar is
  0.2 mm). Determinism holds for all three formats across processes.

### Fixed — M2 verification round

- **[P1]** `papercanvas lint` crashed with a traceback on schema-valid but
  hard-invalid figures (e.g. bad color) during the FC008 pre-render —
  that is exactly the case lint must diagnose; the pre-render is now
  best-effort and FC002 reports the root cause.
- **[P1]** PPTX `arrow: "both"` on a single-segment edge emitted `a:tailEnd`
  before `a:headEnd`, violating the CT_LineProperties schema sequence;
  arrowheads are now inserted in schema order.
- **[P2]** PDF font registration cached by sanitized name only — two
  families sanitizing identically but resolving to different files got the
  wrong glyphs embedded in long-lived processes; the cache key now includes
  the resolved font file.
- **[P2]** Group style with explicitly-nulled stroke/dash rendered
  differently per format (PPTX kept group defaults); all three backends
  now share the same None-resolution.

### Known limitations (v0.1)

- PDF: CJK/emoji labels render as .notdef boxes when the resolved font has
  no glyphs (Arial). SVG/PPTX are unaffected (viewer font fallback).
  CJK-capable font fallback is planned for M3 together with an FC007
  glyph-coverage extension.
- Lint FC003 covers node labels; group-label overflow is deliberate out of
  scope until M3.

### Fixed — second verification round (2026-10-24)

The three verification agents re-audited the fixes (constraint audit
continued, adversarial re-probing of the fixed code paths, geometry
assertions re-run: 1105 + 34 = 1139 all green). Round-1 fixes were all
confirmed correct with no regressions; the re-probe surfaced four new
edge-case defects, now fixed:

- **[P1] Deeply-nested legal JSON** (60k levels) leaked `RecursionError`
  tracebacks from `json.loads` in patch/validate; now a clean
  "JSON nesting too deep" error everywhere (document load, `read_revision`,
  CLI `--ops`, patch op loop).
- **[P2] `render --out` IR guard could be bypassed with a hardlink alias**:
  the path-string comparison missed same-inode files, letting SVG bytes be
  written through the alias into the IR. Output is now committed with
  temp + `os.replace` (re-points the alias entry, IR inode survives), and
  the regression test proves byte-integrity through a real hardlink.
- **[P2] Oversized JSON integers** (400 digits) hit a manual `float()` and
  leaked `OverflowError`; now wrapped into a clean `PatchError`.
- **[P3] Lax-coercion inconsistency closed**: booleans are now refused by
  every numeric IR field at the schema level (`stroke_width: true`,
  `w: true`, `canvas.width: true`, `revision: true`), matching the explicit
  rejection already in `move_node`/`update_node`.
- **[P3] Layout arithmetic overflow** (`w: 1e308` nodes → inf canvas →
  serialize crash) is now a hard validation error: dimensions are bounded
  at 10 000 000 mm and font/stroke metrics at 1000 pt.

Verification round totals: 154 tests green, ruff clean; constraints 3 and 6
(upgraded) fully compliant per the independent audit.
