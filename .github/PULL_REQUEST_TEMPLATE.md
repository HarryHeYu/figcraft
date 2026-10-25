## Summary

<!-- What changes and why. Link issues with "Fixes #N". Keep one PR one concern. -->

## Test evidence

<!-- Paste the tail of `uv run pytest` (pass count) and the `uv run ruff check .` result. -->

- pytest: ____ passed
- ruff: clean / issues noted below
- New behavior covered by tests: <!-- yes — which tests; or n/a with reason -->

## Platform impact

<!-- CI covers Python 3.12/3.14 across ubuntu/windows/macos. Note anything
     platform-specific: font resolution/fallback, path handling, line
     endings, CJK glyph coverage. -->

- [ ] Windows
- [ ] macOS
- [ ] Linux
- Platform-specific notes: <!-- or "none" -->

## Six-constraint self-check

<!-- Normative text in AGENTS.md. Tick only what you verified. -->

- [ ] Naming: only `papercanvas` used as package/CLI/MCP prefix (repo name aside)
- [ ] TextLayout: no renderer decides line wrapping; all wrapping goes through `text/text_layout.py`
- [ ] Read/write discipline: IR writes go through `FigureDocument.save_figure()` (file lock + `expected_revision` + atomic commit); render/lint/inspect stay read-only
- [ ] Routing: edges are orthogonal point sequences consumed by renderers (no single-elbow PPTX connector assumption)
- [ ] Validation vs lint: hard errors still block writes/render; lint stays quality-only (FC001–FC008) and read-only
- [ ] Constraint-6 regression tests added/updated where touched: render leaves source bytes unchanged, layout commits revision+1, TextLayout/SVG line-count agreement, routing determinism, patch failure leaves the file byte-identical
