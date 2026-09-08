# -*- coding: utf-8 -*-
"""E2E con MODELO REAL de la FORJA y de las tareas COTIDIANAS (2026-09-08).

Tres tareas de `cognia hacer` con postcondicion en DISCO (nunca en la prosa):
  1. forja: el agente escribe una herramienta con PRUEBAS, la forja y LA USA en
     la misma tarea -> el manifiesto de la forja tiene la tool (tier staged) y
     la telemetria muestra una llamada a esa tool por su nombre.
  2. documento: escribe una carta en el escritorio propio -> el .txt existe con
     el texto pedido y la tool documento_escribir aparece en la telemetria.
  3. correo: manda un correo (SMTP LOCAL levantado por este script) -> el
     servidor local recibe el mensaje con el asunto pedido.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_forja_cotidiano.py
Salida: 'E2E FORJA+COTIDIANO: N/3 OK'; exit 0 si 3/3.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
RAIZ = Path(__file__).resolve().parents[1]
PY = sys.executable
CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print("  [%s] %s %s" % ("OK" if ok else "FALLO", nombre, ("- " + detalle) if detalle else ""), flush=True)


def hacer(tarea, ws, extra_env=None, timeout=900):
    env = dict(os.environ)
    env.update({"COGNIA_EFIMERO": "1", "PYTHONIOENCODING": "utf-8", "COGNIA_FORJA_DIR": str(ws / "_forja")})
    tel = ws / "tel.jsonl"
    env["COGNIA_TELEMETRIA"] = str(tel)
    env["COGNIA_PARED_S"] = str(timeout - 60)
    if extra_env:
        env.update(extra_env)
    t0 = time.time()
    r = subprocess.run([PY, "-m", "cognia", "hacer", tarea, "--json", "--cwd", str(ws), "--pasos", "40"],
                       cwd=str(RAIZ), env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    print("    (%.0fs, exit %s)" % (time.time() - t0, r.returncode), flush=True)
    tools = []
    if tel.exists():
        for linea in tel.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(linea)
            except Exception:
                continue
            n = ev.get("tool") or ev.get("nombre") or (ev.get("datos") or {}).get("tool")
            if n:
                tools.append(n)
    if not tools:
        # fallback: nombres de tool en stderr/stdout
        import re
        tools = re.findall(r"\b([a-z_]+)\(", r.stderr or "")
    return r, tools


class SMTPLocal:
    def __init__(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.puerto = s.getsockname()[1]
        s.close()
        self.mensajes = []
        self._listo = threading.Event()
        threading.Thread(target=self._correr, daemon=True).start()
        self._listo.wait(5)

    async def _atender(self, r, w):
        w.write(b"220 local ESMTP\r\n")
        await w.drain()
        datos, en_data = b"", False
        while True:
            linea = await r.readline()
            if not linea:
                break
            if en_data:
                if linea.strip() == b".":
                    en_data = False
                    self.mensajes.append(datos)
                    w.write(b"250 OK\r\n")
                else:
                    datos += linea
                await w.drain()
                continue
            c = linea.strip().upper()
            if c.startswith((b"EHLO", b"HELO")):
                w.write(b"250-local\r\n250 8BITMIME\r\n")
            elif c.startswith(b"DATA"):
                en_data = True
                w.write(b"354 go\r\n")
            elif c.startswith(b"QUIT"):
                w.write(b"221 bye\r\n")
                await w.drain()
                w.close()
                return
            else:
                w.write(b"250 OK\r\n")
            await w.drain()

    def _correr(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def main():
            srv = await asyncio.start_server(self._atender, "127.0.0.1", self.puerto)
            self._listo.set()
            async with srv:
                await srv.serve_forever()
        loop.run_until_complete(main())


def main():
    solo = set(a.lstrip("-") for a in sys.argv[1:]) or {"forja", "documento", "correo"}
    base = Path(tempfile.mkdtemp(prefix="cognia_e2e_forja_"))
    print("workspace base:", base)

    # 1. FORJA: escribir, forjar y usar en la misma tarea
    ws1 = base / "forja"
    ws1.mkdir()
    (ws1 / "datos.csv").write_text("nombre,edad,ciudad\nana,30,lima\nluis,25,quito\nmaria,41,cali\n", encoding="utf-8")
    tarea1 = ("Forja una herramienta nueva llamada resumen_csv: escribe el fichero resumen_csv.py siguiendo el contrato "
              "de `forjar plantilla` (DOC, PRUEBAS con prepara/espera, run(args, ctx)) que dado un CSV devuelva "
              "'N filas, M columnas, cabeceras: ...'. Forjala con la tool forjar y, cuando este registrada, USALA "
              "sobre datos.csv y escribe lo que devolvio en resultado.txt.")
    if "forja" not in solo:
        pass
    print("1) forja:", flush=True)
    r1, tools1 = hacer(tarea1, ws1) if "forja" in solo else (None, [])
    man = ws1 / "_forja" / "manifiesto.json"
    entradas = json.loads(man.read_text(encoding="utf-8")) if man.exists() else []
    forjada = next((e for e in entradas if e.get("nombre") == "resumen_csv"), None)
    if "forja" in solo:
        check("forja: resumen_csv en el manifiesto (tier staged/verificada)", forjada and forjada.get("tier") in ("staged", "verificada"),
              ("tier " + str(forjada.get("tier"))) if forjada else "sin manifiesto: " + (r1.stderr or "")[-300:])
    usada = "resumen_csv" in tools1 or (forjada and int(forjada.get("usos_ok", 0)) >= 1)
    res = ws1 / "resultado.txt"
    if "forja" in solo:
      check("forja: la uso (usos_ok>=1 o llamada en telemetria) y dejo resultado.txt con 'filas'",
          usada and res.exists() and "filas" in res.read_text(encoding="utf-8", errors="replace"),
          "usos_ok=%s resultado=%s" % (forjada.get("usos_ok") if forjada else "-", res.read_text(encoding="utf-8", errors="replace")[:80] if res.exists() else "no existe"))

    # 2. DOCUMENTO en el escritorio propio
    ws2 = base / "doc"
    ws2.mkdir()
    tarea2 = ("Escribe una carta breve de agradecimiento (3 frases) para mi abuela en el fichero carta_abuela.txt "
              "usando documento_escribir y abrela en tu escritorio propio para que la vea.")
    print("2) documento:", flush=True)
    r2, tools2 = hacer(tarea2, ws2, timeout=600) if "documento" in solo else (None, [])
    carta = ws2 / "carta_abuela.txt"
    if "documento" in solo:
      check("documento: carta_abuela.txt existe con >= 60 chars y se uso documento_escribir",
          carta.exists() and len(carta.read_text(encoding="utf-8", errors="replace")) >= 60 and "documento_escribir" in tools2,
          "tools=%s" % sorted(set(tools2))[:12])
    try:
        from cognia.agent import app_tools as AT
        AT.cerrar_todas()
    except Exception:
        pass

    # 3. CORREO por SMTP local
    ws3 = base / "correo"
    ws3.mkdir()
    srv = SMTPLocal()
    tarea3 = ("Mandale un correo a dueno@example.com con el asunto 'Informe de la noche' y un cuerpo de dos frases "
              "diciendo que las tareas quedaron hechas. Usa correo_enviar.")
    print("3) correo:", flush=True)
    if "correo" not in solo:
        ok = sum(1 for _n, v in CHECKS if v)
        print("E2E FORJA+COTIDIANO: %d/%d OK" % (ok, len(CHECKS)))
        return 0 if ok == len(CHECKS) else 1
    r3, tools3 = hacer(tarea3, ws3, extra_env={"CORREO_SMTP_HOST": "127.0.0.1", "CORREO_SMTP_PORT": str(srv.puerto),
                                                "CORREO_TLS": "0", "CORREO_DE": "cognia@local"}, timeout=600)
    time.sleep(1)
    crudo = b"\n".join(srv.mensajes).decode("utf-8", "replace")
    check("correo: el SMTP local recibio un mensaje con el asunto pedido",
          bool(srv.mensajes) and "Informe de la noche" in crudo, "mensajes=%d tools=%s" % (len(srv.mensajes), sorted(set(tools3))[:12]))

    ok = sum(1 for _n, v in CHECKS if v)
    print("E2E FORJA+COTIDIANO: %d/%d OK" % (ok, len(CHECKS)))
    return 0 if ok == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
