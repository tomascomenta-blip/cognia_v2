"""
b2_ab_contrato.py — A/B del contrato interno: clásico (≤8 pasos) vs amplio
(10-16 pasos, CodeRM). PREREG_CONTRATO_AMPLIO_20260727.md: leerlo ANTES.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_ab_contrato.py
        [--brazos crudo,full] [--modos clasico,amplio] [--reanudar]

Con --modos distinto del default la salida va a un directorio propio
(b2_ab_contrato_<modos>) para no pisar corridas previas: el brazo clásico se
RE-genera en cada corrida como control concurrente ([[gate-e2e-flaky]]).

Corpus: las páginas de b2_sonda_prompt (cada una con veredicto del BANCO ya
registrado en su resultados.json). Por página se generan DOS contratos
internos (mismo pensador, effort=low, mismo server; modos intercalados con
orden rotado por página), se juzga la página con cada uno y se compara el
veredicto interno contra el del banco:

  FP = interno aprueba ∧ banco reprueba   (el examen deja pasar basura)
  FN = interno reprueba ∧ banco aprueba   (el examen acusa productos sanos)

La generación del contrato usa el inventario del DOM de cada página, como en
producción. Cero generación de páginas: solo contratos (GPU liviana) + juez
(CPU/Chromium).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas_brutales.json"
SONDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
         / "b2_sonda_prompt")
MODOS_DEFECTO = ["clasico", "amplio"]


def main(argv: list) -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.program_creator import juez_ejecutable

    global MODOS, SALIDA
    brazos = (argv[argv.index("--brazos") + 1].split(",")
              if "--brazos" in argv else ["crudo", "full"])
    MODOS = (argv[argv.index("--modos") + 1].split(",")
             if "--modos" in argv else MODOS_DEFECTO)
    sufijo = "" if MODOS == MODOS_DEFECTO else "_" + "-".join(MODOS)
    SALIDA = (RAIZ / "cognia" / "program_creator" / "generated_programs"
              / f"b2_ab_contrato{sufijo}")
    reanudar = "--reanudar" in argv

    ideas = {t["id"]: t["idea"]
             for t in json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]}
    sonda = json.loads((SONDA / "resultados.json").read_text(encoding="utf-8"))
    paginas = []
    for c in sonda["celdas"]:
        if c["brazo"] not in brazos or "aprobado" not in c:
            continue
        d = SONDA / f"{c['tarea']}__{c['brazo']}__r{c['rep']}"
        if (d / "index.html").is_file():
            paginas.append({"tarea": c["tarea"], "brazo": c["brazo"],
                            "rep": c["rep"], "dir": d,
                            "banco": bool(c["aprobado"])})
    if not paginas:
        sys.exit("no hay páginas de la sonda con veredicto en disco")
    # Las páginas que el banco REPRUEBA van primero: son las únicas que miden
    # FP y son pocas (5 de 24 en crudo+full). Bajo un corte de tiempo, el
    # orden decide QUÉ se mide, no CÓMO (el apareado por página no se sesga).
    paginas.sort(key=lambda p: p["banco"])

    SALIDA.mkdir(parents=True, exist_ok=True)
    fichero_res = SALIDA / "resultados.json"
    res: dict = (json.loads(fichero_res.read_text(encoding="utf-8"))
                 if reanudar and fichero_res.is_file() else {"filas": []})
    hechas = {(f["tarea"], f["brazo"], f["rep"], f["modo"])
              for f in res["filas"]}

    print(f"A/B CONTRATO — {len(paginas)} páginas x {len(MODOS)} modos "
          f"(brazos={brazos}); banco aprueba "
          f"{sum(1 for p in paginas if p['banco'])}/{len(paginas)}\n",
          flush=True)

    def _guardar():
        tmp = fichero_res.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero_res)

    for i, p in enumerate(paginas):
        orden = MODOS if i % 2 == 0 else MODOS[::-1]
        for modo in orden:
            clave = (p["tarea"], p["brazo"], p["rep"], modo)
            if clave in hechas:
                continue
            fila = {"tarea": p["tarea"], "brazo": p["brazo"], "rep": p["rep"],
                    "modo": modo, "banco": p["banco"]}
            html = p["dir"] / "index.html"
            t0 = time.time()
            contrato = None
            for _ in (1, 2):        # un reintento: cola de pensamiento
                contrato = juez_ejecutable.generar_contrato(
                    ideas[p["tarea"]], html, modo=modo)
                if contrato:
                    break
            fila["segundos_contrato"] = round(time.time() - t0, 1)
            if not contrato:
                fila["interno"] = None
                fila["motivo"] = "sin contrato (2 intentos)"
                res["filas"].append(fila)
                _guardar()
                print(f"  {p['tarea']:<14} {p['brazo']:<7} r{p['rep']} "
                      f"{modo:<8} SIN CONTRATO", flush=True)
                continue
            # En SALIDA, no junto a la página: una re-corrida no debe pisar
            # los contratos de corridas previas (el corpus de análisis de
            # b2_fn_por_tipo.py son esos archivos).
            (SALIDA / f"{p['tarea']}__{p['brazo']}__r{p['rep']}"
                      f"__contrato_{modo}.json").write_text(
                json.dumps(contrato, indent=2, ensure_ascii=False),
                encoding="utf-8")
            fila["pasos"] = len(contrato.get("pasos", []))
            fila["criticos"] = sum(
                1 for paso in contrato.get("pasos", [])
                if isinstance(paso, dict) and paso.get("critico"))
            try:
                v = juez_ejecutable.juzgar_web(html, contrato)
                fila["interno"] = bool(v.aprobado)
                fila["checks_ok"] = sum(1 for c in v.checks if c.ok)
                fila["checks"] = len(v.checks)
            except Exception as exc:
                fila["interno"] = None
                fila["motivo"] = f"juez crasheo: {exc}"[:100]
            res["filas"].append(fila)
            _guardar()
            marca = {True: "APRUEBA", False: "reprueba", None: "?"}[fila["interno"]]
            print(f"  {p['tarea']:<14} {p['brazo']:<7} r{p['rep']} {modo:<8} "
                  f"interno {marca:<9} banco "
                  f"{'APRUEBA' if p['banco'] else 'reprueba'}  "
                  f"({fila.get('pasos', '?')} pasos)", flush=True)

    # ── resumen ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"{'MODO':<9}{'n':>4}{'FP':>16}{'FN':>16}{'sin contrato':>14}"
          f"{'pasos (med)':>12}")
    print("-" * 72)
    resumen = {}
    for modo in MODOS:
        fs = [f for f in res["filas"] if f["modo"] == modo]
        con = [f for f in fs if f["interno"] is not None]
        ap_int = [f for f in con if f["interno"]]
        no_int = [f for f in con if not f["interno"]]
        fp = sum(1 for f in ap_int if not f["banco"])
        fn = sum(1 for f in no_int if f["banco"])
        pasos = sorted(f["pasos"] for f in fs if f.get("pasos"))
        criticos = sorted(f["criticos"] for f in fs if "criticos" in f)
        resumen[modo] = {
            "n": len(con), "sin_contrato": len(fs) - len(con),
            "fp": f"{fp}/{len(ap_int)}", "fn": f"{fn}/{len(no_int)}",
            "pasos_mediana": pasos[len(pasos) // 2] if pasos else None,
            # distribución de criticidad por brazo (M1 de la enmienda del
            # prereg SEÑAL: si difiere fuerte entre modos, el veredicto no
            # es atribuible solo a los fixes F1-F2)
            "criticos_mediana": (criticos[len(criticos) // 2]
                                 if criticos else None),
            "sin_criticos": sum(1 for c in criticos if c == 0)}
        print(f"{modo:<9}{len(con):>4}"
              f"{f'{fp}/{len(ap_int)} de aprob.':>16}"
              f"{f'{fn}/{len(no_int)} de rech.':>16}"
              f"{len(fs) - len(con):>14}"
              f"{(pasos[len(pasos) // 2] if pasos else 0):>12}")
    res["resumen"] = resumen
    _guardar()
    print(f"\nJSON: {fichero_res}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
