# -*- coding: utf-8 -*-
"""Navegador del agente — Chromium headless + centinela anti-inyección.

No es un navegador para humanos: es el brazo web del AGENTE. Busca en la
web (ddgs, sin API key), ENTRA a los resultados con Chromium real
(playwright), extrae el texto visible y lo pasa TODO por el centinela web
(cognia/agent/sentinel.py) antes de que llegue al modelo: un resultado
envenenado o fuera de tema se DESCARTA con su razón y se sigue con el
siguiente candidato — nunca en silencio (el modo de fallo caro de la casa).

Por qué esto NO repite el fracaso de busqueda_web.py con el raspado HTML:
allí el parser de HTML se escribía y mantenía A MANO (regex sobre tablas de
DuckDuckGo, por encima del techo del modelo que lo mantenía). Aquí el DOM
lo resuelve Chromium (innerText del body: lo que un humano VE, sin scripts
ni CSS ni texto display:none — de paso, el texto oculto, vector clásico de
inyección, ni siquiera entra al pipeline) y el parser de resultados lo
mantiene la librería ddgs. Fallback sin Chromium: httpx + BeautifulSoup,
con aviso de vía. Cada fallo es un error legible, jamás un vacío.

    from cognia.knowledge.navegador import buscar_en_web
    r = buscar_en_web("que es el model context protocol", max_resultados=2)
    for v in r["resultados"]:
        print(v["titulo"], v["url"], v["texto"][:80])
"""
from __future__ import annotations

import re

# Presupuestos: sin límites, una página infinita (scroll) o un PDF gigante
# harían al agente tragarse medio contexto. Truncamiento SIEMPRE declarado.
_MAX_TEXTO_PAGINA = 15000     # chars que se evalúan/conservan por página
_MAX_TEXTO_RESULTADO = 3500   # chars por resultado en la salida del tool
_TIMEOUT_PAGINA_S = 25
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Cognia-Agente")


def _extraer_con_chromium(url: str, timeout_s: int = _TIMEOUT_PAGINA_S) -> dict:
    """Título + innerText del body con Chromium headless. Bloquea imagen/
    media/fuente/css (solo queremos texto y va 3-5x más rápido)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            pagina = browser.new_page(user_agent=_UA)
            pagina.route(
                "**/*",
                lambda ruta: (ruta.abort()
                              if ruta.request.resource_type in
                              ("image", "media", "font", "stylesheet")
                              else ruta.continue_()))
            pagina.goto(url, timeout=timeout_s * 1000,
                        wait_until="domcontentloaded")
            # networkidle cuelga en páginas con polling; un respiro fijo corto
            # deja pintar el contenido JS sin apostar a que la red calle.
            pagina.wait_for_timeout(1200)
            titulo = pagina.title() or url
            texto = pagina.evaluate("document.body ? document.body.innerText : ''")
            return {"titulo": titulo.strip(), "texto": texto or "",
                    "url_final": pagina.url, "via": "chromium"}
        finally:
            browser.close()


def _extraer_con_http(url: str, timeout_s: int = 15) -> dict:
    """Fallback sin Chromium: httpx + BeautifulSoup. No ejecuta JS (páginas
    100% cliente saldrán vacías y el centinela las descartará con razón)."""
    import httpx
    from bs4 import BeautifulSoup
    r = httpx.get(url, timeout=timeout_s, follow_redirects=True,
                  headers={"User-Agent": _UA})
    r.raise_for_status()
    sopa = BeautifulSoup(r.text, "lxml")
    for tag in sopa(["script", "style", "noscript", "template"]):
        tag.decompose()
    titulo = sopa.title.get_text(strip=True) if sopa.title else url
    return {"titulo": titulo, "texto": sopa.get_text("\n"),
            "url_final": str(r.url), "via": "http"}


def extraer_pagina(url: str, timeout_s: int = _TIMEOUT_PAGINA_S) -> dict:
    """Extrae una página: Chromium primero, httpx+bs4 de fallback (con la
    vía declarada en 'via'). Si ambas fallan: RuntimeError legible con las
    DOS causas — nunca un dict vacío."""
    if not re.match(r"^(https?|file)://", url or ""):
        raise ValueError(f"URL no válida (se espera http/https/file): '{url}'")
    try:
        return _extraer_con_chromium(url, timeout_s)
    except Exception as exc_chromium:
        try:
            pag = _extraer_con_http(url, min(timeout_s, 15))
            pag["aviso"] = f"Chromium falló ({exc_chromium}); vía http sin JS"
            return pag
        except Exception as exc_http:
            raise RuntimeError(
                f"no se pudo extraer '{url}': chromium=({exc_chromium}) "
                f"http=({exc_http})") from exc_http


def _buscar_ddg(consulta: str, max_candidatos: int) -> list:
    """Candidatos [{titulo, url, resumen}] vía ddgs (DuckDuckGo, sin clave)."""
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError(
            "falta la librería 'ddgs' (pip install ddgs)") from exc
    filas = DDGS().text(consulta, max_results=max_candidatos)
    out = []
    for f in filas or []:
        url = f.get("href") or f.get("url") or ""
        if url:
            out.append({"titulo": f.get("title") or url, "url": url,
                        "resumen": f.get("body") or ""})
    return out


def buscar_en_web(consulta: str, max_resultados: int = 3,
                  max_candidatos: int = 8, buscador=None,
                  extractor=None) -> dict:
    """Busca, entra a los resultados y devuelve SOLO los que pasan el
    centinela: {"resultados": [...], "descartados": [...], "aviso": str}.

    Cada resultado: {titulo, url, via, texto} (texto ya saneado y truncado
    con declaración). Cada descartado: {url, razon} — el descarte de un
    candidato NO corta la búsqueda: se sigue con el siguiente hasta juntar
    max_resultados o agotar candidatos. `buscador`/`extractor` inyectables
    para tests sin red."""
    from cognia.agent.sentinel import evaluar_contenido_web, sanear_texto_web

    consulta = (consulta or "").strip()
    if not consulta:
        raise ValueError("consulta vacía")
    buscador = buscador or _buscar_ddg
    extractor = extractor or extraer_pagina

    candidatos = buscador(consulta, max_candidatos)
    if not candidatos:
        return {"resultados": [], "descartados": [],
                "aviso": f"el buscador no devolvió candidatos para '{consulta}'"}

    validos, descartados = [], []
    for c in candidatos:
        if len(validos) >= max_resultados:
            break
        url = c.get("url") or ""
        try:
            pag = extractor(url)
        except Exception as exc:
            descartados.append({"url": url, "razon": f"extracción fallida: {exc}"})
            continue
        texto = sanear_texto_web(pag.get("texto") or "")[:_MAX_TEXTO_PAGINA]
        nivel, razon = evaluar_contenido_web(texto, tema=consulta, fuente=url)
        if nivel != "allow":
            descartados.append({"url": url, "razon": f"centinela: {razon}"})
            continue
        recorte = ""
        if len(texto) > _MAX_TEXTO_RESULTADO:
            recorte = (f"\n[... recortado a {_MAX_TEXTO_RESULTADO} de "
                       f"{len(texto)} chars ...]")
        validos.append({
            "titulo": pag.get("titulo") or c.get("titulo") or url,
            "url": pag.get("url_final") or url,
            "via": pag.get("via", "?"),
            "texto": texto[:_MAX_TEXTO_RESULTADO] + recorte,
        })

    aviso = ""
    if not validos:
        razones = "; ".join(f"{d['url']}: {d['razon']}" for d in descartados[:5])
        aviso = (f"ningún candidato pasó el centinela para '{consulta}' "
                 f"({len(descartados)} descartados: {razones})")
    elif descartados:
        aviso = f"{len(descartados)} candidato(s) descartados por el centinela o por extracción"
    return {"resultados": validos, "descartados": descartados, "aviso": aviso}


def abrir_url(url: str, tema: str = None) -> dict:
    """Abre UNA URL con el navegador del agente y pasa el texto por el
    centinela. Devuelve {titulo, url, via, texto, veredicto, razon}; si el
    centinela bloquea, texto="" y el veredicto/razón lo explican (el caller
    decide qué mostrar — nunca llega texto envenenado al modelo)."""
    from cognia.agent.sentinel import evaluar_contenido_web, sanear_texto_web
    pag = extraer_pagina(url)
    texto = sanear_texto_web(pag.get("texto") or "")[:_MAX_TEXTO_PAGINA]
    nivel, razon = evaluar_contenido_web(texto, tema=tema, fuente=url)
    return {
        "titulo": pag.get("titulo") or url,
        "url": pag.get("url_final") or url,
        "via": pag.get("via", "?"),
        "veredicto": nivel, "razon": razon,
        "texto": texto if nivel == "allow" else "",
        "aviso": pag.get("aviso", ""),
    }
