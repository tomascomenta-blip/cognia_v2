# -*- coding: utf-8 -*-
"""PRUEBAS DIFÍCILES del goal HÍBRIDO (mandato 2026-07-15) — MODELO REAL.

Ejercita el ruteo híbrido EN VIVO con /hacer real (el mismo _run_agent_task
de producción) y verifica: (a) la modalidad elegida por tarea (mono/agente/
+colonia/+superorganismo, capturada de los [detail]), (b) POSTCONDICIONES
reales en el workspace, (c) que las etapas caras solo despiertan donde
corresponde.

Escalera de dificultad:
  T1 mono          — trivial; NO debe despertar colonia (gate de costo).
  T2 agente        — multi-archivo fácil; postcondición en disco.
  T3 agente+colonia— código DURO (señales algorítmicas); el 3B suele fallar
                     sus visibles → la cascada escala; función importable +
                     asserts ocultos del script.
  T4 superorganismo— código muy duro; se verifica que la etapa 4 DESPIERTA
                     por perfil (sin env) y el resultado es honesto.
  T5 combinada     — goal B tools en vivo (cuaderno+plan+archivo).

Protección hardware (i3 2 cores): un solo server pesado a la vez (lazy-usar-
cerrar ya es el contrato de las etapas), COGNIA_SUPERORG_BUDGET acotado y
timeout por tarea. Corre SOLO (sin suite/otros procesos en paralelo).

Uso: PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_hibrido_dificil.py [--rapido]
     --rapido: salta T4 (superorganismo, la más lenta)
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHECKS = []
T0 = time.time()


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}"
          + (f" — {str(detalle)[:140]}" if detalle else ""), flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ.setdefault("COGNIA_DISABLE_SWARM", "1")
    # presupuesto acotado del superorganismo para el i3 (default 16 gens)
    os.environ.setdefault("COGNIA_SUPERORG_BUDGET", "8")
    os.environ.setdefault("COGNIA_SUPERORG_TIMEOUT_S", "900")

    tmp = Path(tempfile.mkdtemp(prefix="e2e_dificil_"))
    from cognia.cognia import Cognia
    ai = Cognia(db_path=str(tmp / "e2e.db"))
    import cognia.agents.workers.dev_tools as dv
    dv.AGENT_WORKSPACE_ROOT = str(tmp / "ws")
    (tmp / "ws").mkdir(parents=True, exist_ok=True)

    from shattering.orchestrator import ShatteringOrchestrator
    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()
    if getattr(orch, "_llama", None) is None:
        print("ABORT: no hay backend llama (arrancá el server o revisá GGUF)")
        sys.exit(2)
    ai._orchestrator = orch

    from cognia.cli import _run_agent_task, _load_config
    from cognia.agent.hybrid_router import route_profile

    # esfuerzo ACTIVO del config real: el gate de modalidad es de
    # CONSISTENCIA (la modalidad del loop == la prediccion del router bajo
    # el config activo), no un valor fijo — el dueño puede tener /esfuerzo
    # maximo y entonces la escalera se corre a la izquierda (by design).
    esf = _load_config().get("esfuerzo", "medio")
    print(f"esfuerzo activo del config: {esf}", flush=True)

    def correr(tarea, etiqueta):
        """Corre /hacer real capturando los [detail] (modalidad, etapas)."""
        lineas = []

        def _pr(msg):
            lineas.append(str(msg))
            print(f"    | {str(msg)[:120]}", flush=True)
        t1 = time.time()
        res = _run_agent_task(ai, tarea, _pr)
        dur = time.time() - t1
        todo = "\n".join(lineas)
        m = re.search(r"modalidad=(\S+)", todo)
        modalidad = m.group(1) if m else "?"
        esperada = route_profile(tarea, esf)["modalidad"]
        print(f"    [{etiqueta}] modalidad={modalidad} (router predice: "
              f"{esperada}) {dur:.0f}s", flush=True)
        return res, todo, modalidad, esperada, dur

    ws = tmp / "ws"

    # ── T1 mono: trivial, sin etapas caras ─────────────────────────────
    print("== T1 (mono): trivial ==", flush=True)
    res, det, mod, esp, dur = correr("dime la fecha de hoy", "T1")
    check("T1 modalidad=mono y == prediccion del router",
          mod == "mono" and mod == esp, f"{mod} vs {esp}")
    check("T1 sin etapas caras (ni 7B ni q35 ni etapa 4)",
          "7B" not in det and "Etapa 3" not in det and "Etapa 4" not in det)
    # el 3B puede responder sin repetir la fecha textual ("Esa es la fecha
    # de hoy."): el gate es que USO la tool fecha y cerro con respuesta
    check("T1 usó la tool fecha y respondió",
          "ACCION: fecha" in det and bool((res or "").strip()),
          (res or "")[:80])

    # ── T2 agente: multi-archivo fácil con postcondición ───────────────
    print("== T2 (agente): archivos ==", flush=True)
    res, det, mod, esp, dur = correr(
        "crea un archivo saludo.txt con el texto 'hola hibrido' y mostra "
        "su contenido", "T2")
    saludo = (ws / "saludo.txt")
    check("T2 modalidad agente* y == prediccion del router",
          mod.startswith("agente") and mod == esp, f"{mod} vs {esp}")
    check("T2 postcondición: saludo.txt existe con contenido",
          saludo.exists() and "hola" in saludo.read_text(encoding="utf-8",
                                                         errors="replace").lower(),
          str(saludo))

    # ── T3 agente+colonia: código duro (cascada multi-modelo) ──────────
    print("== T3 (colonia): código duro ==", flush=True)
    tarea3 = ("escribe la funcion `spiral_order(matrix)` que recorre una "
              "matrix en espiral (graph traversal in-place, binary search "
              "no, dynamic program no): devuelve la lista de elementos en "
              "orden espiral horario. edge case: matriz vacía → []. "
              "Ejemplos: spiral_order([[1,2],[3,4]]) == [1,2,4,3], "
              "spiral_order([[1,2,3],[4,5,6],[7,8,9]]) == [1,2,3,6,9,8,7,4,5]")
    res, det, mod, esp, dur = correr(tarea3, "T3")
    check("T3 modalidad incluye colonia y == prediccion",
          "colonia" in mod and mod == esp, f"{mod} vs {esp}")
    fn = ws / "spiral_order.py"
    codigo_ok = False
    if fn.exists():
        # asserts OCULTOS del script (no vistos por el modelo)
        prueba = (
            "import sys; sys.path.insert(0, r'%s')\n"
            "from spiral_order import spiral_order\n"
            "assert spiral_order([[1,2],[3,4]]) == [1,2,4,3]\n"
            "assert spiral_order([[1,2,3],[4,5,6],[7,8,9]]) == [1,2,3,6,9,8,7,4,5]\n"
            "assert spiral_order([]) == []\n"
            "assert spiral_order([[7]]) == [7]\n"
            "print('OCULTOS_PASS')\n" % str(ws))
        r = subprocess.run([sys.executable, "-c", prueba],
                           capture_output=True, text=True, timeout=30)
        codigo_ok = "OCULTOS_PASS" in (r.stdout or "")
        detalle3 = (r.stdout or r.stderr or "")[:100]
    else:
        detalle3 = "no se escribió spiral_order.py"
    check("T3 postcondición: función pasa asserts OCULTOS", codigo_ok, detalle3)

    # ── T4 superorganismo: muy duro, la etapa 4 despierta por perfil ────
    if "--rapido" not in sys.argv:
        print("== T4 (superorganismo): muy duro ==", flush=True)
        assert not os.environ.get("COGNIA_SUPERORGANISMO"), \
            "T4 debe correr SIN env: el perfil decide"
        tarea4 = ("escribe la funcion `decode_ways(s)` con dynamic program "
                  "y memoiz sobre el string: cuenta de cuántas formas se "
                  "decodifica un string de dígitos donde '1'-'26' mapean a "
                  "'A'-'Z', in-place sin importar librerías, edge case de "
                  "ceros ('06' → 0, '0' → 0), overflow no aplica. eficiente "
                  "O(n). Ejemplos: decode_ways('12') == 2, "
                  "decode_ways('226') == 3, decode_ways('06') == 0")
        res, det, mod, dur = correr(tarea4, "T4")
        check("T4 modalidad incluye superorganismo (perfil, sin env)",
              "superorganismo" in mod, mod)
        fn4 = ws / "decode_ways.py"
        ok4, det4 = False, "no se escribió decode_ways.py"
        if fn4.exists():
            prueba4 = (
                "import sys; sys.path.insert(0, r'%s')\n"
                "from decode_ways import decode_ways\n"
                "assert decode_ways('12') == 2\n"
                "assert decode_ways('226') == 3\n"
                "assert decode_ways('06') == 0\n"
                "assert decode_ways('0') == 0\n"
                "assert decode_ways('11106') == 2\n"
                "print('OCULTOS_PASS')\n" % str(ws))
            r = subprocess.run([sys.executable, "-c", prueba4],
                               capture_output=True, text=True, timeout=30)
            ok4 = "OCULTOS_PASS" in (r.stdout or "")
            det4 = (r.stdout or r.stderr or "")[:100]
        # honestidad: si las etapas no lo resolvieron, el FALLO honesto vale
        # como dato (se reporta); el gate duro es que la etapa 4 DESPIERTE.
        check("T4 resultado: asserts ocultos", ok4, det4)

    # ── T5 combinada: goal B tools dentro de /hacer ─────────────────────
    print("== T5 (combinada): cuaderno+plan+archivo ==", flush=True)
    # tarea natural (sin forzar una tool por nombre): la corrida 1 mostró
    # que "usa la herramienta plan para..." empuja al 3B a un meta-loop de
    # `plan crear` malformado → corte por no-progreso (cierre honesto OK,
    # pero el deliverable no salía; el plan ya se probó e2e en la batería)
    res, det, mod, esp, dur = correr(
        "escribe un archivo informe.txt que contenga el texto "
        "'clave HIBRIDO-99', y despues anota resultado_final | HIBRIDO-99 "
        "en la memoria de trabajo", "T5")
    informe = ws / "informe.txt"
    check("T5 postcondición: informe.txt contiene la clave",
          informe.exists() and "HIBRIDO-99" in informe.read_text(
              encoding="utf-8", errors="replace"),
          str(informe) if informe.exists() else "no existe")

    # ── telemetría: la corrida quedó registrada con modalidad ───────────
    tele = ROOT / "cognia" / "agent" / "generated_tools" / "_bon_telemetry.jsonl"
    ok_tele = False
    if tele.exists():
        lineas = tele.read_text(encoding="utf-8").strip().splitlines()
        try:
            ult = json.loads(lineas[-1])
            ok_tele = "modalidad" in ult and "esfuerzo" in ult
        except Exception:
            pass
    check("telemetría BoN registra modalidad/esfuerzo", ok_tele)

    total = len(CHECKS)
    ok = sum(1 for _, o in CHECKS if o)
    print(f"\n== RESULTADO: {ok}/{total} en {(time.time()-T0)/60:.1f} min ==",
          flush=True)
    for n, o in CHECKS:
        if not o:
            print(f"  FALLO: {n}", flush=True)
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
