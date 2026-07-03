"""
cognia/agent/candidates.py
==========================
Best-of-N + juez por tests visibles (palanca #1 de 06_AGENTE_PLAN.md §2).

Evidencia externa en nuestro rango: Qwen2.5-Coder-3B con 10 candidatos + juez
SLM = pass@1 0.361 -> 0.521 (+15.6pp). Nuestro juez v1 es el mas barato
NO-circular disponible: tests visibles generados por el propio modelo ANTES
del codigo (test-first, palanca #2) y EJECUTADOS de verdad en subprocess.
Jerarquia del rank (pre-registrada): tests visibles (oraculo duro) >
bpb-MoM (desempate, HIPOTESIS §1 — se retira si no supera a random) >
primero (indice 0 = greedy).

PROHIBIDO por diseño (P8/CYCLE 12): autocritica ciega como juez — un LLM
juzgando "que candidato se ve mejor" colapsa a gaming. Si no hay tests
visibles, el rank degrada a greedy y lo DECLARA en rank_mode.

Concreto: funciones planas; el generador entra como ``gen_fn(prompt,
temperature, seed) -> str`` para servir igual al harness (LlamaBackend) y
al agente (orch.infer).
"""
from __future__ import annotations

import ast
import re

DEFAULT_N = 8
SAMPLE_TEMPERATURE = 0.7

# ── Generacion de candidatos ────────────────────────────────────────────

def generate_candidates(gen_fn, prompt, n=DEFAULT_N, seed=42):
    """N respuestas del modelo: candidato 0 greedy (temp 0, reproducible),
    el resto a temp 0.7 con seeds consecutivas distintas. Devuelve la lista
    de textos CRUDOS (el caller extrae el codigo con su propio parser)."""
    outs = []
    for i in range(max(1, n)):
        temp = 0.0 if i == 0 else SAMPLE_TEMPERATURE
        s = (seed + i) if seed is not None else None
        outs.append(gen_fn(prompt, temperature=temp, seed=s) or "")
    return outs


def dedupe_codes(codes):
    """Indices de codigos unicos (normalizados por whitespace), en orden.
    Generar 8 veces lo MISMO no aporta señal; ejecutar duplicados es tirar
    tiempo de sandbox."""
    seen, keep = set(), []
    for i, code in enumerate(codes):
        key = re.sub(r"\s+", " ", (code or "").strip())
        if key and key not in seen:
            seen.add(key)
            keep.append(i)
    return keep


# ── Tests visibles (test-first, palanca #2) ─────────────────────────────

TEST_GEN_SYSTEM = ("You are an expert Python tester. Reply with ONLY assert "
                   "statements, one per line. No function definitions, no "
                   "explanations, no code fences.")

_TEST_GEN_PROMPT = (
    "{task}\n\n"
    "Do NOT write the function. Write {k} assert statements that a correct "
    "`{entry_point}` implementation must satisfy, based ONLY on the task "
    "description above. One assert per line, each calling {entry_point}(...) "
    "with concrete values. Cover an edge case."
)


def build_test_gen_prompt(task_prompt, entry_point, k=4):
    """Prompt del paso test-first (el caller lo pasa por su template ChatML)."""
    return _TEST_GEN_PROMPT.format(task=task_prompt, k=k,
                                   entry_point=entry_point)


def extract_asserts(text, entry_point, max_asserts=6):
    """Lineas ``assert ...`` sintacticamente validas que llaman a
    entry_point. Filtra prosa, fences y asserts triviales (sin la funcion).
    Deduplica preservando orden."""
    if not text:
        return []
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("assert "):
            continue
        if entry_point + "(" not in line:
            continue
        try:
            ast.parse(line)
        except SyntaxError:
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
        if len(out) >= max_asserts:
            break
    return out


def generate_visible_tests(gen_fn, task_prompt, entry_point, k=4, seed=42):
    """Pide los asserts al modelo (greedy) y extrae los validos. Puede
    devolver lista vacia: el caller degrada a greedy y lo declara."""
    raw = gen_fn(build_test_gen_prompt(task_prompt, entry_point, k),
                 temperature=0.0, seed=seed) or ""
    return extract_asserts(raw, entry_point)


# ── Juez: ejecucion real de los tests visibles ──────────────────────────

def score_candidate(code, asserts, entry_point):
    """(n_passed, n_total) ejecutando el codigo contra CADA assert por
    separado en subprocess aislado (granularidad por assert: un candidato
    que pasa 3/4 gana a uno que pasa 1/4 aunque ambos 'fallen')."""
    from cognia_v3.eval.benchmark_code import run_task_tests
    passed = 0
    for a in asserts:
        ok, _, _ = run_task_tests(code, a + "\n", entry_point)
        if ok:
            passed += 1
    return passed, len(asserts)


def rank_candidates(codes, asserts, entry_point, bpb_fn=None):
    """Rankea codigos-candidato. Devuelve (mejor_idx, ranking, rank_mode).

    ranking = [{idx, score, total, bpb}] orden final. Jerarquia:
      1. score de tests visibles (desc) — oraculo duro;
      2. bpb_fn(code) (asc, opcional) — desempate HIPOTESIS bpb-MoM;
      3. idx (asc) — el candidato 0 es greedy: ante empate total, gana lo
         reproducible.
    rank_mode: "tests" | "tests+bpb" | "greedy_fallback" (sin asserts o sin
    candidatos utiles — se declara, nunca se disimula)."""
    keep = dedupe_codes(codes)
    if not keep:
        return 0, [], "greedy_fallback"
    if not asserts:
        return keep[0], [{"idx": i, "score": 0, "total": 0, "bpb": None}
                         for i in keep], "greedy_fallback"

    ranking = []
    for i in keep:
        n_pass, n_total = score_candidate(codes[i], asserts, entry_point)
        bpb = None
        if bpb_fn is not None:
            try:
                bpb = float(bpb_fn(codes[i]))
            except Exception:
                bpb = None
        ranking.append({"idx": i, "score": n_pass, "total": n_total,
                        "bpb": bpb})

    use_bpb = bpb_fn is not None and all(r["bpb"] is not None for r in ranking)
    ranking.sort(key=lambda r: (-r["score"],
                                r["bpb"] if use_bpb else 0.0,
                                r["idx"]))
    mode = "tests+bpb" if use_bpb else "tests"
    return ranking[0]["idx"], ranking, mode


def best_of_n(gen_fn, prompt, task_prompt, entry_point, extract_code_fn,
              n=DEFAULT_N, seed=42, bpb_fn=None, test_k=4, test_gen_fn=None):
    """Pipeline completo test-first + BoN: genera tests visibles, genera N
    candidatos, rankea por ejecucion real. Devuelve dict con el elegido y
    la traza completa (para el JSON del bench y el post-mortem AG-ARB).

    ``test_gen_fn``: generador para el paso test-first (suele llevar OTRO
    system prompt — asserts-only vs code-only); default = gen_fn."""
    visible = generate_visible_tests(test_gen_fn or gen_fn, task_prompt,
                                     entry_point, k=test_k, seed=seed)
    raws = generate_candidates(gen_fn, prompt, n=n, seed=seed)
    codes = [extract_code_fn(r) for r in raws]
    best_idx, ranking, mode = rank_candidates(codes, visible, entry_point,
                                              bpb_fn=bpb_fn)
    return {
        "best_idx": best_idx,
        "code": codes[best_idx] if codes else "",
        "response": raws[best_idx] if raws else "",
        "rank_mode": mode,
        "visible_tests": visible,
        "ranking": ranking,
        "n_generated": len(raws),
        "n_unique": len(dedupe_codes(codes)),
    }
