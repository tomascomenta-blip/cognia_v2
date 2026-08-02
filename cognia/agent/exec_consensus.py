"""
cognia/agent/exec_consensus.py
==============================
Consenso por EJECUCIÓN para desempatar candidatos (ROMPER EL TECHO, ataque A).

El techo del código duro es en parte de ORÁCULO: los tests visibles
autogenerados por el 3B son débiles (verifier accuracy ~22% en la
literatura) y dejan pasar varios candidatos que "empatan" pero difieren en
los bordes. Cuando eso pasa, best_of_n elige por índice — a ciegas.

Este módulo agrega el eslabón que faltaba (medido en S*, arXiv 2502.14382:
3B 18.4→42.7, 7B 29.4→54.4 en LiveCodeBench a N=16): entre los candidatos
empatados, el modelo genera INPUTS distinguidores (fácil — solo llamadas,
sin outputs esperados), se EJECUTAN todos los candidatos sobre esos inputs,
y se elige por CONSENSO de comportamiento observado (el grupo mayoritario
por firma de ejecución).

Respeta juez-LLM-PROHIBIDO (candidates.py P8): el LLM solo PROPONE inputs;
el veredicto lo da el sandbox comparando outputs reales. Nunca un LLM juzga
"qué candidato se ve mejor". La hipótesis (CodeT/S*): la solución CORRECTA
es la moda del comportamiento — los bugs difieren entre sí, los aciertos
coinciden.

Concreto: funciones planas; ejecución en subprocess aislado (mismo molde
que benchmark_code.run_task_tests).
"""
from __future__ import annotations

import ast
import logging
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

_LOG = logging.getLogger("cognia.exec_consensus")

_INPUT_GEN_SYSTEM = ("You are an expert Python tester. Reply with ONLY calls "
                     "to the function, one per line. No asserts, no expected "
                     "values, no explanations, no code fences.")

_INPUT_GEN_PROMPT = (
    "{task}\n\n"
    "Write {k} diverse lines, each a single call to `{entry_point}(...)` with "
    "CONCRETE argument values, covering normal cases AND tricky edge cases "
    "(empty, negative, boundary, malformed). Do NOT write the expected result "
    "— only the call, one per line."
)


def build_input_gen_prompt(task_prompt, entry_point, k=6):
    return _INPUT_GEN_PROMPT.format(task=task_prompt, k=k,
                                    entry_point=entry_point)


def _call_dentro_de_assert(line, entry_point):
    """De ``assert entry(...) == <lo que sea>`` devuelve ``entry(...)``; None
    si la línea no tiene esa forma.

    POR QUÉ: el generador de inputs se le pide a un modelo que muchas veces
    corre con un system prompt "responde SOLO con asserts" (así lo llama el
    bench y el agente para el paso test-first). Con eso el modelo devuelve
    `assert entry(2) == 4` en vez de `entry(2)` y el consenso se quedaba con
    CERO inputs — muerte silenciosa medida el 2026-08-01 contra :8080. El
    valor esperado del assert se DESCARTA (sería un oráculo-LLM, prohibido
    por P8): acá solo se rescata la LLAMADA, que es lo único que el consenso
    necesita para ejecutar y comparar comportamientos."""
    try:
        nodo = ast.parse(line)
    except SyntaxError:
        return None
    if not nodo.body or not isinstance(nodo.body[0], ast.Assert):
        return None
    test = nodo.body[0].test
    cand = test.left if isinstance(test, ast.Compare) else test
    if not isinstance(cand, ast.Call):
        return None
    if not (isinstance(cand.func, ast.Name) and cand.func.id == entry_point):
        return None
    try:
        return ast.unparse(cand)
    except Exception:                              # pragma: no cover (py<3.9)
        return None


def extract_input_calls(text, entry_point, max_calls=8):
    """Líneas que son UNA llamada a entry_point, sintácticamente válidas.
    Filtra prosa y fences; de los asserts rescata SOLO la llamada (ver
    _call_dentro_de_assert). Deduplica preservando orden."""
    if not text:
        return []
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # tolerar fences / prefijos tipo ">>> "
        line = line.lstrip("> ").strip("`").strip()
        if line.startswith("assert "):
            line = _call_dentro_de_assert(line, entry_point)
            if not line:
                continue
        if not line.startswith(entry_point + "("):
            continue
        try:
            node = ast.parse(line, mode="eval")
        except SyntaxError:
            continue
        if not isinstance(node.body, ast.Call):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
        if len(out) >= max_calls:
            break
    return out


# Timeout/entorno: reusa el del sandbox del bench si está disponible.
try:
    from cognia_v3.eval.benchmark_code import EXEC_TIMEOUT_S as _TIMEOUT
    from cognia_v3.eval.benchmark_code import _sandbox_env as _sbenv
except Exception:                                  # pragma: no cover
    _TIMEOUT = 10

    def _sbenv():
        import os
        return dict(os.environ)


def behavior_signature(code, entry_point, input_calls):
    """Firma de comportamiento de `code`: tupla con el repr del resultado (o
    'ERR:<Tipo>') de cada input, ejecutada en subprocess aislado. Devuelve
    None si el código ni siquiera importa/define la función (candidato
    inservible, no entra al consenso)."""
    if not code.strip() or f"def {entry_point}" not in code:
        return None
    lines = ["import json as _J", "_R_ = []"]
    for expr in input_calls:
        lines.append("try:")
        lines.append(f"    _R_.append(repr({expr}))")
        lines.append("except Exception as _e:")
        lines.append("    _R_.append('ERR:' + type(_e).__name__)")
    lines.append("print('SIG:' + _J.dumps(_R_))")
    script = code + "\n\n" + "\n".join(lines) + "\n"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="cognia_consensus_",
                delete=False, encoding="utf-8") as f:
            tmp = f.name
            f.write(script)
        proc = subprocess.run([sys.executable, tmp], capture_output=True,
                              text=True, timeout=_TIMEOUT, env=_sbenv())
        for line in (proc.stdout or "").splitlines():
            if line.startswith("SIG:"):
                import json
                return tuple(json.loads(line[4:]))
        return None                                # no imprimió firma
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    finally:
        if tmp:
            try:
                Path(tmp).unlink()
            except Exception:
                pass


def consensus_pick(codes, input_calls, entry_point, tied_idxs=None):
    """Índice del candidato en el MAYOR cluster de comportamiento (CodeT/S*).

    codes: lista de códigos candidatos (str). tied_idxs: subconjunto de
    índices a considerar (los que empataron en tests visibles); si None,
    todos. Devuelve (idx_elegido, info) donde info trae el tamaño del
    cluster ganador y el nº de clusters — o (None, info) si no hay señal
    (0-1 firmas válidas, o sin inputs). El desempate dentro del cluster
    ganador es por idx menor (reproducible; respeta el greedy=0)."""
    idxs = tied_idxs if tied_idxs is not None else list(range(len(codes)))
    info = {"n_considered": len(idxs), "n_valid": 0, "n_clusters": 0,
            "winner_size": 0, "n_inputs": len(input_calls), "reason": None}
    # `reason` SIEMPRE poblado: sin el, "desempate" y "no pude desempatar"
    # se veian IGUAL desde afuera y el caller caia al indice en silencio.
    if not input_calls:
        info["reason"] = "sin_inputs"        # el generador no dio llamadas
        return None, info
    if len(idxs) < 2:
        info["reason"] = "sin_empate"
        return None, info
    sigs = {}
    for i in idxs:
        sig = behavior_signature(codes[i], entry_point, input_calls)
        if sig is not None:
            sigs[i] = sig
    info["n_valid"] = len(sigs)
    if len(sigs) < 2:
        info["reason"] = "unico_ejecutable" if sigs else "sin_firmas_validas"
        return (next(iter(sigs)) if sigs else None), info
    counts = Counter(sigs.values())
    info["n_clusters"] = len(counts)
    top_sig, top_n = counts.most_common(1)[0]
    info["winner_size"] = top_n
    # empate de clusters (todos distintos, o dos parejos) => sin señal
    if top_n < 2:
        info["reason"] = "sin_moda"
        return None, info
    ganador = min(i for i in sigs if sigs[i] == top_sig)   # idx menor
    info["reason"] = "consenso"
    return ganador, info


def _declarar(info):
    """Deja constancia RUIDOSA de que el consenso no pudo desempatar.

    Sin esto el caller cae al desempate por indice y el resultado es
    indistinguible de "el consenso eligio ese candidato": exactamente el
    modo de fallo prohibido (degradar en silencio). Va por logging.WARNING,
    que sin handlers configurados igual sale por stderr (lastResort)."""
    _LOG.warning("consenso NO desempata: reason=%s n_inputs=%s n_valid=%s "
                 "n_clusters=%s%s", info.get("reason"), info.get("n_inputs"),
                 info.get("n_valid"), info.get("n_clusters"),
                 (" raw=" + repr(info["raw_preview"][:80]))
                 if info.get("raw_preview") else "")


def consensus_tiebreak(codes, tied_idxs, gen_fn, task_prompt, entry_point,
                       k_inputs=6, seed=42):
    """Desempate de un BoN: entre los candidatos EMPATADOS (tied_idxs, que
    comparten el top score de tests visibles), genera inputs distinguidores
    con gen_fn, ejecuta y elige por consenso de comportamiento. Devuelve
    (idx_o_None, info). None = sin señal → el caller mantiene su desempate
    por índice (fallback seguro). Respeta CE-2: solo se llama sobre EMPATES,
    nunca overridea un candidato con más tests visibles.

    gen_fn(prompt, temperature, seed) -> str (mismo contrato que candidates).
    El caller envuelve el prompt en su template; acá se pasa crudo."""
    if len(tied_idxs) < 2:
        return None, {"n_considered": len(tied_idxs), "reason": "sin_empate",
                      "n_inputs": 0}
    try:
        raw = gen_fn(build_input_gen_prompt(task_prompt, entry_point, k_inputs),
                     temperature=0.0, seed=seed) or ""
    except Exception as exc:
        info = {"n_considered": len(tied_idxs), "reason": "gen_fn_fallo",
                "n_inputs": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
        _declarar(info)
        return None, info
    inputs = extract_input_calls(raw, entry_point)
    idx, info = consensus_pick(codes, inputs, entry_point,
                               tied_idxs=tied_idxs)
    info["inputs"] = inputs
    if not inputs:
        # Muestra del crudo: si el generador vino con el system prompt
        # equivocado (p.ej. "responde SOLO con asserts") esto lo delata en
        # el JSON del bench en vez de dejarlo morir en silencio.
        info["raw_preview"] = raw.strip()[:200]
    if idx is None:
        _declarar(info)
    return idx, info
