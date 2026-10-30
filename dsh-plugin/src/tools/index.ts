/**
 * The seven papercanvas_* tools — one per engine surface, in workflow order:
 * create → get → patch → layout → lint → render, with inspect for reading
 * state before patching.
 *
 * Output contract:
 *  - `papercanvas_get` / `papercanvas_lint` / `papercanvas_inspect` return the
 *    engine's JSON (parsed objects) — the model reads structured state;
 *  - the mutation surfaces (`create`, `patch`, `layout`, `render`) return the
 *    CLI's concise text, which names the files written and the revision.
 *
 * Every failure is an actionable error: the engine's transactional guarantees
 * mean "operation 2 failed: …" still leaves the figure untouched, so the agent
 * can fix the operation and re-apply the same batch.
 */

import { defineTool } from '@deepseek-ai/dsh-tools';
import {
  callJson,
  callText,
  type BridgeOptions,
} from '../bridge.js';

/**
 * A tool body, turning any failure into a clean, actionable error.
 *
 * The return type is deliberately `any`: the registry types a tool's
 * canonical output as `JsonValue`, and the value here is the engine's own
 * JSON contract (validated by the engine, not by a duplicate schema in the
 * plugin). Mirrors dsh-sessionflow's tools/common.ts.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function guarded(body: () => Promise<unknown>): Promise<any> {
  try {
    return await body();
  } catch (e) {
    throw new Error(e instanceof Error ? e.message : String(e));
  }
}

/** Canonical output is the CLI's own concise text (files written, revision). */
function textOutput() {
  return {
    schema: { type: 'string' as const },
    render: (_args: unknown, value: string) => [
      { type: 'text' as const, text: value },
    ],
  };
}

/** Canonical output is structured JSON the model reads directly. */
function jsonOutput() {
  return {
    schema: { type: 'json' as const },
    render: (_args: unknown, value: unknown) => [
      { type: 'text' as const, text: JSON.stringify(value, null, 2) },
    ],
  };
}

export function createTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_create',
    description:
      'Create a new PaperCanvas figure IR file (the single source of truth for ' +
      'a scientific figure). Nodes and edges are added afterwards with ' +
      'papercanvas_patch; coordinates are filled in by papercanvas_layout.',
    parameters: {
      path: {
        type: 'string',
        required: true,
        description: 'File path of the new figure IR (.json), inside the workspace.',
      },
      figure_id: {
        type: 'string',
        required: true,
        description: 'Figure id ([A-Za-z0-9_-]).',
      },
      width: {
        type: 'string',
        description: 'Optional canvas width in mm (default 182).',
      },
      height: {
        type: 'string',
        description: 'Optional canvas height in mm (default 58).',
      },
    },
    output: textOutput(),
    async execute(args) {
      return await guarded(async () => {
        const argv = ['init', args.path, '--id', args.figure_id];
        if (args.width !== undefined) argv.push('--width', args.width);
        if (args.height !== undefined) argv.push('--height', args.height);
        return await callText(argv, bridge);
      });
    },
  });
}

export function getTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_get',
    description:
      'Read a figure: inventory of nodes/edges/groups plus hard_errors — the ' +
      'structural problems that block render/patch. Call this before patching.',
    parameters: {
      path: { type: 'string', required: true, description: 'Figure IR file path.' },
    },
    output: jsonOutput(),
    async execute(args) {
      return await guarded(() =>
        callJson<unknown>(['inspect', args.path, '--format', 'json'], bridge));
    },
  });
}

export function patchTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_patch',
    description:
      'Apply a batch of semantic operations to a figure in ONE all-or-nothing ' +
      'transaction: add_node, remove_node (with remove_edges:true), update_node, ' +
      'set_style, add_edge, remove_edge, add_group, update_label, move_node. ' +
      'Success bumps the revision; any failure leaves the file byte-identical. ' +
      'Pass expected_revision for optimistic concurrency.',
    parameters: {
      path: { type: 'string', required: true, description: 'Figure IR file path.' },
      operations: {
        type: 'string',
        required: true,
        description:
          'JSON array of operations, e.g. [{"op":"add_node","node":{"id":"enc","label":"Encoder"}}].',
      },
      expected_revision: {
        type: 'string',
        description: 'Optional revision the caller loaded; the patch fails cleanly if it moved.',
      },
    },
    output: textOutput(),
    async execute(args) {
      return await guarded(async () => {
        // Validate the JSON here so a malformed payload is a tool error before
        // anything reaches the engine (which would reject it transactionally).
        const operations = JSON.parse(args.operations) as unknown;
        const request: Record<string, unknown> = { operations };
        if (args.expected_revision !== undefined) {
          request['expected_revision'] = Number(args.expected_revision);
        }
        // `--ops -` reads the batch from stdin: argv arrays only, no temp files.
        return await callText(
          ['patch', args.path, '--ops', '-'],
          bridge,
          JSON.stringify(request),
        );
      });
    },
  });
}

export function layoutTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_layout',
    description:
      'Arrange nodes (preset: layered for DAG flow, linear-h / linear-v for ' +
      'simple rows/columns) and commit the coordinates; revision bumps by one. ' +
      'Run this before the first render.',
    parameters: {
      path: { type: 'string', required: true, description: 'Figure IR file path.' },
      preset: { type: 'string', description: 'linear-h (default) | linear-v | layered.' },
    },
    output: textOutput(),
    async execute(args) {
      return await guarded(async () =>
        await callText(['layout', args.path, '--preset', args.preset ?? 'linear-h'], bridge));
    },
  });
}

export function lintTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_lint',
    description:
      'Quality checks FC001-FC008: canvas bounds, structure, text overflow, ' +
      'overlap, arrows through nodes, font substitution. severity "error" ' +
      'means fix before delivering; warnings are advisory. Read-only.',
    parameters: {
      path: { type: 'string', required: true, description: 'Figure IR file path.' },
      min_font_size_pt: {
        type: 'string',
        description: 'FC005 threshold in pt (default 6).',
      },
    },
    output: jsonOutput(),
    async execute(args) {
      return await guarded(async () => {
        const argv = ['lint', args.path, '--format', 'json'];
        if (args.min_font_size_pt !== undefined) {
          argv.push('--min-font-size', args.min_font_size_pt);
        }
        return await callJson<unknown>(argv, bridge);
      });
    },
  });
}

export function renderTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_render',
    description:
      'Export the figure to true-vector, editable SVG / PDF / PPTX (layout ' +
      'must have run). Read-only on the IR. Reports glyph-coverage warnings ' +
      'when the machine lacks fonts for some labels.',
    parameters: {
      path: { type: 'string', required: true, description: 'Figure IR file path.' },
      format: { type: 'string', description: 'svg | pdf | pptx | all (default svg).' },
    },
    output: textOutput(),
    async execute(args) {
      return await guarded(async () =>
        await callText(['render', args.path, '--format', args.format ?? 'svg'], bridge));
    },
  });
}

export function inspectTool(bridge: BridgeOptions) {
  return defineTool({
    name: 'papercanvas_inspect',
    description:
      'Full detail for one object (geometry, style, connected edges, groups) ' +
      'or the whole-figure inventory. Read-only. Use this to plan a patch ' +
      'without touching the file.',
    parameters: {
      path: { type: 'string', required: true, description: 'Figure IR file path.' },
      object_id: { type: 'string', description: 'Optional object id for full detail.' },
    },
    output: jsonOutput(),
    async execute(args) {
      return await guarded(async () => {
        const argv = ['inspect', args.path, '--format', 'json'];
        if (args.object_id !== undefined) argv.push(args.object_id);
        return await callJson<unknown>(argv, bridge);
      });
    },
  });
}

/** All seven tools, registered by index.apply(). */
export function figcraftTools(bridge: BridgeOptions) {
  return [
    createTool(bridge),
    getTool(bridge),
    patchTool(bridge),
    layoutTool(bridge),
    lintTool(bridge),
    renderTool(bridge),
    inspectTool(bridge),
  ];
}
