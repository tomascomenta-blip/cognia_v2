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
import time

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

    # Prefiltro determinista ANTES de gastar Chromium: quitar duplicados
    # canónicos, agregadores y PDFs cuesta microsegundos y ahorra segundos de
    # extracción. Lo descartado NO desaparece: viaja en `descartados` con su
    # motivo, porque un prefiltro que se come el recall en silencio sería
    # peor que no tenerlo.
    prefiltrados = []
    try:
        from cognia.search.prefiltro import prefiltrar
        pf = prefiltrar(candidatos)
        prefiltrados = [{"url": d["url"], "razon": f"prefiltro: {d['motivo']}"}
                        for d in pf["descartados"]]
        if pf["aceptados"]:
            candidatos = pf["aceptados"]
    except Exception:
        pass          # sin prefiltro se sigue igual que siempre

    validos, descartados = [], list(prefiltrados)
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


# Debajo de esto una extracción "exitosa" es sospechosa: casi siempre es una
# página 100% JS que sin navegador devuelve el cascarón. Es el disparador
# para gastar Chromium, que cuesta ~1-2 s de arranque.
_MIN_TEXTO_UTIL = 400


def extraer_muchas(urls: list, cap: int = 5, timeout_s: int = 15,
                   extractor_http=None, extractor_js=None):
    """Extrae MUCHAS páginas y devuelve un Lote de sobres (cognia.search).

    Dos fases, y el porqué de cada una está medido en el coste, no en el
    gusto:

    1. **HTTP en paralelo.** httpx es thread-safe, así que N páginas salen a
       la vez. La mayoría de la documentación técnica —que es lo que el
       agente lee— es HTML servido, y para eso el navegador es un lujo.
    2. **Chromium SOLO para lo que lo necesita, y UNA sola instancia.** El
       camino viejo (`_extraer_con_chromium`) abre `sync_playwright()` y
       lanza un browser POR URL: 40 páginas eran 40 arranques. Aquí el
       browser se abre una vez y se reusan páginas. Secuencial a propósito:
       la API sync de playwright NO es thread-safe, y fingir concurrencia con
       ella es como se cuelga un proceso sin dejar rastro.

    El resultado de una URL que falla es un sobre con su causa, jamás un
    hueco: el llamador puede contar cuántas cayeron y por qué.
    """
    from cognia.search.fanout import Lote, Sobre, en_paralelo

    urls = [u for u in (urls or []) if u]
    if not urls:
        return Lote(sobres=[])
    extractor_http = extractor_http or _extraer_con_http
    extractor_js = extractor_js or _extraer_con_chromium

    lote = en_paralelo(urls, lambda u: extractor_http(u, timeout_s), cap=cap,
                       timeout_s=timeout_s * 3)

    # Quién merece navegador: las que fallaron y las que volvieron vacías.
    pendientes = [s for s in lote.sobres
                  if not s.ok
                  or len((s.valor or {}).get("texto") or "") < _MIN_TEXTO_UTIL]
    if not pendientes:
        return lote

    sobres = list(lote.sobres)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        # Sin playwright no hay segunda fase; los sobres HTTP valen igual y
        # el aviso viaja en los que quedaron cortos.
        for s in pendientes:
            if not s.ok:
                s.error = f"{s.error}; sin fallback JS ({exc})"
        return Lote(sobres=sobres)

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        try:
            for s in pendientes:
                url = s.spec
                t0 = time.time()
                try:
                    pag = _extraer_en_navegador(navegador, url, timeout_s)
                    if len(pag.get("texto") or "") >= _MIN_TEXTO_UTIL or not s.ok:
                        sobres[s.indice] = Sobre(
                            spec=url, ok=True, valor=pag, indice=s.indice,
                            segundos=round(time.time() - t0, 2))
                except Exception as exc:
                    if not s.ok:
                        # Falló por las DOS vías: la causa útil es la doble.
                        s.error = (f"http=({s.error}) "
                                   f"chromium=({type(exc).__name__}: {exc})")[:500]
                        s.tipo_error = "AmbasVias"
        finally:
            navegador.close()
    return Lote(sobres=sobres)


def _extraer_en_navegador(navegador, url: str, timeout_s: int) -> dict:
    """Una página en un browser YA abierto (el que reusa extraer_muchas)."""
    pagina = navegador.new_page(user_agent=_UA)
    try:
        pagina.route(
            "**/*",
            lambda ruta: (ruta.abort()
                          if ruta.request.resource_type in
                          ("image", "media", "font", "stylesheet")
                          else ruta.continue_()))
        pagina.goto(url, timeout=timeout_s * 1000,
                    wait_until="domcontentloaded")
        pagina.wait_for_timeout(1200)
        titulo = pagina.title() or url
        texto = pagina.evaluate(
            "document.body ? document.body.innerText : ''")
        return {"titulo": titulo.strip(), "texto": texto or "",
                "url_final": pagina.url, "via": "chromium-reusado"}
    finally:
        pagina.close()


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
