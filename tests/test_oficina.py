"""Tests de la oficina agéntica: estado, control externo y API del server."""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognia.oficina.estado import Oficina
from cognia.oficina.motor import _parse_numerada, _parse_roles
from cognia.oficina.server import crear_server


def _of(tmp_path):
    return Oficina(str(tmp_path / "estado.json"))


def _server(tmp_path):
    """Oficina + server en puerto efímero (mismo patrón que test_server_api)."""
    of = _of(tmp_path)
    srv = crear_server(of, puerto=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return of, srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, obj):
    """POST JSON; los 400 del server devuelven cuerpo {ok:False}, no excepción."""
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST")
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def test_meta_y_jerarquia(tmp_path):
    of = _of(tmp_path)
    mid = of.nueva_meta("armar un informe")
    assert of.meta_pendiente()["id"] == mid
    jefe = of.crear_tarea("jefe", "META", "armar un informe", meta=mid)
    d1 = of.crear_tarea("director", "D1", "parte 1", padre=jefe, meta=mid)
    t1 = of.crear_tarea("trabajador", "T1", "buscar datos", padre=d1,
                        rol="investigador", meta=mid)
    assert [h["id"] for h in of.hijos(jefe)] == [d1]
    assert of.hijos(d1)[0]["id"] == t1
    # persistencia real: releer desde disco
    of2 = Oficina(of.path)
    assert t1 in of2.data["tareas"]


def test_control_detener_pausar_editar(tmp_path):
    of = _of(tmp_path)
    t = of.crear_tarea("trabajador", "T", "hacer algo", rol="investigador")
    # pendiente + pausar -> pausada directa; editar permitido; reanudar -> pendiente
    assert of.solicitar(t, "pausar")
    assert of.snapshot()["tareas"][t]["estado"] == "pausada"
    assert of.editar(t, "hacer OTRA cosa")
    assert of.snapshot()["tareas"][t]["detalle"] == "hacer OTRA cosa"
    assert of.solicitar(t, "reanudar")
    assert of.snapshot()["tareas"][t]["estado"] == "pendiente"
    # en curso: la solicitud queda para que el motor la honre
    of.set_estado(t, "en_curso")
    assert of.solicitar(t, "detener")
    assert of.control(t) == "detener"
    of.consumir_solicitud(t)
    of.set_estado(t, "detenida")
    # tarea terminal: no se puede editar ni controlar
    assert not of.editar(t, "x")
    assert not of.solicitar(t, "pausar")


def test_eventos_acotados(tmp_path):
    of = _of(tmp_path)
    t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
    for i in range(230):
        of.evento(t, f"paso {i}")
    evs = of.snapshot()["tareas"][t]["eventos"]
    assert len(evs) == 200 and evs[-1]["msg"] == "paso 229"


def test_parsers_de_planes():
    assert _parse_numerada("1. investigar el tema a fondo\n2) escribir el informe final") == \
        ["investigar el tema a fondo", "escribir el informe final"]
    roles = _parse_roles("implementador: crear script de conteo\n"
                         "investigador: buscar referencias del tema")
    assert roles[0] == ("implementador", "crear script de conteo")
    assert roles[1][0] == "investigador"
    # rol desconocido degrada a investigador (menor blast-radius)
    assert _parse_roles("hacker: romper todo")[0][0] == "investigador"
    # tic real del 3B (e2e v1): prefijo literal "ROL:" copiado del formato
    assert _parse_roles("1. ROL: investigador. Buscar el archivo saludo.txt") == \
        [("investigador", "Buscar el archivo saludo.txt")]
    assert _parse_roles("ROL: implementador: crear saludo.txt con hola")[0][0] == \
        "implementador"
    # guard-rail: sin rol parseable, verbos de escritura infieren implementador
    assert _parse_roles("2) crear el archivo saludo.txt con el texto Hola")[0][0] == \
        "implementador"


def test_seq_y_timestamps(tmp_path):
    of = _of(tmp_path)
    s0 = of.snapshot()["_seq"]
    t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
    s1 = of.snapshot()["_seq"]
    assert s1 > s0                                   # cada _save sube el contador
    tarea = of.snapshot()["tareas"][t]
    assert tarea["creada_ts"] > 0
    of.set_estado(t, "en_curso")
    assert of.snapshot()["tareas"][t]["inicio_ts"] > 0
    of.set_estado(t, "hecha")
    tarea = of.snapshot()["tareas"][t]
    assert tarea["fin_ts"] >= tarea["inicio_ts"]
    assert of.snapshot()["_seq"] > s1
    # el shape viejo sigue intacto (solo claves agregadas)
    assert tarea["estado"] == "hecha" and tarea["creada"] and tarea["eventos"] == []


def test_api_prioridad(tmp_path):
    of, srv, base = _server(tmp_path)
    try:
        a = of.crear_tarea("trabajador", "A", "a", rol="investigador")
        b = of.crear_tarea("trabajador", "B", "b", rol="investigador")
        c = of.crear_tarea("trabajador", "C", "c", rol="investigador")
        assert _post(base + "/api/tarea/prioridad", {"id": c, "delta": -1})["ok"]
        assert of.snapshot()["orden"] == [a, c, b]
        assert _post(base + "/api/tarea/prioridad", {"id": a, "delta": 1})["ok"]
        assert of.snapshot()["orden"] == [c, a, b]
        # bordes y no-pendientes rechazados
        assert not _post(base + "/api/tarea/prioridad", {"id": c, "delta": -1})["ok"]
        of.set_estado(b, "en_curso")
        assert not _post(base + "/api/tarea/prioridad", {"id": b, "delta": -1})["ok"]
        assert not _post(base + "/api/tarea/prioridad", {"id": a, "delta": 5})["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_reasignar(tmp_path):
    of, srv, base = _server(tmp_path)
    try:
        t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
        assert _post(base + "/api/tarea/reasignar", {"id": t, "rol": "implementador"})["ok"]
        tarea = of.snapshot()["tareas"][t]
        assert tarea["rol"] == "implementador"
        assert tarea["eventos"][-1]["msg"] == "[reasignada a implementador]"
        # rol inválido / tarea corriendo / no-trabajador rechazados
        assert not _post(base + "/api/tarea/reasignar", {"id": t, "rol": "hacker"})["ok"]
        of.set_estado(t, "en_curso")
        assert not _post(base + "/api/tarea/reasignar", {"id": t, "rol": "investigador"})["ok"]
        d = of.crear_tarea("director", "D", "dir")
        assert not _post(base + "/api/tarea/reasignar", {"id": d, "rol": "investigador"})["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_reiniciar(tmp_path):
    of, srv, base = _server(tmp_path)
    try:
        d = of.crear_tarea("director", "D", "dir")
        t = of.crear_tarea("trabajador", "T", "hacer x", padre=d,
                           rol="implementador")
        of.set_estado(t, "en_curso")
        of.set_estado(t, "fallida")
        r = _post(base + "/api/agente/reiniciar", {"id": t})
        assert r["ok"] and r["nuevo_id"] in of.snapshot()["tareas"]
        nuevo = of.snapshot()["tareas"][r["nuevo_id"]]
        assert (nuevo["estado"] == "pendiente" and nuevo["padre"] == d
                and nuevo["rol"] == "implementador" and nuevo["detalle"] == "hacer x")
        # una tarea hecha no se reinicia
        h = of.crear_tarea("trabajador", "H", "y", rol="investigador")
        of.set_estado(h, "hecha")
        assert not _post(base + "/api/agente/reiniciar", {"id": h})["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_mensaje(tmp_path):
    of, srv, base = _server(tmp_path)
    try:
        t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
        assert _post(base + "/api/mensaje",
                     {"de": "jefe", "para": t, "texto": "apurate"})["ok"]
        assert of.snapshot()["tareas"][t]["eventos"][-1]["msg"] == \
            "[mensaje de jefe]: apurate"
        # destino inexistente o texto vacío rechazados
        assert not _post(base + "/api/mensaje",
                         {"de": "x", "para": "trab-nope", "texto": "y"})["ok"]
        assert not _post(base + "/api/mensaje",
                         {"de": "x", "para": t, "texto": "  "})["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_sistema_y_sse(tmp_path):
    of, srv, base = _server(tmp_path)
    try:
        of.crear_tarea("trabajador", "T", "x", rol="investigador")
        met = json.loads(urllib.request.urlopen(base + "/api/sistema").read())
        for k in ("cpu_pct", "ram_mb", "ram_pct", "n_threads", "agentes_activos",
                  "tareas_pendientes", "tareas_en_curso", "uptime_s"):
            assert k in met, k
        assert met["tareas_pendientes"] == 1 and met["n_threads"] >= 1
        assert met["uptime_s"] >= 0
        # SSE: al conectar llega un evento "estado" con el snapshot completo
        resp = urllib.request.urlopen(base + "/api/sse", timeout=5)
        evento, data = None, None
        for _ in range(30):
            linea = resp.readline().decode("utf-8").strip()
            if linea.startswith("event: "):
                evento = linea[len("event: "):]
            elif linea.startswith("data: ") and evento == "estado":
                data = json.loads(linea[len("data: "):])
                break
        resp.close()
        assert data is not None and "_seq" in data and "tareas" in data
    finally:
        srv.shutdown()
        srv.server_close()


def test_server_api(tmp_path):
    of = _of(tmp_path)
    srv = crear_server(of, puerto=0)          # puerto libre del SO
    puerto = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{puerto}"
    try:
        # dashboard
        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "Oficina Cognia" in html
        # deep-link con query string sirve el dashboard, no un 404 JSON
        html_q = urllib.request.urlopen(base + "/?sel=trab-abc").read().decode("utf-8")
        assert "Oficina Cognia" in html_q
        # nueva meta por API
        req = urllib.request.Request(base + "/api/meta",
                                     data=json.dumps({"texto": "meta via api"}).encode(),
                                     method="POST")
        r = json.loads(urllib.request.urlopen(req).read())
        assert r["ok"] and of.meta_pendiente()["texto"] == "meta via api"
        # estado refleja la meta
        est = json.loads(urllib.request.urlopen(base + "/api/estado").read())
        assert est["metas"][0]["texto"] == "meta via api"
        # control por API sobre una tarea
        t = of.crear_tarea("trabajador", "T", "x", rol="investigador")
        req = urllib.request.Request(base + "/api/tarea/accion",
                                     data=json.dumps({"id": t, "accion": "pausar"}).encode(),
                                     method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["ok"]
        assert of.snapshot()["tareas"][t]["estado"] == "pausada"
        req = urllib.request.Request(base + "/api/tarea/editar",
                                     data=json.dumps({"id": t, "detalle": "nuevo"}).encode(),
                                     method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["ok"]
        assert of.snapshot()["tareas"][t]["detalle"] == "nuevo"
    finally:
        srv.shutdown()
        srv.server_close()


def test_motor_trabajador_fallido_no_es_hecha(tmp_path, monkeypatch):
    """Fix 2026-07-15: un resultado de error/vacio del trabajador -> tarea
    FALLIDA y, si todos fallan, la meta cierra FALLIDA (antes el motor
    marcaba 'hecha' con '(sin backend de inferencia...)' como resultado y
    cero archivos producidos — cazado por el e2e del producto instalado)."""
    from cognia.oficina.motor import Motor
    import cognia.cli as cli_mod
    of = _of(tmp_path)
    mid = of.nueva_meta("crear flappy.html")
    monkeypatch.setattr(
        cli_mod, "_run_agent_task",
        lambda *a, **kw: "(sin backend de inferencia: el agente no puede "
                         "generar codigo)")
    m = Motor(of, ai=object())
    monkeypatch.setattr(m, "_infer", lambda prompt: "1. hacer el archivo")
    m._procesa_meta(of.meta_pendiente())
    snap = of.snapshot()
    meta = [x for x in snap["metas"] if x["id"] == mid][0]
    assert meta["estado"] == "fallida"
    trabs = [t for t in snap["tareas"].values() if t["nivel"] == "trabajador"]
    assert trabs and all(t["estado"] == "fallida" for t in trabs)


def test_motor_trabajador_ok_meta_hecha(tmp_path, monkeypatch):
    from cognia.oficina.motor import Motor
    import cognia.cli as cli_mod
    of = _of(tmp_path)
    of.nueva_meta("crear un archivo x")
    monkeypatch.setattr(cli_mod, "_run_agent_task",
                        lambda *a, **kw: "archivo x creado OK")
    m = Motor(of, ai=object())
    monkeypatch.setattr(m, "_infer", lambda prompt: "")
    m._procesa_meta(of.meta_pendiente())
    snap = of.snapshot()
    assert snap["metas"][0]["estado"] == "hecha"
    assert "creado OK" in snap["metas"][0].get("resultado", "")
