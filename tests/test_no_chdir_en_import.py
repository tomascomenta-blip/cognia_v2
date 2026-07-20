# -*- coding: utf-8 -*-
"""Regresion: importar modulos de produccion NO puede cambiar el cwd del proceso.

Bug (deuda tecnica cazada 2026-07-16): cognia_v3/interfaces/respuestas_articuladas.py
hacia os.chdir(BASE_DIR) A NIVEL DE MODULO. Se importa lazy desde el chat de
produccion (cli.py fallback no-streaming, _call_articulated de skills,
app/routes/chat.py): el primer turno que lo tocaba movia el cwd del proceso a
site-packages/cognia_v3/interfaces y todo path relativo posterior (archivos
que crea el agente, oficina_estado.json con default os.getcwd()) caia ahi en
vez del directorio del usuario.
"""
import importlib
import os
import sys


def test_importar_respuestas_articuladas_no_cambia_cwd():
    cwd_antes = os.getcwd()
    # Forzar re-import real (si otro test ya lo importo, el modulo cacheado
    # no re-ejecutaria el codigo de nivel de modulo y el test seria vacuo).
    sys.modules.pop("cognia_v3.interfaces.respuestas_articuladas", None)
    try:
        importlib.import_module("cognia_v3.interfaces.respuestas_articuladas")
    finally:
        cwd_despues = os.getcwd()
        os.chdir(cwd_antes)  # restaurar pase lo que pase
    assert cwd_despues == cwd_antes, (
        "importar respuestas_articuladas cambio el cwd del proceso "
        f"({cwd_antes!r} -> {cwd_despues!r})")
