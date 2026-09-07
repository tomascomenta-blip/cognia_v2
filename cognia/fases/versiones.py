# -*- coding: utf-8 -*-
"""
cognia/fases/versiones.py — git como memoria de versiones de la obra.

Cada iteracion ACEPTADA por el juez es un commit ("fases: vN fase X aceptada").
Cuando el juez rechaza, se vuelve de verdad a la ultima version aceptada:
`git checkout <commit> -- .` para lo trackeado y borrado de los ficheros
NUEVOS que aparecieron durante la iteracion (los untracked que ya existian
antes del snapshot se respetan: son del dueno). Asi el modelo puede fallar
y volver atras sin entrar en la espiral de "arregla V5 otra vez".

Si el workspace no es un repo se hace `git init` local (sin remoto) con un
.gitignore minimo. Sin git en el PATH todo degrada con causa visible: el
pipeline sigue, pero sin revert (lo dice el informe).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

IGNORAR = (".cognia_fases/", ".cognia_scratch/", ".cognia_capturas/", "__pycache__/", "*.pyc",
           "node_modules/", ".pytest_cache/", "*.log")


def _git(workspace, *args, timeout: int = 120) -> tuple:
    exe = shutil.which("git")
    if not exe:
        return -2, "", "git no esta en el PATH"
    try:
        r = subprocess.run([exe, *args], cwd=str(workspace), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:
        return -1, "", "%s: %s" % (type(exc).__name__, exc)


def disponible() -> bool:
    return shutil.which("git") is not None


def es_repo(workspace) -> bool:
    rc, out, _ = _git(workspace, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def asegurar_repo(workspace) -> dict:
    """{ok, creado, motivo}. Crea el repo si no existe y completa el .gitignore."""
    ws = Path(str(workspace))
    if not disponible():
        return {"ok": False, "creado": False, "motivo": "git no esta en el PATH"}
    creado = False
    if not es_repo(ws):
        rc, _o, err = _git(ws, "init", "-q")
        if rc != 0:
            return {"ok": False, "creado": False, "motivo": "git init fallo: " + err.strip()[:200]}
        creado = True
        # identidad local para que commit no pare (no toca la global del dueno)
        _git(ws, "config", "user.email", "cognia@local")
        _git(ws, "config", "user.name", "Cognia (fases)")
    gi = ws / ".gitignore"
    try:
        actual = gi.read_text(encoding="utf-8") if gi.exists() else ""
        faltan = [p for p in IGNORAR if p not in actual.splitlines()]
        if faltan:
            with gi.open("a", encoding="utf-8") as fh:
                if actual and not actual.endswith("\n"):
                    fh.write("\n")
                fh.write("# cognia fases\n" + "\n".join(faltan) + "\n")
    except Exception as exc:
        return {"ok": True, "creado": creado, "motivo": ".gitignore no escrito: %s" % exc}
    return {"ok": True, "creado": creado, "motivo": ""}


def head(workspace) -> str:
    rc, out, _ = _git(workspace, "rev-parse", "HEAD")
    return out.strip() if rc == 0 else ""


def untracked(workspace) -> set:
    rc, out, _ = _git(workspace, "ls-files", "--others", "--exclude-standard")
    return {l.strip().replace("\\", "/") for l in out.splitlines() if l.strip()} if rc == 0 else set()


def snapshot(workspace, mensaje: str) -> dict:
    """git add -A + commit. {ok, commit, motivo, sin_cambios}."""
    rc, _o, err = _git(workspace, "add", "-A")
    if rc != 0:
        return {"ok": False, "commit": "", "motivo": "git add: " + err.strip()[:200], "sin_cambios": False}
    rc, out, _e = _git(workspace, "status", "--porcelain")
    if rc == 0 and not out.strip():
        return {"ok": True, "commit": head(workspace), "motivo": "", "sin_cambios": True}
    rc, _o, err = _git(workspace, "commit", "-q", "-m", mensaje, "--no-verify")
    if rc != 0:
        return {"ok": False, "commit": "", "motivo": "git commit: " + err.strip()[:200], "sin_cambios": False}
    return {"ok": True, "commit": head(workspace), "motivo": "", "sin_cambios": False}


def ficheros_cambiados(workspace, desde_commit: str) -> list:
    """Ficheros distintos entre `desde_commit` y el arbol de trabajo (trackeados
    modificados + nuevos sin trackear)."""
    cambiados = set()
    if desde_commit:
        rc, out, _ = _git(workspace, "diff", "--name-only", desde_commit)
        if rc == 0:
            cambiados |= {l.strip().replace("\\", "/") for l in out.splitlines() if l.strip()}
    cambiados |= untracked(workspace)
    return sorted(c for c in cambiados if not c.startswith(".cognia_"))


def revertir(workspace, commit: str, untracked_previos: set) -> dict:
    """Vuelve al estado de `commit`: restaura lo trackeado y borra los ficheros
    nuevos que NO existian antes de la iteracion. {ok, restaurados, borrados, motivo}."""
    if not commit:
        return {"ok": False, "restaurados": 0, "borrados": 0, "motivo": "sin commit al que volver"}
    rc, _o, err = _git(workspace, "checkout", "-q", commit, "--", ".")
    if rc != 0:
        return {"ok": False, "restaurados": 0, "borrados": 0, "motivo": "git checkout: " + err.strip()[:200]}
    # ficheros que existen en el arbol pero no en el commit (nuevos): los que
    # aparecieron en esta iteracion se borran; los previos se respetan
    rc, out, _ = _git(workspace, "ls-tree", "-r", "--name-only", commit)
    en_commit = {l.strip().replace("\\", "/") for l in out.splitlines()} if rc == 0 else set()
    borrados = 0
    ws = Path(str(workspace))
    for rel in sorted(untracked(workspace) | _trackeados_nuevos(workspace, en_commit)):
        if rel in untracked_previos or rel.startswith(".cognia_"):
            continue
        p = ws / rel
        try:
            if p.is_file():
                p.unlink()
                borrados += 1
        except Exception:
            pass
    # el indice tambien vuelve al commit (git add -A del snapshot fallido no queda a medias)
    _git(workspace, "reset", "-q", commit, "--", ".")
    rc, out, _ = _git(workspace, "diff", "--name-only", commit)
    restaurados = len([l for l in out.splitlines() if l.strip()]) if rc == 0 else 0
    return {"ok": True, "restaurados": restaurados, "borrados": borrados, "motivo": ""}


def _trackeados_nuevos(workspace, en_commit: set) -> set:
    rc, out, _ = _git(workspace, "ls-files")
    if rc != 0:
        return set()
    return {l.strip().replace("\\", "/") for l in out.splitlines() if l.strip()} - en_commit


def log_versiones(workspace, n: int = 20) -> list:
    rc, out, _ = _git(workspace, "log", "--oneline", "-n", str(n), "--grep=^fases:")
    return [l for l in out.splitlines() if l.strip()] if rc == 0 else []
