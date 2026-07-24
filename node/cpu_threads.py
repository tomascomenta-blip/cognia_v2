"""
node/cpu_threads.py
===================
Cuantos hilos darle a llama.cpp en CPU. Un solo lugar, porque hasta ahora
node/llama_backend.py y cognia/perf_profiles.py contestaban distinto y los
tres valores que se usaban estaban medidos en maquinas distintas.

MEDICION (llama-bench b9391/build 86a9c79f8, Qwen3-1.7B-Q4_K_M, -ngl 0,
tg32, r=5, 2026-07-23). Maquina del dueno: 6 nucleos fisicos / 12 logicos.

  hilos |  tok/s
  ------+--------
      2 |  21.74
      4 |  39.98
      6 |  45.65  <- pico, == nucleos FISICOS
      8 |  46.03
     12 |  39.81  <- lo que daba el default viejo max(4, cpu_count())

  6 hilos vs 12 hilos = +14.7% de decode. El hyperthreading NO ayuda en el
  GEMM de llama.cpp cuando sobran nucleos fisicos: los hilos logicos extra
  solo se pisan la cache.

Pero "usar siempre los fisicos" es PEOR en maquinas chicas. Mismo binario y
modelo, con el proceso atado por afinidad a 4 CPUs logicas (= 2 fisicas, el
analogo del i3-10110U que es la maquina objetivo del release a PyPI):

  hilos |  tok/s
  ------+--------
      2 |  25.86  <- lo que daba el perfil 'cpu' (nucleos fisicos)
      4 |  39.03  <- +51%
      6 |  34.99  (sobre-suscripcion)
     12 |  32.17

Control de que la afinidad se aplico de verdad: con la misma mascara de 4
CPUs, 6 hilos cae de 45.65 a 34.99 y 12 hilos de 39.81 a 32.17.

De ahi la regla: fisicos, pero nunca menos de 4, y nunca mas que los logicos.
En una maquina de <=4 nucleos fisicos devuelve exactamente el default
historico, asi que las mediciones viejas del i3 (node/llama_backend.py:
"el 4o hilo logico compite con el SO -> cpu-1") siguen valiendo: el cap solo
BAJA hilos en maquinas con mas de 4 nucleos fisicos.

Sin dependencias nuevas: psutil es opcional (solo para contar fisicos).
"""

from __future__ import annotations

import os

# Piso historico: es el default que llama_backend viene usando desde siempre y
# el que las mediciones del i3 (2 fisicos / 4 logicos) dieron por bueno.
PISO_HILOS = 4


def nucleos_fisicos() -> int:
    """Nucleos fisicos via psutil; sin psutil, os.cpu_count()//2 (minimo 1).

    El //2 asume SMT, que es el caso comun en las maquinas donde esto importa.
    Si la maquina no tiene SMT el resultado queda por debajo del piso y
    hilos_cpu_optimos() lo levanta igual, asi que no se pierde nada.
    """
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n:
            return int(n)
    except ImportError:
        pass
    return max(1, (os.cpu_count() or 4) // 2)


def hilos_cpu_optimos(default_logico: int | None = None) -> int:
    """Hilos para decode/prefill en CPU. Ver la tabla del docstring del modulo.

    default_logico: el default que usaba el call-site antes de este modulo
    (max(4, cpu_count) en el camino in-process, cpu_count-1 en el camino
    llama-server). Se respeta como TECHO para no subir hilos en ninguna
    maquina: este cambio solo puede bajarlos. None => os.cpu_count().
    """
    logicos = os.cpu_count() or 4
    techo = logicos if default_logico is None else min(logicos, default_logico)
    return max(1, min(techo, max(nucleos_fisicos(), PISO_HILOS)))
