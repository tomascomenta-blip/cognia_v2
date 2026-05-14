#!/usr/bin/env bash
# Cognia installer — Linux / macOS
# Usage: curl -fsSL https://raw.githubusercontent.com/tomascomenta-blip/cognia_v2/main/install.sh | sh
set -e

REPO="https://github.com/tomascomenta-blip/cognia_v2.git"
MIN_PY_MINOR=11

ok()   { printf '\033[32m[OK]\033[0m   %s\n' "$1"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$1"; }
fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$1"; exit 1; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

step "Cognia installer"
echo "Instalando desde $REPO"
echo "---------------------------------------------------"

# ── Python 3.11+ ──────────────────────────────────────
step "Verificando Python..."
PY=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
            PY="$cmd"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    fail "Python 3.$MIN_PY_MINOR+ no encontrado.

  Linux (Ubuntu/Debian):  sudo apt install python3.11
  Linux (Fedora):         sudo dnf install python3.11
  macOS:                  brew install python@3.11
  Descarga:               https://python.org/downloads"
fi

PY_VER=$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER"

# ── pip ───────────────────────────────────────────────
if ! "$PY" -m pip --version &>/dev/null; then
    fail "pip no disponible. Instala con: $PY -m ensurepip"
fi

# ── Instalar cognia ───────────────────────────────────
step "Instalando cognia..."
"$PY" -m pip install --quiet --upgrade "git+$REPO"

if ! command -v cognia &>/dev/null; then
    # pip instaló en un directorio fuera del PATH — intentar con pipx
    if command -v pipx &>/dev/null; then
        warn "cognia no encontrado en PATH. Reintentando con pipx..."
        pipx install "git+$REPO" --force
    else
        warn "cognia no está en tu PATH."
        warn "Agrega la carpeta de scripts de pip a PATH:"
        warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        warn "Luego ejecuta: cognia"
        exit 0
    fi
fi

ok "cognia instalado en $(command -v cognia)"

# ── Ollama (opcional) ─────────────────────────────────
step "Verificando Ollama..."
if command -v ollama &>/dev/null; then
    ok "Ollama disponible"
else
    warn "Ollama no encontrado."
    echo "  Para usar inferencia local: https://ollama.ai"
    echo "  Para unirte al swarm distribuido no es necesario."
fi

# ── Listo ─────────────────────────────────────────────
echo ""
echo "---------------------------------------------------"
printf '\033[32mInstalacion completa.\033[0m\n'
echo ""
echo "  Ejecuta el siguiente comando para configurar Cognia:"
echo ""
printf '    \033[1mcognia\033[0m\n'
echo ""
echo "  (el wizard se ejecuta automaticamente la primera vez)"
echo ""
echo "  Otros comandos:"
echo "    cognia server       -- servidor web"
echo "    cognia node         -- nodo del swarm distribuido"
echo "    cognia coordinator  -- coordinador del swarm"
echo "    cognia status       -- estado del sistema"
