# -*- coding: utf-8 -*-
"""Teclea de verdad en el REPL de Cognia a traves de una consola ConPTY real.

POR QUE hace falta: el enganche de /mejorar se apaga a proposito cuando no hay
tty (_mejora_aplica -> selector.hay_tty()), asi que un `printf | python -m
cognia` NO puede probar el modo 'auto' ni el selector del Enter. Con pywinpty
hay una consola Win32 de verdad: las mismas condiciones que teclear a mano.

Uso: teclear_repl.py "linea1||linea2||/salir" [seg_por_linea] [fichero_salida]

Dos trampas ya pagadas, por eso el diseno es asi:
- `PtyProcess.read()` BLOQUEA. Un bucle con `time.time() < limite` no corta
  nunca porque se queda dentro del read: por eso el lector va en un HILO y el
  hilo principal solo mira el reloj.
- El spinner de 'pensando' escupe bytes sin parar, asi que "esperar a que haya
  silencio" tampoco corta durante la generacion: hace falta un TOPE DURO.
"""
import sys
import threading
import time

from winpty import PtyProcess

LINEAS = sys.argv[1].split("||")
MAX_LINEA = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
DESTINO = sys.argv[3] if len(sys.argv) > 3 else None
# Sin bytes durante esto = el REPL espera otra orden. 10 s y no 5 porque entre
# "prompt mejorado" y el primer token del modelo hay un hueco mudo (prefill) que
# con 5 s cortaba el turno antes de la respuesta.
QUIETO = 10.0

proc = PtyProcess.spawn(
    r"C:\Users\usuario\Desktop\cognia_v2\venv312\Scripts\python.exe -m cognia",
    cwd=r"C:\Users\usuario\Desktop\cognia_v2",
    dimensions=(45, 120),
)

salida = []
ultimo = [time.time()]
vivo = [True]


def _lector():
    while vivo[0]:
        try:
            trozo = proc.read(8192)
        except Exception:
            break
        if trozo:
            salida.append(trozo)
            ultimo[0] = time.time()
        else:
            time.sleep(0.03)


threading.Thread(target=_lector, daemon=True).start()


def esperar(max_total):
    """Corta por silencio (QUIETO sin bytes) o por tope duro, lo que llegue
    antes. El tope duro es obligatorio: el spinner nunca calla."""
    limite = time.time() + max_total
    while time.time() < limite:
        if time.time() - ultimo[0] > QUIETO:
            return
        time.sleep(0.2)


def volcar():
    if DESTINO:
        with open(DESTINO, "w", encoding="utf-8", errors="replace") as fh:
            fh.write("".join(salida))


esperar(30.0)                      # arranque: banner + prompt_toolkit listo
volcar()
for linea in LINEAS:
    salida.append("\n\n>>>>> TECLEADO: {}\n".format(linea))
    volcar()
    proc.write(linea)
    time.sleep(0.4)                # el Enter aparte: prompt_toolkit agrupa mal
    proc.write("\r")
    ultimo[0] = time.time()
    esperar(MAX_LINEA)
    volcar()

vivo[0] = False
try:
    proc.terminate(force=True)
except Exception:
    pass
volcar()
