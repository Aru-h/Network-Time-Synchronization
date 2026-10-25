#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # repo root
cd "$ROOT"

echo "============================================================"
echo " TOPIC 23 - TRACK C AUTOMATED MININET/SDN EXECUTION"
echo "============================================================"

for cmd in python3 sudo; do command -v "$cmd" >/dev/null || { echo "Missing command: $cmd"; exit 1; }; done
python3 - <<'PY'
mods=['mininet']
for m in mods:
    try: __import__(m)
    except Exception:
        print('ERROR: Mininet Python module is not installed.')
        print('Install on Ubuntu with: sudo apt update && sudo apt install -y mininet openvswitch-switch')
        raise SystemExit(2)
PY
command -v ryu-manager >/dev/null || { echo "ERROR: ryu-manager not found. Install Ryu first."; exit 1; }

sudo env "PATH=$PATH" python3 track_c/ubuntu_runner/track_c_mininet_automated.py
