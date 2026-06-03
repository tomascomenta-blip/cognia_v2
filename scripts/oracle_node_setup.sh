#!/usr/bin/env bash
# oracle_node_setup.sh
# Run this on a fresh Oracle Cloud Ubuntu 22.04 ARM VM.
# Sets up a Cognia shard node that connects to the Railway coordinator.
#
# Usage:
#   ssh ubuntu@<VM_IP> "bash <(curl -fsSL https://raw.githubusercontent.com/<YOUR_REPO>/main/scripts/oracle_node_setup.sh)"
# OR copy manually:
#   scp scripts/oracle_node_setup.sh ubuntu@<VM_IP>:~/
#   ssh ubuntu@<VM_IP> "bash oracle_node_setup.sh"

set -euo pipefail

COORDINATOR_URL="https://cognia-coordinator-production.up.railway.app"
REPO_URL="https://github.com/tomascomenta-blip/cognia_v2.git"
HF_DATASET="Acua124298042/cognia-shards"
INSTALL_DIR="$HOME/cognia"
SHARD_DIR="$INSTALL_DIR/model_shards/qwen-coder-3b-q4"

echo "=== Cognia Oracle Node Setup ==="
echo "Coordinator: $COORDINATOR_URL"
echo ""

# ── 1. System deps ────────────────────────────────────────────────────────────
echo "[1/6] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.11 python3.11-venv python3-pip git curl wget gcc g++ make

# ── 2. Clone repo ─────────────────────────────────────────────────────────────
echo "[2/6] Cloning Cognia repo..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  Directory exists, pulling latest..."
    cd "$INSTALL_DIR" && git pull --quiet
else
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ── 3. Python venv + deps ─────────────────────────────────────────────────────
echo "[3/6] Setting up Python venv..."
python3.11 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ── 4. Download shard weights ─────────────────────────────────────────────────
echo "[4/6] Downloading shard weights from HuggingFace..."
mkdir -p "$SHARD_DIR"

# Try huggingface_hub first (installed via requirements), fallback to wget
python3 - <<'PYEOF'
import os, sys
shard_dir = os.environ.get("SHARD_DIR", os.path.expandvars("$HOME/cognia/model_shards/qwen-coder-3b-q4"))
os.makedirs(shard_dir, exist_ok=True)

# Check what we already have
existing = [f for f in os.listdir(shard_dir) if f.endswith('.npz') or f.endswith('.json')]
print(f"  Existing files: {existing}")

try:
    from huggingface_hub import snapshot_download, hf_hub_download
    # Download just the files we need (tokenizer + shard_1 for the Oracle node)
    files_needed = ["tokenizer.json", "tokenizer_config.json", "shard_1.npz"]
    for fname in files_needed:
        local_path = os.path.join(shard_dir, fname)
        if os.path.exists(local_path):
            print(f"  Already exists: {fname}")
            continue
        print(f"  Downloading {fname}...")
        try:
            hf_hub_download(
                repo_id="Acua124298042/cognia-shards",
                filename=fname,
                repo_type="dataset",
                local_dir=shard_dir,
            )
            print(f"  Downloaded: {fname}")
        except Exception as e:
            print(f"  WARN: Could not download {fname}: {e}")
except ImportError:
    print("  huggingface_hub not available, skipping HF download")
    print("  Manual download: huggingface-cli download Acua124298042/cognia-shards --repo-type dataset --local-dir " + shard_dir)
PYEOF

# Unpack shard_1.npz if downloaded
if [ -f "$SHARD_DIR/shard_1.npz" ] && [ ! -d "$SHARD_DIR/shard_1" ]; then
    echo "  Unpacking shard_1.npz..."
    python3 scripts/unpack_shards.py --shard "$SHARD_DIR/shard_1.npz" --out "$SHARD_DIR/shard_1" 2>/dev/null || \
    python3 -c "
import numpy as np, os
data = np.load('$SHARD_DIR/shard_1.npz')
os.makedirs('$SHARD_DIR/shard_1', exist_ok=True)
for k in data.files:
    np.save('$SHARD_DIR/shard_1/' + k.replace('/', '_') + '.npy', data[k])
print('Unpacked', len(data.files), 'arrays')
"
fi

# ── 5. Write .env ─────────────────────────────────────────────────────────────
echo "[5/6] Writing .env configuration..."
cat > "$INSTALL_DIR/.env" <<ENV
COGNIA_COORDINATOR_URL=$COORDINATOR_URL
COORDINATOR_URL=$COORDINATOR_URL
SHARD_WEIGHTS_DIR=$SHARD_DIR
COGNIA_SWARM_MODEL=qwen-coder-3b-q4
COGNIA_NODE_HARDWARE=Oracle-ARM-A1-4core-24GB
COGNIA_STRICT_AUTH=0
ENV

echo "  .env written."

# ── 6. Start node ─────────────────────────────────────────────────────────────
echo "[6/6] Starting Cognia shard node..."
echo ""
echo "=== Node starting — connecting to $COORDINATOR_URL ==="
echo "    Press Ctrl+C to stop."
echo ""

cd "$INSTALL_DIR"
source venv/bin/activate
python node/main.py
