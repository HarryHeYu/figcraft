# Contributing to PaperCanvas

PaperCanvas is an agent-native scientific figure studio: the Figure IR (JSON)
is the single source of truth; SVG/PDF/PPTX are build products. This guide
covers what a contribution needs.

Naming: the product is **PaperCanvas**; the package, CLI and MCP tool prefix
are **`papercanvas`** (the GitHub repository is `HarryHeYu/figcraft` — a
recorded decision). Do not introduce "FigCraft" as a package or CLI name.

## Development setup

Prerequisites: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/HarryHeYu/figcraft.git
cd figcraft
uv sync                     # creates .venv, installs locked dependencies
uv run papercanvas --help
```

## Engineering constraints

Six hard engineering constraints govern every change: naming unity, the
unified TextLayout (only place that wraps text), the read/write discipline
(only Patch and Layout may write the IR, via lock + `expected_revision` +
atomic commit), the routing point-list regime, the validation/lint split,
and mandatory regression tests. The normative text lives in
[AGENTS.md](AGENTS.md) — read it before your first change; every PR is
reviewed against those six items.

## Branching and commits

Trunk-based: `main` receives direct, self-contained commits; use a feature
branch + PR for larger or risky changes. Commit messages use conventional
prefixes with an imperative subject, matching the existing history:
`feat:`, `fix:`, `docs:`, `test:`, `release:`, with optional scope
(e.g. `fix(gate): ...`).

## Tests

- Every new feature or bug fix ships with a test. No empty implementations,
  no pseudo-tests, no silently skipped tests.
- The suite is 241 tests at v0.1.0-rc1; the authoritative count is always the
  actual output of `uv run pytest`.
- Changes to render/layout/text paths have dedicated regression classes
  (constraint 6): render must not modify source bytes, a successful layout
  commits `revision + 1`, TextLayout and SVG agree on line counts, routing
  point sequences are deterministic, a failed patch leaves the file
  byte-identical.

## Pull request checklist

CI runs ruff + pytest on Python 3.12/3.14 across ubuntu/windows/macos.

- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` passes locally (paste the count in the PR)
- [ ] New behavior is covered by tests
- [ ] Platform impact considered (font resolution, paths, line endings) and
      stated in the PR description
- [ ] User-facing docs updated (README, `docs/`, CHANGELOG.md entry)

## Local verification

```bash
uv run ruff check .
uv run pytest -v
uv run papercanvas build examples/basic_pipeline.json --format all
uv run papercanvas lint examples/basic_pipeline.json
```

## Reporting issues

Bug reports and feature proposals use the issue templates. Security issues
never go to public issues — see [SECURITY.md](SECURITY.md).
