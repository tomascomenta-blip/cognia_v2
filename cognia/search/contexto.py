# -*- coding: utf-8 -*-
"""Cuánto contexto se le puede dar a UNA pregunta, en SEGUNDOS de pared.

LA IDEA. El pipeline de investigación de la casa lee 3 páginas × 2000 chars
porque se escribió cuando la ventana eran 8k
(`web_research.py`: *"sin comerse la ventana de 8k del modelo"*). Hoy el
cerebro sirve 1.048.576 tokens. Pero la ventana grande NO es gratis: en local
los tokens no cuestan dinero, cuestan SEGUNDOS.

Medido en esta máquina el 2026-08-14 con Nemotron 3.5 Lightning 30B-A3B:

    contexto     prefill        pared con ~500 tok de salida
    4k              5 s              ~15 s
    32k            40 s              ~50 s
    128k          160 s             ~2,8 min
    1M          2.061 s              ~35 min   <- medido de punta a punta

Por eso el presupuesto se declara en segundos y se CONVIERTE a tokens con el
tok/s del backend, en vez de elegir un número de tokens a ojo. "Dale 2
minutos a esta pregunta" es una decisión que un humano puede tomar; "dale
128k tokens" no lo es hasta saber cuánto tarda esta máquina.

Un modo NO es mejor que otro por ser más ancho: eso se mide con el banco.
Lo que esto garantiza es que el coste esté DECLARADO antes de pagarlo.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

# tok/s de PREFILL por defecto, medidos (no estimados) en esta máquina:
#   Nemotron 3.5 30B-A3B, KV q8_0, expertos repartidos GPU/CPU
#     32k -> 1.023 | 132k -> 960 | 268k -> 858 | 543k -> 695 | 1,04M -> 508
# Baja con la profundidad porque las 6 capas de atención pagan el KV largo.
# El valor por defecto es el del tramo MEDIO, que es donde vive el uso real;
# `medir_prefill()` lo reemplaza por el del backend vivo cuando importa.
TOK_S_PREFILL_DEFECTO = 900.0
TOK_S_GENERACION_DEFECTO = 45.0

# Un char de texto web ~ 0,29 tokens con este tokenizador (medido: 3,47
# chars/token sobre el pajar de la escalera). Se usa para NO tener que
# tokenizar 4 MB de HTML solo para saber si entran.
CHARS_POR_TOKEN = 3.47


@dataclass
class Modo:
    nombre: str
    tokens: int
    paginas: int
    tok_por_pagina: int
    porque: str


# Los tres modos. `paginas` y `tok_por_pagina` no son decorativos: son el
# reparto que hace el ensamblador, y multiplicados dan `tokens`.
ESTRECHO = Modo("estrecho", 4_000, 3, 1_300,
                "lo que hacía el pipeline de 8k: 3 páginas recortadas. "
                "Es el BRAZO NULO de cualquier medición de esto")
MEDIO = Modo("medio", 32_000, 12, 2_600,
             "12 páginas casi enteras por ~50 s de pared: el punto donde "
             "todavía se puede iterar")
ANCHO = Modo("ancho", 160_000, 40, 4_000,
             "40 páginas COMPLETAS en una sola llamada. Con un solo slot de "
             "GPU esto es más barato que 40 llamadas de 4k, porque el "
             "prefill es el mismo y las latencias de arranque son una")

MODOS = {m.nombre: m for m in (ESTRECHO, MEDIO, ANCHO)}


def segundos_de(modo: Modo, tok_s: float = 0.0,
                tokens_salida: int = 500) -> float:
    """La pared que va a costar ese modo. Lo que el usuario decide."""
    tok_s = tok_s or TOK_S_PREFILL_DEFECTO
    return (modo.tokens / tok_s) + (tokens_salida / TOK_S_GENERACION_DEFECTO)


def modo_para(segundos: float, tok_s: float = 0.0) -> Modo:
    """El modo MÁS ancho que cabe en ese presupuesto de pared.

    Siempre devuelve algo: por debajo del presupuesto de ESTRECHO devuelve
    ESTRECHO igual, porque negarse a contestar por 3 segundos de más sería
    peor que contestar con poco contexto. Lo que no hace nunca es prometer
    ANCHO y entregar la pared de ANCHO sin haberla declarado.
    """
    tok_s = tok_s or TOK_S_PREFILL_DEFECTO
    for modo in (ANCHO, MEDIO, ESTRECHO):
        if segundos_de(modo, tok_s) <= segundos:
            return modo
    return ESTRECHO


def modo_por_nombre(nombre: str) -> Modo:
    """El modo pedido por nombre, con COGNIA_SEARCH_MODO como override."""
    env = os.environ.get("COGNIA_SEARCH_MODO", "").strip().lower()
    clave = (env or nombre or "medio").strip().lower()
    return MODOS.get(clave, MEDIO)


def medir_prefill(url: str = "", tokens_sonda: int = 8_000) -> float:
    """tok/s de prefill REALES del backend vivo, o el default si no se puede.

    Existe porque el número de arriba es de ESTA máquina con ESTE modelo: en
    cuanto cambie el cerebro, el presupuesto en segundos se vuelve mentira si
    nadie lo vuelve a medir. Cuesta una petición de 8k (~10 s).
    """
    import json
    import urllib.request
    try:
        from cognia.agent.model_profiles import url_del_backend
        url = (url or url_del_backend()).rstrip("/")
    except Exception:
        url = (url or "http://127.0.0.1:8080").rstrip("/")
    relleno = ("El nodo sincronizo su estado con el coordinador. "
               * int(tokens_sonda * CHARS_POR_TOKEN / 45))
    cuerpo = json.dumps({
        "messages": [{"role": "user", "content": relleno + "\n\nDi: ok"}],
        "max_tokens": 1, "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            url + "/v1/chat/completions", data=cuerpo,
            headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
        tm = d.get("timings") or {}
        # El server ya lo mide; su número gana al cronómetro de afuera, que
        # incluye la red y el JSON.
        if tm.get("prompt_per_second"):
            return float(tm["prompt_per_second"])
        n = (d.get("usage") or {}).get("prompt_tokens") or tokens_sonda
        return n / max(time.time() - t0, 0.001)
    except Exception:
        return TOK_S_PREFILL_DEFECTO


def repartir(paginas: list, modo: Modo) -> list:
    """Recorta una lista de páginas al presupuesto del modo, DECLARANDO el
    recorte en el propio texto.

    Reparte parejo y devuelve lo que sobra a las que se pasan: si 30 de las
    40 páginas son cortas, las 10 largas se quedan con el resto en vez de
    cortarse en el mismo sitio que todas. Una elisión sin marca es una cita
    falsa esperando a pasar, así que cada recorte deja su cicatriz.
    """
    if not paginas:
        return []
    tope_total = int(modo.tokens * CHARS_POR_TOKEN)
    elegidas = paginas[:modo.paginas]
    tope_pagina = int(modo.tok_por_pagina * CHARS_POR_TOKEN)

    cortas = [p for p in elegidas
              if len(p.get("texto") or "") <= tope_pagina]
    largas = [p for p in elegidas
              if len(p.get("texto") or "") > tope_pagina]
    gastado = sum(len(p.get("texto") or "") for p in cortas)
    reparto = ((tope_total - gastado) // len(largas)) if largas else 0

    salida = []
    for p in elegidas:
        texto = p.get("texto") or ""
        tope = tope_pagina if p in cortas else max(tope_pagina, reparto)
        if len(texto) > tope:
            texto = (texto[:tope]
                     + f"\n[... {len(texto) - tope} chars elididos de esta "
                       f"página ...]")
        salida.append(dict(p, texto=texto))
    return salida
