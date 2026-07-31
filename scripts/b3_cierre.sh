#!/usr/bin/env bash
# b3_cierre.sh — todo lo que va DESPUÉS de la generación de B-LCB.
#
# 1. Re-juicio UNIFORME (enmienda 2): las primeras 98 muestras se juzgaron sin
#    el cap, así que se re-juzga TODO con el criterio actual sobre el código ya
#    guardado. Sin esto la corrida mezcla dos jueces y el apareado no vale.
# 2. Análisis del veredicto sobre el fichero uniforme.
# 3. RÉPLICA con otro sorteo del split: si el neto solo existe con un sorteo
#    concreto no es un mecanismo, es una tirada.
# 4. Análisis de la réplica y tabla resumen.
#
# Cero GPU: la generación no se repite, solo el juicio.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY="./venv312/Scripts/python.exe"
export PYTHONUTF8=1

echo "=== 1/5  re-juicio UNIFORME ==="
$PY scripts/b3_rejuzgar.py lcb.json --salida b3_codigo/lcb_uniforme.json 2>&1 | tail -6

echo ""
echo "=== 2/5  VEREDICTO sobre el fichero uniforme ==="
$PY scripts/b3_analisis.py lcb_uniforme.json --salida b3_codigo/analisis_lcb.json 2>&1 | tail -45

echo ""
echo "=== 3/5  REPLICA con otro split (semilla 21730) ==="
$PY scripts/b3_rejuzgar.py lcb.json --semilla-split 21730 \
    --salida b3_codigo/lcb_split2.json 2>&1 | tail -5

echo ""
echo "=== 4/5  analisis de la REPLICA ==="
$PY scripts/b3_analisis.py lcb_split2.json --salida b3_codigo/analisis_lcb2.json 2>&1 | tail -30

echo ""
echo "=== 5/5  TABLA RESUMEN ==="
$PY scripts/b3_resumen.py analisis_mbpp.json analisis_lcb.json analisis_lcb2.json 2>&1

echo ""
echo "=== CIERRE COMPLETO $(date +%H:%M) ==="
