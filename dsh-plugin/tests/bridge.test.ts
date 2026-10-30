/**
 * dsh-figcraft — bridge contract tests.
 *
 * Mechanics are proven against stub executables (papercanvasBin + a node -e
 * script), so they are hermetic and fast: discovery, timeouts, non-zero
 * exits, malformed JSON. Integration runs the real engine via the repo's own
 * CLI (`papercanvas`, provided by `uv sync` in this repository) and is
 * guarded — a machine without it proves less, honestly.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  PapercanvasError,
  resetBridgeCache,
  resolvePapercanvas,
  callJson,
  callText,
  type BridgeOptions,
} from '../lib/bridge.js';

function stubBin(script: string): BridgeOptions {
  // The stub runs under the current node. `--` separates node's own flags from
  // the script's argv — without it, node's own `--version` would swallow the
  // probe's `--version` and the script would never run (observed).
  return { papercanvasBin: process.execPath, papercanvasArgs: ['-e', script, '--'] };
}

/** Does this machine have the repo's own engine on PATH (or a venv)? */
function papercanvasAvailable(): boolean {
  for (const cmd of process.platform === 'win32'
    ? ['papercanvas.exe', 'papercanvas.cmd']
    : ['papercanvas']) {
    const r = spawnSync(cmd, ['--version'], { encoding: 'utf8' });
    if (r.status === 0 && r.stdout.includes('papercanvas ')) return true;
  }
  const uv = spawnSync('uv', ['run', 'papercanvas', '--version'], {
    encoding: 'utf8',
    cwd: join(__dirname, '..', '..'),
  });
  return uv.status === 0 && uv.stdout.includes('papercanvas ');
}

test('a configured bin answering with a wrong version is INCOMPATIBLE', async () => {
  resetBridgeCache();
  // A configured bin is authoritative: found-but-wrong must not silently fall
  // back to another install on PATH.
  await assert.rejects(
    resolvePapercanvas(stubBin("console.log('not-a-papercanvas 9.9')")),
    (e: unknown) =>
      e instanceof PapercanvasError && e.code === 'INCOMPATIBLE',
  );
});

test('a stub that exits non-zero on --version is a clean NOT_FOUND', async () => {
  resetBridgeCache();
  await assert.rejects(
    resolvePapercanvas(stubBin("process.exit(3)")),
    (e: unknown) =>
      e instanceof PapercanvasError && e.code === 'PAPERCANVAS_NOT_FOUND',
  );
});

test('callText surfaces a non-zero exit as OP_ERROR with the engine text', async () => {
  resetBridgeCache();
  // Probe passes, the op fails: the stub branches on argv.
  await assert.rejects(
    callText(
      ['patch', 'x.json', '--ops', '-'],
      stubBin(
        'if (process.argv[1] === "--version") { console.log("papercanvas 0.1.0"); }' +
        'else { console.error("error: operation 0: nope"); process.exit(1); }',
      ),
      '{"operations": []}',
    ),
    (e: unknown) =>
      e instanceof PapercanvasError && e.code === 'OP_ERROR' &&
      String((e as PapercanvasError).detail ?? '').includes('nope'),
  );
});

test('callJson rejects non-JSON output as BAD_JSON', async () => {
  resetBridgeCache();
  await assert.rejects(
    callJson(
      ['lint', 'x.json', '--format', 'json'],
      stubBin(
        'if (process.argv[1] === "--version") { console.log("papercanvas 0.1.0"); }' +
        'else { console.log("<not json>"); }',
      ),
    ),
    (e: unknown) => e instanceof PapercanvasError && e.code === 'BAD_JSON',
  );
});

test('a hung engine is killed at the deadline and reported as TIMEOUT', async () => {
  resetBridgeCache();
  await assert.rejects(
    callText(
      ['render', 'x.json'],
      {
        papercanvasBin: process.execPath,
        papercanvasArgs: [
          '-e',
          'if (process.argv[1] === "--version") { console.log("papercanvas 0.1.0"); }' +
          'else { setTimeout(() => {}, 60000); }',
          '--',
        ],
        timeoutMs: 300,
      },
    ),
    (e: unknown) => e instanceof PapercanvasError && e.code === 'TIMEOUT',
  );
});

test('an empty PATH means discovery fails honestly', async () => {
  resetBridgeCache();
  const saved = process.env['PAPERCANVAS_BIN'];
  delete process.env['PAPERCANVAS_BIN'];
  const savedPath = process.env['PATH'];
  process.env['PATH'] = '';
  try {
    // process.execPath still runs (spawn uses it directly), but the probe
    // candidates go through PATH lookups that now fail.
    await assert.rejects(
      resolvePapercanvas({}),
      (e: unknown) => e instanceof PapercanvasError,
    );
  } finally {
    if (savedPath !== undefined) process.env['PATH'] = savedPath;
    if (saved !== undefined) process.env['PAPERCANVAS_BIN'] = saved;
    resetBridgeCache();
  }
});
