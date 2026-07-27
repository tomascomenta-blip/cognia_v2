"""
b2_sonda_prompt.py — atribución de los ~25 pts entre crudo (75%) y sistema
con fix (50%) en el banco brutal. NOVENA ENMIENDA (revisada) de
PREREG_BON_RONDAS_20260726.md: leerla ANTES de tocar este script.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_sonda_prompt.py
        [--n 3] [--brazos crudo,base,basereq,full] [--reanudar]

ESCALERA ANIDADA de 4 brazos DIRECTOS (sin lazo), generación a temp 0.2 por
_preguntar_constructor contra :8080 SIN fallback (el fallback de _call_llm
puede caer a otro backend/temperatura y envenenar celdas en silencio —
hallazgo de la revisión de 2 agentes del 2026-07-27), intercalados a nivel
tarea, orden de brazos rotado por celda:

  crudo    la idea pelada (control de deriva concurrente)
  base     _build_prompt_web SIN bloque REQUIRED, SIN extra_hint, SIN
           patrones (aísla: reglas fijas + formato Title/Description)
  basereq  base + el bloque REQUIRED troceado (aísla: el troceo)
  full     basereq + hint de COMPLEXITY_HINTS (semilla por celda) +
           PROVEN PATTERNS (aísla: el PAR hint+patrones)

Cada par adyacente difiere en UNA variable. El HTML sale de la MISMA cadena
para todos los brazos: _parse_response (lo que exige generate_program) y
fence de rescate si falla; parse_estricto_ok se registra por celda (en el
brazo crudo es N/A: su prompt no pide formato).
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_sonda_prompt")
URL = "http://127.0.0.1:8080"

BRAZOS_DEFECTO = ["crudo", "base", "basereq", "full"]

# Copias VERBATIM de generate_program / _build_prompt_web (generator.py).
# El prereg prohíbe tocar generator.py antes de la atribución; main() ABORTA
# si estas cadenas dejan de aparecer literales en el fuente (anti-deriva).
_CABECERA_PATRONES = (
    "\n\nPROVEN PATTERNS from pages that already passed browser "
    "checks and professional review. ADAPT their techniques to "
    "this idea — do NOT copy them verbatim; change data, labels, "
    "colors and layout to fit:\n")
_LINEA_CIERRE_REQ = (
    "- Implement EVERY required component above — a page that skips "
    "any of them is WRONG. Prefer a LONGER page over an incomplete "
    "one; there is no size limit.\n")


def _construir_prompt(brazo: str, idea: str, rep: int) -> tuple[str, dict]:
    """El prompt del brazo + meta de atribución. Determinista por celda."""
    from cognia.program_creator import generator
    from cognia.program_creator.patrones import elegir_patrones

    if brazo == "crudo":
        return idea, {}

    meta: dict = {}
    if brazo == "full":
        # Semilla POR CELDA: el hint queda apareado entre corridas y la
        # corrida es reproducible (revisión: sortear por brazo contaminaba
        # el contraste con una lotería de 7 hints del tamaño del efecto).
        rng = random.Random(f"{idea[:40]}-{rep}")
        hint = rng.choice(generator.COMPLEXITY_HINTS)
        pats = elegir_patrones(idea, max_n=3)
        extra = hint
        if pats:
            extra += _CABECERA_PATRONES + "\n".join(
                f"--- {n} ---\n{c}" for n, c in pats)
        meta = {"hint": hint, "patrones": [n for n, _ in pats]}
    else:
        extra = ""

    if brazo == "base":
        original = generator._componentes_de_idea
        generator._componentes_de_idea = lambda category: []
        try:
            prompt = generator._build_prompt_web(idea, extra)
        finally:
            generator._componentes_de_idea = original
        # Sin lista REQUIRED, la línea de cierre queda apuntando a nada:
        # se quita también (revisión: confound leve del brazo).
        assert _LINEA_CIERRE_REQ in prompt, \
            "generator._build_prompt_web cambió: actualizar _LINEA_CIERRE_REQ"
        prompt = prompt.replace(_LINEA_CIERRE_REQ, "")
    else:
        prompt = generator._build_prompt_web(idea, extra)

    if brazo in ("base", "basereq"):
        # extra_hint vacío deja un bullet huérfano "- \n\n": fuera.
        prompt = prompt.replace("- \n\nRespond EXACTLY", "Respond EXACTLY")
        assert "- \n" not in prompt, "bullet huérfano sin limpiar"
    return prompt, meta


def _extraer_html(crudo: str, idea: str) -> tuple[str | None, bool]:
    """(html, parse_estricto_ok) — la cadena real del sistema + rescate."""
    from cognia.program_creator.generator import _parse_response
    html = None
    estricto = False
    try:
        prog = _parse_response(crudo, idea, "html")
        html = getattr(prog, "code", None) or getattr(prog, "codigo", None)
        estricto = bool(html)
    except Exception:
        pass
    if not html and "```" in crudo:
        trozo = crudo.split("```")[1].lstrip()
        if trozo[:4].lower() == "html":
            trozo = trozo[4:]
        html = trozo
    return (html if html and "<" in html else None), estricto


def _generar(prompt: str) -> tuple[str | None, float, int]:
    """(respuesta, segundos, intentos) por el constructor de :8080, SIN
    fallback. Un reintento: la cola de pensamiento es estocástica
    ([[presupuesto-tokens-razonamiento]])."""
    from cognia.program_creator.generator import (_SISTEMA_WEB,
                                                 _preguntar_constructor)
    t0 = time.time()
    for intento in (1, 2):
        crudo = _preguntar_constructor(URL, prompt, _SISTEMA_WEB, 0.2)
        if crudo:
            return crudo, time.time() - t0, intento
    return None, time.time() - t0, 2


def _verificar_copias_verbatim() -> None:
    fuente = (RAIZ / "cognia" / "program_creator" / "generator.py"
              ).read_text(encoding="utf-8")
    # En el fuente están partidas en literales adyacentes: comparar contra
    # el prompt CONSTRUIDO, no contra el texto del .py. Se construye uno.
    from cognia.program_creator import generator
    prueba = generator._build_prompt_web("idea de prueba con click", "HINTX")
    if _LINEA_CIERRE_REQ not in prueba or "- HINTX\n" not in prueba:
        sys.exit("generator._build_prompt_web ya no coincide con las copias "
                 "verbatim de este script: actualizar antes de correr")
    # La cabecera de patrones vive en generate_program; chequeo laxo sobre
    # el fuente (los literales están partidos línea a línea).
    if "PROVEN PATTERNS from pages that already passed browser" not in fuente:
        sys.exit("la cabecera PROVEN PATTERNS ya no está en generator.py: "
                 "actualizar _CABECERA_PATRONES antes de correr")


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 3
    brazos = (argv[argv.index("--brazos") + 1].split(",")
              if "--brazos" in argv else list(BRAZOS_DEFECTO))
    desconocidos = set(brazos) - set(BRAZOS_DEFECTO)
    if desconocidos:
        sys.exit(f"brazos desconocidos: {sorted(desconocidos)} "
                 f"(válidos: {BRAZOS_DEFECTO})")
    reanudar = "--reanudar" in argv
    _verificar_copias_verbatim()

    datos = json.loads(TAREAS.read_text(encoding="utf-8"))
    tareas = datos["tareas"]
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"celdas": []})
    # Reanudar = saltar SOLO celdas registradas en el JSON. No se reusa
    # index.html suelto de otra corrida (revisión: mezcla de noches).
    hechas = {(c["tarea"], c["brazo"], c["rep"]) for c in res["celdas"]}

    print(f"SONDA DEL PROMPT — {len(tareas)} tareas x {len(brazos)} brazos "
          f"x n={n} = {len(tareas) * len(brazos) * n} generaciones, "
          f"INTERCALADAS a nivel tarea", flush=True)
    print(f"config: brazos={brazos}, n={n}, temp=0.2, backend={URL} "
          f"(directo, sin fallback), reanudar={reanudar}\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    def _aprobados(brazo: str) -> tuple[int, int]:
        cs = [c for c in res["celdas"] if c["brazo"] == brazo]
        return sum(1 for c in cs if c.get("aprobado")), len(cs)

    for rep in range(1, n + 1):
        for i_t, t in enumerate(tareas):
            corte = (rep + i_t) % len(brazos)
            orden = brazos[corte:] + brazos[:corte]
            for brazo in orden:
                if (t["id"], brazo, rep) in hechas:
                    continue
                d = SALIDA / f"{t['id']}__{brazo}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)

                prompt, meta = _construir_prompt(brazo, t["idea"], rep)
                (d / "prompt.txt").write_text(prompt, encoding="utf-8")
                celda = {"tarea": t["id"], "brazo": brazo, "rep": rep, **meta}
                crudo_txt, segs, intentos = _generar(prompt)
                celda["segundos"] = round(segs, 1)
                celda["intentos"] = intentos

                html = None
                if crudo_txt:
                    (d / "respuesta.txt").write_text(crudo_txt,
                                                     encoding="utf-8")
                    html, estricto = _extraer_html(crudo_txt, t["idea"])
                    if brazo != "crudo":     # en crudo el formato no se pide
                        celda["parse_estricto_ok"] = estricto
                if not html:
                    celda.update(aprobado=False,
                                 motivo=("constructor no respondio"
                                         if not crudo_txt else "sin HTML"))
                    res["celdas"].append(celda)
                    _guardar()
                    print(f"  r{rep} {t['id']:<14} {brazo:<8} "
                          f"{celda['motivo'].upper()} ({segs:.0f}s)",
                          flush=True)
                    continue
                (d / "index.html").write_text(html, encoding="utf-8")

                try:
                    v = juez_ejecutable.juzgar_web(d / "index.html",
                                                   t["contrato"])
                except Exception as exc:
                    celda.update(aprobado=False,
                                 motivo=f"juez crasheo: {exc}"[:100])
                    res["celdas"].append(celda)
                    _guardar()
                    print(f"  r{rep} {t['id']:<14} {brazo:<8} JUEZ CRASHEO",
                          flush=True)
                    continue
                celda.update(aprobado=v.aprobado, motivo=v.motivo[:100],
                             checks_ok=sum(1 for c in v.checks if c.ok),
                             checks=len(v.checks))
                if v.aprobado and t["id"] in heldout:
                    try:
                        vh = juez_ejecutable.juzgar_web(d / "index.html",
                                                        heldout[t["id"]])
                        celda["aprobado_heldout"] = vh.aprobado
                    except Exception:
                        pass
                res["celdas"].append(celda)
                _guardar()
                print(f"  r{rep} {t['id']:<14} {brazo:<8} "
                      f"{'APROBADO' if v.aprobado else 'FALLIDO '} "
                      f"({celda['checks_ok']}/{celda['checks']}, {segs:.0f}s)"
                      + ("  [held-out FALLA]"
                         if celda.get("aprobado_heldout") is False else ""),
                      flush=True)

        # Parada por deriva (pre-registrada): si el crudo YA no puede superar
        # 5/12 ni aprobando todo lo que le queda, el server derivó — abortar
        # y sondear finish_reason/usage antes de leer nada.
        if "crudo" in brazos:
            ap, tot = _aprobados("crudo")
            restantes = (n - rep) * len(tareas)
            if ap + restantes <= 5 and tot + restantes >= 12:
                print(f"\nDERIVA: crudo {ap}/{tot} tras la réplica {rep} — "
                      f"imposible superar 5/12. ABORTO la atribución.",
                      flush=True)
                _guardar()
                return 3

    # ── resumen por brazo ────────────────────────────────────────────────
    print(f"\n{'=' * 76}")
    print(f"{'BRAZO':<9}{'aprobados':>10}{'held-out ok':>12}"
          f"{'parse estricto':>16}{'seg/gen':>9}   por tarea")
    print("-" * 76)
    resumen = {}
    for brazo in brazos:
        cs = [c for c in res["celdas"] if c["brazo"] == brazo]
        ap = sum(1 for c in cs if c.get("aprobado"))
        ho = sum(1 for c in cs
                 if c.get("aprobado") and c.get("aprobado_heldout", True))
        pe = [c for c in cs if "parse_estricto_ok" in c]
        pe_ok = sum(1 for c in pe if c["parse_estricto_ok"])
        segs = [c["segundos"] for c in cs if c.get("segundos")]
        por_tarea = {t["id"]: sum(1 for c in cs if c["tarea"] == t["id"]
                                  and c.get("aprobado")) for t in tareas}
        resumen[brazo] = {"aprobados": ap, "n": len(cs), "heldout_ok": ho,
                          "parse_estricto": (f"{pe_ok}/{len(pe)}" if pe
                                             else "N/A"),
                          "por_tarea": por_tarea}
        print(f"{brazo:<9}{f'{ap}/{len(cs)}':>10}{f'{ho}/{len(cs)}':>12}"
              f"{(f'{pe_ok}/{len(pe)}' if pe else 'N/A'):>16}"
              f"{(sum(segs) / len(segs) if segs else 0):>9.0f}   "
              + " ".join(f"{k}:{v}" for k, v in por_tarea.items()))

    # Análisis APAREADO por celda (lectura primaria pre-registrada): pares
    # discordantes entre brazos adyacentes de la escalera.
    print(f"\nPARES DISCORDANTES por celda (tarea, rep) — escalera:")
    escalera = [b for b in ["crudo", "base", "basereq", "full"] if b in brazos]
    pares_disc = {}
    for a, b in zip(escalera, escalera[1:]):
        va = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
              for c in res["celdas"] if c["brazo"] == a}
        vb = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
              for c in res["celdas"] if c["brazo"] == b}
        comunes = sorted(set(va) & set(vb))
        gana_a = [k for k in comunes if va[k] and not vb[k]]
        gana_b = [k for k in comunes if vb[k] and not va[k]]
        pares_disc[f"{a}->{b}"] = {
            "gana_" + a: [f"{t}:r{r}" for t, r in gana_a],
            "gana_" + b: [f"{t}:r{r}" for t, r in gana_b]}
        print(f"  {a:>8} vs {b:<8}: {a} gana {len(gana_a)} "
              f"({', '.join(f'{t}:r{r}' for t, r in gana_a) or '—'}) | "
              f"{b} gana {len(gana_b)} "
              f"({', '.join(f'{t}:r{r}' for t, r in gana_b) or '—'})")
    res["resumen"] = resumen
    res["pares_discordantes"] = pares_disc
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
