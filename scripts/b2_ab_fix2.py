"""
b2_ab_fix2.py — A/B de confirmación del fix del prompt (DÉCIMA ENMIENDA de
PREREG_BON_RONDAS_20260726.md): sistema COMPLETO (lazo real) sobre el banco
brutal, brazos INTERCALADOS a nivel tarea en la misma corrida.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_ab_fix2.py
        [--replicas 6] [--reanudar]

  off  el sistema tal cual está en main (fix de la octava enmienda incluido)
  on   además COGNIA_PROMPT_FIX2=1: troceo por FRASES + números EXACTOS en
       ideas interactivas

Veredicto pre-registrado sobre PARES APAREADOS por celda (tarea, réplica):
ON gana ≥3 celdas netas = el fix cobra; 1-2 = dudoso; ≤0 = no cobra. La
referencia 12/24 de anoche NO entra (deriva entre noches medida: ~2 celdas).
La corrida es reanudable: si el aterrizaje la corta, se reporta el n
alcanzado como PARCIAL y se retoma con --reanudar.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
HELDOUT = RAIZ / "scripts" / "b1_contratos_heldout.json"
SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
          / "b2_ab_fix2")
BRAZOS = ["off", "on"]


def _cargar_b2():
    spec = importlib.util.spec_from_file_location(
        "b2_sistema_real", RAIZ / "scripts" / "b2_sistema_real.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    replicas = (int(argv[argv.index("--replicas") + 1])
                if "--replicas" in argv else 6)
    reanudar = "--reanudar" in argv
    # Flags residuales del shell cambiarian el sistema medido sin dejar
    # rastro (revision 2026-07-27); CONSTRUCTOR_URL ya lo popea correr_sistema.
    os.environ.pop("COGNIA_IDEA_PELADA", None)
    b2 = _cargar_b2()
    # La telemetria del A/B no debe sesgar el contador de salud de produccion.
    from cognia.program_creator import diseno_a_codigo
    diseno_a_codigo.RUTA_TELEMETRIA = SALIDA / "telemetria_sellos.jsonl"

    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    heldout = {t["id"]: t["contrato"]
               for t in json.loads(HELDOUT.read_text(encoding="utf-8"))["tareas"]}
    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    if fichero_res.is_file() and not reanudar:
        sys.exit(f"existe {fichero_res}: usa --reanudar o borralo (correr sin "
                 f"el flag lo SOBRESCRIBIRIA en silencio)")
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"celdas": []})
    hechas = {(c["tarea"], c["brazo"], c["rep"]) for c in res["celdas"]}

    print(f"A/B FIX2 — sistema completo x banco brutal, INTERCALADO\n"
          f"config: brazos={BRAZOS}, replicas={replicas}, "
          f"fix2=COGNIA_PROMPT_FIX2 por celda, contrato interno CLASICO, "
          f"reanudar={reanudar} (hechas: {len(hechas)})\n", flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    for rep in range(1, replicas + 1):
        for i_t, t in enumerate(tareas):
            orden = BRAZOS if (rep + i_t) % 2 == 0 else BRAZOS[::-1]
            for brazo in orden:
                if (t["id"], brazo, rep) in hechas:
                    continue
                if brazo == "on":
                    os.environ["COGNIA_PROMPT_FIX2"] = "1"
                else:
                    os.environ.pop("COGNIA_PROMPT_FIX2", None)
                # ON y OFF del mismo par sacan el MISMO extra_hint de
                # generate_program (random.choice global): menos varianza
                # apareada sin tocar produccion.
                random.seed(f"{t['id']}:{rep}")
                d = SALIDA / f"{t['id']}__{brazo}__r{rep}"
                d.mkdir(parents=True, exist_ok=True)
                print(f"  r{rep} {t['id']:<14} {brazo:<4} ...", flush=True)
                try:
                    html, segs, como, meta = b2.correr_sistema(t["idea"], d)
                except Exception as exc:
                    html, segs, como, meta = (None, 0.0,
                                              f"EXCEPCION {exc}"[:80], {})
                celda = {"tarea": t["id"], "brazo": brazo, "rep": rep,
                         "segundos": round(segs, 1), "como": como[:90], **meta}
                if not html:
                    celda.update(aprobado=False, motivo="sin HTML")
                else:
                    (d / "index.html").write_text(html, encoding="utf-8")
                    try:
                        v = juez_ejecutable.juzgar_web(d / "index.html",
                                                       t["contrato"])
                        celda.update(
                            aprobado=v.aprobado, motivo=v.motivo[:100],
                            checks_ok=sum(1 for c in v.checks if c.ok),
                            checks=len(v.checks))
                        if v.aprobado and t["id"] in heldout:
                            vh = juez_ejecutable.juzgar_web(
                                d / "index.html", heldout[t["id"]])
                            celda["aprobado_heldout"] = vh.aprobado
                    except Exception as exc:
                        celda.update(aprobado=False,
                                     motivo=f"juez crasheo: {exc}"[:100])
                res["celdas"].append(celda)
                _guardar()
                print(f"       -> {'APROBADO' if celda['aprobado'] else 'FALLIDO'}"
                      f" ({celda.get('checks_ok', '?')}/"
                      f"{celda.get('checks', '?')}, {segs:.0f}s, "
                      f"sello={celda.get('sello_lazo')})", flush=True)
    os.environ.pop("COGNIA_PROMPT_FIX2", None)

    # ── resumen apareado ─────────────────────────────────────────────────
    von = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
           for c in res["celdas"] if c["brazo"] == "on"}
    voff = {(c["tarea"], c["rep"]): bool(c.get("aprobado"))
            for c in res["celdas"] if c["brazo"] == "off"}
    comunes = sorted(set(von) & set(voff))
    gana_on = [k for k in comunes if von[k] and not voff[k]]
    gana_off = [k for k in comunes if voff[k] and not von[k]]
    ap_on = sum(1 for c in res["celdas"]
                if c["brazo"] == "on" and c.get("aprobado"))
    n_on = sum(1 for c in res["celdas"] if c["brazo"] == "on")
    ap_off = sum(1 for c in res["celdas"]
                 if c["brazo"] == "off" and c.get("aprobado"))
    n_off = sum(1 for c in res["celdas"] if c["brazo"] == "off")
    print(f"\n{'=' * 70}")
    print(f"  A/B FIX2 (apareado, {len(comunes)} pares): "
          f"ON {ap_on}/{n_on}  OFF {ap_off}/{n_off}")
    print(f"  ON gana:  {len(gana_on)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_on) or '—'})")
    print(f"  OFF gana: {len(gana_off)}  "
          f"({', '.join(f'{t}:r{r}' for t, r in gana_off) or '—'})")
    print(f"  NETO ON: {len(gana_on) - len(gana_off)}  "
          f"(veredicto prereg: >=3 cobra, 1-2 dudoso, <=0 no cobra)")
    print(f"{'=' * 70}")
    res["resumen"] = {"on": f"{ap_on}/{n_on}", "off": f"{ap_off}/{n_off}",
                      "pares": len(comunes),
                      "gana_on": [f"{t}:r{r}" for t, r in gana_on],
                      "gana_off": [f"{t}:r{r}" for t, r in gana_off],
                      "neto_on": len(gana_on) - len(gana_off)}
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
