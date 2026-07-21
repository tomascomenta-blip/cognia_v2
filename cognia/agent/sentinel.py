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

_AUDIT = Path.home() / ".cognia" / "sentinel_audit.jsonl"

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
        _AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "accion": accion, "cmd": cmd[:300],
                "veredicto": veredicto, "razon": razon,
            }, ensure_ascii=False) + "\n")
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
