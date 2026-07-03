"""
Cognia BFCL-slice benchmark: Eje 1 (tool-calling) del plan pre-registrado
cognia_x/construccion/xhundred/06_AGENTE_PLAN.md #4.

Slice CONGELADA de BFCL v3 (checker AST oficial, prompting mode, SIN
ejecutar APIs reales -> corre en CPU pelada): 200 items = 40 por categoria x
5 categorias (simple, multiple, parallel, parallel_multiple, live_simple),
muestreo determinista seed=42. La slice se materializa UNA sola vez en
data/bfcl/slice_200.json y despues SE LEE de ahi (congelada: correr este
harness dos veces sobre el mismo repo da SIEMPRE los mismos 200 ids).

Datos: cognia_v3/eval/data/bfcl/ (descargados de
github.com/ShishirPatil/gorilla, commit congelado
cd9429ccf3d4d04156affe883c495b3b047e6b64 -- el ultimo commit con nombres
BFCL_v3_* antes del rename a v4, ver bfcl_ast_checker.py para el detalle).
Checker: cognia_v3/eval/bfcl_ast_checker.py (port declarado del eval_checker
oficial, simplificaciones documentadas en su docstring).

Prompting mode (no function-calling nativo del backend): el prompt lista
las tools disponibles en JSON + la pregunta, pidiendo la(s) llamada(s) en
sintaxis Python `func(param=value)` separadas por ';', sin prosa.

Usage:
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_bfcl_slice --check-only
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_bfcl_slice --limit 10 --label smoke
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_bfcl_slice --label baseline

Backend: reusa cognia_v3.eval.benchmark_code.make_backend() (mismo
LlamaBackend.try_load(), sin duplicar el arranque del server). Prompt:
ChatML via node.inference_pipeline._apply_qwen_template (igual que
benchmark_code.py).
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import time
from pathlib import Path

from cognia_v3.eval.bfcl_ast_checker import check_response, parse_model_response

EVAL_DIR = Path(__file__).resolve().parent
DATA_DIR = EVAL_DIR / "data" / "bfcl"
POSSIBLE_ANSWER_DIR = DATA_DIR / "possible_answer"
SLICE_PATH = DATA_DIR / "slice_200.json"

# Las 5 categorias prompt-based Python de BFCL v3 elegidas por el plan (todas
# non-live salvo live_simple; multi-turn queda explicitamente FUERA, ver #4
# del plan). En este orden se arma la slice (bloques de 40 por categoria).
CATEGORIES = ["simple", "multiple", "parallel", "parallel_multiple", "live_simple"]
PER_CATEGORY = 40
SLICE_SEED = 42  # fijo -- NO es el --seed de generacion (ese es del modelo)

DEFAULT_MAX_TOKENS = 512
BASE_TEMPERATURE = 0.0  # greedy: pass@1 reproducible, igual que benchmark_code.py

SYSTEM_PROMPT = (
    "You are a function-calling assistant. You are given a user request and a "
    "list of available functions in JSON format. Reply with ONLY the function "
    "call(s) needed to fulfill the request, using Python syntax: "
    "func(param=value). If more than one call is needed, separate them with "
    "';'. Do not output any prose, explanation, or markdown -- only the call(s)."
)


def _data_path(category: str) -> Path:
    return DATA_DIR / f"BFCL_v3_{category}.json"


def _answer_path(category: str) -> Path:
    return POSSIBLE_ANSWER_DIR / f"BFCL_v3_{category}.json"


def load_category_items(category: str) -> dict:
    """id -> item crudo (question/function), leido del JSONL de la categoria
    (1 objeto JSON por linea -- asi lo distribuye Gorilla, no es una lista)."""
    items = {}
    with open(_data_path(category), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            items[item["id"]] = item
    return items


def load_category_answers(category: str) -> dict:
    """id -> ground_truth (lista de {func_name: {param: [valores aceptables]}})."""
    answers = {}
    with open(_answer_path(category), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            answers[item["id"]] = item["ground_truth"]
    return answers


def build_slice() -> list[dict]:
    """
    Slice CONGELADA: si data/bfcl/slice_200.json ya existe se lee tal cual
    (NUNCA se re-muestrea). Si no existe, se construye: PER_CATEGORY ids por
    categoria, muestreados con random.Random(SLICE_SEED).sample() sobre la
    lista de ids de esa categoria ORDENADA (un Random(42) nuevo por
    categoria -- reproducible categoria por categoria, no depende del orden
    en que se recorren las 5), y se persiste a disco.
    """
    if SLICE_PATH.exists():
        with open(SLICE_PATH, encoding="utf-8") as f:
            return json.load(f)

    slice_items = []
    for category in CATEGORIES:
        ids = sorted(load_category_items(category).keys())
        chosen = random.Random(SLICE_SEED).sample(ids, PER_CATEGORY)
        for item_id in chosen:
            slice_items.append({"id": item_id, "category": category})

    SLICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SLICE_PATH, "w", encoding="utf-8") as f:
        json.dump(slice_items, f, indent=2, ensure_ascii=False)
    return slice_items


def question_text_of(item: dict) -> str:
    """Texto de la pregunta: las 5 categorias son single-turn (1 turno con
    1+ mensajes) -- se concatenan los mensajes del unico turno en orden."""
    turn = item["question"][0]
    return "\n".join(f"{m['role']}: {m['content']}" for m in turn)


def build_prompt(functions: list, question_text: str) -> str:
    """ChatML (Qwen) con las tools disponibles (JSON) + la pregunta."""
    from node.inference_pipeline import _apply_qwen_template
    user_msg = ("Available functions:\n" + json.dumps(functions, indent=2)
                + "\n\nQuestion: " + question_text)
    return _apply_qwen_template(user_msg, system=SYSTEM_PROMPT)


def make_backend():
    """Reusa el backend del benchmark de codigo (mismo LlamaBackend.try_load(),
    no se duplica el arranque del llama-server)."""
    from cognia_v3.eval.benchmark_code import make_backend as _make_backend
    return _make_backend()


# ---------------------------------------------------------------------------
# ground_truth -> respuesta "perfecta" (para el self-test del checker)
# ---------------------------------------------------------------------------

def _find_function_tolerant(functions: list, func_name: str) -> dict | None:
    for fd in functions:
        if fd["name"] == func_name:
            return fd
    mangled = func_name.replace(".", "_")
    for fd in functions:
        if fd["name"] == mangled:
            return fd
    return None


def _first_concrete_value(param_type: str | None, nested_type: str | None, accepted: list):
    """
    Primer valor CONCRETO aceptable de un parametro (nunca el sentinel "" --
    ese solo marca "puede omitirse", no es un valor real a enviar). Para
    "dict" y "array de dict" el ground_truth trae PLANTILLAS (dict de clave
    -> lista de valores aceptables por clave, ver bfcl_ast_checker.
    dict_checker/list_dict_checker): hay que resolver un nivel mas para armar
    el valor final. El resto de los tipos ya trae el valor concreto directo.
    """
    if not accepted:
        return None
    non_empty = [v for v in accepted if v != ""] or accepted
    first = non_empty[0]
    if param_type == "dict" and isinstance(first, dict):
        return {k: v[0] for k, v in first.items()}
    if param_type in ("array", "tuple") and nested_type == "dict" and isinstance(first, list):
        return [{k: v[0] for k, v in tmpl.items()} for tmpl in first]
    return first


def ground_truth_to_calls(functions: list, ground_truth: list) -> str:
    """
    Arma la respuesta "perfecta" de un item: para cada entrada del
    ground_truth, una llamada Python con un valor aceptable de cada
    parametro que el checker EXIGE presente. Un parametro se incluye si (a)
    esta en el `required` del schema de la funcion (falta -> missing_required)
    O (b) su lista de valores aceptables NO incluye el sentinel "" (falta ->
    missing_optional: en BFCL "" en la lista es lo que marca que ESTE
    parametro puntual puede omitirse, mas alla de si el schema lo declara
    required o no). El resto se omite -- omitir un opcional real debe seguir
    dando PASS. Llamadas concatenadas con ';', igual que pide SYSTEM_PROMPT.
    """
    calls = []
    for entry in ground_truth:
        func_name = list(entry.keys())[0]
        params = entry[func_name]
        fd = _find_function_tolerant(functions, func_name)
        required = set(fd["parameters"]["required"]) if fd else set(params.keys())
        props = fd["parameters"]["properties"] if fd else {}
        args = {}
        for p, accepted in params.items():
            if p not in required and "" in accepted:
                continue  # opcional para esta instancia: omitir es PASS
            p_type = props.get(p, {}).get("type")
            nested_type = (props.get(p, {}).get("items", {}).get("type")
                          if p_type in ("array", "tuple") else None)
            args[p] = _first_concrete_value(p_type, nested_type, accepted)
        arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        calls.append(f"{func_name}({arg_str})")
    return "; ".join(calls)


# ---------------------------------------------------------------------------
# --check-only: self-test del oraculo, SIN modelo
# ---------------------------------------------------------------------------

def selftest_checker(slice_items: list) -> list[dict]:
    """
    Arma la respuesta ground-truth de cada item de la slice y corre
    check_response: cada uno DEBE dar PASS (si el port del checker esta
    bien). Reporta ademas prompt_len (build_prompt real, sin backend) para
    que el JSON tenga la misma forma que una corrida real.
    """
    items_cache = {c: load_category_items(c) for c in CATEGORIES}
    answers_cache = {c: load_category_answers(c) for c in CATEGORIES}

    results = []
    for entry in slice_items:
        category, item_id = entry["category"], entry["id"]
        item = items_cache[category][item_id]
        ground_truth = answers_cache[category][item_id]
        functions = item["function"]
        prompt = build_prompt(functions, question_text_of(item))
        response = ground_truth_to_calls(functions, ground_truth)
        passed, error_type, error_detail = check_response(
            category, functions, ground_truth, response)
        results.append({
            "id": item_id, "category": category, "prompt_len": len(prompt),
            "response": response, "passed": passed,
            "error_type": error_type, "error_detail": error_detail,
        })
    return results


def negative_cases() -> list[dict]:
    """
    3 casos FAIL hardcodeados sobre el item real 'simple_0' (categoria
    simple: calculate_triangle_area(base, height requeridos; unit opcional),
    ground truth base=[10], height=[5]) -- verifican que el oraculo
    efectivamente RECHAZA lo que debe rechazar, no solo que acepta lo
    correcto. Los 3 pedidos por la tarea: nombre de funcion equivocado,
    parametro requerido faltante, valor no aceptado.
    """
    items = load_category_items("simple")
    answers = load_category_answers("simple")
    item = items["simple_0"]
    functions = item["function"]
    ground_truth = answers["simple_0"]

    cases = [
        ("wrong_func_name", "bad_calculate_triangle_area(base=10, height=5)"),
        ("missing_required", "calculate_triangle_area(height=5)"),
        ("bad_value", "calculate_triangle_area(base=99, height=5)"),
    ]
    out = []
    for label, response in cases:
        passed, error_type, error_detail = check_response(
            "simple", functions, ground_truth, response)
        out.append({"case": label, "response": response, "passed": passed,
                    "error_type": error_type, "error_detail": error_detail})
    return out


SELFTEST_PASS_THRESHOLD = 0.95


def run_check_only(slice_items: list, label: str) -> tuple[dict, bool]:
    """Corre el self-test completo y devuelve (output_json, check_ok)."""
    self_results = selftest_checker(slice_items)
    neg_results = negative_cases()

    n = len(self_results)
    n_pass = sum(1 for r in self_results if r["passed"])
    accuracy = n_pass / n if n else 0.0
    by_cat = {}
    for cat in CATEGORIES:
        sub = [r for r in self_results if r["category"] == cat]
        if sub:
            by_cat[cat] = {"total": len(sub), "passed": sum(1 for r in sub if r["passed"])}

    all_negatives_ok = all(not nc["passed"] for nc in neg_results)
    check_ok = accuracy >= SELFTEST_PASS_THRESHOLD and all_negatives_ok

    output = {
        "label": label, "timestamp": datetime.datetime.now().isoformat(),
        "model": "none (--check-only: self-test del oraculo, sin backend)",
        "check_only": True, "n_items": n, "n_passed": n_pass,
        "accuracy": round(accuracy, 4), "by_category": by_cat,
        "results": self_results, "negative_cases": neg_results,
        "check_ok": check_ok,
    }
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    # 'checkonly_' en el nombre: un self-test del oraculo NUNCA debe poder
    # confundirse con un baseline real del modelo en el listado de results.
    out_path = EVAL_DIR / f"results_bfcl_checkonly_{label}_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 72)
    print(" BFCL-SLICE CHECK-ONLY (self-test del checker AST, sin modelo)")
    print("=" * 72)
    for cat, d in by_cat.items():
        status = "OK" if d["passed"] == d["total"] else "FAIL"
        print(f"   {cat:<20}: {d['passed']}/{d['total']}  [{status}]")
    print("-" * 72)
    print(f" self-test accuracy GLOBAL: {n_pass}/{n} = {accuracy:.1%}  "
          f"(umbral >= {SELFTEST_PASS_THRESHOLD:.0%})")
    failing = [r for r in self_results if not r["passed"]]
    if failing:
        print(f" FALLAS ({len(failing)}):")
        for r in failing[:20]:
            print(f"   {r['id']} ({r['category']}): {r['error_type']} -- "
                  f"{r['error_detail'][:100]}")
    print("-" * 72)
    print(" casos negativos (deben dar FAIL):")
    for nc in neg_results:
        tag = "FAIL (OK)" if not nc["passed"] else "PASS (MAL -- oraculo roto)"
        print(f"   {nc['case']:<20}: {tag}  {nc['error_type']}")
    print("-" * 72)
    print(f" JSON: {out_path}")
    print(f" CHECK: {'PASS' if check_ok else 'FAIL'}  "
          f"(self_test_ok={accuracy >= SELFTEST_PASS_THRESHOLD}, "
          f"negativos_ok={all_negatives_ok})")
    print("=" * 72)
    return output, check_ok


# ---------------------------------------------------------------------------
# Corrida real (--label sin --check-only): SI carga el modelo
# ---------------------------------------------------------------------------

def run_benchmark(slice_items: list, label: str = "baseline",
                  max_tokens: int = DEFAULT_MAX_TOKENS, seed: int = 42) -> dict:
    """Corre las items de la slice contra el modelo real y guarda JSON."""
    backend, gguf_name = make_backend()
    if backend is None:
        print("ERROR: no llama backend available (GGUF o llama-server faltante)")
        raise SystemExit(1)

    items_cache = {c: load_category_items(c) for c in CATEGORIES}
    answers_cache = {c: load_category_answers(c) for c in CATEGORIES}

    print(f"[bench_bfcl_slice] backend OK, model={gguf_name}, "
          f"items={len(slice_items)}, max_tokens={max_tokens}, seed={seed}", flush=True)

    results = []
    for i, entry in enumerate(slice_items, 1):
        category, item_id = entry["category"], entry["id"]
        item = items_cache[category][item_id]
        ground_truth = answers_cache[category][item_id]
        functions = item["function"]
        prompt = build_prompt(functions, question_text_of(item))
        print(f"[{i}/{len(slice_items)}] {item_id} ({category}) generating...", flush=True)
        t0 = time.perf_counter()
        # cache_prompt=False: mismo cuidado de reproducibilidad que benchmark_code.py
        response = backend.generate(prompt, max_tokens=max_tokens,
                                    temperature=BASE_TEMPERATURE, seed=seed,
                                    cache_prompt=False) or ""
        gen_s = time.perf_counter() - t0
        calls, _parse_err = parse_model_response(response)
        passed, error_type, error_detail = check_response(
            category, functions, ground_truth, response)
        status = "PASS" if passed else f"FAIL ({error_type})"
        print(f"    -> {status} {error_detail[:80]}", flush=True)
        results.append({
            "id": item_id, "category": category, "prompt_len": len(prompt),
            "response": response, "parsed_calls": calls, "passed": passed,
            "error_type": error_type, "error_detail": error_detail,
            "gen_seconds": round(gen_s, 2),
        })

    n = len(results)
    n_pass = sum(1 for r in results if r["passed"])
    accuracy = n_pass / n if n else 0.0
    by_cat = {}
    for cat in CATEGORIES:
        sub = [r for r in results if r["category"] == cat]
        if sub:
            by_cat[cat] = {"total": len(sub), "passed": sum(1 for r in sub if r["passed"])}

    output = {
        "label": label, "timestamp": datetime.datetime.now().isoformat(),
        "model": gguf_name, "max_tokens": max_tokens, "temperature": BASE_TEMPERATURE,
        "seed": seed, "n_items": n, "n_passed": n_pass, "accuracy": round(accuracy, 4),
        "by_category": by_cat, "results": results,
    }
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EVAL_DIR / f"results_bfcl_{label}_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 72)
    print(f" BFCL-SLICE BENCHMARK -- label={label} model={gguf_name}")
    print("=" * 72)
    for cat, d in by_cat.items():
        print(f"   {cat:<20}: {d['passed']}/{d['total']}")
    print("-" * 72)
    print(f" accuracy GLOBAL: {n_pass}/{n} = {accuracy:.1%}")
    print(f" JSON: {out_path}")
    print("=" * 72)
    return output


def build_arg_parser() -> argparse.ArgumentParser:
    """Parser CLI del harness (factorizado para testear el parseo sin correr)."""
    parser = argparse.ArgumentParser(
        description="Cognia BFCL-slice benchmark (tool-calling, checker AST)")
    parser.add_argument("--label", default="baseline", help="etiqueta para el JSON de salida")
    parser.add_argument("--limit", type=int, default=None,
                        help="correr solo los primeros N items de la slice "
                             "(orden: 40 simple, 40 multiple, 40 parallel, "
                             "40 parallel_multiple, 40 live_simple)")
    parser.add_argument("--seed", type=int, default=42,
                        help="seed de sampling del MODELO (backend.generate) -- "
                             "NO es el seed de la slice, que esta fijo en 42")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--check-only", action="store_true",
                        help="self-test del checker contra las ground-truth de "
                             "possible_answer -- NO carga el modelo")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    slice_items = build_slice()
    if args.limit:
        slice_items = slice_items[:args.limit]

    if args.check_only:
        _output, check_ok = run_check_only(slice_items, args.label)
        if not check_ok:
            raise SystemExit(1)
        return

    run_benchmark(slice_items, label=args.label, max_tokens=args.max_tokens, seed=args.seed)


if __name__ == "__main__":
    main()
