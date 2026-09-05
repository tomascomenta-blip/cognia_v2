# -*- coding: utf-8 -*-
"""Extracción SIN modelo: de un mensaje (user/assistant/tool) a 0..n `Memoria`.

Reglas por texto en español (y algo de inglés) con la escala de importancia del
contrato (PRIORIDAD). Es deliberadamente conservadora: devuelve [] para el relleno
("ok", "dale", listados) porque cada memoria falsa cuesta tokens en cada rebuild.
NUNCA lanza: cualquier fallo se registra con logging.warning y devuelve [].

Formatos que reconoce (los produce scripts/memoria_larga/generar_dataset.py y el
arnés real):
  user       "Decisión: para la X usamos Y. Motivo: M."
             "Cambio de decisión: la X deja de ser A y pasa a ser B, porque M."
             "Restricción, no negociable: T." / "nunca ..." / "prohibido ..."
             "Aparte, en el proyecto del vecino usan ... no aplica" (distractor → nota imp 1)
  assistant  "Arreglado ...: el problema era ...; ahora ..." (solucion) · "voy a usar" (decision)
             "pendiente/falta/próximo paso/TODO" (pendiente)
  tool       "RESULTADO tests: rc=1 12 passed, 1 failed\\nFAILED tests/..." (error)
             "RESULTADO leer_archivo ruta:\\n   1| def f(...):" (fichero + codigo por símbolo)
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata

from . import Memoria, NIVEL_POR_TIPO

logger = logging.getLogger(__name__)

CHARS_POR_TOKEN = 3.7          # medido contra /tokenize del server (00_DIAGNOSTICO.md)
MAX_RESUMEN = 200
MAX_LINEAS_CUERPO = 12         # líneas del cuerpo que se guardan por símbolo

# Artículos y muletillas que se quitan de la entidad para que "la base de datos" y
# "base de datos" sean la MISMA clave en `por_entidad`.
_ARTICULOS = ("el ", "la ", "los ", "las ", "un ", "una ", "unos ", "unas ", "nuestro ", "nuestra ",
              "nuestros ", "nuestras ", "the ", "our ", "a ", "an ")

_RE_FICHERO = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|js|ts|tsx|jsx|md|json|yaml|yml|toml|txt|html|css|sql|sh|ps1|cfg|ini|lua))\b")
_RE_LINEA_CODIGO = re.compile(r"^\s*(\d+)\|\s?(.*)$")
_RE_DEF = re.compile(r"^(\s*)(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)\s*(\([^)]*\))?\s*(?:->\s*[^:]+)?:?")

_CORTOS = {"ok", "dale", "sí", "si", "no", "va", "bien", "listo", "gracias", "seguí", "segui",
           "continuá", "continua", "continuá, no te frenes", "adelante", "perfecto", "genial"}


# ── utilidades públicas ─────────────────────────────────────────────────────
def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, espacios colapsados: base del hash y de las comparaciones."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def hash_contenido(texto: str) -> str:
    return hashlib.sha1(normalizar(texto).encode("utf-8")).hexdigest()


def estimar_tokens(texto: str) -> int:
    return int(len(texto or "") / CHARS_POR_TOKEN) + 1


def normalizar_entidad(texto: str) -> str:
    """'la Base de Datos' → 'base de datos'. Sin tildes para que sea clave estable."""
    t = normalizar(texto).strip(" .,;:")
    cambio = True
    while cambio:
        cambio = False
        for a in _ARTICULOS:
            if t.startswith(a):
                t = t[len(a):]
                cambio = True
    return t.strip(" .,;:")


def normalizar_valor(texto: str) -> str:
    """Los valores conservan mayúsculas (se muestran al usuario), solo se recortan."""
    return re.sub(r"\s+", " ", (texto or "")).strip(" .,;:")


def ficheros_en(texto: str) -> list[str]:
    vistos: list[str] = []
    for m in _RE_FICHERO.findall(texto or ""):
        if m not in vistos:
            vistos.append(m)
    return vistos[:20]


def recortar(texto: str, tope: int = MAX_RESUMEN) -> str:
    t = re.sub(r"\s+", " ", (texto or "")).strip()
    return t if len(t) <= tope else t[:tope - 1].rstrip() + "…"


def extraer_simbolos(texto: str) -> list[dict]:
    """Parsea la salida de leer_archivo (`N| código`, o código sin numerar).

    Devuelve dicts con: nombre, clase (clase contenedora si es un método, '' si no),
    tipo ('def'|'class'), fichero, linea, firma, doc (docstring de las líneas
    siguientes) y cuerpo (hasta MAX_LINEAS_CUERPO líneas, sin numerar).
    """
    fichero = ""
    cab = re.match(r"^\s*RESULTADO\s+\w+\s+([^\s:]+):?", texto or "")
    if cab:
        fichero = cab.group(1)
    lineas: list[tuple[int, str]] = []
    for i, cruda in enumerate((texto or "").splitlines(), 1):
        m = _RE_LINEA_CODIGO.match(cruda)
        if m:
            lineas.append((int(m.group(1)), m.group(2)))
        elif cab and i == 1:
            continue                                  # la cabecera "RESULTADO leer_archivo x:"
        else:
            lineas.append((i, cruda.rstrip("\n")))
    simbolos: list[dict] = []
    pila_clases: list[tuple[int, str]] = []          # (indentación, nombre) de clases abiertas
    for idx, (num, linea) in enumerate(lineas):
        m = _RE_DEF.match(linea)
        if not m:
            continue
        indent = len(m.group(1).expandtabs(4))
        kind, nombre, args = m.group(2), m.group(3), m.group(4) or ""
        while pila_clases and pila_clases[-1][0] >= indent:
            pila_clases.pop()
        contenedora = pila_clases[-1][1] if pila_clases else ""
        # Docstring: la primera línea no vacía tras la firma que empiece por comillas triples.
        doc_lineas, cuerpo, j = [], [], idx + 1
        en_doc, cerrado = False, False
        while j < len(lineas):
            _n, l = lineas[j]
            s = l.strip()
            if not en_doc and not doc_lineas and not cuerpo:
                if s.startswith(('"""', "'''")):
                    comillas = s[:3]
                    resto = s[3:]
                    if resto.endswith(comillas) and len(resto) >= 3:
                        doc_lineas.append(resto[:-3].strip())
                        cerrado = True
                    else:
                        doc_lineas.append(resto.strip())
                        en_doc = True
                    j += 1
                    continue
                if s == "":
                    j += 1
                    continue
            if en_doc:
                if s.endswith(('"""', "'''")):
                    doc_lineas.append(s[:-3].strip())
                    en_doc = False
                    cerrado = True
                else:
                    doc_lineas.append(s)
                j += 1
                continue
            # cuerpo: hasta que baje la indentación a la del def (fin del bloque) o tope
            ind_l = len(l) - len(l.lstrip(" \t"))
            if s and ind_l <= indent:
                break
            cuerpo.append(l)
            if len(cuerpo) >= MAX_LINEAS_CUERPO:
                break
            j += 1
        while cuerpo and not cuerpo[-1].strip():   # sin líneas en blanco de cola
            cuerpo.pop()
        if kind == "class":
            pila_clases.append((indent, nombre))
        simbolos.append({"nombre": nombre, "clase": contenedora, "tipo": kind, "fichero": fichero,
                         "linea": num, "firma": f"{kind} {nombre}{args}",
                         "doc": " ".join(x for x in doc_lineas if x).strip() if (doc_lineas and (cerrado or en_doc)) else "",
                         "cuerpo": cuerpo})
    return simbolos


# ── construcción de la memoria ──────────────────────────────────────────────
def _nueva(tipo: str, contenido: str, *, fuente: str, task_id: str, session_id: str, paso: int,
           importancia: int, resumen: str = "", entidad: str = "", valor: str = "", tags=(),
           entidades=(), referencias=(), confianza: float = 0.8) -> Memoria:
    contenido = (contenido or "").strip()
    ents = list(dict.fromkeys(list(entidades) + ficheros_en(contenido)))
    return Memoria(tipo=tipo, contenido=contenido, nivel=NIVEL_POR_TIPO.get(tipo, 2),
                   resumen=recortar(resumen or contenido), fuente=fuente, task_id=task_id,
                   session_id=session_id, paso=paso, importancia=importancia, confianza=confianza,
                   tags=list(dict.fromkeys(t for t in tags if t)), entidades=ents,
                   entidad=entidad, valor=valor, referencias=list(referencias),
                   hash=hash_contenido(contenido), tokens=estimar_tokens(contenido))


def extraer(role: str, texto: str, *, tool: str | None = None, task_id: str = "", session_id: str = "",
            paso: int = 0, ok: bool | None = None) -> list[Memoria]:
    """Nunca lanza: un fallo de regla se registra y devuelve []."""
    try:
        texto = texto or ""
        if not texto.strip():
            return []
        comun = dict(task_id=task_id, session_id=session_id, paso=paso)
        if role == "user":
            return _de_usuario(texto, **comun)
        if role == "assistant":
            return _de_asistente(texto, **comun)
        if role == "tool":
            return _de_tool(texto, tool=tool, ok=ok, **comun)
        return []
    except Exception as e:  # noqa: BLE001 — el contrato exige no lanzar; se avisa
        logger.warning("memoria_larga.extraer(%s, tool=%s) falló: %s", role, tool, e)
        return []


# ── user ────────────────────────────────────────────────────────────────────
_RE_PARA_USAMOS = re.compile(r"para\s+(?:la|el|los|las)?\s*(.+?)\s+(?:usamos|usaremos|vamos a usar|usá|usar|elegimos|va)\s+(.+?)(?:[.;\n]|$)", re.I)
_RE_USAMOS_PARA = re.compile(r"(?:usamos|usaremos|vamos a usar|elegimos)\s+(.+?)\s+(?:para|como)\s+(?:la|el|los|las)?\s*(.+?)(?:[.;,\n]|$)", re.I)
_RE_CAMBIO = re.compile(r"(?:la|el|los|las)?\s*(.+?)\s+deja(?:n)? de ser\s+(.+?)\s+y pasa(?:n)? a ser\s+(.+?)(?:,\s*porque\s+(.+?))?(?:[.;\n]|$)", re.I)
_RE_MOTIVO = re.compile(r"motivo:\s*(.+?)(?:[.;\n]|$)", re.I)
_RE_ES = re.compile(r"(?:la|el)\s+(.+?)\s+(?:es|será|sera)\s+([A-Z][\w+ .-]{1,40}?)(?:[.;,\n]|$)")


def _de_usuario(texto: str, *, task_id: str, session_id: str, paso: int) -> list[Memoria]:
    n = normalizar(texto)
    comun = dict(fuente="user", task_id=task_id, session_id=session_id, paso=paso)
    if len(n) < 12 or n.strip("!¡¿?.") in _CORTOS:
        return []
    # 1. Distractor explícito: se guarda con importancia mínima para poder responder
    #    "eso era del vecino", pero que nunca gane en el reranking.
    if any(k in n for k in ("no aplica", "solo un comentario", "sólo un comentario", "proyecto del vecino",
                            "aparte,", "no es para este proyecto", "not relevant here")):
        return [_nueva("nota", texto, importancia=1, confianza=0.5, tags=["distractor", "user"], **comun)]
    memorias: list[Memoria] = []
    # 2. Cambio de decisión: la X deja de ser A y pasa a ser B, porque M.
    #    Se quita el rótulo ("Cambio de decisión:") para que no se cuele en la entidad.
    sin_rotulo = re.sub(r"^\s*[^:\n]{0,40}:\s*", "", texto, count=1)
    m = _RE_CAMBIO.search(sin_rotulo)
    if m:
        entidad, viejo, nuevo, motivo = normalizar_entidad(m.group(1)), normalizar_valor(m.group(2)), \
            normalizar_valor(m.group(3)), (m.group(4) or "").strip(" .")
        resumen = f"{entidad}: {viejo} → {nuevo}" + (f" (porque {motivo})" if motivo else "")
        memorias.append(_nueva("decision", texto, importancia=5, resumen=resumen, entidad=entidad, valor=nuevo,
                               tags=["decision", "cambio", "user"], entidades=[entidad], confianza=0.9, **comun))
        return memorias
    # 3. Decisión: "para la X usamos Y" / "usamos Y para la X"
    m = _RE_PARA_USAMOS.search(texto) or None
    entidad = valor = ""
    if m:
        entidad, valor = normalizar_entidad(m.group(1)), normalizar_valor(m.group(2))
    else:
        m2 = _RE_USAMOS_PARA.search(texto)
        if m2:
            valor, entidad = normalizar_valor(m2.group(1)), normalizar_entidad(m2.group(2))
    es_decision = bool(entidad and valor) or any(k in n for k in ("decision:", "decidimos", "decidido", "queda decidido", "decision final"))
    if es_decision:
        if not (entidad and valor):
            m3 = _RE_ES.search(texto)
            if m3:
                entidad, valor = normalizar_entidad(m3.group(1)), normalizar_valor(m3.group(2))
        mot = _RE_MOTIVO.search(texto)
        motivo = mot.group(1).strip() if mot else ""
        resumen = (f"{entidad} = {valor}" if entidad and valor else recortar(texto)) + (f" (motivo: {motivo})" if motivo else "")
        memorias.append(_nueva("decision", texto, importancia=5, resumen=resumen, entidad=entidad, valor=valor,
                               tags=["decision", "user"], entidades=[entidad] if entidad else [], confianza=0.9, **comun))
    # 4. Restricción: puede convivir con una decisión en el mismo mensaje.
    if any(k in n for k in ("restriccion", "no negociable", "nunca ", "jamas", "prohibido", "no instalar", "no borrar",
                            "no instales", "no borres", "no toques", "no tocar", "never ", "do not ", "don't ")):
        cuerpo = re.sub(r"^\s*restricci[oó]n[^:]*:\s*", "", texto, flags=re.I).strip()
        memorias.append(_nueva("restriccion", texto, importancia=5, resumen=cuerpo, tags=["restriccion", "user"],
                               confianza=0.95, **comun))
    if memorias:
        return memorias
    # 5. Objetivo: el encargo. Primer mensaje largo o verbos de encargo.
    if paso <= 1 and len(n) >= 60 or any(k in n for k in (
            "quiero que", "construi", "implementa", "vamos a construir", "vamos a hacer", "vamos a implementar",
            "necesito que", "hace que", "hacé que", "crea ", "creá ", "objetivo:", "tarea:", "build ", "implement ")):
        return [_nueva("objetivo", texto, importancia=5, tags=["objetivo", "user"], confianza=0.9, **comun)]
    # 6. Mensajes de usuario largos sin señal: nota secundaria (no se pierden del todo).
    if len(n) >= 300:
        return [_nueva("nota", texto, importancia=2, tags=["user"], confianza=0.6, **comun)]
    return []


# ── assistant ───────────────────────────────────────────────────────────────
_RE_VOY_A_USAR = re.compile(r"(?:voy a usar|elijo|decido usar|opto por|uso)\s+(.+?)(?:\s+(?:para|como)\s+(?:la|el|los|las)?\s*(.+?))?(?:[.;,\n]|$)", re.I)


def _de_asistente(texto: str, *, task_id: str, session_id: str, paso: int) -> list[Memoria]:
    n = normalizar(texto)
    comun = dict(fuente="assistant", task_id=task_id, session_id=session_id, paso=paso)
    if len(n) < 12:
        return []
    ficheros = ficheros_en(texto)
    # "ahora" solo cuenta como señal si acompaña a otra marca de arreglo (es demasiado común).
    fuerte = any(k in n for k in ("arreglado", "arregle", "solucion", "solucionado", "el problema era", "la causa",
                                  "corregido", "corregi", "fixed", "the fix", "root cause", "el fallo era", "el bug era"))
    if fuerte or ("ahora " in n and any(k in n for k in ("funciona", "pasa", "pasan", "normalizo", "ya no", "works"))):
        m = re.search(r"(?:el problema era|la causa (?:era|es)|the fix was)\s+(.+?)(?:[.;\n]|$)", texto, re.I)
        resumen = f"solución: {m.group(1).strip()}" if m else recortar(texto)
        return [_nueva("solucion", texto, importancia=4, resumen=resumen, tags=["solucion", "assistant"],
                       entidades=ficheros, confianza=0.85, **comun)]
    if any(k in n for k in ("decido", "voy a usar", "elijo", "opto por", "decision:")):
        m = _RE_VOY_A_USAR.search(texto)
        entidad, valor = "", ""
        if m:
            valor = normalizar_valor(m.group(1))
            entidad = normalizar_entidad(m.group(2) or "")
        resumen = f"{entidad} = {valor}" if entidad and valor else recortar(texto)
        return [_nueva("decision", texto, importancia=4, resumen=resumen, entidad=entidad, valor=valor,
                       tags=["decision", "assistant"], entidades=ficheros, confianza=0.75, **comun)]
    if any(k in n for k in ("pendiente", "falta ", "faltan ", "proximo paso", "proximos pasos", "todo:", "queda por",
                            "next step", "to do")):
        return [_nueva("pendiente", texto, importancia=3, tags=["pendiente", "assistant"], entidades=ficheros,
                       confianza=0.7, **comun)]
    if len(n) >= 400 and ficheros:
        return [_nueva("nota", texto, importancia=2, tags=["assistant"], entidades=ficheros, confianza=0.6, **comun)]
    return []


# ── tool ────────────────────────────────────────────────────────────────────
_RE_PASSED = re.compile(r"(\d+)\s+passed", re.I)
_RE_RUTA_CABECERA = re.compile(r"^\s*RESULTADO\s+\w+\s+([^\s:]+)", re.I)
_TOOLS_TEST = ("tests", "ejecutar", "pytest", "run", "bash", "shell", "powershell", "ejecutar_comando")
_TOOLS_LEER = ("leer_archivo", "leer_lote", "leer", "read_file", "leer_entero")
_TOOLS_ESCRIBIR = ("escribir_archivo", "editar_archivo", "escribir", "editar", "write_file", "edit_file", "parchear")
_TOOLS_HECHO = ("buscar", "http_get", "buscar_web", "web", "grep", "buscar_en_archivos", "search")


def _primera_linea_error(texto: str) -> bool:
    primera = texto.strip().splitlines()[0] if texto.strip() else ""
    return bool(re.search(r"rc=[1-9]\d*|\bfailed\b|\bFAILED\b|Traceback|\bError\b|\bERROR\b|exit code [1-9]", primera))


def _de_tool(texto: str, *, tool: str | None, ok: bool | None, task_id: str, session_id: str, paso: int) -> list[Memoria]:
    tool = (tool or "").strip()
    if not tool:
        m = re.match(r"^\s*RESULTADO\s+(\w+)", texto)
        tool = m.group(1) if m else ""
    fuente = f"tool:{tool or 'desconocida'}"
    comun = dict(fuente=fuente, task_id=task_id, session_id=session_id, paso=paso)
    ficheros = ficheros_en(texto)
    if tool == "listar" or tool.startswith("listar"):
        return []                                   # ruido puro: un listado no es una memoria
    # Error en cualquier tool: primera línea con rc/FAILED/Traceback, o el arnés dice ok=False.
    fallo = ok is False or _primera_linea_error(texto)
    if tool in _TOOLS_TEST or fallo:
        if fallo:
            lineas = [l for l in texto.splitlines() if l.strip()]
            linea_fail = next((l for l in lineas if l.lstrip().startswith(("FAILED", "ERROR", "Traceback")) or "Error" in l), "")
            resumen = linea_fail.strip() or (lineas[0] if lineas else "error")
            tags = ["error", tool] + re.findall(r"\b([A-Z][a-z]+Error)\b", texto)[:3]
            return [_nueva("error", texto, importancia=4, resumen=resumen, tags=tags, entidades=ficheros,
                           confianza=0.9, **comun)]
        if tool in _TOOLS_TEST:
            m = _RE_PASSED.search(texto)
            resumen = f"{m.group(1)} passed" if m else recortar(texto.splitlines()[0] if texto.strip() else "ok")
            return [_nueva("test", texto, importancia=2, resumen=resumen, tags=["test", tool], entidades=ficheros,
                           confianza=0.9, **comun)]
    if tool in _TOOLS_LEER:
        m = _RE_RUTA_CABECERA.match(texto)
        ruta = m.group(1) if m else (ficheros[0] if ficheros else "")
        salida = [_nueva("fichero", texto if len(texto) <= 1200 else texto[:1200], importancia=2,
                         resumen=f"leído {ruta}" if ruta else "fichero leído", entidad=ruta, tags=["fichero", tool],
                         entidades=[ruta] if ruta else [], referencias=[ruta] if ruta else [], confianza=0.9, **comun)]
        for s in extraer_simbolos(texto):
            cuerpo = "\n".join([s["firma"] + ":"] + ([f'    """{s["doc"]}"""'] if s["doc"] else []) + s["cuerpo"])
            resumen = f"{s['firma']} en {ruta or s['fichero']}" + (f": {s['doc']}" if s["doc"] else "")
            # Un simbolo SIN docstring es casi siempre relleno (helpers, tests);
            # con docstring es codigo que alguien quiso explicar (banco 2026-09-04:
            # 900 de 1.400 memorias eran `def` de relleno a importancia 3).
            salida.append(_nueva("codigo", cuerpo, importancia=3 if s["doc"] else 2, resumen=resumen, entidad=s["nombre"],
                                 valor=ruta or s["fichero"], tags=["codigo", s["tipo"], tool],
                                 entidades=[s["nombre"], ruta or s["fichero"]], referencias=[ruta or s["fichero"]],
                                 confianza=0.95, **comun))
        return salida
    if tool in _TOOLS_ESCRIBIR:
        m = _RE_RUTA_CABECERA.match(texto)
        ruta = m.group(1) if m else (ficheros[0] if ficheros else "")
        return [_nueva("fichero", texto if len(texto) <= 600 else texto[:600], importancia=3,
                       resumen=f"escrito {ruta}" if ruta else recortar(texto), entidad=ruta, tags=["fichero", tool, "escrito"],
                       entidades=[ruta] if ruta else [], referencias=[ruta] if ruta else [], confianza=0.9, **comun)]
    if tool in _TOOLS_HECHO:
        return [_nueva("hecho", texto[:300], importancia=2, tags=["hecho", tool], entidades=ficheros, confianza=0.6, **comun)]
    return []


__all__ = ["extraer", "extraer_simbolos", "hash_contenido", "normalizar", "normalizar_entidad",
           "normalizar_valor", "estimar_tokens", "ficheros_en", "recortar", "CHARS_POR_TOKEN"]
