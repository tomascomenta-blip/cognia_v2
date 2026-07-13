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
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

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


def extract_input_calls(text, entry_point, max_calls=8):
    """Líneas que son UNA llamada a entry_point, sintácticamente válidas.
    Filtra asserts, prosa, fences. Deduplica preservando orden."""
    if not text:
        return []
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("assert ") or not line:
            continue
        # tolerar fences / prefijos tipo ">>> "
        line = line.lstrip("> ").strip("`").strip()
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
            "winner_size": 0, "n_inputs": len(input_calls)}
    if not input_calls or len(idxs) < 2:
        return None, info
    sigs = {}
    for i in idxs:
        sig = behavior_signature(codes[i], entry_point, input_calls)
        if sig is not None:
            sigs[i] = sig
    info["n_valid"] = len(sigs)
    if len(sigs) < 2:
        return (next(iter(sigs)) if sigs else None), info
    counts = Counter(sigs.values())
    info["n_clusters"] = len(counts)
    top_sig, top_n = counts.most_common(1)[0]
    info["winner_size"] = top_n
    # empate de clusters (todos distintos, o dos parejos) => sin señal
    if top_n < 2:
        return None, info
    ganador = min(i for i in sigs if sigs[i] == top_sig)   # idx menor
    return ganador, info


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
        return None, {"n_considered": len(tied_idxs), "reason": "sin_empate"}
    try:
        raw = gen_fn(build_input_gen_prompt(task_prompt, entry_point, k_inputs),
                     temperature=0.0, seed=seed) or ""
    except Exception:
        return None, {"reason": "gen_fn_fallo"}
    inputs = extract_input_calls(raw, entry_point)
    return consensus_pick(codes, inputs, entry_point, tied_idxs=tied_idxs)
