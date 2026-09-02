#!/usr/bin/env bash
# ARK otra vez, 45 min, con el runner sin --pasos (el reloj manda) y la sonda del tick.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
echo "[ark2] $(date +%H:%M) espero a que la cola actual termine"
while ! grep -q "FIN" banco_largo/ark_y_kanban_cadena.log 2>/dev/null; do sleep 30; done
echo "[ark2] $(date +%H:%M) ARK, 45 min, reloj manda"
rm -rf banco_largo/corridas/ark_45min_v2
BANCO_PRESUPUESTO=2700 $PY -m banco_largo.runner --ronda ark_45min_v2 --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas ark-supervivencia >> banco_largo/ark2.log 2>&1
echo "[ark2] $(date +%H:%M) FIN"
