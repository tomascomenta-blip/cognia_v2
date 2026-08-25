# -*- coding: utf-8 -*-
"""Puerta REAL del spinner animado (P8 del sistema de estilos por elemento):
el REPL de verdad contra el backend activo, bajo una ConPTY (pywinpty, la
misma ruta que Windows Terminal), con un ~/.cognia/estilo.json TEMPORAL que
enciende spinner.pensar.animacion y spinner.tool.animacion. Dos brazos con la
MISMA pregunta de conocimiento:

    on   sin COGNIA_ANIMACION      -> se esperan N >= 2 cuadros de BARRIDO
                                      distintos (>= 2 colores '38;2;' en la
                                      misma linea del spinner)
    off  COGNIA_ANIMACION=0        -> 0 cuadros de barrido (el token [pensar]
                                      es UN solo color plano por cuadro)

Que mide, en la ventana entre teclear la pregunta y el '/salir': repintados
del status (trozos entre CR / cursor-up / borrado de linea que contienen
'ctrl+c corta' o 'pensando'), cuantos son un barrido y cuantos barridos
distintos hay. El estilo.json (y su .bak) del dueno se guardan antes y se
restauran al final, pase lo que pase.

MEDIDO 2026-08-24 (worktree estilos/spinner, Qwen3.8-27B en :8080, ConPTY
120x40, COLORTERM=truecolor, misma pregunta en los dos brazos):
    on : 12 repintados del status, 8 cuadros de barrido, 7 distintos,
         hasta 10 colores truecolor en un cuadro, 14 cursor-up
    off: 18 repintados, 0 cuadros de barrido, 1 color por cuadro
         (38;2;126;230;42 = el token pensar de la paleta), 11 cursor-up

REVISION 2026-08-25: la puerta daba NO PASA (ventana de 81 bytes, 0 repintados)
en el worktree Y en main. Dos causas, una por capa:
  1. ~/.cognia_config.json del dueno con mejorar_prompt='preguntar': el Enter
     de la pregunta abria el menu 'Enviar el prompt, o mejorarlo con IA?' y el
     segundo <Enter> del gate lo cerraba con 'enviar'. Por eso la ventana
     medida arrancaba en el segundo <Enter>. Ahora la puerta pone
     mejorar_prompt='off' SOLO durante la corrida (guarda y restaura el
     fichero) y la ventana arranca en la PREGUNTA: el spinner sale justo
     despues de ella, haya o no menu.
  2. El backend :8080 ocupado por OTRO proceso (slot is_processing=true con
     12k tokens de prompt): el REPL se queda en enrutador.decidir ->
     _inferir_para_agente -> urlopen SIN spinner (faulthandler a los 25 s),
     asi que no hay nada que medir. Eso es del instrumento: la puerta ahora
     lo comprueba antes y se declara NO CONCLUYENTE (exit 2) en vez de
     NO PASA, porque un backend ocupado no dice nada del spinner.

Mientras cli.py no cargue el fichero al arrancar (gancho de P4), el REPL se
lanza por _lanzador(), que hace A.cargar() + A.conectar_glow() y luego
runpy.run_module('cognia'). Con el gancho en cli.py el lanzador sobra (es
idempotente: cargar dos veces el mismo fichero no cambia nada).

Uso:
    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\spinner_gate_conpty.py [on] [off]
    (por defecto corre los dos brazos, en ese orden)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
ESTILO = os.path.join(os.path.expanduser("~"), ".cognia", "estilo.json")
# ~/.cognia_config.json del dueno: si tiene mejorar_prompt = 'preguntar' (el
# default), al dar Enter sobre la pregunta sale el menu 'Enviar el prompt, o
# mejorarlo con IA?' y se come el <Enter> del gate: la pregunta nunca llega al
# modelo y no hay spinner que medir (medido 2026-08-25: ventana de 81 bytes,
# 0 repintados, en el worktree Y en main). La puerta lo pone en 'off' SOLO
# durante la corrida, guardando y restaurando el fichero igual que estilo.json.
CONFIG = os.path.join(os.path.expanduser("~"), ".cognia_config.json")
BAK = ESTILO + ".bak"
GUARDA = os.path.join(RAIZ, ".spinner_gate_estilo_dueno")
PREGUNTA = "en una frase: que es la fotosintesis? responde sin usar herramientas"
ENTER = "\r"

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


def guardar_dueno() -> None:
    os.makedirs(GUARDA, exist_ok=True)
    for f in (ESTILO, BAK, CONFIG):
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(GUARDA, os.path.basename(f)))


def restaurar_dueno() -> None:
    for destino in (ESTILO, BAK, CONFIG):
        origen = os.path.join(GUARDA, os.path.basename(destino))
        if os.path.exists(origen):
            shutil.copy2(origen, destino)
        elif os.path.exists(destino):
            os.remove(destino)
    shutil.rmtree(GUARDA, ignore_errors=True)


def apagar_mejorar_temporal() -> str:
    """Escribe mejorar_prompt='off' en ~/.cognia_config.json (copia ya
    guardada por guardar_dueno). Devuelve el estado que tenia el dueno, para
    imprimirlo: si era 'preguntar', esa es la razon de que la puerta fallara
    antes de este cambio."""
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    antes = str(cfg.get("mejorar_prompt", "preguntar"))
    cfg["mejorar_prompt"] = "off"
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return antes


def escribir_temporal() -> None:
    doc = {"version": 1, "nombre": "gate-p8",
           "elementos": {"spinner.pensar": {"animacion": {"activa": True}},
                         "spinner.tool": {"animacion": {"activa": True}}}}
    os.makedirs(os.path.dirname(ESTILO), exist_ok=True)
    with open(ESTILO, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def correr(brazo: str, salida_dir: str) -> dict:
    from winpty import PtyProcess
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("COGNIA_"):
            env.pop(k)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "TERM": "xterm-256color",
                "COLORTERM": "truecolor", "PYTHONPATH": RAIZ})
    env.pop("NO_COLOR", None)
    if brazo == "off":
        env["COGNIA_ANIMACION"] = "0"
    proc = PtyProcess.spawn([PY, "-c", _LANZADOR, RAIZ], cwd=RAIZ, env=env,
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
    # Sin el menu de /mejorar ya no hace falta un segundo <Enter>: la pregunta
    # se envia con el suyo y el spinner aparece a continuacion.
    for l in (PREGUNTA, "/salir"):
        et = "<Enter>" if l == ENTER else l
        print(f"[{brazo} {time.strftime('%H:%M:%S')}] tecleo: {et}", flush=True)
        buf.append(f"\n<<<TECLEADO {et}>>>\n")
        proc.write(l if l == ENTER else l + ENTER)
        time.sleep(2.0)
        ok = esperar_quieto()
        print(f"[{brazo} {time.strftime('%H:%M:%S')}] quieto={ok} vivo={proc.isalive()}",
              flush=True)
        if not proc.isalive():
            break
    time.sleep(2)
    if proc.isalive():
        proc.terminate(True)
    raw = "".join(buf)
    ruta = os.path.join(salida_dir, f"spinner_gate_{brazo}.raw.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(raw)
    return medir(raw, brazo, ruta)


def medir(raw: str, brazo: str, ruta: str) -> dict:
    # La ventana arranca en la PREGUNTA (antes: en un segundo <Enter> que solo
    # existia para cerrar el menu de /mejorar; ver REVISION 2026-08-25 arriba).
    i0 = raw.find("<<<TECLEADO " + PREGUNTA)
    i1 = raw.find("<<<TECLEADO /salir>>>")
    ventana = raw[max(i0, 0):i1 if i1 > 0 else None]
    trozos = re.split(r"\r|\x1b\[\d*A|\x1b\[2K|\x1b\[K", ventana)

    def _limpio(s):
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s)
    status = [t for t in trozos if ("ctrl+c corta" in _limpio(t) or "pensando" in _limpio(t))]
    # OJO: el token [pensar] de la paleta YA es un hex (38;2;126;230;42 en
    # oscuro), asi que 'hay 38;2;' no distingue nada. Un BARRIDO es un cuadro
    # con >= 2 colores truecolor DISTINTOS en la misma linea (la ventana de
    # mezcla); el status clasico lleva exactamente uno.
    colores = [tuple(sorted(set(re.findall(r"38;2;\d+;\d+;\d+", t)))) for t in status]
    barridos = [c for c in colores if len(c) >= 2]
    return {"brazo": brazo, "bytes": len(raw), "ventana_bytes": len(ventana),
            "repintados_status": len(status), "cuadros_barrido": len(barridos),
            "cuadros_barrido_distintos": len(set(barridos)),
            "max_colores_en_un_cuadro": max((len(c) for c in colores), default=0),
            "38;2;_total_ventana": ventana.count("38;2;"),
            "cursor_up": len(re.findall(r"\x1b\[\d*A", ventana)), "captura": ruta}


def backend_ocupado() -> str:
    """'' si :8080 responde y ningun slot esta procesando; si no, el motivo.
    Un slot ajeno ocupado deja al REPL esperando en el enrutador sin spinner
    (medido 2026-08-25): la puerta no puede medir nada y lo dice."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/slots", timeout=3) as r:
            slots = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - el motivo va al veredicto
        return f"/slots no responde ({type(exc).__name__}: {exc})"
    ocupados = [s.get("id") for s in slots if s.get("is_processing")]
    if ocupados:
        return f"slot(s) {ocupados} is_processing=true (otro proceso usa el backend)"
    return ""


def main() -> int:
    brazos = [a for a in sys.argv[1:] if a in ("on", "off")] or ["on", "off"]
    motivo = backend_ocupado()
    if motivo:
        print("PUERTA: NO CONCLUYENTE --", motivo)
        print("        (apaga o libera el backend :8080 y vuelve a correr; un slot "
              "ocupado bloquea al REPL en el enrutador SIN spinner)")
        return 2
    salida_dir = os.environ.get("SPINNER_GATE_DIR") or os.path.join(RAIZ, "logs")
    os.makedirs(salida_dir, exist_ok=True)
    guardar_dueno()
    resultados = []
    try:
        escribir_temporal()
        print("[gate] mejorar_prompt del dueno:", apagar_mejorar_temporal(),
              "-> 'off' durante la corrida", flush=True)
        for b in brazos:
            resultados.append(correr(b, salida_dir))
    finally:
        restaurar_dueno()
        print("[gate] estilo.json y .cognia_config.json del dueno restaurados:",
              os.path.exists(ESTILO), os.path.exists(CONFIG))
    ok = True
    for r in resultados:
        print(json.dumps(r, ensure_ascii=False))
        if r["brazo"] == "on" and r["cuadros_barrido_distintos"] < 2:
            ok = False
        if r["brazo"] == "off" and r["cuadros_barrido"] != 0:
            ok = False
    print("PUERTA:", "PASA" if ok else "NO PASA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
