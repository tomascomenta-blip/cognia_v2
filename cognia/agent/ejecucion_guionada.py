# -*- coding: utf-8 -*-
"""
cognia/agent/ejecucion_guionada.py
==================================
`ejecutar_guion`: correr un programa de CONSOLA que pide teclado, tecleandole
entradas UNA A UNA y capturando lo que imprime ENTRE cada entrada.

Lo que ya habia (autoprueba._correr) manda todo el guion de golpe por stdin y
devuelve un unico stdout: sirve para saber si el programa sobrevive, no para
ver que contesto a cada tecla. Aqui la salida vuelve SEGMENTADA:

    >>> arranque
    Menu: 1) Sumar 2) Salir
    >>> entrada 1: '1'
    Primer numero:
    >>> entrada 2: '4'
    ...

Asi el modelo puede comprobar "despues de teclear X el programa mostro Y" sin
interaccion humana. Cada entrada se escribe cuando el programa lleva `pausa_ms`
sin imprimir nada (esta esperando) o al vencer `espera_max_ms`. El proceso corre
con el entorno aislado de autoprueba (HOME/TEMP temporales) y se mata por arbol
al vencer el timeout (la leccion "matar el shell NO mata el proceso").
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time

MAX_SEGMENTO_CHARS = 4000
MAX_ENTRADAS = 60


def _lector(pipe, q: "queue.Queue"):
    """Lee por TROZOS, no por lineas: un prompt de input() ('opcion> ') no lleva
    salto de linea y con readline no llegaba hasta la linea siguiente."""
    fd = pipe.fileno()
    try:
        while True:
            trozo = os.read(fd, 4096)
            if not trozo:
                break
            q.put(trozo)
    except Exception:
        pass
    finally:
        q.put(None)


def _drenar(q: "queue.Queue", pausa_ms: int, espera_max_ms: int) -> tuple:
    """Lee hasta `pausa_ms` de silencio (o espera_max_ms). (texto, eof)."""
    trozos: list = []
    eof = False
    t_ini = time.perf_counter()
    ultimo = t_ini
    while True:
        try:
            item = q.get(timeout=0.05)
        except queue.Empty:
            ahora = time.perf_counter()
            if (ahora - ultimo) * 1000 >= pausa_ms and (trozos or (ahora - t_ini) * 1000 >= pausa_ms):
                break
            if (ahora - t_ini) * 1000 >= espera_max_ms:
                break
            continue
        if item is None:
            eof = True
            break
        trozos.append(item.decode("utf-8", errors="replace"))
        ultimo = time.perf_counter()
    return "".join(trozos), eof


def correr_guionado(comando, entradas, *, cwd=None, timeout_s: int = 60, pausa_ms: int = 400,
                    espera_max_ms: int = 5000, shell: bool = True) -> dict:
    """Corre `comando` y le teclea `entradas` una a una. Devuelve un dict con
    segmentos [{entrada, salida}], rc, expiro, stderr, segundos."""
    entradas = list(entradas or [])[:MAX_ENTRADAS]
    t0 = time.perf_counter()
    q: "queue.Queue" = queue.Queue()
    segmentos: list = []
    with tempfile.TemporaryDirectory(prefix="guion_") as tmp:
        env = dict(os.environ)
        try:
            from cognia.autoprueba import _entorno_subproceso
            env = _entorno_subproceso(tmp)
        except Exception:
            env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["PYTHONUNBUFFERED"] = "1"
        try:
            proc = subprocess.Popen(comando, shell=shell, cwd=cwd or None, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except Exception as exc:
            return {"error": f"no se pudo lanzar: {type(exc).__name__}: {exc}", "segmentos": [], "rc": None}
        hilo = threading.Thread(target=_lector, args=(proc.stdout, q), daemon=True)
        hilo.start()
        expiro = False
        eof = False
        salida, eof = _drenar(q, pausa_ms, espera_max_ms)
        segmentos.append({"entrada": None, "salida": salida[:MAX_SEGMENTO_CHARS]})
        for ent in entradas:
            if eof or proc.poll() is not None:
                segmentos.append({"entrada": ent, "salida": "", "nota": "el programa ya habia terminado"})
                continue
            if (time.perf_counter() - t0) > timeout_s:
                expiro = True
                break
            try:
                proc.stdin.write((str(ent) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except Exception as exc:
                segmentos.append({"entrada": ent, "salida": "", "nota": f"stdin cerrado ({type(exc).__name__})"})
                break
            salida, eof = _drenar(q, pausa_ms, espera_max_ms)
            segmentos.append({"entrada": ent, "salida": salida[:MAX_SEGMENTO_CHARS]})
        # cerrar stdin y esperar el final
        try:
            proc.stdin.close()
        except Exception:
            pass
        restante = max(0.5, timeout_s - (time.perf_counter() - t0))
        try:
            proc.wait(timeout=min(restante, 10))
        except subprocess.TimeoutExpired:
            expiro = True
            try:
                from cognia.harness.timeout_tool import _matar_arbol
                _matar_arbol(proc)
            except Exception:
                proc.kill()
        cola, _ = _drenar(q, 100, 500)
        if cola:
            segmentos.append({"entrada": None, "salida": cola[:MAX_SEGMENTO_CHARS], "nota": "salida final"})
        return {"segmentos": segmentos, "rc": proc.returncode, "expiro": expiro,
                "segundos": round(time.perf_counter() - t0, 1), "entradas": len(entradas)}


_RE_ERROR = re.compile(r"Traceback|SyntaxError|IndentationError|EOFError|Error:", re.I)


def texto_guionado(r: dict, comando: str = "") -> str:
    if r.get("error"):
        return "ERROR: " + r["error"]
    lineas = []
    for s in r.get("segmentos", []):
        if s.get("entrada") is None:
            cab = ">>> arranque" if not s.get("nota") else f">>> {s['nota']}"
        else:
            cab = f">>> entrada: {s['entrada']!r}" + (f" ({s['nota']})" if s.get("nota") else "")
        lineas.append(cab)
        sal = (s.get("salida") or "").rstrip()
        lineas.append(sal if sal else "(sin salida)")
    todo = "\n".join(lineas)
    pie = [f"rc={r.get('rc')}", f"{r.get('segundos')} s", f"{r.get('entradas')} entradas"]
    if r.get("expiro"):
        pie.append("TIMEOUT: el programa seguia esperando (probablemente pide mas entradas o no termina solo)")
    if _RE_ERROR.search(todo):
        pie.append("hay un error de Python en la salida")
    return todo + "\n--- " + " · ".join(pie)


def partir_entradas(texto: str) -> list:
    """'1|4|5|q' o '1;4;5;q' o lineas -> lista. '\\n' literal tambien separa."""
    t = (texto or "").replace("\\n", "\n")
    if not t.strip():
        return []
    if "\n" in t:
        partes = t.split("\n")
    elif "|" in t:
        partes = t.split("|")
    else:
        partes = t.split(";")
    return [p.strip() for p in partes if p.strip() != "" or p == ""][:MAX_ENTRADAS]


__all__ = ["correr_guionado", "texto_guionado", "partir_entradas"]
