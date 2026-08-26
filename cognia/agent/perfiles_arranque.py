# -*- coding: utf-8 -*-
"""
cognia/agent/perfiles_arranque.py
=================================
La receta de arranque MEDIDA de cada modelo: UN solo sitio.

POR QUE EXISTE (2026-08-26)
---------------------------
Esta tabla vivia dentro de scripts/servir_modelo.py, que NO se distribuye
(pyproject solo empaqueta cognia* y node*). Consecuencia: `cognia flota
arrancar pensar-qwen38` servia el 27B con su receta medida (ctx 65.536, KV
q8_0, MTP n=2), pero el auto-arranque —el que dispara el CLI cuando el
:8080 esta muerto, node/llama_backend.py via cli.py:_try_load_llama— no
podia leerla y caia en las perillas GLOBALES de ~/.cognia/config.env.

El 2026-08-26 esas perillas seguian siendo las del modelo ANTERIOR: al
cambiar LLAMA_GGUF_PATH de Qwythos-9B a Qwen3.8-27B nadie toco
LLAMA_CTX_SIZE=200192, que perf_profiles.py calibro para un 9B con
atencion de ventana (~22 KiB/token medidos). Sobre el 27B ese numero cae
justo en la trampa que el propio barrido de este repo documenta:

    ctx        VRAM      gen tok/s
     65.536   13.657        31,03   <- la receta
    131.072   15.961        31,03
    262.144   15.961        11,06   <- MISMA VRAM, un TERCIO de velocidad

200.192 esta en esa zona: arranca, /props confirma el contexto y responde
—solo el tok/s lo delata, porque lo que no cabe lo sirve la RAM del
sistema. Con el agente pidiendo generaciones largas, "un tercio de
velocidad" es la diferencia entre entregar y morir por timeout.

Una perilla GLOBAL no puede saber que modelo se esta sirviendo; una receta
POR GGUF si. Por eso la receta gana, y se DICE en voz alta cuando pisa a
la perilla (nada de arreglos silenciosos: en este repo "no lo cablearon" y
"se rompio" tienen que verse distinto).
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["PERFILES_ARRANQUE", "perfil_arranque"]

# Perfiles de arranque POR MODELO, con flags MEDIDOS en esta maquina. Solo se
# aplican si el basename del gguf casa el patron: para cualquier otro modelo el
# comando sale byte-identico al historico (contrafactual del test de regresion).
#
# nemotron (2026-08-14, RTX 5060 Ti 16 GB): el gguf pesa 17,6 GB y NO cabe
# entero en VRAM, pero es MoE 128x2.4B con solo 6 activos y solo 6 de sus 52
# capas tienen KV (el resto es Mamba2). Medido:
#   - `--fit on` reparte los expertos GPU/CPU solo; con --ctx-size EXPLICITO
#     NO toca el contexto (verificado: pedi 1.048.576 y /props devolvio
#     1.048.576). Por eso aca fit_off queda en False a proposito: con off el
#     server no reparte y muere por OOM.
#   - `--no-mmap` + batch grande: prefill 645 -> 1.023 tok/s en el mismo
#     escalon de 32k (+59%). El propio log lo pide cuando hay tensores en CPU.
#   - KV q8_0: el MILLON entero entra en 14.622 MiB con los pesos.
# Sonda de punta a punta: prompt real de 1.046.706 tokens, aguja recuperada.
# La clave es 'nemotron-3.5' y NO 'nemotron' a secas: en ~/.cognia/models/ hay
# OpenReasoning-Nemotron-14B (denso, ctx viable 16.384) y nemotron-mtp (la
# cabeza MTP de 1,1 GB). Con la clave corta, el combo 'pensar-en-lazo' —que
# arranca justamente --modelo OpenReasoning— habria pedido un KV de 1M sobre
# un denso de 48 capas: ~103 GB solo de KV contra 16.311 MiB de placa. Es la
# TERCERA tabla del repo que casa modelos por substring y la tercera vez que
# 'nemotron' se lleva lo que no es suyo (ya paso en flota.CEREBROS y en
# comparar_modelos._CTX_POR_MODELO). Por eso, ademas, el match va de patron
# MAS LARGO a mas corto: que la proxima entrada no reabra el agujero por el
# orden en que alguien la escriba.
#
# qwen3.8-27b-ridge (2026-08-18, RTX 5060 Ti 16.311 MiB): denso 27,78B en 11,7
# GiB (cuantizacion Ridge, 3,69 bpw). Hibrido: de sus 64 bloques solo 16 llevan
# atencion completa (qwen35.full_attention_interval=4), los otros 48 son
# Gated-DeltaNet -> el KV es de 16 capas y por eso caben ventanas grandes.
# BARRIDO MEDIDO (KV q8_0, sonda de 200 tokens generados):
#     ctx        VRAM      gen tok/s
#      32.768   12.414        31,02
#      65.536   13.657        31,03   <- el perfil
#     131.072   15.961        31,03   <- cabe, pero deja 350 MiB de margen
#     262.144   15.961        11,06   <- MISMA VRAM y un TERCIO de velocidad
# El 262k es la trampa: arranca, /props confirma 262.144 servidos y responde.
# Lo que no cabe lo sirve la RAM del sistema (el driver de Windows spillea) y
# solo el tok/s lo delata -- por eso el barrido genera 200 tokens y no 16.
# Se elige 65.536 y no 131.072 porque los 350 MiB de margen del segundo se los
# come el escritorio (Chrome solo ya ocupaba 2,4 GB en esta maquina): quien
# tenga la GPU para el solo puede pedir --ctx 131072 a mano.
#
# spec_mtp 2: la cabeza MTP viaja DENTRO del gguf (qwen35.nextn_predict_layers
# = 1, blk.64). MEDIDO en este modelo (ctx 65.536, temp 0, 3 medidas por brazo,
# brazo nulo de referencia, prompts frescos):
#     brazo       codigo            prosa           aceptacion
#     sin-spec    30,97             30,94              --
#     mtp n=2     56,27 (1,82x)     43,79 (1,42x)    85% / 57%
#     mtp n=4     58,01 (1,87x)     35,36 (1,14x)    72% / 35%
#     ngram-mod   30,91 (1,00x)     30,86 (1,00x)     0% en prosa
# n=2 y no n=4 porque el 4 gana 3% en codigo y PIERDE 20% en prosa. El
# ngram-mod (default historico del backend) no aporta NADA con prompts
# frescos: sus ganancias aparecian al repetir el mismo prompt contra el mismo
# server, copiando su propia respuesta anterior del cache.
PERFILES_ARRANQUE = {
    "nemotron-3.5": {"ctx": 1048576, "ctk": "q8_0", "ctv": "q8_0",
                     "no_mmap": True, "batch": 4096, "ubatch": 1024,
                     "sin_draft": True, "ngl": 0},
    "qwen3.8-27b-ridge": {"ctx": 65536, "ctk": "q8_0", "ctv": "q8_0",
                          "spec_mtp": 2,
                          "mmproj": "mmproj-Qwen3.8-27B-BF16.gguf"},
}


def perfil_arranque(modelo) -> dict:
    """Flags extra medidos para ese gguf, o {} si no hay perfil."""
    nombre = Path(modelo).name.lower()
    for patron in sorted(PERFILES_ARRANQUE, key=len, reverse=True):
        if patron in nombre:
            return dict(PERFILES_ARRANQUE[patron])
    return {}
