/**
 * dsh-figcraft — integration tests against the real engine.
 *
 * These run the repository's own `papercanvas` CLI (the package under test is
 * the plugin; the engine is provided by `uv sync` in this repository). Every
 * figure is created under a throwaway temp dir; read-only tools are verified
 * not to modify the IR, mirroring the engine's own contract tests.
 *
 * Skipped honestly when no engine is on PATH: the mechanics tests above still
 * prove the bridge. A guard that cannot run must say so, not pass silently.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  resetBridgeCache,
  callJson,
  callText,
  type BridgeOptions,
} from '../lib/bridge.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');

function engineCommand(): string[] | null {
  for (const cmd of process.platform === 'win32'
    ? ['papercanvas.exe', 'papercanvas.cmd']
    : ['papercanvas']) {
    const r = spawnSync(cmd, ['--version'], { encoding: 'utf8' });
    if (r.status === 0 && r.stdout.includes('papercanvas ')) return [cmd];
  }
  const uvTry = spawnSync('uv', ['run', 'papercanvas', '--version'], {
    encoding: 'utf8',
    cwd: REPO,
  });
  if (uvTry.status === 0 && uvTry.stdout.includes('papercanvas ')) {
    return ['uv', 'run', '--project', REPO, 'papercanvas'];
  }
  return null;
}

const engine = engineCommand();
const opts = (): BridgeOptions => ({ papercanvasBin: engine?.[0], papercanvasArgs: engine?.slice(1) });

test('integration: the real engine answers the whole workflow', { skip: engine === null ? 'papercanvas CLI not on PATH' : false }, async () => {
  assert.ok(engine);
  resetBridgeCache();
  const work = mkdtempSync(join(tmpdir(), 'dsh-figcraft-'));
  const ir = join(work, 'fig.json');

  // create
  const created = await callText(['init', ir, '--id', 'dsh_e2e'], opts());
  assert.match(created, /created/);

  // patch (stdin contract: --ops -)
  const patched = await callText(
    ['patch', ir, '--ops', '-'],
    opts(),
    JSON.stringify({
      operations: [
        { op: 'add_node', node: { id: 'a', type: 'rounded_rect', label: 'Input' } },
        { op: 'add_node', node: { id: 'b', type: 'rounded_rect', label: 'Output' } },
        { op: 'add_edge', edge: { id: 'e1', source: 'a', target: 'b' } },
      ],
    }),
  );
  assert.match(patched, /revision 2/);

  // layout
  assert.match(await callText(['layout', ir, '--preset', 'layered'], opts()), /revision 3/);

  // inspect: structured JSON, read-only
  const inventory = (await callJson<{ objects: Array<{ id: string }> }>(
    ['inspect', ir, '--format', 'json'],
    opts(),
  )) as { objects: Array<{ id: string }> };
  assert.ok(inventory.objects.some((o) => o.id === 'a'));
  assert.ok(inventory.objects.some((o) => o.id === 'b'));

  // lint: clean
  const lint = (await callJson<{ summary: { errors: number; warnings: number } }>(
    ['lint', ir, '--format', 'json'],
    opts(),
  )) as { summary: { errors: number; warnings: number } };
  assert.equal(lint.summary.errors, 0);

  // render: three artifacts
  const rendered = await callText(['render', ir, '--format', 'all'], opts());
  assert.match(rendered, /rendered/);
  for (const suffix of ('.svg .pdf .pptx').split(' ')) {
    const artifact = ir.slice(0, -'.json'.length) + suffix;
    const bytes = readFileSync(artifact);
    assert.ok(bytes.length > 0, `${artifact} is empty`);
  }

  // read-only guarantee: inspecting does not change the file
  const before = readFileSync(ir);
  await callJson(['inspect', ir, '--format', 'json'], opts());
  assert.equal(readFileSync(ir).toString(), before.toString());

  rmSync(work, { recursive: true, force: true });
});
