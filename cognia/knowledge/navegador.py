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

SIN DEPENDENCIAS OPCIONALES (medido 2026-08-24): el venv instalado del
producto (~/.cognia/venv) NO trae ddgs, ni playwright, ni lxml — solo httpx,
bs4 y requests. Con el código de antes la búsqueda moría en
RuntimeError("falta la librería 'ddgs'") y la extracción en FeatureNotFound
por el "lxml" hardcodeado. Por eso: (1) `_buscar_ddg` cae a `_buscar_lite`
(POST a lite.duckduckgo.com con urllib + html.parser; 3/3 resultados en
1,54 s y encontró el canal que ddgs no encontraba), (2) el parser de bs4 es
lxml si está y html.parser si no, (3) `_extraer_con_http` pasa el HTML
crudo por `extractores.extraer_datos` para que un cascarón JS (YouTube deja
~220 chars a bs4) igual entregue el dato que trae embebido en su JSON.

    from cognia.knowledge.navegador import buscar_en_web
    r = buscar_en_web("que es el model context protocol", max_resultados=2)
    for v in r["resultados"]:
        print(v["titulo"], v["url"], v["texto"][:80])
"""
from __future__ import annotations

import importlib.util
import re
import time
import urllib.parse
import urllib.request

# Presupuestos: sin límites, una página infinita (scroll) o un PDF gigante
# harían al agente tragarse medio contexto. Truncamiento SIEMPRE declarado.
_MAX_TEXTO_PAGINA = 15000     # chars que se evalúan/conservan por página
_MAX_TEXTO_RESULTADO = 3500   # chars por resultado en la salida del tool
_TIMEOUT_PAGINA_S = 25
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Cognia-Agente")
# UA de navegador PURO para HTTP sin Chromium: el sufijo "Cognia-Agente" y
# el "Python-urllib" de fábrica reciben 403 en Wikipedia (medido 2026-08-24);
# el UA identificable de busqueda_web.py SÍ pasa allí, y es el reintento.
_UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_UA_RESEARCH = "Cognia/1.0 (+local research)"
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"


def _parser_bs4() -> str:
    """"lxml" si está instalado, si no el "html.parser" de la stdlib. El
    "lxml" a pelo era una dependencia fantasma: FeatureNotFound en toda
    instalación limpia del producto."""
    return "lxml" if importlib.util.find_spec("lxml") else "html.parser"


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
    """Fallback sin Chromium: httpx + BeautifulSoup. No ejecuta JS, pero el
    HTML crudo pasa por `extractores.extraer_datos`: si el sitio embebe el
    dato en su JSON (YouTube: suscriptores, handle, título) se antepone al
    texto un bloque "DATOS EXTRAIDOS (sitio): ..." y viaja en "datos". Así
    un cascarón de 220 chars igual entrega el hecho, y el que no trae nada
    sale corto y buscar_en_web lo marca como "texto insuficiente".

    UA Chrome primero; ante un 403 se reintenta con el UA identificable
    (Wikipedia rechaza al primero y acepta al segundo) y se declara."""
    import httpx
    from bs4 import BeautifulSoup
    from cognia.knowledge import extractores

    aviso = ""
    r = httpx.get(url, timeout=timeout_s, follow_redirects=True,
                  headers=extractores.cabeceras_para(url, _UA_CHROME))
    if r.status_code == 403:
        r = httpx.get(url, timeout=timeout_s, follow_redirects=True,
                      headers=extractores.cabeceras_para(url, _UA_RESEARCH))
        aviso = "403 con UA de navegador; reintentado con UA Cognia/1.0"
    r.raise_for_status()
    html_crudo = r.text
    parser = _parser_bs4()
    sopa = BeautifulSoup(html_crudo, parser)
    for tag in sopa(["script", "style", "noscript", "template"]):
        tag.decompose()
    titulo = sopa.title.get_text(strip=True) if sopa.title else ""
    texto = sopa.get_text("\n")
    url_final = str(r.url)

    out = {"titulo": titulo or url, "texto": texto, "url_final": url_final,
           "via": "http", "parser": parser}
    datos = extractores.extraer_datos(url_final, html_crudo)
    if datos:
        if datos.get("aviso"):
            aviso = (aviso + "; " if aviso else "") + datos["aviso"]
        if datos.get("campos"):
            out["datos"] = datos
            out["texto"] = extractores.bloque_datos(datos) + "\n\n" + texto
            if not titulo and datos.get("titulo"):
                out["titulo"] = datos["titulo"]
    if aviso:
        out["aviso"] = aviso
    return out


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


def _abrir_lite(consulta: str, timeout_s: int = 20) -> str:
    """El POST a lite.duckduckgo.com con urllib (stdlib): devuelve el HTML.
    Es lo que `_buscar_lite` recibe inyectado en los tests."""
    datos = urllib.parse.urlencode({"q": consulta}).encode()
    req = urllib.request.Request(
        _DDG_LITE_URL, data=datos,
        headers={"User-Agent": _UA_CHROME,
                 "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return r.read().decode("utf-8", errors="replace")


def _resumen_cercano(enlace) -> str:
    """El texto descriptivo que el endpoint lite pone en la fila <tr>
    siguiente al enlace. Best-effort: si la maqueta cambia, cadena vacía en
    vez de romper la búsqueda entera (port de cognia_v3)."""
    try:
        fila = enlace.find_parent("tr")
        siguiente = fila.find_next_sibling("tr") if fila is not None else None
        return siguiente.get_text(" ", strip=True)[:400] if siguiente else ""
    except Exception as exc:
        return f"(resumen ilegible: {type(exc).__name__})"


def _url_de_lite(href: str) -> str:
    """Los enlaces del lite son directos casi siempre; cuando vienen como
    redirección propia (//duckduckgo.com/l/?uddg=<url>) se desenvuelven."""
    if "duckduckgo.com/l/" in href and "uddg=" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        return (q.get("uddg") or [""])[0]
    return href


def _buscar_lite(consulta: str, max_candidatos: int = 8, abrir=None,
                 intentos: int = 3) -> list:
    """Candidatos [{titulo, url, resumen, via:"lite"}] raspando el endpoint
    lite de DuckDuckGo SIN ddgs: urllib + BeautifulSoup(html, "html.parser").
    Port fiel de cognia_v3/core/investigador.py::buscar_web_resultados, el
    único backend sin API key que devolvía resultados RELEVANTES en las
    mediciones del 2026-07-19 (bing rss mentía: repetía la consulta en el
    título y traía items de otro tema).

    El endpoint limita por frecuencia respondiendo una página SIN resultados
    (no un error): por eso se reintenta con espera creciente (2 s, 4 s).
    Si tras `intentos` no hay nada, RuntimeError con el motivo — nunca una
    lista vacía muda, porque "no hay resultados" y "me limitaron" piden
    decisiones distintas. `abrir(consulta) -> html` inyectable para tests.
    """
    from bs4 import BeautifulSoup
    abrir = abrir or _abrir_lite
    ultimo = "sin resultados en la página"
    for intento in range(max(1, intentos)):
        try:
            html = abrir(consulta)
        except Exception as exc:
            html, ultimo = "", f"{type(exc).__name__}: {exc}"
        salida = []
        if html:
            sopa = BeautifulSoup(html, "html.parser")
            for a in sopa.find_all("a", href=True):
                url = _url_de_lite(a["href"])
                titulo = a.get_text(strip=True)
                # Los resultados son enlaces externos con texto; el resto son
                # controles del propio buscador (Next, Settings...).
                if not url.startswith("http") or "duckduckgo.com" in url:
                    continue
                if not titulo or len(titulo) < 3:
                    continue
                salida.append({"titulo": titulo, "url": url,
                               "resumen": _resumen_cercano(a), "via": "lite"})
                if len(salida) >= max_candidatos:
                    break
            if not salida:
                ultimo = (f"página sin resultados ({len(html)} chars; "
                          f"¿limitado por frecuencia?)")
        if salida:
            return salida
        if intento < intentos - 1:
            time.sleep(2.0 * (intento + 1))     # limitado por frecuencia
    raise RuntimeError(f"DDG lite sin resultados para '{consulta}' tras "
                       f"{intentos} intento(s): {ultimo}")


def _buscar_ddg(consulta: str, max_candidatos: int) -> list:
    """Candidatos [{titulo, url, resumen, via}] : ddgs si está instalada y
    responde; si falta, revienta o devuelve vacío, `_buscar_lite`. Si las
    dos fallan, RuntimeError con AMBOS motivos ("ddgs: ...; lite: ...") —
    el llamador (fanout/responder/browser_tool) ve QUÉ falló, no un vacío.
    Firma fija: la usan cognia.search.fanout y cognia.search.responder."""
    motivo_ddgs = ""
    try:
        from ddgs import DDGS
    except ImportError as exc:
        motivo_ddgs = f"no instalada ({exc})"
    else:
        try:
            filas = DDGS().text(consulta, max_results=max_candidatos)
            out = []
            for f in filas or []:
                url = f.get("href") or f.get("url") or ""
                if url:
                    out.append({"titulo": f.get("title") or url, "url": url,
                                "resumen": f.get("body") or "", "via": "ddgs"})
            if out:
                return out
            motivo_ddgs = "0 resultados"
        except Exception as exc:
            motivo_ddgs = f"{type(exc).__name__}: {exc}"
    try:
        return _buscar_lite(consulta, max_candidatos)
    except Exception as exc_lite:
        raise RuntimeError(
            f"búsqueda web sin resultados para '{consulta}' — "
            f"ddgs: {motivo_ddgs}; lite: {exc_lite}") from exc_lite


def via_busqueda_disponible() -> str:
    """"ddgs" | "lite" | "ninguna: <motivo>", SIN red (solo comprueba qué se
    puede importar). Para que el CLI muestre con qué va a buscar."""
    if importlib.util.find_spec("ddgs"):
        return "ddgs"
    if importlib.util.find_spec("bs4"):
        return "lite"
    return ("ninguna: faltan ddgs y bs4 (pip install beautifulsoup4 para la "
            "vía lite, pip install ddgs para la principal)")


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
            # La RESERVA (aplazados por tope de dominio) va detrás, no fuera:
            # si los aceptados fallan al extraer, se sigue con ella. Sin esto,
            # 6 candidatos de un mismo dominio con los 3 primeros rotos daban
            # 0 resultados donde antes había 2 (reproducido).
            candidatos = pf["aceptados"] + pf.get("reserva", [])
    except Exception:
        pass          # sin prefiltro se sigue igual que siempre

    validos, descartados, insuficientes = [], list(prefiltrados), []
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
        item = {
            "titulo": pag.get("titulo") or c.get("titulo") or url,
            "url": pag.get("url_final") or url,
            "via": pag.get("via", "?"),
            "texto": texto[:_MAX_TEXTO_RESULTADO] + recorte,
        }
        datos = pag.get("datos") or {}
        if datos.get("campos"):
            item["datos"] = datos
        elif len(texto) < _MIN_TEXTO_UTIL:
            # Un cascarón JS (YouTube: 226 chars) pasaba como resultado
            # "válido" con aviso vacío y el modelo contestaba de memoria. No
            # se descarta (el título y la URL siguen valiendo) pero se marca
            # en el item y en el aviso global.
            item["aviso"] = "texto insuficiente (página JS)"
            insuficientes.append(item["url"])
        if pag.get("aviso"):
            item["aviso"] = (item["aviso"] + "; " if item.get("aviso") else
                             "") + pag["aviso"]
        validos.append(item)

    aviso = ""
    if not validos:
        razones = "; ".join(f"{d['url']}: {d['razon']}" for d in descartados[:5])
        aviso = (f"ningún candidato pasó el centinela para '{consulta}' "
                 f"({len(descartados)} descartados: {razones})")
    elif descartados:
        aviso = f"{len(descartados)} candidato(s) descartados por el centinela o por extracción"
    if insuficientes:
        aviso = (aviso + "; " if aviso else "") + (
            f"{len(insuficientes)} resultado(s) con texto insuficiente "
            f"(página JS sin datos extraídos): {', '.join(insuficientes[:3])}")
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
    # Las que volvieron cortas PERO con datos extraídos del JSON embebido
    # ya entregaron el hecho: Chromium solo las reemplazaría por el texto
    # visible (largo) sin la cifra.
    pendientes = [s for s in lote.sobres
                  if not s.ok
                  or (len((s.valor or {}).get("texto") or "") < _MIN_TEXTO_UTIL
                      and not (s.valor or {}).get("datos"))]
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

    # El launch puede fallar (Chromium no instalado, sandbox, disco). Si la
    # excepción escapa, se van con ella TODOS los sobres HTTP que ya habían
    # salido bien: perder trabajo bueno por no poder hacer el opcional es
    # justo el modo de fallo que este módulo existe para evitar.
    try:
        contexto_pw = sync_playwright()
        p = contexto_pw.__enter__()
        navegador = p.chromium.launch(headless=True)
    except Exception as exc:
        for s in pendientes:
            if not s.ok:
                s.error = f"{s.error}; y Chromium no arrancó ({exc})"[:500]
        return Lote(sobres=sobres)

    try:
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
    finally:
        # El __exit__ del context manager va a mano porque el __enter__ se
        # hizo a mano arriba para poder capturar el fallo del launch.
        try:
            contexto_pw.__exit__(None, None, None)
        except Exception:
            pass
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
