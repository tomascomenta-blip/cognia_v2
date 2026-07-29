"""
presupuesto_pared.py — presupuesto de tiempo de PARED por celda de trabajo.

POR QUÉ EXISTE (2026-07-28). En la corrida del gap sistema-vs-crudo una celda
colgó >45 minutos: el timeout de urllib aplica POR OPERACIÓN de socket (cada
recv lo resetea), así que un backend que gotea tokens lentamente nunca lo
dispara — el "timeout de 400 s" era una promesa vacía frente al goteo. La
lección en prosa no impide nada ([[leccion-en-prosa-no-impide]]): esto es el
chequeo ejecutable — un tope de pared DURO por celda que convierte el cuelgue
en una excepción honesta que el runner cuenta como infra.

Uso en runners (la celda = una generación/tarea):

    from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado
    html = con_presupuesto(presupuesto_celda(), correr_sistema, idea, destino)

Limitación declarada: el trabajo desbordado corre en un hilo daemon que NO se
puede matar desde Python — queda huérfano hasta que su socket muera o el
proceso termine. El presupuesto protege la CORRIDA (el reloj de la noche),
no libera la GPU: si el backend sigue goteando, la celda siguiente puede
verlo ocupado. Es el trade-off correcto para runners nocturnos: perder una
celda con etiqueta de infra en vez de perder la noche entera.
"""

from __future__ import annotations

import os
import threading
import time

PRESUPUESTO_ENV = "COGNIA_PRESUPUESTO_CELDA"
PRESUPUESTO_DEFECTO = 1200      # 20 min: ~3x la celda p95 medida (~6-7 min)


class PresupuestoAgotado(Exception):
    """La celda superó su presupuesto de pared. El trabajo sigue huérfano."""


def presupuesto_celda(defecto: int = PRESUPUESTO_DEFECTO) -> int:
    """Segundos de presupuesto por celda (env COGNIA_PRESUPUESTO_CELDA)."""
    try:
        return max(1, int(os.environ.get(PRESUPUESTO_ENV, defecto)))
    except (TypeError, ValueError):
        return defecto


def con_presupuesto(segundos: float, fn, *args, **kwargs):
    """
    Ejecuta fn(*args, **kwargs) con tope de pared DURO. Devuelve su resultado
    o relanza su excepción; si el reloj gana, lanza PresupuestoAgotado y el
    hilo queda huérfano (daemon: no bloquea la salida del proceso).
    """
    caja: dict = {}

    def _correr():
        try:
            caja["resultado"] = fn(*args, **kwargs)
        except BaseException as exc:            # se relanza en el llamador
            caja["error"] = exc

    t0 = time.time()
    hilo = threading.Thread(target=_correr, daemon=True,
                            name=f"presupuesto_pared({fn.__name__})")
    hilo.start()
    hilo.join(segundos)
    if hilo.is_alive():
        raise PresupuestoAgotado(
            f"{fn.__name__} superó el presupuesto de pared "
            f"({segundos:.0f}s; lleva {time.time() - t0:.0f}s); el hilo "
            f"queda huérfano")
    if "error" in caja:
        raise caja["error"]
    return caja.get("resultado")
