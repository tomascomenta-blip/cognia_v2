#!/usr/bin/env python
"""
b2_medoide.py — consenso conductual por CENTRALIDAD en vez de por mayoría.

PREREG_MEDOIDE_20260730.md. Cero GPU: reusa las sondas ya escritas.

POR QUÉ. El consenso conductual dio +2 (17/24 -> 19/24, pierde 0) y su
diagnóstico MEDIDO no fue "elige mal" sino que **en 13 de 24 ensayos las 4
muestras dan 4 firmas distintas**: no hay mayoría que formar y la regla cae al
control. El medoide sustituye mayoría por centralidad — la muestra cuya firma
está más cerca del resto — que existe siempre, aunque no haya dos iguales.

La pieza que faltaba era de INSTRUMENTACIÓN, no de idea: el runner original
guardaba el HASH de la firma, que solo dice igual/distinto. Para medir
distancia hace falta la trayectoria completa, y `_firma` ya la devuelve: solo
había que no tirarla.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402
import b2_consenso_conductual as cc                                       # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
FUENTE = GENERADOS / "b2_bon_heldout"
SONDAS = GENERADOS / "b2_consenso_conductual" / "sondas_por_tarea.json"
SALIDA = GENERADOS / "b2_medoide"
PRESUPUESTO = 300          # s por muestra: _firma NO lo trae (riesgo conocido)
SEMILLA = 20260730
N_NULO = 1000


def distancia(a: tuple, b: tuple) -> float:
    """Fracción de posiciones de la trayectoria en que difieren."""
    n = min(len(a), len(b))
    if n == 0:
        return 1.0
    difs = sum(1 for i in range(n) if a[i] != b[i])
    # los largos distintos cuentan como diferencia: una muestra que ejecutó
    # menos pasos NO es "parecida" a una que los ejecutó todos
    difs += abs(len(a) - len(b))
    return difs / max(len(a), len(b))


def medoide(firmas: dict) -> int:
    """s con menor distancia MEDIA al resto. Empate -> menor s (= control)."""
    ss = sorted(firmas)
    if len(ss) == 1:
        return ss[0]
    medias = {}
    for s in ss:
        otras = [distancia(firmas[s], firmas[o]) for o in ss if o != s]
        medias[s] = sum(otras) / len(otras)
    mejor = min(medias.values())
    return min(s for s in ss if medias[s] == mejor)


def _cargar_gate_v2(raiz: Path) -> dict:
    """
    Corpus de la RÉPLICA (`b2_bon_gate_v2`). Otro formato: los ensayos traen
    `orig` (contrato original por s) y `bon.muestras[]` (el held-out del
    selector), y el HTML cuelga de <tarea>__r<N>/s<M>/index.html.

    El estricto se deriva igual que en su propia corrida:
        orig[s].aprobado  AND  bon.muestras[s].aprobado_sel
    """
    res = json.loads((raiz / "resultados.json").read_text(encoding="utf-8"))
    por_ensayo: dict = {}
    for e in res["ensayos"]:
        sel = {int(m["s"]): m for m in (e.get("bon") or {}).get("muestras", [])}
        muestras = []
        for k, v in (e.get("orig") or {}).items():
            s = int(k)
            html = raiz / f"{e['tarea']}__r{e['rep']}" / f"s{s}" / "index.html"
            if not html.is_file():
                continue
            muestras.append({
                "tarea": e["tarea"], "rep": e["rep"], "s": s, "html": html,
                "estricto": bool(v.get("aprobado")
                                 and sel.get(s, {}).get("aprobado_sel")),
            })
        if muestras:
            por_ensayo[(e["tarea"], int(e["rep"]))] = muestras
    return por_ensayo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--corpus", default="b2_bon_heldout",
                    help="b2_bon_heldout (original) o b2_bon_gate_v2 (replica)")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--agregar", nargs="*", default=None,
                    help="junta varios resultados y resume el AGREGADO")
    args = ap.parse_args(argv)

    if args.agregar is not None:
        union = {"ensayos": []}
        for j in args.agregar:
            p = Path(j)
            if not p.is_absolute():
                p = SALIDA / j
            trozo = json.loads(p.read_text(encoding="utf-8"))["ensayos"]
            for e in trozo:                      # etiqueta el origen
                e["ensayo"] = f"{p.stem}:{e['ensayo']}"
            union["ensayos"] += trozo
            print(f"  + {p.name}: {len(trozo)} ensayos")
        print()
        _resumir(union)
        return 0

    sondas = json.loads(SONDAS.read_text(encoding="utf-8"))
    raiz = GENERADOS / args.corpus
    if args.corpus == "b2_bon_gate_v2":
        por_ensayo = _cargar_gate_v2(raiz)
    else:
        fuente = json.loads((raiz / "resultados.json").read_text(encoding="utf-8"))
        por_ensayo = {}
        for m in fuente["muestras"]:
            m = {**m, "html": raiz / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
                 / "index.html"}
            por_ensayo.setdefault((m["tarea"], int(m["rep"])), []).append(m)

    SALIDA.mkdir(parents=True, exist_ok=True)
    f_res = (Path(args.salida) if args.salida
             else SALIDA / f"resultados{'' if args.corpus == 'b2_bon_heldout' else '_' + args.corpus}.json")
    res = (json.loads(f_res.read_text(encoding="utf-8"))
           if args.reanudar and f_res.is_file() else {"ensayos": []})
    hechos = {e["ensayo"] for e in res["ensayos"]}

    for (tarea, rep), muestras in sorted(por_ensayo.items()):
        etiqueta = f"{tarea}:r{rep}"
        if etiqueta in hechos:
            continue
        pasos = sondas[tarea]["pasos"]
        observar = sondas[tarea]["observar"]
        t0 = time.time()
        firmas, estricto, infra = {}, {}, []
        for m in sorted(muestras, key=lambda x: int(x["s"])):
            d = m["html"]
            if not d.is_file():
                continue
            s = int(m["s"])
            try:
                firma, efec = con_presupuesto(PRESUPUESTO, cc._firma,
                                              d, pasos, observar)
            except (PresupuestoAgotado, Exception) as exc:   # noqa: B014
                infra.append({"s": s, "motivo": f"{type(exc).__name__}"})
                continue
            if efec <= 0:
                # una muestra que no ejecutó NADA no vota: dos páginas rotas
                # por la misma excepción tendrían firmas idénticas
                infra.append({"s": s, "motivo": "0 acciones efectivas"})
                continue
            firmas[s] = firma
            estricto[s] = bool(m.get("estricto"))
        if not firmas:
            continue

        elegida = medoide(firmas)
        control = estricto.get(1)
        e = {"ensayo": etiqueta, "tarea": tarea, "rep": rep,
             "elegida_s": elegida, "estricto_elegida": estricto[elegida],
             "control": control, "techo": any(estricto.values()),
             "n_muestras": len(firmas), "infra": infra,
             "estrictos": sorted(s for s, b in estricto.items() if b),
             "distancias_medias": {
                 str(s): round(sum(distancia(firmas[s], firmas[o])
                                   for o in firmas if o != s)
                               / max(1, len(firmas) - 1), 3)
                 for s in sorted(firmas)},
             "segundos": round(time.time() - t0, 1)}
        res["ensayos"].append(e)
        f_res.write_text(json.dumps(res, indent=2, ensure_ascii=False),
                         encoding="utf-8")
        print(f"{etiqueta:20s} medoide=s{elegida} "
              f"{'OK' if e['estricto_elegida'] else '--'}  "
              f"ctrl={'OK' if control else '--'}  "
              f"techo={'OK' if e['techo'] else '--'}  "
              f"({e['segundos']:.0f}s)", flush=True)

    _resumir(res)
    return 0


def _resumir(res: dict) -> None:
    ens = res["ensayos"]
    if not ens:
        return
    n = len(ens)
    # Un ensayo sin s1 (la muestra 1 no dejó HTML) NO tiene control con el que
    # aparearse: entra en el x/n pero se excluye del NETO, que es apareado.
    apar = [e for e in ens if e["control"] is not None]
    sin_control = n - len(apar)
    ctrl = sum(1 for e in ens if e["control"])
    med = sum(1 for e in ens if e["estricto_elegida"])
    techo = sum(1 for e in ens if e["techo"])
    rescata = [e["ensayo"] for e in apar
               if e["estricto_elegida"] and not e["control"]]
    estropea = [e["ensayo"] for e in apar
                if e["control"] and not e["estricto_elegida"]]

    print(f"\n{'='*66}")
    print(f"ENSAYOS {n} · CONTROL {ctrl}/{n} · MEDOIDE {med}/{n} · "
          f"TECHO {techo}/{n}")
    print(f"NETO APAREADO = {len(rescata) - len(estropea):+d}  "
          f"(RESCATA {len(rescata)} · ESTROPEA {len(estropea)}"
          f"{f' · {sin_control} sin control, excluidos del neto' if sin_control else ''})")
    if rescata:
        print(f"  rescata: {rescata}")
    if estropea:
        print(f"  ESTROPEA: {estropea}")
    print("  referencia ya medida: consenso por MAYORIA = 19/24 (neto +2), "
          "pierde 0")

    # BRAZO NULO: elegir al azar entre las muestras disponibles del ensayo
    rng = random.Random(SEMILLA)
    nulos = []
    for _ in range(N_NULO):
        k = 0
        for e in ens:
            ss = e["estrictos"]
            disp = list(e["distancias_medias"].keys())
            k += int(rng.choice(disp)) in ss
        nulos.append(k)
    nulos.sort()
    p95 = nulos[int(0.95 * len(nulos))]
    print(f"\nBRAZO NULO ({N_NULO} selectores uniformes, semilla {SEMILLA}):")
    print(f"  media {sum(nulos)/len(nulos):.2f}/{n} · p95 = {p95}/{n} · "
          f"max {nulos[-1]}/{n}")
    print(f"  P(azar >= medoide) = "
          f"{sum(1 for x in nulos if x >= med)/len(nulos):.3f}")
    print(f"  --> {'SUPERA' if med > p95 else 'NO supera'} el p95 del azar")


if __name__ == "__main__":
    raise SystemExit(main())
