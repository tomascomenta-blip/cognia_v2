"""
AG-ARB (06_AGENTE_PLAN.md §5): experimento que FALSEA el arbitro del paper.

El paper del dueño (§4.2) afirma que un arbitro puede atribuir una falla al
modulo culpable en un pipeline heterogeneo. Aca se contrasta esa afirmacion
en el dominio agente con tres brazos, sobre casos con UNA falla inyectada en
etapa CONOCIDA (ground truth por construccion, estilo mutation testing):

  (i)   contratos: verificacion por etapa (cognia/agent/contracts.py),
        atribucion = primer contrato violado. CERO LLM, deterministica.
  (ii)  arbitro-LLM global: el 3B ve la SALIDA FINAL y juzga "que etapa fallo".
  (iii) arbitro-LLM con traza: el 3B ve las 4 etapas completas y juzga.

Pipeline modelado: plan -> design -> code -> test (etapas heterogeneas y no
sustituibles, analogo agente del LCD). Cada caso muta EXACTAMENTE una etapa.

Prediccion CONGELADA (plan §5, no se edita tras ver resultados):
  (i) >= 80% en etapas con oraculo ejecutable; (ii) <= 55% (Who&When midio
  53.5% con jueces FRONTIER — un 3B no deberia superarlos); (iii) entre (ii)
  y (i). Falsacion en ambas direcciones: si (ii) >= (i), el arbitro-LLM del
  paper revive; si (i) gana, el arbitro se re-especifica como cascada
  contratos-primero con LLM de fallback.

Cada caso se VERIFICA en build: el pipeline correcto no dispara ningun
contrato y el pipeline con falla produce una falla observable en la salida
final. Un caso que no cumple se descarta con aviso (no se maquilla el N).

Usage:
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_arbitro --check-only
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_arbitro --arm contracts
    venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_arbitro --arm all
"""
import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path

from cognia.agent.contracts import STAGES, attribute_failure

EVAL_DIR = Path(__file__).resolve().parent


# ── Casos base: (plan, design, code, tests) CORRECTOS + entry_point ─────
# Soluciones de referencia escritas a mano (simples, verificables). El
# 'plan' declara required_entities; el 'design' declara signatures; el
# 'code' es una solucion correcta; 'tests' son el oraculo-spec (fijo).

BASE_CASES = [
    {
        "id": "AC01", "entry_point": "count_vowels",
        "plan": {"text": "Contar vocales en un string s, case-insensitive.",
                 "required_entities": ["count_vowels"]},
        "design": {"text": "Funcion count_vowels que recorre s y cuenta vocales.",
                   "signatures": ["count_vowels(s)"]},
        "code": {"code": "def count_vowels(s):\n"
                         "    return sum(1 for c in s.lower() if c in 'aeiou')\n"},
        "tests": 'assert count_vowels("hello") == 2\n'
                 'assert count_vowels("AEIOU") == 5\n'
                 'assert count_vowels("xyz") == 0\n',
    },
    {
        "id": "AC02", "entry_point": "sum_digits",
        "plan": {"text": "Sumar los digitos decimales de un entero no negativo n.",
                 "required_entities": ["sum_digits"]},
        "design": {"text": "Funcion sum_digits sobre los digitos de n.",
                   "signatures": ["sum_digits(n)"]},
        "code": {"code": "def sum_digits(n):\n"
                         "    return sum(int(d) for d in str(n))\n"},
        "tests": 'assert sum_digits(123) == 6\n'
                 'assert sum_digits(0) == 0\n'
                 'assert sum_digits(99999) == 45\n',
    },
    {
        "id": "AC03", "entry_point": "is_palindrome",
        "plan": {"text": "Determinar si el string s es palindromo, case-sensitive.",
                 "required_entities": ["is_palindrome"]},
        "design": {"text": "Funcion is_palindrome que compara s con su reverso.",
                   "signatures": ["is_palindrome(s)"]},
        "code": {"code": "def is_palindrome(s):\n    return s == s[::-1]\n"},
        "tests": 'assert is_palindrome("racecar") == True\n'
                 'assert is_palindrome("hello") == False\n'
                 'assert is_palindrome("") == True\n',
    },
    {
        "id": "AC04", "entry_point": "factorial",
        "plan": {"text": "Factorial recursivo de n; factorial(0)=1.",
                 "required_entities": ["factorial"]},
        "design": {"text": "Funcion factorial recursiva sobre n.",
                   "signatures": ["factorial(n)"]},
        "code": {"code": "def factorial(n):\n"
                         "    return 1 if n <= 1 else n * factorial(n - 1)\n"},
        "tests": 'assert factorial(0) == 1\n'
                 'assert factorial(5) == 120\n'
                 'assert factorial(10) == 3628800\n',
    },
    {
        "id": "AC05", "entry_point": "reverse_words",
        "plan": {"text": "Invertir el orden de las palabras de s (separadas por espacio).",
                 "required_entities": ["reverse_words"]},
        "design": {"text": "Funcion reverse_words que separa s en palabras y las invierte.",
                   "signatures": ["reverse_words(s)"]},
        "code": {"code": "def reverse_words(s):\n"
                         "    return ' '.join(s.split()[::-1])\n"},
        "tests": 'assert reverse_words("hello world") == "world hello"\n'
                 'assert reverse_words("a b c") == "c b a"\n'
                 'assert reverse_words("single") == "single"\n',
    },
    {
        "id": "AC06", "entry_point": "fizzbuzz",
        "plan": {"text": "Lista fizzbuzz de 1 a n: Fizz mult 3, Buzz mult 5, FizzBuzz ambos.",
                 "required_entities": ["fizzbuzz"]},
        "design": {"text": "Funcion fizzbuzz que arma la lista de 1 a n.",
                   "signatures": ["fizzbuzz(n)"]},
        "code": {"code": "def fizzbuzz(n):\n"
                         "    out = []\n"
                         "    for i in range(1, n + 1):\n"
                         "        if i % 15 == 0: out.append('FizzBuzz')\n"
                         "        elif i % 3 == 0: out.append('Fizz')\n"
                         "        elif i % 5 == 0: out.append('Buzz')\n"
                         "        else: out.append(str(i))\n"
                         "    return out\n"},
        "tests": 'assert fizzbuzz(5) == ["1", "2", "Fizz", "4", "Buzz"]\n'
                 'assert fizzbuzz(15)[14] == "FizzBuzz"\n'
                 'assert fizzbuzz(0) == []\n',
    },
    {
        "id": "AC07", "entry_point": "binary_search",
        "plan": {"text": "Busqueda binaria de target en lista ordenada lst; -1 si no esta.",
                 "required_entities": ["binary_search"]},
        "design": {"text": "Funcion binary_search con dos punteros sobre lst.",
                   "signatures": ["binary_search(lst, target)"]},
        "code": {"code": "def binary_search(lst, target):\n"
                         "    lo, hi = 0, len(lst) - 1\n"
                         "    while lo <= hi:\n"
                         "        mid = (lo + hi) // 2\n"
                         "        if lst[mid] == target: return mid\n"
                         "        if lst[mid] < target: lo = mid + 1\n"
                         "        else: hi = mid - 1\n"
                         "    return -1\n"},
        "tests": 'assert binary_search([1, 3, 5, 7, 9], 5) == 2\n'
                 'assert binary_search([1, 3, 5, 7, 9], 4) == -1\n'
                 'assert binary_search([], 1) == -1\n',
    },
    {
        "id": "AC08", "entry_point": "second_largest",
        "plan": {"text": "Segundo valor distinto mas grande de lst; None si <2 distintos.",
                 "required_entities": ["second_largest"]},
        "design": {"text": "Funcion second_largest sobre los valores distintos de lst.",
                   "signatures": ["second_largest(lst)"]},
        "code": {"code": "def second_largest(lst):\n"
                         "    u = sorted(set(lst), reverse=True)\n"
                         "    return u[1] if len(u) >= 2 else None\n"},
        "tests": 'assert second_largest([1, 2, 3]) == 2\n'
                 'assert second_largest([5, 5, 4]) == 4\n'
                 'assert second_largest([7]) == None\n',
    },
]


# ── Inyeccion de fallas seeded (una etapa por caso) ─────────────────────
# Cada mutador toma el caso CORRECTO y devuelve el pipeline con la falla en
# una etapa. La etapa mutada es el ground truth de culpa.

def _mut_plan(case):
    """Falla en plan: el plan omite el requisito central y el downstream lo
    sigue fielmente -> el codigo queda como un STUB que ignora la tarea
    (preservando la firma). Los tests (spec independiente) lo exigen ->
    falla observable al final. Caso PROPAGADO: la raiz esta en plan pero se
    manifiesta en test — el trap del paper (§4.2). El oraculo code->test
    la caza pero atribuye a 'code', no a la raiz 'plan': eso es lo que el
    experimento mide, no lo que asume."""
    p = dict(case["plan"])
    p = {**p, "text": p["text"] + " (el plan OMITE el requisito central)"}
    def_line = case["code"]["code"].split("\n", 1)[0]     # 'def foo(args):'
    stub = def_line + "\n    return None\n"
    return {"plan": p, "design": case["design"],
            "code": {"code": stub}, "test": _test_stage(case)}


def _mut_design(case):
    """Falla en design: declara una firma con aridad INCOMPATIBLE con el
    codigo correcto. Oracle design->code la caza."""
    sig = case["design"]["signatures"][0]
    name = re.match(r"(\w+)", sig).group(1)
    bad = f"{name}(a, b, c, extra_param)"     # aridad inflada a proposito
    return {"plan": case["plan"],
            "design": {**case["design"], "signatures": [bad]},
            "code": case["code"], "test": _test_stage(case)}


def _mut_code(case):
    """Falla en code: bug logico que rompe los tests. Se prueban mutaciones
    candidatas y se ELIGE la primera que de verdad rompe el output (verificado
    aca mismo) — asi cada caso tiene su fault de codigo garantizado."""
    src = case["code"]["code"]
    candidates = (
        ("aeiou", "aeio"), ("str(n)", "str(n)[:-1]"), ("s[::-1]", "s"),
        ("n * factorial", "factorial"), ("split()[::-1]", "split()"),
        ("% 15", "% 30"), ("== target: return mid", "== target: return -1"),
        ("reverse=True", "reverse=False"),
    )
    for a, b in candidates:
        if a not in src:
            continue
        mutated = {"plan": case["plan"], "design": case["design"],
                   "code": {"code": src.replace(a, b, 1)},
                   "test": _test_stage(case)}
        if _final_output_fails(mutated):
            return mutated
    return None


def _mut_test(case):
    """Falla en test: un assert con valor esperado EQUIVOCADO. El codigo es
    correcto pero 'falla' el test malo. Caso donde el oraculo code->test
    NO puede distinguir code-malo de test-malo sin un 2do oraculo."""
    tests = case["tests"]
    lines = tests.strip().split("\n")
    first = lines[0]
    m = re.search(r"==\s*(.+)$", first)
    if not m:
        return None
    # corromper el valor esperado sumandole un sufijo/numero imposible
    corrupted = first[:m.start(1)] + "999999"
    lines[0] = corrupted
    return {"plan": case["plan"], "design": case["design"],
            "code": case["code"],
            "test": {**_test_stage(case), "tests": "\n".join(lines) + "\n"}}


def _test_stage(case):
    return {"tests": case["tests"], "entry_point": case["entry_point"]}


MUTATORS = {"plan": _mut_plan, "design": _mut_design,
            "code": _mut_code, "test": _mut_test}


def build_correct_pipeline(case):
    """Pipeline sin fallas (para el self-test de los contratos)."""
    return {"plan": case["plan"], "design": case["design"],
            "code": case["code"], "test": _test_stage(case)}


def build_faulted_cases():
    """Todos los (caso, etapa) validos: se muta cada etapa de cada caso y se
    VERIFICA en build (correcto no dispara contratos; faulted falla al final).
    Devuelve (cases_ok, descartados)."""
    cases_ok, discarded = [], []
    for case in BASE_CASES:
        # 1) el pipeline correcto no debe disparar ningun contrato
        clean = attribute_failure(build_correct_pipeline(case))
        if clean["stage"] is not None:
            discarded.append((case["id"], "clean", clean["reason"]))
            continue
        for stage in STAGES:
            mut = MUTATORS[stage](case)
            if mut is None:
                discarded.append((case["id"], stage, "sin mutacion aplicable"))
                continue
            # 2) el pipeline con falla debe producir falla observable al final
            #    (el contrato code->test debe fallar, salvo el de design que
            #    se caza antes en design->code).
            observable = _final_output_fails(mut)
            if stage != "design" and not observable:
                discarded.append((case["id"], stage,
                                  "la falla inyectada no rompe el output final"))
                continue
            cases_ok.append({"id": f"{case['id']}_{stage}", "base": case["id"],
                             "ground_truth": stage, "pipeline": mut,
                             "entry_point": case["entry_point"]})
    return cases_ok, discarded


def _final_output_fails(pipeline):
    """True si el codigo del pipeline NO pasa los tests de la etapa test
    (falla observable en la salida final)."""
    from cognia_v3.eval.benchmark_code import run_task_tests
    t = pipeline["test"]
    passed, _, _ = run_task_tests(pipeline["code"].get("code", ""),
                                  t.get("tests", ""), t.get("entry_point", ""))
    return not passed


# ── Brazo (i): contratos ────────────────────────────────────────────────

def arm_contracts(case):
    """Atribucion por contratos (deterministica). Devuelve la etapa culpable."""
    return attribute_failure(case["pipeline"])["stage"]


# ── Brazos (ii)/(iii): arbitro-LLM ──────────────────────────────────────

ARBITER_SYSTEM = ("Sos un arbitro que diagnostica pipelines de software. El "
                  "pipeline tiene 4 etapas: plan, design, code, test. Una "
                  "etapa introdujo un error. Responde SOLO el nombre de la "
                  "etapa culpable: plan, design, code o test.")


def _arbiter_prompt(case, with_trace):
    p = case["pipeline"]
    t = p["test"]
    parts = ["El pipeline produjo una salida final INCORRECTA (los tests fallan)."]
    if with_trace:
        parts += [
            "\n[PLAN]\n" + p["plan"].get("text", ""),
            "requeridos: " + ", ".join(p["plan"].get("required_entities", [])),
            "\n[DESIGN]\n" + p["design"].get("text", ""),
            "firmas: " + ", ".join(p["design"].get("signatures", [])),
            "\n[CODE]\n" + p["code"].get("code", ""),
            "\n[TEST]\n" + t.get("tests", ""),
        ]
    else:
        parts += ["\n[CODE FINAL]\n" + p["code"].get("code", ""),
                  "\n[TESTS QUE FALLAN]\n" + t.get("tests", "")]
    parts.append("\n¿Que etapa (plan/design/code/test) introdujo el error? "
                 "Responde SOLO la palabra.")
    return "\n".join(parts)


_STAGE_RX = re.compile(r"\b(plan|design|code|test)\b", re.IGNORECASE)


def arm_arbiter(case, backend, with_trace, max_tokens=32, seed=42):
    """Atribucion por el 3B. Devuelve (etapa|None, respuesta_cruda)."""
    from node.inference_pipeline import _apply_qwen_template
    prompt = _apply_qwen_template(_arbiter_prompt(case, with_trace),
                                  system=ARBITER_SYSTEM)
    resp = backend.generate(prompt, max_tokens=max_tokens, temperature=0.0,
                            seed=seed, cache_prompt=False) or ""
    # primera etapa nombrada en la respuesta
    m = _STAGE_RX.search(resp)
    return (m.group(1).lower() if m else None), resp.strip()[:200]


# ── Runner ──────────────────────────────────────────────────────────────

def run(arms, label, seed=42):
    cases, discarded = build_faulted_cases()
    print(f"[bench_arbitro] {len(cases)} casos validos "
          f"({len(discarded)} descartados)", flush=True)
    by_stage_total = {}
    for c in cases:
        by_stage_total[c["ground_truth"]] = by_stage_total.get(c["ground_truth"], 0) + 1

    backend = None
    if any(a in arms for a in ("arbiter_global", "arbiter_trace", "all")):
        from cognia_v3.eval.benchmark_code import make_backend
        backend, _ = make_backend()

    results = {"contracts": [], "arbiter_global": [], "arbiter_trace": []}

    def _run_arm(arm_name):
        correct = 0
        per_stage = {}
        for c in cases:
            gt = c["ground_truth"]
            if arm_name == "contracts":
                pred = arm_contracts(c)
                raw = ""
            elif arm_name == "arbiter_global":
                pred, raw = arm_arbiter(c, backend, with_trace=False, seed=seed)
            else:
                pred, raw = arm_arbiter(c, backend, with_trace=True, seed=seed)
            ok = (pred == gt)
            correct += ok
            per_stage.setdefault(gt, [0, 0])
            per_stage[gt][0] += ok
            per_stage[gt][1] += 1
            results[arm_name].append({"id": c["id"], "ground_truth": gt,
                                      "pred": pred, "correct": ok, "raw": raw})
        acc = correct / len(cases) if cases else 0.0
        print(f"  [{arm_name}] accuracy {correct}/{len(cases)} = {acc:.1%}", flush=True)
        for st in STAGES:
            if st in per_stage:
                o, n = per_stage[st]
                print(f"      {st:<8}: {o}/{n}", flush=True)
        return {"accuracy": round(acc, 4), "correct": correct,
                "n": len(cases),
                "per_stage": {k: {"correct": v[0], "total": v[1]}
                              for k, v in per_stage.items()}}

    summary = {}
    if "contracts" in arms or "all" in arms:
        summary["contracts"] = _run_arm("contracts")
    if "arbiter_global" in arms or "all" in arms:
        summary["arbiter_global"] = _run_arm("arbiter_global")
    if "arbiter_trace" in arms or "all" in arms:
        summary["arbiter_trace"] = _run_arm("arbiter_trace")

    output = {
        "label": label, "timestamp": datetime.datetime.now().isoformat(),
        "n_cases": len(cases), "by_stage_total": by_stage_total,
        "discarded": discarded, "seed": seed,
        "prediction_frozen": {"contracts": ">=0.80", "arbiter_global": "<=0.55",
                              "arbiter_trace": "entre ambos"},
        "summary": summary, "details": results,
    }
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EVAL_DIR / f"results_arbitro_{label}_{ts}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"[bench_arbitro] JSON: {out_path.name}", flush=True)
    return output


def main():
    ap = argparse.ArgumentParser(description="AG-ARB: falsacion del arbitro (plan §5)")
    ap.add_argument("--arm", default="contracts",
                    choices=["contracts", "arbiter_global", "arbiter_trace", "all"])
    ap.add_argument("--check-only", action="store_true",
                    help="solo construir/verificar los casos (sin correr brazos)")
    ap.add_argument("--label", default="argb")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.check_only:
        cases, discarded = build_faulted_cases()
        by_stage = {}
        for c in cases:
            by_stage[c["ground_truth"]] = by_stage.get(c["ground_truth"], 0) + 1
        print(f"[check-only] {len(cases)} casos validos, por etapa: {by_stage}")
        if discarded:
            print(f"[check-only] {len(discarded)} descartados:")
            for cid, stage, reason in discarded:
                print(f"    {cid}/{stage}: {reason}")
        # los contratos deben clasificar el pipeline CORRECTO como sin-falla
        clean_ok = all(attribute_failure(build_correct_pipeline(c))["stage"] is None
                       for c in BASE_CASES)
        print(f"[check-only] pipelines correctos sin falla: {clean_ok}")
        sys.exit(0 if cases and clean_ok else 1)

    run([args.arm], args.label, seed=args.seed)


if __name__ == "__main__":
    main()
