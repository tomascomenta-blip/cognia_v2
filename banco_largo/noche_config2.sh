#!/usr/bin/env bash
# Brazo 7: el catalogo CHICO (solo la puerta `probar` anunciada; 19 tools en vez de 93).
# Espera a que termine noche_config.sh para no compartir la GPU.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
TAREAS=web-dashboard,py-cli-tareas,node-cli-generador
export BANCO_PRESUPUESTO=600
while ! grep -q "FIN DE LOS BRAZOS" banco_largo/noche_config_cadena.log 2>/dev/null; do sleep 30; done
echo "[noche2] $(date +%H:%M) brazo catalogo_chico"
env COGNIA_NOCHE=1 $PY -m banco_largo.runner --ronda cfg_catalogo_chico --cwd-cli /c/Users/usuario/Desktop/_cognia_noche_chico --tareas $TAREAS --forzar >> banco_largo/noche_config.log 2>&1
echo "[noche2] $(date +%H:%M) FIN brazo 7"
