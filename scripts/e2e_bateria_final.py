# -*- coding: utf-8 -*-
"""BATERÍA E2E FINAL sobre el producto INSTALADO (mandato del dueño 2026-07-08):
corre DENTRO del venv limpio de la instalación (wheel + ~/.cognia del e2e de
instalación), no del repo. Cubre:

  A. Instalación idempotente (re-run de install-model no re-descarga).
  B. Inferencia de comandos (intent.detect): frase libre → agente/tool o chat.
  C. Router del fleet por turno.
  D. Backend real: fleet cargado, identidad→experto, general→base.
  E. /hacer REAL: tareas de agente con POSTCONDICIÓN verificada en el
     workspace (write/append/copy/calc/read/json/count/list).

Uso (lo lanza el driver con el python del venv limpio y COGNIA_HOME seteado):
  <venv_clean>/python.exe e2e_bateria_final.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHECKS = []
T0 = time.time()


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}"
          + (f" — {str(detalle)[:110]}" if detalle else ""), flush=True)


def main():
    from cognia.first_run import apply_config
    apply_config()

    # ── A. instalación idempotente ──
    print("== A. install-model idempotente ==", flush=True)
    from cognia import model_install as mi
    buf = io.StringIO()
    from contextlib import redirect_stdout
    with redirect_stdout(buf):
        res = mi.install_model()
    salida = buf.getvalue()
    check("A1 re-run no re-descarga GGUF", "ya presente" in salida and res.get("gguf"))
    check("A2 re-run no re-descarga server", salida.count("ya presente") >= 2)
    check("A3 fleet re-verificado", res.get("fleet_adapters", 0) >= 1 or
          (Path(res.get("gguf", "")).parent / "adapters.json").is_file())

    # ── B. inferencia de comandos (intent) ──
    print("== B. intent.detect ==", flush=True)
    from cognia.agent.intent import detect
    casos = [
        ("lee el archivo notas.txt", True, "leer_archivo"),
        ("escribí un archivo llamado plan.txt con tres pasos", True, "escribir_archivo"),
        ("agregá la línea 'fin' al final del archivo log.txt", True, "apendar_archivo"),
        ("buscá 'error' en los logs", True, "buscar"),
        ("listá los archivos de la carpeta", True, "listar"),
        ("cuánto es 348 por 12", True, "calcular"),
        ("hola, ¿cómo estás?", False, ""),
        ("¿qué es la fotosíntesis?", False, ""),
        ("explicame la recursión", False, ""),
        ("crea un script que imprima la fecha", True, ""),   # verbo acción genérico
    ]
    ok_b = 0
    for texto, esp_agente, esp_tool in casos:
        it = detect(texto)
        paso = it.needs_agent == esp_agente and (not esp_tool or it.suggested_tool == esp_tool)
        ok_b += paso
        if not paso:
            print(f"    intent MISS: {texto!r} -> {it}", flush=True)
    check(f"B intent {ok_b}/{len(casos)}", ok_b == len(casos))

    # ── C. router del fleet ──
    print("== C. fleet_router ==", flush=True)
    from cognia.agent.fleet_router import expert_for_chat_turn
    casos_r = [("¿quién sos?", "accion"), ("what is your name", "accion"),
               ("¿eres ChatGPT?", "accion"), ("¿cuál es la capital de Perú?", None),
               ("resumí este texto", None), ("hola", None)]
    ok_c = sum(1 for t, e in casos_r if expert_for_chat_turn(t) == e)
    check(f"C router {ok_c}/{len(casos_r)}", ok_c == len(casos_r))

    # ── D. backend real ──
    print("== D. backend real (llama-server del stack instalado) ==", flush=True)
    subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"], capture_output=True)
    from node.llama_backend import LlamaBackend
    b = LlamaBackend.try_load()
    check("D1 backend levanta", b is not None)
    check("D2 fleet cargado", b is not None and b.fleet_experts == ["accion"],
          str(b.fleet_experts if b else None))
    P = ("<|im_start|>system\nEres un asistente útil.<|im_end|>\n"
         "<|im_start|>user\n¿Quién sos?<|im_end|>\n<|im_start|>assistant\n")
    b.activate_expert("accion")
    r_exp = (b.generate(P, max_tokens=60, temperature=0.0) or "")
    check("D3 identidad→experto dice Cognia", "cognia" in r_exp.lower(), r_exp[:90])
    b.activate_expert(None)
    r_base = (b.generate(P, max_tokens=60, temperature=0.0) or "")
    check("D4 base NO dice Cognia", "cognia" not in r_base.lower(), r_base[:90])

    # ── E. /hacer real con postcondiciones ──
    print("== E. /hacer (agent loop real, 8 tareas) ==", flush=True)
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
        ws = Path(tempfile.mkdtemp(prefix="bat_")).resolve()
        if setup:
            setup(ws)
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        logs = []
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: logs.append(str(s)),
                                        max_steps=pasos)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        try:
            return verificar(ws), (str(resp) or "")[:90]
        except Exception as exc:
            return False, f"verify exc: {exc}"

    def _lee(ws, n):
        hits = list(ws.rglob(n))
        return hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""

    tareas = [
        ("E1 escribir", "escribí un archivo llamado nota.txt con el texto exacto: bateria final ok",
         lambda ws: "bateria final ok" in _lee(ws, "nota.txt"), None),
        ("E2 apendar", "agregá la línea 'tercera' al final del archivo bitacora.txt",
         lambda ws: _lee(ws, "bitacora.txt").strip().splitlines()[-1].strip().strip("'\"") == "tercera",
         lambda ws: (ws / "bitacora.txt").write_text("primera\nsegunda\n", encoding="utf-8")),
        ("E3 copiar", "copiá el archivo origen.txt a un archivo llamado copia.txt",
         lambda ws: _lee(ws, "copia.txt") == "contenido unico 777",
         lambda ws: (ws / "origen.txt").write_text("contenido unico 777", encoding="utf-8")),
        ("E4 calcular+guardar", "calculá 17 por 23 y guardá el resultado en resultado.txt",
         lambda ws: "391" in _lee(ws, "resultado.txt"), None),
        ("E5 leer", "leé el archivo dato.txt y decime qué palabra clave contiene",
         lambda ws: True,   # el check real es la respuesta (abajo)
         lambda ws: (ws / "dato.txt").write_text("la palabra clave es zanahoria", encoding="utf-8")),
        ("E6 json", "creá un archivo config.json con la clave modo puesta en rapido",
         lambda ws: json.loads(_lee(ws, "config.json") or "{}").get("modo") == "rapido", None),
        ("E7 contar", "contá cuántas líneas tiene el archivo lista.txt y escribí el número en total.txt",
         lambda ws: "4" in _lee(ws, "total.txt"),
         lambda ws: (ws / "lista.txt").write_text("a\nb\nc\nd\n", encoding="utf-8")),
        ("E8 python", "escribí y ejecutá un script python que imprima la suma de 100 más 250",
         lambda ws: True, None),   # check por respuesta (350)
    ]
    for nombre, tarea, verificar, setup in tareas:
        t1 = time.time()
        ok, resp = hacer(tarea, verificar, setup)
        if nombre == "E5 leer":
            ok = "zanahoria" in resp.lower()
        if nombre == "E8 python":
            ok = "350" in resp
        check(f"{nombre} ({time.time()-t1:.0f}s)", ok, resp)

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nBATERIA FINAL: {len(CHECKS) - len(fallos)}/{len(CHECKS)} checks OK "
          f"en {(time.time()-T0)/60:.1f} min")
    if fallos:
        print("FALLARON:", fallos)
        sys.exit(1)


if __name__ == "__main__":
    main()
