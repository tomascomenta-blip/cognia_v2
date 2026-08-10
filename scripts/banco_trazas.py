# -*- coding: utf-8 -*-
"""
scripts/banco_trazas.py — bateria de tareas /hacer para FABRICAR trazas selladas.

POR QUE: el cuello del dataset es fabricar SENAL, no el constructor. Este banco
generaliza el patron de scripts/e2e_happy_path.py (hacer + verificar(ws) sobre
el filesystem REAL) a plantillas parametrizadas por semilla: nombres, valores y
contenidos aleatorios hacen que cada corrida sobreviva el dedupe del dataset, y
la postcondicion ejecutable es el sello de EVIDENCIA REAL
(``{"verificar_ws": ok, "banco": "banco_trazas"}``) que el filtro exige.

PRE-CHEQUEO QUE CORRE (no leccion en prosa): antes de generar, se ejecuta
``python -c`` desde un workspace temporal. 2 de 3 bitacoras reales fallaron por
exit 9009 — el alias de Microsoft Store, no el modelo. Generar en masa sin este
chequeo envenena el dataset con fallos de infra.

Uso (GPU: el cerebro :8080 atiende — nada mas debe correr):
  set COGNIA_TRAZAS=1  (el script lo fuerza igual)
  venv312\\Scripts\\python.exe scripts\\banco_trazas.py --n 100 --semilla 7 --desde 0

Exit: 0 corrio (los fallos de verificacion se SELLAN como false, no abortan);
2 pre-chequeo de interprete fallo (no se genero nada).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Vocabulario neutro para parametrizar: palabras sin tildes (los comentarios
# del codigo generado tampoco las llevan) y faciles de verificar por igualdad.
_PALABRAS = ["bateria", "molino", "cometa", "farol", "brujula", "canela",
             "granito", "vereda", "timon", "laurel", "cascada", "membrillo",
             "pizarra", "nogal", "estepa", "faisan"]
_NOMBRES = ["nota", "resumen", "datos", "registro", "salida", "informe",
            "apunte", "acta", "detalle", "parte"]
_CLAVES = ["modo", "nivel", "tono", "ritmo", "canal", "perfil"]
_VALORES = ["rapido", "alto", "suave", "doble", "norte", "base"]


def _lee(ws: Path, nombre: str) -> str:
    hits = list(ws.rglob(nombre))
    return hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""


# ── Plantillas ─────────────────────────────────────────────────────────
# Cada plantilla: f(rng) -> (nombre, tarea, verificar(ws), setup(ws)|None).
# La postcondicion mira el FILESYSTEM real (o, marcado con nombre 'resp:',
# la respuesta final) — nunca la palabra del modelo sobre si mismo.

def _p_escribir(rng):
    arch = rng.choice(_NOMBRES) + ".txt"
    frase = f"{rng.choice(_PALABRAS)} {rng.choice(_PALABRAS)} {rng.randint(10, 99)}"
    return ("escribir",
            f"escribi un archivo llamado {arch} con el texto exacto: {frase}",
            lambda ws: frase in _lee(ws, arch), None)


def _p_multiplicar(rng):
    a, b = rng.randint(11, 97), rng.randint(11, 97)
    arch = rng.choice(_NOMBRES) + ".txt"
    return ("multiplicar",
            f"calcula {a} por {b} y guarda el resultado en {arch}",
            lambda ws: str(a * b) in _lee(ws, arch), None)


def _p_sumar(rng):
    nums = [rng.randint(100, 900) for _ in range(3)]
    return ("sumar",
            f"calcula la suma de {nums[0]}, {nums[1]} y {nums[2]} y "
            "guarda solo el resultado en suma.txt",
            lambda ws: str(sum(nums)) in _lee(ws, "suma.txt"), None)


def _p_json(rng):
    clave, valor = rng.choice(_CLAVES), rng.choice(_VALORES)
    arch = "config" + str(rng.randint(1, 9)) + ".json"

    def verificar(ws):
        try:
            return json.loads(_lee(ws, arch) or "{}").get(clave) == valor
        except Exception:
            return False
    return ("json",
            f"crea un archivo {arch} con la clave {clave} puesta en {valor}",
            verificar, None)


def _p_apendar(rng):
    linea = rng.choice(_PALABRAS) + "-" + str(rng.randint(100, 999))
    previas = [rng.choice(_PALABRAS) for _ in range(2)]

    def setup(ws):
        (ws / "bitacora.txt").write_text("\n".join(previas) + "\n",
                                         encoding="utf-8")

    def verificar(ws):
        lineas = _lee(ws, "bitacora.txt").strip().splitlines()
        return bool(lineas) and lineas[-1].strip().strip("'\"") == linea
    return ("apendar",
            f"agrega la linea '{linea}' al final del archivo bitacora.txt",
            verificar, setup)


def _p_script_python(rng):
    a, b = rng.randint(100, 400), rng.randint(100, 400)
    return ("resp:python",
            f"escribi y ejecuta un script python que imprima la suma de "
            f"{a} mas {b}",
            lambda ws: True, None, str(a + b))


def _p_copiar(rng):
    origen = rng.choice(_NOMBRES) + ".txt"
    destino = "copia_" + origen
    contenido = rng.choice(_PALABRAS) + " " + str(rng.randint(1000, 9999))

    def setup(ws):
        (ws / origen).write_text(contenido, encoding="utf-8")
    return ("copiar",
            f"copia el archivo {origen} a {destino}",
            lambda ws: contenido in _lee(ws, destino), setup)


def _p_dir_y_archivo(rng):
    carpeta = rng.choice(_PALABRAS)
    frase = rng.choice(_PALABRAS) + str(rng.randint(10, 99))
    return ("dir+archivo",
            f"crea un directorio {carpeta} y adentro un archivo listo.txt "
            f"con el texto: {frase}",
            lambda ws: (ws / carpeta).is_dir()
            and frase in _lee(ws / carpeta, "listo.txt"), None)


def _p_contar_lineas(rng):
    n = rng.randint(4, 9)
    arch = rng.choice(_NOMBRES) + ".txt"

    def setup(ws):
        (ws / arch).write_text(
            "\n".join(rng.choice(_PALABRAS) for _ in range(n)) + "\n",
            encoding="utf-8")
    return ("contar_lineas",
            f"conta cuantas lineas tiene el archivo {arch} y guarda el "
            "numero en total.txt",
            lambda ws: str(n) in _lee(ws, "total.txt"), setup)


def _p_reemplazar(rng):
    vieja, nueva = rng.sample(_PALABRAS, 2)
    arch = rng.choice(_NOMBRES) + ".txt"

    def setup(ws):
        (ws / arch).write_text(f"primera {vieja} final\n", encoding="utf-8")

    def verificar(ws):
        t = _lee(ws, arch)
        return nueva in t and vieja not in t
    return ("reemplazar",
            f"en el archivo {arch} reemplaza la palabra {vieja} por {nueva}",
            verificar, setup)


def _p_csv(rng):
    cols = rng.sample(_CLAVES, 2)
    return ("csv",
            f"crea un archivo tabla.csv cuya primera linea sea el encabezado "
            f"{cols[0]},{cols[1]}",
            lambda ws: _lee(ws, "tabla.csv").strip().splitlines()[:1] in
            ([f"{cols[0]},{cols[1]}"], [f"{cols[0]}, {cols[1]}"]), None)


def _p_mayusculas(rng):
    palabra = rng.choice(_PALABRAS)

    def setup(ws):
        (ws / "origen.txt").write_text(palabra, encoding="utf-8")
    return ("mayusculas",
            "lee el archivo origen.txt y escribi su contenido en mayusculas "
            "en mayus.txt",
            lambda ws: palabra.upper() in _lee(ws, "mayus.txt"), setup)


def _p_inventario(rng):
    nombres = [f"{rng.choice(_PALABRAS)}{i}.txt" for i in range(3)]

    def setup(ws):
        for n in nombres:
            (ws / n).write_text("x", encoding="utf-8")

    def verificar(ws):
        inv = _lee(ws, "inventario.txt")
        return sum(1 for n in nombres if n in inv) >= 2
    return ("inventario",
            "lista los archivos .txt del directorio actual y guarda sus "
            "nombres en inventario.txt",
            verificar, setup)


def _p_funcion(rng):
    fn = "calcular_" + rng.choice(_PALABRAS)
    return ("funcion",
            f"escribi un archivo util.py con una funcion {fn} que reciba x "
            "y devuelva x*2",
            lambda ws: ("def " + fn) in _lee(ws, "util.py"), None)


def _p_readme(rng):
    titulo = rng.choice(_PALABRAS).capitalize() + " " + str(rng.randint(1, 9))
    return ("readme",
            f"crea un README.md cuyo titulo (primera linea con #) sea: {titulo}",
            lambda ws: titulo in _lee(ws, "README.md"), None)


def _p_invertir(rng):
    palabra = rng.choice(_PALABRAS)

    def setup(ws):
        (ws / "palabra.txt").write_text(palabra, encoding="utf-8")
    return ("invertir",
            "lee palabra.txt e imprimi/guarda el texto invertido (al reves) "
            "en reves.txt",
            lambda ws: palabra[::-1] in _lee(ws, "reves.txt"), setup)


def _p_secuencia(rng):
    n = rng.randint(5, 9)

    def verificar(ws):
        lineas = [ln.strip() for ln in _lee(ws, "numeros.txt").splitlines()
                  if ln.strip()]
        return lineas[:n] == [str(i) for i in range(1, n + 1)]
    return ("secuencia",
            f"escribi en numeros.txt los numeros del 1 al {n}, uno por linea",
            verificar, None)


def _p_concatenar(rng):
    a, b = rng.sample(_PALABRAS, 2)

    def setup(ws):
        (ws / "parte1.txt").write_text(a, encoding="utf-8")
        (ws / "parte2.txt").write_text(b, encoding="utf-8")

    def verificar(ws):
        t = _lee(ws, "junto.txt")
        return a in t and b in t
    return ("concatenar",
            "junta el contenido de parte1.txt y parte2.txt en un archivo "
            "junto.txt",
            verificar, setup)


def _p_filtrar(rng):
    marca = rng.choice(_PALABRAS)
    otras = [w for w in _PALABRAS if w != marca]

    def setup(ws):
        lineas = [f"{marca} uno", rng.choice(otras), f"dos {marca}",
                  rng.choice(otras)]
        (ws / "log.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    def verificar(ws):
        t = _lee(ws, "filtrado.txt")
        return marca in t and t.count(marca) >= 2
    return ("filtrar",
            f"extrae de log.txt las lineas que contienen la palabra {marca} "
            "y guardalas en filtrado.txt",
            verificar, setup)


def _p_json_lista(rng):
    n = rng.randint(3, 6)

    def verificar(ws):
        try:
            datos = json.loads(_lee(ws, "lista.json") or "null")
            return isinstance(datos, list) and len(datos) == n
        except Exception:
            return False
    return ("json_lista",
            f"crea un archivo lista.json que contenga una lista JSON de "
            f"exactamente {n} numeros",
            verificar, None)


def _p_script_archivo(rng):
    frase = rng.choice(_PALABRAS) + "-" + str(rng.randint(100, 999))
    return ("script_archivo",
            f"escribi y ejecuta un script python que cree un archivo "
            f"generado.txt con el texto: {frase}",
            lambda ws: frase in _lee(ws, "generado.txt"), None)


def _p_contar_palabras(rng):
    palabras = [rng.choice(_PALABRAS) for _ in range(rng.randint(5, 9))]

    def setup(ws):
        (ws / "texto.txt").write_text(" ".join(palabras), encoding="utf-8")
    return ("contar_palabras",
            "conta cuantas palabras tiene texto.txt y guarda el numero en "
            "cuenta.txt",
            lambda ws: str(len(palabras)) in _lee(ws, "cuenta.txt"), setup)


def _p_porcentaje(rng):
    total = rng.choice([200, 400, 500, 800])
    pct = rng.choice([10, 20, 25, 50])
    esperado = total * pct // 100
    return ("porcentaje",
            f"calcula el {pct} por ciento de {total} y guarda solo el "
            "resultado en pct.txt",
            lambda ws: str(esperado) in _lee(ws, "pct.txt"), None)


def _p_ordenar(rng):
    nums = rng.sample(range(10, 99), 4)

    def setup(ws):
        (ws / "desorden.txt").write_text(
            "\n".join(str(n) for n in nums) + "\n", encoding="utf-8")

    def verificar(ws):
        lineas = [ln.strip() for ln in _lee(ws, "orden.txt").splitlines()
                  if ln.strip()]
        return lineas == [str(n) for n in sorted(nums)]
    return ("ordenar",
            "lee los numeros de desorden.txt (uno por linea) y escribilos "
            "ordenados de menor a mayor en orden.txt",
            verificar, setup)


def _p_renombrar(rng):
    viejo = rng.choice(_NOMBRES) + "_v1.txt"
    nuevo = "final_" + str(rng.randint(10, 99)) + ".txt"
    contenido = rng.choice(_PALABRAS)

    def setup(ws):
        (ws / viejo).write_text(contenido, encoding="utf-8")
    return ("renombrar",
            f"crea una copia del archivo {viejo} con el nombre {nuevo}",
            lambda ws: contenido in _lee(ws, nuevo), setup)


PLANTILLAS = [
    _p_escribir, _p_multiplicar, _p_sumar, _p_json, _p_apendar,
    _p_script_python, _p_copiar, _p_dir_y_archivo, _p_contar_lineas,
    _p_reemplazar, _p_csv, _p_mayusculas, _p_inventario, _p_funcion,
    _p_readme, _p_invertir, _p_secuencia, _p_concatenar, _p_filtrar,
    _p_json_lista, _p_script_archivo, _p_contar_palabras, _p_porcentaje,
    _p_ordenar, _p_renombrar,
]


def generar_tareas(n: int, semilla: int, desde: int = 0) -> list:
    """n tareas deterministas por (semilla, indice): la misma semilla
    reproduce el banco entero (para --desde tras un corte) y semillas
    distintas producen parametros distintos (sobreviven el dedupe).
    Cada item: dict(indice, nombre, tarea, verificar, setup, resp_esperada)."""
    tareas = []
    for i in range(desde, desde + n):
        rng = random.Random(f"banco-{semilla}-{i}")
        plantilla = PLANTILLAS[i % len(PLANTILLAS)]
        t = plantilla(rng)
        nombre, tarea, verificar, setup = t[0], t[1], t[2], t[3]
        resp_esperada = t[4] if len(t) > 4 else ""
        tareas.append({"indice": i, "nombre": nombre, "tarea": tarea,
                       "verificar": verificar, "setup": setup,
                       "resp_esperada": resp_esperada})
    return tareas


def prechequeo_interprete(run_fn=None, which_fn=None):
    """(ok, motivo). Ejecuta 'python -c' DESDE un workspace temporal, como lo
    vera la tool ``ejecutar``. Aborta si 'python' resuelve al alias de
    Microsoft Store o si el comando no imprime (exit 9009 y parientes).
    run_fn/which_fn inyectables para testear sin tocar el sistema."""
    import shutil
    import subprocess
    run_fn = run_fn or subprocess.run
    which_fn = which_fn or shutil.which
    ruta = which_fn("python") or ""
    if "WindowsApps" in ruta:
        return False, ("'python' resuelve al alias de Microsoft Store "
                       f"({ruta}): las tareas fallarian con exit 9009. "
                       "Desactivar el alias o anteponer un python real al PATH.")
    ws = tempfile.mkdtemp(prefix="banco_pre_")
    try:
        r = run_fn(["python", "-c", "print(40+2)"], capture_output=True,
                   text=True, timeout=30, cwd=ws)
    except Exception as exc:
        return False, f"no se pudo ejecutar 'python' desde el sandbox: {exc}"
    rc = getattr(r, "returncode", 1)
    salida = getattr(r, "stdout", "") or ""
    if rc != 0 or "42" not in salida:
        return False, (f"'python -c' devolvio exit {rc} con salida "
                       f"{salida[:60]!r}: el sandbox no tiene interprete sano")
    return True, ruta or "python"


def _sellar_nuevas(previas: set, ok: bool):
    """Sella los volcados NUEVOS del dir de trazas. El hook del loop publica
    ctx['_traza_task_id'] recien en la ola 2; leer el diff del directorio es
    la alternativa sancionada por el plan y no depende del orden de llegada."""
    from cognia.agent import traza_chatml
    nuevos = {p.name for p in traza_chatml.dir_trazas().glob("*.json")} - previas
    ids = set()
    for nombre in nuevos:
        # <task_id>-cNN.json -> task_id
        ids.add(re.sub(r"-c\d\d$", "", Path(nombre).stem))
    sellados = []
    for tid in sorted(ids):
        if traza_chatml.sellar(tid, {"verificar_ws": bool(ok),
                                     "banco": "banco_trazas"}):
            sellados.append(tid)
    return sellados, nuevos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="banco de tareas para trazas")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--desde", type=int, default=0)
    ap.add_argument("--pasos", type=int, default=6)
    args = ap.parse_args(argv)

    ok_pre, motivo = prechequeo_interprete()
    if not ok_pre:
        print(f"[banco_trazas] ABORTADO por pre-chequeo: {motivo}",
              file=sys.stderr)
        return 2

    os.environ["COGNIA_TRAZAS"] = "1"   # sin trazas el banco no tiene sentido

    # Arranque identico a scripts/e2e_happy_path.py (patron probado del gate).
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from cognia.agent import traza_chatml
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    def hacer(tarea, verificar, setup, pasos):
        ws = Path(tempfile.mkdtemp(prefix="banco_")).resolve()
        if setup:
            setup(ws)
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: None,
                                        max_steps=pasos)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        try:
            return verificar(ws), (str(resp) or "")[:120]
        except Exception as exc:
            return False, f"verify exc: {exc}"

    tareas = generar_tareas(args.n, args.semilla, args.desde)
    t0 = time.time()
    oks = 0
    for t in tareas:
        previas = {p.name for p in traza_chatml.dir_trazas().glob("*.json")}
        t1 = time.time()
        ok, resp = hacer(t["tarea"], t["verificar"], t["setup"], args.pasos)
        if t["resp_esperada"]:
            ok = t["resp_esperada"] in resp
        sellados, nuevos = _sellar_nuevas(previas, ok)
        oks += 1 if ok else 0
        print(f"  [{'OK ' if ok else 'FAIL'}] #{t['indice']:03d} "
              f"{t['nombre']} ({time.time()-t1:.0f}s) "
              f"trazas={len(nuevos)} sellados={sellados}", flush=True)
        if not nuevos:
            # Sin traza no hay ejemplo: se dice fuerte (flag apagado, volcado
            # fallido o hook ausente), jamas se degrada en silencio.
            print("       AVISO: la corrida no dejo traza en "
                  f"{traza_chatml.dir_trazas()}", flush=True)

    print(f"\nBANCO TRAZAS: {oks}/{len(tareas)} verificadas OK en "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    try:
        if getattr(orch, "_llama", None) is not None:
            orch._llama.stop()    # solo el server que arranco ESTE script
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
