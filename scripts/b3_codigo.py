# -*- coding: utf-8 -*-
"""
b3_codigo.py — runner de bancos PÚBLICOS de código (MBPP / LiveCodeBench).

POR QUÉ EXISTE (2026-07-30, PREREG_BANCO_CODIGO_20260730).
El banco web se saturó (pass@1 92%) y de 9 tareas escritas para romper al
sistema 6 salieron 4/4: el techo que se alcanza primero es el del DISEÑADOR
de exámenes. Los benchmarks de código TRAEN LOS TESTS — la pieza que las 10
vías de señal autogenerada no consiguieron fabricar — y su juez es
`subprocess + timeout`, no Playwright.

Es una PORTACIÓN de cognia_v3/training/cognia3b/ecod_kernel.py (escrito para
Kaggle: OUT=/kaggle/working, modelo por transformers). Aquí el modelo se
sirve por llama-server y el runner es desacoplado + reanudable, como el resto
de los b2_.

Lo que este runner NO decide: el veredicto. Solo GENERA y EJECUTA, y persiste
todo lo intermedio (incluido el texto crudo de cada muestra — regla del repo:
cuando un runner compute algo intermedio, persistirlo aunque no se use hoy).
El análisis BoN-vs-AZAR vive en b3_analisis.py, que lee este JSON.

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_codigo.py --banco mbpp --n 100 --k 4
    ... --reanudar    (obligatorio si ya existe el fichero de resultados)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto

DATOS = RAIZ / "datos_bancos"
SALIDA = RAIZ / "b3_codigo"
BACKEND = os.environ.get("COGNIA_LLM_URL", "http://127.0.0.1:8080")

# Presupuesto de tokens: gpt-oss es Harmony y PIENSA antes de responder. El
# repo lleva 7 bugs idénticos por max_tokens que no cubre el pensamiento
# (memoria presupuesto-tokens-razonamiento): margen 2-3x sobre la respuesta.
MAX_TOKENS = 4096
REASONING_EFFORT = "low"        # se fija por chat_template_kwargs, NO por el
                                # system: "Reasoning: low" en el system NO
                                # hace nada (medido 3/3).
TIMEOUT_HTTP = 300
EXEC_TIMEOUT = 8                # segundos por lote de asserts (MBPP)
SEG_POR_TEST = 6                # LCB: presupuesto POR TEST (su estándar)
TOPE_LOTE = 240                 # techo de pared del lote, pase lo que pase
LCB_VISIBLES = 5                # privados sorteados que ve el selector
MAX_BYTES_CASO = 100_000        # ENMIENDA 2: casos mayores son tests de
MAX_OCULTOS = 15                # RENDIMIENTO y se comen el reloj (ver
                                # tests_lcb); aquí se mide SELECCIÓN.

# MBPP: dos tareas del slice 11-510 cuya solución de REFERENCIA no pasa sus
# propios asserts (180: precisión de float; 367: le falta test_setup_code).
# Se excluyen por prereg: son defectos del dataset, no del modelo.
MBPP_EXCLUIDAS = {180, 367}

SYSTEM_COD = ("You are an expert Python programmer. Reply with ONLY a Python "
              "code block containing the complete function. No explanations.")

_CODE_BLOCK_RX = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


# ----------------------------------------------------------------- código
def extract_code(texto: str) -> str:
    """Bloque markdown; si no hay, código pelado que parezca código.
    Devuelve '' cuando no se pudo extraer nada — el llamador lo cuenta como
    FALLO DE INSTRUMENTO, no como fallo del modelo (contador aparte)."""
    m = _CODE_BLOCK_RX.search(texto or "")
    if m:
        return m.group(1)
    t = (texto or "").strip()
    # bloque abierto sin cerrar (truncamiento): rescatar lo que haya
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
    return t if ("def " in t or "return" in t) else ""


def _ejecuta(src: str, timeout: int = EXEC_TIMEOUT) -> bool:
    """True si el fuente corre con exit 0. Fichero temporal ÚNICO (el
    original de Kaggle reusaba un path fijo: no vale con concurrencia).
    stdin cerrado: un input() del código generado da EOFError y falla, que
    es el veredicto correcto, en vez de colgar la corrida."""
    fd, path = tempfile.mkstemp(suffix=".py", prefix="b3_exec_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        r = subprocess.run([sys.executable, path], capture_output=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# El arnés de lote: UN solo subprocess evalúa TODOS los casos de una muestra.
# LCB trae hasta 40 casos privados por tarea; a un arranque de intérprete por
# caso (~0.15 s) el juez costaría más que la generación. Cada caso corre en un
# namespace FRESCO para que el estado global de uno no contamine al siguiente,
# con stdout/stdin redirigidos, y el lote entero lleva un tope de pared.
_ARNES = r'''
import io, json, sys
sys.setrecursionlimit(100000)

# Preludio de LeetCode: el starter_code usa List/Optional sin importarlos y
# las soluciones de competicion dan por sentado el stdlib habitual. Sin esto
# un NameError contaria como "el modelo falla" cuando falla el ARNES.
#
# OJO CON `from math import *`: sombrea el builtin pow() y rompe pow(a,b,MOD),
# que es el idioma de la exponenciacion modular — 18 de las 175 tareas (10.3%)
# piden el resultado modulo 1e9+7 o 998244353. Verificado aqui:
# pow(2,10,7) -> TypeError. Por eso se importan nombres CONCRETOS de math.
_PRE = ("from typing import *\n"
        "import collections, math, heapq, itertools, bisect, functools, re,"
        " string, random, sys, os, json\n"
        "from collections import *\n"
        "from itertools import *\n"
        "from functools import *\n"
        "from heapq import *\n"
        "from bisect import *\n"
        "from math import (sqrt, gcd, floor, ceil, inf, factorial, comb,"
        " perm, log, log2, log10, hypot, atan2, pi, e, isqrt, lcm)\n")


class _Stdin(io.StringIO):
    """sys.stdin.buffer.read() es EL idioma de entrada rapida en AtCoder
    (112 de las 175 tareas). io.StringIO no tiene .buffer, asi que sin este
    shim cada solucion que lo use puntuaria 0 por fallo de INSTRUMENTO."""

    def __init__(self, texto):
        io.StringIO.__init__(self, texto)
        self.buffer = io.BytesIO(texto.encode("utf-8"))


_cfg = json.loads(open(sys.argv[1], encoding="utf-8").read())
_code, _casos, _modo = _cfg["code"], _cfg["casos"], _cfg["modo"]
_parar = _cfg.get("parar_al_fallar", False)

# Una linea POR CASO, flusheada: si el lote expira, los casos ya resueltos
# siguen contando y solo se pierde el que estaba en vuelo. Con un unico
# print al final, un caso lento anulaba los otros 39 en silencio.
for _i, _c in enumerate(_casos):
    _ok = False
    try:
        _g = {"__name__": "__main__"}
        # exec del preludio SOBRE los globals (no concatenado al fuente):
        # concatenar rompe cualquier solucion que empiece por
        # `from __future__ import ...`, que debe ser la primera sentencia.
        exec(compile(_PRE, "<pre>", "exec"), _g)
        _out = io.StringIO()
        _so, _si = sys.stdout, sys.stdin
        sys.stdout = _out
        sys.stdin = _Stdin(_c.get("input", "") or "")
        try:
            exec(compile(_code, "<sol>", "exec"), _g)
            if _modo == "functional":
                # LCB pasa UN ARGUMENTO POR LINEA, cada uno literal JSON.
                _args = [json.loads(l) for l in
                         (_c.get("input") or "").split("\n") if l.strip()]
                _esp = json.loads(_c.get("output", "null"))
                _fn = _cfg["func_name"]
                _cls = _g.get("Solution")
                _f = getattr(_cls(), _fn) if _cls is not None else _g[_fn]
                _ok = bool(_f(*_args) == _esp)
            elif _modo == "assert":
                exec(compile(_c["assert"], "<t>", "exec"), _g)
                _ok = True
            else:
                _got = "\n".join(l.rstrip() for l in
                                 _out.getvalue().strip().splitlines())
                _esp = "\n".join(l.rstrip() for l in
                                 (_c.get("output") or "").strip().splitlines())
                _ok = (_got == _esp)
        finally:
            sys.stdout, sys.stdin = _so, _si
    except BaseException:
        _ok = False
    print("__B3__%d:%d" % (_i, 1 if _ok else 0), flush=True)
    if _parar and not _ok:
        break
'''


def _ejecuta_lote(code: str, casos: list, modo: str, func_name: str = "",
                  timeout: int = 60, parar_al_fallar: bool = False) -> tuple:
    """Evalúa `casos` contra `code` en UN subprocess.

    Devuelve `(resultados, motivo)`: una lista de bools del largo de `casos`
    y un motivo de instrumento (`""` si todo fue bien). Distinguir el motivo
    importa porque un lote expirado, un arnés reventado y "el código está
    mal" colapsaban al mismo valor — y ese es exactamente el modo de fallo
    característico del repo (degradación silenciosa).

    Un caso resuelto ANTES del timeout cuenta: el arnés emite una línea por
    caso, así que un cuelgue solo pierde el caso en vuelo.
    """
    if not code.strip() or not casos:
        return [False] * len(casos), ("sin_codigo" if not code.strip() else "")
    fd_c, p_cfg = tempfile.mkstemp(suffix=".json", prefix="b3_cfg_")
    fd_a, p_arn = tempfile.mkstemp(suffix=".py", prefix="b3_arn_")
    try:
        with os.fdopen(fd_c, "w", encoding="utf-8") as f:
            json.dump({"code": code, "casos": casos, "modo": modo,
                       "func_name": func_name,
                       "parar_al_fallar": parar_al_fallar}, f)
        with os.fdopen(fd_a, "w", encoding="utf-8") as f:
            f.write(_ARNES)
        motivo = ""
        salida = ""
        try:
            r = subprocess.run([sys.executable, p_arn, p_cfg],
                               capture_output=True, text=True,
                               timeout=timeout, stdin=subprocess.DEVNULL)
            salida = r.stdout or ""
        except subprocess.TimeoutExpired as exc:
            motivo = "lote_expirado"
            salida = (exc.stdout or b"").decode("utf-8", "replace") \
                if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        out = [False] * len(casos)
        vistos = 0
        for linea in salida.splitlines():
            if linea.startswith("__B3__"):
                try:
                    i, v = linea[6:].split(":")
                    out[int(i)] = (v.strip() == "1")
                    vistos += 1
                except (ValueError, IndexError):
                    pass
        if not vistos and not motivo:
            motivo = "sin_sentinel"
        return out, motivo
    except Exception as exc:
        return [False] * len(casos), f"arnes_error: {type(exc).__name__}"
    finally:
        for p in (p_cfg, p_arn):
            try:
                os.unlink(p)
            except OSError:
                pass


# ----------------------------------------------------------------- MBPP
def carga_mbpp() -> list:
    tareas = []
    with open(DATOS / "mbpp.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tareas.append(json.loads(line))
    return tareas


def prompt_mbpp(t: dict) -> str:
    """El prompt de ecod_kernel.prompt_de, literal: enunciado + el primer
    assert (en MBPP la firma de la función SOLO se conoce por los tests)."""
    firma = (t.get("test_list") or [""])[0]
    return f"{t['text']}\nYour function must satisfy tests like: {firma}"


def tests_mbpp(t: dict) -> tuple:
    """Split CONGELADO en el prereg: visibles = test_list[0..1];
    ocultos = test_list[2:] + challenge_test_list."""
    tl = list(t.get("test_list") or [])
    visibles = tl[:2]
    ocultos = tl[2:] + list(t.get("challenge_test_list") or [])
    return visibles, ocultos


def juzga_mbpp(code: str, t: dict, asserts: list) -> tuple:
    """(nº de asserts que pasan, motivo). Cada assert en su namespace fresco:
    uno que revienta no puede enmascarar a los demás. `test_setup_code`
    precede SIEMPRE al código (1 tarea del slice lo tiene no vacío)."""
    if not code.strip() or not asserts:
        return 0, ("sin_codigo" if not code.strip() else "sin_tests")
    setup = (t.get("test_setup_code") or "")
    casos = [{"assert": a} for a in asserts]
    res, motivo = _ejecuta_lote(setup + "\n" + code, casos, "assert",
                                timeout=EXEC_TIMEOUT * max(1, len(asserts)))
    return sum(res), motivo


# ------------------------------------------------------- LiveCodeBench
def carga_lcb(desde: str = "2024-06-30", ficheros: tuple = ()) -> list:
    """Problemas de LiveCodeBench con `contest_date` POSTERIOR al corte de
    entrenamiento del 20B (junio 2024, model card verificada en red).

    Por defecto usa los incrementos que estén descargados. `test6.jsonl` son
    175 problemas de 2025-01 a 2025-04; `test5.jsonl` añade la mitad que
    faltaba (jul-2024 → ene-2025) para cubrir la ventana entera. Se declara
    porque yo mismo firmé "~10 meses" cuando solo tenía los 4 últimos.
    """
    import base64
    import pickle
    import zlib

    if not ficheros:
        ficheros = tuple(n for n in ("lcb_test5.jsonl", "lcb_test6.jsonl")
                         if (DATOS / n).exists())
    tareas = []
    vistos = set()
    for nombre in ficheros:
      with open(DATOS / nombre, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except ValueError:
                # fichero a medias (descarga en curso) o línea corrupta: se
                # salta en vez de tumbar la carga entera. Se avisa, porque
                # una degradación silenciosa aquí daría un banco más pequeño
                # sin que nadie lo note.
                print(f"[carga_lcb] linea ilegible en {nombre}, saltada",
                      flush=True)
                continue
            if (o.get("contest_date") or "")[:10] <= desde:
                continue
            # los incrementos se solapan: un problema puede estar en varios
            if o.get("question_id") in vistos:
                continue
            vistos.add(o.get("question_id"))
            try:
                pub = json.loads(o["public_test_cases"])
            except Exception:
                continue
            priv = o.get("private_test_cases") or ""
            try:
                priv = json.loads(priv)
            except Exception:
                try:
                    priv = json.loads(pickle.loads(zlib.decompress(
                        base64.b64decode(priv.encode("utf-8")))))
                except Exception:
                    priv = []
            if not pub or not priv:
                continue
            meta = o.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            tareas.append({
                "task_id": o["question_id"],
                "titulo": o.get("question_title", ""),
                "fecha": o.get("contest_date", "")[:10],
                "plataforma": o.get("platform", ""),
                "dificultad": o.get("difficulty", ""),
                "enunciado": o.get("question_content", ""),
                "starter_code": o.get("starter_code") or "",
                "func_name": meta.get("func_name", ""),
                "publicos": pub,
                "privados": priv,
            })
    return tareas


def prompt_lcb(t: dict) -> str:
    """Prompt estándar de LCB: enunciado + modo de E/S. Sin adornos."""
    if t["starter_code"].strip():
        return (f"{t['enunciado']}\n\n"
                f"You will use the following starter code and complete the "
                f"solution:\n```python\n{t['starter_code']}\n```\n"
                f"Return ONLY the completed code block.")
    return (f"{t['enunciado']}\n\n"
            f"Read from standard input and write to standard output. "
            f"Return ONLY a Python code block with the complete program.")


def juzga_lcb(code: str, t: dict, casos: list,
              parar_al_fallar: bool = False) -> tuple:
    """(nº de casos que pasan, motivo). `stdin`: se alimenta por stdin y se
    compara la salida normalizada. `functional`: se llama a func_name con
    los args.

    Presupuesto POR TEST (`SEG_POR_TEST`, el estándar de LCB), no un tope
    global de 8 s: con mediana 40 tests privados, un global de 8 s reprobaría
    en masa soluciones correctas y tiraría el pass@1 fuera de banda por la
    razón equivocada.
    """
    if not code.strip() or not casos:
        return 0, ("sin_codigo" if not code.strip() else "sin_tests")
    modo = "functional" if (casos[0].get("testtype") == "functional"
                            or t.get("func_name")) else "stdin"
    tope = min(TOPE_LOTE, max(30, SEG_POR_TEST * len(casos)))
    res, motivo = _ejecuta_lote(code, casos, modo, t.get("func_name", ""),
                                timeout=tope, parar_al_fallar=parar_al_fallar)
    return sum(res), motivo


def tests_lcb(t: dict, rng: random.Random) -> tuple:
    """Split de B-LCB, ENMENDADO tras la revisión adversarial.

    Los `public_test_cases` NO sirven como examen del selector: están
    impresos en el enunciado (medido: 78.0% de los casos, y **77.1% de los
    problemas tienen TODOS los suyos dentro de `question_content`**), que es
    justo lo que va al prompt. Usarlos daría al selector un examen que el
    generador YA VIO — el vicio `aprobado_sel` del gate, en su forma peor.
    Y además 24.0% de los problemas tienen algún público dentro de `private`.

    Así que el split se construye ENTERO desde `private_test_cases`, que no
    aparecen en ningún prompt: **5 sorteados con semilla fija como VISIBLES,
    el resto como OCULTOS**, disjuntos por construcción.
    """
    # ENMIENDA 2: se descartan los casos con entrada > MAX_BYTES_CASO y se
    # capan los ocultos a MAX_OCULTOS. Motivo medido: 37 de 167 tareas (22%)
    # traen >1 MB de entradas ocultas (máx 19 MB) — son tests de RENDIMIENTO,
    # y a 210 s de tope por lote se comían el reloj de la noche (ritmo
    # observado: 0.57 muestras/min, ~17 h para la corrida).
    # Aquí se mide SELECCIÓN, no eficiencia, y el mismo recorte se aplica a
    # los cuatro brazos, así que no sesga el contraste. Todas las muestras
    # se RE-JUZGAN con este criterio al final, para que el instrumento sea
    # uniforme en toda la corrida.
    priv = [c for c in t["privados"]
            if len(c.get("input") or "") <= MAX_BYTES_CASO]
    if len(priv) < LCB_VISIBLES + 2:
        return [], []                      # sin margen para partir
    idx = list(range(len(priv)))
    rng.shuffle(idx)
    vis = [priv[i] for i in idx[:LCB_VISIBLES]]
    oc = [priv[i] for i in idx[LCB_VISIBLES:LCB_VISIBLES + MAX_OCULTOS]]
    return vis, oc


# ------------------------------------------------------------ generación
def genera(prompt: str, temperature: float, max_tokens: int = 0) -> tuple:
    """Devuelve (texto, motivo). motivo != '' marca FALLO DE INSTRUMENTO
    (sin respuesta, truncado por longitud, HTTP): se cuenta aparte y NUNCA
    como fallo del modelo — la degradación silenciosa es el modo de fallo
    característico de este repo."""
    payload = {
        "model": "local",
        "messages": [{"role": "system", "content": SYSTEM_COD},
                     {"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens or MAX_TOKENS,
        "chat_template_kwargs": {"reasoning_effort": REASONING_EFFORT},
    }
    req = urllib.request.Request(
        BACKEND + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_HTTP) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return "", f"http: {type(exc).__name__}: {exc}"[:120]
    try:
        ch = data["choices"][0]
        texto = (ch["message"].get("content") or "").strip()
        fin = ch.get("finish_reason", "")
    except Exception as exc:
        return "", f"formato: {exc}"[:120]
    if fin == "length":
        return texto, "truncado_por_longitud"
    if not texto:
        return "", "respuesta_vacia"
    return texto, ""


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--banco", choices=["mbpp", "lcb"], required=True)
    ap.add_argument("--n", type=int, default=100, help="nº de tareas")
    ap.add_argument("--k", type=int, default=4, help="muestras por tarea")
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--semilla", type=int, default=20260730)
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--sufijo", default="")
    ap.add_argument("--pared", type=int, default=180,
                    help="tope de pared por muestra, en segundos")
    ap.add_argument("--dificultad", default="",
                    help="lcb: filtrar a easy|medium|hard (coma-separado)")
    ap.add_argument("--max-tokens", dest="max_tokens", type=int, default=0,
                    help="0 = MAX_TOKENS (4096); LCB usa 8192 por prereg")
    args = ap.parse_args()
    if args.banco == "lcb" and not args.max_tokens:
        # Presupuesto de PENSAMIENTO: LCB es competitiva y las respuestas son
        # 5-15x más largas que en MBPP. El repo lleva 7 bugs por un
        # max_tokens que no cubría el razonamiento.
        args.max_tokens = 8192

    SALIDA.mkdir(exist_ok=True)
    fichero = SALIDA / f"{args.banco}{args.sufijo}.json"

    if args.banco == "mbpp":
        todas = carga_mbpp()
        # slice de evaluación pre-registrado: task_id 11..510
        pool = [t for t in todas if 11 <= t["task_id"] <= 510
                and t["task_id"] not in MBPP_EXCLUIDAS]
        rng = random.Random(args.semilla)
        rng.shuffle(pool)
        tareas = pool[:args.n]
        for t in tareas:
            t["_id"] = str(t["task_id"])
            t["_prompt"] = prompt_mbpp(t)
            t["_vis"], t["_oc"] = tests_mbpp(t)
    else:
        pool = carga_lcb()
        if args.dificultad:
            pool = [t for t in pool
                    if t["dificultad"] in args.dificultad.split(",")]
        rng = random.Random(args.semilla)
        rng.shuffle(pool)
        # El split de LCB se sortea con un RNG propio y determinista POR
        # TAREA, para que no dependa de cuántas tareas se corran ni del
        # orden: reanudar o ampliar N no puede cambiar el examen.
        tareas = []
        for t in pool:
            t["_id"] = str(t["task_id"])
            t["_prompt"] = prompt_lcb(t)
            t["_vis"], t["_oc"] = tests_lcb(
                t, random.Random(f"{args.semilla}:{t['_id']}"))
            if t["_vis"] and t["_oc"]:
                tareas.append(t)
            if len(tareas) >= args.n:
                break

    print(f"[b3] banco={args.banco} tareas={len(tareas)} k={args.k} "
          f"temp={args.temp} backend={BACKEND}", flush=True)
    if args.banco == "lcb":
        fechas = sorted(t["fecha"] for t in tareas)
        print(f"[b3] ventana temporal: {fechas[0]} .. {fechas[-1]} "
              f"(corte del 20B: 2024-06)", flush=True)

    # ---- reanudación (el patrón de b2_bon_heldout: sin el flag, abortar) --
    res = {"banco": args.banco, "k": args.k, "temp": args.temp,
           "semilla": args.semilla, "n_pedidas": args.n,
           "max_tokens": args.max_tokens or MAX_TOKENS,
           "reasoning_effort": REASONING_EFFORT,
           "seg_por_test": SEG_POR_TEST, "lcb_visibles": LCB_VISIBLES,
           "prereg": "PREREG_BANCO_CODIGO_20260730.md",
           "muestras": []}
    if fichero.exists():
        if not args.reanudar:
            print(f"ABORTA: {fichero} ya existe y correr sin --reanudar lo "
                  f"SOBRESCRIBIRÍA en silencio.", flush=True)
            sys.exit(2)
        res = json.loads(fichero.read_text(encoding="utf-8"))
        # mezclar k, semilla, temp o banco falsea el apareado igual de mal
        for campo, valor in (("k", args.k), ("semilla", args.semilla),
                             ("temp", args.temp), ("banco", args.banco)):
            if res.get(campo) != valor:
                print(f"ABORTA: el fichero tiene {campo}={res.get(campo)!r} "
                      f"y se pide {valor!r}; mezclarlo falsearía el "
                      f"apareado.", flush=True)
                sys.exit(2)
        print(f"[b3] reanudando: {len(res['muestras'])} muestras en disco",
              flush=True)
    hechas = {(m["tarea"], m["s"]) for m in res["muestras"]}

    def guardar():
        tmp = fichero.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero)

    t0 = time.time()
    for i, t in enumerate(tareas):
        for s in range(1, args.k + 1):
            if (t["_id"], s) in hechas:
                continue
            ts = time.time()
            # Tope de pared DURO por muestra: el timeout de urllib es POR
            # OPERACIÓN de socket, así que un backend que gotea tokens no lo
            # dispara nunca (medido: una celda colgó >45 min). Sin esto, una
            # sola tarea puede llevarse la noche.
            try:
                texto, motivo = con_presupuesto(
                    args.pared, genera, t["_prompt"], args.temp,
                    args.max_tokens)
            except PresupuestoAgotado:
                texto, motivo = "", f"presupuesto_pared_{args.pared}s"
            code = extract_code(texto)
            if not code and not motivo:
                motivo = "sin_codigo_extraible"
            if args.banco == "mbpp":
                vis_ok, m_vis = juzga_mbpp(code, t, t["_vis"])
                oc_ok, m_oc = juzga_mbpp(code, t, t["_oc"])
            else:
                vis_ok, m_vis = juzga_lcb(code, t, t["_vis"])
                # el oculto solo decide PASA/NO PASA, así que se corta al
                # primer fallo: con mediana 35 ocultos eso es la diferencia
                # entre una noche y tres.
                oc_ok, m_oc = juzga_lcb(code, t, t["_oc"],
                                        parar_al_fallar=True)
            res["muestras"].append({
                "tarea": t["_id"], "s": s,
                "vis_ok": vis_ok, "vis_n": len(t["_vis"]),
                "oc_ok": oc_ok, "oc_n": len(t["_oc"]),
                "pasa_vis": vis_ok == len(t["_vis"]) and len(t["_vis"]) > 0,
                "pasa_oc": oc_ok == len(t["_oc"]) and len(t["_oc"]) > 0,
                "instrumento": motivo,
                "juez_vis": m_vis, "juez_oc": m_oc,
                "segundos": round(time.time() - ts, 1),
                "crudo": texto[:6000],
            })
            guardar()
        hechos = len(res["muestras"])
        if i % 5 == 0 or i == len(tareas) - 1:
            oc = sum(1 for m in res["muestras"] if m["pasa_oc"])
            inst = sum(1 for m in res["muestras"] if m["instrumento"])
            print(f"[b3] tarea {i+1}/{len(tareas)} muestras={hechos} "
                  f"pasa_oc={oc} ({oc/max(1,hechos):.1%}) instrumento={inst} "
                  f"({(time.time()-t0)/60:.0f} min)", flush=True)

    guardar()
    ms = res["muestras"]
    oc = sum(1 for m in ms if m["pasa_oc"])
    print(f"[b3] FIN {len(ms)} muestras; pass@1(oculto)={oc/max(1,len(ms)):.1%}"
          f"  instrumento={sum(1 for m in ms if m['instrumento'])}", flush=True)
    print(f"[b3] -> {fichero}", flush=True)


if __name__ == "__main__":
    main()
