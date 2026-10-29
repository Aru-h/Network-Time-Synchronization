#!/bin/bash
set -e
cd "$(dirname "$0")/.."
ryu-manager controller/time_sync_controller.py --ofp-tcp-listen-port 6653
