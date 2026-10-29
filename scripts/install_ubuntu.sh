#!/bin/bash
set -e

echo "=== Installing Topic 23 D1/D2 dependencies ==="

sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip python3-venv git \
    iproute2 iputils-ping ethtool

if [ ! -d "$HOME/topic23-venv" ]; then
    python3 -m venv "$HOME/topic23-venv"
fi

source "$HOME/topic23-venv/bin/activate"
python -m pip install --upgrade pip

# --- Ryu on modern Python 3 / Ubuntu 24.04 ------------------------------
# `pip install ryu` alone silently resolves to ancient Ryu 2.2 (Python
# 2-era) on current pip because 4.x wheels don't declare python_requires
# cleanly with recent setuptools. Pin the version and the build tooling
# explicitly, or ryu-manager will fail with Python-2 syntax errors.
python -m pip install "setuptools==57.5.0" wheel
python -m pip install --no-build-isolation "ryu==4.34"

# ryu 4.34 and its entry-point script still import `from oslo.config
# import cfg` / `from oslo.i18n import ...` — the old OpenStack namespace
# package layout. Current oslo.config/oslo.i18n only expose oslo_config /
# oslo_i18n. Patch every occurrence in the installed package + the
# ryu-manager script itself.
RYU_DIR="$(python -c 'import ryu, os; print(os.path.dirname(ryu.__file__))')"
for f in $(grep -rl "from oslo\.config import\|from oslo\.i18n import" "$RYU_DIR" 2>/dev/null); do
    sed -i -E 's/from oslo\.config import/from oslo_config import/g; s/from oslo\.i18n import/from oslo_i18n import/g' "$f"
done
sed -i -E 's/from oslo\.config import/from oslo_config import/g' "$HOME/topic23-venv/bin/ryu-manager" 2>/dev/null || true

# eventlet>=0.33 removed the ALREADY_HANDLED sentinel that ryu/app/wsgi.py
# imports at module load time, which otherwise crashes ryu-manager before
# it even parses arguments. Pin an eventlet version new enough for Python
# 3.11 (0.31/0.32 crash on Python's now-immutable TimeoutError) and patch
# the one missing symbol with an equivalent local sentinel.
python -m pip install "eventlet==0.33.0"
sed -i 's/from eventlet\.wsgi import ALREADY_HANDLED/ALREADY_HANDLED = object()  # eventlet>=0.33 removed this sentinel/' \
    "$RYU_DIR/app/wsgi.py"

# eventlet==0.33's greendns support (imported at ryu-manager startup via
# ryu/lib/hub.py -> eventlet -> eventlet.green.socket -> greendns) is only
# compatible with the dnspython 1.x / early-2.x module layout. A plain
# `pip install eventlet==0.33.0` on a clean machine can resolve a recent
# dnspython (observed: 2.8.0) whose dns.rdtypes.ANY.SMIMEA module imports
# dns.rdtypes.tlsabase before greendns's patched import order has it
# available, crashing ryu-manager with:
#   AttributeError: module 'dns.rdtypes' has no attribute 'tlsabase'
# Pin a dnspython version known to work with eventlet 0.33's greendns.
python -m pip install "dnspython==1.16.0"

# dnspython 1.16.0 itself uses collections.MutableMapping, removed from the
# collections module in Python 3.10+. Patch it rather than upgrading
# dnspython, since eventlet's greendns patcher expects the old 1.x layout.
DNS_DIR="$(python -c 'import dns, os; print(os.path.dirname(dns.__file__))' 2>/dev/null || true)"
if [ -n "$DNS_DIR" ] && [ -f "$DNS_DIR/namedict.py" ]; then
    sed -i 's/class NameDict(collections\.MutableMapping):/class NameDict(collections.abc.MutableMapping):/' "$DNS_DIR/namedict.py"
    grep -q '^import collections.abc' "$DNS_DIR/namedict.py" || \
        sed -i '0,/^import collections$/s//import collections\nimport collections.abc/' "$DNS_DIR/namedict.py"
fi

# Clear any bytecode cache from the pre-patch files.
find "$RYU_DIR" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo
echo "Installation complete."
echo "Activate later with:"
echo "source ~/topic23-venv/bin/activate"
echo
echo "Verify with:"
echo "  ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653"
echo
echo "If ovs-vswitchd can't load its kernel module (some VM/container"
echo "setups), OVS falls back to the slower userspace datapath. If UDP"
echo "sync traffic times out in that case but ping works, disable checksum"
echo "offload on the host veth interfaces as a workaround:"
echo "  h1 ethtool -K h1-eth0 tx off rx off"
