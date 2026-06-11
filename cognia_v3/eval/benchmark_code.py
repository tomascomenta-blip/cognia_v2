"""
Cognia code-quality benchmark: pass@1 con ejecucion REAL, 100% local.

Cada task pide una funcion Python concreta; la respuesta del modelo se extrae,
se ejecuta en un subprocess aislado junto a los asserts de la task, y exit
code 0 = PASS. Es la metrica troncal para medir mejora de programacion
(antes/despues de QLoRA, cambios de prompt, etc.).

Usage:
    venv312\\Scripts\\python.exe -m cognia_v3.eval.benchmark_code --limit 3 --label smoke
    venv312\\Scripts\\python.exe -m cognia_v3.eval.benchmark_code --label baseline

Backend: node/llama_backend.py LlamaBackend.try_load() (llama-server arranca solo).
Prompt: ChatML via node/inference_pipeline._apply_qwen_template.
Ejecucion: subprocess directo (cognia_v3/interfaces/code_executor.run_python NO
encaja: exige stdout no vacio para success, y los tests con asserts no imprimen).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent

SYSTEM_PROMPT = ("You are an expert Python programmer. Reply with ONLY a Python "
                 "code block containing the complete function. No explanations.")

DEFAULT_MAX_TOKENS = 768
EXEC_TIMEOUT_S = 10

# Gramatica GBNF (llama-server /completion, campo "grammar"): fuerza el output
# a ser EXACTAMENTE un bloque markdown ```python ... ``` (newline final
# opcional), sin prosa antes ni despues. body admite cualquier caracter pero
# nunca tres backticks seguidos: un ``` dentro de un string del codigo
# generado corta el bloque — mismo comportamiento que extract_code, aceptable.
GRAMMAR_PYTHON_BLOCK = r'''root ::= "```python\n" body "```" "\n"?
body ::= ( [^`] | "`" [^`] | "``" [^`] )*
'''
# Temperatura de la generacion base: greedy para que pass@1 sea reproducible.
# Es la MISMA constante que se persiste en el JSON (antes habia un hardcode
# duplicado en el output que podia desalinearse del valor real usado).
BASE_TEMPERATURE = 0.0

# ── Tasks embebidas (estilo MBPP, escritas a mano, solo stdlib, sin I/O) ──────
# Cada task: id, difficulty, prompt, entry_point, tests (3-5 asserts).
# 10 faciles / 10 medias / 5 dificiles. Incluye 2 bug-fix (M10, H05).

TASKS = [
    # ---------- FACILES ----------
    {"id": "E01", "difficulty": "easy", "entry_point": "count_vowels",
     "prompt": "Write a Python function `count_vowels(s)` that returns the number of vowels (a, e, i, o, u, case-insensitive) in the string s.",
     "tests": 'assert count_vowels("hello") == 2\n'
              'assert count_vowels("AEIOU") == 5\n'
              'assert count_vowels("xyz") == 0\n'
              'assert count_vowels("") == 0\n'
              'assert count_vowels("Programming") == 3\n'},
    {"id": "E02", "difficulty": "easy", "entry_point": "sum_digits",
     "prompt": "Write a Python function `sum_digits(n)` that returns the sum of the decimal digits of a non-negative integer n.",
     "tests": 'assert sum_digits(0) == 0\n'
              'assert sum_digits(5) == 5\n'
              'assert sum_digits(123) == 6\n'
              'assert sum_digits(99999) == 45\n'},
    {"id": "E03", "difficulty": "easy", "entry_point": "is_palindrome",
     "prompt": "Write a Python function `is_palindrome(s)` that returns True if the string s reads the same forwards and backwards (exact characters, case-sensitive), False otherwise.",
     "tests": 'assert is_palindrome("racecar") == True\n'
              'assert is_palindrome("hello") == False\n'
              'assert is_palindrome("") == True\n'
              'assert is_palindrome("ab") == False\n'
              'assert is_palindrome("Aa") == False\n'},
    {"id": "E04", "difficulty": "easy", "entry_point": "factorial",
     "prompt": "Write a recursive Python function `factorial(n)` that returns n! for a non-negative integer n. factorial(0) must return 1.",
     "tests": 'assert factorial(0) == 1\n'
              'assert factorial(1) == 1\n'
              'assert factorial(5) == 120\n'
              'assert factorial(10) == 3628800\n'},
    {"id": "E05", "difficulty": "easy", "entry_point": "reverse_words",
     "prompt": "Write a Python function `reverse_words(s)` that returns the string s with the order of its words reversed. Words are separated by single spaces.",
     "tests": 'assert reverse_words("hello world") == "world hello"\n'
              'assert reverse_words("a b c") == "c b a"\n'
              'assert reverse_words("single") == "single"\n'
              'assert reverse_words("the quick brown fox") == "fox brown quick the"\n'},
    {"id": "E06", "difficulty": "easy", "entry_point": "remove_duplicates",
     "prompt": "Write a Python function `remove_duplicates(lst)` that returns a new list with duplicate elements removed, preserving the order of first appearance.",
     "tests": 'assert remove_duplicates([1, 2, 2, 3, 1]) == [1, 2, 3]\n'
              'assert remove_duplicates([]) == []\n'
              'assert remove_duplicates(["a", "b", "a"]) == ["a", "b"]\n'
              'assert remove_duplicates([5, 5, 5, 5]) == [5]\n'},
    {"id": "E07", "difficulty": "easy", "entry_point": "merge_dicts",
     "prompt": "Write a Python function `merge_dicts(d1, d2)` that returns a new dict with all keys from d1 and d2. If a key is in both, the value from d2 wins. Do not modify the input dicts.",
     "tests": 'assert merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}\n'
              'assert merge_dicts({"a": 1}, {"a": 9}) == {"a": 9}\n'
              'assert merge_dicts({}, {}) == {}\n'
              'd1 = {"x": 1}\n'
              'merge_dicts(d1, {"x": 2})\n'
              'assert d1 == {"x": 1}\n'},
    {"id": "E08", "difficulty": "easy", "entry_point": "fizzbuzz",
     "prompt": 'Write a Python function `fizzbuzz(n)` that returns a list of strings for the numbers 1 to n: "Fizz" for multiples of 3, "Buzz" for multiples of 5, "FizzBuzz" for multiples of both, and the number itself as a string otherwise.',
     "tests": 'assert fizzbuzz(1) == ["1"]\n'
              'assert fizzbuzz(3) == ["1", "2", "Fizz"]\n'
              'assert fizzbuzz(5) == ["1", "2", "Fizz", "4", "Buzz"]\n'
              'assert fizzbuzz(15)[14] == "FizzBuzz"\n'
              'assert fizzbuzz(0) == []\n'},
    {"id": "E09", "difficulty": "easy", "entry_point": "find_min_max",
     "prompt": "Write a Python function `find_min_max(lst)` that returns a tuple (minimum, maximum) of a non-empty list of numbers.",
     "tests": 'assert find_min_max([3, 1, 2]) == (1, 3)\n'
              'assert find_min_max([7]) == (7, 7)\n'
              'assert find_min_max([-5, 0, 5]) == (-5, 5)\n'
              'assert find_min_max([2, 2, 2]) == (2, 2)\n'},
    {"id": "E10", "difficulty": "easy", "entry_point": "capitalize_words",
     "prompt": 'Write a Python function `capitalize_words(s)` that returns the string s with the first letter of each word uppercased and the rest of each word lowercased. Words are separated by single spaces. Example: "PYTHON is FUN" -> "Python Is Fun".',
     "tests": 'assert capitalize_words("hello world") == "Hello World"\n'
              'assert capitalize_words("PYTHON is FUN") == "Python Is Fun"\n'
              'assert capitalize_words("a") == "A"\n'
              'assert capitalize_words("") == ""\n'},

    # ---------- MEDIAS ----------
    {"id": "M01", "difficulty": "medium", "entry_point": "fibonacci",
     "prompt": "Write a Python function `fibonacci(n)` that returns the n-th Fibonacci number, with fibonacci(0) == 0 and fibonacci(1) == 1. It must be efficient enough for n up to 100 (do not use naive exponential recursion).",
     "tests": 'assert fibonacci(0) == 0\n'
              'assert fibonacci(1) == 1\n'
              'assert fibonacci(10) == 55\n'
              'assert fibonacci(30) == 832040\n'
              'assert fibonacci(100) == 354224848179261915075\n'},
    {"id": "M02", "difficulty": "medium", "entry_point": "flatten",
     "prompt": "Write a Python function `flatten(nested)` that takes a list which may contain other lists nested to any depth, and returns a single flat list with all the non-list elements in their original order.",
     "tests": 'assert flatten([1, [2, 3], [4, [5, 6]]]) == [1, 2, 3, 4, 5, 6]\n'
              'assert flatten([]) == []\n'
              'assert flatten([[[[1]]]]) == [1]\n'
              'assert flatten([1, 2, 3]) == [1, 2, 3]\n'
              'assert flatten([[], [1], []]) == [1]\n'},
    {"id": "M03", "difficulty": "medium", "entry_point": "char_frequency",
     "prompt": "Write a Python function `char_frequency(s)` that returns a dict mapping each character in the string s to the number of times it appears.",
     "tests": 'assert char_frequency("aab") == {"a": 2, "b": 1}\n'
              'assert char_frequency("") == {}\n'
              'assert char_frequency("abc") == {"a": 1, "b": 1, "c": 1}\n'
              'assert char_frequency("aaa") == {"a": 3}\n'},
    {"id": "M04", "difficulty": "medium", "entry_point": "is_balanced",
     "prompt": "Write a Python function `is_balanced(s)` that returns True if every bracket in the string s is correctly matched and nested, False otherwise. Brackets are (), [] and {}. Other characters may appear and must be ignored.",
     "tests": 'assert is_balanced("()") == True\n'
              'assert is_balanced("([{}])") == True\n'
              'assert is_balanced("(]") == False\n'
              'assert is_balanced(")(") == False\n'
              'assert is_balanced("a(b)c[d]") == True\n'},
    {"id": "M05", "difficulty": "medium", "entry_point": "binary_search",
     "prompt": "Write a Python function `binary_search(lst, target)` that performs binary search on a sorted list lst and returns the index of target, or -1 if target is not present.",
     "tests": 'assert binary_search([1, 3, 5, 7, 9], 5) == 2\n'
              'assert binary_search([1, 3, 5, 7, 9], 1) == 0\n'
              'assert binary_search([1, 3, 5, 7, 9], 9) == 4\n'
              'assert binary_search([1, 3, 5, 7, 9], 4) == -1\n'
              'assert binary_search([], 1) == -1\n'},
    {"id": "M06", "difficulty": "medium", "entry_point": "extract_emails",
     "prompt": "Write a Python function `extract_emails(text)` that uses a regular expression to return a list of all email addresses found in text, in order of appearance. The local part may contain letters, digits, dots, underscores, plus signs and hyphens; the domain may have multiple dot-separated parts, e.g. user.name+tag@example.co.uk.",
     "tests": 'assert extract_emails("contact bob@test.com now") == ["bob@test.com"]\n'
              'assert extract_emails("a@b.com and c.d@e.org") == ["a@b.com", "c.d@e.org"]\n'
              'assert extract_emails("no emails here") == []\n'
              'assert extract_emails("x user.name+tag@example.co.uk y") == ["user.name+tag@example.co.uk"]\n'},
    {"id": "M07", "difficulty": "medium", "entry_point": "longest_common_prefix",
     "prompt": "Write a Python function `longest_common_prefix(strs)` that returns the longest common prefix of a list of strings. Return an empty string if there is no common prefix or the list is empty.",
     "tests": 'assert longest_common_prefix(["flower", "flow", "flight"]) == "fl"\n'
              'assert longest_common_prefix(["dog", "racecar", "car"]) == ""\n'
              'assert longest_common_prefix(["same", "same"]) == "same"\n'
              'assert longest_common_prefix([]) == ""\n'
              'assert longest_common_prefix(["alone"]) == "alone"\n'},
    {"id": "M08", "difficulty": "medium", "entry_point": "parse_query_string",
     "prompt": 'Write a Python function `parse_query_string(qs)` that parses a URL query string like "a=1&b=hello" into a dict mapping each key to its string value. An empty input string returns an empty dict. Assume keys are unique and every pair has the form key=value.',
     "tests": 'assert parse_query_string("a=1&b=hello") == {"a": "1", "b": "hello"}\n'
              'assert parse_query_string("") == {}\n'
              'assert parse_query_string("x=42") == {"x": "42"}\n'
              'assert parse_query_string("k=v&k2=v2&k3=v3") == {"k": "v", "k2": "v2", "k3": "v3"}\n'},
    {"id": "M09", "difficulty": "medium", "entry_point": "second_largest",
     "prompt": "Write a Python function `second_largest(lst)` that returns the second largest distinct value in a list of numbers, or None if there are fewer than two distinct values.",
     "tests": 'assert second_largest([1, 2, 3]) == 2\n'
              'assert second_largest([5, 5, 4]) == 4\n'
              'assert second_largest([7]) == None\n'
              'assert second_largest([3, 3, 3]) == None\n'
              'assert second_largest([-1, -2, -3]) == -2\n'},
    {"id": "M10", "difficulty": "medium", "entry_point": "filter_even",
     "prompt": "Fix the bug in this Python function so that it returns only the even numbers from the input list, preserving order. Reply with the corrected function, keeping the name `filter_even`.\n\n"
               "```python\n"
               "def filter_even(numbers):\n"
               "    evens = []\n"
               "    for n in numbers:\n"
               "        if n % 2 == 1:\n"
               "            evens.append(n)\n"
               "    return evens\n"
               "```",
     "tests": 'assert filter_even([1, 2, 3, 4]) == [2, 4]\n'
              'assert filter_even([]) == []\n'
              'assert filter_even([1, 3, 5]) == []\n'
              'assert filter_even([2, 4, 6]) == [2, 4, 6]\n'
              'assert filter_even([0, -2, 7]) == [0, -2]\n'},

    # ---------- DIFICILES ----------
    {"id": "H01", "difficulty": "hard", "entry_point": "roman_to_int",
     "prompt": "Write a Python function `roman_to_int(s)` that converts a Roman numeral string (symbols I, V, X, L, C, D, M, including subtractive notation like IV=4 and IX=9) to an integer.",
     "tests": 'assert roman_to_int("III") == 3\n'
              'assert roman_to_int("IV") == 4\n'
              'assert roman_to_int("LVIII") == 58\n'
              'assert roman_to_int("MCMXCIV") == 1994\n'
              'assert roman_to_int("MMXXV") == 2025\n'},
    {"id": "H02", "difficulty": "hard", "entry_point": "spiral_order",
     "prompt": "Write a Python function `spiral_order(matrix)` that returns all elements of a 2D matrix (list of lists) in clockwise spiral order, starting from the top-left element. Return an empty list for an empty matrix.",
     "tests": 'assert spiral_order([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 2, 3, 6, 9, 8, 7, 4, 5]\n'
              'assert spiral_order([[1, 2], [3, 4]]) == [1, 2, 4, 3]\n'
              'assert spiral_order([[1, 2, 3]]) == [1, 2, 3]\n'
              'assert spiral_order([[1], [2], [3]]) == [1, 2, 3]\n'
              'assert spiral_order([]) == []\n'},
    {"id": "H03", "difficulty": "hard", "entry_point": "validate_ipv4",
     "prompt": 'Write a Python function `validate_ipv4(s)` that returns True only if s is a valid IPv4 address in dotted-decimal notation: exactly four parts separated by dots, each part a decimal number from 0 to 255 with no leading zeros ("0" itself is valid), and no extra characters or spaces. Return False otherwise.',
     "tests": 'assert validate_ipv4("192.168.1.1") == True\n'
              'assert validate_ipv4("255.255.255.255") == True\n'
              'assert validate_ipv4("256.1.1.1") == False\n'
              'assert validate_ipv4("01.2.3.4") == False\n'
              'assert validate_ipv4("1.2.3") == False\n'},
    {"id": "H04", "difficulty": "hard", "entry_point": "lis_length",
     "prompt": "Write a Python function `lis_length(lst)` that returns the length of the longest strictly increasing subsequence of a list of integers (elements keep their relative order but need not be contiguous). Return 0 for an empty list.",
     "tests": 'assert lis_length([10, 9, 2, 5, 3, 7, 101, 18]) == 4\n'
              'assert lis_length([0, 1, 0, 3, 2, 3]) == 4\n'
              'assert lis_length([7, 7, 7, 7]) == 1\n'
              'assert lis_length([]) == 0\n'
              'assert lis_length([1, 2, 3, 4]) == 4\n'},
    {"id": "H05", "difficulty": "hard", "entry_point": "merge_sorted",
     "prompt": "Fix the bug in this Python function. It is supposed to merge two already-sorted lists into one sorted list, but it loses elements. Reply with the corrected function, keeping the name `merge_sorted`.\n\n"
               "```python\n"
               "def merge_sorted(a, b):\n"
               "    result = []\n"
               "    i = j = 0\n"
               "    while i < len(a) and j < len(b):\n"
               "        if a[i] <= b[j]:\n"
               "            result.append(a[i])\n"
               "            i += 1\n"
               "        else:\n"
               "            result.append(b[j])\n"
               "            j += 1\n"
               "    return result\n"
               "```",
     "tests": 'assert merge_sorted([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]\n'
              'assert merge_sorted([1, 2], [3, 4, 5]) == [1, 2, 3, 4, 5]\n'
              'assert merge_sorted([], [1, 2]) == [1, 2]\n'
              'assert merge_sorted([1, 1], [1]) == [1, 1, 1]\n'
              'assert merge_sorted([5], []) == [5]\n'},
]

_CODE_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(response: str) -> str:
    """Primer bloque ```python ...``` de la respuesta; fallback: respuesta entera."""
    if not response:
        return ""
    m = _CODE_FENCE_RE.search(response)
    if m:
        return m.group(1).strip()
    # Fence abierto sin cerrar (corte por max_tokens): tomar lo que sigue al fence
    open_fence = re.search(r"```(?:python|py)?\s*\n", response)
    if open_fence:
        return response[open_fence.end():].strip()
    return response.strip()


def _sandbox_env() -> dict:
    """Env minimo para el subprocess (Windows necesita SystemRoot)."""
    env = {"PYTHONPATH": "", "PYTHONIOENCODING": "utf-8",
           "TERM": "dumb", "HOME": tempfile.gettempdir()}
    for key in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_task_tests(code: str, tests: str, entry_point: str) -> tuple[bool, str, str]:
    """
    Ejecuta codigo + tests en subprocess aislado con timeout.
    Devuelve (passed, error_type, stderr_corto).
    error_type: "" | "empty" | "missing_func" | "syntax" | "assert" | "timeout" | "runtime"
    """
    if not code.strip():
        return False, "empty", "no code extracted"
    if f"def {entry_point}" not in code:
        return False, "missing_func", f"no 'def {entry_point}' in generated code"

    script = code + "\n\n" + tests + "\n"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="cognia_bench_",
            delete=False, encoding="utf-8",
        ) as f:
            tmp_path = f.name
            f.write(script)
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=EXEC_TIMEOUT_S, env=_sandbox_env(),
        )
        if proc.returncode == 0:
            return True, "", ""
        stderr = (proc.stderr or "").strip()
        last_line = stderr.splitlines()[-1] if stderr else f"exit={proc.returncode}"
        if "SyntaxError" in stderr or "IndentationError" in stderr:
            return False, "syntax", last_line
        if "AssertionError" in stderr:
            # Incluir la linea del assert que fallo si esta en el traceback
            assert_line = next((ln.strip() for ln in stderr.splitlines()
                                if ln.strip().startswith("assert")), last_line)
            return False, "assert", assert_line
        return False, "runtime", last_line
    except subprocess.TimeoutExpired:
        return False, "timeout", f"timeout after {EXEC_TIMEOUT_S}s"
    except Exception as exc:
        return False, "runtime", f"sandbox error: {exc}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def make_backend():
    """Carga LlamaBackend (arranca llama-server solo). Devuelve (backend, gguf_name)."""
    from node.llama_backend import LlamaBackend, _find_gguf
    backend = LlamaBackend.try_load()
    gguf = _find_gguf()
    return backend, (gguf.name if gguf else "unknown")


def build_prompt(task_prompt: str) -> str:
    from node.inference_pipeline import _apply_qwen_template
    return _apply_qwen_template(task_prompt, system=SYSTEM_PROMPT)


def build_repair_prompt(task_prompt: str, code: str, err_type: str,
                        err_detail: str) -> str:
    """Prompt de reparacion: tarea original + codigo fallido + error real."""
    msg = (task_prompt
           + "\n\nYour previous solution was:\n```python\n" + code + "\n```\n\n"
           + "It FAILED when executed. Error type: " + err_type
           + "\nError detail: " + err_detail[-300:]
           + "\n\nReply with ONLY the corrected complete function in a "
             "python code block. No explanations.")
    return build_prompt(msg)


def repair_failures(backend, tasks: list[dict], results: list[dict],
                    repair_rounds: int, max_tokens: int,
                    repair_temperature: float = 0.5,
                    seed: int = None, grammar: str = None) -> dict:
    """
    Para cada task FAIL: regenerar con el error de ejecucion real, hasta
    repair_rounds rondas o PASS. Muta results (passed_final, repair_attempts)
    y devuelve stats agregadas {tokens, seconds, recovered}.
    """
    task_by_id = {t["id"]: t for t in tasks}
    total_tokens = 0
    total_seconds = 0.0
    recovered = 0
    for r in results:
        r["passed_final"] = r["passed"]
        r["repair_attempts"] = []
    for rnd in range(1, repair_rounds + 1):
        pending = [r for r in results if not r["passed_final"]]
        if not pending:
            break
        print(f"[repair] round {rnd}/{repair_rounds}: "
              f"{len(pending)} tasks failing", flush=True)
        for r in pending:
            task = task_by_id[r["id"]]
            # Ultimo codigo + error (de la ronda previa si ya hubo repair)
            if r["repair_attempts"]:
                last = r["repair_attempts"][-1]
                prev_code = last["extracted_code"]
                prev_err_type, prev_err_detail = last["error_type"], last["error_detail"]
            else:
                prev_code = r["extracted_code"]
                prev_err_type, prev_err_detail = r["error_type"], r["error_detail"]
            prompt = build_repair_prompt(task["prompt"], prev_code,
                                         prev_err_type, prev_err_detail)
            t0 = time.perf_counter()
            # cache_prompt=False: el KV-cache reusado cambia los logits
            # (experimento 2026-06-11) -- prefill completo para reproducibilidad
            response = backend.generate(prompt, max_tokens=max_tokens,
                                        temperature=repair_temperature,
                                        seed=seed, cache_prompt=False,
                                        grammar=grammar) or ""
            gen_s = time.perf_counter() - t0
            tokens = backend.last_tokens_predicted
            total_tokens += tokens or 0
            total_seconds += gen_s
            code = extract_code(response)
            passed, err_type, err_detail = run_task_tests(
                code, task["tests"], task["entry_point"])
            r["repair_attempts"].append({
                "round": rnd, "passed": passed,
                "error_type": err_type, "error_detail": err_detail[:300],
                "gen_seconds": round(gen_s, 2), "tokens_predicted": tokens,
                "response": response, "extracted_code": code,
            })
            if passed:
                r["passed_final"] = True
                recovered += 1
            status = "PASS" if passed else f"FAIL ({err_type})"
            print(f"    [repair r{rnd}] {r['id']} -> {status} "
                  f"{err_detail[:60]}", flush=True)
    return {"tokens": total_tokens, "seconds": total_seconds,
            "recovered": recovered}


def run_benchmark(tasks: list[dict], label: str = "baseline",
                  max_tokens: int = DEFAULT_MAX_TOKENS,
                  repair_rounds: int = 0,
                  repair_temperature: float = 0.5,
                  seed: int = None, use_grammar: bool = False) -> dict:
    """Corre todas las tasks contra el modelo real y guarda JSON con resultados."""
    # use_grammar: restringe el sampling a un bloque ```python ...``` exacto
    # (base y repair) — elimina prosa y fences rotos sin tocar el modelo.
    grammar = GRAMMAR_PYTHON_BLOCK if use_grammar else None
    backend, gguf_name = make_backend()
    if backend is None:
        print("ERROR: no llama backend available (GGUF or llama-server missing)")
        sys.exit(1)
    # Config real del server al inicio del run (None si el impl no expone /props):
    # se persiste en el JSON para que cada resultado declare contra QUE server corrio.
    server_props = None
    props_fn = getattr(backend, "server_props", None)
    if callable(props_fn):
        server_props = props_fn()
    print(f"[benchmark_code] backend OK, model={gguf_name}, "
          f"tasks={len(tasks)}, max_tokens={max_tokens}, seed={seed}, "
          f"grammar={use_grammar}", flush=True)

    results = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task['id']} ({task['difficulty']}) "
              f"generating...", flush=True)
        t0 = time.perf_counter()
        # cache_prompt=False: el KV-cache reusado cambia los logits
        # (experimento 2026-06-11) -- prefill completo para reproducibilidad
        response = backend.generate(build_prompt(task["prompt"]),
                                    max_tokens=max_tokens,
                                    temperature=BASE_TEMPERATURE, seed=seed,
                                    cache_prompt=False, grammar=grammar)
        gen_s = time.perf_counter() - t0
        response = response or ""
        tokens = backend.last_tokens_predicted  # None si el impl no lo reporta
        tok_s = (tokens / gen_s) if (tokens and gen_s > 0) else None

        code = extract_code(response)
        passed, err_type, err_detail = run_task_tests(
            code, task["tests"], task["entry_point"])
        status = "PASS" if passed else f"FAIL ({err_type})"
        print(f"    -> {status} {err_detail[:80]}", flush=True)

        results.append({
            "id": task["id"], "difficulty": task["difficulty"],
            "entry_point": task["entry_point"], "passed": passed,
            "error_type": err_type, "error_detail": err_detail[:300],
            "gen_seconds": round(gen_s, 2), "tokens_predicted": tokens,
            "tok_per_s": round(tok_s, 2) if tok_s else None,
            "response": response, "extracted_code": code,
        })

    # -- Repair (opcional): regenerar FAILs con el error real --------------
    repair_stats = None
    if repair_rounds > 0:
        repair_stats = repair_failures(backend, tasks, results,
                                       repair_rounds, max_tokens,
                                       repair_temperature, seed=seed,
                                       grammar=grammar)

    # ── Metricas ──────────────────────────────────────────────────────────
    n = len(results)
    n_pass = sum(1 for r in results if r["passed"])
    pass_at_1 = n_pass / n if n else 0.0
    by_diff = {}
    for diff in ("easy", "medium", "hard"):
        sub = [r for r in results if r["difficulty"] == diff]
        if sub:
            by_diff[diff] = {"total": len(sub),
                             "passed": sum(1 for r in sub if r["passed"])}
    errors_by_type = {}
    for r in results:
        if not r["passed"]:
            errors_by_type[r["error_type"]] = errors_by_type.get(r["error_type"], 0) + 1
    speeds = [r["tok_per_s"] for r in results if r["tok_per_s"]]
    avg_tok_s = sum(speeds) / len(speeds) if speeds else None
    total_tokens = sum(r["tokens_predicted"] or 0 for r in results)

    output = {
        "label": label,
        "timestamp": datetime.datetime.now().isoformat(),
        "model": gguf_name,
        "max_tokens": max_tokens,
        "temperature": BASE_TEMPERATURE,
        "seed": seed,
        # Toda generacion del benchmark (base y repair) corre sin KV-cache
        "cache_prompt": False,
        # True si la generacion fue restringida con GRAMMAR_PYTHON_BLOCK
        "grammar": use_grammar,
        "repair_temperature": repair_temperature if repair_rounds > 0 else None,
        "server_props": server_props,
        "n_tasks": n,
        "n_passed": n_pass,
        "pass_at_1": round(pass_at_1, 4),
        "by_difficulty": by_diff,
        "errors_by_type": errors_by_type,
        "avg_tok_per_s": round(avg_tok_s, 2) if avg_tok_s else None,
        "total_tokens_predicted": total_tokens,
        "results": results,
    }

    if repair_stats is not None:
        n_pass_final = sum(1 for r in results if r["passed_final"])
        # Recovered por categoria (campo "category" si existe; fallback difficulty)
        task_by_id = {t["id"]: t for t in tasks}
        recovered_by_cat = {}
        pass_by_round = {}
        for r in results:
            cat = task_by_id[r["id"]].get("category", r["difficulty"])
            if not r["passed"] and r["passed_final"]:
                recovered_by_cat[cat] = recovered_by_cat.get(cat, 0) + 1
            for att in r["repair_attempts"]:
                if att["passed"]:
                    pass_by_round[att["round"]] = pass_by_round.get(att["round"], 0) + 1
        # Acumulado de PASS tras cada ronda
        cum = n_pass
        pass_after_round = {}
        for rnd in range(1, repair_rounds + 1):
            cum += pass_by_round.get(rnd, 0)
            pass_after_round[str(rnd)] = cum
        output.update({
            "repair_rounds": repair_rounds,
            "n_passed_after_repair": n_pass_final,
            "pass_after_repair": round(n_pass_final / n, 4) if n else 0.0,
            "recovered": repair_stats["recovered"],
            "recovered_by_category": recovered_by_cat,
            "pass_after_round": pass_after_round,
            "repair_total_tokens": repair_stats["tokens"],
            "repair_total_seconds": round(repair_stats["seconds"], 2),
        })

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = EVAL_DIR / f"results_code_{label}_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ── Tabla ASCII ───────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print(f" CODE BENCHMARK pass@1 -- label={label}  model={gguf_name}")
    print("=" * 72)
    print(f" {'ID':<5} {'DIFF':<7} {'RESULT':<7} REASON")
    print("-" * 72)
    for r in results:
        reason = "-" if r["passed"] else f"{r['error_type']}: {r['error_detail'][:42]}"
        print(f" {r['id']:<5} {r['difficulty']:<7} "
              f"{'PASS' if r['passed'] else 'FAIL':<7} {reason}")
    print("-" * 72)
    print(f" pass@1 GLOBAL: {n_pass}/{n} = {pass_at_1:.1%}")
    for diff, d in by_diff.items():
        print(f"   {diff:<7}: {d['passed']}/{d['total']}")
    if errors_by_type:
        print(f" errores: " + ", ".join(f"{k}={v}" for k, v in sorted(errors_by_type.items())))
    if avg_tok_s:
        print(f" velocidad: {avg_tok_s:.2f} tok/s promedio, "
              f"{total_tokens} tokens generados en total")
    if repair_stats is not None:
        print("-" * 72)
        print(f" REPAIR (hasta {repair_rounds} rondas, feedback de ejecucion real):")
        for rnd, cum in output["pass_after_round"].items():
            print(f"   pass tras ronda {rnd}: {cum}/{n} = {cum / n:.1%}")
        print(f"   pass_after_repair: {output['n_passed_after_repair']}/{n} "
              f"= {output['pass_after_repair']:.1%}  "
              f"(recovered {output['recovered']} FAIL->PASS)")
        if output["recovered_by_category"]:
            print("   recovered por categoria: " + ", ".join(
                f"{k}={v}" for k, v in sorted(output["recovered_by_category"].items())))
        print(f"   costo repair: {output['repair_total_tokens']} tokens, "
              f"{output['repair_total_seconds']:.0f}s extra")
    print(f" JSON: {out_path}")
    print("=" * 72)
    return output


def main():
    parser = argparse.ArgumentParser(description="Cognia code benchmark (pass@1, ejecucion real)")
    parser.add_argument("--label", default="baseline", help="etiqueta para el JSON de salida")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--limit", type=int, default=None,
                        help="correr solo las primeras N tasks (smoke test)")
    parser.add_argument("--tasks-file", default=None,
                        help="JSON opcional con lista de tasks (mismo schema que TASKS)")
    parser.add_argument("--repair", type=int, default=0,
                        help="N rondas de reparacion con feedback de ejecucion "
                             "para las tasks FAIL (default 0 = sin repair)")
    parser.add_argument("--repair-temp", type=float, default=0.5,
                        help="temperatura para las rondas de reparacion (default 0.5; "
                             "temp=0 reproduce codigo identico, temp>0 permite divergir)")
    parser.add_argument("--seed", type=int, default=42,
                        help="seed de sampling para llama-server (default 42 = "
                             "determinista junto a cache_prompt=False); se "
                             "persiste en el JSON")
    parser.add_argument("--grammar", action="store_true",
                        help="restringir el sampling con GRAMMAR_PYTHON_BLOCK "
                             "(GBNF): el output es exactamente un bloque "
                             "```python ...``` — sin prosa ni fences rotos")
    args = parser.parse_args()

    tasks = TASKS
    if args.tasks_file:
        with open(args.tasks_file, encoding="utf-8") as f:
            text = f.read()
        try:
            tasks = json.loads(text)          # lista JSON clasica
        except json.JSONDecodeError:          # JSONL: un objeto por linea
            tasks = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if args.limit:
        tasks = tasks[:args.limit]

    run_benchmark(tasks, label=args.label, max_tokens=args.max_tokens,
                  repair_rounds=args.repair, repair_temperature=args.repair_temp,
                  seed=args.seed, use_grammar=args.grammar)


if __name__ == "__main__":
    main()
