#!/usr/bin/env bash
# Espera a que la GPU este libre (utilizacion < 15 % en 3 lecturas seguidas, 30 s
# entre ellas) y corre los brazos CON modelo del banco: baseline y despues sobre
# 100k y 1M. Escrito porque con TFT/League abiertos el prefill cae de 2.600 a
# 50 tok/s (VRAM desbordada a memoria compartida) y medir asi es mentir.
cd "$(dirname "$0")/../.."
PY=venv312/Scripts/python.exe
SAL=scratchpad/ml/resultados.jsonl
LOG=scratchpad/ml/vigilante_gpu.log
libres=0
echo "== vigilante arranca $(date)" >> "$LOG"
while [ "$libres" -lt 3 ]; do
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  juegos=$(tasklist 2>/dev/null | grep -ciE "TFTClient|LeagueClient|League of Legends|RobloxPlayer|Lunar Client")
  # Relajado (2026-09-04 18:30): con el juego en el lobby (util 0 %, VRAM tomada) el
  # prefill es 648 tok/s (4x mas lento que libre, medible). Solo se exige util baja;
  # el numero de juegos abiertos queda en el log para la salvedad del informe.
  if [ -n "$util" ] && [ "$util" -lt 15 ]; then libres=$((libres+1)); else libres=0; fi
  echo "$(date +%H:%M:%S) util=$util juegos=$juegos libres=$libres" >> "$LOG"
  [ "$libres" -lt 3 ] && sleep 30
done
echo "== GPU libre, midiendo $(date)" >> "$LOG"
for n in 100000 1000000; do
  for m in baseline despues; do
    echo "== $m $n $(date +%H:%M:%S)" | tee -a "$LOG"
    PYTHONUTF8=1 $PY scripts/memoria_larga/banco.py --dataset scratchpad/ml/$n --modo $m --salida "$SAL" 2>&1 | grep -vE "Warning|^\s*$" | cut -c1-300 | tee -a "$LOG"
  done
done
echo "== gate e2e $(date)" | tee -a "$LOG"
PYTHONUTF8=1 COGNIA_LLM_URL=http://127.0.0.1:8080 $PY scripts/e2e_happy_path.py 2>&1 | tail -3 | tee -a "$LOG"
echo "== prueba de crash real $(date)" | tee -a "$LOG"
bash scripts/memoria_larga/prueba_crash_real.sh 2>&1 | tee -a "$LOG" | tail -25
echo "== fin $(date)" | tee -a "$LOG"
