/**
 * The PaperCanvas bridge — the one place this plugin talks to the engine.
 *
 * The same two rules from the dsh-sessionflow contract apply here:
 *
 *  * **argv arrays only.** Arguments go to `spawn` as an array; no shell string
 *    is ever built, so a path containing spaces, `;` or a CJK label is data,
 *    not syntax.
 *  * **no second implementation.** Every call targets a `papercanvas` CLI
 *    subcommand that already exists. The plugin never parses the Figure IR,
 *    renders, or lints itself — the engine stays the single source of truth,
 *    and its transactional guarantees (atomic writes, revision checks) hold
 *    for every tool call.
 *
 * Read surfaces that emit JSON on the CLI (`inspect`, `lint`) are returned as
 * parsed objects; mutation surfaces (`init`, `patch`, `layout`, `render`)
 * return the CLI's own concise text, which names the files written and the
 * revision bumped.
 *
 * Every failure is a typed {@link PapercanvasError} with an actionable
 * message, so a tool can surface *why* figures are unavailable.
 */

import { spawn } from 'node:child_process';

/** CLI contract this plugin was written against. */
export const REQUIRED_CLI_VERSION = '0.1.0';

const DEFAULT_TIMEOUT_MS = 60_000;

export interface PapercanvasVersion {
  /** The full first line, e.g. `papercanvas 0.1.0`. */
  raw: string;
  version: string;
}

export type PapercanvasErrorCode =
  | 'PAPERCANVAS_NOT_FOUND'
  | 'TIMEOUT'
  | 'NO_OUTPUT'
  | 'BAD_JSON'
  | 'OP_ERROR'
  | 'CLI_FAILED'
  | 'INCOMPATIBLE';

export class PapercanvasError extends Error {
  readonly code: PapercanvasErrorCode;
  readonly detail: string | undefined;

  constructor(code: PapercanvasErrorCode, message: string, detail?: string) {
    super(message);
    this.name = 'PapercanvasError';
    this.code = code;
    this.detail = detail;
  }
}

/** A resolved way to invoke the engine: `<command> <prefixArgs...> <args...>`. */
export interface PapercanvasCommand {
  command: string;
  prefixArgs: string[];
}

export interface BridgeOptions {
  /** Explicit executable (plugin config `papercanvasBin`, else `$PAPERCANVAS_BIN`). */
  papercanvasBin?: string;
  /** Leading arguments for {@link papercanvasBin}. */
  papercanvasArgs?: string[];
  /** Python interpreter for the `python -m papercanvas.cli` fallback. */
  python?: string;
  /** Per-call deadline in milliseconds (default 60000 — PDF/PPTX writes files). */
  timeoutMs?: number;
}

interface RunResult {
  stdout: string;
  stderr: string;
  code: number | null;
}

/** Probes and results are cached per configuration, like the engine itself. */
let cachedKey: string | null = null;
let cachedCommand: PapercanvasCommand | null = null;
let cachedVersion: PapercanvasVersion | null = null;
let inFlight: Promise<PapercanvasCommand> | null = null;
let inFlightKey: string | null = null;

/** Reset the process-wide caches (tests). */
export function resetBridgeCache(): void {
  cachedKey = null;
  cachedCommand = null;
  cachedVersion = null;
  inFlight = null;
  inFlightKey = null;
}

function cacheKey(opts: BridgeOptions): string {
  return JSON.stringify([
    opts.papercanvasBin ?? process.env['PAPERCANVAS_BIN'] ?? null,
    opts.papercanvasArgs ?? null,
    opts.python ?? process.env['PAPERCANVAS_PYTHON'] ?? null,
  ]);
}

function candidates(opts: BridgeOptions): PapercanvasCommand[] {
  const out: PapercanvasCommand[] = [];
  const bin = opts.papercanvasBin ?? process.env['PAPERCANVAS_BIN'];
  if (bin) out.push({ command: bin, prefixArgs: [...(opts.papercanvasArgs ?? [])] });
  out.push({ command: 'papercanvas', prefixArgs: [] });
  if (process.platform === 'win32') {
    // A pip console-script install puts `papercanvas.exe` on PATH; the npm shim
    // is `papercanvas.cmd`, which cannot be spawned without a shell.
    out.push({ command: 'papercanvas.exe', prefixArgs: [] });
  }
  const python = opts.python ?? process.env['PAPERCANVAS_PYTHON'];
  if (python) {
    out.push({ command: python, prefixArgs: ['-m', 'papercanvas.cli'] });
  }
  if (process.platform === 'win32') {
    out.push({ command: 'py', prefixArgs: ['-m', 'papercanvas.cli'] });
  }
  out.push({ command: 'python', prefixArgs: ['-m', 'papercanvas.cli'] });
  out.push({ command: 'python3', prefixArgs: ['-m', 'papercanvas.cli'] });
  return out;
}

function run(cmd: PapercanvasCommand, args: string[], opts: BridgeOptions,
             stdin?: string): Promise<RunResult> {
  return new Promise<RunResult>((resolve, reject) => {
    const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    let child;
    try {
      child = spawn(cmd.command, [...cmd.prefixArgs, ...args], {
        windowsHide: true,
        shell: false,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (e) {
      reject(new PapercanvasError('PAPERCANVAS_NOT_FOUND',
        `could not start '${cmd.command}': ${String(e)}`));
      return;
    }

    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (fn: () => void): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn();
    };
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* already gone */ }
      finish(() => reject(new PapercanvasError('TIMEOUT',
        `\`${cmd.command} ${[...cmd.prefixArgs, ...args].join(' ')}\` exceeded ${timeoutMs}ms`)));
    }, timeoutMs);

    child.stdout?.setEncoding('utf8');
    child.stderr?.setEncoding('utf8');
    child.stdout?.on('data', (d: string) => { stdout += d; });
    child.stderr?.on('data', (d: string) => { stderr += d; });
    child.on('error', (e: NodeJS.ErrnoException) => {
      finish(() => reject(e.code === 'ENOENT'
        ? new PapercanvasError('PAPERCANVAS_NOT_FOUND', `'${cmd.command}' is not on PATH`)
        : new PapercanvasError('CLI_FAILED', `'${cmd.command}' failed: ${e.message}`)));
    });
    child.on('close', (code: number | null) => {
      finish(() => resolve({ stdout, stderr, code }));
    });

    if (child.stdin) {
      if (stdin !== undefined) child.stdin.write(stdin);
      child.stdin.end();
    }
  });
}

export interface ProbeFailure {
  ok: false;
  reason: string;
  found: boolean;
}

export type ProbeResult = { ok: true } | ProbeFailure;

/**
 * Prove one candidate works. The probe is `--version`: exit 0 and a stdout
 * starting with `papercanvas ` is the CLI contract since v0.1.0.
 */
async function probe(cmd: PapercanvasCommand, opts: BridgeOptions): Promise<ProbeResult> {
  const shown = [cmd.command, ...cmd.prefixArgs].join(' ');
  try {
    const { stdout, stderr, code } = await run(cmd, ['--version'],
      { ...opts, timeoutMs: Math.max(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS, DEFAULT_TIMEOUT_MS) });
    if (code !== 0) {
      const why = (stderr.trim().split(/\r?\n/).find((l) => l.trim().length > 0) ?? '').slice(0, 200);
      return {
        ok: false, found: false,
        reason: `\`${shown} --version\` exited ${code}${why ? `: ${why}` : ''}`,
      };
    }
    const line = stdout.trim().split(/\r?\n/)[0] ?? '';
    if (!line.startsWith('papercanvas ')) {
      return {
        ok: false, found: true,
        reason: `\`${shown} --version\` answered "${line.slice(0, 80)}" instead of a papercanvas version`,
      };
    }
    return { ok: true };
  } catch (e) {
    return {
      ok: false, found: false,
      reason: `\`${shown}\` could not be started or timed out: ` +
              `${e instanceof Error ? e.message : String(e)}`,
    };
  }
}

function configuredBin(opts: BridgeOptions): string | undefined {
  return opts.papercanvasBin ?? process.env['PAPERCANVAS_BIN'];
}

/**
 * Find a working engine, or explain precisely why none was found.
 *
 * A **configured** executable is authoritative: if it fails the probe this
 * throws instead of falling through to a PATH candidate, because another
 * install on PATH may be a different papercanvas with different figures.
 */
export async function resolvePapercanvas(opts: BridgeOptions = {}): Promise<PapercanvasCommand> {
  const key = cacheKey(opts);
  if (cachedCommand && cachedKey === key) return cachedCommand;
  if (inFlight && inFlightKey === key) return inFlight;

  const pending = resolveUncached(opts, key);
  inFlight = pending;
  inFlightKey = key;
  try {
    return await pending;
  } finally {
    if (inFlight === pending) {
      inFlight = null;
      inFlightKey = null;
    }
  }
}

async function resolveUncached(opts: BridgeOptions,
                               key: string): Promise<PapercanvasCommand> {
  const bin = configuredBin(opts);
  const [first, ...rest] = candidates(opts);
  if (first === undefined) {
    throw new PapercanvasError('PAPERCANVAS_NOT_FOUND', 'no candidate command to probe');
  }
  const firstProbe = await probe(first, opts);
  if (firstProbe.ok) {
    cachedCommand = first;
    cachedKey = key;
    return first;
  }
  if (bin) {
    if (firstProbe.found) {
      throw new PapercanvasError('INCOMPATIBLE',
        `the configured papercanvas cannot be used: ${firstProbe.reason}`,
        `Refusing to fall back to another papercanvas on PATH: it may be a ` +
        `different install with different figures. Fix the path, or remove ` +
        `\`papercanvasBin\` (and \`PAPERCANVAS_BIN\`) to let the plugin ` +
        `discover the engine from PATH.`);
    }
    throw new PapercanvasError('PAPERCANVAS_NOT_FOUND',
      `the configured papercanvas executable does not work: ${firstProbe.reason}`,
      `Refusing to fall back to another papercanvas on PATH. Fix the path, ` +
      `or remove \`papercanvasBin\` (and \`PAPERCANVAS_BIN\`) to let the ` +
      `plugin discover the engine from PATH.`);
  }

  const failures: ProbeFailure[] = [firstProbe];
  for (const cmd of rest) {
    const r = await probe(cmd, opts);
    if (r.ok) {
      cachedCommand = cmd;
      cachedKey = key;
      return cmd;
    }
    failures.push(r);
  }
  throw unresolvableEngineError(failures);
}

/**
 * Every candidate failed. A found-but-refused engine is a different problem
 * with a different fix than a missing one.
 */
export function unresolvableEngineError(failures: ProbeFailure[]): PapercanvasError {
  const present = failures.find((f) => f.found);
  if (present) {
    return new PapercanvasError('INCOMPATIBLE',
      `a papercanvas was found but this plugin cannot use it: ${present.reason}`,
      `This plugin needs the papercanvas CLI (v${REQUIRED_CLI_VERSION} or newer). ` +
      `Reinstall it and check \`papercanvas --version\`.`);
  }
  return new PapercanvasError('PAPERCANVAS_NOT_FOUND',
    'the papercanvas engine is not reachable from this DSH process. Either it ' +
    'is not installed, or it is installed where this process cannot see it.',
    `What was tried: ${failures.map((f) => f.reason).join('; ')}\n\n` +
    `Install it from the PaperCanvas repository (pip install -e .) or from ` +
    `PyPI once published (pip install papercanvas). If it is installed in a ` +
    `virtualenv that is not active here, point at it directly:\n` +
    `    PAPERCANVAS_BIN=/full/path/to/papercanvas\n` +
    `or activate the venv before starting DSH.`);
}

/** Run a read surface that emits JSON (`inspect` / `lint --format json`). */
export async function callJson<T>(args: string[], opts: BridgeOptions = {}): Promise<T> {
  const cmd = await resolvePapercanvas(opts);
  const { stdout, stderr, code } = await run(cmd, args, opts);
  if (code !== 0) {
    const why = (stderr.trim().split(/\r?\n/).find((l) => l.trim().length > 0)
      ?? stdout.trim().split(/\r?\n/).find((l) => l.trim().length > 0)
      ?? '').slice(0, 400);
    throw new PapercanvasError('OP_ERROR',
      `\`papercanvas ${args.join(' ')}\` failed with exit code ${code}`,
      why || undefined);
  }
  try {
    return JSON.parse(stdout) as T;
  } catch {
    throw new PapercanvasError('BAD_JSON',
      `\`papercanvas ${args.join(' ')}\` did not return JSON`, stdout.slice(0, 400));
  }
}

/**
 * Run a mutation/read surface that reports in concise text (init, patch,
 * layout, render). Exit code 0 is the success contract; the text is the
 * tool's output.
 */
export async function callText(args: string[], opts: BridgeOptions = {},
                               stdin?: string): Promise<string> {
  const cmd = await resolvePapercanvas(opts);
  const { stdout, stderr, code } = await run(cmd, args, opts, stdin);
  if (code !== 0) {
    const why = (stderr.trim().split(/\r?\n/).find((l) => l.trim().length > 0)
      ?? stdout.trim().split(/\r?\n/).find((l) => l.trim().length > 0)
      ?? '').slice(0, 400);
    throw new PapercanvasError('OP_ERROR',
      `\`papercanvas ${args.join(' ')}\` failed with exit code ${code}`,
      why || undefined);
  }
  return stdout;
}
