"""
Kernel Kaggle GPU: generador de dataset sintetico de CODIGO para QLoRA dirigido (CYCLE 8).

Por que: el techo de pass@1 del Qwen2.5-Coder-3B (40% set duro) es capacidad single-shot
(5 hipotesis de prompt/decode medidas, 0 ganancia). La palanca es ENTRENAR, y el dataset
actual (cognia_dataset.jsonl: kg_triples/episodios) dio deltas NEGATIVOS en codigo.

Corre COMO KERNEL DE KAGGLE (script, GPU, enable_internet=true):
  - Generador: Qwen2.5-Coder-7B-Instruct en 4-bit nf4 (bitsandbytes), montado como
    model source. El 14B-Instruct tambien va montado: se usa SOLO si un device tiene
    >= 20 GB de VRAM. En las GPUs gratis de Kaggle (T4 16GB x2 / P100 16GB) gana el
    7B: el 14B solo cabe shardeado entre 2 T4 (pipeline-parallel bnb = mitad de
    throughput) y el cuello de botella es pares VERIFICADOS dentro de las 4h.
  - El image de Kaggle NO trae bitsandbytes>=0.46.1 (run 1 del 2026-06-11 murio
    con ImportError en el load 4-bit). Cascada de carga: pip install -U
    bitsandbytes -> 4-bit nf4; si bnb sigue inusable -> fp16 shardeado entre las
    2 T4 (7B fp16 ~15GB cabe); si el load igual falla (OOM) -> 3b-instruct fp16.
  - Plantillas dirigidas a las bandas debiles del 3B: LONG 60% (clases con estado,
    40-80 lineas) y SPEC 40% (formato EXACTO de salida, casos borde explicitos).
    Temperatura 0.8 para diversidad de soluciones.
  - ANTI-LEAKAGE: los temas son DISJUNTOS de cognia_v3/eval/tasks_hard.jsonl
    (prohibido LRUCache / Matrix / Polynomial / parse_json / run_turtle /
    format_table / compare_versions / validate_username / summarize_logs y los
    6 algo). El set duro es el instrumento de medicion y no se contamina.
  - GATE DE CALIDAD (no negociable): por cada candidato el kernel genera 3-5
    asserts (greedy) desde el MISMO enunciado, valida estaticamente solucion y
    asserts (ast.parse, allowlist de imports, sin input/open/eval/exec) y ejecuta
    solucion+asserts en subprocess aislado (-I) con timeout 10s. Solo lo que pasa
    entra al JSONL final.

Output en /kaggle/working (descargable por CLI):
  - synthetic_code_dataset.jsonl   {prompt, completion, source: "syn_long"|"syn_spec"}
  - datagen_report.json            conteos, tasa de aceptacion, distribucion por banda
Checkpoint parcial cada 50 pares aceptados. Corte: 500 pares o 4h, lo primero.

Las funciones de armado de prompts y validacion de pares son module-level PURAS
(sin torch) para testearlas en local: tests/test_datagen_kernel.py.
"""
import ast
import glob
import json
import os
import random
import re
import subprocess
import sys
import time

OUT = "/kaggle/working"
TARGET_PAIRS = 500
TIME_BUDGET_S = 4 * 3600
CHECKPOINT_EVERY = 50
EXEC_TIMEOUT_S = 10
GEN_BATCH = 4               # prompts por lote de generacion (left-padding)
LONG_RATIO = 0.6            # mezcla objetivo: 60% LONG / 40% SPEC
MIN_LONG_LINES = 20         # lineas de codigo (no blanco/comentario) minimas en LONG
MIN_SPEC_LINES = 3
MAX_LINES = 120
MIN_ASSERTS = 3
MAX_NEW_SOLUTION = 1024
MAX_NEW_ASSERTS = 300
SEED = 20260611

SOLUTION_SYSTEM = ("You are an expert Python programmer. Reply with ONLY a Python "
                   "code block containing the complete solution. No explanations.")
ASSERTS_SYSTEM = ("You are an expert Python test writer. Reply with ONLY a Python "
                  "code block. No explanations.")

# Allowlist de imports para el codigo generado Y sus asserts (regla 9 de CLAUDE.md:
# scan estatico + sandbox). Determinista y sin IO: nada de os/sys/random/time.
IMPORT_ALLOWLIST = {"math", "re", "json", "itertools", "functools", "collections",
                    "heapq", "bisect", "string", "typing", "dataclasses", "copy"}
_FORBIDDEN_CALLS = {"input", "open", "eval", "exec", "compile", "__import__",
                    "exit", "quit", "breakpoint"}

# ---------------------------------------------------------------------------
# Plantillas. Cada una: name, entry (nombre exacto de clase/funcion), kind
# (class|function), prompt con tokens {slot} y slots con sus opciones. Los
# enunciados copian el ESTILO del set duro (ALL of these methods / exact rules
# / ejemplos inline) pero con temas disjuntos. Los ejemplos inline con `==`
# alimentan la generacion de asserts. Cuando un slot cambia la semantica, el
# ejemplo correspondiente vive DENTRO del slot para que nunca contradiga.
# ---------------------------------------------------------------------------

LONG_TEMPLATES = [
    {
        "name": "bank_account",
        "entry": "BankAccount",
        "kind": "class",
        "prompt": """Implement a Python class `BankAccount` with ALL of these methods, using exactly these names:
- `__init__(self, owner)`: account for `owner` with balance 0. `balance` must be readable as an attribute.
- `deposit(self, amount)`: add amount. Raise ValueError if amount is not a positive integer.
- `withdraw(self, amount)`: subtract amount (positive integer). If the operation would leave the balance below {min_balance}, raise ValueError and leave the balance unchanged.
- `transfer(self, other, amount)`: withdraw `amount` from self and deposit it into `other` (another BankAccount). If the withdrawal fails, NEITHER account changes.
- `history(self)`: list of strings, one per successful operation on this account, in chronological order, formatted exactly like "deposit 100", "withdraw 30", "transfer 40 to bob" (a transfer is recorded only on the sender; the receiver records a plain deposit).
Example: a = BankAccount("ana"); b = BankAccount("bob"); a.deposit(100); a.transfer(b, 40) -> a.balance == 60, b.balance == 40, a.history() == ["deposit 100", "transfer 40 to bob"].""",
        "slots": {"min_balance": ["0", "the overdraft limit of -100", "10"]},
    },
    {
        "name": "fraction",
        "entry": "Frac",
        "kind": "class",
        "prompt": """Implement a Python class `Frac` for exact rational numbers, constructed as `Frac(num, den)`, with ALL of these behaviors:
- On construction the fraction is normalized: reduced to lowest terms and the denominator is always positive (the sign lives in the numerator). Raise ValueError if den == 0.
- `__add__`, `__sub__`, `__mul__`: arithmetic with another Frac, returning a NEW normalized Frac.
- `__eq__`: two Frac are equal when their normalized forms match.
- `__str__`: exactly "num/den", except when the normalized denominator is 1, then just "num".
- {extra_method}
Example: str(Frac(2, 4) + Frac(1, 4)) == "3/4"; str(Frac(2, 2)) == "1"; Frac(1, -2) == Frac(-1, 2).""",
        "slots": {"extra_method": [
            "`to_float(self)`: the value as a float. Example: Frac(1, 4).to_float() == 0.25.",
            "`reciprocal(self)`: a new Frac with num and den swapped; raise ZeroDivisionError on a zero fraction. Example: str(Frac(2, 3).reciprocal()) == \"3/2\".",
            "`__lt__(self, other)`: compare by numeric value. Example: Frac(1, 3) < Frac(1, 2).",
        ]},
    },
    {
        "name": "scheduler",
        "entry": "Scheduler",
        "kind": "class",
        "prompt": """Implement a Python class `Scheduler` that manages named events on an integer timeline, with ALL of these methods, using exactly these names:
- `__init__(self)`: empty schedule.
- `book(self, start, end, name)`: add the event only if it does not overlap any existing event; touching endpoints (one event ends exactly where another starts) {touch_rule}. Return True if added, False otherwise. Raise ValueError unless start < end.
- `cancel(self, name)`: remove the event with that name; return True if it existed, False otherwise.
- `next_event(self, t)`: the name of the booked event with the smallest start >= t, or None if there is none.
- `count(self)`: how many events are currently booked.
Example: s = Scheduler(); s.book(0, 10, "a") is True; s.book(5, 15, "b") is False; s.next_event(0) == "a"; s.count() == 1.""",
        "slots": {"touch_rule": ["do NOT count as overlap", "DO count as overlap"]},
    },
    {
        "name": "text_history",
        "entry": "TextHistory",
        "kind": "class",
        "prompt": """Implement a Python class `TextHistory` (an editable text buffer with undo/redo) with ALL of these methods, using exactly these names:
- `__init__(self)`: empty text "".
- `type(self, s)`: append the string s to the text.
- `delete(self, n)`: remove the last n characters; {over_delete}.
- `undo(self)`: revert the most recent type/delete not yet undone (repeated undos keep walking back); do nothing if there is nothing to undo.
- `redo(self)`: re-apply the most recently undone operation; any new type/delete clears the redo history.
- `text(self)`: return the current text.
Example: h = TextHistory(); h.type("ab"); h.type("cd"); h.undo(); h.text() == "ab"; h.redo(); h.text() == "abcd".""",
        "slots": {"over_delete": [
            "if n exceeds the current length, clear the whole text",
            "raise ValueError if n exceeds the current length (and change nothing)",
        ]},
    },
    {
        "name": "task_list",
        "entry": "TaskList",
        "kind": "class",
        "prompt": """Implement a Python class `TaskList` (a priority task list) with ALL of these methods, using exactly these names:
- `__init__(self)`: empty list.
- `add(self, name, priority)`: add a pending task with an integer priority (duplicate names are allowed).
- `pop(self)`: remove and return the name of the pending task with the {pop_rule} Raise IndexError when empty.
- `peek(self)`: like pop but WITHOUT removing; return None when empty.
- `cancel(self, name)`: remove the earliest-added pending task with that name; return True if one was removed, False otherwise.
- `__len__(self)`: number of pending tasks.
Example: t = TaskList(); t.add("x", 3); len(t) == 1; t.cancel("x") is True; len(t) == 0; t.peek() is None.""",
        "slots": {"pop_rule": [
            'HIGHEST numeric priority; ties broken by insertion order (earlier added wins). Example: t.add("a", 1); t.add("b", 9) -> t.pop() == "b".',
            'LOWEST numeric priority; ties broken by insertion order (earlier added wins). Example: t.add("a", 1); t.add("b", 9) -> t.pop() == "a".',
        ]},
    },
    {
        "name": "vending",
        "entry": "Vending",
        "kind": "class",
        "prompt": """Implement a Python class `Vending` (a vending machine) with ALL of these methods, using exactly these names:
- `__init__(self, items)`: items maps name -> [price_cents, stock]. Credit starts at 0.
- `insert(self, coin)`: add the coin to the current credit; only coins in {coins} are accepted, any other value raises ValueError (credit unchanged).
- `buy(self, name)`: if the item exists, its stock is > 0 and credit >= price: decrement the stock, reset credit to 0 and return the change in cents. Otherwise return None and change NOTHING.
- `refund(self)`: return the current credit and reset it to 0.
- `stock(self, name)`: remaining stock for the item (0 for unknown names).
Example: v = Vending({"cola": [150, 1]}); v.insert(100); v.insert(100); v.buy("cola") == 50; v.stock("cola") == 0; v.buy("cola") is None.""",
        "slots": {"coins": ["(5, 10, 25, 50, 100)", "(10, 50, 100, 200)",
                            "(1, 5, 10, 25, 50, 100)"]},
    },
    {
        "name": "grade_book",
        "entry": "GradeBook",
        "kind": "class",
        "prompt": """Implement a Python class `GradeBook` with ALL of these methods, using exactly these names:
- `__init__(self)`: empty grade book.
- `add_student(self, name)`: register a student; raise ValueError on duplicate names.
- `record(self, name, score)`: append a score for the student; raise KeyError for unknown students and ValueError unless 0 <= score <= 100.
- `average(self, name)`: float average of the student's scores; {empty_avg} when the student has no scores yet; KeyError for unknown students.
- `best(self)`: name of the student with the highest average, ties broken alphabetically; students without scores are ignored; None when nobody has scores.
- `passing(self, threshold)`: alphabetically sorted list of student names whose average is >= threshold.
Example: g = GradeBook(); g.add_student("ana"); g.record("ana", 80); g.record("ana", 90); g.average("ana") == 85.0; g.best() == "ana".""",
        "slots": {"empty_avg": ["return 0.0", "raise ValueError"]},
    },
    {
        "name": "ring_buffer",
        "entry": "Ring",
        "kind": "class",
        "prompt": """Implement a Python class `Ring` (a fixed-capacity circular buffer) with ALL of these methods, using exactly these names:
- `__init__(self, capacity)`: empty buffer; raise ValueError unless capacity is a positive integer.
- `push(self, x)`: append x; when the buffer is FULL, the oldest element is overwritten.
- `pop(self)`: remove and return the OLDEST element; {empty_pop} when empty.
- `to_list(self)`: the current elements as a list, oldest first.
- `__len__(self)`: number of stored elements (never above capacity).
- `is_full(self)`: True when len equals capacity.
Example: r = Ring(2); r.push(1); r.push(2); r.push(3); r.to_list() == [2, 3]; r.pop() == 2; len(r) == 1.""",
        "slots": {"empty_pop": ["raise IndexError", "return None"]},
    },
    {
        "name": "config_parser",
        "entry": "parse_config",
        "kind": "function",
        "prompt": """Write a Python function `parse_config(text)` that parses a small INI-like configuration into a dict of dicts, following these exact rules:
1. A line `[section]` opens a section named "section" (it becomes a key of the outer dict, mapping to an inner dict).
2. A line `key = value` assigns inside the CURRENT section; spaces around `=`, the key and the value are trimmed.
3. Value coercion: a string of digits (optionally with a leading `-`) -> int; "true"/"false" in any case -> bool; anything else -> the trimmed string.
4. Blank lines and lines whose first non-space character is `{comment}` are ignored.
5. {extra_rule}
6. `key = value` lines appearing before any `[section]` go under the "" (empty string) section.
Example: parse_config("[db]\\nport = 5432\\nlocal = true") == {"db": {"port": 5432, "local": True}}.""",
        "slots": {
            "comment": ["#", ";"],
            "extra_rule": [
                "Duplicate keys inside a section keep the LAST value.",
                "A non-blank line that is neither a section, an assignment nor a comment raises ValueError.",
                "Section names repeated later MERGE into the already-created inner dict.",
            ],
        },
    },
    {
        "name": "warehouse",
        "entry": "Warehouse",
        "kind": "class",
        "prompt": """Implement a Python class `Warehouse` (stock with reservations) with ALL of these methods, using exactly these names:
- `__init__(self)`: empty warehouse.
- `add(self, sku, qty)`: add qty units on hand for sku; raise ValueError unless qty is a positive integer.
- `available(self, sku)`: units on hand MINUS reserved units (0 for unknown skus).
- `reserve(self, sku, qty)`: reserve qty units only if available(sku) >= qty; return True/False. Reserving an unknown sku {unknown_rule}.
- `release(self, sku, qty)`: un-reserve up to qty units (the reserved count never goes below 0).
- `ship(self, sku, qty)`: if at least qty units of sku are reserved, remove them from both the reservation and the stock on hand and return True; otherwise return False and change nothing.
Example: w = Warehouse(); w.add("a", 5); w.reserve("a", 3) is True; w.available("a") == 2; w.ship("a", 3) is True; w.available("a") == 2.""",
        "slots": {"unknown_rule": ["returns False", "raises KeyError"]},
    },
]

SPEC_TEMPLATES = [
    {
        "name": "format_duration",
        "entry": "format_duration",
        "kind": "function",
        "prompt": """Write a Python function `format_duration(seconds)` that renders an integer number of seconds as a string following these EXACT rules:
1. Decompose into hours, minutes and seconds.
2. If hours > 0: "Hh MMm SSs" where minutes and seconds are zero-padded to 2 digits and hours is not padded.
3. Else if minutes > 0: "Mm SSs" where only the seconds are zero-padded to 2 digits.
4. Else: "Ss" with no padding at all.
5. format_duration(0) == "0s".
6. {neg_rule}
Examples: format_duration(0) == "0s"; format_duration(9) == "9s"; format_duration(61) == "1m 01s"; format_duration(3661) == "1h 01m 01s".""",
        "slots": {"neg_rule": [
            "A negative input raises ValueError.",
            'A negative input is formatted as the absolute value with a leading "-" (e.g. format_duration(-61) == "-1m 01s").',
        ]},
    },
    {
        "name": "progress_bar",
        "entry": "progress_bar",
        "kind": "function",
        "prompt": """Write a Python function `progress_bar(done, total, width)` that returns EXACTLY one string "[BAR] P%" following these rules:
1. BAR has exactly `width` characters: floor(width * done / total) hash marks '#' followed by dots '.' for the rest.
2. P is floor(100 * done / total), an integer with no decimals.
3. There is exactly one space between "]" and the percentage, and '%' is attached to the number.
4. total == 0 raises ValueError. done < 0 raises ValueError. done > total {over_rule}.
Examples: progress_bar(1, 2, 10) == "[#####.....] 50%"; progress_bar(0, 4, 4) == "[....] 0%"; progress_bar(3, 3, 5) == "[#####] 100%".""",
        "slots": {"over_rule": [
            "is clamped to total (full bar, 100%)",
            "raises ValueError",
        ]},
    },
    {
        "name": "humanize_bytes",
        "entry": "humanize_bytes",
        "kind": "function",
        "prompt": """Write a Python function `humanize_bytes(n)` that formats a byte count following these EXACT rules:
1. Units, from smallest to largest: {units}
2. Pick the LARGEST unit whose value is >= 1; below the first threshold the number stays in plain "B" with no decimals.
3. For units above B: keep exactly one decimal digit, truncated (NOT rounded); but when that decimal is 0 drop it entirely (write "2 KB", never "2.0 KB").
4. humanize_bytes(0) == "0 B". A negative input raises ValueError.
5. There is exactly one space between the number and the unit.""",
        "slots": {"units": [
            'B, KB, MB, GB, TB with factor 1024. Examples: humanize_bytes(512) == "512 B"; humanize_bytes(1536) == "1.5 KB"; humanize_bytes(1048576) == "1 MB".',
            'B, KiB, MiB, GiB with factor 1024. Examples: humanize_bytes(512) == "512 B"; humanize_bytes(1536) == "1.5 KiB"; humanize_bytes(1048576) == "1 MiB".',
        ]},
    },
    {
        "name": "csv_row",
        "entry": "csv_row",
        "kind": "function",
        "prompt": """Write a Python function `csv_row(fields)` that serializes a list of strings into ONE CSV line (a single string, no trailing newline) following these EXACT rules:
1. Fields are joined with a comma.
2. A field must be wrapped in double quotes when it contains a comma, a double quote, a newline, or has leading/trailing spaces.
3. Inside a quoted field, every double quote is doubled.
4. csv_row([]) == "". {empty_field_rule}
Examples: csv_row(["a", "b,c"]) == 'a,"b,c"'; csv_row(['say "hi" now']) == '"say ""hi"" now"'; csv_row([" x"]) == '" x"'.""",
        "slots": {"empty_field_rule": [
            "An empty string field is rendered as nothing (two adjacent commas around it).",
            'An empty string field is rendered as "" (two double quotes).',
        ]},
    },
    {
        "name": "to_roman",
        "entry": "to_roman",
        "kind": "function",
        "prompt": """Write a Python function `to_roman(n)` that converts an integer to a Roman numeral string following these EXACT rules:
1. Valid range is 1 <= n <= 3999; anything else {invalid_rule}.
2. Use uppercase letters I, V, X, L, C, D, M with standard subtractive notation (IV, IX, XL, XC, CD, CM); never four identical symbols in a row.
Examples: to_roman(4) == "IV"; to_roman(9) == "IX"; to_roman(1994) == "MCMXCIV"; to_roman(3999) == "MMMCMXCIX".""",
        "slots": {"invalid_rule": ["raises ValueError", "returns None"]},
    },
    {
        "name": "format_phone",
        "entry": "format_phone",
        "kind": "function",
        "prompt": """Write a Python function `format_phone(digits)` where `digits` is a string, following these EXACT rules:
1. First strip EVERY non-digit character (spaces, dashes, parentheses, dots, anything).
2. Exactly 10 digits left -> return "(AAA) BBB-CCCC".
3. {eleven_rule}
4. Any other digit count raises ValueError.
Example: format_phone("123-456.7890") == "(123) 456-7890".""",
        "slots": {"eleven_rule": [
            'Exactly 11 digits starting with "1" -> "+1 (AAA) BBB-CCCC" using the last 10 digits; 11 digits NOT starting with "1" raise ValueError. Example: format_phone("1 (234) 567 8901") == "+1 (234) 567-8901".',
            "Exactly 11 digits raise ValueError no matter what they start with.",
        ]},
    },
    {
        "name": "wrap_text",
        "entry": "wrap",
        "kind": "function",
        "prompt": """Write a Python function `wrap(text, width)` (greedy word wrap) following these EXACT rules:
1. Words are maximal runs of non-whitespace; any other whitespace in the input is discarded.
2. Build lines greedily: keep appending the next word (joined by a single space) while the line stays <= width characters.
3. A single word LONGER than width {long_word_rule}
4. Return the list of lines; no line has leading or trailing spaces. Empty or whitespace-only text -> [].
Examples: wrap("a bb ccc", 4) == ["a bb", "ccc"]; wrap("", 5) == [].""",
        "slots": {"long_word_rule": [
            'is hard-split into chunks of exactly `width` characters (the last chunk may be shorter). Example: wrap("abcdef", 2) == ["ab", "cd", "ef"].',
            'is placed alone on its own line even though it exceeds width. Example: wrap("abcdef", 2) == ["abcdef"].',
        ]},
    },
    {
        "name": "ordinal",
        "entry": "ordinal",
        "kind": "function",
        "prompt": """Write a Python function `ordinal(n)` that renders an integer with its English ordinal suffix following these EXACT rules:
1. Numbers ending in 1 -> "st", in 2 -> "nd", in 3 -> "rd", everything else -> "th".
2. EXCEPTION: numbers ending in 11, 12 or 13 always take "th" (11th, 112th, 1013th).
3. {bad_input}
Examples: ordinal(1) == "1st"; ordinal(2) == "2nd"; ordinal(11) == "11th"; ordinal(22) == "22nd"; ordinal(113) == "113th".""",
        "slots": {"bad_input": [
            "ordinal(0) and negative numbers raise ValueError.",
            'ordinal(0) == "0th"; negative numbers raise ValueError.',
        ]},
    },
    {
        "name": "group_digits",
        "entry": "group_digits",
        "kind": "function",
        "prompt": """Write a Python function `group_digits(n, sep=",")` that formats an integer with a separator every 3 digits following these EXACT rules:
1. Grouping starts from the RIGHTMOST digit.
2. A negative number keeps its leading "-" and the sign is NEVER followed by a separator.
3. Numbers with absolute value < 1000 get no separator at all.
4. {sep_rule}
Examples: group_digits(1234567) == "1,234,567"; group_digits(-1000, "_") == "-1_000"; group_digits(42) == "42".""",
        "slots": {"sep_rule": [
            "The separator may be any non-empty string and is used verbatim.",
            "Raise ValueError if sep is an empty string or contains a digit.",
        ]},
    },
    {
        "name": "mask_card",
        "entry": "mask_card",
        "kind": "function",
        "prompt": """Write a Python function `mask_card(s)` that masks a card number string following these EXACT rules:
1. First remove every space and dash from s. The result must be 13 to 19 digits, otherwise raise ValueError.
2. Replace every digit EXCEPT the last {keep} with "*".
3. Regroup the masked string into blocks of 4 characters from the LEFT, joined by single spaces (the final block may be shorter).
Examples: mask_card("1234 5678 9012 3456") == "**** **** **** 3456"; mask_card("1234-5678-90123") == "**** **** ***1 23".""",
        "slots": {"keep": ["4 digits"]},
    },
]

TEMPLATES = {"long": LONG_TEMPLATES, "spec": SPEC_TEMPLATES}

# OJO con mask_card: el segundo ejemplo depende de keep=4 (unico valor del slot).
# Si se agregan opciones a "keep", mover los ejemplos adentro del slot.


# ---------------------------------------------------------------------------
# Funciones puras (testeadas en tests/test_datagen_kernel.py)
# ---------------------------------------------------------------------------

def fill_slots(prompt: str, slots: dict, rng: random.Random) -> str:
    """Reemplaza cada token {slot} por una opcion al azar. Orden estable por clave."""
    for key in sorted(slots):
        prompt = prompt.replace("{" + key + "}", rng.choice(slots[key]))
    return prompt


def build_prompt(band: str, rng: random.Random) -> dict:
    """Elige plantilla de la banda y devuelve el enunciado final con slots llenos."""
    t = rng.choice(TEMPLATES[band])
    return {"band": band, "name": t["name"], "entry": t["entry"], "kind": t["kind"],
            "prompt": fill_slots(t["prompt"], t.get("slots", {}), rng)}


def pick_band(n_long: int, n_spec: int) -> str:
    """Banda del proximo candidato manteniendo la mezcla LONG_RATIO sobre ACEPTADOS
    (si LONG acepta menos, se insiste mas con LONG: la mezcla se autocorrige)."""
    total = n_long + n_spec
    if total == 0:
        return "long"
    return "long" if n_long / total < LONG_RATIO else "spec"


_CODE_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_python_block(text: str):
    """Primer bloque ```python``` de la respuesta. Fence abierto sin cerrar (corte
    por max tokens): lo que sigue al fence. Sin fence: el texto entero SOLO si
    parsea como Python (prosa -> None)."""
    if not text:
        return None
    m = _CODE_FENCE_RE.search(text)
    if m:
        return m.group(1).strip() or None
    open_fence = re.search(r"```(?:python|py)?\s*\n", text)
    if open_fence:
        return text[open_fence.end():].strip() or None
    code = text.strip()
    if not code:
        return None
    try:
        ast.parse(code)
    except SyntaxError:
        return None
    return code


def _static_scan(tree: ast.AST):
    """Razon de rechazo (str) o None: imports fuera de allowlist / builtins prohibidos."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in IMPORT_ALLOWLIST:
                    return "import:" + root
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in IMPORT_ALLOWLIST:
                return "import:" + root
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FORBIDDEN_CALLS):
            return "call:" + node.func.id
    return None


def _code_lines(code: str) -> list:
    return [ln for ln in code.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def validate_solution(code: str, band: str, entry: str, kind: str):
    """Gate estatico de la solucion: parsea, imports/builtins, entry presente con el
    kind correcto, tamano acorde a la banda. Devuelve (ok, razon)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, "syntax:%s" % e.lineno
    bad = _static_scan(tree)
    if bad:
        return False, bad
    node_type = ast.ClassDef if kind == "class" else ast.FunctionDef
    if not any(isinstance(n, node_type) and n.name == entry for n in ast.walk(tree)):
        return False, "missing_entry:" + entry
    n_lines = len(_code_lines(code))
    min_lines = MIN_LONG_LINES if band == "long" else MIN_SPEC_LINES
    if n_lines < min_lines:
        return False, "too_short:%d" % n_lines
    if n_lines > MAX_LINES:
        return False, "too_long:%d" % n_lines
    return True, ""


def validate_asserts(code: str, entry: str):
    """Gate estatico del bloque de asserts: parsea, imports/builtins, >= MIN_ASSERTS
    asserts reales, referencia al entry y NO lo redefine (eso anularia el gate)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, "syntax:%s" % e.lineno
    bad = _static_scan(tree)
    if bad:
        return False, bad
    n = sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
    if n < MIN_ASSERTS:
        return False, "few_asserts:%d" % n
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name == entry):
            return False, "redefines_entry"
    if entry not in code:
        return False, "no_entry_ref"
    if len(code.splitlines()) > 60:
        return False, "too_long"
    return True, ""


def build_harness(solution: str, asserts: str) -> str:
    """Script autoejecutable: solucion + asserts + marcador de exito."""
    return solution + "\n\n" + asserts + "\n\nprint('ASSERTS_OK')\n"


def run_harness(solution: str, asserts: str, timeout_s: int = EXEC_TIMEOUT_S):
    """Ejecuta solucion+asserts en un subprocess aislado (-I). (ok, detalle)."""
    try:
        r = subprocess.run([sys.executable, "-I", "-"],
                           input=build_harness(solution, asserts),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0 or "ASSERTS_OK" not in (r.stdout or ""):
        return False, ((r.stderr or r.stdout or "").strip())[-300:]
    return True, ""


def make_record(prompt: str, code: str, band: str) -> dict:
    """Registro JSONL de entrenamiento: la completion es SOLO el bloque ```python
    (es exactamente lo que extract_code del benchmark espera ver en eval)."""
    return {"prompt": prompt,
            "completion": "```python\n" + code + "\n```",
            "source": "syn_long" if band == "long" else "syn_spec"}


def build_asserts_request(task_prompt: str, entry: str) -> str:
    """User prompt para que el modelo escriba los asserts del gate, desde el MISMO
    enunciado (con sus ejemplos inline) y sin ver la solucion candidata."""
    return ("Below is a Python programming task. Write between 3 and 5 standalone "
            "`assert` statements that verify a CORRECT solution, using only the "
            "rules and the literal examples stated in the task. Use the exact "
            "names from the task. Do NOT define or redefine `" + entry + "`: "
            "assume it already exists. Short setup lines (creating instances or "
            "variables) are allowed. Reply with ONLY a ```python code block.\n\n"
            "[TASK]\n" + task_prompt)


# ---------------------------------------------------------------------------
# Lado Kaggle (GPU): carga del modelo y loop de generacion. torch/transformers
# se importan aca adentro para que el modulo siga siendo importable en local.
# ---------------------------------------------------------------------------

def _ensure_bitsandbytes() -> bool:
    """El image de Kaggle (run 1, 2026-06-11) trae bitsandbytes viejo y el load
    4-bit muere: transformers exige bitsandbytes>=0.46.1. Intento guardado de
    upgrade por pip (necesita enable_internet=true) y chequeo de version; si
    devuelve False, main() carga en fp16 sin quantization_config."""
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U",
                            "bitsandbytes"],
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print("[bnb] pip install -U bitsandbytes -> rc=%d (%s)"
              % (r.returncode, tail[-1] if tail else "sin output"), flush=True)
    except Exception as e:
        print("[bnb] pip install fallo: %s" % e, flush=True)
    try:
        import importlib.metadata
        import bitsandbytes  # noqa: F401  (importable = sus libs CUDA cargan)
        ver = importlib.metadata.version("bitsandbytes")
        ok = tuple(int(x) for x in ver.split(".")[:3]) >= (0, 46, 1)
        print("[bnb] version instalada: %s -> %s"
              % (ver, "OK" if ok else "insuficiente (<0.46.1)"), flush=True)
        return ok
    except Exception as e:
        print("[bnb] import fallo: %s" % e, flush=True)
        return False


def _pick_model_dir() -> str:
    """Dir del modelo montado bajo /kaggle/input. 14B solo si UN device tiene
    >= 20 GB (en T4 16GB x2 / P100 16GB el 14B va shardeado y rinde la mitad;
    el cuello es pares verificados/hora, asi que ahi gana el 7B)."""
    import torch
    candidates = sorted({os.path.dirname(p) for p in
                         glob.glob("/kaggle/input/**/config.json", recursive=True)})
    if not candidates:
        raise FileNotFoundError(
            "No hay modelos montados bajo /kaggle/input. Adjuntar "
            "qwen-lm/qwen2.5-coder/transformers/{7b,14b}-instruct.")
    gpus = list(range(torch.cuda.device_count())) if torch.cuda.is_available() else []
    vrams = [torch.cuda.get_device_properties(i).total_memory / 1e9 for i in gpus]
    for i, v in enumerate(vrams):
        print("[gpu] device %d: %s %.1f GB" % (i, torch.cuda.get_device_name(i), v))
    # v2 (2026-06-12): el run v1 con 7B produjo 20 candidatos en 4h (~12 min/par,
    # camino lento: fp16 shardeado entre 2 T4). El 3b fp16 (~6GB) cabe ENTERO en
    # una T4 -> 5-10x mas candidatos/hora; con el gate de ejecucion esto es
    # rejection sampling (estilo STaR): data auto-generada y verificada es valida
    # para mejorar al MISMO 3B en sus bandas debiles.
    key = "14b" if vrams and max(vrams) >= 20.0 else "3b"
    match = [d for d in candidates if key in d.lower()]
    pool = match or candidates
    pool.sort(key=len)
    print("[model] eleccion: %s -> %s" % (key, pool[0]))
    return pool[0]


def _generate_batch(model, tokenizer, system: str, user_prompts: list,
                    temperature: float, max_new_tokens: int) -> list:
    """Genera en lote con left-padding. temperature <= 0 -> greedy."""
    import torch
    texts = [tokenizer.apply_chat_template(
        [{"role": "system", "content": system}, {"role": "user", "content": p}],
        tokenize=False, add_generation_prompt=True) for p in user_prompts]
    inputs = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
    kwargs = dict(max_new_tokens=max_new_tokens,
                  pad_token_id=tokenizer.pad_token_id)
    if temperature > 0:
        kwargs.update(do_sample=True, temperature=temperature, top_p=0.95)
    else:
        kwargs.update(do_sample=False)
    with torch.no_grad():
        out = model.generate(**inputs, **kwargs)
    n_in = inputs["input_ids"].shape[1]
    return [tokenizer.decode(out[i][n_in:], skip_special_tokens=True)
            for i in range(len(user_prompts))]


def _write_outputs(accepted: list, rejects: dict, n_candidates: int,
                   model_dir: str, t0: float, partial: bool) -> None:
    path = os.path.join(OUT, "synthetic_code_dataset.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for rec in accepted:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    n_long = sum(1 for rec in accepted if rec["source"] == "syn_long")
    report = {
        "partial": partial,
        "model_dir": model_dir,
        "generated": n_candidates,
        "accepted": len(accepted),
        "acceptance_rate": round(len(accepted) / n_candidates, 4) if n_candidates else 0.0,
        "by_band": {"syn_long": n_long, "syn_spec": len(accepted) - n_long},
        "rejects": rejects,
        "elapsed_s": int(time.time() - t0),
    }
    with open(os.path.join(OUT, "datagen_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def main():
    # ANTES de importar transformers: el pip upgrade debe correr primero para
    # que transformers vea la version nueva de bitsandbytes en el load 4-bit.
    use_bnb = _ensure_bitsandbytes()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    rng = random.Random(SEED)
    model_dir = _pick_model_dir()

    def _make_tokenizer(d):
        tok = AutoTokenizer.from_pretrained(d, trust_remote_code=True)
        tok.padding_side = "left"  # generacion en lote
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        return tok

    tokenizer = _make_tokenizer(model_dir)

    if use_bnb:
        from transformers import BitsAndBytesConfig
        # T4/P100 no tienen bf16 -> compute dtype float16 (mismo criterio que el
        # kernel de entrenamiento train_qlora_kaggle.py)
        load_kwargs = dict(quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16))
        print("[model] camino de carga: 4-bit nf4 (bitsandbytes)", flush=True)
    else:
        # FALLBACK sin bnb usable: fp16 shardeado entre GPUs via device_map
        # (7B fp16 ~15GB cabe entre las 2 T4 de 16GB).
        load_kwargs = dict(torch_dtype=torch.float16)
        print("[model] camino de carga: FALLBACK fp16 (bnb>=0.46.1 no disponible)",
              flush=True)

    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_dir, device_map="auto", trust_remote_code=True, **load_kwargs)
    except Exception as e:
        # Ultimo recurso: si ni 4-bit ni fp16 del 7B cargan (p.ej. OOM),
        # degradar al 3B en fp16 (~6GB, entra en una sola T4). Generar con el
        # 3B es lo peor pero mejor que perder la ventana de GPU.
        print("[model] load de %s fallo: %s: %s"
              % (model_dir, type(e).__name__, e), flush=True)
        dirs3 = sorted((d for d in {os.path.dirname(p) for p in glob.glob(
            "/kaggle/input/**/config.json", recursive=True)}
            if "3b" in d.lower()), key=len)
        if not dirs3:
            raise
        model_dir = dirs3[0]
        print("[model] DEGRADADO a 3b-instruct fp16: %s" % model_dir, flush=True)
        tokenizer = _make_tokenizer(model_dir)
        model = AutoModelForCausalLM.from_pretrained(
            model_dir, torch_dtype=torch.float16, device_map="auto",
            trust_remote_code=True)
    model.eval()
    print("[model] cargado en %.1fs" % (time.time() - t0), flush=True)

    accepted = []
    seen = set()
    rejects = {"no_block": 0, "bad_static": 0, "bad_asserts": 0,
               "failed_run": 0, "dup": 0}
    n_long = n_spec = n_candidates = 0
    last_checkpoint = 0

    while len(accepted) < TARGET_PAIRS and time.time() - t0 < TIME_BUDGET_S:
        # lote de candidatos respetando la mezcla 60/40 sobre aceptados
        batch = [build_prompt(pick_band(n_long, n_spec), rng)
                 for _ in range(GEN_BATCH)]
        raws = _generate_batch(model, tokenizer, SOLUTION_SYSTEM,
                               [b["prompt"] for b in batch],
                               temperature=0.8, max_new_tokens=MAX_NEW_SOLUTION)
        n_candidates += len(batch)

        survivors = []
        for spec, raw in zip(batch, raws):
            code = extract_python_block(raw)
            if code is None:
                rejects["no_block"] += 1
                continue
            ok, _reason = validate_solution(code, spec["band"], spec["entry"],
                                            spec["kind"])
            if not ok:
                rejects["bad_static"] += 1
                continue
            survivors.append((spec, code))

        if survivors:
            reqs = [build_asserts_request(s["prompt"], s["entry"])
                    for s, _ in survivors]
            araws = _generate_batch(model, tokenizer, ASSERTS_SYSTEM, reqs,
                                    temperature=0.0,  # asserts: greedy, fiabilidad
                                    max_new_tokens=MAX_NEW_ASSERTS)
            for (spec, code), araw in zip(survivors, araws):
                asserts = extract_python_block(araw)
                if asserts is None or not validate_asserts(asserts, spec["entry"])[0]:
                    rejects["bad_asserts"] += 1
                    continue
                ok, _detail = run_harness(code, asserts)
                if not ok:
                    rejects["failed_run"] += 1
                    continue
                rec = make_record(spec["prompt"], code, spec["band"])
                key = (rec["prompt"], rec["completion"])
                if key in seen:
                    rejects["dup"] += 1
                    continue
                seen.add(key)
                accepted.append(rec)
                if spec["band"] == "long":
                    n_long += 1
                else:
                    n_spec += 1

        if len(accepted) - last_checkpoint >= CHECKPOINT_EVERY:
            _write_outputs(accepted, rejects, n_candidates, model_dir, t0,
                           partial=True)
            last_checkpoint = len(accepted)
            print("[checkpoint] %d pares escritos" % len(accepted), flush=True)

        print("[%6.1fm] candidatos=%d aceptados=%d (long=%d spec=%d) rechazos=%s"
              % ((time.time() - t0) / 60, n_candidates, len(accepted),
                 n_long, n_spec, rejects), flush=True)

    _write_outputs(accepted, rejects, n_candidates, model_dir, t0, partial=False)
    rate = len(accepted) / n_candidates if n_candidates else 0.0
    print("\n=== DATAGEN REPORT ===")
    print("generados:    %d" % n_candidates)
    print("verificados:  %d" % len(accepted))
    print("aceptacion:   %.1f%%" % (100 * rate))
    print("por banda:    long=%d spec=%d" % (n_long, n_spec))
    print("rechazos:     %s" % rejects)
    print("DONE")


if __name__ == "__main__":
    main()
