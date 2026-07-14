# -*- coding: utf-8 -*-
"""E-SUPERORGANISMO (PREREG_SUPERORGANISMO.md): la colonia muerde por pedazos.

Mecanismo: CARTOGRAFÍA (qwen3_4b descompone + extrae SPEC-ASSERTS del
enunciado) → HORMIGAS por pieza (qwen35_4b resuelve cada auxiliar contra su
micro-oráculo) → ENSAMBLE con FEROMONA (los fallos dejan rastro que el
siguiente intento lee). Presupuesto ≤16 generaciones/tarea (= pass@16
baseline, mismo modelo generador). Score SOLO contra tests ocultos.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_superorganismo [--smoke]
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT = REPO / "cognia_v3" / "eval" / "results_superorganismo_v2.json"
NOTHINK = "<think>\n\n</think>\n\n"
BUDGET = 16
# orden = prioridad (deadline 04:30): primero las más prometedoras
# (NEWX3 quedó a 1 assert en v1; SPEC1 tiene banda de varianza; NEWX*).
VIRGENES = ["NEWX3", "SPEC1", "NEWX2", "NEWX4", "NEWX5", "NEWD2", "ALG3",
            "LONG3", "LONG5", "SPEC2", "SPEC3", "LONG2", "SPEC4"]
SMOKE = ["ALG3", "SPEC2", "NEWX3", "LONG2"]

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


def _run_asserts(code: str, asserts: list, timeout: int = 10):
    """Corre code + cada assert por separado.
    Devuelve (n_pass, primer_fallo, fallos_lista)."""
    from cognia_v3.eval.benchmark_code import _sandbox_env
    passed, primer_fallo, fallos = 0, "", []
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
                primer_fallo = primer_fallo or fallos[-1]
        except subprocess.TimeoutExpired:
            fallos.append(f"{a}  ->  TIMEOUT")
            primer_fallo = primer_fallo or fallos[-1]
        except Exception as exc:
            fallos.append(f"{a}  ->  sandbox: {exc}")
            primer_fallo = primer_fallo or fallos[-1]
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
    return passed, primer_fallo, fallos


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


ASSERTS_PLANO_TMPL = """Problem statement:
{spec}

List EVERY test assertion that follows LITERALLY from the problem text: one
per line, each a Python `assert {entry}(...) == ...` (or `== -1`, etc.).
Cover EVERY concrete example mentioned in the text (every quoted input whose
output or validity is stated) and every explicit rule/forbidden case. Do not
invent cases whose answer is not stated or directly implied. Reply with ONLY
assert lines, no other text."""


def _carto_plano(b, t, seed_off: int = 0) -> dict | None:
    """Fallback sin JSON: pide solo asserts, uno por línea (para enunciados
    donde el cartógrafo nunca logra emitir el JSON completo)."""
    from cognia_v3.eval.benchmark_code import build_prompt
    prompt = build_prompt(
        ASSERTS_PLANO_TMPL.format(spec=t["prompt"], entry=t["entry_point"]),
        system=CARTO_SYSTEM.replace("JSON object", "list of assert lines")
    ) + NOTHINK
    raw = b.generate(prompt, max_tokens=1200,
                     temperature=0.0 if seed_off == 0 else 0.6,
                     seed=91 + seed_off, cache_prompt=False) or ""
    asserts = _valida_asserts(
        [ln.strip() for ln in raw.splitlines()], requiere=t["entry_point"])
    if len(asserts) < 4:
        return None
    return {"helpers": [], "spec_asserts": asserts[:14]}


def fase_cartografia(res: dict, tareas: dict, ids: list):
    """qwen3_4b mapea cada tarea (1-2 gens). Persistencia incremental."""
    from cognia_v3.eval.benchmark_code import build_prompt, extract_code  # noqa
    from node.fleet_registry import fleet_backend
    # re-intenta mapas vacíos/anémicos (<4 spec-asserts = extracción fallida,
    # p.ej. JSON truncado por max_tokens)
    pend = [t for t in ids
            if len((res["tareas"].setdefault(t, {}).get("carto") or {})
                   .get("spec_asserts", [])) < 4
            or t in res.get("reforzar", [])]
    if not pend:
        return
    b = fleet_backend("qwen3_4b")
    if b is None:
        raise RuntimeError("qwen3_4b no arranco")
    for tid in pend:
        t = tareas[tid]
        prompt = build_prompt(
            CARTO_TMPL.format(spec=t["prompt"], entry=t["entry_point"]),
            system=CARTO_SYSTEM) + NOTHINK
        gens = 0
        carto = None
        # offset por gens de corridas previas: sin él, el retry ENTRE
        # corridas repite seeds 77/78/79 exactas = re-fallo determinista
        # (mismo bug que el retry intra-corrida ya corrigió con temps).
        prev = res["tareas"][tid].get("gens", 0)
        # hasta 3 intentos con temperaturas VARIADAS (con seeds fijos el
        # retry repetía exactamente el mismo fallo de parseo). Las tareas
        # en "reforzar" ya tienen mapa: van directo al refuerzo plano.
        if tid not in res.get("reforzar", []):
            for temp in (0.0, 0.5, 0.9):
                raw = b.generate(prompt, max_tokens=2400, temperature=temp,
                                 seed=77 + prev + gens, cache_prompt=False) or ""
                gens += 1
                carto = _parse_carto(raw, t["entry_point"])
                if carto and len(carto["spec_asserts"]) >= 4:
                    break
        if (not (carto and len(carto["spec_asserts"]) >= 4)
                or tid in res.get("reforzar", [])):
            plano = _carto_plano(b, t, seed_off=prev)  # fallback/refuerzo sin JSON
            gens += 1
            if plano and len(plano["spec_asserts"]) >= len(
                    (carto or {}).get("spec_asserts", [])):
                carto = plano
        if tid in res.get("reforzar", []):
            res["reforzar"].remove(tid)
        viejo = res["tareas"][tid].get("carto") or {"helpers": [],
                                                    "spec_asserts": []}
        nuevo = carto or {"helpers": [], "spec_asserts": []}
        # UNIÓN entre corridas: más oráculo es estrictamente mejor
        # (lección NEWX3: 10 asserts buenos PERO faltaba el ejemplo "IC")
        union = list(dict.fromkeys(viejo["spec_asserts"]
                                   + nuevo["spec_asserts"]))[:20]
        res["tareas"][tid]["carto"] = {
            "helpers": nuevo["helpers"] or viejo["helpers"],
            "spec_asserts": union}
        res["tareas"][tid]["gens"] = gens
        n_h = len(carto["helpers"]) if carto else 0
        n_a = len(carto["spec_asserts"]) if carto else 0
        print(f"[{tid}] carto: {n_h} helpers, {n_a} spec-asserts "
              f"({gens} gens){' — SIN MAPA' if not carto else ''}", flush=True)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")


def fase_colonia(res: dict, tareas: dict, ids: list):
    """qwen35_4b: hormigas por pieza + ensamble con feromona + score oculto."""
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code, run_task_tests)
    from node.fleet_registry import fleet_backend
    pend = [t for t in ids if "final" not in res["tareas"].get(t, {})]
    if not pend:
        return
    b = fleet_backend("qwen35_4b")
    if b is None:
        raise RuntimeError("qwen35_4b no arranco")

    def gen(msg: str, temp: float, seed: int) -> str:
        raw = b.generate(build_prompt(msg, system=SYSTEM_PROMPT) + NOTHINK,
                         max_tokens=700, temperature=temp, seed=seed,
                         cache_prompt=False) or ""
        return extract_code(raw)

    for tid in pend:
        t, r = tareas[tid], res["tareas"][tid]
        carto = r["carto"]
        gens = r.get("gens", 0)
        t0 = time.time()

        # refuerzo por el CODER: cuando el cartógrafo-razonador no logra
        # extraer asserts de este enunciado, otra hifa toma el relevo
        if tid in res.get("reforzar_coder", []):
            raw = b.generate(build_prompt(ASSERTS_PLANO_TMPL.format(
                spec=t["prompt"], entry=t["entry_point"]),
                system=SYSTEM_PROMPT) + NOTHINK, max_tokens=1200,
                temperature=0.0, seed=93, cache_prompt=False) or ""
            gens += 1
            extra = _valida_asserts([ln.strip() for ln in raw.splitlines()],
                                    requiere=t["entry_point"])
            union = list(dict.fromkeys(carto["spec_asserts"] + extra))[:20]
            print(f"[{tid}] refuerzo-coder: +{len(union) - len(carto['spec_asserts'])} asserts "
                  f"(total {len(union)})", flush=True)
            carto = {"helpers": carto["helpers"], "spec_asserts": union}
            r["carto"] = carto
            res["reforzar_coder"].remove(tid)

        # --- hormigas por pieza: cada helper contra su micro-oráculo ---
        piezas_ok, piezas_code = [], []
        for h in carto["helpers"]:
            if gens >= BUDGET - 2:             # reservar ensamble
                break
            mejor, mejor_n = "", -1
            objetivo = len(h["asserts"])
            for k in range(3):
                if gens >= BUDGET - 2:
                    break
                code = gen(PIEZA_TMPL.format(
                    signature=h["signature"], contract=h["contract"],
                    asserts="\n".join(h["asserts"]) or "(no tests: follow "
                    "the contract exactly)"), 0.0 if k == 0 else 0.8,
                    200 + k)
                gens += 1
                # evaluar sobre el ACUMULADO: soporta helpers mutuamente
                # recursivos (lección ALG3 v1)
                acumulado = "\n\n".join(piezas_code + [code])
                n, _, _ = _run_asserts(acumulado, h["asserts"]) \
                    if h["asserts"] else (0, "", [])
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

        # --- ensamble + feromona ---
        spec_a = carto["spec_asserts"]
        rastro, mejor_full, mejor_n = [], "", -1
        fallo = ""
        while gens < BUDGET:
            if not rastro:
                entry_code = gen(ENSAMBLE_TMPL.format(
                    spec=t["prompt"], firmas=firmas,
                    entry=t["entry_point"]), 0.0, 300)
            else:
                entry_code = gen(FEROMONA_TMPL.format(
                    spec=t["prompt"], firmas=firmas,
                    rastro="\n".join(rastro[-6:]), code=mejor_full,
                    fallo=fallo, entry=t["entry_point"]),
                    0.6, 300 + gens)
            gens += 1
            full = (helpers_code + "\n\n" + entry_code).strip()
            n, _, fallos_k = _run_asserts(full, spec_a)
            if n > mejor_n:
                mejor_full, mejor_n = full, n
            if n == len(spec_a):
                break
            # feromona v2: TODOS los asserts que fallan (no solo el primero)
            fallo = "\n".join(f_[:200] for f_ in fallos_k[:8])
            rastro.append(f"- intento {len(rastro) + 1}: paso {n}/"
                          f"{len(spec_a)} spec-asserts; 1er fallo: "
                          f"{fallos_k[0][:160] if fallos_k else '?'}")

        # --- score contra ocultos (el único veredicto) ---
        ok, et, _ = run_task_tests(mejor_full, t["tests"], t["entry_point"])
        r.update({
            "gens": gens, "piezas": piezas_ok,
            "spec_asserts_pasados": [mejor_n, len(spec_a)],
            "intentos_ensamble": len(rastro) + 1,
            "oculto": {"passed": bool(ok), "err": et},
            "secs": round(time.time() - t0, 1),
            "final": bool(ok),
        })
        r["code"] = mejor_full[-4000:]
        print(f"[{tid}] piezas [{', '.join(piezas_ok) or '-'}] | spec "
              f"{mejor_n}/{len(spec_a)} | OCULTO: "
              f"{'**PASS**' if ok else 'fail:' + et} | {gens} gens "
              f"{r['secs']}s", flush=True)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ.setdefault("COGNIA_FLEET_RAM_GB", "6")
    ids = SMOKE if "--smoke" in sys.argv else VIRGENES
    from node.fleet_registry import close_fleet30
    tareas = {json.loads(l)["id"]: json.loads(l) for l in
              open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                   encoding="utf-8") if l.strip()}
    res = {"prereg": "PREREG_SUPERORGANISMO v2 (autopsia smoke v1)",
           "budget": BUDGET,
           "cartografo": "qwen3_4b", "coder": "qwen35_4b", "tareas": {}}
    if OUT.is_file():
        res = json.loads(OUT.read_text(encoding="utf-8"))
    try:
        fase_cartografia(res, tareas, ids)
        fase_colonia(res, tareas, ids)
    finally:
        close_fleet30()
    hechos = [t for t in ids if "final" in res["tareas"].get(t, {})]
    ganadas = [t for t in hechos if res["tareas"][t]["final"]]
    res["veredicto"] = {"n": len(hechos), "ganadas": [len(ganadas), ganadas],
                        "baseline": "0 (virgenes por definicion; ALG3 0/8 "
                                    "pass@16)"}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"\nVEREDICTO parcial: {len(ganadas)}/{len(hechos)} vírgenes "
          f"resueltas por el superorganismo: {ganadas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
