# -*- coding: utf-8 -*-
"""Regresion 2026-07-25: la respuesta del agente quedaba PLEGADA en Actividad.

En la sesion real del dueno, Cognia abrio Chrome en YouTube, tomo la captura y
contesto "Se ha abierto Chrome con YouTube... aqui tienes el archivo: ...png".
Esa respuesta llego enmarcada en un panel rich ("| ... |") porque el CLI la
imprime con _show_response, y el clasificador del remoto manda todo lo
enmarcado a Actividad (plegado). El dueno lo leyo como que no habia contestado.

El clasificador NO se toco (su premisa "el chrome va enmarcado" es correcta):
lo que cambia es que en el remoto la RESPUESTA FINAL sale sin marco.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from cognia.remoto.sesiones import reclasificar

RAIZ = Path(__file__).resolve().parent.parent


def test_respuesta_enmarcada_iba_a_actividad():
    """El comportamiento que causaba el bug (sigue vigente para el chrome)."""
    enmarcada = ("│ Se ha abierto Chrome con YouTube y se ha tomado una "
                 "captura de pantalla. │")
    assert reclasificar("cognia", enmarcada, False)[0] == "actividad"


def test_respuesta_sin_marco_va_al_chat():
    plana = ("Se ha abierto Chrome con YouTube y se ha tomado una captura de "
             "pantalla. Aquí tienes el archivo: C:\\Users\\x\\captura.png")
    assert reclasificar("cognia", plana, False)[0] == "cognia"


def test_el_remoto_marca_su_entorno():
    """sesiones.py tiene que anunciar COGNIA_REMOTO=1 al REPL: es lo que
    activa la respuesta sin marco."""
    fuente = (RAIZ / "cognia" / "remoto" / "sesiones.py").read_text(
        encoding="utf-8")
    assert 'COGNIA_REMOTO="1"' in fuente


def test_show_response_final_sin_panel_en_remoto():
    """End-to-end del render: mismo texto, con y sin COGNIA_REMOTO."""
    guion = (
        "from cognia.cli import _show_response\n"
        "_show_response('Listo: la captura esta en C:/x/y.png', 'cyan',"
        " respuesta_final=True)\n"
        "_show_response('Estado: local', 'cyan')\n"
    )
    # heredar el entorno real: con uno minimo, Path.home() no resuelve en
    # Windows y cognia.config revienta al importar
    entorno_base = dict(os.environ,
                        PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                        NO_COLOR="1", TERM="dumb", PYTHONPATH=str(RAIZ))
    entorno_base.pop("COGNIA_REMOTO", None)
    salidas = {}
    for etiqueta, remoto in (("remoto", "1"), ("terminal", "")):
        env = dict(entorno_base)
        if remoto:
            env["COGNIA_REMOTO"] = remoto
        salidas[etiqueta] = subprocess.run(
            [sys.executable, "-c", guion], capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(RAIZ), env=env,
            timeout=300).stdout

    # en el remoto la respuesta final no lleva marco...
    for linea in salidas["remoto"].splitlines():
        if "captura esta en" in linea:
            assert "│" not in linea and "|" not in linea, linea
            break
    else:
        raise AssertionError("no se imprimio la respuesta final")
    # ...pero el chrome (estado, ayuda, tablas) SIGUE enmarcado
    assert any("│" in l and "Estado: local" in l
               for l in salidas["remoto"].splitlines()), salidas["remoto"]
    # y en terminal normal no cambia nada: la respuesta va en su panel
    assert any("│" in l and "captura esta en" in l
               for l in salidas["terminal"].splitlines()), salidas["terminal"]


def test_respuesta_llega_sin_esperar_a_que_muera_el_repl():
    """La respuesta tiene que SALIR del proceso al escribirla, no al cerrarlo.

    En el remoto el REPL es un subproceso vivo y su stdout es un pipe:
    block-buffered (8 KB). rich hacia flush; un print pelado no. Cazado al
    verificar este mismo cambio: el REPL quedaba inactivo con la respuesta
    atrapada en el buffer y el chat del movil parecia congelado.

    subprocess.run() NO puede detectarlo (al terminar, el buffer se vacia solo):
    hay que leer con el proceso todavia vivo."""
    import queue
    import threading

    guion = (
        "import time\n"
        "from cognia.cli import _show_response\n"
        "_show_response('RESPUESTA-VIVA', 'cyan', respuesta_final=True)\n"
        # duerme MUCHO mas que el plazo de lectura: si el proceso terminara
        # dentro del plazo, el buffer se vaciaria al morir y el test pasaria
        # aunque faltase el flush (agujero real, medido al escribirlo).
        "time.sleep(900)\n"
    )
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               NO_COLOR="1", TERM="dumb", COGNIA_REMOTO="1",
               PYTHONPATH=str(RAIZ))
    env.pop("PYTHONUNBUFFERED", None)         # el flush debe venir del codigo
    proc = subprocess.Popen(
        [sys.executable, "-c", guion], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        errors="replace", bufsize=1, cwd=str(RAIZ), env=env)
    lineas: queue.Queue = queue.Queue()

    def _leer():
        try:
            for linea in proc.stdout:
                lineas.put(linea)
        except Exception:
            pass

    threading.Thread(target=_leer, daemon=True).start()
    try:
        visto, plazo = False, time.time() + 45
        while time.time() < plazo and not visto:
            try:
                if "RESPUESTA-VIVA" in lineas.get(timeout=5):
                    visto = True
            except queue.Empty:
                pass
        assert visto, ("la respuesta no salio del REPL mientras seguia vivo "
                       "(falta flush: se quedo en el buffer del pipe)")
    finally:
        proc.kill()
        proc.wait(timeout=30)
