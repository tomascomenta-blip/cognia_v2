# -*- coding: utf-8 -*-
"""Smoke e2e del motor de workflows + worker + RLM ruteado (contrato 2026-08-11).

POR QUE: los tests del motor (test_workflows_engine.py) guionan el completar
y jamas tocan un modelo; este smoke es la pieza que prueba las 4 patas contra
el backend REAL: (1) agente() con schema devuelve JSON conforme, (2) el rol
'worker' del summoner levanta (o reporta por que no: eso es DATO, no fallo),
(3) paralelo() con cap 2 solapa dos agentes de verdad, (4) el modo RLM con
worker=True rutea los hijos y el informe DICE por donde salieron.

El pajar de la seccion 4 es determinista (seed 20260811): misma corrida,
mismo pajar, mismas agujas — un FAIL es comparable con el anterior. Acierto
ESTRICTO: el token hex textual en la respuesta (la leccion del campo de
acierto sin declarar: con criterio permisivo el banco no decide nada).

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_workflows_smoke.py
Salida: PASS/FAIL por seccion + presupuesto gastado (PresupuestoTokens real).
Exit: 0 si las 4 secciones PASS; 1 si alguna FAIL; 3 sin backend;
      4 sin cognia.agent.workflows (el motor del WP2 no esta en el arbol).
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SEED = 20260811
OBJETIVO_CHARS = 100_000
HEALTH_TIMEOUT = 5
# Presupuesto holgado: el smoke mide funcionamiento, no eficiencia; un corte
# por presupuesto aca seria un FAIL falso. Se REPORTA el gasto real al final.
PRESUPUESTO_TOKENS = 200_000

# Nombres y fracciones fijos (no sorteados): la pregunta se arma por nombre y
# tiene que ser identica entre corridas. Bordes y medio, como el smoke RLM.
_NOMBRES = ["Amaranta", "Baltasar", "Casilda"]
_FRACCIONES = [0.15, 0.50, 0.85]

_PALABRAS = ("sistema modelo contexto ventana memoria indice registro "
             "proceso archivo modulo bitacora medidor informe corrida "
             "verificacion presupuesto fragmento respuesta pregunta "
             "resultado servidor cliente linea trozo patron origen "
             "cobertura union limite guarda bucle turno paso herramienta "
             "prueba banco relleno parrafo").split()


def _generar_pajar():
    """(texto ~100k chars, [(nombre, token), ...]) determinista, seed fijo.

    Relleno de frases variadas (una pared repetida se comprime en la ventana
    y el smoke dejaria de medir busqueda), agujas insertadas de atras hacia
    adelante para no correr los indices pendientes.
    """
    random.seed(SEED)
    agujas = [(n, "".join(random.choice("0123456789abcdef") for _ in range(8)))
              for n in _NOMBRES]
    lineas, acum = [], 0
    while acum < OBJETIVO_CHARS:
        frase = " ".join(random.choice(_PALABRAS)
                         for _ in range(random.randint(8, 14)))
        linea = frase.capitalize() + "."
        lineas.append(linea)
        acum += len(linea) + 1
        if random.random() < 0.2:
            lineas.append("")
            acum += 1
    for frac, (nombre, token) in sorted(zip(_FRACCIONES, agujas),
                                        reverse=True):
        idx = int(len(lineas) * frac)
        lineas.insert(idx, f"El codigo de acceso de {nombre} es {token}")
    return "\n".join(lineas), agujas


def _salud_backend(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health",
                                    timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    from cognia.first_run import apply_config
    apply_config()
    from cognia.agent.model_profiles import url_del_backend
    url = url_del_backend()
    if not _salud_backend(url):
        print(f"SIN BACKEND: {url}/health no responde en {HEALTH_TIMEOUT}s. "
              "Levanta la flota (scripts/servir_flota.py) y reintenta.",
              flush=True)
        sys.exit(3)

    # Import PEREZOSO del motor (WP2): este smoke se programa contra el
    # contrato congelado; si el motor no esta en el arbol el fallo tiene que
    # ser un mensaje claro con exit propio, no un traceback.
    try:
        from cognia.agent import workflows as wf
    except ImportError as exc:
        print("SIN MOTOR: no se pudo importar cognia.agent.workflows "
              f"({exc}). El motor del WP2 no esta en el arbol; este smoke "
              "lo necesita para las secciones 1 y 3.", flush=True)
        sys.exit(4)

    secciones = []          # (nombre, ok: bool, nota)
    c = wf.corrida("e2e-smoke", presupuesto_tokens=PRESUPUESTO_TOKENS)

    # ── 1. agente() con schema real contra el cerebro ──────────────────
    print("\n[1] agente() con schema contra el cerebro", flush=True)
    schema = {"type": "object",
              "properties": {"respuesta": {"type": "string"},
                             "numero": {"type": "integer"}},
              "required": ["respuesta", "numero"]}
    t1 = time.time()
    out1 = wf.agente(c, "Responde un saludo corto en 'respuesta' y el "
                        "entero 7 en 'numero'.", schema)
    pared1 = time.time() - t1
    ok1 = (isinstance(out1, dict) and "_error" not in out1
           and isinstance(out1.get("respuesta"), str)
           and isinstance(out1.get("numero"), int)
           and not isinstance(out1.get("numero"), bool))
    print(f"    salida: {str(out1)[:200]}", flush=True)
    print(f"    conforme al schema: {ok1} ({pared1:.1f}s)", flush=True)
    secciones.append(("agente con schema", ok1, f"{pared1:.1f}s"))

    # ── 2. worker REAL via summoner (dato, no gate) ────────────────────
    print("\n[2] summoner.ensure('worker')", flush=True)
    worker_url = ""
    try:
        from cognia import summoner
        resw = summoner.ensure("worker", evictar=False)
        worker_url = str(resw.get("url") or "")
        print(f"    worker arriba: {worker_url} "
              f"(modelo {resw.get('modelo')}, frio "
              f"{resw.get('arranque_frio')})", flush=True)
    except Exception as exc:
        # No es fallo del smoke: es el DATO de que esta maquina/momento no
        # tiene VRAM o rol para el worker; las secciones 3 y 4 siguen con
        # el cerebro y lo reportan.
        print(f"    worker no disponible: {exc} -- sigo sin worker "
              "(dato, no fallo)", flush=True)
    secciones.append(("worker via summoner", True,
                      worker_url or "sin worker (degradado)"))

    # ── 3. paralelo cap 2 con dos agente() ─────────────────────────────
    print("\n[3] paralelo(cap=2) con dos agente()", flush=True)
    roles = ["", "worker"] if worker_url else ["", ""]

    def _mide(rol):
        def _thunk():
            t = time.time()
            r = wf.agente(c, "Responde exactamente con la palabra: listo",
                          rol=rol, max_tokens=1024)
            return (time.time() - t, r)
        return _thunk

    t3 = time.time()
    resultados = wf.paralelo([_mide(r) for r in roles], cap=2)
    pared3 = time.time() - t3
    ok3 = True
    for rol, res in zip(roles, resultados):
        etiqueta = rol or "cerebro"
        if res is None:
            print(f"    [{etiqueta}] None (fallo o timeout)", flush=True)
            ok3 = False
            continue
        pared_i, salida = res
        fallo = isinstance(salida, dict) and "_error" in salida
        if fallo:
            ok3 = False
        print(f"    [{etiqueta}] pared {pared_i:.1f}s -> "
              f"{str(salida)[:120]}", flush=True)
    print(f"    pared total: {pared3:.1f}s", flush=True)
    secciones.append(("paralelo cap 2", ok3,
                      f"total {pared3:.1f}s ({'+'.join(r or 'cerebro' for r in roles)})"))

    # ── 4. RLM con worker=True sobre un pajar chico ────────────────────
    print("\n[4] RLM worker=True sobre pajar de ~100k chars", flush=True)
    from cognia.agent.rlm import correr_rlm
    texto, agujas = _generar_pajar()
    ruta = Path(tempfile.mkdtemp(prefix="wf_smoke_")) / "pajar.txt"
    ruta.write_text(texto, encoding="utf-8")
    print(f"    pajar: {len(texto):,} chars | {len(agujas)} agujas | {ruta}",
          flush=True)
    elegidas = [agujas[0], agujas[2]]       # inicio y final del pajar
    aciertos, informes_ok = 0, True
    for nombre, token in elegidas:
        t4 = time.time()
        res = correr_rlm(f"cual es el codigo de acceso de {nombre}?",
                         str(ruta), url=url, worker=True, print_fn=print)
        texto_resp = str(res.get("texto") or "")
        ok = token in texto_resp            # ESTRICTO: token textual
        aciertos += 1 if ok else 0
        informe = res.get("informe") or ""
        print(f"    [{'PASS' if ok else 'FAIL'}] {nombre} "
              f"({time.time() - t4:.0f}s) esperado {token} -> "
              f"{texto_resp[:120]}", flush=True)
        print(informe, flush=True)
        if worker_url and "hijos via: " + worker_url not in informe:
            # Si el worker levanto, el informe TIENE que decir que los
            # hijos salieron por el (":8082"); callarselo seria medir un
            # modo distinto al contratado.
            informes_ok = False
            print(f"    INVARIANTE ROTA: el informe no dice "
                  f"'hijos via: {worker_url}'", flush=True)
    ok4 = aciertos == len(elegidas) and informes_ok
    secciones.append(("rlm con worker", ok4,
                      f"{aciertos}/{len(elegidas)} aciertos"))

    # ── resumen ────────────────────────────────────────────────────────
    print("\nRESUMEN e2e workflows:", flush=True)
    for nombre, ok, nota in secciones:
        print(f"  [{'PASS' if ok else 'FAIL'}] {nombre} -- {nota}",
              flush=True)
    print(f"presupuesto gastado (corrida '{c.nombre}'): "
          f"{c.presupuesto.gastado():,} de {PRESUPUESTO_TOKENS:,} tokens",
          flush=True)
    sys.exit(0 if all(ok for _, ok, _ in secciones) else 1)


if __name__ == "__main__":
    main()
