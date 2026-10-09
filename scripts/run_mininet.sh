#!/bin/bash
set -e
cd "$(dirname "$0")/.."
sudo python3 mininet/time_sync_topology.py
