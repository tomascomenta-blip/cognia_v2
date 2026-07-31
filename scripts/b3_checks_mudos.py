# -*- coding: utf-8 -*-
"""
b3_checks_mudos.py — ¿el check DESCRIBE una interacción que nunca EJECUTA?

Salió auditando a mano la muestra del PREREG_INVENCION_VS_SECUENCIA. El caso
que lo destapó, literal del corpus:

    {"nombre": "Al introducir 5 unidades, total sin descuento es 50.00",
     "acciones": [{"accion":"texto","selector":"#cant","contiene":"5"},
                  {"accion":"texto","selector":"#total","contiene":"50.00"}]}

El paso dice *"al introducir 5 unidades"* y **no introduce nada**: solo
comprueba el estado como si la interacción hubiera ocurrido. Si eso es
general, explica de una vez:

  - por qué los valores de ENTRADA no aparecen (nadie los escribió),
  - por qué los de SALIDA tampoco (la interacción no ocurrió),
  - por qué "ejecutar el check no hace aparecer los valores" (no hay nada
    que ejecutar),
  - y por qué arreglar el 41% de `texto`-sobre-`input` movió el veredicto
    0.0 puntos.

Pero UNA observación no es una medición: aquí se mide sobre los 87 contratos
del corpus ampliado, con brazo de comparación (checks que SÍ interactúan) y
contra el veredicto real del juez.

Cero GPU.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GEN = RAIZ / "cognia" / "program_creator" / "generated_programs"
DATOS = GEN / "b2_contratos_ampliado"

INTERACCION = {"click", "tecla", "escribir"}

# Verbos que anuncian una interacción en el NOMBRE del paso. Lista fijada
# antes de contar (si se ajustara después de ver el resultado, el número
# dejaría de significar nada).
_VERBOS = (r"introduc|ingres|escrib|tecle|pulsa|puls[ae]r|clic|click|"
           r"agrega|añad|anad|reserv|apunt|cambi|aplic|seleccion|"
           r"deshac|rehac|undo|redo|crea|marca|mueve|mover|filtr|orden|"
           r"avanz|intent|pon[eg]|quita|cancel|ajust|presion|activ|"
           r"desmarc|arrastr|elimin|borra|añade")
_RX_VERBO = re.compile(_VERBOS, re.IGNORECASE)


def describe_interaccion(nombre: str) -> bool:
    return bool(_RX_VERBO.search(nombre or ""))


def ejecuta_interaccion(acciones: list) -> bool:
    return any((a.get("accion") or "").strip() in INTERACCION
               for a in (acciones or []) if isinstance(a, dict))


def main():
    indice = json.loads((DATOS / "indice.json").read_text(
        encoding="utf-8"))["filas"]
    juicios = json.loads((DATOS / "juicios.json").read_text(
        encoding="utf-8"))
    juicios = juicios if isinstance(juicios, list) \
        else list(juicios.values())[0]

    # juicios: detalle por check (clave 'n' = nombre del paso), para cruzar
    # MUDO con FALLA. gt = ground truth de sanidad de la página.
    det, gt = {}, {}
    for j in juicios:
        pag = j.get("pagina", "")
        gt[pag] = j.get("gt")
        for c in (j.get("detalle") or []):
            if isinstance(c, dict) and c.get("n") is not None:
                det[(pag, c["n"])] = bool(c.get("ok"))

    filas = []
    for entrada in indice:
        pag = entrada.get("pagina", "")
        ruta = GEN / pag / "contrato_interno.json"
        if not ruta.exists():
            continue
        try:
            c = json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            continue
        for p in (c.get("pasos") or []):
            if not isinstance(p, dict):
                continue
            nombre = p.get("nombre", "")
            acc = p.get("acciones") or []
            filas.append({
                "pagina": pag, "tarea": entrada.get("tarea", ""),
                "nombre": nombre, "critico": bool(p.get("critico")),
                "describe": describe_interaccion(nombre),
                "ejecuta": ejecuta_interaccion(acc),
                "n_acc": len(acc), "gt": gt.get(pag),
                "ok": det.get((pag, nombre)),
            })

    if not filas:
        print("[!] no se pudo leer ningún contrato — revisa indice.json")
        return

    n = len(filas)
    print(f"checks leídos: {n}  (de {len({f['pagina'] for f in filas})} páginas)")

    describe = [f for f in filas if f["describe"]]
    mudos = [f for f in describe if not f["ejecuta"]]
    hablan = [f for f in describe if f["ejecuta"]]
    print(f"\n== ¿el check EJECUTA lo que su nombre DESCRIBE? ==")
    print(f"  checks cuyo nombre describe una interacción : {len(describe)} "
          f"({len(describe)/n:.1%})")
    print(f"    de esos, MUDOS (no ejecutan ninguna)      : {len(mudos)} "
          f"({len(mudos)/max(1,len(describe)):.1%})")
    print(f"    de esos, sí interactúan                   : {len(hablan)} "
          f"({len(hablan)/max(1,len(describe)):.1%})")

    # ---- ¿los MUDOS son los que fallan? (el cruce que decide) ----
    con_ok = [f for f in filas if f["ok"] is not None]
    if con_ok:
        def tasa(pool):
            p = [f for f in pool if f["ok"] is not None]
            return (sum(1 for f in p if not f["ok"]) / len(p), len(p)) if p \
                else (float("nan"), 0)
        t_mudo, n_mudo = tasa(mudos)
        t_habla, n_habla = tasa(hablan)
        t_nodesc, n_nodesc = tasa([f for f in filas if not f["describe"]])
        print(f"\n== tasa de FALLO del check, por clase "
              f"(juicio real del juez, {len(con_ok)} checks con veredicto) ==")
        print(f"  MUDO (describe y no ejecuta) : {t_mudo:.1%}  [n={n_mudo}]")
        print(f"  INTERACTÚA                   : {t_habla:.1%}  [n={n_habla}]")
        print(f"  no describe interacción      : {t_nodesc:.1%}  [n={n_nodesc}]")
        if n_mudo and n_habla:
            print(f"  --> diferencia MUDO - INTERACTÚA : "
                  f"{(t_mudo - t_habla)*100:+.1f} puntos")

        # La tasa cruda MEZCLA páginas sanas y rotas: en una página rota un
        # check puede fallar con razón. Lo que acusa al examen es fallar en
        # una página SANA, que es la métrica de todo el diagnóstico previo.
        print(f"\n== SOLO PÁGINAS SANAS (gt=True): fallar aquí acusa al "
              f"EXAMEN, no al producto ==")
        for etiq, pool in (("MUDO", mudos), ("INTERACTÚA", hablan),
                           ("no describe", [f for f in filas
                                            if not f["describe"]])):
            p = [f for f in pool if f["ok"] is not None and f["gt"] is True]
            if p:
                t = sum(1 for f in p if not f["ok"]) / len(p)
                print(f"  {etiq:<12}: falla {t:.1%}  [n={len(p)}]")
            else:
                print(f"  {etiq:<12}: sin datos")
        print(f"\n== SOLO PÁGINAS ROTAS (gt=False) ==")
        for etiq, pool in (("MUDO", mudos), ("INTERACTÚA", hablan)):
            p = [f for f in pool if f["ok"] is not None and f["gt"] is False]
            if p:
                t = sum(1 for f in p if not f["ok"]) / len(p)
                print(f"  {etiq:<12}: falla {t:.1%}  [n={len(p)}]")
            else:
                print(f"  {etiq:<12}: sin datos")
        print(f"  [reparto de gt: "
              f"{dict(Counter(str(f['gt']) for f in filas))}]")

        # ¿dónde viven los que SÍ interactúan? Si se concentran en pocas
        # tareas, su 95% no es comparable con el 50% de los mudos.
        print(f"\n== dónde viven los checks que SÍ interactúan ==")
        for t, c in Counter(f["tarea"] for f in hablan).most_common(8):
            print(f"    {t:<24} {c:>3}")

        # La comparación cruda MUDO-vs-INTERACTÚA está CONFUNDIDA POR TAREA
        # (los que interactúan viven en 2 tareas). El contraste válido es
        # APAREADO dentro de la misma tarea, y solo en páginas sanas.
        print(f"\n== APAREADO DENTRO DE TAREA (páginas sanas, tareas con "
              f">=3 de cada clase) ==")
        pt = defaultdict(lambda: {"m": [], "i": [], "n": []})
        for f in filas:
            if f["ok"] is None or f["gt"] is not True:
                continue
            cual = "n" if not f["describe"] else ("m" if not f["ejecuta"]
                                                  else "i")
            pt[f["tarea"]][cual].append(not f["ok"])
        difs_mi, difs_mn = [], []
        for t, d in sorted(pt.items()):
            if len(d["m"]) >= 3 and len(d["i"]) >= 3:
                dm, di = sum(d["m"]) / len(d["m"]), sum(d["i"]) / len(d["i"])
                difs_mi.append(dm - di)
                print(f"    {t:<24} MUDO {dm:>5.0%} (n={len(d['m']):>2})  vs "
                      f"INTERACTÚA {di:>5.0%} (n={len(d['i']):>2})  "
                      f"dif {(dm-di)*100:+.0f}")
            if len(d["m"]) >= 3 and len(d["n"]) >= 3:
                dm, dn = sum(d["m"]) / len(d["m"]), sum(d["n"]) / len(d["n"])
                difs_mn.append(dm - dn)
        if difs_mi:
            print(f"  MEDIA de la diferencia MUDO-INTERACTÚA apareada: "
                  f"{sum(difs_mi)/len(difs_mi)*100:+.1f} pts "
                  f"[{len(difs_mi)} tareas]")
        else:
            print(f"    ninguna tarea tiene >=3 de ambas clases: la "
                  f"comparación MUDO-vs-INTERACTÚA NO es identificable")
        if difs_mn:
            print(f"  MEDIA de la diferencia MUDO - 'no describe' apareada: "
                  f"{sum(difs_mn)/len(difs_mn)*100:+.1f} pts "
                  f"[{len(difs_mn)} tareas]")
    else:
        print("\n[!] los juicios no traen detalle por check cruzable; "
              "solo se reporta la estructura")

    # ---- solo CRÍTICOS, que son los que deciden el veredicto (AND) ----
    crit = [f for f in filas if f["critico"]]
    cd = [f for f in crit if f["describe"]]
    cm = [f for f in cd if not f["ejecuta"]]
    print(f"\n== solo CRÍTICOS (los que deciden el veredicto por AND) ==")
    print(f"  críticos: {len(crit)}; describen interacción: {len(cd)}; "
          f"MUDOS: {len(cm)} ({len(cm)/max(1,len(crit)):.1%} de los críticos)")

    # ---- páginas con al menos un crítico MUDO ----
    porpag = defaultdict(int)
    for f in cm:
        porpag[f["pagina"]] += 1
    pags = {f["pagina"] for f in filas}
    print(f"  páginas con >=1 crítico MUDO: {len(porpag)}/{len(pags)} "
          f"({len(porpag)/max(1,len(pags)):.1%})")
    print(f"  mediana de críticos mudos por página afectada: "
          f"{sorted(porpag.values())[len(porpag)//2] if porpag else 0}")

    print(f"\n== por tarea (críticos mudos / críticos que describen) ==")
    pt = defaultdict(lambda: [0, 0])
    for f in cd:
        pt[f["tarea"]][1] += 1
        if not f["ejecuta"]:
            pt[f["tarea"]][0] += 1
    for t, (a, b) in sorted(pt.items(), key=lambda kv: -kv[1][1])[:15]:
        print(f"    {t:<24} {a:>3} / {b:>3}   ({a/max(1,b):.0%})")

    out = DATOS / "checks_mudos.json"
    out.write_text(json.dumps(filas, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
