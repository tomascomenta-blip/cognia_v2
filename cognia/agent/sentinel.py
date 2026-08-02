# -*- coding: utf-8 -*-
"""Sentinel — validación de seguridad pre-acción, DEFAULT-ON.

Mandato 2026-07-14: "Sentinel debe estar activo por defecto; todos los
agentes deben usarlo para validación/supervisión/seguridad antes de
ejecutar acciones importantes." El inventario detectó que la seguridad de
Cognia estaba dispersa (GoalContract al final del /hacer, sandbox para
código Python generado, denylist de substrings en `ejecutar` con
shell=True, gates de pantalla) y que `ejecutar` era denylist pura — cualquier
comando no listado pasaba. Sentinel unifica la decisión ANTES de la acción.

Modelo de riesgo para comandos de shell (3 niveles):
- ALLOW: prefijo en la allowlist de dev conocido-seguro (git status, pytest,
  ls, python, ruff, ...) → pasa sin fricción (un agente de código los usa
  todo el tiempo; bloquearlos lo inutiliza).
- BLOCK: patrón destructivo duro (rm -rf, mkfs, dd, shutdown, fork-bomb,
  format C:, redirección a dispositivos) → jamás pasa, ni en autónomo.
- CONFIRM: todo lo demás (riesgo desconocido) → pide ctx['confirm'] humano;
  en modo autónomo (COGNIA_AUTONOMOUS=1) procede pero SIEMPRE audita.

Es más defendible que la denylist pura (default-deny para lo desconocido,
no default-allow) y honesto sobre el trade-off: no es aislamiento de OS
(eso es el sandbox de program_creator para código Python). Cada decisión
deja evento en el bus (cognia/events.py) y línea en la auditoría
append-only (~/.cognia/sentinel_audit.jsonl), así la supervisión es
observable por la oficina y por un manager.

Kill-switch: COGNIA_SENTINEL=0 lo desactiva (vuelve al comportamiento
denylist previo). Default = ON (la excepción pedida por el dueño).
"""
import datetime
import json
import os
import re
from pathlib import Path

# El append con lock + la rotacion viven en backend_activo (solo stdlib): la
# rotacion estaba COPIADA en los dos modulos y por eso la carrera que destruia
# la generacion .1 tambien estaba en los dos. Una implementacion, un arreglo.
from cognia.backend_activo import escribir_linea_jsonl

_AUDIT = Path.home() / ".cognia" / "sentinel_audit.jsonl"

# Rotacion a UNA generacion (.1): el jsonl crecia sin cota (492KB en 2
# semanas). Al superar el tope se renombra a .1 (pisando la generacion
# previa) y se sigue en un archivo fresco. Mismo esquema que backend_activo.
_ROTAR_BYTES = 10 * 1024 * 1024

# Prefijos de comandos de dev conocidos-seguros (allowlist). Se matchea el
# PRIMER token (o los dos primeros para subcomandos de git). No incluye nada
# que borre/mueva masivamente ni toque red sin control.
_ALLOW_PREFIXES = {
    "git", "python", "python3", "py", "pytest", "pip", "ruff", "black",
    "mypy", "flake8", "ls", "dir", "cat", "type", "echo", "pwd", "cd",
    "head", "tail", "wc", "grep", "findstr", "find", "where", "which",
    "node", "npm", "npx", "tsc", "go", "cargo", "rustc", "java", "javac",
    "make", "cmake", "diff", "sort", "uniq", "tree", "date", "whoami",
    "poetry", "uv", "conda", "pytest.exe",
    # lanzadores: abrir apps/archivos/URLs (para "abre Chrome/YouTube/una app").
    # Un payload destructivo dentro sigue cazado por el BLOCK (corre antes).
    "start", "explorer", "open", "xdg-open", "wt", "code", "notepad",
    # consolas y utilidades del sistema (el dueño pidió poder abrirlas/usarlas;
    # un payload destructivo DENTRO sigue cazado por _BLOCK, que corre antes)
    "powershell", "pwsh", "cmd", "tasklist", "taskmgr", "calc", "mspaint",
    "curl", "wget", "ping", "ipconfig", "systeminfo", "hostname",
}
# git subcomandos que NO son de solo-lectura pero son parte del flujo normal
# de un agente de código (commit/add/checkout local); push/reset-hard/clean
# NO están → caen a CONFIRM.
_GIT_SAFE_SUB = {"status", "log", "diff", "show", "branch", "add", "commit",
                 "stash", "fetch", "pull", "rev-parse", "ls-files", "blame",
                 "restore", "switch", "checkout", "config"}

# Bloqueo duro: destructivo irreversible. Substrings + regex (del _shell viejo,
# ampliado). Estos NUNCA pasan.
_BLOCK_SUB = [
    "rm -rf", "rm -fr", "del /s", "del /q", "del /f", ":(){", ":|:&",
    "mkfs", "dd if=", "> /dev/", ">/dev/", "shutdown", "reboot", "rmdir /s",
    "format c:", "deltree", "> /dev/sda", "chmod -r 000", "chown -r",
    "rd /s", "diskpart", "cipher /w",   # destructores de Windows
]
_BLOCK_RE = [
    re.compile(r"\bformat\s+[a-z]:", re.I),        # format C: real
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f", re.I),   # rm -rf en cualquier orden
    re.compile(r"\brm\s+-[a-z]*f[a-z]*r", re.I),
    re.compile(r">\s*/dev/(sd|hd|nvme|null)?", re.I),
    re.compile(r"\bgit\s+push\b.*--force", re.I),  # force-push (destructivo remoto)
    re.compile(r"\bgit\s+reset\b.*--hard", re.I),
    re.compile(r"\bgit\s+clean\b.*-[a-z]*f", re.I),
    # borrado recursivo forzado en PowerShell (remove-item -recurse -force)
    re.compile(r"remove-item\b.*-re?c?u?r?s?e?\b.*-for?ce?\b", re.I),
    re.compile(r"remove-item\b.*-for?ce?\b.*-re?c?u?r?s?e?\b", re.I),
]

ALLOW, CONFIRM, BLOCK = "allow", "confirm", "block"


def sentinel_enabled() -> bool:
    return os.environ.get("COGNIA_SENTINEL", "1").strip().lower() not in (
        "0", "off", "false", "no")


def _autonomous() -> bool:
    return os.environ.get("COGNIA_AUTONOMOUS", "").strip().lower() in (
        "1", "on", "true", "yes")


def _acceso_total() -> bool:
    """Modo 'acceso total' pedido por el dueño para SU maquina (p.ej. el control
    remoto): los comandos de riesgo DESCONOCIDO (CONFIRM) proceden sin canal de
    confirmacion, para que Cognia pueda de verdad abrir apps/navegar/operar el
    equipo. El BLOCK duro (rm -rf, format, shutdown, dd, mkfs, reset --hard,
    force-push, borrados recursivos...) SIGUE vigente: es la ultima red."""
    return os.environ.get("COGNIA_ACCESO_TOTAL", "").strip().lower() in (
        "1", "on", "true", "yes")


def clasificar_shell(cmd: str) -> tuple:
    """(nivel, razon) para un comando de shell. Determinista, cero LLM."""
    norm = re.sub(r"\s+", " ", (cmd or "").strip().lower())
    if not norm:
        return CONFIRM, "comando vacío"
    # 1) bloqueo duro primero (gana sobre cualquier allowlist)
    if any(b in norm for b in _BLOCK_SUB) or any(rx.search(norm)
                                                 for rx in _BLOCK_RE):
        return BLOCK, "patrón destructivo irreversible"
    # 2) encadenamiento oculto: un allow-prefix seguido de ; && | `$( puede
    # esconder algo peligroso en el 2º comando. Reclasificar a CONFIRM salvo
    # que TODOS los segmentos sean allow.
    segmentos = re.split(r"[;&|]{1,2}|`|\$\(", norm)
    segmentos = [s.strip() for s in segmentos if s.strip()]
    if len(segmentos) > 1:
        niveles = [clasificar_shell(s)[0] for s in segmentos]
        if any(n == BLOCK for n in niveles):
            return BLOCK, "un segmento encadenado es destructivo"
        if all(n == ALLOW for n in niveles):
            return ALLOW, "todos los segmentos en la allowlist"
        return CONFIRM, "encadena un comando fuera de la allowlist"
    # 3) allowlist por prefijo. El head puede ser una RUTA citada a un
    # ejecutable ("c:\...\python.exe" -m pytest ...) que arma el propio
    # Cognia (tool `tests`): reducir al basename sin extensión antes de
    # comparar. La inyección en los argumentos ya la caza el paso 2
    # (encadenamiento), no la allowlist.
    tokens = norm.split()
    head = tokens[0].strip('"\'')
    if "/" in head or "\\" in head:
        head = re.split(r"[\\/]", head)[-1]
    if head.endswith(".exe"):
        head = head[:-4]
    if head in _ALLOW_PREFIXES:
        if head == "git" and len(tokens) > 1 and tokens[1] not in _GIT_SAFE_SUB:
            return CONFIRM, f"git {tokens[1]} no está en el set seguro"
        return ALLOW, f"prefijo '{head}' conocido-seguro"
    # 4) desconocido → default-deny (confirmación)
    return CONFIRM, f"comando '{head}' de riesgo desconocido"


def _audit(accion: str, cmd: str, veredicto: str, razon: str) -> None:
    try:
        # UNA sola write() de la linea completa sobre O_APPEND, y la rotacion
        # DENTRO del mismo lock entre procesos (ver escribir_linea_jsonl).
        linea = (json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "accion": accion, "cmd": cmd[:300],
            "veredicto": veredicto, "razon": razon,
        }, ensure_ascii=False) + "\n").encode("utf-8")
        escribir_linea_jsonl(_AUDIT, linea, _ROTAR_BYTES)
    except Exception:
        pass


def evaluar_shell(cmd: str, ctx: dict = None) -> tuple:
    """Compuerta pre-ejecución de un comando de shell.
    Devuelve (permitido: bool, mensaje_o_None). No ejecuta nada.
    Si Sentinel está OFF, replica la denylist previa (no rompe nada)."""
    ctx = ctx or {}
    if not sentinel_enabled():
        norm = re.sub(r"\s+", " ", (cmd or "").lower())
        if any(b in norm for b in _BLOCK_SUB) or any(rx.search(norm)
                                                     for rx in _BLOCK_RE):
            return False, "RESULTADO ejecutar: BLOQUEADO por seguridad"
        return True, None

    nivel, razon = clasificar_shell(cmd)
    _audit("shell", cmd, nivel, razon)
    try:
        from cognia.events import emit
        emit("sentinel.evaluada", accion="shell", veredicto=nivel,
             razon=razon, cmd_head=(cmd or "")[:80])
    except Exception:
        pass

    if nivel == ALLOW:
        return True, None
    if nivel == BLOCK:
        return False, (f"RESULTADO ejecutar: BLOQUEADO por Sentinel "
                       f"({razon}). Acción destructiva irreversible.")
    # CONFIRM
    if _autonomous() or _acceso_total():
        return True, None            # procede pero YA quedó auditado
    confirm = ctx.get("confirm")
    if callable(confirm):
        try:
            if confirm("ejecutar comando", cmd):
                return True, None
        except Exception:
            pass
        return False, (f"RESULTADO ejecutar: no confirmado por el usuario "
                       f"({razon}).")
    # sin canal de confirmación y no-autónomo → denegar (default-deny)
    return False, (f"RESULTADO ejecutar: requiere confirmación ({razon}). "
                   f"Sin canal de confirmación disponible; para permitir "
                   f"comandos de riesgo desconocido en modo desatendido, "
                   f"COGNIA_AUTONOMOUS=1.")


# ══════════════════════════════════════════════════════════════════════
# Centinela WEB — contenido de páginas ANTES de que llegue al modelo
# (mandato 2026-08-01: el navegador del agente descarta resultados
# envenenados o fuera de tema y sigue buscando; nunca en silencio).
# Determinista, cero LLM, como clasificar_shell: un juez LLM aquí
# repetiría el cuelgue de "juez-colgado-js-bloqueante" y además el
# contenido hostil podría inyectarse en el propio juez.
# ══════════════════════════════════════════════════════════════════════

# Invisibles/bidi: los usan para esconder instrucciones al ojo humano y
# para partir palabras y evadir matcheo por substring. Se cuentan ANTES
# de normalizar y se quitan ANTES de matchear patrones.
_WEB_INVISIBLES = re.compile(
    "[\u200b-\u200f\u2060\ufeff\u202a-\u202e\u2066-\u2069]")

# Patrones de inyección (ES+EN) sobre texto ya normalizado (minúsculas,
# sin invisibles, espacios colapsados). Substrings para lo literal,
# regex para lo que flexiona.
_WEB_INJ_SUB = [
    "<|im_start|>", "<|system|>", "<<sys>>", "[inst]", "### instruction",
    "### system", "you are now", "pretend you are", "jailbreak",
    "developer mode enabled", "do not tell the user", "no le digas al usuario",
    "hidden instruction", "instruccion oculta", "instrucción oculta",
]
_WEB_INJ_RE = [
    re.compile(r"ignor\w*\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)"
               r"\s+(?:instruction|prompt|rule|direction)", re.I),
    re.compile(r"ignora\w*\s+(?:todas?\s+)?(?:las?\s+)?(?:instrucciones|reglas|"
               r"indicaciones)\s+(?:anteriores|previas|del sistema)", re.I),
    re.compile(r"(?:disregard|forget|override)\s+(?:all\s+)?(?:your|previous|"
               r"the)\s+(?:instructions?|prompts?|rules?)", re.I),
    re.compile(r"olvida\s+(?:todas?\s+)?(?:tus|las)\s+(?:instrucciones|reglas)",
               re.I),
    re.compile(r"(?:system|assistant)\s*prompt", re.I),
    re.compile(r"prompt\s+del?\s+sistema", re.I),
    re.compile(r"(?:new|nuevas?)\s+(?:instructions?|instrucciones)\s*:", re.I),
    # exfiltración: pedir claves/tokens o mandarlos a otro sitio
    re.compile(r"(?:reveal|print|send|share|leak)\s+.{0,40}(?:api\s*key|"
               r"password|secret|token|credential)", re.I),
    re.compile(r"(?:env[ií]a|manda|comparte|filtra|exfiltra)\s+.{0,40}"
               r"(?:clave|token|contrase|secreto|credencial)", re.I),
    # imita la gramática ReAct de Cognia ("ACCION: <tool> <args>"): una
    # página legítima no tiene por qué traer líneas de acción del agente.
    re.compile(r"^\s*ACCION\s*:\s*\w+", re.M),
]

# Stopwords mínimas para la relevancia (no exhaustivo a propósito: solo
# quitar conectores que inflarían el denominador).
_WEB_STOP = {
    "para", "como", "cómo", "sobre", "entre", "donde", "dónde", "cuando",
    "cuándo", "cual", "cuál", "esta", "este", "esto", "with", "from",
    "what", "when", "where", "which", "that", "this", "does", "tiene",
    "hace", "mejor", "best",
}


def _sin_acentos(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def sanear_texto_web(texto: str) -> str:
    """Texto web listo para el modelo: sin invisibles/bidi, espacios
    colapsados por línea (se preservan los saltos), acentos INTACTOS."""
    texto = _WEB_INVISIBLES.sub("", texto or "")
    lineas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def evaluar_contenido_web(texto: str, tema: str = None,
                          fuente: str = "") -> tuple:
    """(nivel, razon) para TEXTO extraído de la web, antes del modelo.

    BLOCK si huele a inyección de prompt (patrones ES/EN, gramática ACCION
    del agente, exceso de invisibles) o si no tiene relación con `tema`.
    ALLOW en el resto. Audita cada veredicto (accion='web') en el mismo
    jsonl que los comandos de shell. Determinista: mismo texto, mismo
    veredicto."""
    crudo = texto or ""
    if not crudo.strip():
        _audit("web", fuente, BLOCK, "página sin texto extraíble")
        return BLOCK, "página sin texto extraíble"

    n_invis = len(_WEB_INVISIBLES.findall(crudo))
    # >5: los invisibles sueltos existen en páginas legítimas (emoji ZWJ,
    # marcas RTL); decenas seguidas solo las he visto escondiendo texto.
    if n_invis > 5:
        razon = f"exceso de caracteres invisibles/bidi ({n_invis})"
        _audit("web", fuente, BLOCK, razon)
        return BLOCK, razon

    # La razón devuelta es GENÉRICA a propósito: citar el texto que casó
    # re-inyectaría el payload en el contexto del modelo vía el mensaje de
    # bloqueo (lo cazó test_tool_web_abrir_bloqueado). La cita exacta va
    # SOLO a la auditoría.
    norm = re.sub(r"[ \t]+", " ", _WEB_INVISIBLES.sub("", crudo).lower())
    for s in _WEB_INJ_SUB:
        if s in norm:
            _audit("web", fuente, BLOCK, f"patrón de inyección: '{s}'")
            return BLOCK, "patrón de inyección de prompt detectado"
    for rx in _WEB_INJ_RE:
        m = rx.search(_WEB_INVISIBLES.sub("", crudo))
        if m:
            _audit("web", fuente, BLOCK,
                   f"patrón de inyección: '{m.group(0)[:60]}'")
            return BLOCK, "patrón de inyección de prompt detectado"

    if tema:
        base = _sin_acentos(tema.lower())
        palabras = [w for w in re.findall(r"[a-z0-9]{4,}", base)
                    if w not in {_sin_acentos(s) for s in _WEB_STOP}]
        if palabras:
            cuerpo = _sin_acentos(norm)
            hits = sum(1 for w in palabras if w in cuerpo)
            necesarios = max(1, round(0.2 * len(palabras)))
            if hits < necesarios:
                razon = (f"irrelevante para '{tema}': {hits}/{len(palabras)} "
                         f"palabras clave presentes")
                _audit("web", fuente, BLOCK, razon)
                return BLOCK, razon

    _audit("web", fuente, ALLOW, "contenido limpio y en tema")
    return ALLOW, "contenido limpio y en tema"
