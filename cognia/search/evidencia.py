# -*- coding: utf-8 -*-
"""¿La cita está DE VERDAD en la página? Chequeo literal, sin juez.

POR QUE SIN MODELO. Un juez LLM que valida citas tiene el mismo problema que
el que las produce: si el extractor alucina una frase plausible, el juez la
encuentra plausible. Este chequeo es una comparación de cadenas y por eso su
veredicto es DURO — y, lo que importa más, su tasa de error es del
instrumento y no del modelo bajo prueba.

Da un número que no depende de la opinión de nadie: la **tasa de citas
fabricadas** = fracción de registros extraídos cuya `evidencia` no aparece en
el texto de su propia `source_url`.

LO QUE NO HACE. No dice si la cita RESPONDE la pregunta, solo si existe. Un
extractor puede citar literal y aun así traer lo que no era: eso es otra
medición (la de acierto), y confundirlas es cómo un pipeline pasa un gate sin
servir para nada.
"""
from __future__ import annotations

import re
import unicodedata

# Debajo de esto una "cita" no identifica nada: cualquier texto largo
# contiene "el", "de 2026" o "la API". Verificar fragmentos así da un verde
# que no significa nada, y un verde vacío es peor que un rojo.
MIN_CHARS_CITA = 24

# El extractor puede elidir el medio de una frase larga. Se acepta la elisión
# EXPLÍCITA (…, ..., [...]) y se verifica cada trozo por separado: así una
# cita honesta con corte no reprueba, pero pegar dos frases de sitios
# distintos sin marcar sí.
_ELISION = re.compile(r"\s*(?:\[\s*\.\.\.\s*\]|\.\.\.|…)\s*")


def normalizar(texto: str) -> str:
    """Forma canónica para comparar: NFKC, minúsculas, espacios colapsados.

    NFKC y no NFC porque las páginas traen comillas tipográficas, guiones
    largos y espacios finos que el modelo re-teclea como ASCII; sin eso, una
    cita correcta reprueba por un carácter invisible.
    """
    t = unicodedata.normalize("NFKC", texto or "")
    t = (t.replace("‘", "'").replace("’", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-")
          .replace(" ", " "))
    return re.sub(r"\s+", " ", t).strip().lower()


def verificar_cita(cita: str, texto_fuente: str) -> dict:
    """{ok, razon, trozos, trozos_ok} para UNA cita contra UNA página."""
    cita = (cita or "").strip()
    if not cita:
        return {"ok": False, "razon": "cita vacía", "trozos": 0,
                "trozos_ok": 0}
    if len(cita) < MIN_CHARS_CITA:
        return {"ok": False, "trozos": 0, "trozos_ok": 0,
                "razon": (f"cita de {len(cita)} chars: por debajo de "
                          f"{MIN_CHARS_CITA} no identifica nada")}
    fuente = normalizar(texto_fuente)
    if not fuente:
        return {"ok": False, "razon": "la fuente no tiene texto", "trozos": 0,
                "trozos_ok": 0}

    trozos = [t for t in (_ELISION.split(cita)) if len(t.strip()) >= 8]
    if not trozos:
        trozos = [cita]
    encontrados = [t for t in trozos if normalizar(t) in fuente]
    ok = len(encontrados) == len(trozos)
    if ok:
        razon = ("literal en la fuente"
                 if len(trozos) == 1
                 else f"los {len(trozos)} trozos de la cita elidida están")
    else:
        falta = next(t for t in trozos if normalizar(t) not in fuente)
        razon = (f"no está en la fuente: «{falta.strip()[:80]}»")
    return {"ok": ok, "razon": razon, "trozos": len(trozos),
            "trozos_ok": len(encontrados)}


def verificar_registros(registros: list, textos: dict) -> dict:
    """Verifica una tanda de registros extraídos contra sus páginas.

    registros: [{evidencia, source_url, ...}]   textos: {url: texto}
    Devuelve {verificados, fabricados, sin_fuente, tasa_fabricacion, detalle}.

    `sin_fuente` se cuenta APARTE de `fabricados`: un registro cuya página no
    se pudo descargar no es una mentira del modelo, es un hueco del pipeline,
    y mezclarlos le echaría al modelo la culpa de una caída de red.
    """
    verificados, fabricados, sin_fuente, detalle = [], [], [], []
    for r in registros or []:
        url = (r.get("source_url") or r.get("url") or "").strip()
        texto = textos.get(url)
        if texto is None:
            sin_fuente.append(r)
            detalle.append({"url": url, "estado": "sin_fuente",
                            "razon": "no tengo el texto de esa página"})
            continue
        v = verificar_cita(r.get("evidencia") or "", texto)
        detalle.append({"url": url, "razon": v["razon"],
                        "estado": "ok" if v["ok"] else "fabricada"})
        (verificados if v["ok"] else fabricados).append(r)
    juzgados = len(verificados) + len(fabricados)
    return {
        "verificados": verificados,
        "fabricados": fabricados,
        "sin_fuente": sin_fuente,
        # Sobre los JUZGABLES, no sobre el total: si la mitad no se pudo
        # descargar, la tasa sobre el total diría "poca fabricación" cuando
        # lo que hubo fue poca verificación.
        "tasa_fabricacion": (len(fabricados) / juzgados) if juzgados else 0.0,
        "detalle": detalle,
    }
