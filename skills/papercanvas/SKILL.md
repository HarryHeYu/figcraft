---
name: papercanvas
description: >-
  Draw and revise publication-ready scientific figures (method pipelines,
  model architectures, system frameworks) as code. Creates a versioned Figure
  IR, applies semantic patches, auto-layouts, lints quality issues, and
  exports true-vector SVG / PDF / PPTX. Use when the user asks for a paper
  figure, diagram, method overview, or architecture sketch — or asks to
  modify one.
---

# PaperCanvas — scientific figures as code

PaperCanvas turns a method description into an editable vector figure. The
Figure IR (a JSON file) is the single source of truth; SVG/PDF/PPTX are
build products. **Never hand-edit the IR JSON** — every change goes through
patches, which are validated transactionally (any failure leaves the file
byte-identical).

You have two equivalent interfaces. Prefer MCP tools when connected
(`papercanvas_*`); otherwise use the CLI (`uv run papercanvas --help`).
Both share one service layer, results are identical.

## Workflow: description → figure

### 1. Extract the structure from the method description

From the user's text, identify:

- **modules** (boxes): each becomes a node — pick a short, stable id
  (`video_encoder`, not `VE1`), and a concise label (1–4 words)
- **data flow** (arrows): each becomes an edge; pick ports so arrows leave
  and enter sensibly (`right`→`left` for left-to-right flow, `bottom`→`top`
  for vertical). Legal ports: left, right, top, bottom. Self-loops are
  rejected.
- **groupings** (dashed boxes): stages/branches become groups; a node can
  belong to at most one group

Leave out `x/y/w/h` — layout computes coordinates.

### 2. Create and fill the figure

```bash
papercanvas init figures/method.json --id method_overview
```

then add nodes and edges in ONE patch (cheaper and atomic):

```bash
papercanvas patch figures/method.json --ops ops.json
```

with `ops.json`:

```json
{
  "operations": [
    {"op": "add_node", "node": {"id": "encoder", "label": "Video Encoder"}},
    {"op": "add_node", "node": {"id": "llm", "label": "LLM"}},
    {"op": "add_edge", "edge": {"id": "e1", "source": "encoder", "target": "llm"}}
  ]
}
```

Patch operations: `add_node`, `update_node`, `remove_node`, `set_style`,
`add_edge`, `remove_edge`, `add_group`, `update_label`, `move_node`.
`remove_node` refuses to delete connected edges unless you pass
`"remove_edges": true`. Colors accept `#rgb`/`#rrggbb` or palette keys from
the theme.

### 3. Lay out, then iterate

```bash
papercanvas layout figures/method.json --preset layered
```

Presets: `linear-h` (row, IR order), `linear-v` (column), `layered`
(Sugiyama-style DAG; cycles are rejected). Layout rewrites coordinates and
bumps the revision.

### 4. Lint until clean of errors

```bash
papercanvas lint figures/method.json
```

Fix findings with targeted patches — never by re-drawing:

- `FC001` node outside canvas → re-layout, or `move_node`
- `FC003` label overflow → shorten the label, or `update_node` w/h
- `FC004` overlapping nodes → re-layout or `move_node`
- `FC006` arrow crosses an unrelated node → change ports or `move_node`
- `FC005`/`FC007` are warnings (font size / substitution) — report them to
  the user if relevant

Exit code 1 means at least one Error-severity finding.

### 5. Revise without breaking the figure

For "make the forget branch orange" you do NOT redraw — you patch:

```json
{"op": "set_style", "target": "forget_branch", "style": {"fill": "#FCE4CF"}}
```

Multiple edits in one batch (one revision). Concurrent editing is safe:
pass `"expected_revision": N` and re-apply on conflict. `papercanvas inspect
figures/method.json <id>` shows an object's geometry, style, and relations
before you touch it.

### 6. Export

```bash
papercanvas render figures/method.json --format all
# -> method.svg  method.pdf  method.pptx
```

All three are build products of the same IR: true vector, editable, no
rasterization. Re-export after any patch.

## MCP tools (when connected)

| Tool | Purpose |
|---|---|
| `papercanvas_create(path, figure_id, width?, height?, margin?)` | new IR file |
| `papercanvas_get(path)` | full IR + `hard_errors` list |
| `papercanvas_patch(path, operations, expected_revision?)` | transactional batch |
| `papercanvas_layout(path, preset)` | arrange + commit coordinates |
| `papercanvas_render(path, formats)` | export svg/pdf/pptx |
| `papercanvas_lint(path, min_font_size_pt?)` | FC001–FC008 findings |
| `papercanvas_inspect(path, object_id?)` | inventory or object detail |

All paths must resolve inside the server's project root. Domain failures
come back as `{"ok": false, "error": "..."}` — read the message, fix the
operation, retry. Check `ok` before trusting a result.

## Rules of thumb

- One figure project per topic; keep the IR next to the paper source.
- Stable ids are a contract: styling never changes ids, and later patches
  reference them. Choose them once, choose them well.
- Always `layout` before the first `render`; render refuses unplaced nodes.
- Run `lint` before delivering; fix every Error, mention warnings.
- Same IR + same fonts ⇒ byte-identical output; safe to re-export and
  diff. Do not try to preserve hand-tweaks inside SVG/PDF/PPTX files — they
  are products, not sources.
- Revision conflicts mean another writer committed since you loaded:
  re-read with `get`/`inspect`, redo your patch on the new state.
