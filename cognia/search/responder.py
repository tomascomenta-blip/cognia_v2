# -*- coding: utf-8 -*-
"""Responder una pregunta con CONFIANZA, y si no la hay, ir a buscar.

Es el pegamento entre las tres piezas de `cognia/search`: el modelo propone,
la evidencia dispone y la confianza decide si hay que salir a la web.

EL BUCLE, y el porqué de cada paso:

  1. Se le pregunta al modelo a libro cerrado. NO para creerle: para tener la
     hipótesis y, sobre todo, para que declare si lo sabe o no. Una respuesta
     de memoria arranca con confianza baja por diseño
     (`confianza.CONFIANZA_SIN_FUENTE`), no importa lo segura que suene.
  2. Si eso ya alcanza el umbral, se responde. Hoy nunca alcanza sin fuentes,
     y eso es intencional: la vía barata no puede ser también la vía cómoda.
  3. Si no, se investiga: fan-out de consultas -> extracción en paralelo ->
     contexto según el presupuesto de PARED -> respuesta CON cita.
  4. La cita se verifica LITERAL contra la página. Una cita que no está no
     sube la confianza: la baja, porque el modelo acaba de fabricar.

LO QUE NO HACE. No promete acertar más: promete que el número que acompaña a
la respuesta esté construido con señales verificables. Si el banco dice que
la confianza no predice el acierto, los pesos están mal y hay que moverlos
(`confianza.calibracion` es quien lo dice).
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

from cognia.search import confianza as CF
from cognia.search import contexto as CTX
from cognia.search.evidencia import verificar_cita

_TIMEOUT_S = 1800


def _chat(mensajes: list, url: str, max_tokens: int = 800,
          esquema: dict = None, pensar: bool = False) -> str:
    cuerpo = {
        "messages": mensajes,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": bool(pensar)},
    }
    if esquema:
        cuerpo["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "r",
                                                     "schema": esquema,
                                                     "strict": True}}
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    m = d["choices"][0]["message"]
    return (m.get("content") or "").strip()


_ESQUEMA_MEMORIA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["respuesta", "lo_se"],
    "properties": {
        "respuesta": {"type": "string"},
        # Se le pregunta si lo SABE, no cuánta confianza tiene: lo primero es
        # una pregunta sobre el mundo, lo segundo una sobre sí mismo, y los
        # modelos contestan lo segundo con un 0,9 casi siempre.
        "lo_se": {"type": "boolean"},
    },
}

_ESQUEMA_CON_FUENTES = {
    "type": "object",
    "additionalProperties": False,
    "required": ["respuesta", "evidencia", "fuente", "encontrado"],
    "properties": {
        "respuesta": {"type": "string"},
        "evidencia": {"type": "string",
                      "description": "frase LITERAL copiada de la fuente"},
        "fuente": {"type": "string", "description": "la URL exacta"},
        "encontrado": {"type": "boolean"},
    },
}


def _json_de(texto: str) -> dict:
    try:
        return json.loads(texto)
    except Exception:
        m = re.search(r"\{.*\}", texto or "", re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def responder(pregunta: str, url: str = "", presupuesto_s: float = 120.0,
              buscar_fn=None, extraer_fn=None, chat_fn=None) -> CF.Veredicto:
    """Devuelve un Veredicto (valor, confianza, razones, accion, fuentes).

    `buscar_fn`, `extraer_fn` y `chat_fn` son inyectables para poder probar
    esto sin red ni GPU — sin eso, el único test posible sería un e2e lento y
    esta función se quedaría sin red de seguridad.
    """
    if not url:
        try:
            from cognia.agent.model_profiles import url_del_backend
            url = url_del_backend()
        except Exception:
            url = "http://127.0.0.1:8080"
    chat = chat_fn or (lambda ms, **kw: _chat(ms, url, **kw))

    # --- 1. A libro cerrado ------------------------------------------------
    crudo = chat([{"role": "user",
                   "content": (f"{pregunta}\n\nResponde en JSON. Si no lo "
                               f"sabes con certeza, pon lo_se=false: no pasa "
                               f"nada por no saberlo, se va a buscar.")}],
                 max_tokens=400, esquema=_ESQUEMA_MEMORIA)
    memoria = _json_de(crudo)
    valor = (memoria.get("respuesta") or "").strip()

    v = CF.evaluar(valor, apoyos=[])
    if memoria.get("lo_se") is False:
        v.razones.insert(0, "el propio modelo declara que no lo sabe")
    if v.accion == "responder":
        return v                       # hoy inalcanzable sin fuentes: querido

    # --- 2. Investigar -----------------------------------------------------
    if buscar_fn is None:
        from cognia.knowledge.navegador import _buscar_ddg as buscar_fn
    if extraer_fn is None:
        from cognia.knowledge.navegador import extraer_muchas as extraer_fn

    from cognia.search.fanout import buscar_many

    t0 = time.time()
    consultas = _consultas_para(pregunta, chat)
    lote = buscar_many(consultas, por_consulta=6, buscador=buscar_fn)
    urls, vistos = [], set()
    for sobre in lote.ok:
        for cand in (sobre.valor or []):
            u = cand.get("url") or ""
            if u and u not in vistos:
                vistos.add(u)
                urls.append(u)
    if not urls:
        # Buscar y no encontrar NADA no deja la confianza donde estaba: la
        # hipótesis de memoria se queda sin el respaldo que se fue a buscar.
        # (La rama anterior comparaba 0,30 < 0,25, que nunca se cumple: era
        # código muerto que aparentaba una política.)
        v.razones.append(f"la búsqueda no devolvió URLs ({lote.resumen()})")
        v.accion = "abstenerse"
        return v

    # Se ARRANCA barato aunque el presupuesto dé para más: la política que la
    # medición respalda es pagar `medio` en el caso común y subir solo si no
    # encuentra. `modo_para` a secas devolvía el modo más ancho que cupiera y
    # entonces el escalado no llegaba a existir nunca (lo cazó el test).
    # COGNIA_SEARCH_MODO sigue mandando si alguien fija uno a mano.
    cabe = CTX.modo_para(max(presupuesto_s - (time.time() - t0), 15))
    pedido = CTX.modo_por_nombre("medio")
    modo = pedido if pedido.tokens <= cabe.tokens else cabe
    return _con_contexto(pregunta, urls, modo, chat, extraer_fn, v, t0,
                         presupuesto_s)


def _con_contexto(pregunta, urls, modo, chat, extraer_fn, v, t0,
                  presupuesto_s, escalado=False):
    """Lee páginas con ese modo y contesta; ESCALA si no encuentra.

    El escalado sale de una medición, no de una intuición (banco b5 del
    2026-08-15, con la aguja en posición sorteada y no siempre arriba):

        estrecho  0/5     2,3 s
        medio     2/5    27,6 s     <- solo acierta si la página cae en su top-12
        ancho     5/5   152,2 s

    O sea: `medio` es 5,5× más barato pero depende de que el ranking ponga la
    página buena arriba, y el ranking de la casa es léxico, sin reranker. La
    respuesta no es elegir uno de los dos a ciegas: es pagar `medio` en el
    caso común y **subir a `ancho` solo cuando medio dice que no encontró**.
    Un no-encontrado es barato de detectar (`encontrado=false`) y es
    exactamente la señal de que hacía falta más contexto.
    """
    lote_pag = extraer_fn(urls[:modo.paginas], cap=5)
    paginas = [{"url": s.spec, "texto": (s.valor or {}).get("texto", "")}
               for s in lote_pag.ok if (s.valor or {}).get("texto")]
    if not paginas:
        v.razones.append(f"ninguna página se pudo leer ({lote_pag.resumen()})")
        return v

    dadas = CTX.repartir(paginas, modo)
    bloques = "\n\n".join(f"=== {p['url']} ===\n{p['texto']}" for p in dadas)
    crudo2 = chat(
        [{"role": "user",
          "content": (f"{bloques}\n\n===\nPregunta: {pregunta}\n"
                      f"Responde en JSON. `evidencia` tiene que ser una frase "
                      f"COPIADA LITERAL de una de las fuentes de arriba (se "
                      f"verifica carácter a carácter) y `fuente` su URL. Si la "
                      f"respuesta no está en las fuentes, encontrado=false.")}],
        max_tokens=800, esquema=_ESQUEMA_CON_FUENTES)
    hallado = _json_de(crudo2)

    if not hallado.get("encontrado"):
        v.razones.append(f"leí {len(dadas)} páginas ({modo.nombre}) y la "
                         f"respuesta no estaba en ellas")
        # ESCALAR: si con `medio` no apareció y queda presupuesto, vale la
        # pena pagar `ancho` — en el banco eso es la diferencia entre 2/5 y
        # 5/5. Una sola vez: si con 40 páginas tampoco está, insistir es
        # gastar 152 s para repetir el mismo "no".
        resta = presupuesto_s - (time.time() - t0)
        if (not escalado and modo.nombre != CTX.ANCHO.nombre
                and len(urls) > modo.paginas
                and resta > CTX.segundos_de(CTX.ANCHO)):
            v.razones.append(f"escalo a {CTX.ANCHO.nombre} "
                             f"({CTX.ANCHO.paginas} páginas)")
            return _con_contexto(pregunta, urls, CTX.ANCHO, chat, extraer_fn,
                                 v, t0, presupuesto_s, escalado=True)
        return v

    # --- 3. La cita se verifica, no se cree --------------------------------
    fuente = (hallado.get("fuente") or "").strip()
    texto_fuente = next((p["texto"] for p in dadas if p["url"] == fuente), "")
    chequeo = verificar_cita(hallado.get("evidencia") or "", texto_fuente)
    apoyos = [{"source_url": fuente, "evidencia_verificada": chequeo["ok"]}]
    final = CF.evaluar((hallado.get("respuesta") or "").strip(), apoyos)
    final.razones.append(f"modo {modo.nombre}: {len(dadas)} páginas, "
                         f"{time.time() - t0:.0f}s")
    if escalado:
        # El veredicto final se arma de cero desde las señales, así que la
        # nota del escalado hay que traerla: sin ella, el informe diría
        # "modo ancho" sin contar que se pagó medio primero, y el coste real
        # de la respuesta quedaría subdeclarado.
        final.razones.append("escalo a ancho tras no encontrarla en medio")
    if not chequeo["ok"]:
        # Fabricar una cita no es neutro: es evidencia de que este registro
        # concreto no es de fiar, así que además de no sumar, se marca.
        final.razones.insert(0, f"CITA NO VERIFICADA: {chequeo['razon']}")
    return final


def _consultas_para(pregunta: str, chat) -> list:
    """3 consultas de buscador para una pregunta. Degrada a la pregunta
    pelada si el modelo no colabora: quedarse sin buscar por no saber
    reformular sería el peor de los dos mundos."""
    esquema = {"type": "object", "additionalProperties": False,
               "required": ["consultas"],
               "properties": {"consultas": {"type": "array",
                                            "items": {"type": "string"}}}}
    try:
        d = _json_de(chat(
            [{"role": "user",
              "content": (f"Pregunta: {pregunta}\n\nDame 3 consultas de "
                          f"buscador (palabras clave, sin comillas ni "
                          f"operadores booleanos) que sirvan para "
                          f"responderla. JSON.")}],
            max_tokens=300, esquema=esquema))
        cs = [c.strip() for c in (d.get("consultas") or []) if c.strip()]
        return cs[:3] or [pregunta]
    except Exception:
        return [pregunta]
