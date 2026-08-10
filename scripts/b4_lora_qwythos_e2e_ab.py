# -*- coding: utf-8 -*-
"""
b4_lora_qwythos_e2e_ab.py — GATE F1 del PREREG_LORA_QWYTHOS_20260809: e2e
APAREADO adapter ON/OFF sobre el mismo server vivo.

POR QUE apareado e intercalado: la varianza ENTRE corridas de este banco es
de +/-34 pts (memoria del repo) — solo los netos APAREADOS intra-corrida son
evidencia, y los brazos van INTERCALADOS (orden pre-sorteado con la semilla
del prereg) para que la deriva del instrumento no caiga toda en un brazo.
POR QUE el nulo OFF/OFF primero: un instrumento que da |d|>1 entre dos
brazos IDENTICOS esta sucio y la corrida no cuenta (un nulo no basta como
leccion: aqui esta cableado y se lee ANTES que la primaria).

Mecanica: un solo llama-server con --lora ... --lora-init-without-apply
--sin-draft --parallel 1 (jamas --lora-scaled: el ':' de C: rompe el split
en Windows). ON = POST /lora-adapters scale 1.0; OFF = scale 0.0 — el OFF es
el MISMO proceso a escala 0 (el contrafactual: quitar el defecto y que el
efecto se apague). Tras CADA swap se marca el KV sucio (chat_client) para
que la primera request re-prefille (KV contaminado, trampa medida 2026-07-07).

Primaria pre-declarada: d_i = aciertos_ON_i - aciertos_OFF_i por par sobre
el banco (5 e2e + 15 held-out de banco_trazas). Exito = mediana(d) >= 0 Y
d_i >= 0 en >=5/6 pares Y suma(d) > 0. MDE ~3 tareas (15 pp): un "sin
efecto" con este MDE es NO DETERMINADO, no KILL de la via.

Uso ([GPU-EXCL], flota y oficina APAGADAS; ver prereg):
  venv312\\Scripts\\python.exe scripts\\b4_lora_qwythos_e2e_ab.py
      [--url http://127.0.0.1:8090] [--pares 6] [--nulos 2]
      [--semilla 20260809] [--salida f1_qwythos_e2e_ab.json] [--solo-plan]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import statistics
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA_DIR = RAIZ / "b4_loras"
SEED = 20260809
MDE_TAREAS = 3          # con 20 tareas y n=6 no se distinguen efectos menores
MDE_PP = 15.0           # se reporta SIEMPRE junto al resultado
URL_DEFAULT = "http://127.0.0.1:8090"   # C3: solo con flota Y oficina apagadas


# ---------------------------------------------------------------------------
# Puras / testeables en CPU
# ---------------------------------------------------------------------------

def orden_pares(semilla: int = SEED, n_pares: int = 6,
                n_nulos: int = 2) -> list[dict]:
    """Plan de corrida pre-sorteado y determinista por semilla.

    n_pares pares A/B (cada uno con orden interno ON-primero u OFF-primero
    sorteado) + n_nulos pares OFF/OFF intercalados en posiciones sorteadas.
    El plan entero queda fijado ANTES de correr nada (se imprime y se guarda
    en el JSON: nada de re-sortear a mitad)."""
    rng = random.Random(semilla)
    pares = [{"tipo": "AB",
              "orden": ("ON", "OFF") if rng.random() < 0.5 else ("OFF", "ON")}
             for _ in range(n_pares)]
    for _ in range(n_nulos):
        pos = rng.randint(0, len(pares))
        pares.insert(pos, {"tipo": "NULO", "orden": ("OFF", "OFF")})
    for i, p in enumerate(pares):
        p["idx"] = i
    return pares


def evaluar_primaria(d_pares: list[int], d_nulos: list[int],
                     n_tareas: int) -> dict:
    """Lectura pre-registrada de la corrida. El nulo se lee PRIMERO.

    - INSTRUMENTO_SUCIO si algun |d_nulo| > 1 (la corrida no cuenta).
    - KILL si mediana(d) < 0 o algun d_i <= -3 (regla congelada del prereg).
    - PASS si mediana(d) >= 0 Y d_i >= 0 en >= n-1 de n pares Y suma > 0.
    - NO_DETERMINADO en el resto (efecto < MDE: no se afirma nada).
    """
    res = {"d_pares": list(d_pares), "d_nulos": list(d_nulos),
           "n_tareas": n_tareas, "mde_tareas": MDE_TAREAS, "mde_pp": MDE_PP}
    if any(abs(d) > 1 for d in d_nulos):
        res.update(veredicto="INSTRUMENTO_SUCIO",
                   motivo="|d_nulo| > 1: dos brazos identicos difieren mas "
                          "de 1 tarea; la corrida no cuenta")
        return res
    if not d_pares:
        res.update(veredicto="INSTRUMENTO_SUCIO", motivo="sin pares A/B")
        return res
    mediana = statistics.median(d_pares)
    suma = sum(d_pares)
    no_negativos = sum(1 for d in d_pares if d >= 0)
    res.update(mediana=mediana, suma=suma, pares_no_negativos=no_negativos)
    if mediana < 0 or any(d <= -3 for d in d_pares):
        res.update(veredicto="KILL",
                   motivo="mediana(d) < 0 o algun par con d <= -3 "
                          "(regresion): el adapters.json NO se instala")
    elif mediana >= 0 and no_negativos >= max(1, len(d_pares) - 1) and suma > 0:
        res.update(veredicto="PASS", motivo="mediana >= 0, >=n-1 pares no "
                                            "negativos y suma > 0")
    else:
        res.update(veredicto="NO_DETERMINADO",
                   motivo="efecto por debajo del MDE (~%d tareas / %.0f pp): "
                          "no se afirma nada" % (MDE_TAREAS, MDE_PP))
    return res


def cargar_heldout(n: int = 15, semilla: int = SEED) -> tuple[list, str]:
    """Las 15 tareas HELD-OUT de banco_trazas (split por PLANTILLA, jamas
    vistas en el dataset — leccion split-disjunto). Import perezoso y
    tolerante: si banco_trazas (agente Z, ola 1) aun no expone
    tareas_heldout(), se degrada VISIBLE a solo las 5 del e2e y el JSON lo
    declara (una corrida oficial de F1 exige el banco completo)."""
    ruta = RAIZ / "scripts" / "banco_trazas.py"
    try:
        spec = importlib.util.spec_from_file_location("banco_trazas", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for nombre in ("tareas_heldout", "heldout", "plantillas_heldout"):
            fn = getattr(mod, nombre, None)
            if callable(fn):
                return list(fn(n=n, semilla=semilla)), ""
        return [], "banco_trazas.py sin tareas_heldout()/heldout()"
    except Exception as exc:
        return [], "banco_trazas no disponible: %s" % exc


def tareas_e2e() -> list[tuple]:
    """Las 5 tareas del gate e2e clasico (copiadas de e2e_happy_path.py, que
    las define DENTRO de main() y no son importables). (nombre, tarea,
    verificar(ws)->bool|None, setup(ws)|None); la de python se chequea por
    la respuesta ('350')."""
    def _lee(ws, n):
        hits = list(Path(ws).rglob(n))
        return hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""

    return [
        ("escribir", "escribi un archivo llamado nota.txt con el texto exacto: bateria ok",
         lambda ws: "bateria ok" in _lee(ws, "nota.txt"), None),
        ("calcular+guardar", "calcula 17 por 23 y guarda el resultado en resultado.txt",
         lambda ws: "391" in _lee(ws, "resultado.txt"), None),
        ("json", "crea un archivo config.json con la clave modo puesta en rapido",
         lambda ws: json.loads(_lee(ws, "config.json") or "{}").get("modo") == "rapido", None),
        ("apendar", "agrega la linea 'tercera' al final del archivo bitacora.txt",
         lambda ws: (_lee(ws, "bitacora.txt").strip().splitlines() or [""])[-1].strip().strip("'\"") == "tercera",
         lambda ws: (Path(ws) / "bitacora.txt").write_text("primera\nsegunda\n", encoding="utf-8")),
        ("python", "escribi y ejecuta un script python que imprima la suma de 100 mas 250",
         None, None),
    ]


# ---------------------------------------------------------------------------
# Instrumento (red + agente; solo dentro de main)
# ---------------------------------------------------------------------------

def _post_escala(url: str, escala: float) -> None:
    """Swap por el endpoint runtime (jamas --lora-scaled) + KV sucio: la
    primera request tras el swap manda cache_prompt:false via chat_client.
    Si chat_client no expone marcar_kv_sucio se ABORTA: correr el gate con
    KV contaminado falsea los dos brazos en silencio."""
    req = urllib.request.Request(
        url.rstrip("/") + "/lora-adapters",
        data=json.dumps([{"id": 0, "scale": escala}]).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    from cognia.agent import chat_client
    chat_client.marcar_kv_sucio()


def _verificar_server(url: str) -> None:
    ad = json.loads(urllib.request.urlopen(
        url.rstrip("/") + "/lora-adapters", timeout=10).read().decode("utf-8"))
    print("adapters del server: %s" % ad)
    if not ad:
        print("FALLA: el server no tiene adapters cargados (--lora falta)")
        sys.exit(2)
    props = json.loads(urllib.request.urlopen(
        url.rstrip("/") + "/props", timeout=10).read().decode("utf-8"))
    slots = props.get("total_slots")
    if slots != 1:
        print("FALLA: total_slots=%s (exigido 1: --parallel 1)" % slots)
        sys.exit(2)


def _armar_hacer():
    """El runner de tareas del e2e clasico (mismo instrumento, mismo camino
    _run_agent_task) devuelto como closure hacer(tarea, verificar, setup)."""
    import tempfile

    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    def hacer(tarea, verificar, setup=None, pasos=6):
        ws = Path(tempfile.mkdtemp(prefix="ab_")).resolve()
        if setup:
            setup(ws)
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: None, max_steps=pasos)
        except Exception as exc:
            resp = "EXCEPTION: %s" % exc
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        try:
            return verificar(ws) if verificar else None, (str(resp) or "")[:90]
        except Exception as exc:
            return False, "verify exc: %s" % exc

    return hacer, orch


def _correr_brazo(hacer, tareas: list, etiqueta: str) -> tuple[int, list]:
    """Corre el banco entero bajo la escala vigente. Devuelve (aciertos,
    detalle por tarea)."""
    aciertos, detalle = 0, []
    for nombre, tarea, verificar, setup in tareas:
        t0 = time.time()
        ok, resp = hacer(tarea, verificar, setup)
        if ok is None:   # tareas chequeadas por respuesta (la de python)
            ok = "350" in resp
        aciertos += 1 if ok else 0
        detalle.append({"tarea": nombre, "ok": bool(ok),
                        "seg": round(time.time() - t0, 1)})
        print("    [%s] %-18s %s (%.0fs)"
              % (etiqueta, nombre, "OK " if ok else "FAIL", time.time() - t0),
              flush=True)
    return aciertos, detalle


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate F1: e2e apareado ON/OFF")
    ap.add_argument("--url", default=URL_DEFAULT)
    ap.add_argument("--pares", type=int, default=6)
    ap.add_argument("--nulos", type=int, default=2)
    ap.add_argument("--semilla", type=int, default=SEED)
    ap.add_argument("--heldout", type=int, default=15)
    ap.add_argument("--salida", default="f1_qwythos_e2e_ab.json")
    ap.add_argument("--solo-plan", action="store_true",
                    help="imprime el orden pre-sorteado y sale (sin GPU)")
    args = ap.parse_args()

    plan = orden_pares(args.semilla, args.pares, args.nulos)
    print("plan pre-sorteado (semilla %d):" % args.semilla)
    for p in plan:
        print("  par %d: %s %s" % (p["idx"], p["tipo"], "/".join(p["orden"])))
    if args.solo_plan:
        return 0

    heldout, motivo_heldout = cargar_heldout(args.heldout, args.semilla)
    tareas = tareas_e2e() + list(heldout)
    if motivo_heldout:
        print("AVISO (degradacion VISIBLE): sin held-out de banco_trazas — "
              "%s; el banco queda en %d tareas y la corrida NO es la oficial "
              "del prereg (exige 20)" % (motivo_heldout, len(tareas)))
    print("banco: %d tareas (%d e2e + %d held-out) | MDE ~%d tareas (%.0f pp)"
          % (len(tareas), len(tareas_e2e()), len(heldout), MDE_TAREAS, MDE_PP))

    _verificar_server(args.url)
    # el agente del gate habla con ESTE server, no con la flota
    os.environ["COGNIA_LLM_URL"] = args.url
    hacer, orch = _armar_hacer()

    ESCALAS = {"ON": 1.0, "OFF": 0.0}
    corridas, d_pares, d_nulos = [], [], []
    t0 = time.time()
    try:
        for p in plan:
            print("\n== par %d (%s: %s) ==" % (p["idx"], p["tipo"],
                                               "/".join(p["orden"])))
            aciertos = {}
            detalle_par = []
            for brazo in p["orden"]:
                # swap SIEMPRE (tambien OFF->OFF en el nulo): el instrumento
                # debe ser identico en todos los brazos
                _post_escala(args.url, ESCALAS[brazo])
                a, det = _correr_brazo(hacer, tareas, brazo)
                # el mismo brazo puede aparecer 2 veces en un par NULO:
                # se acumula por posicion, no por nombre
                detalle_par.append({"brazo": brazo, "aciertos": a,
                                    "tareas": det})
                aciertos.setdefault(brazo, []).append(a)
            if p["tipo"] == "AB":
                d = aciertos["ON"][0] - aciertos["OFF"][0]
                d_pares.append(d)
            else:
                d = detalle_par[0]["aciertos"] - detalle_par[1]["aciertos"]
                d_nulos.append(d)
            print("  d_%s = %+d" % (p["tipo"].lower(), d))
            corridas.append({"par": p["idx"], "tipo": p["tipo"],
                             "orden": list(p["orden"]), "d": d,
                             "brazos": detalle_par})
    finally:
        try:
            if getattr(orch, "_llama", None) is not None:
                orch._llama.stop()   # solo el server que arranco este script
        except Exception:
            pass

    res = evaluar_primaria(d_pares, d_nulos, len(tareas))
    print("\nd_nulos = %s | d_pares = %s" % (d_nulos, d_pares))
    print("GATE F1: %s — %s" % (res["veredicto"], res["motivo"]))
    print("(MDE declarado: ~%d tareas / %.0f pp por par; niveles absolutos "
          "entre corridas NO son evidencia)" % (MDE_TAREAS, MDE_PP))

    SALIDA_DIR.mkdir(exist_ok=True)
    (SALIDA_DIR / args.salida).write_text(json.dumps({
        "prereg": "PREREG_LORA_QWYTHOS_20260809.md F1",
        "semilla": args.semilla, "url": args.url,
        "banco_tareas": len(tareas), "heldout_motivo": motivo_heldout,
        "plan": plan, "corridas": corridas, "evaluacion": res,
        "minutos": round((time.time() - t0) / 60, 1),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print("-> %s" % (SALIDA_DIR / args.salida))
    return 0 if res["veredicto"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
