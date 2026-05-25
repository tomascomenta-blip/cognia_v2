#!/usr/bin/env bash
# Cognia installer — Linux / macOS
#
# Usage (from web, no repo needed):
#   curl -fsSL https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/main/install.sh | bash
#
# Usage (from inside the cloned repo):
#   bash install.sh
#   bash install.sh --local           # standalone mode
#   bash install.sh --coordinator https://my-coordinator.example.com

set -e

COORDINATOR="https://cognia-coordinator-production.up.railway.app"
LOCAL_MODE=0

for arg in "$@"; do
    case "$arg" in
        --local) LOCAL_MODE=1 ;;
        --coordinator=*) COORDINATOR="${arg#*=}" ;;
        --coordinator)   shift; COORDINATOR="$1" ;;
    esac
done

ok()   { printf '  \033[32m[ok]\033[0m  %s\n' "$1"; }
warn() { printf '  \033[33m[--]\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31m[!!]\033[0m  %s\n' "$1"; exit 1; }
step() { printf '\n  \033[1m%s\033[0m\n' "$1"; }

echo ""
echo "  Cognia"
echo "  ------"
echo ""
echo "  Cognia is a P2P AI network. You contribute one model fragment"
echo "  (~300 MB of storage) and get access to the full AI model in return."
echo ""

# ── Detect if running from repo ───────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
IN_REPO=0
[ -f "$SCRIPT_DIR/scripts/cognia_setup.py" ] && IN_REPO=1

DATA_DIR="$HOME/.cognia"
REPO_DIR="$( [ $IN_REPO -eq 1 ] && echo "$SCRIPT_DIR" || echo "$DATA_DIR/repo" )"
VENV_DIR="$DATA_DIR/env"
ENV_FILE="$DATA_DIR/.env"
SHARDS_DIR="$DATA_DIR/shards/qwen-coder-3b-q4"

# ── Python 3.11+ ──────────────────────────────────────────────────────────────
step "Checking Python..."

PY=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
            PY="$cmd"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    fail "Python 3.11+ not found.

  Ubuntu/Debian:  sudo apt install python3.11
  Fedora:         sudo dnf install python3.11
  macOS:          brew install python@3.11
  Download:       https://python.org/downloads"
fi

PY_VER=$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER"

# ── Clone repo if needed ──────────────────────────────────────────────────────

if [ $IN_REPO -eq 0 ]; then
    step "Downloading Cognia..."

    if ! command -v git >/dev/null 2>&1; then
        fail "git is required. Install it with your package manager or from https://git-scm.com"
    fi

    if [ ! -d "$REPO_DIR/.git" ]; then
        mkdir -p "$(dirname "$REPO_DIR")"
        git clone --depth 1 https://github.com/tomascomenta-blip/cognia_v2.git "$REPO_DIR"
    else
        ok "Repository already present at $REPO_DIR"
    fi
fi

ok "Cognia source: $REPO_DIR"

# ── Virtual environment ───────────────────────────────────────────────────────
step "Setting up Python environment..."

if [ ! -f "$VENV_DIR/bin/python" ]; then
    "$PY" -m venv "$VENV_DIR" --prompt cognia
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

VPYTHON="$VENV_DIR/bin/python"

# ── Install dependencies ──────────────────────────────────────────────────────
step "Installing dependencies..."

REQ="$REPO_DIR/requirements.txt"
[ -f "$REQ" ] || fail "requirements.txt not found in $REPO_DIR"

"$VPYTHON" -m pip install -r "$REQ" -q --disable-pip-version-check
ok "Dependencies installed"

# ── Run Cognia setup ──────────────────────────────────────────────────────────
step "Setting up Cognia..."

SETUP="$REPO_DIR/scripts/cognia_setup.py"
[ -f "$SETUP" ] || fail "Setup script not found: $SETUP"

if [ $LOCAL_MODE -eq 1 ]; then
    echo ""
    echo "  Running in standalone mode."
    echo "  Downloading all 4 model fragments (~1.1 GB)."
    echo ""
    "$VPYTHON" "$SETUP" --mode cli --coordinator local \
        --shards-dir "$SHARDS_DIR" --env-path "$ENV_FILE"
else
    echo ""
    echo "  Connecting to the Cognia network at:"
    echo "  $COORDINATOR"
    echo ""
    echo "  The coordinator will assign you one model fragment (~300 MB)."
    echo "  You'll host it in exchange for full AI access."
    echo ""
    "$VPYTHON" "$SETUP" --mode cli --coordinator "$COORDINATOR" \
        --shards-dir "$SHARDS_DIR" --env-path "$ENV_FILE"
fi

if [ $? -ne 0 ]; then
    echo ""
    warn "Setup encountered an issue."
    echo ""
    echo "  If the network is unavailable, try standalone mode:"
    echo "    bash install.sh --local"
    exit 1
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "  ----------------------------------------"
printf '  \033[32mCognia is ready.\033[0m\n'
echo ""
echo "  Start the desktop app:"
echo "    cd $REPO_DIR/cognia_desktop && npm start"
echo ""
echo "  Or use the command line:"
echo "    $VPYTHON -m cognia"
echo ""
