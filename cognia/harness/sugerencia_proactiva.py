# -*- coding: utf-8 -*-
"""La herramienta levanta la mano cuando el modelo la está necesitando.

POR QUÉ (idea del dueño, 2026-08-13): el modelo sólo ve las 12 de `CORE_TOOLS`;
las otras ~40 registradas son invisibles salvo que se le ocurra pedir
`buscar_herramientas`. Pero es un razonador: emite `reasoning_content` ANTES de
actuar, y ahí dice qué está intentando hacer. Ese texto hoy se tira entero.

Aquí se lee y, si menciona algo que una herramienta no anunciada resuelve, se le
ofrece — hasta DOS, con su nombre y una línea de qué hacen. El modelo decide.

QUÉ NO HACE Y POR QUÉ:
- **No activa ni ejecuta nada.** Sólo informa. Que el harness decida por él qué
  herramienta usar es cambiarle el criterio, no ayudarlo.
- **No ofrece más de 2.** El A/B de este repo midió que 46 herramientas en el
  catálogo bajan el camino feliz de 4,25/5 a 2,5/5: inyectar sin tope
  reproduciría esa degradación por la puerta de atrás.
- **No repite una oferta.** Ofrecer lo mismo cada turno es ruido, y encima
  contradictorio: si no la usó la primera vez, es que no la quería.
- **No ofrece nada con score bajo.** Una sugerencia irrelevante es peor que
  ninguna (mismo umbral que `traductor_tools`, medido ahí).

OPT-IN: `COGNIA_TOOLS_PROACTIVAS=1`. Apagado por defecto hasta que el A/B de
`PREREG_TOOLS_PROACTIVAS_20260813.md` diga otra cosa.
"""

from __future__ import annotations

import os
import re

# UNA sola oferta, no dos. Medido sobre 5 razonamientos reales: la primera
# sugerencia acertó en 4/5 (contar_lineas, json_validar, git_estado,
# copiar_archivo) y la SEGUNDA fue ruido en 3/5 (deshacer_edicion, ejecutar_flujo,
# ctx_info). Ofrecer la segunda sólo añade un nombre irrelevante al contexto,
# que es justo lo que degrada según el A/B del catálogo.
MAX_OFERTAS = 1

# Umbral calibrado con los scores crudos de esos mismos casos:
#     aciertos -> 8,18 / 7,39 / 6,90      ruido -> 5,66 / 5,48
# 6.5 los separa. LIMITACIÓN DECLARADA: son 5 casos, no una calibración con
# potencia; si aparecen falsos positivos, el número a mover es éste.
SCORE_MINIMO = 6.5
MAX_CHARS_RAZONAMIENTO = 4000

# Ruido del razonamiento que no aporta a la búsqueda: si entra, BM25 empareja
# por palabras vacías y sugiere cualquier cosa.
_RUIDO = re.compile(
    r"\b(el|la|los|las|un|una|de|del|que|para|con|por|y|o|a|en|es|se|su|"
    r"lo|al|me|mi|ya|no|si|the|to|and|of|is|it|this|that|need|i|then)\b",
    re.IGNORECASE)


def activo() -> bool:
    return os.environ.get("COGNIA_TOOLS_PROACTIVAS", "").strip().lower() in (
        "1", "on", "true", "yes", "si")


def _consulta_de(razonamiento: str, intencion: str = "") -> str:
    """El texto del razonamiento reducido a términos con contenido.

    Se usa la COLA del razonamiento (los últimos caracteres): ahí es donde el
    modelo concluye qué va a hacer, mientras que el principio suele repetir el
    enunciado del usuario.
    """
    crudo = f"{(razonamiento or '')[-MAX_CHARS_RAZONAMIENTO:]} {intencion or ''}"
    sin_ruido = _RUIDO.sub(" ", crudo)
    return " ".join(sin_ruido.split())


def sugerir(razonamiento: str, activas, catalogo, ya_ofrecidas=(),
            intencion: str = "", limite: int = MAX_OFERTAS) -> list:
    """[(nombre, descripcion)] de herramientas NO anunciadas que encajan.

    `activas` son las que el modelo ya tiene; `catalogo` es el registry completo
    en forma de `catalogo_schemas()`. Nunca lanza: sin razonamiento útil o sin
    candidatas devuelve [].
    """
    if not razonamiento and not intencion:
        return []
    consulta = _consulta_de(razonamiento, intencion)
    if len(consulta) < 12:
        return []
    activas, ya = set(activas or ()), set(ya_ofrecidas or ())
    candidatas = [e for e in (catalogo or [])
                  if e.get("nombre") not in activas and e.get("nombre") not in ya]
    if not candidatas:
        return []
    try:
        from cognia.harness import registro_dinamico as rd
        indice = rd.indexar(candidatas)
        hallados = rd.buscar(indice, consulta, limite=limite * 3)
    except Exception:
        return []
    salida = []
    for nombre, score, desc in hallados:
        if score < SCORE_MINIMO:
            break
        salida.append((nombre, (desc or "").strip()))
        if len(salida) >= limite:
            break
    return salida


def texto_oferta(sugerencias) -> str:
    """La línea que se le anexa al resultado. Vacío si no hay nada que ofrecer.

    Se redacta como una OFERTA, no como una orden: el modelo tiene que poder
    ignorarla sin sentir que desobedece una instrucción del sistema.
    """
    if not sugerencias:
        return ""
    lineas = [f"  - {nombre}: {desc[:120]}" for nombre, desc in sugerencias]
    return ("[por lo que estas intentando, quiza te sirvan estas herramientas "
            "que no estaban en tu lista]\n" + "\n".join(lineas))


def anexar(resultado: str, razonamiento: str, activas, catalogo,
           ya_ofrecidas=None, intencion: str = "") -> str:
    """El resultado de la herramienta con la oferta pegada, si procede.

    `ya_ofrecidas` es un set MUTABLE que el llamador conserva durante la tarea:
    se actualiza aquí para no repetir ofertas entre pasos.
    """
    if not activo():
        return resultado
    try:
        vistas = ya_ofrecidas if ya_ofrecidas is not None else set()
        sugerencias = sugerir(razonamiento, activas, catalogo, vistas, intencion)
        if not sugerencias:
            return resultado
        for nombre, _ in sugerencias:
            vistas.add(nombre)
        oferta = texto_oferta(sugerencias)
        return f"{resultado}\n{oferta}" if oferta else resultado
    except Exception:
        return resultado          # una sugerencia rota jamas rompe el turno
