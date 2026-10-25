# PaperCanvas

**Agent-Native Scientific Figure Studio** — Figures as Code, Agents as Artists.

PaperCanvas lets coding agents draw, edit, and maintain scientific paper figures
the way they write code: a versioned **Figure IR** (JSON) is the single source of
truth, agents modify it only through semantic patches, and deterministic
renderers turn it into true-vector, editable **SVG / PDF / PPTX**.

> Naming note: the GitHub repository lives at `HarryHeYu/figcraft` (same name as
> the local working folder); the PyPI package, CLI and MCP tool prefix are and
> stay **`papercanvas`** — the clean, collision-free name on PyPI.

## Naming (final decision)

| Surface | Name | Notes |
|---|---|---|
| GitHub repository | `HarryHeYu/figcraft` | chosen by the author; matches the local folder |
| PyPI package / install | `pip install papercanvas` | verified available; no name collisions |
| CLI executable | `papercanvas` | `uv run papercanvas --help` |
| MCP server & tool prefix | `papercanvas_*` | `papercanvas_create/get/patch/layout/render/lint/inspect` |
| Python package import | `papercanvas` | `from papercanvas.core import Figure` |

"FigCraft" is the historical project codename and appears only in the GitHub
repository name; every user-facing surface (install, command, import, MCP
tools) is `papercanvas`. The v0.1.0 PyPI release (M4) will publish under
`papercanvas`.

## Status

v0.1.0 development — milestone plan in [PROJECT-PLAN.md](PROJECT-PLAN.md).

- [x] M0 — project skeleton, Figure IR schema + hard validation, transactional patch engine, CLI `init`/`validate`
- [x] M1 — TextLayout, linear/layered layout, orthogonal routing, SVG renderer, CLI `layout`/`render`/`patch`/`build`
- [x] M2 — PDF (reportlab), PPTX (python-pptx native shapes), Lint FC001–FC008, cross-format consistency ≤0.2 mm
- [x] M3 — shared service layer, MCP server (`papercanvas-mcp`, 7 tools), Agent Skill, real-agent end-to-end acceptance
- [x] M4 — three examples, MCP protocol e2e, Release Gate automation, docs, v0.1.0-ready (239 tests green)

## Install

```bash
pip install papercanvas        # PyPI publication pending final approval
```

For development:

```bash
uv sync
uv run pytest
uv run papercanvas --help
```

## Quick start

```bash
uv run papercanvas build examples/basic_pipeline.json --format all
# -> examples/basic_pipeline.{svg,pdf,pptx} (layout commits revision+1)
uv run papercanvas lint examples/basic_pipeline.json
uv run papercanvas inspect examples/basic_pipeline.json
```

## Known limitations (v0.1)

1. **PDF CJK/emoji glyphs**: when the resolved font has no CJK coverage
   (e.g. Arial), PDF output renders those glyphs as .notdef boxes; SVG and
   PPTX are unaffected (viewer-side font fallback). CJK font fallback and an
   FC007 glyph-coverage extension are planned.
2. **No PPTX→IR sync**: the PPTX is a product — edit it freely in
   PowerPoint, but changes do not flow back into the Figure IR.
3. **No obstacle avoidance in routing**: an edge may cross unrelated nodes;
   lint rule FC006 reports it after the fact.
4. **Group labels do not auto-wrap** (explicit `\n` is honored).
5. `canvas.unit` is `mm` only; `schema_version` is `"0.1"` only.

## Known limitations (v0.1)

1. **PDF CJK/emoji glyphs**: when the resolved font has no CJK coverage
   (e.g. Arial), PDF output renders those glyphs as .notdef boxes; SVG and
   PPTX are unaffected (viewer-side font fallback). CJK font fallback and an
   FC007 glyph-coverage extension are planned.
2. **No PPTX→IR sync**: the PPTX is a product — edit it freely in
   PowerPoint, but changes do not flow back into the Figure IR.
3. **No obstacle avoidance in routing**: an edge may cross unrelated nodes;
   lint rule FC006 reports it after the fact.
4. **Group labels do not auto-wrap** (explicit `\n` is honored).
5. `canvas.unit` is `mm` only; `schema_version` is `"0.1"` only.

## MCP server

```bash
uv run papercanvas-mcp --root path/to/project
```

Seven stdio tools (`papercanvas_create/get/patch/layout/render/lint/inspect`)
over the same service layer as the CLI. All paths must resolve inside
`--root`; outputs are written next to the IR inside the root. Domain errors
return `{"ok": false, "error": ...}` so agents can self-correct.

The Agent Skill in [`skills/papercanvas/SKILL.md`](skills/papercanvas/SKILL.md)
teaches coding agents the full workflow; a recorded real-agent acceptance run
lives in [`docs/m3-e2e-log.md`](docs/m3-e2e-log.md).

## The Figure IR in one minute

Copy-paste this into `quickstart.json` — it validates and renders as-is:

```json
{
  "schema_version": "0.1",
  "id": "method_pipeline",
  "revision": 1,
  "canvas": {"width": 100, "height": 40, "unit": "mm", "margin": 4},
  "theme": {"font_family": "Arial", "font_size_pt": 8, "palette": {}},
  "nodes": [
    {
      "id": "input",
      "type": "rounded_rect",
      "label": "Input Video",
      "x": 8, "y": 13, "w": 34, "h": 14,
      "style": {"fill": "#E8F0FE", "stroke": "#4275C4"}
    },
    {
      "id": "encoder",
      "type": "rounded_rect",
      "label": "Video Encoder",
      "x": 58, "y": 13, "w": 34, "h": 14,
      "style": {"fill": "#E5F4EC", "stroke": "#418968"}
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": "input",
      "target": "encoder",
      "source_port": "right",
      "target_port": "left",
      "style": {"stroke": "#444444", "arrow": "end"}
    }
  ],
  "groups": []
}
```

```bash
uv run papercanvas validate quickstart.json   # -> valid
uv run papercanvas render quickstart.json     # -> quickstart.svg
```

Agents never write XML or PPTX internals; they apply patches such as
`{"op": "set_style", "target": "forget_branch", "style": {"fill": "#FCE4CF"}}`.

## License

MIT
