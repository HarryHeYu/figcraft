/**
 * dsh-figcraft — PaperCanvas for DeepSeek Harness.
 *
 * Seven tools over the papercanvas CLI, one per engine surface. The plugin is
 * a **thin adapter**: it never parses the Figure IR, lays out, renders or
 * lints itself — every call goes to the papercanvas CLI, whose transactional
 * guarantees (atomic writes, revision checks, all-or-nothing patches) hold
 * for every tool call.
 *
 *   DSH → plugin tool → bridge (argv, text/JSON) → papercanvas CLI → result
 */

import type { Context } from '@deepseek-ai/cordis';
import {
  resolvePapercanvas,
  type BridgeOptions,
} from './bridge.js';
import { figcraftTools } from './tools/index.js';

export const name = 'dsh-figcraft';

/** The tools service must be mounted before the tools can be registered. */
export const inject = ['tools'];

export interface Config {
  /**
   * Explicit `papercanvas` executable. When omitted the plugin tries
   * `papercanvas` on PATH and then `python -m papercanvas.cli`.
   */
  papercanvasBin?: string;
  /** Leading arguments for `papercanvasBin`. */
  papercanvasArgs?: string[];
  /** Python interpreter used by the `python -m papercanvas.cli` fallback. */
  python?: string;
  /** Per-call deadline in milliseconds (default 60000). */
  timeoutMs?: number;
}

export function apply(ctx: Context, config: Config = {}): void {
  const bridge: BridgeOptions = {};
  if (config.papercanvasBin !== undefined) bridge.papercanvasBin = config.papercanvasBin;
  if (config.papercanvasArgs !== undefined) bridge.papercanvasArgs = config.papercanvasArgs;
  if (config.python !== undefined) bridge.python = config.python;
  if (config.timeoutMs !== undefined) bridge.timeoutMs = config.timeoutMs;

  if (config.papercanvasArgs !== undefined && config.papercanvasArgs.length > 0
      && config.papercanvasBin === undefined
      && process.env['PAPERCANVAS_BIN'] === undefined) {
    ctx.logger.warn(
      '[dsh-figcraft] `papercanvasArgs` is set without `papercanvasBin`, so it ' +
      'will be ignored and the default `papercanvas` will be used. Set both ' +
      'together, e.g. papercanvasBin: py + papercanvasArgs: [-m, papercanvas.cli].');
  }

  ctx.effect(() => {
    const disposers = figcraftTools(bridge).map((tool) => ctx.tools.register(tool));
    return () => {
      for (const dispose of disposers) dispose();
    };
  });

  // Prove the engine is reachable, loudly but without blocking boot: a missing
  // papercanvas must not stop DSH from starting, and the first tool call still
  // reports precisely what is wrong.
  void resolvePapercanvas(bridge)
    .then((cmd) => {
      ctx.logger.info(
        `[dsh-figcraft] papercanvas engine ready: ${cmd.command} ` +
        `${cmd.prefixArgs.join(' ')}`.trim());
    })
    .catch((e: unknown) => {
      ctx.logger.warn(`[dsh-figcraft] ${e instanceof Error ? e.message : String(e)}`);
    });
}
