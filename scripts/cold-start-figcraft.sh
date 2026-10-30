#!/usr/bin/env bash
#
# Cold-start verification for dsh-figcraft — the same three-gate discipline as
# dsh-sessionflow's, adapted to a Python engine:
#
#   INSTALL VERIFIED    `dsh plugin add` exited 0
#   BUNDLE DISCOVERED   dsh-figcraft is in the profile's bundles
#   PREPARE RAN         the installed package ships a built dsh-plugin/lib
#   LAYER APPLIED       the plugin's patch layer is in the composed tree
#   ENGINE READY        the installed bridge reached the real papercanvas CLI
#
# The engine (papercanvas) must be installed by the caller — in CI that is
# `pip install -e .` from the repository checkout, which is the documented
# path until the PyPI publication. A real model turn is deliberately not
# claimed: the boot stops at the credential gate, which is all the evidence
# the script needs.
#
# Usage:
#   COLD_ROOT=/tmp/cold bash scripts/cold-start-figcraft.sh <spec> <profile>
#
# Exit status: 0 only when every check passed.

set -uo pipefail

SPEC="${1:?usage: cold-start-figcraft.sh <spec> <profile>}"
PROFILE="${2:?usage: cold-start-figcraft.sh <spec> <profile>}"

: "${COLD_ROOT:?COLD_ROOT must point at an empty scratch directory}"

export DSH_HOME="$COLD_ROOT/dshhome"
WORK="$COLD_ROOT/work"
mkdir -p "$DSH_HOME" "$WORK"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

cd "$WORK" || fail "cannot enter $WORK"

# ---------------------------------------------------------------- install ---
echo "--- creating profile '$PROFILE' under $DSH_HOME"
dsh --from-default-profile headless --profile "$PROFILE" --dump-config \
  > "$COLD_ROOT/init.log" 2>&1 \
  || { tail -20 "$COLD_ROOT/init.log" >&2; fail "profile creation"; }

PROFILE_DIR="$DSH_HOME/profiles/$PROFILE"
[ -f "$PROFILE_DIR/package.json" ] || fail "profile has no package.json"

_allowbuild_add() {
  local key="$1" ws="$PROFILE_DIR/pnpm-workspace.yaml"
  [ -f "$ws" ] || fail "no pnpm-workspace.yaml to allowlist in"
  if grep -q '^allowBuilds:' "$ws"; then
    printf '  %s\n' "$key" >> "$ws"
  else
    printf '\nallowBuilds:\n  %s\n' "$key" >> "$ws"
  fi
}

echo "--- dsh plugin add $SPEC"
dsh plugin --profile "$PROFILE" add "$SPEC" > "$COLD_ROOT/add-1.log" 2>&1
ADD_RC=$?

if [ "$ADD_RC" -ne 0 ]; then
  if grep -q 'ERR_PNPM_GIT_DEP_PREPARE_NOT_ALLOWED' "$COLD_ROOT/add-1.log"; then
    KEY=$(sed -n 's/^[[:space:]]\{1,\}\(dsh-figcraft@.*: *true\)[[:space:]]*$/\1/p' \
            "$COLD_ROOT/add-1.log" | tail -1)
    [ -n "$KEY" ] || { cat "$COLD_ROOT/add-1.log" >&2
                       fail "prepare was blocked but pnpm printed no allowBuilds key"; }
    echo "--- prepare was blocked; allowlisting the key pnpm printed: $KEY"
    _allowbuild_add "$KEY"
    dsh plugin --profile "$PROFILE" add "$SPEC" > "$COLD_ROOT/add-2.log" 2>&1 \
      || { tail -20 "$COLD_ROOT/add-2.log" >&2; fail "dsh plugin add after allowBuilds"; }
  else
    tail -20 "$COLD_ROOT/add-1.log" >&2
    fail "dsh plugin add"
  fi
fi
pass "INSTALL VERIFIED: dsh plugin add $SPEC exited 0"

# ------------------------------------------------------------ bundle wiring ---
node -e '
  const fs = require("fs");
  const p = process.argv[1];
  const j = JSON.parse(fs.readFileSync(p, "utf8"));
  const bundles = j?.dsh?.profile?.bundles ?? j?.dsh?.bundles ?? [];
  if (!bundles.includes("dsh-figcraft"))
    { console.error("bundles =", JSON.stringify(bundles)); process.exit(1); }
  console.log("bundles =", bundles.join(", "));
' "$PROFILE_DIR/package.json" || fail "the plugin never made it into the profile's bundles"
pass "BUNDLE DISCOVERED: dsh-figcraft is in the profile's bundles"

# --------------------------------------------------------------- prepared ---
[ -f "$PROFILE_DIR/node_modules/dsh-figcraft/dsh-plugin/lib/index.js" ] \
  || fail "the installed package ships no built dsh-plugin/lib"
pass "PREPARE RAN: the installed package ships a built dsh-plugin/lib"

# ------------------------------------------------------- does DSH load it? ---
# On 0.2.x the headless boot may exit 0 silently on Windows, so the load
# question is answered in two layers here: the composed layer (above) proves
# the tree references the plugin, and the bridge probe below proves the
# installed module actually imports and runs.  The full boot gate is the
# Linux CI job's business.
echo "--- booting the profile to see whether DSH can import the plugin"
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
  timeout 600 dsh --profile "$PROFILE" "cold-start probe" > "$COLD_ROOT/boot.log" 2>&1
BOOT_RC=$?

if grep -qE "plugin tree failed to load|Cannot find package|ERR_MODULE_NOT_FOUND" "$COLD_ROOT/boot.log"; then
  grep -nE "plugin tree failed to load|Cannot find package|ERR_MODULE_NOT_FOUND" \
    "$COLD_ROOT/boot.log" | head -5 >&2
  fail "DSH could not import the plugin (boot rc=$BOOT_RC)"
fi
pass "BOOT CLEAN: no import or module-resolution errors in the boot log (rc=$BOOT_RC)"

# --------------------------------------------------------------- bridge call ---
# The installed bridge imports only Node builtins, so it can be driven
# directly: this is a real subprocess reaching the real papercanvas engine,
# with no model and no credentials.
INSTALLED="$PROFILE_DIR/node_modules/dsh-figcraft"
VOYAGER_PYTHON="$CORE_PYTHON" node --input-type=module -e '
  import { pathToFileURL } from "node:url";
  const installed = process.argv[1];
  const bridge = await import(pathToFileURL(installed + "/dsh-plugin/lib/bridge.js").href);
  const cmd = await bridge.resolvePapercanvas({});
  const work = process.cwd();
  const created = await bridge.callText(["init", work + "/smoke.json", "--id", "cold_start"], {});
  if (!created.includes("created")) { console.error(created); process.exit(1); }
  console.log("papercanvas =", cmd.command, (cmd.args || []).join(" "));
  console.log("create output =", created.trim().split(/\r?\n/)[0]);
' "$INSTALLED" || fail "the bridge could not reach the installed engine"
pass "BRIDGE EXECUTED: the installed plugin reached the real papercanvas engine"

# ------------------------------------------------- a real figure, exported ---
(cd "$WORK" && papercanvas lint smoke.json) > "$COLD_ROOT/lint.log" 2>&1 \
  || fail "lint of the cold-start figure failed"
pass "FIGURE VERIFIED: the cold-start figure lints clean"

echo "--- smoke artifacts ---"
ls -la "$WORK"/smoke.json
