#!/usr/bin/env bash
# One command for everything:  sudo ./run_d2.sh [--sandbox-only] [--out DIR]
#   1. sandbox tests (controller policy, flow/tc assertions, kernel timestamps, clock filter)
#   2. environment probe (read-only)
#   3. the Mininet/SDN run: baseline, second client, delay, load, QoS off vs on, recovery
#   4. a PASS/FAIL/SKIP table; the exit status is 0 only if nothing failed
# --out DIR writes the run's results to DIR instead of evaluation/results/actual_sdn_results
# (which a full run replaces). Override tools with EVAL_RYU_MANAGER / EVAL_PYTHON.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ORIG_ARGS=("$@")          # the re-exec under sudo below needs the original arguments
SANDBOX_ONLY=0; OUTDIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sandbox-only) SANDBOX_ONLY=1 ;;
    --out) OUTDIR="${2:?--out needs a directory}"; shift ;;
    *) echo "usage: sudo ./run_d2.sh [--sandbox-only] [--out DIR]"; exit 2 ;;
  esac
  shift
done

if [ "$SANDBOX_ONLY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then exec sudo -E env "PATH=$PATH" "$0" "${ORIG_ARGS[@]}"; fi
export PYTHONDONTWRITEBYTECODE=1

WORK="$(mktemp -d)"; STEPS="$WORK/steps.tsv"; : > "$STEPS"
trap 'rm -rf "$WORK"' EXIT
step() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$STEPS"; }

# --- find ryu-manager and its python (same search as evaluation/ubuntu_runner/run_evaluation.sh)
HOMES=(); [ -n "${SUDO_USER:-}" ] && HOMES+=("$(getent passwd "$SUDO_USER" | cut -d: -f6)"); HOMES+=("$HOME")
RYU="${EVAL_RYU_MANAGER:-$(command -v ryu-manager || true)}"
if [ -z "$RYU" ]; then
  for base in "${HOMES[@]}"; do [ -x "$base/topic23-venv/bin/ryu-manager" ] && RYU="$base/topic23-venv/bin/ryu-manager" && break; done
fi
RYU_PY="python3"; [ -n "$RYU" ] && [ -x "$(dirname "$RYU")/python3" ] && RYU_PY="$(dirname "$RYU")/python3"

echo "== 1. sandbox tests =="
for t in tests/test_*.py; do
  name="sandbox: $(basename "$t" .py)"
  py=python3; [ "$t" = tests/test_controller_policy.py ] && py="$RYU_PY"
  if out=$("$py" -W ignore "$t" 2>&1); then step "$name" PASS "$(echo "$out" | grep -E '^(Ran|OK)' | tr '\n' ' ')"
  else echo "$out" | tail -15; step "$name" FAIL "see output above"; fi
done

if [ "$SANDBOX_ONLY" -eq 0 ]; then
  echo "== 2. environment probe =="
  if out=$(EVAL_CHECK_ONLY=1 ./evaluation/ubuntu_runner/run_evaluation.sh 2>&1); then step "environment probe" PASS "ryu, ovs, tc, netem, iperf found"
  else echo "$out" | tail -8; step "environment probe" FAIL "$(echo "$out" | grep ERROR | head -1)"; fi

  echo "== 3. Mininet / SDN run (several minutes) =="
  OUT="${OUTDIR:-$ROOT/evaluation/results/actual_sdn_results}"
  echo "results -> $OUT"
  if grep -q "environment probe.*FAIL" "$STEPS"; then
    step "mininet run" FAIL "skipped: environment probe failed"; SUMMARY=""
  else
    EVAL_OUT_DIR="$OUT" ./evaluation/ubuntu_runner/run_evaluation.sh
    rc=$?
    [ $rc -eq 0 ] && step "mininet run (exit status)" PASS "runner exit 0" || step "mininet run (exit status)" FAIL "runner exit $rc"
    SUMMARY="$OUT/SUMMARY.txt"
  fi
  mn -c >/dev/null 2>&1 || true
  echo "== 4. error reduction (mean vs min-RTT filtered) =="
  [ -n "${SUMMARY:-}" ] && python3 -I evaluation/code/error_reduction.py "$OUT" --markdown "$OUT/error_reduction.md"
fi

python3 -I evaluation/code/pass_table.py "$STEPS" ${SUMMARY:+"$SUMMARY"}
exit $?
