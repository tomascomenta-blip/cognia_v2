# -*- coding: utf-8 -*-
"""
cognia/clases/__main__.py
=========================
La PUERTA del cerebrito: `python -m cognia.clases` enciende el icono flotante.

DOS LOCKS Y NO UNO, y conviene entender por que antes de tocarlos:

  - `widget.tomar_lock_widget()` impide DOS CEREBRITOS. Es el lock que decide
    si este proceso arranca o se va. Sin el, un segundo `python -m
    cognia.clases` pone otro icono exactamente encima del primero: dos menus,
    dos exportaciones y un duenio arrastrando el de arriba sin entender por
    que el de abajo no se mueve.
  - `jornada.lock_actual()` dice QUIEN GRABA. NO impide arrancar: el widget
    sirve igual con la clase grabandose desde el REPL -- de hecho es cuando
    mas sirve, porque ensenia el estado -- pero se IMPRIME al arrancar, para
    que el duenio sepa antes de nada que el boton Grabar no va a aparecer y
    por que. `jornada.estado()` publica eso mismo como `otro_proceso` y el
    menu ya lo respeta; esto es solo decirlo tambien por consola.

El lock del widget se suelta SIEMPRE, en el `finally`: un lock que sobrevive a
un cierre sucio bloquearia el cerebrito manana, y el bloqueo aparecerria sin
causa visible. Para eso ademas se roba solo (con aviso) si su PID esta muerto.
"""

from __future__ import annotations

import sys

from cognia.clases import jornada as jor
from cognia.clases import widget as wg


def _informe_jornada() -> str:
    """Una linea sobre quien tiene la grabacion, o "" si no la tiene nadie."""
    lock = jor.lock_actual()
    if not lock or not lock.get("vivo") or not lock.get("ajeno"):
        return ""
    return ("aviso: la clase la esta grabando el proceso PID %s (jornada "
            "'%s'). El cerebrito la mostrara ENCENDIDA, pero para pararla hay "
            "que ir a ese proceso; si ese proceso ya no existe, el menu del "
            "icono trae 'Liberar el bloqueo'."
            % (lock.get("pid"), lock.get("jornada") or "?"))


def main(argv=None) -> int:
    """0 si el widget corrio y cerro bien; 1 si ya habia otro; 2 sin pantalla."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "ayuda"):
        print("uso: python -m cognia.clases")
        print("  Enciende el cerebrito: el icono flotante del cuaderno de "
              "clase.")
        print("  Clic en el icono -> menu (grabar / pausar / mutear / "
              "materia / ver cuaderno / exportar / salir).")
        print("  Se arrastra con el raton y recuerda donde lo dejaste.")
        return 0

    ok, aviso = wg.tomar_lock_widget()
    if not ok:
        print(aviso)
        return 1
    if aviso:
        print(aviso)
    informe = _informe_jornada()
    if informe:
        print(informe)

    try:
        app = wg.Cerebrito()
    except Exception as exc:
        # Sin escritorio (una sesion SSH, un servicio) `tk.Tk()` lanza
        # TclError. Se dice con todas las letras en vez de volcar el
        # traceback: el motivo real cabe en una linea y el traceback no lo
        # explica.
        wg.soltar_lock_widget()
        print("no pude abrir el cerebrito (%s: %s). Hace falta un escritorio "
              "con pantalla; sin el, el cuaderno se maneja desde el REPL con "
              "/grabar-clase." % (type(exc).__name__, exc))
        return 2
    try:
        print("cerebrito encendido. Clic en el icono para el menu.")
        app.correr()
    finally:
        # SIEMPRE: un lock que sobrevive al cierre bloquea el widget de
        # manana y el bloqueo aparece sin causa.
        motivo = wg.soltar_lock_widget()
        if motivo:
            print(motivo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
