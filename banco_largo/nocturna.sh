#!/usr/bin/env bash
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
TAREAS=web-dashboard,node-cli-generador,py-cli-tareas,juego-tower-defense,py-servidor-api,herramienta-diff,web-kanban,ark-supervivencia,py-compilador,multi-componente
export BANCO_PRESUPUESTO=480
LIMITE=$(( $(date +%s) + 7200 ))

echo "[nocturna] $(date +%H:%M) espero a que la ronda 1 llegue a 10 tareas"
while true; do
  N=$(ls banco_largo/corridas/r1_baseline/ 2>/dev/null | grep -c '^[a-z0-9-]*\.json$')
  if [ "$N" -ge 11 ]; then break; fi
  if [ "$(date +%s)" -gt "$LIMITE" ]; then echo "[nocturna] corte por reloj con $N"; break; fi
  sleep 60
done

echo "[nocturna] $(date +%H:%M) ronda 1 cerrada; lanzo la ronda 2 con el arnes mejorado"
$PY -m banco_largo.runner --ronda r2_mejorado --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --deadline 05:30 --tareas $TAREAS >> banco_largo/r2.log 2>&1

echo "[nocturna] $(date +%H:%M) informe comparativo"
$PY -m banco_largo.informe --antes r1_baseline --despues r2_mejorado --salida banco_largo/INFORME_COMPARATIVO.md >> banco_largo/informe.log 2>&1
echo "[nocturna] $(date +%H:%M) FIN"
