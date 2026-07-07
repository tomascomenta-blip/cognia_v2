"""E2E REAL de la oficina: arranca server+motor con el 3B, encarga una meta
chica, espera el flujo jefe→director→trabajador y verifica el resultado.

Correr:  .\\venv312\\Scripts\\python.exe -m cognia.oficina.e2e_oficina
Sale 0 si la meta termina 'hecha' y el flujo tuvo los 3 niveles; imprime el
estado final. Es LENTO (3B local ~8 tok/s): presupuesto ~20 min.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

BUDGET_S = 20 * 60


def _post(base, ruta, obj):
    req = urllib.request.Request(base + ruta, data=json.dumps(obj).encode(),
                                 method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _get(base, ruta):
    return json.loads(urllib.request.urlopen(base + ruta, timeout=10).read())


def main():
    from cognia.oficina.estado import Oficina
    from cognia.oficina.server import crear_server
    from cognia.oficina.motor import Motor
    from cognia.cli import Cognia

    workdir = tempfile.mkdtemp(prefix="oficina_e2e_")
    os.chdir(workdir)
    print(f"[e2e] workdir: {workdir}", flush=True)

    of = Oficina(os.path.join(workdir, "estado.json"))
    print("[e2e] cargando Cognia() (backend real)...", flush=True)
    ai = Cognia()
    motor = Motor(of, ai=ai)
    motor.start()
    srv = crear_server(of, puerto=0)
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{puerto}"
    print(f"[e2e] dashboard: {base}", flush=True)

    meta = ("Crea un archivo llamado saludo.txt que contenga exactamente una "
            "linea: Hola desde la oficina de Cognia")
    r = _post(base, "/api/meta", {"texto": meta})
    print(f"[e2e] meta encargada: {r}", flush=True)

    t0 = time.time()
    ultimo = ""
    while time.time() - t0 < BUDGET_S:
        est = _get(base, "/api/estado")
        m = est["metas"][0]
        niveles = {t["nivel"] for t in est["tareas"].values()}
        linea = (f"meta={m['estado']} tareas={len(est['tareas'])} "
                 f"niveles={sorted(niveles)}")
        if linea != ultimo:
            print(f"[e2e] {time.strftime('%H:%M:%S')} {linea}", flush=True)
            ultimo = linea
        if m["estado"] in ("hecha", "fallida", "detenida"):
            break
        time.sleep(5)

    est = _get(base, "/api/estado")
    m = est["metas"][0]
    niveles = {t["nivel"] for t in est["tareas"].values()}
    archivo = os.path.join(workdir, "saludo.txt")
    existe = os.path.exists(archivo)
    contenido = open(archivo, encoding="utf-8").read().strip() if existe else ""
    print("\n========== E2E OFICINA ==========", flush=True)
    print(f"meta final     : {m['estado']}", flush=True)
    print(f"niveles usados : {sorted(niveles)}", flush=True)
    print(f"saludo.txt     : existe={existe} contenido={contenido[:80]!r}", flush=True)
    for t in est["tareas"].values():
        print(f"  {t['id']} [{t['nivel']}/{t.get('rol') or '-'}] {t['estado']}: "
              f"{t['titulo'][:60]}", flush=True)
    ok = (m["estado"] == "hecha" and {"jefe", "director", "trabajador"} <= niveles
          and existe)
    print("CHECK:", "PASS" if ok else "FAIL", flush=True)
    motor.stop()
    srv.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
