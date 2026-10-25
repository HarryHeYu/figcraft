# Versioning

PaperCanvas versions two things independently: the **package** and the
**Figure IR schema**. This document states the promises each one carries.

## Package version (SemVer)

The package version in `pyproject.toml` (and `papercanvas.__version__`)
follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.
The changelog of record is [CHANGELOG.md](../CHANGELOG.md).

- **PATCH** — bug fixes only, no API or IR changes.
- **MINOR** — new features, and (pre-1.0) breaking changes, each documented
  in CHANGELOG.md with a migration note. Pre-1.0, the minor version is the
  breaking-change signal.
- **MAJOR** — breaking changes after 1.0.

Current state: `0.1.0` (release candidate built and verified; PyPI
publication pending). `0.1.x` releases stay compatible within the line.

## Figure IR `schema_version`

Every IR file carries `schema_version`. Strictness is deliberate: readers
accept only schema versions they know, and unknown fields are rejected
(`extra=forbid`), so there is no silent forward compatibility and no
half-interpreted files.

- v0.1 readers accept **only `"0.1"`**; any other value is a hard validation
  error at load time.
- When the IR evolves, the new `papercanvas` version will read the previous
  schema version for at least one minor release and document the migration
  in CHANGELOG.md. Rendering an old file always requires an explicit
  migration step (a patch or CLI upgrade path) — never an implicit rewrite.
- New optional IR fields land with a minor bump; they must be ignored safely
  by older readers only where the reader already rejects the file, which is
  why additive changes still bump `schema_version` and are announced.

## `revision` and concurrency

`revision` (int ≥ 1) is the optimistic-concurrency counter of one IR file —
it is not the package version and not the schema version.

- Every committed change increments it by exactly 1: one successful patch
  batch (however many operations), one successful layout. Read-only
  operations (`render`, `lint`, `inspect`, `validate`) never touch it.
- Writers pass `expected_revision`; the check happens against the on-disk
  file **inside the sidecar file lock**, so two agents cannot interleave.
- A mismatch is a clean `DocumentConflictError` (MCP:
  `{"ok": false, "error": ...}`) — the file stays byte-identical, and the
  agent re-reads and retries.
- All writes are atomic (temp file + `os.replace`): a crash mid-write never
  corrupts the IR.

## Determinism across versions

Same IR + same fonts + same package version ⇒ byte-identical SVG/PDF/PPTX.
Output is not guaranteed byte-stable across package versions; compare via
the IR (the source of truth) or re-render.

## Known evolution points (v0.1 → later)

Planned or reserved, none of them promised in `0.1.x`:

- CJK-capable font fallback for PDF, plus an FC007 glyph-coverage extension.
- Obstacle avoidance in orthogonal routing (FC006 currently reports
  crossings after the fact).
- Group-label auto-wrapping (explicit `\n` is honored today).
- `canvas.unit` beyond `mm`.
- Node types beyond `rect` / `rounded_rect`.
- PPTX→IR reverse sync is explicitly out of scope for v0.1.
