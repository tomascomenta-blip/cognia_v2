# -*- coding: utf-8 -*-
"""BATERÍA E2E — goal HÍBRIDO (mandato 2026-07-15). Partes SIN modelo real.

  1. Goal B (9 módulos nativos, API real + archivos reales):
     events / sentinel / code_graph / analytics / converters /
     reminders-recurrentes / notebook / oficina / http_get.
  2. Herramientas previas del agente vía run_tool REAL: archivos, git,
     calcular, memoria/KG episódica, plan (patrón OpenManus), crear_flujo,
     escena LCD (planner de reglas cero-LLM), delegación (wiring).
  3. Comandos slash: REPL real en subproceso (stdin piped), cada comando en
     forma segura (sin args). Gate: cero Traceback y cierre limpio.

Aislamiento (lección incidente 2026-07-05): DB en tmp (Cognia(db_path=tmp)),
workspace del agente en tmp, reminders en tmp. Solo lectura sobre datos prod
(analytics/telemetría/git).

Las partes CON modelo real corren aparte: scripts/e2e_happy_path.py (5/5
obligatorio) + pruebas difíciles del goal (ruteo híbrido en vivo).

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_goal_hibrido.py [--sin-repl]
"""
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
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
          + (f" — {str(detalle)[:130]}" if detalle else ""), flush=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    tmp = Path(tempfile.mkdtemp(prefix="e2e_hibrido_"))
    os.environ.setdefault("COGNIA_DISABLE_SWARM", "1")

    # AI real con DB AISLADA + workspace del agente en tmp
    from cognia.cognia import Cognia
    ai = Cognia(db_path=str(tmp / "e2e.db"))
    import cognia.agents.workers.dev_tools as dv
    dv.AGENT_WORKSPACE_ROOT = str(tmp / "ws")
    ctx = {"ai": ai, "agent_state": {}}
    from cognia.agent.tools import run_tool

    # ══ PARTE 1 — GOAL B ═══════════════════════════════════════════════
    print("== 1. GOAL B: módulos nativos ==", flush=True)

    # 1.1 events: bus pub/sub + emisión real desde run_tool
    from cognia.events import subscribe, unsubscribe, emit
    vistos = []
    cb = lambda ev: vistos.append(ev)
    subscribe("tool.ejecutada", cb)
    emit("e2e.ping", valor=42)
    run_tool("fecha", "", ctx)
    unsubscribe("tool.ejecutada", cb)
    check("1.1 events: run_tool emite tool.ejecutada al bus",
          any(e.get("datos", {}).get("nombre") == "fecha" for e in vistos)
          or any("fecha" in str(e) for e in vistos), str(vistos[:1]))

    # 1.2 sentinel: allow / block / confirm + e2e vía tool ejecutar
    from cognia.agent.sentinel import clasificar_shell
    ok_cls = (clasificar_shell("git status")[0] == "allow"
              and clasificar_shell("rm -rf /x_e2e_inexistente")[0] == "block"
              and clasificar_shell("regedit /s algo.reg")[0] == "confirm")
    check("1.2a sentinel: clasificación allow/block/confirm", ok_cls)
    out = run_tool("ejecutar", "echo hola_sentinel", ctx)
    check("1.2b sentinel: allowlist deja pasar echo", "hola_sentinel" in out, out)
    out = run_tool("ejecutar", "rm -rf /x_e2e_inexistente", ctx)
    check("1.2c sentinel: bloquea destructivo (no ejecuta)",
          "hola" not in out and ("BLOQUE" in out.upper() or "bloque" in out
                                 or "block" in out.lower()), out)

    # 1.3 code_graph: AST→KG sobre paquete real chiquito en tmp
    paq = tmp / "paq_e2e"
    paq.mkdir()
    (paq / "__init__.py").write_text("", encoding="utf-8")
    (paq / "b.py").write_text("def util():\n    return 1\n", encoding="utf-8")
    (paq / "a.py").write_text("from paq_e2e import b\n\n"
                              "def usa():\n    return b.util()\n",
                              encoding="utf-8")
    from cognia.knowledge.code_graph import indexar_codigo, dependencias
    res = indexar_codigo(raiz=tmp, kg=ai.kg, paquetes=["paq_e2e"])
    deps = dependencias("paq_e2e.a", kg=ai.kg)
    check("1.3 code_graph: indexa e infiere import a→b",
          res.get("modulos", 0) >= 2 and any("paq_e2e.b" in d for d in deps),
          f"{res} deps={deps}")

    # 1.4 analytics: panel real (lectura sobre telemetría prod, read-only)
    from cognia.analytics.panel import panel, render_texto
    p = panel()
    texto = render_texto(p)
    check("1.4 analytics: panel agrega fuentes y renderiza",
          isinstance(p, dict) and len(texto) > 50, texto.splitlines()[0][:80])

    # 1.5 converters: HTML/CSV/JSON → texto
    from cognia.converters import convertir_a_texto, html_a_texto
    fh = tmp / "doc.html"
    fh.write_text("<html><body><h1>Título E2E</h1><p>párrafo uno</p>"
                  "<script>skip()</script></body></html>", encoding="utf-8")
    fc = tmp / "datos.csv"
    fc.write_text("col1,col2\nuno,dos\n", encoding="utf-8")
    fj = tmp / "obj.json"
    fj.write_text('{"clave": "valor_e2e"}', encoding="utf-8")
    t_html = convertir_a_texto(fh)
    t_csv = convertir_a_texto(fc)
    t_json = convertir_a_texto(fj)
    check("1.5 converters: html/csv/json a texto limpio",
          "Título E2E" in t_html and "skip()" not in t_html
          and "uno" in t_csv and "valor_e2e" in t_json)

    # 1.6 reminders recurrentes: create(recur=daily) + re-agenda al disparar
    from cognia.reminders.reminder_manager import (ReminderManager,
                                                   _proxima_ocurrencia)
    rm = ReminderManager(db_path=str(tmp / "rem.db"))
    try:
        r = rm.create(user_id="e2e", title="regar plantas",
                      fire_at=time.time() - 5, recur="daily")
        rm._check_and_fire()   # dispara y debe re-agendar la próxima
        pend = rm.get_pending("e2e")
        prox = _proxima_ocurrencia(time.time() - 5, "daily", time.time())
        check("1.6 reminders: daily re-agenda al disparar",
              r.get("recur") == "daily" and len(pend) == 1
              and pend[0]["fire_at"] > time.time()
              and prox > time.time(), f"pendientes={len(pend)}")
    finally:
        rm.stop()

    # 1.7 notebook: nota + fuente ingerida + consulta RAG (DB aislada)
    from cognia.notebook import Cuaderno
    cua = Cuaderno(ai=ai)
    nid = cua.anotar("la clave de la demo es cuaderno_e2e_77")
    fsrc = tmp / "fuente.txt"
    fsrc.write_text("El protocolo secreto del e2e se llama HIBRIDO-77 y "
                    "vive en el cuaderno. " * 8, encoding="utf-8")
    ing = cua.agregar_fuente(str(fsrc))
    hits = cua.consultar("protocolo secreto del e2e")
    r = cua.resumen()
    check("1.7 notebook: nota+fuente+consulta RAG",
          nid and "error" not in ing and r["fuentes"] >= 1
          and any("HIBRIDO-77" in h["texto"] for h in hits),
          f"notas={r['notas']} fuentes={r['fuentes']} hits={len(hits)}")

    # 1.8 oficina: roster/departamentos reales del manifest
    from cognia.oficina.identidad import roster, departamentos, recomendar_modelo
    rs, deps_of = roster(), departamentos()
    check("1.8 oficina: roster+departamentos+modelo por tool",
          len(rs) >= 3 and len(deps_of) >= 2
          and isinstance(recomendar_modelo("generar_codigo"), str),
          f"{len(rs)} roles, {len(deps_of)} deptos")

    # 1.9 http_get contra server local real (sin red externa)
    class _Srv(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            body = ("<html><body><h1>página e2e</h1><p>contenido "
                    "http_e2e_ok</p></body></html>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    httpd = http.server.HTTPServer(("127.0.0.1", puerto), _Srv)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        out = run_tool("http_get", f"http://127.0.0.1:{puerto}/", ctx)
        check("1.9 http_get: descarga y extrae texto limpio",
              "http_e2e_ok" in out and "<p>" not in out, out[:100])
    finally:
        httpd.shutdown()

    # ══ PARTE 2 — HERRAMIENTAS PREVIAS (run_tool real) ═══════════════════
    print("== 2. Herramientas previas del agente ==", flush=True)

    # 2.1 archivos: escribir → apendar → leer → copiar → listar → contar
    run_tool("escribir_archivo", "nota.txt | línea uno", ctx)
    run_tool("apendar_archivo", "nota.txt | línea dos", ctx)
    out = run_tool("leer_archivo", "nota.txt", ctx)
    run_tool("copiar_archivo", "nota.txt | copia.txt", ctx)
    lst = run_tool("listar", "", ctx)
    cnt = run_tool("contar_lineas", "nota.txt", ctx)
    check("2.1 archivos: ciclo escribir/apendar/leer/copiar/listar/contar",
          "línea uno" in out and "línea dos" in out
          and "copia.txt" in lst and "2" in cnt)

    # 2.2 buscar + arbol
    bus = run_tool("buscar", "línea dos", ctx)
    arb = run_tool("arbol", "", ctx)
    check("2.2 buscar+arbol sobre el workspace",
          "nota.txt" in bus and "nota.txt" in arb)

    # 2.3 validadores + calcular + fecha
    okv = run_tool("py_validar", "nota_py.py | def f():\n    return 1", ctx)
    ruta_json = tmp / "ws" / "v.json"
    ruta_json.parent.mkdir(parents=True, exist_ok=True)
    ruta_json.write_text('{"a": 1}', encoding="utf-8")
    okj = run_tool("json_validar", "v.json", ctx)
    calc = run_tool("calcular", "(3+4)*5", ctx)
    fecha = run_tool("fecha", "", ctx)
    check("2.3 py_validar/json_validar/calcular/fecha",
          "ERROR" not in okv and "ERROR" not in okj and "35" in calc
          and "202" in fecha, f"{okv[:40]} | {okj[:40]} | {calc[:40]}")

    # 2.4 git (solo lectura sobre el repo real)
    ge = run_tool("git_estado", "", ctx)
    gl = run_tool("git_log", "", ctx)
    check("2.4 git_estado+git_log", "ERROR" not in ge and len(gl) > 20)

    # 2.5 memoria episódica + KG (DB aislada)
    run_tool("memorizar", "El proyecto e2e híbrido usa el color turquesa "
                          "para su bandera oficial", ctx)
    rec = run_tool("recordar", "color de la bandera del proyecto", ctx)
    ka = run_tool("kg_agregar", "cognia | tiene | ruteo híbrido", ctx)
    kb = run_tool("kg_buscar", "cognia", ctx)
    check("2.5 memorizar/recordar + kg_agregar/kg_buscar",
          "turquesa" in rec and "ERROR" not in ka and "híbrido" in kb,
          f"{rec[:60]} | {kb[:60]}")

    # 2.6 anotar/notas + cuaderno (tool)
    run_tool("anotar", "resultado intermedio e2e: 123", ctx)
    nts = run_tool("notas", "", ctx)
    cn = run_tool("cuaderno", "nota | apunte vía tool e2e", ctx)
    cv = run_tool("cuaderno", "ver |", ctx)
    check("2.6 anotar/notas + cuaderno tool",
          "123" in nts and "ERROR" not in cn and "notas" in cv.lower())

    # 2.7 plan (patrón OpenManus: artefacto mutable)
    from cognia.agent.tool_synthesis import load_generated_tools  # registra extras
    pc = run_tool("plan", "crear 1. investigar\n2. implementar\n3. verificar", ctx)
    pm = run_tool("plan", "marcar 1 hecho", ctx)
    pv = run_tool("plan", "ver", ctx)
    check("2.7 plan OpenManus: crear/marcar/ver",
          "ERROR" not in pc and "ERROR" not in pm and "investigar" in pv, pv[:80])

    # 2.8 crear_flujo (DAG n8n desde NL, determinista)
    cf = run_tool("crear_flujo", "leer nota.txt y luego contar sus líneas", ctx)
    check("2.8 crear_flujo: organiza DAG de pasos", "pasos" in cf and "ERROR" not in cf,
          cf[:80])

    # 2.9 LCD: escena estructurada con planner de reglas (cero LLM) + render
    from cognia.lcd.tools_lcd import load_lcd_tools
    load_lcd_tools()
    ec = run_tool("escena_crear", "un circulo rojo arriba de un cuadrado azul", ctx)
    eq = run_tool("escena_consultar", "", ctx)
    png = tmp / "escena_e2e.png"
    er = run_tool("render_aprox", str(png), ctx)
    check("2.9 LCD: escena_crear/consultar/render_aprox",
          "ERROR" not in ec and "objetos" in eq
          and ("ERROR" not in er and png.exists()),
          f"{ec[:70]}")

    # 2.10 delegar_subtarea: wiring runner + rol
    ctx_d = dict(ctx)
    ctx_d["_run_agent"] = lambda sub, allowed_tools=None, max_steps=None, \
        delegation_depth=0: f"sub-agente hizo: {sub[:30]}"
    dg = run_tool("delegar_subtarea", "investigador | busca datos de prueba", ctx_d)
    check("2.10 delegar_subtarea: despacha al sub-agente por rol",
          "sub-agente hizo" in dg, dg[:80])

    # 2.11 tools sintetizadas (HERMES) cargables
    n_gen = load_generated_tools()
    check("2.11 HERMES: tools auto-generadas cargan sin romper",
          isinstance(n_gen, int), f"{n_gen} tools")

    # ══ PARTE 3 — COMANDOS SLASH (REPL real piped) ═══════════════════════
    if "--sin-repl" not in sys.argv:
        print("== 3. Comandos slash (REPL subproceso) ==", flush=True)
        from cognia.cli import COMMANDS
        # skip: destructivos / red externa / servidores / pesados-LLM / salida
        SKIP = {"/salir", "/update", "/mesh_iniciar", "/mesh_peer",
                "/mesh_publicar", "/backup", "/exportar-todo", "/dormir",
                "/distill run", "/worktree", "/quiz", "/template",
                "/resume", "/historial-limpiar", "/limpiar-sesion",
                "/olvido", "/cognia-olvida", "/web-fetch", "/web-buscar",
                "/buscar-web", "/monitor", "/reflexion-profunda",
                "/inicio-dia", "/reporte-completo", "/debate"}
        cmds = [c for c in sorted(COMMANDS) if c not in SKIP]
        stdin_txt = "\n".join(cmds) + "\n/salir\n"
        env = dict(os.environ, PYTHONUTF8="1", COGNIA_DISABLE_SWARM="1")
        t1 = time.time()
        proc = subprocess.run(
            [sys.executable, "-m", "cognia"],
            input=stdin_txt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
            cwd=str(ROOT), timeout=1800)
        salida = (proc.stdout or "") + (proc.stderr or "")
        tracebacks = salida.count("Traceback (most recent call last)")
        check(f"3.1 REPL procesa {len(cmds)} comandos sin crash "
              f"({time.time()-t1:.0f}s)",
              proc.returncode == 0 and tracebacks == 0,
              f"rc={proc.returncode} tracebacks={tracebacks}")
        check("3.2 REPL cerró limpio con /salir",
              "hasta luego" in salida.lower() or "adios" in salida.lower()
              or proc.returncode == 0)
        print(f"    (skip declarado: {len(SKIP)} comandos destructivos/red/"
              f"LLM-pesado)", flush=True)
        if tracebacks:
            # volcar contexto del primer traceback para diagnóstico
            i = salida.find("Traceback (most recent call last)")
            print(salida[max(0, i - 400):i + 600], flush=True)

    # ══ resumen ══════════════════════════════════════════════════════════
    total = len(CHECKS)
    ok = sum(1 for _, o in CHECKS if o)
    print(f"\n== RESULTADO: {ok}/{total} en {time.time()-T0:.0f}s ==", flush=True)
    for n, o in CHECKS:
        if not o:
            print(f"  FALLO: {n}", flush=True)
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
