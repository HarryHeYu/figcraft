# PaperCanvas

**Agent-Native Scientific Figure Studio** — Figures as Code, Agents as Artists.

PaperCanvas lets coding agents draw, edit, and maintain scientific paper figures
the way they write code: a versioned **Figure IR** (JSON) is the single source of
truth, agents modify it only through semantic patches, and deterministic
renderers turn it into true-vector, editable **SVG / PDF / PPTX**.

> Naming note: the GitHub repository lives at `HarryHeYu/figcraft` (same name as
> the local working folder); the PyPI package, CLI and MCP tool prefix are and
> stay **`papercanvas`** — the clean, collision-free name on PyPI.

## Status

v0.1.0 development — milestone plan in [PROJECT-PLAN.md](PROJECT-PLAN.md).

- [x] M0 — project skeleton, Figure IR schema + hard validation, transactional patch engine, CLI `init`/`validate`
- [x] M1 — TextLayout, linear/layered layout, orthogonal routing, SVG renderer, CLI `layout`/`render`/`patch`/`build` (125 tests green; acceptance artifact: `examples/basic_pipeline.svg`)
- [ ] M2 — PDF (reportlab), PPTX (python-pptx), Lint FC001–FC008
- [ ] M3 — full CLI, 7 MCP tools (`papercanvas_*`), Agent Skill
- [ ] M4 — examples, real-agent end-to-end, release v0.1.0

## Install (development)

```bash
uv sync
uv run pytest
uv run papercanvas --help
```

## Quick start (M1 engine)

```bash
uv run papercanvas build examples/basic_pipeline.json
# -> examples/basic_pipeline.svg (layout commits revision+1, then renders)
```

## The Figure IR in one minute

```json
{
  "schema_version": "0.1",
  "id": "method_pipeline",
  "revision": 1,
  "canvas": {"width": 182, "height": 58, "unit": "mm", "margin": 4},
  "theme": {"font_family": "Arial", "font_size_pt": 8, "palette": {}},
  "nodes": [
    {"id": "input", "type": "rounded_rect", "label": "Input Video",
     "x": 5, "y": 18, "w": 38, "h": 20, "style": {"fill": "#E8F0FE"}}
  ],
  "edges": [
    {"id": "e1", "source": "input", "target": "encoder",
     "source_port": "right", "target_port": "left", "style": {"arrow": "end"}}
  ],
  "groups": []
}
```

Agents never write XML or PPTX internals; they apply patches such as
`{"op": "set_style", "target": "forget_branch", "style": {"fill": "#FCE4CF"}}`.

## License

MIT
