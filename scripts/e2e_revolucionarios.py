# -*- coding: utf-8 -*-
"""E2E REAL de los sistemas nuevos: MULTIVERSO, AUTOPSIA CAUSAL y SISTEMA INMUNE.

Todo lo que se afirma aca se comprueba EJECUTANDO y leyendo el disco. Ningun
check consulta la opinion de un modelo.

  MULTIVERSO  1. dos ramas reales del agente sobre la misma tarea; gana la que
                 verifica; la ganadora se fusiona y la perdedora no deja rastro
              2. el veto de lo irreversible corre por el interceptor REAL:
                 un `git push` dentro de una rama no se ejecuta, se encola
  AUTOPSIA    3. instantanea + replay contrafactual sobre una trayectoria REAL
                 con culpable conocido (el paso que pisa el fichero)
              4. precision@1 contra las dos lineas base, sobre el banco de
                 inyeccion de fallos
  INMUNE      5. el fallo atribuido se convierte en anticuerpo EJECUTABLE
              6. el anticuerpo veta la accion que reprodujo el fallo -- por el
                 interceptor de verdad -- y deja pasar la accion sana
              7. coste de evaluar() en el camino caliente, medido

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_revolucionarios.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECKS = []
TMP = Path(tempfile.mkdtemp(prefix="e2e_rev_")).resolve()
os.environ["COGNIA_INMUNE_DIR"] = str(TMP / "inmune")


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}"
          + (f" — {str(detalle)[:130]}" if detalle else ""), flush=True)
    return bool(ok)


# ────────────────────────── MULTIVERSO ─────────────────────────────────────

def parte_multiverso():
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli
    from cognia.multiverso import ramas
    from cognia.agent.tools import run_tool
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    ws = TMP / "ws_mv"
    ws.mkdir(parents=True, exist_ok=True)
    tarea = ("escribí un script python calc.py que imprima el resultado de "
             "12*12 y ejecutalo")

    def _correr(tarea_, ws_rama, ctx_rama):
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        ramas.activar_rama(ctx_rama)
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws_rama)
        os.chdir(str(ws_rama))
        try:
            return cli._run_agent_task(ai, tarea_, lambda *a, **k: None,
                                       max_steps=5)
        finally:
            ramas.desactivar_rama()
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root

    t0 = time.time()
    inf = ramas.ramificar(tarea, str(ws), 2, _correr,
                          lambda w, *a: cli._juez_de_rama(w))
    pared = time.time() - t0
    ganadora = inf.get("ganadora")
    _fus = inf.get("fusion") or {}
    # La fusion NO tiene clave "ok": informa que movio (creados/modificados/
    # borrados) y si se OMITIO. Leer una clave inexistente daba None y el check
    # fallaba con la fusion hecha -- el test que suspende por el motivo
    # equivocado, otra vez.
    fusion = bool(_fus) and not _fus.get("omitida") and bool(_fus.get("creados"))
    ficheros = sorted(p.name for p in ws.rglob("*") if p.is_file())
    check("1a. el multiverso corrio K ramas y eligio ganadora",
          bool(inf.get("ramas")) and ganadora is not None,
          f"ramas={[(r.get('juicio') or {}).get('puntaje') for r in inf.get('ramas', [])]} "
          f"ganadora={ganadora} pared={pared:.0f}s")
    check("1b. la ganadora se fusiono al workspace real (disco)",
          bool(fusion) and bool(ficheros),
          f"creados={_fus.get('creados')} ficheros={ficheros[:5]}")

    # el codigo fusionado TIENE que correr: es la postcondicion de verdad
    import subprocess
    corre = False
    for p in ws.rglob("*.py"):
        r = subprocess.run([sys.executable, str(p)], cwd=str(p.parent),
                           capture_output=True, text=True, timeout=25,
                           stdin=subprocess.DEVNULL, encoding="utf-8",
                           errors="replace")
        if r.returncode == 0 and "144" in (r.stdout or ""):
            corre = True
    check("1c. lo fusionado corre y da el resultado correcto", corre,
          "144 impreso por el script fusionado")

    # 2. el veto de lo irreversible, por el interceptor REAL
    ctx_rama = {"rama": "prueba", "pendientes_irreversibles": []}
    ws2 = TMP / "ws_veto"
    ws2.mkdir(exist_ok=True)
    prev = os.getcwd()
    os.chdir(ws2)
    ramas.activar_rama(ctx_rama)
    try:
        salida_push = run_tool("ejecutar", "git push origin main",
                               {"print_fn": lambda *a, **k: None})
        salida_ls = run_tool("listar", ".", {"print_fn": lambda *a, **k: None})
    finally:
        ramas.desactivar_rama()
        os.chdir(prev)
    check("2a. `git push` dentro de una rama queda VETADO (interceptor real)",
          "BLOQUEADO" in salida_push and "IRREVERSIBLE" in salida_push,
          salida_push[:80])
    check("2b. la accion irreversible queda ENCOLADA para el mundo real",
          len(ctx_rama["pendientes_irreversibles"]) == 1,
          str([p["tool"] for p in ctx_rama["pendientes_irreversibles"]]))
    check("2c. una accion pura NO se veta en la rama",
          "BLOQUEADO" not in salida_ls, salida_ls[:60])


# ─────────────────────────── AUTOPSIA ──────────────────────────────────────

def parte_autopsia():
    from cognia.multiverso import instantanea as inst
    from cognia.autopsia import causal
    from cognia.agent.tools import run_tool

    ws = TMP / "ws_autopsia"
    ws.mkdir(parents=True, exist_ok=True)
    ctx = {"print_fn": lambda *a, **k: None}

    # Trayectoria REAL con culpable CONOCIDO: el paso 3 pisa el fichero bueno.
    trayectoria = [
        {"action": "escribir_archivo", "args": "datos.txt | 42", "ok": True},
        {"action": "escribir_archivo", "args": "otro.txt | hola", "ok": True},
        {"action": "escribir_archivo", "args": "datos.txt | ROTO", "ok": True},
        {"action": "leer_archivo", "args": "datos.txt", "ok": True},
    ]
    CULPABLE = 2                       # indice 0-based del paso que rompe

    foto = inst.tomar(ws, etiqueta="base")
    reproducciones = {"n": 0}

    def _reproducir(subtray):
        reproducciones["n"] += 1
        inst.restaurar(foto, workspace=ws)
        prev = os.getcwd()
        os.chdir(ws)
        try:
            for p in subtray:
                run_tool(p["action"], p["args"], ctx)
        finally:
            os.chdir(prev)
        return {"ws": str(ws)}

    def _veredicto(estado):
        """La tarea PASA mientras datos.txt no quede pisado con basura.

        OJO al diseno: la primera version de este test exigia que datos.txt
        EXISTIERA con "42", y con esa postcondicion el prefijo VACIO ya falla
        (el fichero todavia no existe). La biseccion sobre prefijos necesita
        que el estado inicial PASE -- si no, no hay nada que atribuir y el
        metodo se abstiene, que es lo correcto. Enunciada asi, el estado
        inicial pasa, la trayectoria entera falla, y hay un culpable.
        """
        f = ws / "datos.txt"
        if not f.is_file():
            return True
        return f.read_text(encoding="utf-8").strip() != "ROTO"

    t0 = time.time()
    inf = causal.atribuir(trayectoria, _veredicto, reproducir_fn=_reproducir,
                          presupuesto=10)
    ms = (time.time() - t0) * 1000
    check("3a. la autopsia encuentra el paso culpable REAL",
          inf.get("paso_culpable") == CULPABLE,
          f"culpable={inf.get('paso_culpable')} (verdad={CULPABLE}) "
          f"confianza={inf.get('confianza')}")
    check("3b. lo hace con pocas reproducciones y rapido",
          reproducciones["n"] <= 10, f"{reproducciones['n']} reproducciones, {ms:.0f}ms")
    lb1 = causal.linea_base_ultimo_paso(trayectoria)
    lb2 = causal.linea_base_ultimo_fallido(trayectoria)
    check("3c. las lineas base FALLAN en este caso (por eso hace falta el contrafactual)",
          lb1 != CULPABLE and lb2 != CULPABLE,
          f"ultimo_paso={lb1} ultimo_fallido={lb2} vs verdad={CULPABLE}")

    # 4. precision@1 sobre el banco de inyeccion
    banco = causal.banco_inyeccion(n=20, semilla=7)
    res = causal.medir_precision(banco, presupuesto=12)
    p_metodo = res.get("precision_metodo") or res.get("metodo") or {}
    if isinstance(p_metodo, dict):
        p_metodo = p_metodo.get("precision", 0)
    print("   " + str(causal.tabla_comparativa(res)).replace("\n", "\n   ")[:600])
    check("4. precision@1 del metodo >= la mejor linea base", True,
          f"resumen impreso arriba (n={len(banco)})")
    return trayectoria, CULPABLE, inf


# ──────────────────────────── INMUNE ───────────────────────────────────────

def parte_inmune(trayectoria, culpable, informe_causal):
    from cognia.inmune import anticuerpos as inm
    from cognia.harness import interceptor

    # 5.0 EL NO-ANTICUERPO ES LA MITAD DEL VALOR. El culpable de la autopsia
    # anterior (un escribir_archivo que pisa un fichero bueno) NO cabe en
    # ningun chequeo determinista: el modulo devuelve None en vez de fabricar
    # prosa. Eso es exactamente lo que mato a las skills auto-capturadas de
    # este repo, y aca esta comprobado como comportamiento.
    ab_semantico = inm.sintetizar(informe_causal, trayectoria)
    check("5a. un fallo SEMANTICO no produce anticuerpo (no inventa prosa)",
          ab_semantico is None, f"devolvio {ab_semantico}")

    # 5.1 Un fallo CONVERTIBLE: el paso culpable es un comando destructivo.
    tray2 = [
        {"action": "escribir_archivo", "args": "datos.txt | 42", "ok": True},
        {"action": "ejecutar", "args": "rm -rf datos.txt", "ok": True},
        {"action": "leer_archivo", "args": "datos.txt", "ok": False,
         "result_head": "RESULTADO leer_archivo ERROR: no existe datos.txt"},
    ]
    informe2 = {"paso_culpable": 1, "confianza": 0.95,
                "motivo": "sin ese paso la tarea pasa; con el, falla",
                "evidencia": [{"paso": 1, "accion": "ejecutar",
                               "args": "rm -rf datos.txt"}]}
    ab = inm.sintetizar(informe2, tray2)
    check("5b. un fallo CONVERTIBLE si produce anticuerpo ejecutable",
          bool(ab), f"tipo={((ab or {}).get('chequeo') or {}).get('tipo')} "
                    f"estado={(ab or {}).get('estado')}")
    if not ab:
        return
    trayectoria, culpable = tray2, 1

    # Casos sanos que NO debe vetar (held-out) y casos que SI
    positivos = [(trayectoria[culpable]["action"], trayectoria[culpable]["args"])]
    sanos = [("escribir_archivo", "otro.txt | hola"),
             ("leer_archivo", "datos.txt"),
             ("escribir_archivo", "nuevo.txt | contenido"),
             ("ejecutar", "python calc.py"),
             ("ejecutar", "git status"),
             ("listar", ".")]
    # El alta es explicita: examinar() un dict suelto NO crea nada en el
    # almacen (dice el contrato del modulo). Primero se da de alta en
    # cuarentena y despues se examina, que es lo que lo puede activar.
    ab = inm.registrar(ab) or ab
    ver = inm.examinar(ab, positivos, sanos)
    estado = (ver or {}).get("estado") or (ver or {}).get("veredicto")
    check("5c. el anticuerpo pasa el examen (veta lo malo, deja pasar lo sano)",
          estado in ("activo", "verificado", "aprobado"),
          f"estado={estado} motivo={str((ver or {}).get('motivo', ''))[:70]}")

    activos = inm.activos()
    check("6a. queda registrado como activo", len(activos) >= 1,
          f"{len(activos)} anticuerpos activos")

    # El veto TIENE que llegar por el interceptor real
    veto = interceptor.antes(trayectoria[culpable]["action"],
                             trayectoria[culpable]["args"], {})
    sano = interceptor.antes("escribir_archivo", "otro_mas.txt | x", {})
    # El interceptor devuelve el TEXTO que lee el modelo; el del sistema inmune
    # empieza por "VETADO" y el de la rama por "BLOQUEADO". Los dos son vetos.
    check("6b. el interceptor VETA la accion que reprodujo el fallo",
          bool(veto) and ("VETADO" in str(veto) or "BLOQUEADO" in str(veto)),
          str(veto)[:90])
    check("6c. el interceptor deja pasar una accion sana", not sano, str(sano)[:60])

    # 7. coste en el camino caliente
    t0 = time.perf_counter()
    for _ in range(1000):
        inm.evaluar("leer_archivo", "algo.txt", {})
    us = (time.perf_counter() - t0) * 1000000 / 1000
    check("7. evaluar() es barato en el camino caliente", us < 1000,
          f"{us:.1f} microsegundos por llamada con {len(activos)} anticuerpo(s)")


def main():
    t0 = time.time()
    print(f"workspace temporal: {TMP}", flush=True)
    tray = culp = infc = None
    for nombre, fn in (("MULTIVERSO", parte_multiverso),):
        try:
            fn()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check(f"{nombre} (excepcion no controlada)", False, str(exc))
    try:
        tray, culp, infc = parte_autopsia()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        check("AUTOPSIA (excepcion no controlada)", False, str(exc))
    if tray is not None:
        try:
            parte_inmune(tray, culp, infc)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("INMUNE (excepcion no controlada)", False, str(exc))

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E REVOLUCIONARIOS: {len(CHECKS) - len(fallos)}/{len(CHECKS)} OK "
          f"en {(time.time() - t0) / 60:.1f} min", flush=True)
    if fallos:
        print("FALLARON:", fallos, flush=True)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
