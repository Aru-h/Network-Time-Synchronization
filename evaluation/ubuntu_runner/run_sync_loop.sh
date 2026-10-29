#!/usr/bin/env bash
# Sync-loop evaluation on Mininet, with its own PASS / FAIL / SKIP table and exit code.
#   sudo ./evaluation/ubuntu_runner/run_sync_loop.sh [--out DIR] [--sandbox-only]
# Runs the sandbox tests for the sync loop, probes the environment, runs legs S1..S5 and S6 (see run_sync_loop.py) and
# prints the table (exit 1 if any check FAILs; SKIP means no data and is never a PASS). Results go to --out
# (default evaluation/results/sync_loop), never under actual_sdn_results. EVAL_RYU_MANAGER / EVAL_PYTHON override tools.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ORIG_ARGS=("$@")
SANDBOX_ONLY=0; OUT="$ROOT/evaluation/results/sync_loop"
while [ $# -gt 0 ]; do
  case "$1" in
    --sandbox-only) SANDBOX_ONLY=1 ;;
    --out) OUT="$(realpath -m "${2:?--out needs a directory}")"; shift ;;
    *) echo "usage: sudo $0 [--out DIR] [--sandbox-only]"; exit 2 ;;
  esac
  shift
done
case "$OUT" in *actual_sdn_results*) echo "refusing to write under actual_sdn_results"; exit 2 ;; esac
if [ "$SANDBOX_ONLY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then exec sudo -E env "PATH=$PATH" "$0" "${ORIG_ARGS[@]}"; fi
export PYTHONDONTWRITEBYTECODE=1

WORK="$(mktemp -d)"; STEPS="$WORK/steps.tsv"; : > "$STEPS"; trap 'rm -rf "$WORK"' EXIT
step() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$STEPS"; }

# --- ryu-manager and a python with Mininet (same search as run_evaluation.sh)
HOMES=(); [ -n "${SUDO_USER:-}" ] && HOMES+=("$(getent passwd "$SUDO_USER" | cut -d: -f6)"); HOMES+=("$HOME")
RYU="${EVAL_RYU_MANAGER:-$(command -v ryu-manager || true)}"
if [ -z "$RYU" ]; then
  for base in "${HOMES[@]}"; do for c in "$base"/topic23-venv/bin/ryu-manager "$base"/.pyenv/versions/*/bin/ryu-manager; do
    [ -x "$c" ] && RYU="$c" && break 2; done; done
fi
PYBIN=""
for c in "${EVAL_PYTHON:-}" "$([ -n "$RYU" ] && dirname "$RYU")/python3" "$(command -v python3 || true)" /usr/bin/python3; do
  if [ -n "$c" ] && [ -x "$c" ] && "$c" -I -c 'from mininet.net import Mininet' 2>/dev/null; then PYBIN="$c"; break; fi
done

echo "== 1. sandbox tests =="
for t in tests/test_agefilter.py tests/test_sync_loop.py tests/test_sync_loop_check.py; do
  if out=$(python3 -W ignore "$t" 2>&1); then step "sandbox: $(basename "$t" .py)" PASS "$(echo "$out" | grep -E '^Ran' | tr '\n' ' ')"
  else echo "$out" | tail -15; step "sandbox: $(basename "$t" .py)" FAIL "see output above"; fi
done

if [ "$SANDBOX_ONLY" -eq 0 ]; then
  echo "== 2. environment probe =="
  if [ -z "$RYU" ] || [ -z "$PYBIN" ]; then step "environment probe" FAIL "ryu-manager or a Python with Mininet not found"
  elif out=$(EVAL_RYU_MANAGER="$RYU" EVAL_CHECK_ONLY=1 "$PYBIN" evaluation/ubuntu_runner/run_sync_loop.py 2>&1); then step "environment probe" PASS "ryu, ovs, tc found"
  else echo "$out" | tail -6; step "environment probe" FAIL "$(echo "$out" | grep ERROR | head -1)"; fi

  echo "== 3. Mininet run (about 10 minutes) =="
  if grep -q "environment probe.*FAIL" "$STEPS"; then step "mininet run" FAIL "skipped: environment probe failed"
  else
    mn -c >/dev/null 2>&1 || true
    echo "results -> $OUT"
    EVAL_RYU_MANAGER="$RYU" "$PYBIN" evaluation/ubuntu_runner/run_sync_loop.py --out "$OUT"; rc=$?
    [ $rc -eq 0 ] && step "mininet run (exit status)" PASS "runner exit 0" || step "mininet run (exit status)" FAIL "runner exit $rc"
    mn -c >/dev/null 2>&1 || true
  fi
fi

mkdir -p "$OUT"
python3 -I evaluation/code/sync_loop_check.py "$OUT" --steps "$STEPS"
rc=$?
[ -n "${SUDO_UID:-}" ] && chown -R "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$OUT" 2>/dev/null
exit $rc
