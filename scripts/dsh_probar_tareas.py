# -*- coding: utf-8 -*-
"""
dsh_probar_tareas.py — arnes de pruebas HUMANAS del CLI, con captura de pantalla.

POR QUE EXISTE (2026-08-18, pedido del dueno): el gate e2e mide si la tarea se
CUMPLE, y eso deja fuera la mitad del producto. Un CLI puede cumplir 5/5 y ser
un desastre de usar: logs mezclados con la interfaz, spinners huerfanos, texto
que se corta, respuestas crudas sin formato. Esto prueba tareas como las pide
un humano de verdad ("hazme una pagina html", "abre una pestana con...") y
guarda una CAPTURA de la pantalla para poder juzgar lo VISUAL, no solo el
resultado.

Cada tarea produce:
  tareas/<id>/pantalla_NN.png   capturas durante la corrida (la ventana real)
  tareas/<id>/salida.txt        todo lo que el CLI escribio (con ANSI crudo)
  tareas/<id>/veredicto.json    tiempo, exit code, postcondicion en DISCO

La postcondicion se comprueba en DISCO, nunca contra lo que diga el modelo:
un CLI que responde "listo" sin tocar nada tiene que FALLAR aqui.

Uso:
    python scripts/dsh_probar_tareas.py --listar
    python scripts/dsh_probar_tareas.py --tarea html_simple
    python scripts/dsh_probar_tareas.py --todas --salida C:/ruta/resultados

Solo stdlib + mss/PIL para la captura (opcionales: sin ellas corre igual y
avisa de que no hay capturas).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = RAIZ / "venv312" / "Scripts" / "python.exe"


# ── Catalogo de tareas HUMANAS ────────────────────────────────────────────────
# Cada tarea es lo que escribiria una persona, no un prompt de benchmark. La
# postcondicion mira el DISCO (o el proceso), nunca el texto de la respuesta.

def _hay_html(ws: Path) -> tuple:
    for f in ws.rglob("*.html"):
        t = f.read_text(encoding="utf-8", errors="replace")
        if "<html" in t.lower() and len(t) > 120:
            return True, f"{f.name} ({len(t)} chars)"
    return False, "no hay ningun .html con contenido"


def _hay_css_o_estilo(ws: Path) -> tuple:
    for f in ws.rglob("*.html"):
        t = f.read_text(encoding="utf-8", errors="replace").lower()
        if "<style" in t or "stylesheet" in t:
            return True, f"{f.name} lleva estilos"
    for f in ws.rglob("*.css"):
        return True, f.name
    return False, "no hay estilos"


def _fichero_editado(ws: Path) -> tuple:
    f = ws / "notas.txt"
    if not f.is_file():
        return False, "notas.txt no existe"
    t = f.read_text(encoding="utf-8", errors="replace")
    if "jueves" in t.lower():
        return True, repr(t[:80])
    return False, f"notas.txt no menciona el cambio: {t[:80]!r}"


def _json_valido(ws: Path) -> tuple:
    for f in ws.rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"{f.name} no es JSON valido: {exc}"
        if isinstance(d, list) and len(d) >= 3:
            return True, f"{f.name} con {len(d)} elementos"
        if isinstance(d, dict) and d:
            return True, f"{f.name} con {len(d)} claves"
    return False, "no hay .json"


def _script_que_corre(ws: Path) -> tuple:
    for f in ws.rglob("*.py"):
        try:
            r = subprocess.run([sys.executable, str(f)], capture_output=True,
                               text=True, timeout=30, cwd=ws)
        except Exception as exc:
            return False, f"{f.name} no se pudo ejecutar: {exc}"
        if r.returncode == 0 and r.stdout.strip():
            return True, f"{f.name} imprime {r.stdout.strip()[:60]!r}"
    return False, "no hay .py que corra y escriba algo"


def _pidio_contexto(ws: Path, salida: str = "") -> tuple:
    """Ante una peticion sin sujeto, el ACIERTO es preguntar, no inventar.

    La primera version de esta postcondicion exigia "que quede algo escrito", y
    penalizaba justo lo correcto: en la corrida del 2026-08-18 el agente miro el
    workspace (ls + find), busco en memoria episodica y contesto "arregla esto
    no tiene objeto; dame la ruta, el error o el comportamiento esperado". Eso
    es lo que hace un buen harness, y mi banco lo marcaba como fallo. El test
    estaba midiendo lo que era facil de medir, no lo que importaba.
    """
    texto = (salida or "").lower()
    señales = ("necesito", "que archivo", "cual", "cuál", "no tiene objeto",
               "dame", "especifica", "mensaje de error", "ruta del archivo")
    if any(s in texto for s in señales) and "?" in texto:
        return True, "pidio contexto en vez de inventar"
    hijos = [p for p in ws.rglob("*") if p.is_file()]
    if hijos:
        return False, ("invento un arreglo sin preguntar: "
                       + ", ".join(p.name for p in hijos[:5]))
    return False, "ni pregunto ni hizo nada"


TAREAS = {
    "html_simple": {
        "pide": "hazme una pagina web sencilla que salude, guardala como index.html",
        "post": _hay_html,
        "por_que": "lo primero que pide cualquiera; toca escritura de fichero",
    },
    "html_bonito": {
        "pide": ("hazme una landing page bonita para una cafeteria, con colores "
                 "calidos y un boton de contacto, en un solo archivo html"),
        "post": _hay_css_o_estilo,
        "por_que": "salida larga: revela si el CLI corta el codigo o lo pinta mal",
    },
    "editar_fichero": {
        "pide": "en notas.txt cambia la reunion del martes al jueves",
        "prepara": lambda ws: (ws / "notas.txt").write_text(
            "Pendientes:\n- reunion el martes a las 10\n- comprar cafe\n",
            encoding="utf-8"),
        "post": _fichero_editado,
        "por_que": "editar > crear: el harness tiene que LEER antes de escribir",
    },
    "json_datos": {
        "pide": "creame un json con tres peliculas y su ano y director",
        "post": _json_valido,
        "por_que": "estructura: revela si el modelo escribe json valido a disco",
    },
    "script_util": {
        "pide": ("escribeme un script python que cuente cuantas palabras hay en "
                 "notas.txt y lo ejecute"),
        "prepara": lambda ws: (ws / "notas.txt").write_text(
            "hola mundo esto es una prueba\ncon dos lineas\n", encoding="utf-8"),
        "post": _script_que_corre,
        "por_que": "pide EJECUTAR, no solo escribir: prueba la tool de comandos",
    },
    "pregunta_ambigua": {
        "pide": "arregla esto",
        "post": _pidio_contexto,
        "usa_salida": True,
        "espera_pregunta": True,
        "por_que": ("un buen harness PREGUNTA en vez de inventar. Aqui lo que se "
                    "evalua es si pide contexto o si se lanza a adivinar"),
    },
}


# ── Captura de pantalla ───────────────────────────────────────────────────────

def capturar(destino: Path) -> bool:
    """PNG de la pantalla completa. False si no hay backend de captura."""
    try:
        import mss
        from PIL import Image
    except Exception:
        return False
    try:
        with mss.mss() as sct:
            m = sct.monitors[1]
            img = sct.grab(m)
            Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX").save(destino)
        return True
    except Exception:
        return False


def rasterizar(ansi: Path, destino: Path) -> bool:
    """Rasteriza la salida ANSI REAL del comando a PNG.

    POR QUE ASI y no capturando la ventana: la pantalla del escritorio muestra
    lo que haya delante, y el comando corre sin ventana propia. Aca se rasteriza
    exactamente lo que el proceso escribio -- ni un byte mas -- asi que el PNG
    no puede mostrar algo que el CLI no imprimio. Ademas es reproducible sin
    tocar el escritorio del usuario.
    """
    try:
        r = subprocess.run(
            [str(PY) if PY.is_file() else sys.executable,
             str(RAIZ / "scripts" / "captura_terminal_png.py"),
             "--salida", str(destino), "--ansi", str(ansi)],
            capture_output=True, text=True, timeout=300)
        return destino.is_file() and r.returncode == 0
    except Exception:
        return False


# ── Corrida de una tarea ──────────────────────────────────────────────────────

def corre_tarea(nombre: str, dst: Path, timeout: int, capturas: bool) -> dict:
    spec = TAREAS[nombre]
    caso = dst / nombre
    ws = caso / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    if spec.get("prepara"):
        spec["prepara"](ws)

    # El CLI en modo tarea, con el workspace como cwd. stdin cerrado: si el CLI
    # se queda esperando input, el timeout lo caza y ESO es un hallazgo.
    cmd = [str(PY) if PY.is_file() else sys.executable, "-u", "-m", "cognia",
           "hacer", spec["pide"]]
    # COGNIA_EFIMERO: `cognia hacer` con Cognia real guardaba el episodio
    # "agente_tarea_completada" en la memoria del dueno por cada tarea del
    # banco (2026-08-25). Efimero: la corrida no deja rastro.
    env = dict(os.environ, COGNIA_EFIMERO="1",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               FORCE_COLOR="1", TERM="xterm-256color", COLUMNS="100",
               COGNIA_SPINNER=os.environ.get("COGNIA_SPINNER", "1"))
    env.pop("NO_COLOR", None)

    salida = []
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=ws, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1)

    def bombea():
        for linea in proc.stdout:
            salida.append(linea)

    hilo = threading.Thread(target=bombea, daemon=True)
    hilo.start()

    disparos = 0
    while proc.poll() is None and time.time() - t0 < timeout:
        if capturas and time.time() - t0 > disparos * 20:
            capturar(caso / f"pantalla_{disparos:02d}.png")
            disparos += 1
        time.sleep(1)

    expiro = proc.poll() is None
    if expiro:
        proc.kill()
    hilo.join(timeout=5)
    if capturas:
        capturar(caso / "pantalla_final.png")

    texto = "".join(salida)
    ruta_ansi = caso / "salida.txt"
    ruta_ansi.write_text(texto, encoding="utf-8")
    png = rasterizar(ruta_ansi, caso / "salida.png") if texto.strip() else False

    if spec.get("usa_salida"):
        ok, detalle = spec["post"](ws, texto)
    else:
        ok, detalle = spec["post"](ws)
    veredicto = {
        "tarea": nombre,
        "pide": spec["pide"],
        "por_que": spec["por_que"],
        "segundos": round(time.time() - t0, 1),
        "expiro": expiro,
        "exit": proc.returncode,
        "postcondicion_ok": ok,
        "postcondicion": detalle,
        "chars_salida": len(texto),
        "lineas_salida": texto.count("\n"),
        "capturas": disparos + (1 if capturas else 0),
        "png_salida": bool(png),
    }
    (caso / "veredicto.json").write_text(
        json.dumps(veredicto, indent=2, ensure_ascii=False), encoding="utf-8")
    return veredicto


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tarea", action="append", help="nombre de tarea (repetible)")
    ap.add_argument("--todas", action="store_true")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--salida", default=str(RAIZ / "dsh_pruebas"))
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--sin-capturas", action="store_true")
    args = ap.parse_args()

    if args.listar:
        print(f"{'tarea':<20} que se le pide")
        for k, v in TAREAS.items():
            print(f"  {k:<18} {v['pide']}")
            print(f"  {'':<18} -> {v['por_que']}")
        return 0

    elegidas = list(TAREAS) if args.todas else (args.tarea or [])
    if not elegidas:
        print("nada que correr: usa --tarea NOMBRE o --todas", file=sys.stderr)
        return 2
    malas = [t for t in elegidas if t not in TAREAS]
    if malas:
        print(f"tareas desconocidas: {malas}", file=sys.stderr)
        return 2

    dst = Path(args.salida)
    dst.mkdir(parents=True, exist_ok=True)
    filas = []
    for nombre in elegidas:
        print(f"\n=== {nombre} ===", flush=True)
        v = corre_tarea(nombre, dst, args.timeout, not args.sin_capturas)
        filas.append(v)
        print(f"  {'OK ' if v['postcondicion_ok'] else 'NO '} "
              f"{v['segundos']}s  exit={v['exit']}  "
              f"{'EXPIRO  ' if v['expiro'] else ''}{v['postcondicion']}",
              flush=True)
        (dst / "resumen.json").write_text(
            json.dumps(filas, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for f in filas if f["postcondicion_ok"])
    print(f"\nDSH TAREAS HUMANAS: {ok}/{len(filas)} con postcondicion cumplida")
    print(f"evidencia en {dst}")
    return 0 if ok == len(filas) else 1


if __name__ == "__main__":
    sys.exit(main())
