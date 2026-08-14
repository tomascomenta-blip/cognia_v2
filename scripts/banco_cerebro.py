# -*- coding: utf-8 -*-
"""BANCO QUE DISCRIMINA entre cerebros candidatos (2026-08-13).

POR QUE existe: el gate del repo (scripts/e2e_happy_path.py) es un GATE, no una
regla graduada. Qwythos-9B ya saca 5/5 ahi, asi que ese banco solo puede mostrar
que un modelo es PEOR que el actual; no tiene margen para mostrar que otro es
MEJOR. Cambiar de cerebro con un instrumento saturado es elegir a ciegas.

Este banco mide con 12 tareas de agente REALES (mismo camino que /hacer:
cli._run_agent_task sobre el backend que haya) graduadas en tres niveles:

  - 3 faciles   : casi cualquier modelo pasa (escribir, calcular+guardar, json)
  - 4 medias    : varios pasos encadenados (leer->transformar->escribir, editar
                  sin romper, ejecutar y guardar la salida, filtrar por criterio)
  - 5 dificiles : 4+ pasos, corregir un error de SINTAXIS que devuelve la
                  verificacion, elegir entre dos fuentes, integrar dos ficheros,
                  y codigo que tiene que pasar un test que corremos NOSOTROS

REGLA DEL INSTRUMENTO: la postcondicion se comprueba LEYENDO EL DISCO (y, cuando
hace falta, EJECUTANDO lo que quedo escrito). Nunca la respuesta del modelo. Un
modelo que contesta "listo" sin haber tocado nada FALLA. La respuesta se guarda
solo como diagnostico en `detalle`.

Cada tarea es un dict con las claves del encargo:
    id, dificultad, enunciado, preparacion(ws), postcondicion(ws) -> bool
mas `pasos` (presupuesto de pasos propio: una tarea de 4 eslabones no se mide
con el mismo techo que "escribi un fichero").

Uso desde el arnes de barrido (scripts/comparar_modelos.py), preferido — cada
medicion en su PROPIO proceso, sin caches por URL heredados del candidato
anterior:
    --banco "scripts\\banco_cerebro.py"
El arnes lee el ultimo 'N/M' del stdout: la ultima linea de este script es
'RESULTADO BANCO CEREBRO: p/max pts' (puntos, no tareas) justamente por eso.

Uso importado (in-process; el arnes acepta 'py:banco_cerebro:medir'):
    from banco_cerebro import TAREAS, correr_banco, medir
    res = correr_banco(ai, print_fn=print, max_steps=None)
    # res = {total, de, puntos, puntos_max, por_dificultad, detalle, segundos,
    #        interrumpido, pedidas}

Uso suelto, contra el backend que YA este corriendo (lo ADOPTA, no lo arranca):
    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\banco_cerebro.py
    ... --solo d2_sintaxis --dif dificil --pasos 12 --json out.json --minimo 8

Probar el BANCO sin backend (ni una conexion, ni un modelo):
    ... scripts\\banco_cerebro.py --dry-run
Escribe la solucion perfecta de cada tarea y exige APROBADO, deja el workspace
vacio (el modelo que contesta "ya lo hice") y exige REPROBADO, y repite las
trampas medidas que alguna version del banco dejo pasar. Exit 0 solo si todo
sale como debe: si esto falla, cualquier numero que de el banco es ruido.

NOTA DURA: este script no arranca ni para ningun llama-server propio. Si el
backend fue ADOPTADO (ya habia uno vivo en el puerto), no se lo toca al salir;
solo se detiene el proceso que hubiera arrancado ESTA corrida, igual que el
gate — y esa parada va en un `finally`, asi que tambien ocurre si la corrida
revienta o el usuario da Ctrl-C. La cabecera dice cual de los dos casos es.

Exit: 0 normal, 1 si se pidio --minimo y no se alcanzo, 2 error de invocacion,
130 si se interrumpio (el resultado queda marcado 'interrumpido': PARCIAL, no
comparable contra una corrida entera).
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Peso por dificultad: un banco graduado necesita que acertar lo dificil valga
# mas que acertar lo facil, o dos modelos con el mismo total (uno 3+4+1, otro
# 1+3+4) quedarian empatados siendo muy distintos.
PESOS = {"facil": 1, "media": 2, "dificil": 3}

# Presupuesto de pasos por defecto segun dificultad (se puede pisar por tarea
# con la clave 'pasos', y globalmente con max_steps=).
PASOS_POR_DIFICULTAD = {"facil": 6, "media": 10, "dificil": 16}


# --------------------------------------------------------------------------
# Lectura del DISCO (todas las postcondiciones pasan por aca)
# --------------------------------------------------------------------------

def _buscar_fichero(ws: Path, nombre: str):
    """Primer fichero del workspace cuyo nombre coincide (case-insensitive).

    Se busca recursivo porque el agente a veces crea una subcarpeta; lo que se
    mide es si el ARTEFACTO existe, no si eligio la ruta que imaginabamos.
    """
    objetivo = nombre.lower()
    exactos, parecidos = [], []
    for p in ws.rglob("*"):
        if not p.is_file():
            continue
        if p.name == nombre:
            exactos.append(p)
        elif p.name.lower() == objetivo:
            parecidos.append(p)
    hits = exactos or parecidos
    return hits[0] if hits else None


def _leer(ws: Path, nombre: str) -> str:
    p = _buscar_fichero(ws, nombre)
    if p is None:
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _existe(ws: Path, nombre: str) -> bool:
    return _buscar_fichero(ws, nombre) is not None


def _json_de(ws: Path, nombre: str):
    """Parsea el fichero como JSON. Tolera fences ```json que algunos modelos
    dejan pegados; si no parsea, devuelve None (y la postcondicion falla)."""
    txt = (_leer(ws, nombre) or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", txt).strip()
    try:
        return json.loads(txt)
    except Exception:
        return None


_RE_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def _numeros(texto: str):
    """Todos los numeros de un texto, como floats.

    Se prueba tambien una variante con separador de miles quitado (1.591 ->
    1591) porque un modelo puede formatear el resultado y el numero seguiria
    siendo el correcto.
    """
    txt = texto or ""
    variantes = [txt, re.sub(r"(?<=\d)[.,](?=\d{3}(?!\d))", "", txt)]
    out = []
    for v in variantes:
        for m in _RE_NUM.finditer(v):
            try:
                out.append(float(m.group(0).replace(",", ".")))
            except ValueError:
                pass
    return out


def _tiene_numero(texto: str, valor: float, tol: float = 0.01) -> bool:
    return any(abs(n - valor) <= tol for n in _numeros(texto))


def _lineas(texto: str):
    return [ln.strip().strip("'\"") for ln in (texto or "").splitlines() if ln.strip()]


_RE_VINETA = re.compile(r"^[\s\-\*•\d\.\)]+")


def _lineas_limpias(texto: str):
    """Lineas sin vinetas ni numeracion: '1. mariposa' -> 'mariposa'. La forma
    de la lista no es lo que se mide, el CONTENIDO si."""
    out = []
    for ln in _lineas(texto):
        limpia = _RE_VINETA.sub("", ln).strip().strip("'\",")
        if limpia:
            out.append(limpia)
    return out


def _ejecutar_py(ws: Path, script: str, timeout: int = 60):
    """Corre un .py del workspace con ESTE interprete (venv312) y devuelve
    (exit_code, salida). Es parte de la verificacion en disco: para saber si el
    fichero que quedo escrito FUNCIONA hay que ejecutarlo.

    stdin=DEVNULL a proposito: el codigo lo escribio un modelo y un `input()`
    colado heredaria la consola del banco — se comeria las teclas del usuario y
    colgaria la verificacion hasta el timeout. Con DEVNULL da EOFError y la
    tarea falla, que es el veredicto correcto."""
    p = _buscar_fichero(ws, script)
    if p is None:
        return 127, "(no existe el script)"
    try:
        r = subprocess.run([sys.executable, str(p)], cwd=str(p.parent),
                           capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace")
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))
    except subprocess.TimeoutExpired:
        return 124, "(timeout)"
    except Exception as exc:
        return 125, f"(excepcion: {exc})"


def _sonda(ws: Path, ancla: str, nombre: str, cuerpo: str) -> bool:
    """Escribe una SONDA junto al fichero `ancla` y la ejecuta.

    Es la unica forma de saber si lo que quedo en disco se COMPORTA como pide
    el enunciado: compilar y contener las lineas correctas no basta (un modelo
    puede conservar `def resumen():` y vaciarle el cuerpo). La sonda va junto
    al ancla para que el import relativo funcione desde su carpeta.
    """
    p = _buscar_fichero(ws, ancla)
    if p is None:
        return False
    try:
        (p.parent / nombre).write_text(cuerpo, encoding="utf-8")
    except Exception:
        return False
    code, out = _ejecutar_py(ws, nombre)
    return code == 0 and "SONDA OK" in out


def _compila(ws: Path, script: str) -> bool:
    p = _buscar_fichero(ws, script)
    if p is None:
        return False
    try:
        ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        return True
    except Exception:
        return False


def _sublista(seq, patron) -> bool:
    """¿`patron` aparece como tramo CONTIGUO de `seq`?"""
    n, m = len(seq), len(patron)
    return any(seq[i:i + m] == patron for i in range(n - m + 1)) if m <= n else False


# --------------------------------------------------------------------------
# FACILES (3) — piso del banco: si un modelo falla aca, no es candidato
# --------------------------------------------------------------------------

def _post_f1(ws: Path) -> bool:
    return "banco listo" in _leer(ws, "saludo.txt").lower()


def _post_f2(ws: Path) -> bool:
    # 37*43 = 1591
    return _tiene_numero(_leer(ws, "producto.txt"), 1591)


def _post_f3(ws: Path) -> bool:
    d = _json_de(ws, "ajustes.json")
    if not isinstance(d, dict):
        return False
    if str(d.get("modo", "")).lower() != "estricto":
        return False
    try:
        return float(str(d.get("reintentos", "")).strip()) == 3.0
    except ValueError:
        return False


# --------------------------------------------------------------------------
# MEDIAS (4) — leer->transformar->escribir, editar sin romper, ejecutar
# --------------------------------------------------------------------------

def _prep_m1(ws: Path) -> None:
    (ws / "numeros.txt").write_text("12\n45\n7\n88\n3\n", encoding="utf-8")


def _post_m1(ws: Path) -> bool:
    # 12+45+7+88+3 = 155. Se exige el resultado Y que el fichero no sea una
    # COPIA de la entrada con el total pegado al final (el enunciado pide solo
    # el total; una linea con la cuenta "12+45+7+88+3 = 155" sigue valiendo).
    txt = _leer(ws, "suma.txt")
    return _tiene_numero(txt, 155) and len(_lineas(txt)) <= 3


_CONFIG_PY = (
    "# Configuracion del servicio\n"
    "TIMEOUT = 30\n"
    "REINTENTOS = 3\n"
    "HOST = \"127.0.0.1\"\n"
    "\n"
    "def resumen():\n"
    "    return f\"{HOST}:{TIMEOUT} x{REINTENTOS}\"\n"
)


def _prep_m2(ws: Path) -> None:
    (ws / "config.py").write_text(_CONFIG_PY, encoding="utf-8")


def _post_m2(ws: Path) -> bool:
    # Cambiar UN valor sin romper el resto: el fallo tipico del modelo chico es
    # reescribir el fichero entero y perder lineas.
    txt = _leer(ws, "config.py")
    if not txt or not _compila(ws, "config.py"):
        return False
    if not re.search(r"^\s*TIMEOUT\s*=\s*60\s*$", txt, re.M):
        return False
    if not re.search(r"^\s*REINTENTOS\s*=\s*3\s*$", txt, re.M):
        return False
    if '127.0.0.1' not in txt or "def resumen" not in txt:
        return False
    # Y el modulo tiene que COMPORTARSE igual: mirar solo la forma de las lineas
    # dejaba pasar tres trampas medidas el 2026-08-13 — `def resumen(): pass`,
    # `return ""` y un `TIMEOUT = 30` reasignado mas abajo — todas con el
    # fichero compilando y las tres lineas presentes.
    return _sonda(ws, "config.py", "_sonda_m2.py",
                  "from config import TIMEOUT, REINTENTOS, HOST, resumen\n"
                  "assert TIMEOUT == 60, TIMEOUT\n"
                  "assert REINTENTOS == 3, REINTENTOS\n"
                  "assert HOST == '127.0.0.1', HOST\n"
                  "assert resumen() == '127.0.0.1:60 x3', repr(resumen())\n"
                  "print('SONDA OK')\n")


def _post_m3(ws: Path) -> bool:
    # El script tiene que existir Y su salida guardada tiene que contener la
    # serie. Se acepta que empiece en 0 o en 1 (ambas convenciones): se exige
    # el tramo contiguo 1,2,3,5,8,13,21.
    serie = [1, 2, 3, 5, 8, 13, 21]
    if not _existe(ws, "fib.py"):
        return False
    nums = [int(n) for n in _numeros(_leer(ws, "salida_fib.txt")) if float(n).is_integer()]
    if not _sublista(nums, serie):
        return False
    # El script GUARDADO tiene que producir de verdad esa salida: si copio el
    # texto a mano y fib.py no corre, no ejecuto nada.
    code, out = _ejecutar_py(ws, "fib.py")
    reales = [int(n) for n in _numeros(out) if float(n).is_integer()]
    return code == 0 and _sublista(reales, serie)


def _prep_m4(ws: Path) -> None:
    (ws / "ventas.csv").write_text(
        "producto,precio\n"
        "teclado,120\n"
        "mouse,35\n"
        "monitor,240\n"
        "cable,8\n"
        "alfombrilla,15\n", encoding="utf-8")


def _post_m4(ws: Path) -> bool:
    txt = _leer(ws, "caros.txt").lower()
    if not txt.strip():
        return False
    dentro = ("teclado" in txt) and ("monitor" in txt)
    fuera = not any(p in txt for p in ("mouse", "cable", "alfombrilla"))
    return dentro and fuera


# --------------------------------------------------------------------------
# DIFICILES (5) — aca es donde se espera que Qwythos empiece a fallar
# --------------------------------------------------------------------------

def _prep_d1(ws: Path) -> None:
    (ws / "palabras.txt").write_text(
        "sol\nventana\nmar\nordenador\nluz\nteclado\npan\nmariposa\n", encoding="utf-8")
    (ws / "bitacora.md").write_text("# Bitacora\n", encoding="utf-8")


def _post_d1(ws: Path) -> bool:
    # Cuatro eslabones: filtrar, ordenar, contar y APENDAR sin borrar lo previo.
    largas = [l.lower() for l in _lineas_limpias(_leer(ws, "largas.txt"))]
    if largas != ["mariposa", "ordenador", "teclado", "ventana"]:
        return False
    if not _tiene_numero(_leer(ws, "conteo.txt"), 4):
        return False
    bit = _leer(ws, "bitacora.md")
    if "# Bitacora" not in bit:
        return False
    return any("largas" in ln.lower() and "4" in ln for ln in bit.splitlines())


_ROTO_PY = (
    "def calcular(a, b)\n"
    "    total = a + b\n"
    "    return total\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    print(calcular(20, 22)\n"
)


def _prep_d2(ws: Path) -> None:
    (ws / "roto.py").write_text(_ROTO_PY, encoding="utf-8")


def _post_d2(ws: Path) -> bool:
    # DOS errores de sintaxis (falta ':' y falta ')'). El modelo tiene que
    # LEER el error que le devuelve la verificacion y volver a intentar. Se
    # verifica ejecutando: compilar no basta, tiene que seguir imprimiendo 42.
    if not _compila(ws, "roto.py"):
        return False
    if "def calcular" not in _leer(ws, "roto.py"):
        return False   # borrar la funcion y dejar un print(42) no es arreglarlo
    code, out = _ejecutar_py(ws, "roto.py")
    if code != 0 or "42" not in out:
        return False
    # Y la funcion tiene que seguir siendo la misma funcion.
    return _sonda(ws, "roto.py", "_sonda_d2.py",
                  "from roto import calcular\n"
                  "assert calcular(20, 22) == 42\n"
                  "assert calcular(1, 2) == 3\n"
                  "print('SONDA OK')\n")


def _prep_d3(ws: Path) -> None:
    (ws / "precios.json").write_text(
        json.dumps({"cuaderno": 3.5, "lapiz": 0.75, "regla": 2.0}), encoding="utf-8")
    (ws / "pedido.csv").write_text(
        "producto,cantidad\ncuaderno,4\nlapiz,10\nregla,3\n", encoding="utf-8")


def _post_d3(ws: Path) -> bool:
    # 4*3.5 + 10*0.75 + 3*2.0 = 27.5 — integrar DOS ficheros de formato distinto.
    return _tiene_numero(_leer(ws, "total.txt"), 27.5, tol=0.02)


def _prep_d4(ws: Path) -> None:
    # datos_a.json esta TRUNCADO a proposito: no parsea como JSON.
    (ws / "datos_a.json").write_text('{"valores": [1, 2, 3,', encoding="utf-8")
    (ws / "datos_b.json").write_text('{"valores": [4, 8, 15, 16, 23, 42]}', encoding="utf-8")


def _post_d4(ws: Path) -> bool:
    # promedio de datos_b = 108/6 = 18.0. Si usa la fuente corrupta (o inventa
    # numeros a partir del texto truncado) da 2.0 y no hay 18.0 en ningun lado:
    # el 18.0 SOLO sale de datos_b, asi que es la senal que discrimina.
    txt = _leer(ws, "promedio.txt")
    if not _tiene_numero(txt, 18.0):
        return False
    # Anti-hedge: dar los DOS promedios sin elegir tampoco es resolver. Pero
    # solo cuenta si el 2.0 aparece como RESPUESTA (una linea que es ese numero
    # y nada mas); rechazar cualquier "2" del texto convertia en FALLO a
    # "promedio 18.0 (elegi datos_b, la otra fuente tiene 2 lineas)".
    return not any(re.fullmatch(r"-?2(?:[.,]0+)?", ln) for ln in _lineas(txt))


def _post_d5(ws: Path) -> bool:
    # El modelo escribe codigo Y su test. El test que decide NO es el suyo: es
    # el nuestro (abajo), corrido contra el modulo que quedo en disco. Su test
    # tambien tiene que existir y pasar (pytest exit 0 con >=1 test).
    if not (_existe(ws, "utilidades.py") and _existe(ws, "test_utilidades.py")):
        return False
    mod = _buscar_fichero(ws, "utilidades.py")
    ok_sonda = _sonda(
        ws, "utilidades.py", "_sonda_banco.py",
        "from utilidades import normalizar\n"
        "assert normalizar('  Hola Mundo  ') == 'hola mundo', repr(normalizar('  Hola Mundo  '))\n"
        "assert normalizar('YA') == 'ya'\n"
        "print('SONDA OK')\n")
    if not ok_sonda:
        return False
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             str(_buscar_fichero(ws, "test_utilidades.py"))],
            cwd=str(mod.parent), capture_output=True, text=True, timeout=180,
            stdin=subprocess.DEVNULL,
            encoding="utf-8", errors="replace")
    except Exception:
        return False
    salida = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0 and "no tests ran" not in salida.lower()


# --------------------------------------------------------------------------
# LAS TAREAS
# --------------------------------------------------------------------------

TAREAS = [
    # --- faciles ---------------------------------------------------------
    {"id": "f1_escribir", "dificultad": "facil",
     "enunciado": "escribí un archivo llamado saludo.txt con el texto exacto: banco listo",
     "preparacion": None, "postcondicion": _post_f1, "pasos": 6},
    {"id": "f2_calcular", "dificultad": "facil",
     "enunciado": "calculá 37 por 43 y guardá SOLO el resultado en producto.txt",
     "preparacion": None, "postcondicion": _post_f2, "pasos": 6},
    {"id": "f3_json", "dificultad": "facil",
     "enunciado": ("creá un archivo ajustes.json con dos claves: modo puesto en "
                   "estricto y reintentos puesto en 3"),
     "preparacion": None, "postcondicion": _post_f3, "pasos": 6},

    # --- medias ----------------------------------------------------------
    {"id": "m1_sumar_fichero", "dificultad": "media",
     "enunciado": ("el archivo numeros.txt tiene un número por línea. Sumá todos "
                   "esos números y escribí SOLO el total en suma.txt"),
     "preparacion": _prep_m1, "postcondicion": _post_m1, "pasos": 10},
    {"id": "m2_editar_sin_romper", "dificultad": "media",
     "enunciado": ("en config.py cambiá el valor de TIMEOUT de 30 a 60. No toques "
                   "ninguna otra línea del archivo: REINTENTOS, HOST y la función "
                   "resumen() tienen que quedar exactamente como están"),
     "preparacion": _prep_m2, "postcondicion": _post_m2, "pasos": 10},
    {"id": "m3_ejecutar_y_guardar", "dificultad": "media",
     "enunciado": ("escribí un script fib.py que imprima los primeros 10 números de "
                   "Fibonacci separados por espacios, ejecutalo, y guardá su salida "
                   "en salida_fib.txt"),
     "preparacion": None, "postcondicion": _post_m3, "pasos": 12},
    {"id": "m4_filtrar_csv", "dificultad": "media",
     "enunciado": ("ventas.csv tiene columnas producto,precio. Escribí en caros.txt "
                   "los nombres de los productos que cuestan MÁS de 100, uno por "
                   "línea, y ninguno más"),
     "preparacion": _prep_m4, "postcondicion": _post_m4, "pasos": 12},

    # --- dificiles -------------------------------------------------------
    {"id": "d1_cadena_cuatro_pasos", "dificultad": "dificil",
     "enunciado": ("palabras.txt tiene una palabra por línea. Hacé estas cuatro "
                   "cosas: (1) escribí en largas.txt las palabras de MÁS de 5 letras, "
                   "ordenadas alfabéticamente, una por línea; (2) escribí en "
                   "conteo.txt cuántas son; (3) agregá al final de bitacora.md una "
                   "línea con el formato largas=N; (4) no borres el encabezado que "
                   "ya tiene bitacora.md"),
     "preparacion": _prep_d1, "postcondicion": _post_d1, "pasos": 18},
    {"id": "d2_sintaxis", "dificultad": "dificil",
     "enunciado": ("el archivo roto.py no compila: tiene errores de sintaxis. "
                   "Arreglalo SIN cambiar lo que hace, y verificá ejecutándolo hasta "
                   "que corra sin error e imprima 42. Si el error persiste, leé el "
                   "mensaje y volvé a corregir"),
     "preparacion": _prep_d2, "postcondicion": _post_d2, "pasos": 18},
    {"id": "d3_integrar_dos_ficheros", "dificultad": "dificil",
     "enunciado": ("precios.json tiene el precio unitario de cada producto y "
                   "pedido.csv tiene producto,cantidad. Calculá el importe total del "
                   "pedido cruzando los dos archivos y escribí SOLO ese total en "
                   "total.txt"),
     "preparacion": _prep_d3, "postcondicion": _post_d3, "pasos": 16},
    {"id": "d4_elegir_fuente", "dificultad": "dificil",
     "enunciado": ("hay dos fuentes de datos: datos_a.json y datos_b.json. Una de las "
                   "dos está corrupta y no es JSON válido. Averiguá cuál sirve, "
                   "calculá el promedio de su lista valores y escribí SOLO ese "
                   "promedio en promedio.txt"),
     "preparacion": _prep_d4, "postcondicion": _post_d4, "pasos": 16},
    {"id": "d5_codigo_con_test", "dificultad": "dificil",
     "enunciado": ("creá utilidades.py con una función normalizar(texto) que devuelva "
                   "el texto en minúsculas y sin espacios al principio ni al final. "
                   "Creá también test_utilidades.py con al menos un test de pytest que "
                   "la pruebe, corré pytest y dejalo en verde"),
     "preparacion": None, "postcondicion": _post_d5, "pasos": 20},
]


# --------------------------------------------------------------------------
# Corrida
# --------------------------------------------------------------------------

def _correr_una(ai, tarea: dict, print_fn, max_steps=None):
    """Corre UNA tarea en un workspace temporal y verifica en disco.

    Mismo protocolo que scripts/e2e_happy_path.py: workspace temporal,
    dev_tools.AGENT_WORKSPACE_ROOT reapuntado y RESTAURADO, cwd reapuntado y
    restaurado. Devuelve (ok, respuesta_recortada, segundos, ws).
    """
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli

    ws = Path(tempfile.mkdtemp(prefix=f"banco_{tarea['id']}_")).resolve()
    prep = tarea.get("preparacion")
    if prep:
        prep(ws)

    pasos = max_steps or tarea.get("pasos") or PASOS_POR_DIFICULTAD.get(
        tarea["dificultad"], 10)

    t0 = time.time()
    prev_cwd = os.getcwd()
    prev_root = dev_tools.AGENT_WORKSPACE_ROOT
    prev_env = os.environ.get("COGNIA_AGENT_WORKSPACE")
    # Las tres mutaciones van DENTRO del try: si os.chdir(ws) fallara (ruta
    # borrada, permisos) con las dos primeras ya hechas, el proceso se quedaba
    # con el workspace del banco apuntando a un temporal muerto para siempre.
    try:
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.environ["COGNIA_AGENT_WORKSPACE"] = str(ws)
        os.chdir(ws)
        resp = _cli._run_agent_task(ai, tarea["enunciado"],
                                    print_fn or (lambda s: None),
                                    max_steps=pasos)
    except Exception as exc:
        resp = f"EXCEPTION: {exc}"
    finally:
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        if prev_env is None:
            os.environ.pop("COGNIA_AGENT_WORKSPACE", None)
        else:
            os.environ["COGNIA_AGENT_WORKSPACE"] = prev_env
    segundos = time.time() - t0

    # LA VERIFICACION: solo disco. `resp` no entra nunca en el veredicto.
    try:
        ok = bool(tarea["postcondicion"](ws))
    except Exception as exc:
        ok = False
        resp = f"{resp} | verify exc: {exc}"
    return ok, (str(resp) or "")[:200], segundos, ws


def correr_banco(ai, print_fn=None, max_steps=None, tareas=None, verbose=True) -> dict:
    """Corre el banco entero y devuelve el resultado agregado.

    ai        : objeto con ._orchestrator (el mismo que espera cli._run_agent_task)
    print_fn  : callback de trazas del agente (None = mudo)
    max_steps : pisa el presupuesto de pasos de TODAS las tareas (None = el de
                cada tarea; usarlo solo para ablaciones de presupuesto)
    tareas    : subconjunto de TAREAS (None = todas)
    verbose   : imprime una linea por tarea, estilo e2e_happy_path

    Devuelve {total, de, puntos, puntos_max, por_dificultad, detalle, segundos}.
    """
    lista = list(tareas if tareas is not None else TAREAS)
    detalle, t_ini, interrumpido = [], time.time(), False

    for tarea in lista:
        try:
            ok, resp, secs, ws = _correr_una(ai, tarea, print_fn, max_steps)
        except KeyboardInterrupt:
            # Ctrl-C a mitad: el estado (cwd/workspace) ya lo restauro el
            # finally de _correr_una. Aca se corta la corrida CONSERVANDO lo
            # medido hasta ahora, y se marca el resultado como parcial para que
            # nadie lo compare contra una corrida entera.
            interrumpido = True
            if verbose:
                print("  [STOP] interrumpido por el usuario (Ctrl-C)", flush=True)
            break
        detalle.append({
            "id": tarea["id"],
            "dificultad": tarea["dificultad"],
            "ok": ok,
            "segundos": round(secs, 1),
            "peso": PESOS.get(tarea["dificultad"], 1),
            "respuesta": resp,
            "workspace": str(ws),
        })
        if verbose:
            print(f"  [{'OK  ' if ok else 'FAIL'}] {tarea['dificultad'][:3]} "
                  f"{tarea['id']} ({secs:.0f}s)"
                  + ("" if ok else f" — {resp[:90]}"), flush=True)

    por_dif = {}
    for d in detalle:
        celda = por_dif.setdefault(d["dificultad"], {"ok": 0, "de": 0})
        celda["de"] += 1
        celda["ok"] += 1 if d["ok"] else 0

    return {
        "total": sum(1 for d in detalle if d["ok"]),
        "de": len(detalle),
        "puntos": sum(d["peso"] for d in detalle if d["ok"]),
        "puntos_max": sum(d["peso"] for d in detalle),
        "por_dificultad": por_dif,
        "detalle": detalle,
        "segundos": round(time.time() - t_ini, 1),
        "interrumpido": interrumpido,
        "pedidas": len(lista),
    }


# --------------------------------------------------------------------------
# AUTOVERIFICACION (--dry-run): el instrumento antes que la medida
# --------------------------------------------------------------------------
#
# Un banco solo sirve si (a) aprueba a quien hace la tarea bien y (b) REPRUEBA
# a quien no la hizo. Lo segundo no es gratis: la version del 2026-08-13 daba
# por buena una m2 con `def resumen(): pass` porque miraba la FORMA del fichero
# y no su comportamiento. Esto lo corre sin backend: escribe la solucion
# perfecta en un workspace y exige True, y sobre uno VACIO (el modelo que
# contesta "ya lo hice" sin tocar nada) exige False.

def _w(ws: Path, nombre: str, txt: str) -> None:
    p = ws / nombre
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


_FIB_PY = ("a, b = 0, 1\nout = []\nfor _ in range(10):\n"
           "    out.append(str(a))\n    a, b = b, a + b\nprint(' '.join(out))\n")

GOLDEN = {
    "f1_escribir": lambda ws: _w(ws, "saludo.txt", "banco listo\n"),
    "f2_calcular": lambda ws: _w(ws, "producto.txt", "1591\n"),
    "f3_json": lambda ws: _w(ws, "ajustes.json",
                             '{"modo": "estricto", "reintentos": 3}'),
    "m1_sumar_fichero": lambda ws: _w(ws, "suma.txt", "155\n"),
    "m2_editar_sin_romper": lambda ws: _w(
        ws, "config.py", _CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 60")),
    "m3_ejecutar_y_guardar": lambda ws: (
        _w(ws, "fib.py", _FIB_PY),
        _w(ws, "salida_fib.txt", "0 1 1 2 3 5 8 13 21 34\n")),
    "m4_filtrar_csv": lambda ws: _w(ws, "caros.txt", "teclado\nmonitor\n"),
    "d1_cadena_cuatro_pasos": lambda ws: (
        _w(ws, "largas.txt", "mariposa\nordenador\nteclado\nventana\n"),
        _w(ws, "conteo.txt", "4\n"),
        _w(ws, "bitacora.md", "# Bitacora\nlargas=4\n")),
    "d2_sintaxis": lambda ws: _w(ws, "roto.py", _ROTO_PY
                                 .replace("def calcular(a, b)", "def calcular(a, b):")
                                 .replace("print(calcular(20, 22)", "print(calcular(20, 22))")),
    "d3_integrar_dos_ficheros": lambda ws: _w(ws, "total.txt", "27.5\n"),
    "d4_elegir_fuente": lambda ws: _w(ws, "promedio.txt", "18.0\n"),
    "d5_codigo_con_test": lambda ws: (
        _w(ws, "utilidades.py",
           "def normalizar(texto):\n    return texto.strip().lower()\n"),
        _w(ws, "test_utilidades.py",
           "from utilidades import normalizar\n\n"
           "def test_normalizar():\n    assert normalizar('  Hola  ') == 'hola'\n")),
}

# Trampas MEDIDAS: cada una fallaba de verdad en alguna version del banco.
TRAMPAS = [
    ("m2_editar_sin_romper", "resumen() vaciada, lineas intactas",
     lambda ws: _w(ws, "config.py", 'TIMEOUT = 60\nREINTENTOS = 3\n'
                   'HOST = "127.0.0.1"\n\ndef resumen():\n    return ""\n')),
    ("m2_editar_sin_romper", "reasigna TIMEOUT=30 mas abajo",
     lambda ws: _w(ws, "config.py",
                   _CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 60") + "TIMEOUT = 30\n")),
    ("m3_ejecutar_y_guardar", "copia la salida a mano; fib.py no la produce",
     lambda ws: (_w(ws, "fib.py", "print('hola')\n"),
                 _w(ws, "salida_fib.txt", "0 1 1 2 3 5 8 13 21 34\n"))),
    ("d2_sintaxis", "borra la funcion y deja print(42)",
     lambda ws: _w(ws, "roto.py", "print(42)\n")),
    ("d2_sintaxis", "hardcodea el 42 dentro de la funcion",
     lambda ws: _w(ws, "roto.py", "def calcular(a, b):\n    return 42\n\n"
                   "if __name__ == '__main__':\n    print(calcular(20, 22))\n")),
    ("d4_elegir_fuente", "usa la fuente corrupta (2.0)",
     lambda ws: _w(ws, "promedio.txt", "2.0\n")),
    ("d1_cadena_cuatro_pasos", "borra el encabezado de bitacora",
     lambda ws: (_w(ws, "largas.txt", "mariposa\nordenador\nteclado\nventana\n"),
                 _w(ws, "conteo.txt", "4\n"), _w(ws, "bitacora.md", "largas=4\n"))),
    ("d5_codigo_con_test", "no hace strip; su test es vacuo",
     lambda ws: (_w(ws, "utilidades.py", "def normalizar(t):\n    return t.lower()\n"),
                 _w(ws, "test_utilidades.py", "def test_x():\n    assert True\n"))),
    ("d5_codigo_con_test", "codigo bien pero su test en rojo",
     lambda ws: (_w(ws, "utilidades.py",
                    "def normalizar(t):\n    return t.strip().lower()\n"),
                 _w(ws, "test_utilidades.py", "def test_x():\n    assert False\n"))),
    ("m4_filtrar_csv", "cuela un producto barato",
     lambda ws: _w(ws, "caros.txt", "teclado\nmonitor\nmouse\n")),
]


def _caso_seco(tarea: dict, escribir, esperado: bool, nota: str) -> bool:
    ws = Path(tempfile.mkdtemp(prefix="seco_")).resolve()
    try:
        prep = tarea.get("preparacion")
        if prep:
            prep(ws)
        if escribir:
            escribir(ws)
        try:
            got = bool(tarea["postcondicion"](ws))
        except Exception as exc:
            got = f"EXC {exc}"
        ok = (got is esperado)
        print(f"  [{'OK  ' if ok else 'MAL '}] {tarea['id']:24s} "
              f"espera={str(esperado):5s} da={got!s:5s}  {nota}", flush=True)
        return ok
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def autoverificar(lista=None) -> bool:
    """--dry-run: prueba el BANCO, no al modelo. No toca ningun backend."""
    lista = list(lista if lista is not None else TAREAS)
    print(f"AUTOVERIFICACION (sin backend) — {len(lista)} tareas", flush=True)
    malos = []

    print("\n GOLDEN (la solucion perfecta tiene que APROBAR)", flush=True)
    for t in lista:
        if not _caso_seco(t, GOLDEN[t["id"]], True, "golden"):
            malos.append((t["id"], "golden"))

    print("\n MENTIROSO (dice 'ya lo hice' y no escribe nada -> REPROBAR)", flush=True)
    for t in lista:
        if not _caso_seco(t, None, False, "workspace vacio"):
            malos.append((t["id"], "mentiroso"))

    ids = {t["id"] for t in lista}
    trampas = [x for x in TRAMPAS if x[0] in ids]
    if trampas:
        print("\n TRAMPAS (hecho a medias o simulado -> REPROBAR)", flush=True)
        for tid, nota, escribir in trampas:
            t = next(x for x in TAREAS if x["id"] == tid)
            if not _caso_seco(t, escribir, False, nota):
                malos.append((tid, nota))

    print(f"\nAUTOVERIFICACION: {'OK' if not malos else str(len(malos)) + ' FALLOS'}",
          flush=True)
    for m in malos:
        print("  -", m, flush=True)
    return not malos


def construir_ai():
    """Arma el `ai` contra el backend que HAYA (igual que e2e_happy_path).

    Si ya hay un llama-server vivo en el puerto, LlamaBackend lo ADOPTA: este
    script no levanta un modelo propio salvo que no haya ninguno. Devuelve
    (ai, orch).
    """
    from cognia.first_run import apply_config
    apply_config()
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch
    return ai, orch


def _parar_si_es_nuestro(orch) -> None:
    """Para SOLO el proceso que arranco esta corrida. stop() de LlamaBackend
    termina unicamente self._proc: un server ADOPTADO (el cerebro del usuario)
    queda intacto. Mismo criterio que el gate.

    Se llama SIEMPRE desde un finally: si la corrida revienta a mitad (o el
    usuario da Ctrl-C) y este script habia levantado un server propio, dejarlo
    vivo bloquea el puerto y la VRAM del cerebro del dueno."""
    try:
        if getattr(orch, "_llama", None) is not None:
            orch._llama.stop()
    except Exception:
        pass


def _identidad_backend(orch) -> dict:
    """Quien va a contestar: modelo SERVIDO, puerto y si fue ADOPTADO.

    Se pregunta al server (/props -> model_path), no al manifiesto local: en un
    banco que compara cerebros, etiquetar la corrida con el modelo equivocado
    invalida la medicion entera. `adoptado` sale de que el impl no tenga _proc
    propio; None = no se pudo determinar."""
    info = {"modelo": "", "puerto": None, "adoptado": None}
    llama = getattr(orch, "_llama", None)
    if llama is None:
        return info
    try:
        props = llama.server_props() or {}
        info["modelo"] = str(props.get("model_path") or "")
    except Exception:
        pass
    if not info["modelo"]:
        try:
            info["modelo"] = str(llama.gguf_path or "")
        except Exception:
            pass
    impl = getattr(llama, "_impl", None)
    if impl is not None:
        info["puerto"] = getattr(impl, "_port", None)
        if hasattr(impl, "_proc"):
            info["adoptado"] = getattr(impl, "_proc", None) is None
    return info


def medir(url: str = "", puerto=None, minimo=None, tareas=None) -> dict:
    """Punto de entrada para el arnes de barrido: `py:banco_cerebro:medir`.

    scripts/comparar_modelos.py importa la funcion y le pasa SOLO los kwargs
    que su firma acepta (url, puerto), esperando un dict con 'ok'. La firma que
    documentaba este modulo (correr_banco) no acepta ninguno de los dos y pide
    `ai` posicional: el barrido moria con TypeError y anotaba 'banco FALLO'
    para todos los modelos — verificado 2026-08-13 reproduciendo la llamada.

    'ok' significa CORRIO ENTERO, no aprobado: el resultado de un banco
    graduado es el puntaje ('puntaje': 'p/max'), no un booleano. Con `minimo`
    (puntos) si hay veredicto.

    OJO: esta via corre EN EL PROCESO del barrido, asi que los caches por URL
    (props, perfiles) sobreviven entre candidatos. Para comparar modelos es
    preferible la via COMANDO, que aisla cada medicion en su propio proceso:
        --banco "scripts\\banco_cerebro.py"
    """
    previo = {k: os.environ.get(k) for k in ("LLAMA_SERVER_PORT", "COGNIA_LLM_URL")}
    if puerto:
        os.environ["LLAMA_SERVER_PORT"] = str(puerto)
    if url:
        os.environ["COGNIA_LLM_URL"] = str(url)
    orch = None
    try:
        ai, orch = construir_ai()
        res = correr_banco(ai, print_fn=None, tareas=tareas)
    finally:
        if orch is not None:
            _parar_si_es_nuestro(orch)
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    res["backend"] = _identidad_backend(orch) if orch is not None else {}
    res["puntaje"] = f"{res['puntos']}/{res['puntos_max']}"
    res["ok"] = (not res.get("interrumpido")
                 and (res["puntos"] >= minimo if minimo is not None else True))
    return res


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    def _opt(nombre, default=None):
        """Valor de `--flag valor`. Si lo que sigue es OTRO flag, se trata como
        ausente: `--solo --dif dificil` ponia solo='--dif' y el banco corria
        cero tareas sin decir por que."""
        if nombre in argv:
            i = argv.index(nombre)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                return argv[i + 1]
        return default

    def _entero(nombre, valor):
        if valor is None:
            return None
        try:
            return int(valor)
        except ValueError:
            print(f"{nombre} espera un entero, llego {valor!r}", flush=True)
            raise SystemExit(2)

    solo = _opt("--solo")
    dif = _opt("--dif")
    pasos = _entero("--pasos", _opt("--pasos"))
    destino = _opt("--json")
    minimo = _entero("--minimo", _opt("--minimo"))
    trazas = "--trazas" in argv
    seco = "--dry-run" in argv

    lista = TAREAS
    if dif:
        lista = [t for t in lista if t["dificultad"].startswith(dif.lower()[:3])]
    if solo:
        ids = {s.strip() for s in solo.split(",") if s.strip()}
        desconocidos = ids - {t["id"] for t in TAREAS}
        if desconocidos:
            print(f"ids desconocidos: {', '.join(sorted(desconocidos))}", flush=True)
        lista = [t for t in lista if t["id"] in ids]
    if not lista:
        print("Ninguna tarea coincide con el filtro.", flush=True)
        return 2

    if seco:
        # NO se construye el backend: --dry-run no abre una sola conexion.
        return 0 if autoverificar(lista) else 1

    ai, orch = construir_ai()
    ident = _identidad_backend(orch)
    quien = ("ADOPTADO (no se toca al salir)" if ident["adoptado"] is True else
             "ARRANCADO POR ESTA CORRIDA (se para al salir)"
             if ident["adoptado"] is False else "origen desconocido")
    print(f"BANCO CEREBRO — {len(lista)} tareas"
          + (f" — modelo: {Path(ident['modelo']).name}" if ident["modelo"] else "")
          + (f" — :{ident['puerto']}" if ident["puerto"] else "")
          + f" — backend {quien}", flush=True)

    res = {}
    try:
        res = correr_banco(ai, print_fn=(print if trazas else None),
                           max_steps=pasos, tareas=lista)
    finally:
        # SIEMPRE: excepcion, Ctrl-C que se escapa, o salida limpia. Lo unico
        # que se para es el proceso propio (ver _parar_si_es_nuestro).
        _parar_si_es_nuestro(orch)

    res["modelo"] = ident["modelo"]
    res["backend"] = ident
    print(f"\nBANCO CEREBRO: {res['total']}/{res['de']} OK "
          f"({res['puntos']}/{res['puntos_max']} pts) en "
          f"{res['segundos'] / 60:.1f} min"
          + (f"  [PARCIAL: {res['de']}/{res['pedidas']} tareas, interrumpido]"
             if res.get("interrumpido") else ""), flush=True)
    for nivel in ("facil", "media", "dificil"):
        celda = res["por_dificultad"].get(nivel)
        if celda:
            print(f"  {nivel:8s} {celda['ok']}/{celda['de']}", flush=True)
    fallos = [d["id"] for d in res["detalle"] if not d["ok"]]
    if fallos:
        print("FALLARON:", ", ".join(fallos), flush=True)
    if destino:
        # Media hora de corrida no se pierde por un directorio inexistente.
        try:
            p = Path(destino)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            print(f"JSON -> {destino}", flush=True)
        except Exception as exc:
            alterno = Path(tempfile.gettempdir()) / f"banco_cerebro_{int(time.time())}.json"
            alterno.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            print(f"JSON: no pude escribir {destino} ({exc}); guardado en {alterno}",
                  flush=True)

    # ULTIMA linea y con UNA sola fraccion, a proposito: el arnes de barrido
    # (scripts/comparar_modelos.py, _puntaje) se queda con el ULTIMO 'N/M' del
    # stdout. Con el desglose por dificultad al final, la tabla del barrido
    # mostraba '0/5' (los dificiles) como si fuera el resultado del banco.
    print(f"RESULTADO BANCO CEREBRO: {res['puntos']}/{res['puntos_max']} pts",
          flush=True)

    if res.get("interrumpido"):
        return 130
    if minimo is not None:
        return 0 if res["total"] >= minimo else 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # El finally de main ya paro lo que fuera nuestro; aca solo el codigo.
        print("\ninterrumpido", flush=True)
        sys.exit(130)
