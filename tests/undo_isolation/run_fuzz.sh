#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Run the per-tab undo invariant test (undo_fuzz.py) over many seeds, in parallel,
# one headless process per seed (a crash takes down one seed, never the run).
#
#   tests/undo_isolation/run_fuzz.sh <Mixar.app> [first_seed=1] [count=50] [jobs=6] [steps=200]
#
# Env passes through: MIXAR_UNDO_FUZZ_TABS, MIXAR_UNDO_FUZZ_UNDO_STEPS. Results land in
# ${MIXAR_UNDO_FUZZ_ROOT:-/tmp/mixar-undo-fuzz}/seed-<n>/ (log.txt, trace.json,
# violation.txt). Exit 0 only when every seed is clean.
set -u
APP="${1:?usage: run_fuzz.sh <Mixar.app> [first_seed] [count] [jobs] [steps]}"
FIRST="${2:-1}"; COUNT="${3:-50}"; JOBS="${4:-6}"; STEPS="${5:-200}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${MIXAR_UNDO_FUZZ_ROOT:-/tmp/mixar-undo-fuzz}"
BIN="$APP/Contents/MacOS/Mixar"
[ -x "$BIN" ] || BIN="$APP"
mkdir -p "$ROOT"

run_seed() {
  local seed="$1" out="$ROOT/seed-$1"
  mkdir -p "$out"
  MIXAR_UNDO_FUZZ_SEED="$seed" MIXAR_UNDO_FUZZ_STEPS="$STEPS" MIXAR_UNDO_FUZZ_OUT="$out" \
    "$BIN" --background --factory-startup --python "$HERE/undo_fuzz.py" > "$out/log.txt" 2>&1
  local rc=$?
  case $rc in
    0) echo "$seed clean" ;;
    1) echo "$seed VIOLATION $(head -c 300 "$out/violation.txt" 2>/dev/null)" ;;
    2) echo "$seed HARNESS-ERROR" ;;
    *) echo "$seed CRASH rc=$rc" ;;
  esac
}
export -f run_seed
export ROOT STEPS BIN HERE

seq "$FIRST" $((FIRST + COUNT - 1)) | xargs -P "$JOBS" -I{} bash -c 'run_seed {}' | tee "$ROOT/summary.txt"
clean=$(grep -c " clean$" "$ROOT/summary.txt")
echo "[fuzz] $clean / $COUNT seeds clean — $ROOT/summary.txt"
[ "$clean" -eq "$COUNT" ]
