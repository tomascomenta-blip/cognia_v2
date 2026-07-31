# -*- coding: utf-8 -*-
"""
b3_reparacion.py — REPARACIÓN CON CONTRAEJEMPLO contra BEST-OF-N, a iso-cómputo.

POR QUÉ EXISTE (PREREG_REPARACION_CONTRAEJEMPLO_20260731).
La reparación guiada era la prioridad #1 de META y la suspendí yo mismo el
2026-07-28 con evidencia propia (dos A/B: las rondas RESTABAN, −3 y −7). Pero
la suspensión llevaba una CONDICIÓN escrita: *"self-repair gana con un
verificador FIABLE; la nuestra no lo es todavía"*. En código el verificador son
los tests del benchmark y anoche se midió que discriminan (ACUSA_SANOS 2.0%,
DEJA_PASAR 13.4%, J +84.6, contra 88-94% / ~50% / +12.2 del contrato web).
La condición se cumple por primera vez.

TRES BRAZOS que comparten la MISMA `s1` y el MISMO presupuesto (4 candidatos),
con la MISMA política de selección (la literal de bon.py). Solo cambia cómo se
producen los candidatos 2-4:

    BoN      s2,s3,s4 independientes            (el enunciado, otra vez)
    REP      r2,r3,r4 en cadena                 (+ código + CONTRAEJEMPLO)
    PLACEBO  p2,p3,p4 en cadena                 (+ código, SIN contraejemplo)

El PLACEBO no es opcional: un estudio con placebo (arXiv:2606.31511) encontró
que devolver la traza o el código fallido EMPATA con un placebo sin contenido.
Sin él, un REP>BoN no distingue "el contraejemplo informa" de "reintentar
diversifica".

Uso:
    venv312\\Scripts\\python.exe scripts\\b3_reparacion.py --n 90 ^
        --ficheros lcb_test5.jsonl,lcb_test6.jsonl --pared 240 [--reanudar]

Genera y ejecuta; NO decide el veredicto. El análisis vive en
b3_reparacion_analisis.py, que lee este JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from cognia.presupuesto_pared import PresupuestoAgotado, con_presupuesto
from b3_codigo import (SALIDA, carga_lcb, extract_code, genera, juzga_lcb,
                       prompt_lcb, tests_lcb)

TOPE_CAMPO = 1200      # cap por campo del contraejemplo (prereg, amenaza 4)


def _bloque_codigo(texto: str) -> str:
    """El código tal cual, para pegarlo en el prompt de reparación."""
    return (texto or "").strip()


def contraejemplo(t: dict, casos: list, res_por_caso: list,
                  det: dict) -> dict:
    """El PRIMER caso visible que falla, con (entrada, esperada, obtenida).

    Devuelve {} si no hay ninguno (el código pasa todos los visibles) o si el
    arnés no dejó detalle para ese índice (fallo de instrumento del juez): en
    los dos casos el llamador NO puede construir un contraejemplo y lo dice,
    en vez de inventar uno — que es exactamente el modo de fallo que esta
    sesión persigue (facturar instrumento al modelo).
    """
    # Se exige DETALLE. Un caso sin detalle es un caso que no llegó a correr
    # (lote expirado): decir "Actual output: (no output)" ahí sería
    # INVENTARSE el contraejemplo — el mismo pecado de facturar instrumento al
    # modelo que costó 48 veredictos anoche. Si ningún fallo tiene detalle se
    # devuelve {} y el llamador lo registra como `sin_contraejemplo`.
    #
    # Y entre los que tienen detalle se elige el de ENTRADA MÁS CORTA, no el
    # primero (revisión adversarial del 2026-07-31): un contraejemplo cuya
    # entrada hay que recortar a 1200 caracteres llega autocontradictorio —
    # una salida esperada que esos datos truncados no producen. El más corto
    # es el que más veces cabe entero. Empates: el índice más bajo.
    candidatos = [i for i, ok in enumerate(res_por_caso)
                  if not ok and det.get(i)]
    if not candidatos:
        return {}
    i = min(candidatos, key=lambda j: (len(casos[j].get("input") or ""), j))
    c, d = casos[i], det[i]
    ent = c.get("input") or ""
    esp = c.get("output") or ""
    obt = d.get("obtenido") or ""
    return {
        "i": i,
        "entrada": ent[:TOPE_CAMPO], "entrada_len": len(ent),
        "esperada": esp[:TOPE_CAMPO], "esperada_len": len(esp),
        "obtenida": obt[:TOPE_CAMPO], "obtenida_len": len(obt),
        "excepcion": (d.get("excepcion") or "")[:TOPE_CAMPO],
        "recortado": bool(len(ent) > TOPE_CAMPO or len(esp) > TOPE_CAMPO
                          or len(obt) > TOPE_CAMPO),
        "sin_detalle": False,
    }


def _cabecera(t: dict) -> str:
    """EXACTAMENTE el prompt que recibe el brazo BoN (`prompt_lcb`).

    BLOQUEA cazado en la revisión adversarial del 2026-07-31, y era mío: la
    primera versión usaba `t['enunciado']` pelado, así que REP y PLACEBO
    perdían el `starter_code` y las instrucciones de E/S (stdin/stdout) que
    BoN sí recibe. Eso no es "reparar con contraejemplo": es reparar con
    MENOS información que el brazo de control, y el neto habría medido esa
    mutilación. Los tres brazos comparten esta cabecera, letra por letra.
    """
    return prompt_lcb(t)


def _campo(valor: str, largo_real: int, etiqueta: str) -> str:
    """Un campo del contraejemplo, con la marca de recorte VISIBLE.

    Sin la marca, una entrada cortada a 1200 caracteres llega como si fuera
    la entrada COMPLETA y el modelo intenta cuadrar una salida esperada con
    unos datos que no la producen: un contraejemplo autocontradictorio, que
    es peor que ninguno.
    """
    v = valor or ""
    if largo_real and largo_real > len(v):
        return (v + f"\n... [{etiqueta} RECORTADA: {largo_real} caracteres en "
                    f"total, se muestran los primeros {len(v)}]")
    return v


def prompt_reparar(t: dict, codigo: str, ce: dict) -> str:
    """La MISMA cabecera que BoN + código roto + CONTRAEJEMPLO. Se le da el
    caso concreto, NO la traza de la pila: la traza es justo lo que el estudio
    con placebo encontró indistinguible de un placebo vacío."""
    if ce.get("excepcion"):
        obtenido = f"the program raised: {ce['excepcion']}"
    else:
        obtenido = (ce.get("obtenida") or "").strip() or "(no output)"
    return (
        f"{_cabecera(t)}\n\n"
        f"The following Python program is an INCORRECT attempt at the problem "
        f"above:\n```python\n{codigo}\n```\n\n"
        f"It fails on this test case:\n"
        f"Input:\n"
        f"{_campo(ce.get('entrada',''), ce.get('entrada_len',0), 'ENTRADA')}\n"
        f"Expected output:\n"
        f"{_campo(ce.get('esperada',''), ce.get('esperada_len',0), 'SALIDA ESPERADA')}\n"
        f"Actual output:\n"
        f"{_campo(obtenido, 0 if ce.get('excepcion') else ce.get('obtenida_len',0), 'SALIDA OBTENIDA')}\n\n"
        f"Fix the program so that it produces the expected output on this "
        f"case and stays correct in general. Return ONLY a Python code block "
        f"with the complete corrected program.")


def prompt_placebo(t: dict, codigo: str) -> str:
    """IDÉNTICO al de reparación menos el bloque del contraejemplo. Esa
    diferencia — y solo esa — es lo que mide la secundaria 1."""
    return (
        f"{_cabecera(t)}\n\n"
        f"The following Python program is an INCORRECT attempt at the problem "
        f"above:\n```python\n{codigo}\n```\n\n"
        f"It does not pass the tests. "
        f"Fix the program so that it is correct. Return ONLY a Python code "
        f"block with the complete corrected program.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=154)
    ap.add_argument("--minutos", type=int, default=0,
                    help="corte por RELOJ pre-registrado: para al terminar la "
                         "tarea en curso pasados N minutos (0 = sin corte)")
    ap.add_argument("--k", type=int, default=4, help="presupuesto por brazo")
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--semilla", type=int, default=20260731)
    ap.add_argument("--dificultad", default="hard")
    ap.add_argument("--ficheros", default="lcb_test5.jsonl,lcb_test6.jsonl")
    ap.add_argument("--pared", type=int, default=240)
    ap.add_argument("--max-tokens", dest="max_tokens", type=int, default=8192)
    ap.add_argument("--sufijo", default="")
    ap.add_argument("--reanudar", action="store_true")
    args = ap.parse_args()

    SALIDA.mkdir(exist_ok=True)
    fichero = SALIDA / f"reparacion{args.sufijo}.json"

    pool = carga_lcb(ficheros=tuple(x.strip() for x in args.ficheros.split(",")
                                    if x.strip()))
    if args.dificultad:
        pool = [t for t in pool
                if t["dificultad"] in args.dificultad.split(",")]
    rng = random.Random(args.semilla)
    rng.shuffle(pool)
    tareas = []
    for t in pool:
        t["_id"] = str(t["task_id"])
        t["_prompt"] = prompt_lcb(t)
        # MISMO examen que anoche: RNG determinista POR TAREA, para que ni
        # reanudar ni cambiar N puedan mover el split.
        t["_vis"], t["_oc"] = tests_lcb(
            t, random.Random(f"20260730:{t['_id']}"), sin_fuga=True)
        if t["_vis"] and t["_oc"]:
            tareas.append(t)
        if len(tareas) >= args.n:
            break

    print(f"[rep] tareas={len(tareas)} dificultad={args.dificultad} "
          f"k={args.k} temp={args.temp}", flush=True)
    fechas = sorted(t["fecha"] for t in tareas)
    print(f"[rep] ventana: {fechas[0]} .. {fechas[-1]}", flush=True)

    res = {"experimento": "reparacion_contraejemplo",
           "prereg": "PREREG_REPARACION_CONTRAEJEMPLO_20260731.md",
           "k": args.k, "temp": args.temp, "semilla": args.semilla,
           "dificultad": args.dificultad, "ficheros": args.ficheros,
           "n_pedidas": args.n, "max_tokens": args.max_tokens,
           "muestras": []}
    if fichero.exists():
        if not args.reanudar:
            print(f"ABORTA: {fichero} existe y sin --reanudar lo "
                  f"SOBRESCRIBIRÍA en silencio.", flush=True)
            sys.exit(2)
        res = json.loads(fichero.read_text(encoding="utf-8"))
        for campo, valor in (("k", args.k), ("semilla", args.semilla),
                             ("temp", args.temp),
                             ("dificultad", args.dificultad),
                             ("ficheros", args.ficheros)):
            if res.get(campo) != valor:
                print(f"ABORTA: el fichero tiene {campo}={res.get(campo)!r} y "
                      f"se pide {valor!r}; mezclarlo falsearía el apareado.",
                      flush=True)
                sys.exit(2)
        print(f"[rep] reanudando: {len(res['muestras'])} muestras en disco",
              flush=True)
    # una tarea está HECHA si tiene su registro de cierre (marca explícita:
    # contar muestras no vale, porque la parada temprana hace que el número
    # legítimo por tarea varíe entre 1 y 10)
    hechas = {m["tarea"] for m in res["muestras"] if m.get("cierre")}
    # Y se TIRAN los registros de las tareas a medias. Una tarea sin `cierre`
    # se rehace entera al reanudar (la cadena rep/pla necesita el `_code` del
    # eslabón anterior, que vive en memoria); si sus registros parciales se
    # quedaran, la tarea aparecería DOS VECES en el análisis y sus brazos
    # tendrían más candidatos de los que se le dieron. Es barato: se pierde
    # como mucho una tarea de generación.
    antes = len(res["muestras"])
    res["muestras"] = [m for m in res["muestras"] if m["tarea"] in hechas]
    if antes != len(res["muestras"]):
        print(f"[rep] descartados {antes - len(res['muestras'])} registros de "
              f"tareas a medias (se rehacen enteras)", flush=True)

    def guardar():
        tmp = fichero.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(res, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, fichero)

    def una_muestra(t, prompt, brazo, idx):
        """Genera, juzga visibles CON DETALLE y juzga ocultos. Devuelve el
        registro (ya appendeado) para que el llamador encadene."""
        ts = time.time()
        uso = {}
        try:
            texto, motivo = con_presupuesto(args.pared, genera, prompt,
                                            args.temp, args.max_tokens,
                                            "", "", uso)
        except PresupuestoAgotado:
            texto, motivo = "", f"presupuesto_pared_{args.pared}s"
        code = extract_code(texto)
        # EL MODELO SE RINDE != EL ARNÉS FALLA. Reproducido a mano el
        # 2026-07-31 sobre esta misma corrida: las muestras marcadas
        # `sin_codigo_extraible` decían literalmente *"Sorry, I cannot provide
        # a solution."* con 1426 tokens de razonamiento y finish_reason
        # normal. No hay nada que extraer porque el modelo no escribió código,
        # no porque el extractor falle. Contarlo como INSTRUMENTO sería el
        # error SIMÉTRICO del de anoche —facturarle al instrumento un fallo
        # del modelo— y encima expulsaría de la primaria justo las tareas más
        # difíciles, que es donde vive el efecto.
        sin_codigo_modelo = bool(not code and not motivo)
        det = {}
        vis_ok, m_vis = juzga_lcb(code, t, t["_vis"], detalle=det)
        # por caso, para saber CUÁL falló (el sumatorio no basta)
        res_caso = [(i not in det) for i in range(len(t["_vis"]))]
        if vis_ok != sum(res_caso):
            # el arnés no dejó detalle de algún fallo: se marca y el
            # contraejemplo saldrá con sin_detalle=True
            res_caso = None
        oc_ok, m_oc = juzga_lcb(code, t, t["_oc"], parar_al_fallar=True)
        reg = {
            "tarea": t["_id"], "brazo": brazo, "idx": idx,
            "vis_ok": vis_ok, "vis_n": len(t["_vis"]),
            "oc_ok": oc_ok, "oc_n": len(t["_oc"]),
            "pasa_vis": vis_ok == len(t["_vis"]) and len(t["_vis"]) > 0,
            "pasa_oc": oc_ok == len(t["_oc"]) and len(t["_oc"]) > 0,
            "instrumento": motivo,
            "sin_codigo_modelo": sin_codigo_modelo,
            "juez_vis": m_vis, "juez_oc": m_oc,
            "segundos": round(time.time() - ts, 1),
            "prompt_chars": len(prompt),
            "tok_prompt": uso.get("prompt_tokens"),
            "tok_salida": uso.get("completion_tokens"),
            "crudo": texto[:6000],
        }
        ce = {}
        if res_caso is not None and not reg["pasa_vis"]:
            ce = contraejemplo(t, t["_vis"], res_caso, det)
        elif not reg["pasa_vis"]:
            ce = contraejemplo(t, t["_vis"],
                               [False] * len(t["_vis"]), det)
        reg["contraejemplo"] = ce
        reg["_code"] = code
        res["muestras"].append(reg)
        return reg

    t0 = time.time()
    for i, t in enumerate(tareas):
        if t["_id"] in hechas:
            continue
        # corte por RELOJ pre-registrado: se comprueba ANTES de empezar una
        # tarea, nunca a mitad — así el fichero solo contiene tareas COMPLETAS
        # y el prefijo analizable no depende de dónde cayó el corte.
        if args.minutos and (time.time() - t0) / 60 >= args.minutos:
            print(f"[rep] CORTE POR RELOJ a los {args.minutos} min con "
                  f"{len(hechas)} tareas completas", flush=True)
            break
        # ---- raíz compartida por los tres brazos ----
        raiz = una_muestra(t, t["_prompt"], "raiz", 1)
        guardar()

        if not raiz["pasa_vis"]:
            # ---- BoN: muestras independientes, parada temprana ----
            for s in range(2, args.k + 1):
                m = una_muestra(t, t["_prompt"], "bon", s)
                guardar()
                if m["pasa_vis"]:
                    break
            # ---- REP y PLACEBO: cadenas desde la raíz ----
            for brazo in ("rep", "pla"):
                actual = raiz
                for s in range(2, args.k + 1):
                    codigo = _bloque_codigo(actual.get("_code") or "")
                    if not codigo:
                        # no hay nada que reparar: se corta y se marca como
                        # instrumento en vez de inventar una reparación
                        # NO es instrumento: es una propiedad REAL del método.
                        # Si el candidato anterior no trae código, no hay nada
                        # que reparar y la cadena se acaba — mientras que BoN
                        # simplemente genera otra muestra. Esa asimetría es
                        # parte de lo que se está midiendo, así que se marca
                        # `no_generado` (el análisis lo saca del pool) y no se
                        # disfraza de fallo del arnés.
                        res["muestras"].append({
                            "tarea": t["_id"], "brazo": brazo, "idx": s,
                            "instrumento": "", "no_generado": True,
                            "corte": "sin_codigo_previo",
                            "sin_codigo_modelo": False,
                            "vis_ok": 0, "vis_n": len(t["_vis"]),
                            "oc_ok": 0, "oc_n": len(t["_oc"]),
                            "pasa_vis": False, "pasa_oc": False,
                            "juez_vis": "", "juez_oc": "", "segundos": 0.0,
                            "prompt_chars": 0, "tok_prompt": 0,
                            "tok_salida": 0, "crudo": "",
                            "contraejemplo": {}})
                        break
                    if brazo == "rep":
                        ce = actual.get("contraejemplo") or {}
                        if not ce:
                            # ESTE SÍ es instrumento: hay código y falla algún
                            # visible, pero el arnés no dejó la salida
                            # obtenida de ninguno (lote expirado o arnés
                            # reventado). El brazo REP se queda sin su
                            # ingrediente por culpa del juez, no del modelo.
                            res["muestras"].append({
                                "tarea": t["_id"], "brazo": brazo, "idx": s,
                                "instrumento": "sin_contraejemplo",
                                "no_generado": True,
                                "sin_codigo_modelo": False,
                                "vis_ok": 0, "vis_n": len(t["_vis"]),
                                "oc_ok": 0, "oc_n": len(t["_oc"]),
                                "pasa_vis": False, "pasa_oc": False,
                                "juez_vis": "", "juez_oc": "",
                                "segundos": 0.0, "prompt_chars": 0,
                                "tok_prompt": 0, "tok_salida": 0,
                                "crudo": "", "contraejemplo": {}})
                            break
                        p = prompt_reparar(t, codigo, ce)
                    else:
                        p = prompt_placebo(t, codigo)
                    actual = una_muestra(t, p, brazo, s)
                    guardar()
                    if actual["pasa_vis"]:
                        break

        # cierre de la tarea: la marca que hace reanudable una corrida con
        # número VARIABLE de muestras por tarea
        res["muestras"].append({"tarea": t["_id"], "brazo": "cierre",
                                "idx": 0, "cierre": True,
                                "instrumento": "", "vis_ok": 0, "vis_n": 0,
                                "oc_ok": 0, "oc_n": 0, "pasa_vis": False,
                                "pasa_oc": False, "juez_vis": "",
                                "juez_oc": "", "segundos": 0.0,
                                "prompt_chars": 0, "tok_prompt": 0,
                                "tok_salida": 0, "crudo": "",
                                "contraejemplo": {}})
        hechas.add(t["_id"])
        guardar()

        gen = sum(1 for m in res["muestras"] if not m.get("cierre"))
        inst = sum(1 for m in res["muestras"]
                   if m.get("instrumento") and not m.get("cierre"))
        print(f"[rep] tarea {i+1}/{len(tareas)} generaciones={gen} "
              f"instrumento={inst} ({inst/max(1,gen):.1%}) "
              f"({(time.time()-t0)/60:.0f} min)", flush=True)

    guardar()
    print(f"[rep] FIN -> {fichero}", flush=True)


if __name__ == "__main__":
    main()
