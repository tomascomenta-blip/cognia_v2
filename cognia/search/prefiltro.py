# -*- coding: utf-8 -*-
"""Prefiltrado determinista de candidatos: CERO modelo, cero red.

La etapa que ningún clon de buscador tiene y que hace rendir a las caras. Sin
esto, el presupuesto de fetch se gasta en tres copias del mismo artículo y en
agregadores que republican lo que ya se leyó.

TODO lo de aquí es código: canonicalizar, deduplicar, topar por dominio y
descartar por extensión. Ninguna decisión de contenido — eso es del ranking,
y mezclarlas haría imposible saber cuál de las dos etapas rompió el recall.

LA GUARDA QUE IMPORTA: un prefiltro que ahorra mucho y baja el recall está
REPROBADO, aunque la lista se vea más limpia. Por eso `prefiltrar` devuelve
también lo descartado con su motivo: sin eso no se puede auditar qué se
perdió.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse, urlunparse

# Parámetros de tracking: no cambian el documento, solo parten la identidad
# de la URL y hacen que la misma página entre tres veces.
_BASURA_QS = re.compile(
    r"^(utm_|fbclid|gclid|msclkid|ref|ref_src|mc_[ce]id|igshid|si|"
    r"campaign|source|medium)", re.I)

# Extensiones que el pipeline no sabe leer: bajarlas gasta el presupuesto
# para acabar en un descarte.
_EXT_NO = (".pdf", ".zip", ".tar", ".gz", ".exe", ".dmg", ".mp4", ".mp3",
           ".avi", ".mkv", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
           ".ico", ".woff", ".woff2", ".ttf", ".css", ".xml", ".rss")

# Sitios que casi siempre republican texto de otro sitio. No es una lista de
# calidad (eso sería censura de contenido): es una lista de DUPLICACIÓN.
_AGREGADORES = frozenset({
    "webcache.googleusercontent.com", "translate.google.com",
    "r.jina.ai", "12ft.io", "outline.com", "archive.is",
})

TOPE_POR_DOMINIO = 3


def canonicalizar(url: str) -> str:
    """La forma canónica de una URL para comparar identidad.

    Quita parámetros de tracking, el fragmento y la barra final; baja el
    esquema y el host. NO toca el resto del query string: en muchos sitios
    `?id=42` ES el documento, y limpiarlo de más colapsaría páginas distintas
    en una — un falso duplicado se lleva contenido bueno sin dejar rastro.
    """
    try:
        p = urlparse((url or "").strip())
    except Exception:
        return (url or "").strip()
    if not p.netloc:
        return (url or "").strip()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
          if not _BASURA_QS.match(k)]
    query = "&".join(f"{k}={v}" for k, v in qs)
    ruta = p.path.rstrip("/") or "/"
    # El esquema se fija a https SIEMPRE: http://x/a y https://x/a son el
    # mismo documento, y dejarlos distintos hace que la misma página se baje
    # dos veces. La URL original se conserva en el registro; esto es la CLAVE
    # de identidad, no la dirección con la que se va a descargar.
    return urlunparse(("https", host, ruta, "", query, ""))


def dominio(url: str) -> str:
    try:
        h = (urlparse(url or "").netloc or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def prefiltrar(candidatos: list, tope_dominio: int = TOPE_POR_DOMINIO,
               limite: int = 0) -> dict:
    """{aceptados, descartados, ahorro} sobre [{url, ...}].

    Conserva el ORDEN de entrada (que suele ser el del ranking del buscador):
    reordenar aquí sería tomar una decisión de relevancia disfrazada de
    limpieza.
    """
    aceptados, descartados, reserva = [], [], []
    vistos, por_dominio = set(), {}
    for c in candidatos or []:
        url = (c.get("url") or "").strip() if isinstance(c, dict) else str(c)
        if not url:
            descartados.append({"url": url, "motivo": "sin url"})
            continue
        canon = canonicalizar(url)
        dom = dominio(canon)
        if canon in vistos:
            descartados.append({"url": url, "motivo": "duplicada (canónica)"})
            continue
        if dom in _AGREGADORES:
            descartados.append({"url": url, "motivo": f"agregador ({dom})"})
            continue
        if canon.lower().endswith(_EXT_NO):
            descartados.append({"url": url, "motivo": "extensión no legible"})
            continue
        if por_dominio.get(dom, 0) >= tope_dominio:
            # A la RESERVA, no a la basura. El tope por dominio es una
            # preferencia de diversidad, no un defecto de la página: si las
            # tres primeras de ese dominio fallan al extraer, la cuarta es lo
            # único que queda. Descartarla de verdad hacía que 2 resultados
            # se volvieran 0 (reproducido) — y un prefiltro que ahorra
            # bajando el recall está reprobado por su propia guarda.
            fila = dict(c) if isinstance(c, dict) else {"url": url}
            fila["url_canonica"] = canon
            fila["motivo_reserva"] = f"tope de {tope_dominio} por dominio"
            reserva.append(fila)
            continue
        vistos.add(canon)
        por_dominio[dom] = por_dominio.get(dom, 0) + 1
        fila = dict(c) if isinstance(c, dict) else {"url": url}
        fila["url_canonica"] = canon
        aceptados.append(fila)
        if limite and len(aceptados) >= limite:
            break
    total = len(candidatos or [])
    return {"aceptados": aceptados, "descartados": descartados,
            # `reserva`: aplazados por diversidad, NO desechados. El llamador
            # tira de aquí cuando los aceptados no le alcanzan.
            "reserva": reserva,
            "ahorro": (len(descartados) / total) if total else 0.0,
            "dominios": len(por_dominio)}
