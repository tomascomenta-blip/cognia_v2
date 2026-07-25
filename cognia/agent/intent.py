"""
cognia/agent/intent.py
=====================
Decide, from a free-text message, whether the user is ASKING FOR AN ACTION (so
Cognia should run the agent with tools) vs just chatting -- without needing an
explicit slash command. Also suggests WHICH tool likely fits, to bias the agent's
first step.

Rule-based on purpose: it must be instant (no extra LLM call per message) and
high-precision (a chat message wrongly sent to the slow tool agent is worse than
a missed action). When unsure, it returns chat -- the agent is opt-in by clarity.

Concrete: ordered (pattern -> tool) rules + an imperative-verb fallback. Easy to
extend by adding a row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Intent:
    needs_agent: bool
    suggested_tool: str = ""   # best-guess tool name, or "" if action but unsure
    reason: str = ""


# Saludo de apertura: se PELA antes de juzgar, no descarta el mensaje.
# Cazado 2026-07-25 en una sesion real: "Hola podrias crear una carpeta que se
# llame..." casaba el guard de "hola" y volvia conversacional -> ni agente ni
# enrutador (cli.py veta el enrutador cuando reason=="conversacional") -> el
# chat contesto "```mkdir nueva_carpeta``` la carpeta ha sido creada" SIN crear
# nada. La cortesia no puede desactivar la ejecucion.
_SALUDO_APERTURA = re.compile(
    r"^\s*(hola|buenas(?:\s+(?:tardes|noches|d[ií]as))?|buen(?:os)?\s+d[ií]as?"
    r"|hey|ey|holi|qu[eé]\s+tal|c[oó]mo\s+(?:est[aá]s|va)|saludos)"
    r"[\s,!¡.:;·\-]*", re.I)

# Phrasings that look like an action but are really conversational -> force chat.
_CHAT_GUARDS = (
    r"^\s*(gracias|chau|adios|como estas|que tal|quien eres|quien sos)\b",
    r"^\s*(que es|que son|que significa|por que|para que|cual es|quien fue|quien es)\b",
    r"^\s*(explica|explicame|contame|definí|define|opina|opinas|crees que)\b",
)

# (regex, tool). First match wins. Spanish imperative/infinitive + common forms.
_RULES = [
    # abrir apps/URLs/pestañas ANTES que leer_archivo: "abre una pestaña de
    # Chrome con YouTube", "abre PowerShell", "abre youtube.com". (Reporte del
    # dueño 2026-07-21: "abre PowerShell" caía al chat y el modelo se negaba.)
    (r"\babr(?:e|a|as|i|í|ir|irme|ime|eme)\b.*\b(pesta[ñn]a|navegador|chrome|firefox|edge|brave|youtube|google)\b", "abrir"),
    (r"\b(?:abr(?:e|a|as|i|í|ir|irme|ime|eme)|lanz[aá]r?|lances?)\s+(el\s+|la\s+|una?\s+)?(powershell|terminal|consola|cmd|s[ií]mbolo del sistema|explorador|explorer|calculadora|bloc de notas|notepad|paint|spotify|discord|steam|word|excel)\b", "abrir"),
    (r"\babr(?:e|a|as|i|í|ir|irme|ime|eme)\b.*\s(https?://|www\.|\S+\.(com|net|org|es|co|io|tv|me|app)\b)", "abrir"),
    # "me envias la foto" / "mandame la captura": es una ENTREGA, no charla.
    # Cazado 2026-07-25 (sesion ...112753): fue al chat y el modelo contesto
    # "Aqui tienes la foto" sin foto ninguna, teniendo la captura en disco.
    (r"\b(env[ií]a|env[ií]as|enviame|env[ií]ame|manda|mandas|mandame|m[aá]ndame"
     r"|pasa|pasas|pasame|p[aá]same|mostr[aá]me|mu[eé]strame|ens[eé][ñn]ame)\b"
     r".{0,20}\b(foto|captura|pantallazo|imagen|screenshot|pantalla)\b",
     "pantalla_captura"),
    # ventanas: "pone Chrome al frente, esta detras de otras ventanas" (pedido
    # real 2026-07-25). Necesita la tool de ventanas, no leer_archivo.
    (r"\b(pon(?:e|er|é|es|ga)|tra(?:e|er|é)|mostr[aá]r?|enfoc[aá]r?|maximiz[aá]r?|restaur[aá]r?|activ[aá]r?)\b.*\b(al\s+frente|adelante|primer\s+plano|encima|visible)\b", "pantalla_activar_ventana"),
    (r"\b(al\s+frente|primer\s+plano)\b.*\b(ventana|pesta[ñn]a|chrome|firefox|edge|roblox|explorador)\b", "pantalla_activar_ventana"),
    (r"\b(le[eé]|leer|mostra?r?|ver|abr[ií]r?)\s+(el\s+)?(archivo|fichero|c[oó]digo|file)\b", "leer_archivo"),
    (r"\bque\s+(contiene|tiene|dice)\s+(el\s+)?(archivo|fichero)\b", "leer_archivo"),
    # carpetas ANTES que archivos: "crea una carpeta" no es escribir_archivo,
    # se hace con `ejecutar` (mkdir). Faltaba, y el mensaje caia al chat, que
    # respondia "la carpeta ha sido creada" sin crear nada (sesion 2026-07-25).
    (r"\b(cre[aá]r?|gener[aá]r?|hac[eé]r?|arm[aá]r?)\s+(un[ao]?\s+|el\s+|la\s+)?(carpeta|directorio|folder|subcarpeta)\b", "ejecutar"),
    (r"\b(escrib[ií]r?|cre[aá]r?|gener[aá]r?|guard[aá]r?)\s+(un\s+|el\s+|una\s+)?(archivo|fichero|script|file|funci[oó]n|clase|programa|html|json)\b", "escribir_archivo"),
    (r"\b(agreg[aá]r?|añad[ií]r?|apend[aá]r?)\s+.*\b(al\s+archivo|al\s+final)\b", "apendar_archivo"),
    (r"\b(busc[aá]r?|encontr[aá]r?|grep)\b.*\b(en|dentro de)\b", "buscar"),
    (r"\b(list[aá]r?)\s+(los?\s+)?(archivos?|carpetas?|directorio)\b", "listar"),
    (r"\b(ejecut[aá]r?|corr[eé]r?|run)\s+\S+", "ejecutar"),
    (r"\b(corr[eé]r?|ejecut[aá]r?)\s+(los?\s+)?tests?\b", "tests"),
    (r"\b(calcul[aá]r?|cu[aá]nto\s+(es|da|son))\b", "calcular"),
    (r"\b(resum[ií]r?|resume)\b", "resumir"),
    (r"\b(descarg[aá]r?|baj[aá]r?)\s+(de\s+)?https?://", "http_get"),
    (r"\b(record[aá]s?|que\s+sab[eé]s?|que\s+recordas|busc[aá]\s+en\s+(tu\s+)?memoria)\b", "recordar"),
    (r"\b(git\s+(status|estado|diff|log))\b", "git_estado"),
]

# Generic imperative action verbs: if one starts the message (and no chat guard
# fired), it's an action even if no specific tool matched -> let the agent pick.
_ACTION_VERBS = (
    "haz", "hace", "hacé", "haceme", "hazme", "crea", "creá", "create",
    "escribe", "escribí", "genera", "generá", "construye", "armá", "arma",
    "modifica", "modificá", "edita", "editá", "refactoriza", "refactorizá",
    "implementa", "implementá", "agrega", "agregá", "borra", "borrá", "elimina",
    "mueve", "mové", "copia", "copiá", "renombra", "descarga", "descargá",
    "instala", "instalá", "corre", "corré", "ejecuta", "ejecutá", "lee", "leé",
    "busca", "buscá", "lista", "listá", "analiza", "analizá",
    "abre", "abrí", "lanza", "lanzá", "cierra", "cerrá", "arranca",
    "captura", "capturá", "clickea", "clic", "teclea", "presiona", "pulsa",
)


# Prefijos de DESEO/CORTESIA: "quiero que me abras...", "podrias hacerme...",
# "necesito que crees..." — el nucleo de la peticion viene despues. Se pelan
# ANTES de casar reglas y verbo. (Reporte del dueño 2026-07-21: "quiero que me
# abras una pestaña en YouTube" caia al chat y el modelo solo daba el comando.)
_PREFIJOS_DESEO = re.compile(
    r"^\s*(por favor|porfa|che|oye|dale|hey)?[,\s]*"
    r"((yo\s+)?(quiero|quisiera|necesito|me gustaria|me gustaría|deseo)\s+que"
    r"|(puedes|podes|podrias|podrías|puede|podria|podría)"
    r"|(hazme el favor de|te pido que|hace?me el favor de))?[,\s]*"
    r"(me|nos|le)?\s*", re.I)

# Subjuntivo y cliticos de los mismos verbos de accion ("que me ABRAS", "que
# HAGAS", "abreme", "hazme"): sin esto solo el imperativo directo activaba.
_ACTION_VERBS_EXTRA = (
    "abras", "abra", "abrime", "abreme", "ábreme", "abrirme", "abrir", "hagas", "haga", "crees",
    "cree", "creame", "escribas", "escriba", "generes", "genere", "ejecutes",
    "ejecute", "corras", "corra", "busques", "busque", "muevas", "mueva",
    "captures", "capture", "cierres", "cierre", "lances", "lance", "instales",
    "instale", "descargues", "descargue", "borres", "borre", "elimines",
    "elimine", "leas", "lea", "listes", "liste", "analices", "analice",
    "construyas", "construya", "armes", "arme", "modifiques", "modifique",
    "edites", "edite", "implementes", "implemente", "teclees", "presiones",
)


def detect(text: str) -> Intent:
    """Classify a free-text message as action (run agent) or chat."""
    t = (text or "").strip().lower()
    if not t:
        return Intent(False, reason="vacio")

    # Un saludo NO decide nada por si solo: se pela y se juzga lo que sigue.
    # "hola" a secas sigue siendo conversacional (no queda nucleo).
    sin_saludo = _SALUDO_APERTURA.sub("", t, count=1).strip()
    if not sin_saludo:
        return Intent(False, reason="conversacional")
    t = sin_saludo

    for guard in _CHAT_GUARDS:
        if re.search(guard, t):
            return Intent(False, reason="conversacional")

    # pelar el prefijo de deseo/cortesia: el nucleo es lo que sigue
    nucleo = _PREFIJOS_DESEO.sub("", t, count=1).strip()

    for pattern, tool in _RULES:
        if re.search(pattern, t) or re.search(pattern, nucleo):
            return Intent(True, suggested_tool=tool, reason=f"regla:{tool}")

    # Imperative/subjunctive-verb fallback on the peeled core.
    first = nucleo.split()
    if first and (first[0] in _ACTION_VERBS or first[0] in _ACTION_VERBS_EXTRA):
        return Intent(True, suggested_tool="", reason=f"verbo:{first[0]}")

    return Intent(False, reason="chat")
