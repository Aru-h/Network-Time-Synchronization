#!/usr/bin/env bash
# One-command evaluation run. Works as:   sudo ./evaluation/ubuntu_runner/run_evaluation.sh
# (also finds ryu-manager / a Python with Mininet inside ~/topic23-venv or pyenv even though sudo
#  resets PATH). Override with EVAL_RYU_MANAGER=... and EVAL_PYTHON=...
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # repo root
cd "$ROOT"

echo "============================================================"
echo " TOPIC 23 - EVALUATION: AUTOMATED MININET/SDN EXECUTION"
echo "============================================================"

if [ "$(id -u)" -ne 0 ]; then exec sudo -E env "PATH=$PATH" "$0" "$@"; fi

# --- home dirs to search for a venv (the invoking user, then root)
HOMES=()
if [ -n "${SUDO_USER:-}" ]; then HOMES+=("$(getent passwd "$SUDO_USER" | cut -d: -f6)"); fi
HOMES+=("$HOME")

# --- ryu-manager
RYU="${EVAL_RYU_MANAGER:-$(command -v ryu-manager || true)}"
if [ -z "$RYU" ]; then
  for base in "${HOMES[@]}"; do
    for c in "$base"/topic23-venv/bin/ryu-manager "$base"/.pyenv/versions/*/bin/ryu-manager; do
      if [ -x "$c" ]; then RYU="$c"; break 2; fi
    done
  done
fi
[ -n "$RYU" ] || { echo "ERROR: ryu-manager not found. Install Ryu or set EVAL_RYU_MANAGER=/path/to/ryu-manager"; exit 1; }

# --- a python that can import mininet (the runner only needs the stdlib besides mininet)
PYBIN=""
for c in "${EVAL_PYTHON:-}" "$(dirname "$RYU")/python3" "$(command -v python3 || true)" /usr/bin/python3; do
  if [ -n "$c" ] && [ -x "$c" ] && "$c" -I -c 'from mininet.net import Mininet' 2>/dev/null; then PYBIN="$c"; break; fi
done
if [ -z "$PYBIN" ]; then
  echo "ERROR: no Python with the Mininet module found."
  echo "Install on Ubuntu: sudo apt update && sudo apt install -y mininet openvswitch-switch"
  echo "or point EVAL_PYTHON at the interpreter that has Mininet."
  exit 2
fi

for t in ovs-vsctl ovs-ofctl tc ip ethtool; do
  command -v "$t" >/dev/null || { echo "ERROR: missing command: $t (sudo apt install -y openvswitch-switch iproute2 ethtool)"; exit 1; }
done
command -v iperf >/dev/null || echo "WARNING: iperf not installed (sudo apt install -y iperf). Falling back to the Python load generator; it may not reach the target rate and the congestion check will say so."

echo "ryu-manager : $RYU"
echo "python      : $PYBIN ($("$PYBIN" --version 2>&1))"
export EVAL_RYU_MANAGER="$RYU"
if [ "${EVAL_CHECK_ONLY:-0}" = "1" ]; then
  # Read-only probe by the runner itself (OVS daemon, netem, datapath). It exits before touching results/,
  # and we skip `mn -c` here because that cleans up /tmp state.
  exec "$PYBIN" evaluation/ubuntu_runner/run_mininet_tests.py
fi
mn -c >/dev/null 2>&1 || true
exec "$PYBIN" evaluation/ubuntu_runner/run_mininet_tests.py
