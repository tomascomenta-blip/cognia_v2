"""
cognia/enrutador.py
===================
Enrutado por INFERENCIA sobre todo el catalogo (goal 2026-07-21).

El dueño: "que Cognia infiera sobre TODAS sus herramientas y comandos; que
deje de depender de palabras clave y los use ella misma".

Antes: texto libre -> regex de intents (rapido pero ciego: solo casaba
patrones escritos a mano) -> si no casaba, CHAT. Los ~60 comandos "/" solo
se usaban si el usuario los tecleaba.

Ahora: cuando las reglas rapidas no reconocen una accion, el PROPIO MODELO
lee el mensaje + el catalogo completo (comandos "/" con sus descripciones y
las capacidades del agente) y ELIGE la ruta:

    CHAT               -> conversacion normal (respuesta directa)
    AGENTE             -> tarea de archivos/sistema/web (loop de tools)
    /comando <args>    -> un comando del catalogo, con sus argumentos

La decision del modelo se VALIDA (solo comandos que existen; formato
estricto; ante cualquier duda -> CHAT, que es el fallback inofensivo). El
comando elegido se reinyecta al REPL como si el usuario lo hubiera tecleado,
asi TODO el catalogo queda disponible por lenguaje natural.

Concreto: 3 funciones planas. Sin estado, sin clases. Kill-switch:
COGNIA_ENRUTADOR=0.
"""
from __future__ import annotations

import os
import re

# Comandos que el enrutador tiene PROHIBIDO elegir solo (destructivos, de
# salida, o que necesitan intencion explicita del usuario).
_VETADOS = {"/salir", "/exit", "/quit", "/limpiar", "/reset", "/borrar",
            "/apagar", "/shutdown", "/shell-kill"}


def activo() -> bool:
    return os.environ.get("COGNIA_ENRUTADOR", "1").strip().lower() not in (
        "0", "off", "false", "no")


_cache_catalogo: str | None = None


def catalogo_compacto(cmd_descriptions: dict) -> str:
    """El catalogo '/' en una linea por comando (nombre + descripcion corta),
    apto para el prompt del enrutador. Cacheado (el catalogo no cambia en
    runtime)."""
    global _cache_catalogo
    if _cache_catalogo is not None:
        return _cache_catalogo
    lineas = []
    for cmd, desc in sorted(cmd_descriptions.items()):
        if cmd in _VETADOS:
            continue
        d = re.sub(r"\s+", " ", str(desc)).strip()[:90]
        lineas.append(f"{cmd} — {d}")
    _cache_catalogo = "\n".join(lineas)
    return _cache_catalogo


_PROMPT = """Eres el enrutador interno de Cognia. Lee el mensaje del usuario y elige UNA ruta:

- CHAT: conversacion, opinion, o pregunta que se responde hablando.
- AGENTE: tarea concreta sobre archivos, sistema, apps o web (el agente tiene herramientas: leer/escribir archivos, ejecutar comandos, abrir apps/URLs, buscar, capturar pantalla, click, teclear).
- Un comando del catalogo si encaja MEJOR que el chat y que el agente.

Catalogo de comandos:
{catalogo}

Reglas:
- Responde SOLO una linea: "RUTA: CHAT" o "RUTA: AGENTE" o "RUTA: /comando argumentos".
- Elige un /comando SOLO si el mensaje pide claramente esa capacidad.
- Ante la duda, RUTA: CHAT.

Ejemplos:
- "muestrame tus estadisticas" -> RUTA: /stats
- "piensa muy a fondo y resuelve: <problema>" -> RUTA: /pensar <problema>
- "investiga sobre X" -> RUTA: /investigar X
- "hazme un programa que ordene numeros" -> RUTA: /crear programa que ordena numeros
- "borra la ultima linea del archivo notas.txt" -> RUTA: AGENTE
- "como estas hoy?" -> RUTA: CHAT

Mensaje del usuario: {mensaje}
RUTA:"""


def decidir(mensaje: str, infer_fn, catalogo_txt: str) -> tuple[str, str]:
    """
    ("chat"|"agente"|"comando", extra) — extra es la linea "/cmd args" cuando
    la ruta es comando. infer_fn(prompt) -> str (el modelo residente).
    Cualquier fallo o salida rara -> ("chat", "").
    """
    try:
        crudo = infer_fn(_PROMPT.format(catalogo=catalogo_txt,
                                        mensaje=mensaje.strip()[:600])) or ""
    except Exception:
        return "chat", ""
    # primera linea util; tolera que el modelo repita "RUTA:" o no
    linea = ""
    for l in crudo.splitlines():
        l = l.strip()
        if l:
            linea = re.sub(r"^RUTA\s*:\s*", "", l, flags=re.I).strip()
            break
    if not linea:
        return "chat", ""
    if re.fullmatch(r"chat\.?", linea, re.I):
        return "chat", ""
    if re.fullmatch(r"agente\.?", linea, re.I):
        return "agente", ""
    # el modelo a veces omite la barra ("RUTA: stats"): si el primer token
    # con "/" delante existe en el catalogo, se acepta igual (medido 2026-07-21)
    if not linea.startswith("/"):
        tok = linea.split()[0].rstrip(".,;:").lower()
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,24}", tok) and \
                re.search(rf"^/{re.escape(tok)} —", catalogo_txt, re.M):
            linea = "/" + linea
    if linea.startswith("/"):
        cmd = linea.split()[0].rstrip(".,;:")
        # VALIDACION dura: el comando debe existir en el catalogo y no estar
        # vetado — el modelo no puede inventar ni elegir destructivos.
        if cmd in _VETADOS:
            return "chat", ""
        if re.search(rf"^{re.escape(cmd)} —", catalogo_txt, re.M):
            resto = linea[len(cmd):].strip().rstrip(".")
            return "comando", (cmd + (" " + resto if resto else ""))
    return "chat", ""
