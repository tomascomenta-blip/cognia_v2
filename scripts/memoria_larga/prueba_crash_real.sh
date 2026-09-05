#!/usr/bin/env bash
# Prueba de CRASH REAL con el CLI (no con un modelo falso): arranca `cognia hacer`
# con una tarea de varios pasos en un directorio limpio, espera a que exista el
# primer checkpoint de tarea, mata el arbol de procesos (taskkill /T), comprueba que
# el checkpoint quedo 'en_curso' y lo retoma con `cognia hacer --retomar --json`.
# Sale 0 si la retomada termina ok y el checkpoint queda 'completa'.
set -u
cd "$(dirname "$0")/../.."
PY="$(pwd)/venv312/Scripts/python.exe"
# El proyecto de prueba esta FUERA del repo: sin esto `python -m cognia` importa el
# paquete INSTALADO en site-packages (la trampa documentada en la memoria del repo).
export PYTHONPATH="$(pwd)"
DIR="$(pwd)/scratchpad/ml/crash_real"
rm -rf "$DIR"; mkdir -p "$DIR/proyecto"
# Rutas en formato WINDOWS para todo lo que lee Python: la version anterior pasaba
# /c/Users/... y ni el vigilante ni el checkpoint se encontraban (2026-09-04).
DIRW=$(cygpath -w "$DIR")
export COGNIA_MEMORIA_DIR="$DIRW\memoria" COGNIA_HOME="$DIRW\home" COGNIA_OFFLOAD_DIR="$DIRW\offload"
export COGNIA_LLM_URL=http://127.0.0.1:8080 PYTHONUTF8=1 COGNIA_MEMORIA_CHECKPOINT_CADA=2
TAREA="Crea un paquete python 'tienda' con cinco modulos: productos.py (clase Producto con nombre, precio y stock), carrito.py (clase Carrito con agregar, quitar, total y descuento por cupon), inventario.py (clase Inventario que descuenta stock al vender y lanza error si no hay), facturas.py (funcion generar_factura que devuelve un texto con lineas y total) y clientes.py (clase Cliente con historial de compras). Escribe tests en test_tienda.py que cubran los cinco modulos con al menos 12 tests. Corre los tests hasta que pasen y al final muestra el arbol de ficheros."
cd "$DIR/proyecto"
echo "== arranco cognia hacer $(date +%H:%M:%S)"
"$PY" -m cognia hacer --cwd "$DIRW\proyecto" "$TAREA" < /dev/null > "$DIR/primera.out" 2> "$DIR/primera.err" &
PID=$!
# Esperar al PRIMER checkpoint (paso 2) y matar enseguida: asi el corte cae a mitad
# de la tarea (el agente la termina en ~3 min, 12 pasos, medido). `ls` con la ruta
# MSYS funciona; lo que fallaba era pasarsela a Python.
for i in $(seq 1 72); do
  if ls "$DIR"/memoria/tareas/*/checkpoint.json >/dev/null 2>&1; then echo "checkpoint visto a los $((i*5)) s"; break; fi
  sleep 5
done
sleep 3
echo "== mato el arbol (pid $PID) $(date +%H:%M:%S)"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'cognia hacer' } | ForEach-Object { taskkill /T /F /PID \$_.ProcessId 2>&1 | Out-Null }"
sleep 2
echo "== checkpoint tras el crash:"; "$PY" -c "
import json,glob,os
for f in glob.glob(os.path.join(os.environ['COGNIA_MEMORIA_DIR'],'tareas','*','checkpoint.json')):
    c=json.load(open(f,encoding='utf-8')); print({k:c[k] for k in ('n','paso','estado','next_action','ficheros')})"
echo "== ficheros en el proyecto tras el crash:"; ls "$DIR/proyecto"
echo "== sesion lista:"; "$PY" -m cognia sesion lista 2>&1 | tail -3
echo "== retomo $(date +%H:%M:%S)"
"$PY" -m cognia hacer --retomar --json --cwd "$DIRW\proyecto" < /dev/null > "$DIR/retomada.out" 2> "$DIR/retomada.err"
echo "rc=$?"
"$PY" -c "
import json,glob,os
s=open(r'$DIRW\retomada.out',encoding='utf-8').read(); j,_=json.JSONDecoder().raw_decode(s[s.index('{'):])
print('retomada ok=',j.get('ok'),'segundos=',j.get('segundos'))
print('respuesta:', (j.get('respuesta') or '')[:300].replace('\n',' '))
for f in glob.glob(os.path.join(os.environ['COGNIA_MEMORIA_DIR'],'tareas','*','checkpoint.json')):
    c=json.load(open(f,encoding='utf-8')); print('checkpoint', c['task_id'], c['estado'], 'paso', c['paso'])
"
echo "== ficheros finales:"; ls "$DIR/proyecto"; (cd "$DIR/proyecto" && "$PY" -m pytest -q --no-header -p no:cacheprovider 2>&1 | tail -1)
