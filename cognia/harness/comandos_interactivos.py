# -*- coding: utf-8 -*-
"""Comandos que se QUEDAN ESPERANDO: bloqueo por lista y pista en el timeout.

Portado de SWE-agent (`sweagent/tools/tools.py: ToolFilterConfig.blocklist /
blocklist_standalone / block_unless_regex` y la plantilla
`command_cancelled_timeout_template`) el 2026-09-04, tras leer su código.

El problema que resuelve: `ejecutar "python"` o `ejecutar "vim x.py"` no fallan,
se quedan colgados leyendo un stdin que nadie va a escribir, y el modelo solo
ve "timeout tras 30s" sin saber por qué. Tres capas:

1. `motivo_bloqueo(cmd)`: comandos que SIEMPRE esperan entrada (editores,
   pagers, intérpretes sin script, `pause`, `ssh` sin comando) se rechazan
   ANTES de lanzarlos, con la alternativa en el mismo mensaje.
2. `stdin` cerrado (`subprocess.DEVNULL`, lo pone `_correr_proceso`): un
   `input()` inesperado recibe EOF y muere con EOFError en vez de colgar.
3. `pista_timeout(cmd, s)`: cuando aun así vence el timeout, el mensaje nombra
   la causa probable (interactivo o servidor) y la salida (`ejecutar_fondo`).

No es una frontera de seguridad (esa es el sentinel): es una lista de cosas
que no pueden funcionar sin un humano delante. Kill-switch: COGNIA_INTERACTIVOS=0.
"""
from __future__ import annotations

import os
import re
import shlex

ENV_ACTIVO = "COGNIA_INTERACTIVOS"

# Prefijos: el comando EMPIEZA por esto (tras quitar `cd X &&`, sudo, etc.).
BLOQUEO_PREFIJO = (
    "vim", "vi ", "nvim", "nano", "emacs", "pico", "joe", "ed ",
    "less", "more ", "most", "man ",
    "top", "htop", "btop", "watch ",
    "tail -f", "tail --follow", "journalctl -f",
    "python -i", "python3 -i", "py -i", "node -i", "irb", "ipython", "jshell",
    "ssh ", "telnet ", "ftp ", "sftp ", "mysql", "psql", "sqlite3",
    "npm run dev", "npm start", "yarn dev", "pnpm dev", "flask run", "uvicorn ",
    "read ", "pause", "choice ", "set /p", "read-host", "$host.ui",
)
# Igualdad exacta: el comando ES esto (un intérprete sin script espera un REPL).
BLOQUEO_EXACTO = (
    "python", "python3", "py", "node", "bash", "sh", "zsh", "fish", "cmd",
    "powershell", "pwsh", "su", "sudo", "ipython", "irb", "ghci", "R",
)
# Bloqueado SALVO que aparezca el regex (SWE-agent: block_unless_regex).
BLOQUEO_SALVO = {
    "git ": r"\s--no-pager\b|\s-c\s+core\.pager=|\bgit\s+(status|diff|log|show|add|commit|push|pull|fetch|checkout|switch|branch|stash|rev-parse|ls-files|remote|init|clone|mv|rm|reset|tag|config|merge|rebase|blame|grep|apply|worktree)\b",
    "ssh ": r"\s\S+\s+\S",   # ssh host CMD sí; ssh host solo, no
    # clientes de BD: con sentencia entre comillas, -c/-e o entrada redirigida
    # corren y terminan; pelados abren un prompt.
    "sqlite3": r"['\"]|\s-(?:c|e|cmd|batch)\b|<",
    "mysql": r"['\"]|\s-(?:e|c)\b|\s--execute\b|<",
    "psql": r"['\"]|\s-(?:c|f)\b|\s--command\b|<",
}

_RE_PREFIJOS_QUITABLES = re.compile(
    r"^(?:(?:cd\s+\S+\s*(?:&&|;)\s*)|(?:sudo\s+)|(?:time\s+)|(?:env\s+\w+=\S+\s+)|(?:\w+=\S+\s+))+",
    re.I)

_MENSAJE = ("bloqueado antes de lanzarlo: '{cab}' {motivo}. Nadie puede "
            "contestarle desde aquí y se quedaría colgado hasta el timeout. "
            "{alternativa}")

_ALTERNATIVAS = {
    "editor": "Edita con editar_archivo / escribir_archivo.",
    "pager": "Usa `cat`, `head`, `tail -n N`, `sed -n 'a,bp'` o leer_archivo.",
    "monitor": "Toma una foto: `tasklist`, `ps`, `Get-Process` sin seguir.",
    "repl": "Pásale un script o `-c \"...\"`, o escribe un fichero y córrelo.",
    "remoto": "Da el comando completo (`ssh host 'cmd'`) o usa http_get.",
    "servidor": "Es un proceso de larga vida: usa ejecutar_fondo y luego ver_salida / procesos.",
    "entrada": "No hay teclado: quita la espera o pasa el valor como argumento.",
}


def activo() -> bool:
    return os.environ.get(ENV_ACTIVO, "1").strip().lower() not in ("0", "no", "off", "false")


def _cabeza(cmd: str) -> str:
    """El comando propio, sin `cd X &&`, `sudo`, asignaciones de entorno."""
    c = (cmd or "").strip()
    c = re.sub(r"\s+", " ", c)
    c = _RE_PREFIJOS_QUITABLES.sub("", c).strip()
    return c


def _tipo(cab: str) -> str:
    low = cab.lower()
    if low.startswith(("vim", "vi ", "nvim", "nano", "emacs", "pico", "joe", "ed ")):
        return "editor"
    if low.startswith(("less", "more ", "most", "man ")):
        return "pager"
    if low.startswith(("top", "htop", "btop", "watch ", "tail -f", "tail --follow", "journalctl -f")):
        return "monitor"
    if low.startswith(("ssh ", "telnet ", "ftp ", "sftp ", "mysql", "psql", "sqlite3")):
        return "remoto"
    if low.startswith(("npm run dev", "npm start", "yarn dev", "pnpm dev", "flask run", "uvicorn ")):
        return "servidor"
    if low.startswith(("read ", "pause", "choice ", "set /p", "read-host", "$host.ui")):
        return "entrada"
    return "repl"


def motivo_bloqueo(cmd: str) -> str | None:
    """El motivo (texto para el modelo) si `cmd` es interactivo; None si no.

    Solo mira la CABEZA del comando: `python x.py | less` se bloquea por el
    pager, `echo hola | python -` no (tiene stdin). Nunca lanza.
    """
    if not activo():
        return None
    try:
        cab = _cabeza(cmd)
        if not cab:
            return None
        # Cada tramo de una tubería/encadenado se mira por separado.
        tramos = [t.strip() for t in re.split(r"\s*(?:\|\||&&|;|\|)\s*", cab) if t.strip()]
        for tramo in tramos:
            low = tramo.lower()
            palabra = low.split(" ", 1)[0]
            if tramo in BLOQUEO_EXACTO or palabra in BLOQUEO_EXACTO and len(tramos) == 1 and " " not in tramo:
                return _MENSAJE.format(cab=tramo, motivo="abre un intérprete interactivo",
                                       alternativa=_ALTERNATIVAS["repl"])
            for pref in BLOQUEO_PREFIJO:
                if low.startswith(pref) or low == pref.strip():
                    # `pip install -e .`, `python -m venv` NO son interactivos: no están.
                    salvo = next((r for p, r in BLOQUEO_SALVO.items() if low.startswith(p)), None)
                    if salvo and re.search(salvo, tramo, re.I):
                        break
                    tipo = _tipo(tramo)
                    return _MENSAJE.format(cab=tramo, motivo={
                        "editor": "abre un editor de pantalla completa",
                        "pager": "abre un paginador que espera teclas",
                        "monitor": "se queda refrescando hasta que alguien lo corte",
                        "remoto": "abre una sesión remota interactiva",
                        "servidor": "arranca un servidor que no termina solo",
                        "entrada": "espera que alguien teclee algo",
                        "repl": "abre un intérprete interactivo",
                    }[tipo], alternativa=_ALTERNATIVAS[tipo])
        return None
    except Exception:
        return None


def pista_timeout(cmd: str, timeout: float) -> str:
    """Mensaje de timeout accionable: nombra la causa probable y la salida."""
    cab = _cabeza(cmd)[:80]
    base = (f"timeout tras {int(timeout)}s. ")
    low = cab.lower()
    if any(k in low for k in ("serve", "server", "run dev", "start", "uvicorn", "flask", "http.server", "manage.py runserver", "listen")):
        return base + ("Parece un SERVIDOR o proceso de larga vida: no termina solo. "
                       "Lánzalo con ejecutar_fondo y mira su salida con ver_salida.")
    return base + ("Causas probables: el comando esperaba ENTRADA por teclado "
                   "(stdin está cerrado, nadie contesta) o tarda más de lo que se "
                   "le dio. Acótalo (ruta/target más específico, `-x`, menos "
                   "datos), pásale `timeout=N` mayor, o si es de larga vida usa "
                   "ejecutar_fondo.")


__all__ = ["motivo_bloqueo", "pista_timeout", "activo", "ENV_ACTIVO",
           "BLOQUEO_PREFIJO", "BLOQUEO_EXACTO", "BLOQUEO_SALVO"]
