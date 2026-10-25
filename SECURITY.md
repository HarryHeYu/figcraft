# Security Policy

## Supported versions

| Version | Support |
|---|---|
| 0.1.x (current release candidate; PyPI publication pending) | security fixes |
| < 0.1.0 | never published — no support |

PaperCanvas is pre-1.0: fixes land on the latest `0.1.x` line only.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting — the **Security → Report a
vulnerability** form on `HarryHeYu/figcraft`, which opens a private GitHub
Security Advisory. Do not file public issues for vulnerabilities. (A direct
contact address may be added later; until then the advisory form above is
the authoritative private channel.)

**Response expectation**: acknowledgment within **72 hours**, then an
assessment; accepted reports get a fix and coordinated disclosure with credit.

## Known security design (v0.1)

- **MCP path whitelist**: every path argument of the seven `papercanvas_*`
  tools must resolve inside the server's `--root` directory; escapes return
  `{"ok": false, "error": ...}` and write nothing.
- **No network access**: the MCP server speaks stdio only; the codebase
  makes no network calls.
- **No code execution**: nothing is `eval`-ed, `exec`-ed or spawned; the
  Figure IR is parsed as data by strict Pydantic models that reject unknown
  fields.
- **Output confinement**: renderers write next to the IR inside the root
  and never overwrite the IR file itself (guarded, atomic commit via temp
  file + `os.replace`).
- **Read-only tools**: `get`, `lint` and `inspect` never write to disk.
- **Validation gate**: hard validation (`core/validate.py`) blocks every
  write and render of an invalid figure.

## Scope

The `papercanvas` package, the `papercanvas` CLI and the `papercanvas-mcp`
server in this repository. Files under `examples/` are fixtures, not attack
surface. See [docs/mcp.md](docs/mcp.md) for the full MCP security posture.
