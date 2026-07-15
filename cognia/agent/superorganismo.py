# -*- coding: utf-8 -*-
"""Superorganismo: etapa 4 de la cascada de generar_codigo (colonia por pedazos).

Port de producción del mecanismo v2 validado por PREREG_SUPERORGANISMO
(gate ≥2/13 CRUZADO 2026-07-14: NEWX3 y ALG3 pasan sus tests OCULTOS con el
presupuesto del pass@16, cuyo baseline es 0/13 por definición). Mecanismo:

  CARTOGRAFÍA (qwen3_4b): descompone el enunciado en helpers con contrato +
    extrae SPEC-ASSERTS literales del texto. Si el razonador no logra un
    oráculo decente, el CODER extrae los suyos y se usa la UNIÓN
    (refuerzo-coder: la clave que rompió NEWX3).
  HORMIGAS POR PIEZA (qwen35_4b): cada helper se resuelve contra su
    micro-oráculo, evaluado sobre el ACUMULADO (soporta recursión mutua).
  ENSAMBLE + FEROMONA: la función principal usa los helpers verificados;
    cada fallo deja rastro (asserts fallados + enfoque) que el siguiente
    intento lee y debe evitar. Keep-best por #asserts pasados.

Lecciones de la corrida medida que este port incorpora:
- Oráculo INFIEL = anti-solución (SPEC1: 43 min optimizando contra un mapa
  falso; NEWX4: asserts autocontradictorios → 0/6 por diseño). Por eso acá
  hay un filtro DETERMINISTA de contradicciones (mismo input → outputs
  distintos ⇒ ambos asserts fuera). Cero LLM: solo elimina pares
  demostrablemente incoherentes.
- Piezas verificadas NO garantizan el ensamble (NEWX2/NEWD2): el veredicto
  del caller debe seguir siendo su propio oráculo (tests visibles/ocultos),
  jamás la palabra de esta etapa.

Solo dispara opt-in (COGNIA_SUPERORGANISMO=1) en tarea dura donde las etapas
1-3 no confirmaron: es el miembro MÁS caro de la colonia (2 modelos 4B
lazy-load + hasta `budget` generaciones). Kill-switch y fallos → None
(la cascada se queda con lo que tenía; esta etapa nunca rompe la tool).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

NOTHINK = "<think>\n\n</think>\n\n"

CARTO_SYSTEM = (
    "You are an expert software architect. You decompose a programming "
    "problem into small helper functions and extract test assertions that "
    "follow LITERALLY from the problem statement. Reply with ONLY a JSON "
    "object, no other text.")

CARTO_TMPL = """Problem statement:
{spec}

The final solution must define `{entry}`. Decompose it into 2-4 SMALL helper
functions, each strictly simpler than the whole problem. For each helper give
a contract and 3-5 assert statements testing ONLY that helper. Also extract
`spec_asserts` (6-14 asserts about `{entry}`), following BOTH rules:
- EVERY concrete example in the problem text (every quoted input whose output
  or validity is stated) MUST appear as one assert. Do not skip any.
- EVERY explicit rule or forbidden/edge case listed in the text gets one
  assert exercising it.
Do not invent cases whose answer you are unsure of.

Reply with ONLY this JSON:
{{"helpers": [{{"name": "...", "signature": "def ...", "contract": "...",
  "asserts": ["assert ..."]}}],
 "spec_asserts": ["assert {entry}(...) == ..."]}}"""

ASSERTS_PLANO_TMPL = """Problem statement:
{spec}

List EVERY test assertion that follows LITERALLY from the problem text: one
per line, each a Python `assert {entry}(...) == ...` (or `== -1`, etc.).
Cover EVERY concrete example mentioned in the text (every quoted input whose
output or validity is stated) and every explicit rule/forbidden case. Do not
invent cases whose answer is not stated or directly implied. Reply with ONLY
assert lines, no other text."""

PIEZA_TMPL = """Write ONLY the Python function below. No explanations, no examples, no other functions.

{signature}

Contract: {contract}

It must pass these tests:
{asserts}

Reply with ONLY a python code block."""

ENSAMBLE_TMPL = """{spec}

These helper functions are ALREADY implemented and verified — they will be \
prepended to your code automatically. Do NOT redefine them, just call them:

{firmas}

Write ONLY the function `{entry}` using these helpers where useful. Reply \
with ONLY a python code block."""

FEROMONA_TMPL = """{spec}

These verified helpers are available (do NOT redefine them):
{firmas}

Your colony's previous attempts FAILED. Trail of failures (avoid repeating \
these mistakes):
{rastro}

Last attempt:
```python
{code}
```
ALL failing tests of the last attempt:
{fallo}

Write ONLY the corrected function `{entry}`. Try a DIFFERENT approach for \
the failing part. Reply with ONLY a python code block."""


def superorganismo_enabled() -> bool:
    return (os.environ.get("COGNIA_SUPERORGANISMO", "").strip().lower()
            in ("1", "on", "true", "yes"))


def _valida_asserts(asserts, requiere: str = "") -> list:
    """Filtra a asserts que compilan (y mencionan `requiere` si se pide)."""
    out = []
    for a in asserts or []:
        a = str(a).strip()
        if not a.startswith("assert"):
            continue
        if requiere and requiere not in a:
            continue
        try:
            compile(a, "<a>", "exec")
        except SyntaxError:
            continue
        out.append(a)
    return out


_ASSERT_EQ_RE = re.compile(r"^assert\s+(.+?)\s*==\s*(.+?)\s*$")


def filtra_contradicciones(asserts: list) -> list:
    """Elimina pares demostrablemente incoherentes: si el MISMO lado
    izquierdo (misma llamada) aparece con resultados esperados DISTINTOS,
    ninguno de esos asserts es confiable y se descartan TODOS los de ese
    input (lección NEWX4: '123' dos veces con outputs distintos hacía el
    oráculo imposible por diseño y quemó el presupuesto entero contra un
    mapa falso). Determinista, cero LLM; los asserts sin '==' pasan tal
    cual (no hay par que comparar)."""
    lhs_rhs: dict = {}
    parseados = []
    for a in asserts or []:
        m = _ASSERT_EQ_RE.match(a)
        if not m:
            parseados.append((a, None, None))
            continue
        lhs = re.sub(r"\s+", " ", m.group(1))
        rhs = re.sub(r"\s+", " ", m.group(2))
        parseados.append((a, lhs, rhs))
        lhs_rhs.setdefault(lhs, set()).add(rhs)
    malos = {lhs for lhs, vals in lhs_rhs.items() if len(vals) > 1}
    return [a for a, lhs, _ in parseados if lhs is None or lhs not in malos]


def _parse_carto(raw: str, entry: str):
    """Extrae el JSON de cartografía; None si irrecuperable."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    helpers = []
    for h in d.get("helpers", [])[:4]:
        sig = str(h.get("signature", "")).strip()
        nom = str(h.get("name", "")).strip()
        if not sig.startswith("def ") or not nom:
            continue
        helpers.append({"name": nom, "signature": sig,
                        "contract": str(h.get("contract", ""))[:400],
                        "asserts": _valida_asserts(h.get("asserts"),
                                                   requiere=nom)})
    spec_asserts = _valida_asserts(d.get("spec_asserts"), requiere=entry)
    if not spec_asserts:
        return None
    return {"helpers": helpers, "spec_asserts": spec_asserts[:14]}


def _run_asserts(code: str, asserts: list, timeout: int = 10):
    """Corre code + cada assert por separado en sandbox.
    Devuelve (n_pass, fallos_lista)."""
    from cognia_v3.eval.benchmark_code import _sandbox_env
    passed, fallos = 0, []
    for a in asserts:
        script = code + "\n\n" + a + "\n"
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", prefix="cognia_so_",
                    delete=False, encoding="utf-8") as f:
                tmp = f.name
                f.write(script)
            p = subprocess.run([sys.executable, tmp], capture_output=True,
                               text=True, timeout=timeout, env=_sandbox_env())
            if p.returncode == 0:
                passed += 1
            else:
                last = (p.stderr or "").strip().splitlines()
                fallos.append(f"{a}  ->  {last[-1] if last else 'exit!=0'}")
        except subprocess.TimeoutExpired:
            fallos.append(f"{a}  ->  TIMEOUT")
        except Exception as exc:
            fallos.append(f"{a}  ->  sandbox: {exc}")
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
    return passed, fallos


def _extrae_asserts_planos(raw: str, entry: str) -> list:
    return _valida_asserts([ln.strip() for ln in (raw or "").splitlines()],
                           requiere=entry)


def superorganismo_solve(desc: str, entry: str, budget: int = None,
                         print_fn=None, timeout_s: int = None):
    """Resuelve `desc` con la colonia por pedazos. Devuelve
    {"code", "spec_pass", "spec_total", "gens", "piezas"} o None si el
    fleet no está disponible / no se logró oráculo / cualquier fallo.
    NUNCA lanza: la cascada que llama se queda con su candidato previo."""
    try:
        return _solve(desc, entry, budget, print_fn, timeout_s)
    except Exception:
        return None


def _detail(print_fn, msg: str) -> None:
    if callable(print_fn):
        print_fn(f"[detail]{msg}[/detail]")


def _solve(desc: str, entry: str, budget, print_fn, timeout_s):
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code)
    from node.fleet_registry import close_fleet_member, fleet_backend
    budget = budget or int(os.environ.get("COGNIA_SUPERORG_BUDGET", "16"))
    timeout_s = timeout_s or int(
        os.environ.get("COGNIA_SUPERORG_TIMEOUT_S", "1800"))
    t0 = time.time()
    gens = 0
    # RESERVA de tiempo para el ensamble: en CPU lento las gens de carto son
    # de 2400 tokens (~400s c/u) y podían consumir TODO el timeout, dejando
    # 0 gens de ensamble → None (cazado por el smoke e2e 2026-07-15 sobre
    # SPEC3). El carto no puede pasar de CARTO_TIME_FRAC del timeout; el
    # resto queda garantizado para piezas+ensamble.
    carto_deadline = t0 + timeout_s * 0.55

    # ── CARTOGRAFÍA (razonador; lazy-load-usar-cerrar) ──────────────────
    carto = None
    razonador = fleet_backend("qwen3_4b")
    if razonador is not None:
        try:
            prompt = build_prompt(
                CARTO_TMPL.format(spec=desc, entry=entry),
                system=CARTO_SYSTEM) + NOTHINK
            for temp in (0.0, 0.5, 0.9):
                if time.time() > carto_deadline:
                    break
                raw = razonador.generate(prompt, max_tokens=2400,
                                         temperature=temp, seed=77 + gens,
                                         cache_prompt=False) or ""
                gens += 1
                carto = _parse_carto(raw, entry)
                if carto and len(carto["spec_asserts"]) >= 4:
                    break
            if (not (carto and len(carto["spec_asserts"]) >= 4)
                    and time.time() <= carto_deadline):
                raw = razonador.generate(build_prompt(
                    ASSERTS_PLANO_TMPL.format(spec=desc, entry=entry),
                    system=CARTO_SYSTEM.replace(
                        "JSON object", "list of assert lines")) + NOTHINK,
                    max_tokens=1200, temperature=0.0, seed=91,
                    cache_prompt=False) or ""
                gens += 1
                planos = _extrae_asserts_planos(raw, entry)
                base = (carto or {}).get("spec_asserts", [])
                if len(planos) >= len(base):
                    carto = {"helpers": (carto or {}).get("helpers", []),
                             "spec_asserts": planos[:14]}
        finally:
            close_fleet_member("qwen3_4b")
    carto = carto or {"helpers": [], "spec_asserts": []}

    coder = fleet_backend("qwen35_4b")
    if coder is None:
        return None

    def gen(msg: str, temp: float, seed: int, max_tokens: int = 700) -> str:
        raw = coder.generate(build_prompt(msg, system=SYSTEM_PROMPT) + NOTHINK,
                             max_tokens=max_tokens, temperature=temp,
                             seed=seed, cache_prompt=False) or ""
        return extract_code(raw)

    try:
        # ── refuerzo-coder: si el oráculo del razonador quedó pobre, la
        # otra hifa extrae los suyos y se usa la UNIÓN (clave de NEWX3) ──
        if len(carto["spec_asserts"]) < 6:
            raw = coder.generate(build_prompt(
                ASSERTS_PLANO_TMPL.format(spec=desc, entry=entry),
                system=SYSTEM_PROMPT) + NOTHINK, max_tokens=1200,
                temperature=0.0, seed=93, cache_prompt=False) or ""
            gens += 1
            extra = _extrae_asserts_planos(raw, entry)
            carto["spec_asserts"] = list(dict.fromkeys(
                carto["spec_asserts"] + extra))[:20]
        # higiene determinista del oráculo (lección NEWX4/SPEC4)
        carto["spec_asserts"] = filtra_contradicciones(carto["spec_asserts"])
        if not carto["spec_asserts"]:
            return None     # sin oráculo no hay feromona que valga
        _detail(print_fn, f"Superorganismo: oráculo de "
                          f"{len(carto['spec_asserts'])} asserts, "
                          f"{len(carto['helpers'])} piezas...")

        # ── hormigas por pieza (acumulado: soporta recursión mutua) ─────
        piezas_ok, piezas_code = [], []
        for h in carto["helpers"]:
            if gens >= budget - 2 or time.time() - t0 > timeout_s:
                break
            mejor, mejor_n = "", -1
            objetivo = len(h["asserts"])
            for k in range(3):
                if gens >= budget - 2 or time.time() - t0 > timeout_s:
                    break
                code = gen(PIEZA_TMPL.format(
                    signature=h["signature"], contract=h["contract"],
                    asserts="\n".join(h["asserts"]) or "(no tests: follow "
                    "the contract exactly)"), 0.0 if k == 0 else 0.8,
                    200 + k)
                gens += 1
                acumulado = "\n\n".join(piezas_code + [code])
                n, _ = _run_asserts(acumulado, h["asserts"]) \
                    if h["asserts"] else (0, [])
                if n > mejor_n and f"def {h['name']}" in code:
                    mejor, mejor_n = code, n
                if objetivo and n == objetivo:
                    break
            if mejor:
                piezas_code.append(mejor)
                piezas_ok.append(f"{h['name']}: {mejor_n}/{objetivo}")
        helpers_code = "\n\n".join(piezas_code)
        firmas = "\n".join(h["signature"] + "  # " + h["contract"][:80]
                           for h in carto["helpers"]) or "(none)"

        # ── ensamble + feromona ─────────────────────────────────────────
        spec_a = carto["spec_asserts"]
        rastro, mejor_full, mejor_n = [], "", -1
        fallo = ""
        while gens < budget and time.time() - t0 <= timeout_s:
            if not rastro:
                entry_code = gen(ENSAMBLE_TMPL.format(
                    spec=desc, firmas=firmas, entry=entry), 0.0, 300)
            else:
                entry_code = gen(FEROMONA_TMPL.format(
                    spec=desc, firmas=firmas, rastro="\n".join(rastro[-6:]),
                    code=mejor_full, fallo=fallo, entry=entry),
                    0.6, 300 + gens)
            gens += 1
            full = (helpers_code + "\n\n" + entry_code).strip()
            n, fallos_k = _run_asserts(full, spec_a)
            if n > mejor_n and f"def {entry}" in full:
                mejor_full, mejor_n = full, n
            if n == len(spec_a):
                break
            fallo = "\n".join(f_[:200] for f_ in fallos_k[:8])
            rastro.append(f"- intento {len(rastro) + 1}: paso {n}/"
                          f"{len(spec_a)} spec-asserts; 1er fallo: "
                          f"{fallos_k[0][:160] if fallos_k else '?'}")
    finally:
        close_fleet_member("qwen35_4b")

    if not mejor_full or f"def {entry}" not in mejor_full:
        return None
    return {"code": mejor_full, "spec_pass": mejor_n,
            "spec_total": len(spec_a), "gens": gens, "piezas": piezas_ok,
            "secs": round(time.time() - t0, 1)}
