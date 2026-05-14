#!/usr/bin/env bash
# install.sh -- Cognia one-command installer for Linux / macOS
set -e

GRN='\033[0;32m'
YLW='\033[1;33m'
RED='\033[0;31m'
CYN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GRN}[OK]   $1${NC}"; }
warn() { echo -e "${YLW}[WARN] $1${NC}"; }
fail() { echo -e "${RED}[FAIL] $1${NC}"; exit 1; }
skip() { echo -e "${CYN}[SKIP] $1${NC}"; }
info() { echo "       $1"; }

echo "Cognia -- installer"
echo "-------------------"

# Python 3.11+
if ! command -v python3 &>/dev/null; then
    fail "python3 not found. Install Python 3.11+ from https://python.org"
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)"; then
    ok "Python $PY_VER"
else
    fail "Python $PY_VER found -- 3.11+ required."
fi

# Python dependencies
info "Installing Python dependencies..."
python3 -m pip install -r requirements.txt --quiet
ok "Python dependencies"

# Ollama
if command -v ollama &>/dev/null; then
    ok "Ollama"
else
    warn "Ollama not found. Download from https://ollama.ai"
    info "Cognia requires Ollama to generate responses."
fi

# Node.js + Electron (optional)
if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    ok "Node.js $NODE_VER"
    if [ -f "cognia_desktop/package.json" ]; then
        info "Installing Electron dependencies..."
        (cd cognia_desktop && npm install --quiet)
        ok "Electron dependencies"
    fi
else
    warn "Node.js not found. Desktop app will not be available."
    info "Download from https://nodejs.org"
fi

# .env from .env.example
if [ ! -f ".env" ]; then
    cp .env.example .env
    ok ".env created from .env.example"
    warn "Review .env and set COORDINATOR_KEY before production use."
else
    skip ".env already exists"
fi

echo ""
echo -e "${GRN}Installation complete.${NC}"
echo "  Start CLI:     python3 -m cognia.cli"
echo "  Run checks:    python3 scripts/cognia_doctor.py"
echo "  Start desktop: cd cognia_desktop && npm start"
