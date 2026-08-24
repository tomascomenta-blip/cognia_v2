# -*- coding: utf-8 -*-
"""Puerta REAL del banner animado (P7 del sistema de estilos por elemento):
el REPL de verdad contra el backend activo, bajo una ConPTY (pywinpty, la
misma ruta que Windows Terminal), 120x40, COLORTERM=truecolor, con un
~/.cognia/estilo.json TEMPORAL que enciende banner.arte.animacion
(solo_al_llegar) + glow y renombra el titulo a 'JARVIS'. Tres brazos:

    anim      ConPTY 120x40 -> se esperan >= 2 cuadros de BARRIDO distintos
              (repintados entre cursor-up en los que alguna linea del arte
              lleva >= 2 colores truecolor distintos y cuyo arte cambia
              respecto del cuadro anterior), el frame final QUIETO (el ultimo
              cuadro antes de la linea del modelo lleva el arte y despues de
              ella el arte no se repinta; los cursor-up posteriores son de
              prompt_toolkit dibujando el prompt) y el titulo 'JARVIS' en ese
              frame final.
    pipe      echo /salir | python -m cognia, mismo estilo.json -> 0 cursor-up,
              0 Live (0 escondidas de cursor), el banner estatico con JARVIS.
    cotidiano el estilo.json del DUENO (restaurado: default del banner) bajo
              ConPTY: 2 tareas cotidianas tecleadas contra el 27B; el banner
              sale intacto (titulo COGNIA, 0 barridos) y se guardan las
              respuestas limpias para pegarlas en el commit.

El estilo.json (y su .bak) del dueno se guardan antes y se restauran al
final, byte a byte, pase lo que pase.

Mientras cli.py no cargue el fichero al arrancar (gancho de P4, rama
estilos/cli), el REPL se lanza por _LANZADOR: A.cargar() + A.conectar_glow()
y luego runpy.run_module('cognia'). Con el gancho en cli.py el lanzador
sobra (cargar dos veces el mismo fichero no cambia nada).

Uso:
    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\banner_gate_conpty.py [anim] [pipe] [cotidiano]
    (por defecto corre los tres, en ese orden)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
ESTILO = os.path.join(os.path.expanduser("~"), ".cognia", "estilo.json")
BAK = ESTILO + ".bak"
GUARDA = os.path.join(RAIZ, ".banner_gate_estilo_dueno")
ENTER = "\r"
TAREAS = [
    "en una frase: que es un semaforo en programacion concurrente? responde sin usar herramientas",
    "que hay en el fichero README.md de este repo? resumilo en una linea",
]

_LANZADOR = """
import os, runpy, sys
RAIZ = sys.argv[1]
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)
import cognia
assert cognia.__file__.lower().startswith(RAIZ.lower()), cognia.__file__
from cognia.ux import aspecto as A
doc = A.cargar()
A.conectar_glow()
sys.stderr.write("[gate] estilo cargado: %s\\n" % sorted((doc.get("elementos") or {}).keys()))
sys.argv = ["cognia"]
runpy.run_module("cognia", run_name="__main__", alter_sys=True)
"""

BRAILLE = re.compile("[⠁-⣿]")
CURSOR_UP = re.compile(r"\x1b\[\d*A")
TRUECOLOR = re.compile(r"38;2;\d+;\d+;\d+")


def _limpio(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s)


def guardar_dueno() -> None:
    os.makedirs(GUARDA, exist_ok=True)
    for f in (ESTILO, BAK):
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(GUARDA, os.path.basename(f)))


def restaurar_dueno() -> None:
    for nombre in ("estilo.json", "estilo.json.bak"):
        destino = os.path.join(os.path.dirname(ESTILO), nombre)
        origen = os.path.join(GUARDA, nombre)
        if os.path.exists(origen):
            shutil.copy2(origen, destino)
        elif os.path.exists(destino):
            os.remove(destino)


def bytes_dueno() -> dict:
    return {f: (open(f, "rb").read() if os.path.exists(f) else None) for f in (ESTILO, BAK)}


def escribir_temporal() -> None:
    doc = {"version": 1, "nombre": "gate-p7",
           "elementos": {
               "banner.arte": {"animacion": {"activa": True, "solo_al_llegar": True,
                                             "velocidad": 2},
                               "glow": {"intensidad": 2}},
               "banner.marco": {"texto": {"titulo": "JARVIS"}}}}
    os.makedirs(os.path.dirname(ESTILO), exist_ok=True)
    with open(ESTILO, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def _env() -> dict:
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("COGNIA_"):
            env.pop(k)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "TERM": "xterm-256color",
                "COLORTERM": "truecolor", "PYTHONPATH": RAIZ})
    env.pop("NO_COLOR", None)
    return env


def correr_conpty(brazo: str, salida_dir: str, lineas: list) -> str:
    """Arranca el REPL bajo ConPTY 120x40, espera el prompt, teclea `lineas`
    (esperando quietud tras cada una) y devuelve la captura cruda."""
    from winpty import PtyProcess
    proc = PtyProcess.spawn([PY, "-c", _LANZADOR, RAIZ], cwd=RAIZ, env=_env(),
                            dimensions=(40, 120))
    buf, ultimo = [], [time.time()]

    def lector():
        while True:
            try:
                d = proc.read(4096)
            except Exception:
                break
            if not d:
                if not proc.isalive():
                    break
                time.sleep(0.05)
                continue
            buf.append(d)
            ultimo[0] = time.time()
    threading.Thread(target=lector, daemon=True).start()

    def esperar_quieto(quieto=10.0, maximo=300.0):
        t0 = time.time()
        while time.time() - t0 < maximo:
            if time.time() - ultimo[0] > quieto and buf:
                return True
            if not proc.isalive():
                return False
            time.sleep(0.5)
        return False

    esperar_quieto(quieto=12.0, maximo=180.0)
    buf.append("\n<<<PROMPT LISTO>>>\n")
    for l in lineas:
        print(f"[{brazo} {time.strftime('%H:%M:%S')}] tecleo: {l}", flush=True)
        buf.append(f"\n<<<TECLEADO {l}>>>\n")
        proc.write(l + ENTER)
        time.sleep(2.0)
        if not l.startswith("/"):
            # el selector de /mejorar ('Enviar el prompt, o mejorarlo con IA?'):
            # Enter = 'Enviar tal cual', como en scripts/spinner_gate_conpty.py
            proc.write(ENTER)
            time.sleep(1.0)
        ok = esperar_quieto()
        print(f"[{brazo} {time.strftime('%H:%M:%S')}] quieto={ok} vivo={proc.isalive()}",
              flush=True)
        if not proc.isalive():
            break
    time.sleep(2)
    if proc.isalive():
        proc.terminate(True)
    raw = "".join(buf)
    ruta = os.path.join(salida_dir, f"banner_gate_{brazo}.raw.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(raw)
    return raw


def medir_anim(raw: str, brazo: str) -> dict:
    """Ventana: desde el arranque hasta el prompt. Cuadros = trozos entre
    cursor-up; un cuadro de barrido tiene alguna linea de arte con >= 2
    colores truecolor DISTINTOS y un arte distinto del cuadro anterior."""
    fin = raw.find("<<<PROMPT LISTO>>>")
    ventana = raw[:fin if fin > 0 else None]
    cuadros = CURSOR_UP.split(ventana)
    arte_previo, barridos, con_dos_colores = None, 0, 0
    for c in cuadros:
        lineas_arte = [l for l in c.split("\n") if BRAILLE.search(l)]
        if not lineas_arte:
            continue
        # solo los colores DENTRO del arte (entre el primer y el ultimo
        # caracter Braille de la linea): a 120 columnas la guia comparte la
        # fila con el gato y el borde '│' del panel va delante con su propio
        # color -- cazado en las dos primeras medidas: el brazo por defecto
        # daba 1 'barrido' por la guia y luego por el borde. Un tono plano por
        # linea (default) deja 0 escapes dentro del arte; glow/barrido, varios.
        colores = max(len(set(TRUECOLOR.findall(_dentro_del_arte(l)))) for l in lineas_arte)
        arte = "\n".join(lineas_arte)
        if colores >= 2:
            con_dos_colores += 1
            if arte != arte_previo:
                barridos += 1
        arte_previo = arte
    # 'quieto': la linea del modelo se imprime DESPUES de que el banner
    # termina; el ultimo cuadro antes de ella tiene que ser el frame estatico
    # (con arte) y despues de ella el arte no se repinta nunca mas. Los
    # cursor-up posteriores son de prompt_toolkit dibujando prompt + barra
    # (ESC[10A, medido): se informan aparte, no cuentan como banner.
    i_modelo = ventana.find("modo ")
    antes = ventana[:i_modelo] if i_modelo > 0 else ventana
    despues = ventana[i_modelo:] if i_modelo > 0 else ""
    ultimo = CURSOR_UP.split(antes)[-1]
    limpio_final = _limpio(ultimo)
    limpio = _limpio(ventana)
    return {"brazo": brazo, "bytes": len(raw), "ventana_bytes": len(ventana),
            "cursor_up": len(CURSOR_UP.findall(ventana)),
            "cuadros_con_arte": sum(1 for c in cuadros if BRAILLE.search(c)),
            "cuadros_con_2_colores_en_el_arte": con_dos_colores,
            "cuadros_barrido_distintos": barridos,
            "frame_final_con_arte": bool(BRAILLE.search(ultimo)),
            "arte_repintado_tras_linea_modelo": bool(BRAILLE.search(despues)),
            "cursor_up_tras_linea_modelo_prompt_toolkit": len(CURSOR_UP.findall(despues)),
            "titulo_jarvis_en_frame_final": "JARVIS" in limpio_final,
            "titulo_jarvis": "JARVIS" in limpio, "titulo_cognia": " COGNIA v" in limpio,
            "escondidas_cursor": ventana.count("\x1b[?25l")}


def _dentro_del_arte(linea: str) -> str:
    posiciones = [m.start() for m in BRAILLE.finditer(linea)]
    return linea[posiciones[0]:posiciones[-1] + 1]


def correr_pipe(salida_dir: str) -> dict:
    out = subprocess.run([PY, "-c", _LANZADOR, RAIZ], input="/salir\n", capture_output=True,
                         text=True, encoding="utf-8", errors="replace", cwd=RAIZ, env=_env(),
                         timeout=180)
    raw = out.stdout
    ruta = os.path.join(salida_dir, "banner_gate_pipe.raw.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(raw + "\n<<<STDERR>>>\n" + out.stderr)
    limpio = _limpio(raw)
    return {"brazo": "pipe", "rc": out.returncode, "bytes": len(raw),
            "cursor_up": len(CURSOR_UP.findall(raw)), "escondidas_cursor": raw.count("\x1b[?25l"),
            "38;2;": raw.count("38;2;"), "lineas_arte": sum(1 for l in limpio.splitlines()
                                                             if BRAILLE.search(l)),
            "titulo_jarvis": "JARVIS" in limpio, "captura": ruta}


def medir_cotidiano(raw: str, salida_dir: str) -> dict:
    m = medir_anim(raw, "cotidiano")
    limpio = _limpio(raw)
    respuestas = []
    for t in TAREAS:
        i = limpio.find(f"<<<TECLEADO {t}>>>")
        if i < 0:
            respuestas.append("")
            continue
        j = limpio.find("<<<TECLEADO", i + 10)
        trozo = limpio[i:j if j > 0 else None]
        # sin repintados del spinner ni de la cola viva del markdown (una
        # linea que es PREFIJO de otra posterior era un repintado parcial)
        lineas = [l.rstrip() for l in trozo.splitlines()]
        lineas = [l for l in lineas if l.strip() and "ctrl+c corta" not in l
                  and not l.lstrip().startswith(("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"))]
        finales = []
        for k, l in enumerate(lineas):
            if len(l.strip()) > 8 and any(m.startswith(l) for m in lineas[k + 1:]):
                continue        # repintado parcial o repetido: queda el ultimo
            finales.append(l)
        respuestas.append("\n".join(finales[-25:]))
    with open(os.path.join(salida_dir, "banner_gate_cotidiano.limpio.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n\n".join(respuestas))
    m.update({"respuestas_no_vacias": sum(1 for r in respuestas if r.strip()),
              "respuestas": respuestas})
    return m


def main() -> int:
    brazos = [a for a in sys.argv[1:] if a in ("anim", "pipe", "cotidiano")] or ["anim", "pipe", "cotidiano"]
    salida_dir = os.environ.get("BANNER_GATE_DIR") or os.path.join(RAIZ, "logs")
    os.makedirs(salida_dir, exist_ok=True)
    guardar_dueno()
    antes = bytes_dueno()
    resultados = []
    try:
        if "anim" in brazos or "pipe" in brazos:
            escribir_temporal()
        if "anim" in brazos:
            raw = correr_conpty("anim", salida_dir, ["/salir"])
            resultados.append(medir_anim(raw, "anim"))
        if "pipe" in brazos:
            resultados.append(correr_pipe(salida_dir))
        if "cotidiano" in brazos:
            restaurar_dueno()          # el default del dueno: banner intacto
            raw = correr_conpty("cotidiano", salida_dir, TAREAS + ["/salir"])
            resultados.append(medir_cotidiano(raw, salida_dir))
    finally:
        restaurar_dueno()
        despues = bytes_dueno()
        print("[gate] estilo.json del dueno restaurado byte a byte:", antes == despues)
        shutil.rmtree(GUARDA, ignore_errors=True)
    ok = True
    for r in resultados:
        print(json.dumps({k: v for k, v in r.items() if k != "respuestas"}, ensure_ascii=False))
        if r["brazo"] == "anim":
            ok &= (r["cuadros_barrido_distintos"] >= 2 and r["frame_final_con_arte"]
                   and not r["arte_repintado_tras_linea_modelo"]
                   and r["titulo_jarvis_en_frame_final"])
        elif r["brazo"] == "pipe":
            ok &= (r["cursor_up"] == 0 and r["escondidas_cursor"] == 0 and r["lineas_arte"] > 20
                   and r["titulo_jarvis"])
        elif r["brazo"] == "cotidiano":
            ok &= (r["titulo_cognia"] and not r["titulo_jarvis"] and r["cuadros_barrido_distintos"] == 0
                   and r["respuestas_no_vacias"] == len(TAREAS))
            for t, resp in zip(TAREAS, r["respuestas"]):
                print(f"--- {t}\n{resp}\n")
    print("PUERTA:", "PASA" if ok else "NO PASA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
