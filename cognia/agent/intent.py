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

import os
import re
from dataclasses import dataclass


@dataclass
class Intent:
    needs_agent: bool
    suggested_tool: str = ""   # best-guess tool name, or "" if action but unsure
    reason: str = ""
    # Explicacion para el usuario cuando la tool que TOCABA esta apagada por
    # flag. Vacio en el caso normal. Lo consume la capa que imprime (cli.py).
    aviso: str = ""


# Las pantalla_* solo se REGISTRAN con COGNIA_SCREEN activo (opt-in duro: el
# A/B 2026-07-25 midio que inflar el catalogo degrada al modelo chico). Si se
# sugieren igual, el agente pide una tool que NO existe y el usuario recibe
# "herramienta 'pantalla_captura' no existe" — un mensaje que le hace creer que
# Cognia no sabe hacer capturas, cuando lo unico que falta es el flag.
# Se lee EN LA LLAMADA, no en import-time: el flag puede ponerse despues de
# importar el modulo (cognia/remoto/sesiones.py lo exporta por sesion).
_PANTALLA_OFF_AVISO = (
    "Las herramientas de pantalla estan DESHABILITADAS. Habilitalas con "
    "COGNIA_SCREEN=1 (control de la maquina: es opt-in a proposito)."
)


def _pantalla_habilitada() -> bool:
    """Mismos valores que screen_tools._enabled() y que el gate de registro
    en tools.py: si cambia uno, cambian los tres."""
    return os.environ.get("COGNIA_SCREEN", "").strip().lower() in (
        "1", "on", "true", "yes")


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
    # Preguntas de PROCEDIMIENTO ("como se borra...", "que comandos usaria para
    # limpiar...") piden una EXPLICACION, no una ejecucion. Sin este guard, la
    # regla accion-sobre-el-sistema de abajo (verbo+objeto en cualquier
    # posicion) las mandaria al agente. Transcript 2026-08-25: el flujo sano es
    # "que comandos usaria..." -> chat explica; "hazlo tu" -> agente ejecuta.
    r"^\s*(como|c[oó]mo)\s+(se|puedo|podr[ií]a|hago|har[ií]a|debo|deber[ií]a|funciona)\b",
    r"^\s*(que|qu[eé]|cual|cu[aá]l|cuales|cu[aá]les)\s+(comandos?|programas?"
    r"|herramientas?|pasos?|opciones?|formas?|maneras?)\b",
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
    r"^\s*(por ?favor|porfa|che|oye|dale|hey|bueno|ok|okay|bien|entonces|a ver)?[,\s]*"
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


# ── ACCION SOBRE EL SISTEMA en cualquier posicion (transcript 2026-08-25) ──
# "Quiero que limpies todas las capturas de pantalla en mi computador" caia al
# chat: _RULES solo casa formas concretas y el fallback exige el verbo AL
# INICIO. El chat respondio con comandos de LINUX en Windows y despues INVENTO
# haberlos ejecutado ("veintinueve archivos eliminados", cero tools). Regla:
# verbo de accion de sistema (imperativo/subjuntivo-2a/infinitivo; las formas
# en -o tipo "borro/creo" quedan FUERA a proposito: son afirmaciones, no
# ordenes) + un OBJETO de sistema (fichero/carpeta/capturas/pc...) en
# CUALQUIER posicion = accion.
_OBJETO_SISTEMA_RE = re.compile(
    r"\b(archivos?|ficheros?|carpetas?|directorios?|programas?"
    r"|aplicaci[oó]n(?:es)?|apps?|capturas?|pantallazos?|pantallas?"
    r"|screenshots?|im[aá]gen(?:es)?|fotos?|videos?|escritorio|descargas"
    r"|documentos|papelera|discos?|pc|computador(?:a)?|ordenador|m[aá]quina"
    r"|equipo|sistema|files?|folders?|desktop|downloads|computer|disk)\b")

# Terminaciones admitidas por verbo (con y sin acento, con cliticos me/lo/la):
# imperativo tu/vos, subjuntivo 2a ("que limpies"), usted e infinitivo.
_VERBO_SISTEMA_RE = re.compile(
    r"\b(?:"
    r"borr(?:a|á|as|ás|es|e|ar)|limpi(?:a|á|as|ás|es|e|ar)"
    r"|elimin(?:a|á|as|ás|es|e|ar)|muev(?:e|as|a|es)|mov(?:er|é|eme)"
    r"|renombr(?:a|á|as|ás|es|e|ar)|organiz(?:a|á|as|ás|ar)"
    r"|orden(?:a|á|ás|ar)|instal(?:a|á|as|ás|es|e|ar)"
    r"|desinstal(?:a|á|as|ás|es|e|ar)|actualiz(?:a|á|as|ás|ar)"
    r"|descarg(?:a|á|as|ás|ues|ue|ar)|cre(?:a|á|es|ar)|gener(?:a|á|es|ar)"
    r"|conviert(?:e|as|a)|convert(?:ir|í)|comprim(?:e|as|a|ir|í)"
    r"|descomprim(?:e|as|a|ir|í)|abr(?:e|as|a|ir|í)|cierr(?:a|es|e)|cerr(?:ar|á)"
    r"|vaci(?:a|á|es|e|ar)"
    r"|delete|remove|clean(?:up)?|move|rename|organize|install|uninstall"
    r"|update|download|create|open|close"
    r")(?:me|lo|los|la|las|melo|melos|mela|melas)?\b")

# Palabra INMEDIATAMENTE anterior que convierte el verbo en descripcion, no en
# orden ("como se ordenan...", "windows organiza los archivos", "no borres").
# "que" esta porque las construcciones de deseo legitimas ("quiero que
# limpies") ya llegan PELADAS por _PREFIJOS_DESEO; un "que" superviviente es
# relativo ("el programa que limpia los archivos").
_VETO_PREVIA_VERBO = {
    "se", "no", "que", "como", "cómo", "cuando", "si", "quien", "quién", "ya",
    "nunca", "jamas", "jamás", "windows", "linux", "programa", "sistema",
    "app", "aplicacion", "aplicación", "explorador", "cognia", "modelo",
}


def _accion_sobre_sistema(nucleo: str) -> bool:
    """Verbo de sistema (no vetado por la palabra previa) + objeto de sistema."""
    if not _OBJETO_SISTEMA_RE.search(nucleo):
        return False
    for m in _VERBO_SISTEMA_RE.finditer(nucleo):
        previas = re.findall(r"[\wáéíóúñ]+", nucleo[:m.start()])
        if previas and previas[-1] in _VETO_PREVIA_VERBO:
            continue
        return True
    return False


# ── RECLAMO de no-ejecucion (transcript 2026-08-25) ────────────────────────
# "no los ejecutaste" tras la respuesta inventada volvia al CHAT, que repitio
# el mismo texto inventado. Un reclamo asi es la peticion de accion mas clara
# que existe: el CLI reencamina la peticion ORIGINAL al agente.
_RECLAMO_NO_EJECUTADO = re.compile(
    r"(\bno\s+(?:lo|los|la|las)\s+(?:ejecutaste|hiciste|corriste|borraste"
    r"|eliminaste|creaste|moviste|instalaste|descargaste|limpiaste)\b"
    r"|\bno\s+hiciste\s+nada\b"
    r"|\bno\s+(?:se\s+)?ejecut(?:o|ó|aron)\b"
    r"|\bno\s+ejecutaste\b"
    r"|\bno\s+(?:borraste|corriste|limpiaste)\s+nada\b"
    r"|\beso\s+no\s+(?:paso|pasó|ocurrio|ocurrió|sucedio|sucedió)\b"
    r"|\bde\s+verdad\s+(?:hazlo|hacelo|ejec[uú]talo|c[oó]rrelo)\b"
    r"|\byou\s+didn'?t\s+(?:run|execute|do|delete)\b"
    r"|\bnothing\s+(?:happened|was\s+(?:run|executed|deleted))\b"
    r"|\bthat\s+didn'?t\s+happen\b)", re.I)

# ── CONTINUACION corta ("hazlo tu", "dale", "procede") ─────────────────────
# Turno corto que ORDENA ejecutar lo recien conversado. "hazlo/ejecutalo/
# correlo" llevan el mandato adentro y disparan SIEMPRE; "dale/procede/
# adelante/ok" solos solo disparan cuando la respuesta previa del chat traia
# comandos o un plan (sin ese contexto son muletillas de charla).
_CONTINUACION_CORTA = re.compile(
    r"^\s*(?:si|sí|ok|okay|dale|vale|bueno|claro)?[,\s]*"
    r"(?:hazlo|hacelo|hazlos|hacelos|ejecutalo|ejecútalo|ejecutalos"
    r"|ejecútalos|correlo|córrelo|correlos|córrelos|dale|procede|proced[eé]"
    r"|adelante|do\s+it|go\s+ahead)"
    r"(?:\s+(?:tu|tú|vos|ya|ahora|mismo|entonces|por\s+favor|porfa"
    r"|porfavor|please))*\s*[.!?]*\s*$", re.I)
_HAZLO_DIRECTO = re.compile(
    r"\b(hazlo|hacelo|ejec[uú]talos?|c[oó]rrelos?)\b", re.I)

# La respuesta previa "contenia comandos o un plan": fence de codigo, comando
# tipico de shell (ES/Windows/unix), lista numerada o la palabra plan/comando.
_PLAN_EN_RESPUESTA = re.compile(
    r"(```|^\s*[$>]\s"
    r"|\b(?:ls|rm|del|dir|find|mkdir|rmdir|mv|cp|move|copy|cd|powershell"
    r"|cmd|bash|Remove-Item|Get-ChildItem|Clear-RecycleBin|pip|npm|git"
    r"|sudo|apt|winget|gnome-screenshot)\b"
    r"|^\s*\d+[.)]\s|\bpaso\s+\d|\bplan\b|\bcomandos?\b)",
    re.I | re.M)


# ── AFIRMACIONES DE ACCION en una respuesta de CHAT (sin tools) ────────────
# El fast-path de chat NO ejecuta nada nunca; si su respuesta AFIRMA en
# primera persona pasado haber tocado el sistema ("Ejecute los dos
# comandos... veintinueve archivos eliminados", transcript 2026-08-25), esa
# respuesta es una invencion. El detector exige PASADO en primera persona o
# una cifra de resultados: "ejecuta este comando" (imperativo al usuario) y
# "si ejecutas X pasara Y" (condicional) NO son afirmaciones y se descartan
# por el guard de la oracion.

# Oracion que INSTRUYE o CONDICIONA (dirigida al usuario): no cuenta.
_AFIRMA_GUARD_ORACION = re.compile(
    r"^\s*(?:si|cuando|para|una vez|despu[eé]s|luego|antes)\b"
    r"|\b(?:puedes|pod[eé]s|podr[ií]as|deber[ií]as|debes|tienes que"
    r"|tendr[ií]as|ejecutas?\b|ejecutes|corres|corras|usa|usar[ií]as|prueba"
    r"|abre|escribe|you can|you should|run this|try)\b", re.I)

# Numeros en palabras para las cifras de resultado ("veintinueve archivos
# eliminados"): el modelo del transcript las escribio asi, no en digitos.
_NUM_PALABRA = (
    r"(?:\d+|un[oa]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once"
    r"|doce|trece|catorce|quince|diecis[eé]is|diecisiete|dieciocho"
    r"|diecinueve|veinte|veinti\w+|treinta|cuarenta|cincuenta|sesenta"
    r"|setenta|ochenta|noventa|cien(?:to)?\w*)(?:\s+y\s+\w+)?")

_AFIRMA_PATRONES = [
    # 1a persona preterito CON acento o formas inequivocas sin el (corri, movi,
    # abri, hice... no colisionan con el imperativo-usted).
    re.compile(
        r"\b(ejecut[eé]|corr[ií]|borr[eé]|elimin[eé]|mov[ií]|cre[eé]"
        r"|guard[eé]|instal[eé]|desinstal[eé]|modifiqu[eé]|edit[eé]"
        r"|renombr[eé]|descargu[eé]|limpi[eé]|comprim[ií]|descomprim[ií]"
        r"|copi[eé]|abr[ií]|cerr[eé]|actualic[eé]|organic[eé]|orden[eé]"
        r"|gener[eé]|escrib[ií]|vaci[eé]|hice)\s+"
        r"(?:ya\s+)?(?:los|las|el|la|ambos|tod[oa]s|tus?|un[oa]?|es[oa]s?|\d+)\b",
        re.I),
    # participio con haber: "he ejecutado", "he borrado", "hemos eliminado"
    re.compile(
        r"\b(?:he|hemos|ya he)\s+(?:ejecutado|corrido|borrado|eliminado"
        r"|movido|creado|guardado|instalado|desinstalado|modificado|editado"
        r"|renombrado|descargado|limpiado|comprimido|copiado|abierto|cerrado"
        r"|actualizado|organizado|ordenado|generado|escrito|vaciado|hecho)\b",
        re.I),
    # "acabo de ejecutar/borrar..."
    re.compile(
        r"\bacabo\s+de\s+(?:ejecutar|correr|borrar|eliminar|mover|crear"
        r"|guardar|instalar|limpiar|copiar|descargar)\b", re.I),
    # cierre de tarea: "ya esta hecho", "todo quedo borrado", "tarea completada"
    re.compile(
        r"\b(?:ya|todo)\s+(?:est[aá]|qued[oó])\s+(?:hecho|listo|borrado"
        r"|eliminado|limpio|ejecutado|instalado)\b", re.I),
    re.compile(
        r"\b(?:tarea|limpieza|operaci[oó]n)\s+(?:completada|realizada"
        r"|finalizada|terminada)\b", re.I),
    # cifras de resultado: "veintinueve archivos eliminados", "salieron 17
    # imagenes", "se eliminaron 29 archivos", "quedaron 3 carpetas borradas"
    re.compile(
        _NUM_PALABRA + r"\s+(?:archivos?|ficheros?|im[aá]gen(?:es)?|capturas?"
        r"|carpetas?|elementos?|files?)\s+(?:eliminad|borrad|movid|renombrad"
        r"|copiad|cread|deleted|removed|moved)\w*", re.I),
    re.compile(
        r"\b(?:salieron|se\s+(?:eliminaron|borraron|movieron|crearon"
        r"|instalaron)|fueron\s+(?:eliminad|borrad|movid)\w+|han\s+sido\s+"
        r"(?:eliminad|borrad|movid)\w+|quedaron\s+(?:eliminad|borrad)\w+)\b",
        re.I),
    # EN: "I ran", "I deleted", "I've removed", "29 files were deleted"
    re.compile(
        r"\bI\s+(?:ran|executed|deleted|removed|created|moved|renamed"
        r"|installed|cleaned|copied|edited|modified|downloaded|wrote)\b"
        r"|\bI(?:'ve|\s+have)\s+(?:run|executed|deleted|removed|created"
        r"|moved|renamed|installed|cleaned|copied|edited|modified"
        r"|downloaded|written)\b"
        r"|\b\d+\s+files?\s+(?:were\s+|have\s+been\s+)?(?:deleted|removed"
        r"|moved)\b", re.I),
]

# Falsos positivos concretos dentro de una oracion afirmativa: "Ejecute los
# SIGUIENTES comandos" es imperativo-usted, no pasado.
_AFIRMA_VETO_SIGUIENTE = re.compile(
    r"\b(?:ejecute|borre|elimine|cree|instale|corra)\s+(?:los|las|el|la)?\s*"
    r"(?:siguientes?|estos?|estas?)\b", re.I)


def afirma_accion_ejecutada(respuesta: str) -> str:
    """Devuelve el fragmento que AFIRMA una accion ejecutada, o "" si la
    respuesta solo explica/instruye. Se usa sobre respuestas del fast-path de
    chat, que NUNCA ejecuta tools: cualquier afirmacion es inventada."""
    if not respuesta:
        return ""
    # los bloques de codigo son comandos PROPUESTOS, no afirmaciones
    limpio = re.sub(r"```.*?```", " ", respuesta, flags=re.S)
    limpio = re.sub(r"`[^`\n]*`", " ", limpio)
    for oracion in re.split(r"[.!?\n]+", limpio):
        if not oracion.strip():
            continue
        if _AFIRMA_GUARD_ORACION.search(oracion):
            continue
        if _AFIRMA_VETO_SIGUIENTE.search(oracion):
            continue
        for pat in _AFIRMA_PATRONES:
            m = pat.search(oracion)
            if m:
                # "me pediste QUE ejecute los comandos" / "NO ejecute los
                # comandos" reformulan o niegan: la palabra previa lo delata.
                previas = re.findall(r"[\wáéíóúñ]+", oracion[:m.start()])
                if previas and previas[-1].lower() in ("que", "no"):
                    continue
                return m.group(0).strip()
    return ""


def detect(text: str, respuesta_previa: str = "") -> Intent:
    """Classify a free-text message as action (run agent) or chat.

    `respuesta_previa` (opcional): la ultima respuesta del CHAT en la sesion;
    habilita la regla de continuacion ("hazlo tu" tras una respuesta con
    comandos/plan -> la accion es lo conversado, no el turno corto)."""
    t = (text or "").strip().lower()
    if not t:
        return Intent(False, reason="vacio")

    # Un saludo NO decide nada por si solo: se pela y se juzga lo que sigue.
    # "hola" a secas sigue siendo conversacional (no queda nucleo).
    sin_saludo = _SALUDO_APERTURA.sub("", t, count=1).strip()
    if not sin_saludo:
        return Intent(False, reason="conversacional")
    t = sin_saludo

    # RECLAMO de no-ejecucion: va ANTES de los guards (ninguno lo cubre) y de
    # las reglas. El CLI reencamina la peticion ORIGINAL, no este texto.
    if _RECLAMO_NO_EJECUTADO.search(t):
        return Intent(True, suggested_tool="", reason="reclamo:no_ejecutado")

    # CONTINUACION corta: "hazlo tu"/"dale"/"procede" tras una respuesta con
    # comandos o plan. "hazlo/ejecutalo/correlo" disparan aun sin contexto
    # (el mandato va adentro); "dale/procede/adelante" solos, no.
    if len(t.split()) <= 6 and _CONTINUACION_CORTA.match(t):
        if respuesta_previa and _PLAN_EN_RESPUESTA.search(respuesta_previa):
            return Intent(True, suggested_tool="", reason="continuacion:accion")
        if _HAZLO_DIRECTO.search(t):
            return Intent(True, suggested_tool="", reason="accion:hazlo")

    for guard in _CHAT_GUARDS:
        if re.search(guard, t):
            return Intent(False, reason="conversacional")

    # pelar el prefijo de deseo/cortesia: el nucleo es lo que sigue
    nucleo = _PREFIJOS_DESEO.sub("", t, count=1).strip()

    for pattern, tool in _RULES:
        if re.search(pattern, t) or re.search(pattern, nucleo):
            # Sigue siendo una ACCION (needs_agent=True), pero no se sugiere
            # una tool que el catalogo no tiene: sin el flag, el hint hacia que
            # el agente la invocara y volviera "herramienta ... no existe".
            if tool.startswith("pantalla_") and not _pantalla_habilitada():
                return Intent(True, suggested_tool="",
                              reason=f"regla:{tool}:deshabilitado",
                              aviso=_PANTALLA_OFF_AVISO)
            return Intent(True, suggested_tool=tool, reason=f"regla:{tool}")

    # Accion sobre el SISTEMA en cualquier posicion: "quiero que limpies todas
    # las capturas de pantalla en mi computador" (nucleo pelado: "limpies
    # todas las capturas..."). Sin tool sugerida: el agente elige (suele ser
    # `ejecutar` o `listar`). Transcript 2026-08-25.
    if _accion_sobre_sistema(nucleo):
        return Intent(True, suggested_tool="", reason="accion:sistema")

    # Imperative/subjunctive-verb fallback on the peeled core.
    first = nucleo.split()
    if first and (first[0] in _ACTION_VERBS or first[0] in _ACTION_VERBS_EXTRA):
        return Intent(True, suggested_tool="", reason=f"verbo:{first[0]}")

    return Intent(False, reason="chat")
