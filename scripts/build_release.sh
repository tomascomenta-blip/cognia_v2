#!/usr/bin/env bash
# scripts/build_release.sh
# ========================
# Build a Cognia Desktop release package for Linux (AppImage) or macOS (DMG).
#
# Usage:
#   bash scripts/build_release.sh [--version X.Y.Z] [--skip-sign] [--target linux|mac]
#
# Environment:
#   CSC_LINK           Path to signing certificate (.p12 for macOS)
#   CSC_KEY_PASSWORD   Certificate password
#   APPLE_ID           For macOS notarization
#   APPLE_APP_SPECIFIC_PASSWORD

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESK="$ROOT/cognia_desktop"

VERSION=""
SKIP_SIGN=0
TARGET=""

ok()   { echo "[OK] $*"; }
fail() { echo "[FAIL] $*"; exit 1; }
step() { echo "[BUILD] $*"; }

# ── Parse arguments ────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)  VERSION="$2"; shift 2 ;;
    --skip-sign) SKIP_SIGN=1; shift ;;
    --target)   TARGET="$2"; shift 2 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

# ── Detect target platform ─────────────────────────────────────────────

if [[ -z "$TARGET" ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    TARGET="mac"
  else
    TARGET="linux"
  fi
fi

# ── Validate prerequisites ─────────────────────────────────────────────

step "Checking Node.js..."
command -v node >/dev/null 2>&1 || fail "Node.js not found. Install from https://nodejs.org"
ok "Node.js $(node --version)"

step "Checking Python..."
command -v python3 >/dev/null 2>&1 || fail "Python3 not found."
ok "Python3"

# ── Install Node dependencies ──────────────────────────────────────────

step "Installing Node dependencies..."
cd "$DESK"
npm install --no-audit --no-fund --prefer-offline
ok "npm install"

# ── Set version if provided ────────────────────────────────────────────

if [[ -n "$VERSION" ]]; then
  step "Setting version to $VERSION..."
  npm version "$VERSION" --no-git-tag-version >/dev/null
  ok "Version set to $VERSION"
fi

# ── Configure signing ──────────────────────────────────────────────────

if [[ "$SKIP_SIGN" -eq 1 ]]; then
  unset CSC_LINK CSC_KEY_PASSWORD
  step "Code signing skipped (--skip-sign)."
elif [[ -n "${CSC_LINK:-}" ]]; then
  ok "Code signing enabled via CSC_LINK."
else
  step "CSC_LINK not set. Building unsigned package."
fi

# ── Run electron-builder ───────────────────────────────────────────────

step "Running electron-builder ($TARGET)..."
npx electron-builder \
  "--$TARGET" \
  --config electron-builder.config.js \
  --publish never
ok "Build complete."

# ── Report output ──────────────────────────────────────────────────────

DIST="$DESK/dist"
echo ""
echo "[DONE] Package written to: $DIST"
ls -lh "$DIST"/*.{AppImage,dmg} 2>/dev/null || true
