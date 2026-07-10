# -*- coding: utf-8 -*-
"""E2E REAL de tareas programadas en la oficina (mandato dueño 2026-07-09).

Levanta la oficina completa (server + motor con el modelo real), programa una
meta a futuro y verifica el ciclo entero contra la API:
  P1  la meta queda con despierta_ts y el JEFE pre-creado duerme (pendiente)
  P2  el motor NO la toma mientras duerme (sigue pendiente tras 12 s)
  P3  el build 3D servido incluye la feature (camaDeSala/dormido en el bundle)
  P4  editar la hora via POST /api/tarea/despertar
  P5  "despertar ya" -> el motor la TOMA (deja de estar pendiente)

Uso: .\\venv312\\Scripts\\python.exe scripts/e2e_oficina_programada.py
"""
import json
import os
import sys
import tempfile
import time
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre} {('- ' + str(detalle)[:90]) if detalle else ''}",
          flush=True)


def api(puerto, ruta, body=None):
    url = f"http://127.0.0.1:{puerto}{ruta}"
    if body is None:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.load(r)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    from cognia.first_run import apply_config
    apply_config()
    from cognia.oficina.estado import Oficina
    from cognia.oficina.server import crear_server
    from cognia.oficina.motor import Motor
    from cognia.cli import Cognia

    estado_path = os.path.join(tempfile.mkdtemp(prefix="ofi_e2e_"), "estado.json")
    of = Oficina(estado_path)
    print("[e2e] cargando backend real (como python -m cognia.oficina)...", flush=True)
    ai = Cognia()
    motor = Motor(of, ai=ai, poll_s=0.5)
    motor.start()
    srv = crear_server(of, puerto=0)
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        # ── P1: meta programada -> jefe dormido ──
        ts = time.time() + 3600
        r = api(puerto, "/api/meta", {"texto": "escribi un archivo prueba.txt con hola",
                                      "despierta_ts": ts})
        mid = r["id"]
        snap = api(puerto, "/api/estado")
        meta = next(m for m in snap["metas"] if m["id"] == mid)
        jefe = next((t for t in snap["tareas"].values()
                     if t["nivel"] == "jefe" and t.get("meta") == mid), None)
        check("P1 meta programada con despierta_ts", meta.get("despierta_ts") == ts)
        check("P1 jefe pre-creado DURMIENDO", jefe is not None
              and jefe["estado"] == "pendiente" and jefe.get("despierta_ts") == ts,
              jefe and jefe["id"])

        # ── P2: el motor no la toma mientras duerme ──
        time.sleep(12)
        snap = api(puerto, "/api/estado")
        meta = next(m for m in snap["metas"] if m["id"] == mid)
        check("P2 sigue pendiente tras 12s (motor la respeta)",
              meta["estado"] == "pendiente"
              and snap["tareas"][jefe["id"]]["estado"] == "pendiente")

        # ── P3: el build 3D servido trae la feature ──
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/oficina3d/", timeout=10) as rr:
            html = rr.read().decode("utf-8", "replace")
        js = next((p.split('"')[0] for p in html.split('src="')[1:] if ".js" in p), "")
        bundle = ""
        if js:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{js if js.startswith('/') else '/oficina3d/' + js}",
                                        timeout=10) as rr:
                bundle = rr.read().decode("utf-8", "replace")
        check("P3 bundle 3D con dormido+despierta", "dormido" in bundle
              and "despierta" in bundle, f"{js} ({len(bundle)//1024}KB)")

        # ── P4: editar la hora de despertar ──
        ts2 = time.time() + 7200
        ok = api(puerto, "/api/tarea/despertar",
                 {"id": jefe["id"], "despierta_ts": ts2})["ok"]
        snap = api(puerto, "/api/estado")
        check("P4 hora editada via API (tarea Y meta)",
              ok and snap["tareas"][jefe["id"]]["despierta_ts"] == ts2
              and next(m for m in snap["metas"] if m["id"] == mid)["despierta_ts"] == ts2)

        # ── P5: despertar YA -> el motor la toma ──
        api(puerto, "/api/tarea/despertar", {"id": mid, "despierta_ts": None})
        t0 = time.time()
        tomada = False
        while time.time() - t0 < 90:
            snap = api(puerto, "/api/estado")
            meta = next(m for m in snap["metas"] if m["id"] == mid)
            if meta["estado"] != "pendiente":
                tomada = True
                break
            time.sleep(2)
        check("P5 despertada: el motor la tomo", tomada, f"meta -> {meta['estado']}")
    finally:
        motor.stop()
        srv.shutdown()

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E OFICINA PROGRAMADA: {len(CHECKS) - len(fallos)}/{len(CHECKS)} OK")
    if fallos:
        print("FALLARON:", fallos)
        sys.exit(1)


if __name__ == "__main__":
    main()
