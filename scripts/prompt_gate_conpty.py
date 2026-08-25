# Puerta REAL del PULSO del prompt (P9) en ConPTY 100x30 (pywinpty).
#
# Con un ~/.cognia/estilo.json TEMPORAL {prompt.etiqueta: animacion activa +
# glow 2} arranca `python -m cognia` en una pseudoconsola, espera el prompt y:
#   1. cuenta los CUADROS del prompt (redibujados de la linea que lleva la
#      etiqueta) que traen >= 2 colores truecolor distintos durante los
#      primeros ~2,5 s (el pulso dura min(3 s, duracion del elemento));
#   2. comprueba que despues el prompt queda QUIETO (0 bytes nuevos en 2 s:
#      el hilo del pulso murio solo y refresh_interval no se toco, E3);
#   3. mide con psutil el % de CPU del proceso del REPL durante el pulso y
#      durante el reposo posterior (tiene que caer a ~0 %);
#   4. teclea /salir y comprueba que sale.
# Guarda y restaura el estilo.json (y .bak) del dueno byte a byte.
#
# Uso: PYTHONUTF8=1 venv312\Scripts\python.exe scripts\prompt_gate_conpty.py
import json
import os
import re
import sys
import threading
import time

import psutil
from winpty import PtyProcess

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
AQUI = os.environ.get("ESTILO_GATE_DIR") or os.path.join(RAIZ, "logs")
os.makedirs(AQUI, exist_ok=True)
OUT = os.path.join(AQUI, "gate_prompt_pulso_raw.txt")
CASA = os.path.join(os.path.expanduser("~"), ".cognia")
EST = os.path.join(CASA, "estilo.json")
BAK = EST + ".bak"
ETIQUETA = "pulso"     # etiqueta distinta de 'cognia' para encontrar la linea del prompt

copia = {p: (open(p, "rb").read() if os.path.exists(p) else None) for p in (EST, BAK)}


CONTROL = "--control" in sys.argv     # brazo de CONTROL: misma etiqueta, sin animacion


def escribir_temporal() -> None:
    os.makedirs(CASA, exist_ok=True)
    doc = {"version": 1, "elementos": {
        "prompt.etiqueta": {"texto": ETIQUETA, "glow": {"intensidad": 2},
                            "animacion": {"activa": not CONTROL, "tipo": "barrido",
                                          "velocidad": 2, "ancho": 5}}}}
    with open(EST, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def restaurar_dueno() -> None:
    for p, c in copia.items():
        if c is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            open(p, "wb").write(c)


def _env() -> dict:
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("COGNIA_"):
            env.pop(k)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "TERM": "xterm-256color",
                "COLORTERM": "truecolor", "PYTHONPATH": RAIZ, "COGNIA_SPINNER": "0",
                "COGNIA_EFIMERO": "1"})  # gate sin rastro en la memoria del dueno (2026-08-25)
    env.pop("NO_COLOR", None)
    return env


RE_ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
RE_TC = re.compile(r"38;2;\d+;\d+;\d+")


def cuadros_del_prompt(tramo: str) -> list:
    """Cada redibujado de la linea del prompt: prompt_toolkit repinta SOLO
    las celdas que cambian, con un escape de color por caracter (en el crudo
    la etiqueta sale como 'p<esc>u<esc>l...'), asi que un cuadro es el tramo
    entre dos flechas que toca alguna letra de la etiqueta; se guarda el
    conjunto de truecolors que pinta."""
    cuadros = []
    # un ciclo de render de prompt_toolkit va entre 'esconder cursor'
    # (\x1b[?25l) y 'mostrar cursor' (\x1b[?25h); los ciclos sin celdas que
    # repintar quedan vacios y no cuentan
    for seg in tramo.split("\x1b[?25l")[1:]:
        seg = seg.split("\x1b[?25h")[0]
        if not any(ch in RE_ESC.sub("", seg) for ch in ETIQUETA):
            continue
        cuadros.append(sorted(set(RE_TC.findall(seg))))
    return cuadros


def main() -> int:
    escribir_temporal()
    res = {}
    buf = []
    ultimo = [time.time()]
    proc = None
    try:
        proc = PtyProcess.spawn([PY, "-m", "cognia"], cwd=RAIZ, env=_env(), dimensions=(30, 100))
        ps = psutil.Process(proc.pid)

        def lector():
            while True:
                try:
                    d = proc.read(4096)
                except Exception:
                    break
                if not d:
                    if not proc.isalive():
                        break
                    time.sleep(0.02)
                    continue
                buf.append(d)
                ultimo[0] = time.time()

        threading.Thread(target=lector, daemon=True).start()

        def cap():
            return "".join(buf)

        def esperar(marca, t=90.0):
            # sobre el texto SIN escapes: la etiqueta viaja con un color por
            # caracter y 'pulso➤' nunca es contiguo en el crudo
            fin = time.time() + t
            while time.time() < fin:
                if marca in RE_ESC.sub("", cap()):
                    return True
                time.sleep(0.05)
            return False

        # 1. el prompt aparece (la etiqueta temporal seguida de la flecha)
        res["prompt"] = esperar(ETIQUETA + "➤", 120)
        t_prompt = time.time()
        n0 = cap().rfind(ETIQUETA) - 200
        n0 = max(0, n0)
        # el pid del PtyProcess puede ser el agente de la pseudoconsola: se
        # mide el python.exe que corre `-m cognia` (el mismo o un hijo)
        # (el python.exe del venv es un LANZADOR que ejecuta el interprete
        # real como hijo: se toma el candidato mas profundo, no el primero)
        candidatos = [ps] + ps.children(recursive=True)
        for c in candidatos:
            try:
                if "cognia" in " ".join(c.cmdline()) and "python" in c.name().lower():
                    ps = c
            except (psutil.Error, OSError):
                continue
        res["pid_medido"] = ps.pid
        res["proceso_medido"] = ps.name()
        # 2. durante el pulso: cuadros + CPU (% de UN nucleo, intervalo bloqueante
        # de 2,5 s: el lector sigue leyendo en su hilo)
        res["cpu_pulso_pct_1core"] = round(ps.cpu_percent(interval=2.5), 2)
        res["cpu_pulso_pct"] = round(res["cpu_pulso_pct_1core"] / max(1, psutil.cpu_count()), 2)
        tramo_pulso = cap()[n0:]
        cuadros = cuadros_del_prompt(tramo_pulso)
        res["cuadros_prompt"] = len(cuadros)
        res["cuadros_con_2_truecolor"] = sum(1 for c in cuadros if len(c) >= 2)
        res["cuadros_distintos"] = len({tuple(c) for c in cuadros})
        # 3. reposo: 0 bytes nuevos en 2 s y CPU ~0
        time.sleep(1.5)                      # margen hasta los 3 s de tope
        n1 = len(cap())
        res["cpu_reposo_pct_1core"] = round(ps.cpu_percent(interval=2.0), 2)
        res["cpu_reposo_pct"] = round(res["cpu_reposo_pct_1core"] / max(1, psutil.cpu_count()), 2)
        res["bytes_nuevos_en_reposo"] = len(cap()) - n1
        res["quieto"] = res["bytes_nuevos_en_reposo"] == 0
        res["hilos_reposo"] = ps.num_threads()
        # segunda ventana de reposo (t+8..10 s): el arranque del REPL (warm-up,
        # monitores, continuidad) sigue trabajando unos segundos despues del
        # primer prompt; el brazo --control separa ese coste del pulso
        time.sleep(2.0)
        n2 = len(cap())
        res["cpu_reposo2_pct_1core"] = round(ps.cpu_percent(interval=2.0), 2)
        res["bytes_nuevos_en_reposo2"] = len(cap()) - n2
        res["s_desde_prompt"] = round(time.time() - t_prompt, 1)
        # 3b. la medida LIMPIA del pulso: con el arranque ya asentado (t+25 s)
        # se abre un SEGUNDO prompt (Enter en vacio) y se mide la CPU del
        # proceso en tres ventanas apareadas: base (antes), pulso (2,5 s
        # desde el Enter) y tras el pulso (2 s desde t+4 s). El brazo
        # --control abre el mismo prompt sin animacion.
        while time.time() - t_prompt < 25.0:
            time.sleep(0.2)
        res["cpu_base2_pct_1core"] = round(ps.cpu_percent(interval=2.0), 2)
        n3 = len(cap())
        proc.write("\r")
        res["cpu_pulso2_pct_1core"] = round(ps.cpu_percent(interval=2.5), 2)
        cuadros2 = cuadros_del_prompt(cap()[n3:])
        res["cuadros2_prompt"] = len(cuadros2)
        res["cuadros2_con_2_truecolor"] = sum(1 for c in cuadros2 if len(c) >= 2)
        res["cuadros2_distintos"] = len({tuple(c) for c in cuadros2})
        time.sleep(1.5)
        n4 = len(cap())
        res["cpu_tras_pulso2_pct_1core"] = round(ps.cpu_percent(interval=2.0), 2)
        res["bytes_nuevos_tras_pulso2"] = len(cap()) - n4
        # 4. salir
        proc.write("/salir\r")
        res["salio"] = esperar("Hasta luego", 20)
        time.sleep(0.5)
    finally:
        try:
            if proc is not None:
                proc.terminate(True)
        except Exception:
            pass
        open(OUT, "w", encoding="utf-8").write("".join(buf))
        restaurar_dueno()
    res["restaurado_dueno"] = all(
        (open(p, "rb").read() if os.path.exists(p) else None) == c for p, c in copia.items())
    comun = (res.get("prompt") and res.get("quieto") and res.get("salio")
             and res.get("restaurado_dueno")
             and res.get("bytes_nuevos_en_reposo2", 1) == 0)
    if CONTROL:
        ok = comun and res.get("cuadros_distintos", 9) <= 2 and res.get("cuadros2_distintos", 9) <= 2
    else:
        ok = (comun and res.get("cuadros_con_2_truecolor", 0) >= 5
              and res.get("cuadros_distintos", 0) >= 3
              and res.get("cuadros2_con_2_truecolor", 0) >= 5
              and res.get("bytes_nuevos_tras_pulso2", 1) == 0
              and res.get("cpu_tras_pulso2_pct_1core", 100) < 5.0)
    res["brazo"] = "control (sin animacion)" if CONTROL else "animado"
    print("RESULTADO", json.dumps(res, ensure_ascii=False))
    print("raw:", OUT)
    print("PUERTA:", "PASA" if ok else "NO PASA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
