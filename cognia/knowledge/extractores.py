# -*- coding: utf-8 -*-
"""Extractores de DATOS VIVOS de páginas que sin JS son cascarones.

Medido el 2026-08-24: la página de un canal de YouTube le deja a bs4 ~220
chars de texto (menús, avisos de cookies), pero el HTML crudo trae
`ytInitialData` con TODO el dato: '"subscriberCountText":...', cadenas como
"4.63 K suscriptores" / "4.63 mil suscriptores",
'"content":"@theacuaboy170 • 4.63 K suscriptores"' (con caracteres
invisibles de aislamiento bidi alrededor) y <title>the acua boy - YouTube.
Un agente sin Chromium (el venv instalado del producto NO trae playwright)
leía el cascarón y contestaba de memoria. Aquí se raspa el JSON embebido con
regex — cero dependencias externas: re + json + urllib + html.parser — y
navegador._extraer_con_http antepone el resultado al texto como bloque
"DATOS EXTRAIDOS (sitio): clave: valor; ...", así el cascarón igual entrega
el hecho.

Punto de extensión: `registrar(patron_url, fn)`. Cada extractor es una
función (url, html) -> dict | None con la forma

    {"sitio": "youtube", "titulo": "the acua boy",
     "campos": {"handle": "@theacuaboy170", "suscriptores": "4.63 K",
                "suscriptores_n": 4630, ...},
     "resumen": "the acua boy (@theacuaboy170): 4.63 K suscriptores"}

y la regla dura es que NUNCA lanza: si no reconoce nada devuelve None y la
extracción sigue por el camino de siempre. Si un extractor revienta, el
fallo NO se traga: `extraer_datos` devuelve un dict con "aviso" y campos
vacíos, y el navegador lo declara en el resultado.
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request

# ── limpieza común ─────────────────────────────────────────────────────

# YouTube envuelve las cifras en marcas bidi (U+2068 FSI ... U+2069 PDI,
# U+200E LRM) y a veces las serializa escapadas ("⁨") dentro del JSON.
# Se quitan las dos formas ANTES de cualquier regex: "4.63⁩ K" no casa
# con ningún patrón razonable y el centinela cuenta invisibles (>5 = BLOCK).
_INVISIBLES = re.compile("[\u200b\u200c\u200d\u200e\u200f\u2066\u2067\u2068"
                         "\u2069\u202a\u202b\u202c\u202d\u202e\ufeff]")
_INVISIBLES_ESC = re.compile(r"\\u(?:200[b-f]|206[6-9]|202[a-e]|feff)",
                             re.IGNORECASE)


def _limpiar(texto: str) -> str:
    """Sin invisibles/bidi (literales o escapados), NBSP a espacio y espacios
    colapsados. No toca acentos."""
    texto = _INVISIBLES_ESC.sub("", _INVISIBLES.sub("", texto or ""))
    texto = texto.replace("\u00a0", " ").replace("\\u00a0", " ")
    return re.sub(r"[ \t]+", " ", texto).strip()


def _des_json(s: str) -> str:
    """Desescapa una cadena tomada de dentro de un literal JSON ("\\/",
    "\\u00e9"...). Si no es JSON válido se devuelve tal cual: el dato vale
    más que la pureza."""
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace("\\/", "/").replace('\\"', '"')


# ── cifras: "4.63 K" -> 4630 ───────────────────────────────────────────

# Multiplicadores por idioma. "M" en español es millones y "mil" es miles;
# en portugués "mi" es millón. Las claves van en minúscula: se compara
# tras lower().
_MULT = {
    "k": 1_000, "mil": 1_000, "tsd": 1_000,
    "m": 1_000_000, "mill": 1_000_000, "millon": 1_000_000,
    "millón": 1_000_000, "millones": 1_000_000, "mio": 1_000_000,
    "mln": 1_000_000, "mi": 1_000_000, "mn": 1_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "mrd": 1_000_000_000,
}
_RE_CIFRA = re.compile(r"^\s*(\d[\d.,]*(?:\s\d{3})*)\s*([a-záéíóúñ]*)\.?",
                       re.IGNORECASE)


def normalizar_cifra(texto: str):
    """"4.63 K" -> 4630, "305 k" -> 305000, "1.2M" -> 1200000, "5" -> 5,
    "4.63 mil" -> 4630, "4.630" -> 4630, "4,63 mil" -> 4630. None si no se
    entiende (p.ej. "4.63" a secas: un separador con 2 decimales y sin
    escala no es una cuenta de nada).

    La ambigüedad real es el punto/coma: con escala ("4.63 K") es decimal;
    sin escala, "4.630" son miles (grupos de exactamente 3) y "1,234" también.
    Devuelve int; las palabras que no son escala ("suscriptores") se ignoran.
    """
    m = _RE_CIFRA.match(_limpiar(texto or ""))
    if not m:
        return None
    numero = m.group(1).replace(" ", "").rstrip(".,")
    palabra = m.group(2).lower()
    mult = _MULT.get(palabra, 1)
    tiene_punto, tiene_coma = "." in numero, "," in numero
    try:
        if tiene_punto and tiene_coma:
            # Estilo inglés "1,234.5" o alemán "1.234,5": el ÚLTIMO
            # separador es el decimal.
            dec = "." if numero.rfind(".") > numero.rfind(",") else ","
            miles = "," if dec == "." else "."
            valor = float(numero.replace(miles, "").replace(dec, "."))
        elif tiene_punto or tiene_coma:
            sep = "." if tiene_punto else ","
            partes = numero.split(sep)
            if len(partes) > 2 or (mult == 1 and len(partes[-1]) == 3):
                # "1.234.567" o "4.630": separadores de miles
                if any(len(p) != 3 for p in partes[1:]):
                    return None
                valor = float("".join(partes))
            elif mult == 1:
                return None            # "4.63" sin escala: no es una cuenta
            else:
                valor = float(numero.replace(",", "."))
        else:
            valor = float(numero)
    except ValueError:
        return None
    return int(round(valor * mult))


# Palabra-unidad por idioma (YouTube sirve en el idioma del Accept-Language,
# y el agente puede caer en cualquiera).
_PAL_SUSC = (r"(?:suscriptores?|subscribers?|abonn[ée]s?|inscritos?|inscrits?"
             r"|abonnenten|iscritti|assinantes|subskrybent\w*|abone(?:lik)?"
             r"|подписчик\w*|登録者)")
_PAL_VIDEOS = r"(?:v[ií]d[ée]os?|videos?|vídeo|动画|動画)"
_ESCALA = r"(?:millones|mill?[oó]n|mill|mil|mio|mln|mrd|mn|bn|mi|[kKmMbB])?"


def _cifra_en(texto: str, palabra: str):
    """La cifra que precede a `palabra` en `texto` ("4.63 K suscriptores" ->
    "4.63 K"; también "1,2 M de suscriptores"), ya limpia. None si no hay."""
    m = re.search(rf"(\d[\d.,]*\s*{_ESCALA}\.?)\s*(?:de\s+)?{palabra}\b",
                  _limpiar(texto), re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip().rstrip(".")


def _cifra_sola(texto: str):
    """Una cifra con escala al principio del texto, SIN palabra-unidad
    ("4.63 K" partido en runs). Solo se usa cuando la clave JSON ya dice
    qué es la cifra."""
    m = re.match(rf"\s*(\d[\d.,]*\s*{_ESCALA})\b", _limpiar(texto),
                 re.IGNORECASE)
    return m.group(1).strip() if m else None


# ── YouTube ────────────────────────────────────────────────────────────

# Con estas cabeceras YouTube sirve la página completa con ytInitialData y
# SIN el interstitial de consentimiento (medido con curl el 2026-08-24; sin
# la cookie CONSENT redirige a consent.youtube.com y no hay dato).
UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CABECERAS_YOUTUBE = {
    "User-Agent": UA_CHROME,
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}
_RE_YT_HOST = re.compile(r"^https?://(?:www\.|m\.)?youtube\.com(?::\d+)?/",
                         re.IGNORECASE)

# Formas en que ytInitialData serializa un texto: una cadena a secas
# (cabecera nueva del canal), {"simpleText":"..."} con o sin el bloque
# "accessibility" delante, o {"runs":[{"text":".."},...]}. Las tres van
# ANCLADAS a la llave que abre: un ".{0,400}?" suelto pescaba el simpleText
# de la clave VECINA cuando la propia venía en runs, y eso convertía "12
# vídeos" en suscriptores. No se parsea el JSON entero: pesa ~1 MB y en el
# HTML a veces viene truncado.
_STR = r'"((?:[^"\\]|\\.)*)"'


def _texto_yt(html: str, clave: str):
    m = re.search(
        rf'"{clave}"\s*:\s*(?:{_STR}'
        rf'|\{{\s*(?:"accessibility"\s*:\s*\{{.{{0,300}}?\}}\s*\}}\s*,\s*)?'
        rf'"simpleText"\s*:\s*{_STR}'
        rf'|\{{\s*"runs"\s*:\s*\[(.*?)\])',
        html, re.DOTALL)
    if not m:
        return None
    if m.group(3) is not None:
        trozos = re.findall(rf'"text"\s*:\s*{_STR}', m.group(3))
        return _limpiar("".join(_des_json(t) for t in trozos)) or None
    return _limpiar(_des_json(m.group(1) if m.group(1) is not None
                              else m.group(2)))


def _cadena_yt(html: str, clave: str):
    """Valor string de una clave JSON simple ("channelId":"UC...")."""
    m = re.search(rf'"{clave}"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
    return _limpiar(_des_json(m.group(1))) if m else None


def _titulo_yt(html: str):
    m = re.search(
        rf'"channelMetadataRenderer"\s*:\s*\{{\s*"title"\s*:\s*{_STR}', html)
    if m:
        return _limpiar(_des_json(m.group(1)))
    t = _cadena_yt(html, "pageTitle")
    if t:
        return t
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if m:
        t = _limpiar(_html.unescape(m.group(1)))
        return re.sub(r"\s*-\s*YouTube\s*$", "", t) or None
    return None


def _handle_en(texto: str):
    # (?<!\w) deja pasar "/@x" y "@x" y rechaza "correo@dominio".
    m = re.search(r"(?<!\w)@([\w.\-]{2,})", texto or "")
    return "@" + m.group(1).rstrip(".") if m else None


# Claves JSON cuyo valor es un texto que el usuario VE (no plantillas i18n
# como "case1":"1 video", que también son cadenas y confundían la cuenta de
# vídeos). La cifra de un canal solo se acepta si viene en una de estas.
_CLAVES_VISIBLES = r'"(?:content|simpleText|text|label|accessibilityText)"'


def _valores_visibles(html: str, palabra: str) -> list:
    """[(texto, cifra)] de los valores visibles que traen "N <palabra>"."""
    out = []
    for m in re.finditer(rf'{_CLAVES_VISIBLES}\s*:\s*{_STR}', html):
        texto = _des_json(m.group(1))
        cifra = _cifra_en(texto, palabra)
        if cifra:
            out.append((texto, cifra))
    return out


def _bloque_cabecera(html: str) -> str:
    """El trozo de ytInitialData que describe al canal de la PÁGINA:
    "pageHeaderRenderer" (maqueta 2024+) o "c4TabbedHeaderRenderer" (vieja),
    acotado hasta la sección siguiente ("metadata"/channelMetadataRenderer)
    o 12000 chars. Cadena vacía si no hay cabecera (interstitial, error).

    Medido 2026-08-24: fuera de este bloque las cifras son de OTROS. En
    @ThatBoyAqua el primer "subscriberCountText" del documento (27.8 k) es
    de un gridChannelRenderer de canal relacionado y la cabecera dice 305 k;
    en @theacuaboy170 "47 videos" es el badge de una playlist y la cabecera
    dice 138. Por eso la cabecera manda y lo demás es fallback."""
    for clave in ("pageHeaderRenderer", "c4TabbedHeaderRenderer"):
        m = re.search(rf'"{clave}"\s*:\s*\{{', html)
        if not m:
            continue
        ini = m.start()
        fin = min(len(html), ini + 12000)
        # OJO: no acotar por '"metadata":' a secas — la cabecera nueva tiene
        # su PROPIA clave "metadata":{"contentMetadataViewModel":{
        # "metadataRows":[...]}} y ahí van justo suscriptores y vídeos.
        for tope in ('"channelMetadataRenderer"',
                     '"twoColumnBrowseResultsRenderer"'):
            j = html.find(tope, ini + 40, fin)
            if j > 0:
                fin = j
        return html[ini:fin]
    return ""


def _handle_pagina(html: str, url: str):
    """El @handle del canal de la página: de la URL; si no, del canal
    (vanityChannelUrl/ownerUrls de channelMetadataRenderer). El primer
    canonicalBaseUrl del documento va último porque puede ser de un canal
    relacionado."""
    handle = _handle_en(urllib.parse.urlparse(url).path)
    if handle:
        return handle
    for clave in ("vanityChannelUrl", "ownerUrls", "canonicalBaseUrl"):
        m = re.search(rf'"{clave}"\s*:\s*\[?\s*{_STR}', html)
        handle = _handle_en(_des_json(m.group(1))) if m else None
        if handle:
            return handle
    return None


def _campos_canal(html: str, url: str) -> dict:
    """Los campos de la página de UN canal (/@handle, /channel/ID, /c/,
    /user/). Suscriptores, en orden: (1) la cabecera de la página
    (`_bloque_cabecera`); (2) entre los textos visibles "N suscriptores" del
    documento, el que lleva el handle de la PÁGINA (la lista de canales
    "@handle • N suscriptores", donde el primero puede ser ajeno: "Sukh
    Mehra • 120 k" delante de "@theacuaboy170 • 4.63 K"); (3) si todas las
    candidatas coinciden, esa. Si no, NINGUNA: una cifra ajena es peor que
    ninguna. Los vídeos solo salen de la cabecera (fuera de ella son badges
    de playlists o de canales relacionados)."""
    campos = {}
    handle = _handle_pagina(html, url)
    if handle:
        campos["handle"] = handle
    cid = _cadena_yt(html, "externalId") or _cadena_yt(html, "channelId")
    if cid and cid.startswith("UC"):
        campos["canal_id"] = cid

    cabecera = _bloque_cabecera(html)
    susc = None
    if cabecera:
        bruto = _texto_yt(cabecera, "subscriberCountText")
        if bruto and not bruto.startswith("@"):
            susc = _cifra_en(bruto, _PAL_SUSC) or _cifra_sola(bruto)
        if not susc:
            visibles = _valores_visibles(cabecera, _PAL_SUSC)
            susc = visibles[0][1] if visibles else None
    if not susc:
        candidatas = _valores_visibles(html, _PAL_SUSC)
        propias = [c for t, c in candidatas
                   if handle and handle.lower() in t.lower()]
        if propias:
            susc = propias[0]
        elif candidatas and len({c for _, c in candidatas}) == 1:
            susc = candidatas[0][1]
    if susc:
        campos["suscriptores"] = susc
        n = normalizar_cifra(susc)
        if n is not None:
            campos["suscriptores_n"] = n

    videos = None
    if cabecera:
        bruto = (_texto_yt(cabecera, "videosCountText")
                 or _texto_yt(cabecera, "videoCountText"))
        if bruto:
            videos = _cifra_en(bruto, _PAL_VIDEOS)
        if not videos:
            # Solo un valor visible que sea ENTERO la cuenta ("138 vídeos"):
            # las plantillas i18n ("borrar 1 video") también son cadenas.
            for texto, cifra in _valores_visibles(cabecera, _PAL_VIDEOS):
                if re.fullmatch(
                        rf"{re.escape(cifra)}\.?\s*(?:de\s+)?{_PAL_VIDEOS}",
                        _limpiar(texto), re.IGNORECASE):
                    videos = cifra
                    break
    if videos:
        campos["videos"] = videos

    m = re.search(
        rf'"channelMetadataRenderer"\s*:\s*\{{[^{{}}]*?"description"\s*:\s*{_STR}',
        html)
    if m and m.group(1):
        campos["descripcion"] = _limpiar(_des_json(m.group(1)))[:300]
    return campos


def _canales_en_resultados(html: str) -> list:
    """Los bloques "channelRenderer" de una página /results, en orden.
    Cada bloque se acota hasta el siguiente (o 8000 chars): dentro van
    channelId, canonicalBaseUrl, el título y la cifra de suscriptores —
    que YouTube pone unas veces en subscriberCountText y otras (maqueta
    2024+) en videoCountText mientras subscriberCountText lleva el @handle.
    Por eso la cifra se busca por su PALABRA, no por su clave."""
    html = _limpiar(html)
    inicios = [m.start() for m in re.finditer(r'"channelRenderer"\s*:\s*\{', html)]
    canales, vistos = [], set()
    for i, ini in enumerate(inicios):
        fin = inicios[i + 1] if i + 1 < len(inicios) else len(html)
        bloque = html[ini:min(fin, ini + 8000)]
        cid = _cadena_yt(bloque, "channelId")
        base = _cadena_yt(bloque, "canonicalBaseUrl") or ""
        m = re.search(r'"title"\s*:\s*\{\s*"simpleText"\s*:\s*"((?:[^"\\]|\\.)*)"',
                      bloque)
        titulo = _limpiar(_des_json(m.group(1))) if m else ""
        handle = _handle_en(base)
        if not handle:
            sct = _texto_yt(bloque, "subscriberCountText") or ""
            handle = _handle_en(sct) if sct.startswith("@") else None
        url = ("https://www.youtube.com" + base if base.startswith("/")
               else (f"https://www.youtube.com/channel/{cid}" if cid else ""))
        clave = cid or url
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        susc = _cifra_en(bloque, _PAL_SUSC)
        canal = {"titulo": titulo, "handle": handle or "", "url": url,
                 "canal_id": cid or "", "suscriptores": susc or ""}
        n = normalizar_cifra(susc) if susc else None
        if n is not None:
            canal["suscriptores_n"] = n
        videos = _cifra_en(bloque, _PAL_VIDEOS)
        if videos:
            canal["videos"] = videos
        canales.append(canal)
    return canales


def _linea_canal(c: dict) -> str:
    quien = c.get("titulo") or c.get("handle") or c.get("canal_id") or "?"
    if c.get("handle") and c.get("titulo"):
        quien = f"{c['titulo']} ({c['handle']})"
    partes = []
    if c.get("suscriptores"):
        partes.append(f"{c['suscriptores']} suscriptores")
    if c.get("videos"):
        partes.append(f"{c['videos']} vídeos")
    return quien + (": " + ", ".join(partes) if partes else "")


def extraer_youtube(url: str, html: str):
    """Extractor de YouTube: página de canal o página /results (filtro de
    canales). None si el HTML no trae ningún dato reconocible (interstitial
    de consentimiento, página de error, vídeo suelto)."""
    ruta = urllib.parse.urlparse(url).path or "/"
    if ruta.startswith("/results"):
        canales = _canales_en_resultados(html)
        if not canales:
            return None
        campos = {"canales": len(canales)}
        for i, c in enumerate(canales[:10], 1):
            campos[f"canal_{i}"] = _linea_canal(c)
            if c.get("url"):
                campos[f"canal_{i}_url"] = c["url"]
        titulo = _titulo_yt(html) or "Resultados de YouTube"
        return {"sitio": "youtube", "titulo": titulo, "campos": campos,
                "canales": canales,
                "resumen": f"{len(canales)} canal(es): "
                           + "; ".join(_linea_canal(c) for c in canales[:3])}
    if not re.match(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)", ruta):
        return None
    html = _limpiar(html)
    campos = _campos_canal(html, url)
    titulo = _titulo_yt(html)
    # Evidencia que tiene que venir del HTML, no de la URL: el handle sale
    # de la ruta y el <title> lo trae hasta el interstitial de consentimiento
    # ("Antes de ir a YouTube"), que NO es dato.
    if not campos.get("suscriptores") and not campos.get("canal_id"):
        return None
    campos["url"] = url
    resumen = _linea_canal({"titulo": titulo, **campos})
    return {"sitio": "youtube", "titulo": titulo or campos.get("handle") or url,
            "campos": campos, "resumen": resumen}


def _descargar(url: str, cabeceras: dict = None, timeout_s: int = 15) -> str:
    req = urllib.request.Request(url, headers=cabeceras or CABECERAS_YOUTUBE)
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return r.read().decode("utf-8", errors="replace")


def youtube_canal(nombre: str, abrir=None, max_canales: int = 10) -> list:
    """Busca canales de YouTube por nombre y devuelve
    [{titulo, handle, url, suscriptores, suscriptores_n, canal_id}] en el
    orden de YouTube. Usa la página /results con el filtro "canales"
    (sp=EgIQAg%253D%253D), que trae los channelRenderer con la cifra —
    medido 2026-08-24: "the acua boy" -> @theacuaboy170 con 4.63 K, canal
    que ddgs no encontraba. `abrir(url) -> html` inyectable para tests.
    Si la red falla lanza RuntimeError con el motivo (el llamador decide);
    si la página no trae canales devuelve [] — son cosas distintas."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("nombre de canal vacío")
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote_plus(nombre) + "&sp=EgIQAg%253D%253D")
    abrir = abrir or _descargar
    try:
        html = abrir(url)
    except Exception as exc:
        raise RuntimeError(
            f"youtube_canal: no se pudo descargar {url}: "
            f"{type(exc).__name__}: {exc}") from exc
    return _canales_en_resultados(html or "")[:max_canales]


# ── registry ───────────────────────────────────────────────────────────

# (regex de URL compilado, fn(url, html) -> dict | None). Gana el PRIMERO
# que casa por URL; para añadir un sitio: registrar(r"^https?://...", fn).
EXTRACTORES = [
    (_RE_YT_HOST, extraer_youtube),
]


def registrar(patron: str, fn, al_principio: bool = False) -> None:
    """Punto de extensión: añade un extractor para las URLs que casen con
    `patron` (regex sobre la URL final). `al_principio=True` para
    sobreescribir uno existente sin quitarlo."""
    par = (re.compile(patron, re.IGNORECASE), fn)
    if al_principio:
        EXTRACTORES.insert(0, par)
    else:
        EXTRACTORES.append(par)


def cabeceras_para(url: str, ua: str = UA_CHROME) -> dict:
    """Cabeceras HTTP con las que un sitio JS-only sirve el dato (YouTube
    exige la cookie de consentimiento). Para el resto: UA + idioma."""
    if _RE_YT_HOST.match(url or ""):
        return dict(CABECERAS_YOUTUBE, **{"User-Agent": ua})
    return {"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}


def extraer_datos(url: str, html: str):
    """El dict del primer extractor cuya regex casa con `url`, o None si
    ninguno casa o el que casa no reconoce nada. Si el extractor lanza, se
    devuelve {"sitio", "campos": {}, "aviso": ...}: un extractor roto se
    declara, no se esconde tras un None indistinguible de "no había dato"."""
    for rx, fn in EXTRACTORES:
        if not rx.match(url or ""):
            continue
        try:
            return fn(url, html or "")
        except Exception as exc:
            return {"sitio": getattr(fn, "__name__", "?"), "titulo": "",
                    "campos": {}, "resumen": "",
                    "aviso": f"extractor {fn.__name__} falló sobre {url}: "
                             f"{type(exc).__name__}: {exc}"}
    return None


def bloque_datos(datos: dict, max_chars: int = 1500) -> str:
    """El bloque que se antepone al texto de la página:
    "DATOS EXTRAIDOS (youtube): titulo: X; handle: @x; suscriptores: 4.63 K
    (4630); ...". Vacío si no hay campos."""
    campos = (datos or {}).get("campos") or {}
    if not campos:
        return ""
    partes = []
    if datos.get("titulo"):
        partes.append(f"titulo: {datos['titulo']}")
    for k, v in campos.items():
        if k.endswith("_n") or v in ("", None):
            continue
        if k == "suscriptores" and campos.get("suscriptores_n") is not None:
            v = f"{v} ({campos['suscriptores_n']})"
        partes.append(f"{k}: {v}")
    linea = f"DATOS EXTRAIDOS ({datos.get('sitio', '?')}): " + "; ".join(partes)
    if len(linea) > max_chars:
        linea = linea[:max_chars] + " [...]"
    return linea
