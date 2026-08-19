"""
tests/test_monitores_sondas.py
==============================
Pruebas del catalogo de sondas (cognia/monitores/sondas.py) y de los guardias
del agente (cognia/monitores/guardias.py).

METODO (regla del repo: nada de mocks de la funcionalidad)
    - Los comandos son REALES: se corre el propio interprete con `-c` para
      fabricar un exit 0 / exit 1 / cuelgue, y un binario inexistente para la
      rama "no medible". Nadie parchea subprocess.
    - El backend HTTP es un servidor de verdad (http.server en un hilo) que
      contesta 200 en /health y 500 en /roto, mas un puerto cerrado para el
      caso "no responde".
    - El puerto ocupado se comprueba con un socket que abre EL PROPIO TEST:
      el listener es este proceso de python, asi que se sabe la respuesta
      correcta sin inventarla.
    - Lo unico que se inyecta es lo que no se puede provocar en un test: el
      listado de procesos y el reloj del zombi (esperar 10 minutos reales no
      es una opcion), y la fabrica del detector de bucles para ejercitar la
      degradacion.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cognia.monitores import guardias, sondas

PY = sys.executable


# ---------------------------------------------------------------------------
# Utilidades del test
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                  # noqa: N802 (API de stdlib)
        if self.path.startswith("/health"):
            cuerpo = b'{"status":"ok"}'
            self.send_response(200)
        else:
            cuerpo = b'{"error":"cargando modelo"}'
            self.send_response(503)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):                         # silencio en la salida del test
        return


@pytest.fixture(scope="module")
def servidor():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _puerto_muerto() -> int:
    """Un puerto que nadie escucha: se reserva y se suelta."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


# ---------------------------------------------------------------------------
# 1. gpu_libre
# ---------------------------------------------------------------------------

def test_gpu_libre_dispara_con_vram_suficiente():
    cond = sondas.gpu_libre(1000, cmd=[PY, "-c", "print(9999)"])
    r = sondas.evaluar(cond)
    assert r["medible"] is True
    assert r["disparo"] is True
    assert r["mib_libres"] == 9999


def test_gpu_libre_no_dispara_con_vram_insuficiente():
    cond = sondas.gpu_libre(20000, cmd=[PY, "-c", "print(3000)"])
    r = sondas.evaluar(cond)
    assert r["medible"] is True and r["disparo"] is False
    assert "3000" in r["detalle"]


def test_gpu_libre_modo_por_debajo_es_la_alarma_inversa():
    cond = sondas.gpu_libre(4000, modo="por_debajo", cmd=[PY, "-c", "print(500)"])
    assert sondas.evaluar(cond)["disparo"] is True


def test_gpu_libre_sin_nvidia_smi_es_no_medible_y_no_dispara():
    # La rama que separa "no hay VRAM" de "no se puede ver la VRAM".
    cond = sondas.gpu_libre(1, cmd=["nvidia-smi-que-no-existe-jamas"])
    r = sondas.evaluar(cond)
    assert r["medible"] is False
    assert r["disparo"] is False
    assert "no medible" in r["detalle"]


def test_gpu_libre_contra_la_gpu_real_si_la_hay():
    if not shutil.which("nvidia-smi"):
        pytest.skip("esta maquina no tiene nvidia-smi")
    r = sondas.evaluar(sondas.gpu_libre(0))
    assert r["medible"] is True and r["disparo"] is True
    assert r["mib_libres"] >= 0


# ---------------------------------------------------------------------------
# 2. backend_vivo / backend_caido
# ---------------------------------------------------------------------------

def test_backend_vivo_dispara_con_health_200(servidor):
    r = sondas.evaluar(sondas.backend_vivo(servidor))
    assert r["disparo"] is True and r["situacion"] == "vivo"


def test_backend_vivo_no_dispara_si_responde_error(servidor):
    r = sondas.evaluar(sondas.backend_vivo(servidor + "/roto"))
    assert r["disparo"] is False
    assert r["situacion"] == "error" and r["codigo"] == 503
    assert r["medible"] is True                 # responder 503 ES una medicion


def test_backend_caido_dispara_cuando_no_responde_nadie():
    url = f"http://127.0.0.1:{_puerto_muerto()}"
    r = sondas.evaluar(sondas.backend_caido(url, timeout_s=2.0))
    assert r["disparo"] is True and r["situacion"] == "sin_respuesta"


def test_backend_caido_distingue_error_de_silencio(servidor):
    # llama-server contesta 503 mientras carga: eso NO es una caida si el
    # monitor se configuro con solo_sin_respuesta.
    estricto = sondas.backend_caido(servidor + "/roto", solo_sin_respuesta=True)
    laxo = sondas.backend_caido(servidor + "/roto", solo_sin_respuesta=False)
    assert sondas.evaluar(estricto)["disparo"] is False
    assert sondas.evaluar(laxo)["disparo"] is True
    assert sondas.evaluar(estricto)["situacion"] == "error"


def test_backend_caido_no_dispara_con_backend_sano(servidor):
    assert sondas.evaluar(sondas.backend_caido(servidor))["disparo"] is False


def test_backend_url_pelada_recibe_health():
    assert sondas.backend_vivo("http://127.0.0.1:8080")["url"].endswith("/health")
    # Si ya trae ruta se respeta tal cual.
    assert sondas.backend_vivo("http://127.0.0.1:11434/api/tags")["url"].endswith("/api/tags")


def test_backend_url_invalida_es_no_medible():
    r = sondas.evaluar(sondas.backend_vivo("no-es-una-url"))
    assert r["medible"] is False and r["disparo"] is False


# ---------------------------------------------------------------------------
# 3. disco_libre
# ---------------------------------------------------------------------------

def test_disco_libre_positivo_y_negativo(tmp_path):
    assert sondas.evaluar(sondas.disco_libre(str(tmp_path), 0.0))["disparo"] is True
    r = sondas.evaluar(sondas.disco_libre(str(tmp_path), 10 ** 9))
    assert r["disparo"] is False and r["medible"] is True
    assert r["gb_libres"] > 0


def test_disco_libre_ruta_inexistente_es_no_medible(tmp_path):
    r = sondas.evaluar(sondas.disco_libre(str(tmp_path / "no" / "existe"), 1.0))
    assert r["medible"] is False and r["disparo"] is False


# ---------------------------------------------------------------------------
# 4. fichero_cambio
# ---------------------------------------------------------------------------

def test_fichero_cambio_linea_base_no_dispara(tmp_path):
    f = tmp_path / "salida.txt"
    f.write_text("uno", encoding="utf-8")
    cond = sondas.fichero_cambio(str(f))
    r = sondas.evaluar(cond)
    assert r["disparo"] is False and r.get("base") is True
    # Segunda pasada sin tocar nada: sigue sin disparar.
    assert sondas.evaluar(cond)["disparo"] is False


def test_fichero_cambio_dispara_al_cambiar_contenido(tmp_path):
    f = tmp_path / "salida.txt"
    f.write_text("uno", encoding="utf-8")
    cond = sondas.fichero_cambio(str(f))
    sondas.evaluar(cond)
    f.write_text("dos y algo mas", encoding="utf-8")
    r = sondas.evaluar(cond)
    assert r["disparo"] is True and "cambio" in r["detalle"]
    # Y no se queda disparado para siempre: sin cambios nuevos, calla.
    assert sondas.evaluar(cond)["disparo"] is False


def test_fichero_cambio_ve_aparicion_y_desaparicion(tmp_path):
    f = tmp_path / "artefacto.gguf"
    cond = sondas.fichero_cambio(str(f))
    assert sondas.evaluar(cond)["disparo"] is False      # linea base: no existe
    f.write_bytes(b"x" * 10)
    assert "APARECIO" in sondas.evaluar(cond)["detalle"]
    f.unlink()
    assert "DESAPARECIO" in sondas.evaluar(cond)["detalle"]


def test_fichero_cambio_detecta_mismo_tamano_distinto_contenido(tmp_path):
    # mtime y tamano pueden coincidir; el sha es lo que cierra el caso.
    f = tmp_path / "igual.txt"
    f.write_text("aaaa", encoding="utf-8")
    cond = sondas.fichero_cambio(str(f))
    sondas.evaluar(cond)
    f.write_text("bbbb", encoding="utf-8")
    r = sondas.evaluar(cond)
    assert r["disparo"] is True and "sha" in r["detalle"]


# ---------------------------------------------------------------------------
# 5. log_patron  (tail INCREMENTAL: el punto es que NO relee)
# ---------------------------------------------------------------------------

def test_log_patron_dispara_solo_con_lineas_nuevas(tmp_path):
    log = tmp_path / "servidor.log"
    log.write_text("arranque ok\n", encoding="utf-8")
    cond = sondas.log_patron(str(log), r"ERROR|CUDA out of memory")
    r0 = sondas.evaluar(cond)
    assert r0["disparo"] is False and r0["bytes_leidos"] == 0

    with open(log, "a", encoding="utf-8") as f:
        f.write("todo bien\nCUDA out of memory: 12 GiB\n")
    r1 = sondas.evaluar(cond)
    assert r1["disparo"] is True
    assert "CUDA out of memory" in r1["detalle"]


def test_log_patron_no_relee_el_fichero_entero(tmp_path):
    """El offset avanza EXACTAMENTE los bytes nuevos y nunca retrocede.

    Es la propiedad que hace la sonda viable sobre un log de 100 MB: si
    releyera desde 0 cada 2 s, el monitor costaria mas que lo vigilado.
    """
    log = tmp_path / "grande.log"
    cabecera = "linea vieja\n" * 100
    # newline="" en todo el test: sin eso Windows traduce \n a \r\n al escribir
    # y las cuentas de bytes dejarian de ser comprobables.
    log.write_text(cabecera, encoding="utf-8", newline="")
    cond = sondas.log_patron(str(log), r"BOOM")

    r0 = sondas.evaluar(cond)
    assert r0["bytes_leidos"] == 0                       # arranca en el final
    assert r0["offset"] == len(cabecera.encode("utf-8"))

    nueva = "todavia nada\n"
    with open(log, "a", encoding="utf-8", newline="") as f:
        f.write(nueva)
    r1 = sondas.evaluar(cond)
    assert r1["bytes_leidos"] == len(nueva.encode("utf-8"))   # SOLO lo nuevo
    assert r1["offset"] == r0["offset"] + r1["bytes_leidos"]

    r2 = sondas.evaluar(cond)
    assert r2["bytes_leidos"] == 0                       # nada nuevo: no relee
    assert r2["offset"] == r1["offset"]

    con_match = "BOOM se rompio\n"
    with open(log, "a", encoding="utf-8", newline="") as f:
        f.write(con_match)
    r3 = sondas.evaluar(cond)
    assert r3["disparo"] is True
    assert r3["bytes_leidos"] == len(con_match.encode("utf-8"))
    # La coincidencia ya consumida no vuelve a disparar en la pasada siguiente.
    assert sondas.evaluar(cond)["disparo"] is False


def test_log_patron_desde_inicio_examina_lo_ya_escrito(tmp_path):
    log = tmp_path / "viejo.log"
    log.write_text("hola\nERROR fatal\n", encoding="utf-8")
    cond = sondas.log_patron(str(log), r"ERROR", desde_inicio=True)
    r = sondas.evaluar(cond)
    assert r["disparo"] is True and r["bytes_leidos"] > 0


def test_log_patron_sobrevive_a_la_rotacion(tmp_path):
    log = tmp_path / "rota.log"
    log.write_text("x" * 500 + "\n", encoding="utf-8", newline="")
    cond = sondas.log_patron(str(log), r"ERROR")
    sondas.evaluar(cond)                                  # offset = 501
    # El fichero encogio (rotacion): el offset viejo dejaria al monitor ciego.
    log.write_text("ERROR tras rotar\n", encoding="utf-8", newline="")
    r = sondas.evaluar(cond)
    assert r["disparo"] is True
    assert r["offset"] == len("ERROR tras rotar\n".encode("utf-8"))


def test_log_patron_fichero_ausente_es_no_medible(tmp_path):
    cond = sondas.log_patron(str(tmp_path / "aun-no.log"), r"ERROR")
    r = sondas.evaluar(cond)
    assert r["medible"] is False and r["disparo"] is False


def test_log_patron_regex_invalido_es_no_medible(tmp_path):
    log = tmp_path / "l.log"
    log.write_text("hola\n", encoding="utf-8")
    r = sondas.evaluar(sondas.log_patron(str(log), r"(sin cerrar"))
    assert r["medible"] is False and "regex" in r["detalle"]


# ---------------------------------------------------------------------------
# 6. git_sucio
# ---------------------------------------------------------------------------

def _git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, timeout=60)


@pytest.mark.skipif(not shutil.which("git"), reason="sin git en esta maquina")
def test_git_sucio_positivo_y_negativo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git("init", "-q", cwd=str(repo)).returncode == 0
    limpio = sondas.evaluar(sondas.git_sucio(str(repo)))
    assert limpio["medible"] is True and limpio["disparo"] is False

    (repo / "nuevo.txt").write_text("cambio sin commitear", encoding="utf-8")
    sucio = sondas.evaluar(sondas.git_sucio(str(repo)))
    assert sucio["disparo"] is True and sucio["cambios"] == 1


@pytest.mark.skipif(not shutil.which("git"), reason="sin git en esta maquina")
def test_git_sucio_fuera_de_un_repo_es_no_medible(tmp_path):
    # "No es un repo" NO es "esta limpio".
    r = sondas.evaluar(sondas.git_sucio(str(tmp_path)))
    assert r["medible"] is False and r["disparo"] is False


# ---------------------------------------------------------------------------
# 7. tests_rojos
# ---------------------------------------------------------------------------

def test_tests_rojos_dispara_con_exit_1(tmp_path):
    cond = sondas.tests_rojos(str(tmp_path), [PY, "-c", "raise SystemExit(1)"], timeout_s=60)
    r = sondas.evaluar(cond)
    assert r["disparo"] is True and r["rc"] == 1


def test_tests_rojos_no_dispara_con_exit_0(tmp_path):
    cond = sondas.tests_rojos(str(tmp_path), [PY, "-c", "print('7 passed')"], timeout_s=60)
    r = sondas.evaluar(cond)
    assert r["disparo"] is False and r["rc"] == 0
    assert "7 passed" in r["detalle"]


def test_tests_rojos_cuelgue_cuenta_como_rojo(tmp_path):
    cond = sondas.tests_rojos(str(tmp_path), [PY, "-c", "import time; time.sleep(30)"],
                              timeout_s=1.0)
    r = sondas.evaluar(cond)
    assert r["disparo"] is True and r["timeout"] is True


def test_tests_rojos_binario_ausente_es_no_medible(tmp_path):
    cond = sondas.tests_rojos(str(tmp_path), ["pytest-que-no-existe", "-q"], timeout_s=30)
    r = sondas.evaluar(cond)
    # Un arnes roto no es codigo roto: acusar al codigo aqui seria mentir.
    assert r["medible"] is False and r["disparo"] is False


# ---------------------------------------------------------------------------
# 8. proceso_zombi  (listado y reloj inyectados: 10 min no se esperan)
# ---------------------------------------------------------------------------

def _listador(muestras):
    """Devuelve un `listar` que va entregando las muestras dadas, en orden."""
    caja = {"i": 0}

    def listar(_filtro):
        i = min(caja["i"], len(muestras) - 1)
        caja["i"] += 1
        return muestras[i]

    return listar


def test_proceso_zombi_dispara_con_proceso_vivo_sin_cpu():
    quieto = [{"pid": 4242, "nombre": "python.exe", "cmdline": "python banco.py",
               "cpu_s": 7200.0}]
    listar = _listador([quieto, quieto, quieto])
    cond = sondas.proceso_zombi("banco.py", min_cpu=1.0, minutos=10.0)
    t0 = 1_000_000.0

    r0 = sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0)
    assert r0["disparo"] is False                     # linea base: una muestra
    r1 = sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0 + 60)
    assert r1["disparo"] is False                     # quieto hace 0 s
    r2 = sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0 + 60 + 601)
    assert r2["disparo"] is True
    assert r2["zombis"][0]["pid"] == 4242
    assert r2["zombis"][0]["cpu_pct"] == 0.0


def test_proceso_zombi_no_dispara_si_el_proceso_trabaja():
    muestras = [[{"pid": 7, "nombre": "python.exe", "cmdline": "banco.py", "cpu_s": c}]
                for c in (100.0, 160.0, 220.0, 880.0)]   # ~100% de un nucleo
    listar = _listador(muestras)
    cond = sondas.proceso_zombi("banco.py", min_cpu=1.0, minutos=10.0)
    t0 = 500.0
    for k, salto in enumerate((0, 60, 120, 780)):
        r = sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0 + salto)
        assert r["disparo"] is False, f"muestra {k}: {r['detalle']}"


def test_proceso_zombi_reinicia_el_reloj_cuando_vuelve_a_trabajar():
    # Quieto 9 min, un pico de CPU, y luego 9 min mas: no llega a 10 seguidos.
    muestras = [[{"pid": 9, "nombre": "python.exe", "cmdline": "x", "cpu_s": c}]
                for c in (10.0, 10.0, 610.0, 610.0)]
    listar = _listador(muestras)
    cond = sondas.proceso_zombi("x", min_cpu=1.0, minutos=10.0)
    t0 = 0.0
    assert sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0)["disparo"] is False
    assert sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0 + 540)["disparo"] is False
    assert sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0 + 1140)["disparo"] is False
    assert sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=t0 + 1680)["disparo"] is False


def test_proceso_zombi_sin_procesos_no_dispara():
    cond = sondas.proceso_zombi("no-existe-este-proceso", min_cpu=1.0, minutos=1.0)
    r = sondas.evaluar_proceso_zombi(cond, listar=lambda _f: [], ahora=1.0)
    assert r["disparo"] is False and r["zombis"] == []


def test_proceso_zombi_sin_listado_es_no_medible():
    def listar_roto(_f):
        raise OSError("no pude listar procesos")

    cond = sondas.proceso_zombi("x", min_cpu=1.0, minutos=1.0)
    r = sondas.evaluar_proceso_zombi(cond, listar=listar_roto, ahora=1.0)
    assert r["medible"] is False and r["disparo"] is False


def test_proceso_zombi_olvida_los_pids_muertos():
    vivo = [{"pid": 1, "nombre": "a", "cmdline": "a", "cpu_s": 1.0}]
    listar = _listador([vivo, vivo, []])
    cond = sondas.proceso_zombi("a", min_cpu=1.0, minutos=10.0)
    sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=0.0)
    sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=60.0)
    sondas.evaluar_proceso_zombi(cond, listar=listar, ahora=120.0)
    assert cond["estado"]["procs"] == {}          # el estado no crece sin techo


def test_listar_procesos_real_devuelve_este_proceso():
    # El listador de verdad, contra el sistema de verdad.
    procs = sondas.listar_procesos("python")
    assert isinstance(procs, list) and procs
    assert os.getpid() in {p["pid"] for p in procs}
    assert all(p["cpu_s"] >= 0 for p in procs)


# ---------------------------------------------------------------------------
# 9. puerto_ocupado_por_otro  (socket REAL abierto por el propio test)
# ---------------------------------------------------------------------------

def test_puerto_ocupado_por_otro_con_socket_real():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    puerto = s.getsockname()[1]
    try:
        # El listener es ESTE proceso de python: si el esperado es python,
        # nadie robo nada.
        propio = sondas.evaluar(sondas.puerto_ocupado_por_otro(puerto, "python"))
        if not propio["medible"]:
            pytest.skip(f"no se pudo resolver el listener: {propio['detalle']}")
        assert propio["disparo"] is False
        assert propio["pid"] == os.getpid()

        # El caso real de esta maquina: se esperaba llama-server y escucha otro.
        robado = sondas.evaluar(sondas.puerto_ocupado_por_otro(puerto, "llama-server"))
        assert robado["disparo"] is True
        assert "python" in robado["exe"].lower()
        assert robado["pid"] == os.getpid()
    finally:
        s.close()


def test_puerto_libre_no_dispara():
    r = sondas.evaluar(sondas.puerto_ocupado_por_otro(_puerto_muerto(), "llama-server"))
    assert r["disparo"] is False and "libre" in r["detalle"]


def test_puerto_sin_resolver_el_exe_es_no_medible():
    # Hay listener pero no se sabe QUIEN: afirmar "intruso" aqui es como se
    # termina matando al proceso equivocado.
    r = sondas.evaluar_puerto_ocupado_por_otro(
        sondas.puerto_ocupado_por_otro(8080, "llama-server"),
        pid_de_puerto=lambda _p: 4242, nombre_pid=lambda _pid: "")
    assert r["medible"] is False and r["disparo"] is False


def test_puerto_compara_exe_sin_extension_ni_mayusculas():
    cond = sondas.puerto_ocupado_por_otro(8080, "llama-server")
    igual = sondas.evaluar_puerto_ocupado_por_otro(
        cond, pid_de_puerto=lambda _p: 1, nombre_pid=lambda _pid: "LLAMA-SERVER.EXE")
    intruso = sondas.evaluar_puerto_ocupado_por_otro(
        cond, pid_de_puerto=lambda _p: 1, nombre_pid=lambda _pid: "tailscaled.exe")
    assert igual["disparo"] is False
    assert intruso["disparo"] is True and "tailscaled" in intruso["detalle"]


# ---------------------------------------------------------------------------
# Despachador y contrato general
# ---------------------------------------------------------------------------

def test_todas_las_sondas_son_serializables_a_json():
    # El nucleo las guarda en disco: si una no serializa, el monitor se pierde.
    conds = [sondas.gpu_libre(1000), sondas.backend_vivo("http://127.0.0.1:8080"),
             sondas.backend_caido("http://127.0.0.1:8080"), sondas.disco_libre(".", 5),
             sondas.fichero_cambio("x.txt"), sondas.log_patron("x.log", "ERROR"),
             sondas.git_sucio("."), sondas.tests_rojos(".", ["pytest", "-q"]),
             sondas.proceso_zombi("python", 1.0, 10.0),
             sondas.puerto_ocupado_por_otro(8080, "llama-server")]
    assert {c["tipo"] for c in conds} == set(sondas.EVALUADORES)
    for c in conds:
        assert json.loads(json.dumps(c))["tipo"] == c["tipo"]
        assert sondas.describir(c).startswith(c["tipo"] + "(")


def test_evaluar_tipo_desconocido_no_lanza():
    r = sondas.evaluar({"tipo": "sonda_inventada"})
    assert r["medible"] is False and r["disparo"] is False


def test_evaluar_cond_invalida_no_lanza():
    assert sondas.evaluar("no soy un dict")["medible"] is False


def test_evaluar_sonda_que_revienta_sale_como_no_medible(monkeypatch):
    def explota(_cond):
        raise RuntimeError("boom")

    monkeypatch.setitem(sondas.EVALUADORES, "gpu_libre", explota)
    r = sondas.evaluar(sondas.gpu_libre(1))
    assert r["medible"] is False and r["disparo"] is False
    assert "la sonda fallo" in r["detalle"]


def test_no_medible_nunca_dispara():
    # La regla dura del modulo, comprobada sobre el constructor de resultados.
    r = sondas._res("x", True, "deberia caer", medible=False)
    assert r["disparo"] is False


# ---------------------------------------------------------------------------
# GUARDIAS: presupuesto
# ---------------------------------------------------------------------------

def test_guardia_presupuesto_ok_con_gasto_tranquilo():
    estado = {"tokens_usados": 1000, "presupuesto_tokens": 100000,
              "inicio_ts": 0.0, "ahora": 600.0}
    v = guardias.guardia_presupuesto(estado)
    assert v["estado"] == "ok"
    assert v["evidencia"]["ritmo_tpm"] == 100.0


def test_guardia_presupuesto_avisa_al_cruzar_la_fraccion():
    estado = {"tokens_usados": 80000, "presupuesto_tokens": 100000,
              "inicio_ts": 0.0, "ahora": 3600.0}
    v = guardias.guardia_presupuesto(estado)
    assert v["estado"] == "aviso" and "80%" in v["mensaje"]


def test_guardia_presupuesto_corta_al_agotarse():
    estado = {"tokens_usados": 100001, "presupuesto_tokens": 100000,
              "inicio_ts": 0.0, "ahora": 3600.0}
    assert guardias.guardia_presupuesto(estado)["estado"] == "corte"


def test_guardia_presupuesto_corta_por_RITMO_con_presupuesto_de_sobra():
    # El punto del guardia: 3% del techo gastado y aun asi hay que cortar,
    # porque el ritmo del ultimo tramo es una fuga.
    estado = {"tokens_usados": 30000, "presupuesto_tokens": 1000000,
              "inicio_ts": 0.0, "ahora": 60.0,
              "muestras": [(0.0, 0), (30.0, 500), (60.0, 30000)]}
    v = guardias.guardia_presupuesto(estado)
    assert v["estado"] == "corte" and "fuga" in v["mensaje"]
    assert v["evidencia"]["origen_ritmo"] == "muestras"
    assert v["evidencia"]["fraccion"] < 0.05


def test_guardia_presupuesto_avisa_por_proyeccion_antes_del_techo():
    # 60% gastado (por debajo del 75% de aviso) pero a este ritmo quedan 60 s.
    estado = {"tokens_usados": 6000, "presupuesto_tokens": 10000,
              "inicio_ts": 0.0, "ahora": 90.0,
              "muestras": [(0.0, 0), (45.0, 3000), (90.0, 6000)]}
    v = guardias.guardia_presupuesto(estado)
    assert v["estado"] == "aviso"
    assert 0 < v["evidencia"]["seg_para_agotar"] <= guardias.HORIZONTE_AVISO_S


def test_guardia_presupuesto_no_corta_por_ritmo_sin_muestras_reales():
    # Promedio enorme por una ventana ridicula: no se corta sobre eso.
    estado = {"tokens_usados": 5000, "presupuesto_tokens": 1000000,
              "inicio_ts": 0.0, "ahora": 1.0}
    v = guardias.guardia_presupuesto(estado)
    assert v["estado"] == "ok" and v["evidencia"]["origen_ritmo"] == "promedio"


def test_guardia_presupuesto_sin_datos_no_lanza():
    assert guardias.guardia_presupuesto({})["estado"] == "ok"
    assert guardias.guardia_presupuesto(None)["estado"] == "ok"


def test_guardia_presupuesto_tolera_basura_en_el_estado():
    v = guardias.guardia_presupuesto({"tokens_usados": "muchos",
                                      "presupuesto_tokens": None,
                                      "muestras": ["ruido", (1,)]})
    assert v["estado"] == "ok"


# ---------------------------------------------------------------------------
# GUARDIAS: pared
# ---------------------------------------------------------------------------

def test_guardia_pared_ok_recien_cerrado_un_paso():
    estado = {"inicio_ts": 0.0, "ultimo_paso_ts": 100.0, "paso": 3, "ahora": 130.0}
    assert guardias.guardia_pared(estado)["estado"] == "ok"


def test_guardia_pared_avisa_y_corta():
    base = {"inicio_ts": 0.0, "ultimo_paso_ts": 0.0, "paso": 4}
    aviso = guardias.guardia_pared(dict(base, ahora=6 * 60.0))
    corte = guardias.guardia_pared(dict(base, ahora=20 * 60.0))
    assert aviso["estado"] == "aviso" and aviso["evidencia"]["quieto_min"] == 6.0
    assert corte["estado"] == "corte" and "colgada" in corte["mensaje"]


def test_guardia_pared_cae_al_inicio_si_nunca_cerro_un_paso():
    # El caso peor: se colgo en el PRIMER paso y no hay ultimo_paso_ts.
    v = guardias.guardia_pared({"inicio_ts": 0.0, "paso": 1, "ahora": 20 * 60.0})
    assert v["estado"] == "corte"
    assert v["evidencia"]["referencia"] == "inicio_tarea"
    assert v["evidencia"]["sin_pasos_cerrados"] is True
    assert "PRIMER paso" in v["mensaje"]


def test_guardia_pared_limites_configurables():
    estado = {"inicio_ts": 0.0, "ultimo_paso_ts": 0.0, "ahora": 120.0}
    v = guardias.guardia_pared(estado, limites={"aviso_min": 1.0, "corte_min": 1.5})
    assert v["estado"] == "corte"


def test_guardia_pared_sin_marcas_declara_que_no_puede_medir():
    v = guardias.guardia_pared({"paso": 2})
    assert v["estado"] == "ok" and v["evidencia"]["medible"] is False


# ---------------------------------------------------------------------------
# GUARDIAS: repeticion
# ---------------------------------------------------------------------------

def test_guardia_repeticion_ok_con_pasos_variados():
    estado = {"historial": [("leer_archivo", "a.py"), ("editar_archivo", "a.py"),
                            ("tests", "-q"), ("git_diff", "")]}
    v = guardias.guardia_repeticion(estado)
    assert v["estado"] == "ok" and v["evidencia"]["degradado"] is False


def test_guardia_repeticion_avisa_y_luego_corta():
    tres = {"historial": [("leer_archivo", "a.py")] * 3}
    cinco = {"historial": [("leer_archivo", "a.py")] * 5}
    assert guardias.guardia_repeticion(tres)["estado"] == "aviso"
    corte = guardias.guardia_repeticion(cinco)
    assert corte["estado"] == "corte"
    assert corte["evidencia"]["patron"] == "repeticion"


def test_guardia_repeticion_ve_el_ping_pong():
    estado = {"historial": [("leer", "a"), ("leer", "b")] * 3}
    v = guardias.guardia_repeticion(estado)
    assert v["estado"] in ("aviso", "corte")
    assert v["evidencia"]["patron"] == "ping_pong"


def test_guardia_repeticion_es_pura():
    # Mismo historial dos veces seguidas -> mismo veredicto (sin estado oculto).
    estado = {"historial": [("leer_archivo", "a.py")] * 4}
    assert guardias.guardia_repeticion(estado) == guardias.guardia_repeticion(estado)


def test_guardia_repeticion_degrada_si_no_esta_guardia_bucle():
    def sin_modulo():
        raise ImportError("no module named cognia.hermes.guardia_bucle")

    estado = {"historial": [("leer_archivo", "a.py")] * 4}
    v = guardias.guardia_repeticion(estado, fabrica=sin_modulo)
    assert v["estado"] == "aviso"                    # degrada, NO falla
    assert v["evidencia"]["degradado"] is True
    assert "guardia_bucle" in v["evidencia"]["motivo"]


def test_guardia_repeticion_historial_vacio():
    assert guardias.guardia_repeticion({})["estado"] == "ok"


# ---------------------------------------------------------------------------
# GUARDIAS: contrato comun
# ---------------------------------------------------------------------------

def test_los_tres_guardias_devuelven_el_mismo_contrato():
    estado = {"tokens_usados": 10, "presupuesto_tokens": 1000, "inicio_ts": 0.0,
              "ahora": 10.0, "ultimo_paso_ts": 9.0, "historial": [("leer", "a")]}
    for nombre, fn in guardias.GUARDIAS.items():
        v = fn(estado)
        assert set(v) == {"estado", "mensaje", "evidencia"}, nombre
        assert v["estado"] in ("ok", "aviso", "corte"), nombre
        assert isinstance(v["evidencia"], dict), nombre


def test_guardia_roto_no_rompe_el_turno():
    # El blindaje: un guardia que revienta sale como 'ok' pero lo DECLARA.
    @guardias._blindar
    def guardia_explosivo(_estado):
        raise ValueError("boom")

    v = guardia_explosivo({})
    assert v["estado"] == "ok" and v["evidencia"]["guardia_roto"] is True


def test_evaluar_guardias_devuelve_el_peor():
    estado = {"tokens_usados": 999999, "presupuesto_tokens": 1000,
              "inicio_ts": 0.0, "ahora": 60.0,
              "ultimo_paso_ts": 59.0,
              "historial": [("leer", "a"), ("editar", "b")]}
    v = guardias.evaluar_guardias(estado)
    assert v["estado"] == "corte"
    assert set(v["evidencia"]["guardias"]) == set(guardias.GUARDIAS)
    assert "[presupuesto]" in v["mensaje"]
