# -*- coding: utf-8 -*-
"""
Tests de scripts/servidor_modelo.py - la pieza que arranca y para llama-server.

REGLA DE ESTE FICHERO (2026-08-13): ni un solo test arranca un llama-server ni
toca el :8080. El :8080 es el cerebro del dueno. Lo que se prueba aca es todo
lo que se puede probar SIN inferencia, y se prueba con cosas REALES, no con
mocks:

  - el parseo de la cmdline, contra la cmdline literal capturada del proceso
    vivo el 2026-08-13 (352 caracteres, leida por CIM);
  - la construccion de flags, que es una funcion pura;
  - el calculo de ctx, contra ficheros GGUF de verdad (cabecera valida escrita
    por el propio test y leida por el lector real de scripts/ctx_maximo.py);
  - parar(), contra PROCESOS DE VERDAD (un python durmiendo), porque matar es
    justo lo que no se puede probar de mentira;
  - esperar_salud()/estado(), contra un servidor HTTP de verdad en un puerto
    efimero (jamas el 8080).

Lo unico que se inyecta es la LISTA de procesos (_procesos_llama), y lo que se
inyecta son datos REALES capturados de la maquina, no un comportamiento
inventado.
"""

import ast
import http.server
import json
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import servidor_modelo as SM

# Capturada el 2026-08-13 con Get-CimInstance Win32_Process del llama-server
# vivo en :8080 (pid 2784). Es el caso que restaurar() tiene que devolver
# intacto: --ctx-size 200192 y --log-disable incluidos.
CMDLINE_VIVA = (
    r"C:\Users\usuario\.cognia\llama\llama-server.exe --model "
    r"C:\Users\usuario\.cognia\models\Huihui-Qwythos-9B-Claude-Mythos-5-1M-"
    r"abliterated-Q4_K.gguf --host 127.0.0.1 --port 8080 --ctx-size 200192 "
    r"--parallel 1 --n-gpu-layers 99 --threads 12 --threads-batch 12 "
    r"--cache-reuse 256 --cache-ram 1024 --prio 2 --flash-attn on "
    r"--log-disable --spec-type ngram-mod"
)


# ---------------------------------------------------------------------------
# Utilidades: GGUF de verdad y servidor HTTP de verdad
# ---------------------------------------------------------------------------

def _cad(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def escribir_gguf(ruta: Path, *, arq: str = "qwen2", n_layer: int = 28,
                  n_head: int = 4, n_head_kv: int = 4, n_embd: int = 512,
                  head_dim: int = 128, ctx_train: int = 32768,
                  tam_mib: int = 100, sin_capas: bool = False) -> Path:
    """Escribe un GGUF con cabecera VALIDA (la lee ctx_maximo de verdad) y lo
    infla a `tam_mib` para que pesos_mib() vea un peso realista."""
    campos = []
    if not sin_capas:
        campos.append((f"{arq}.block_count", 4, n_layer))
    campos += [
        (f"{arq}.attention.head_count", 4, n_head),
        (f"{arq}.attention.head_count_kv", 4, n_head_kv),
        (f"{arq}.embedding_length", 4, n_embd),
        (f"{arq}.attention.key_length", 4, head_dim),
        (f"{arq}.context_length", 4, ctx_train),
        ("general.architecture", 8, arq),
    ]
    with open(ruta, "wb") as fh:
        fh.write(b"GGUF")
        fh.write(struct.pack("<I", 3))                 # version
        fh.write(struct.pack("<Q", 0))                 # tensor_count
        fh.write(struct.pack("<Q", len(campos)))       # n_kv
        for clave, tipo, valor in campos:
            fh.write(_cad(clave))
            fh.write(struct.pack("<I", tipo))
            if tipo == 8:
                fh.write(_cad(valor))
            else:
                fh.write(struct.pack("<I", valor))
        fh.truncate(tam_mib * 1024 * 1024)             # "pesos"
    return ruta


class _ManejadorSalud(http.server.BaseHTTPRequestHandler):
    codigo = 200
    modelo = ""          # '' = no expone /v1/models (no prueba identidad)

    def do_GET(self):
        if self.path == "/health":
            cuerpo = b'{"ok":true}'
            codigo = self.codigo
        elif self.path == "/v1/models" and self.modelo:
            cuerpo = json.dumps(
                {"models": [{"name": self.modelo, "model": self.modelo}]}
            ).encode("utf-8")
            codigo = 200
        else:
            self.send_error(404)
            return
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):    # silencio en la salida de pytest
        pass


def _servidor(codigo: int = 200, modelo: str = ""):
    """Servidor HTTP real en un puerto EFIMERO. Nunca el 8080.

    `modelo` = la ruta que devolvera /v1/models, o sea la PRUEBA DE IDENTIDAD
    que restaurar() exige antes de darse por satisfecha."""
    clase = type("Manejador", (_ManejadorSalud,),
                 {"codigo": codigo, "modelo": modelo})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), clase)
    assert srv.server_address[1] != SM.PUERTO_CEREBRO, "jamas el puerto del cerebro"
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    return srv, srv.server_address[1]


MODELO_VIVO = (r"C:\Users\usuario\.cognia\models\Huihui-Qwythos-9B-Claude-"
               r"Mythos-5-1M-abliterated-Q4_K.gguf")


def _dormilon() -> subprocess.Popen:
    """Un proceso REAL para matar (no es un llama-server: nada que ver con
    :8080). 120s es mas que cualquier test."""
    return subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(120)"])


# ---------------------------------------------------------------------------
# 1. Parseo de la cmdline
# ---------------------------------------------------------------------------

class TestPartirCmdline:

    def test_la_cmdline_viva_se_parte_entera(self):
        argv = SM.partir_cmdline(CMDLINE_VIVA)
        assert argv[0].endswith("llama-server.exe")
        assert argv[1] == "--model"
        assert argv[2].endswith("Q4_K.gguf")
        # Los pares que restaurar() tiene que devolver intactos:
        for flag, valor in (("--port", "8080"), ("--ctx-size", "200192"),
                            ("--cache-reuse", "256"), ("--prio", "2"),
                            ("--spec-type", "ngram-mod")):
            assert argv[argv.index(flag) + 1] == valor
        assert "--log-disable" in argv       # el del dueno lo lleva; se respeta

    def test_no_rompe_las_barras_de_windows(self):
        """shlex(posix) se comeria las '\\' de las rutas: por eso hay parser."""
        argv = SM.partir_cmdline(CMDLINE_VIVA)
        assert argv[2].startswith("C:\\Users\\usuario\\.cognia\\models\\")

    def test_comillas_agrupan_rutas_con_espacios(self):
        argv = SM.partir_cmdline(
            '"C:\\Program Files\\llama\\llama-server.exe" --model "D:\\mis '
            'modelos\\m.gguf" --port 8099')
        assert argv[0] == "C:\\Program Files\\llama\\llama-server.exe"
        assert argv[2] == "D:\\mis modelos\\m.gguf"
        assert argv[-1] == "8099"

    def test_argumento_vacio_entre_comillas(self):
        assert SM.partir_cmdline('exe "" x') == ["exe", "", "x"]

    def test_cadena_vacia(self):
        assert SM.partir_cmdline("") == []
        assert SM.partir_cmdline("   ") == []

    def test_ida_y_vuelta_por_subprocess(self):
        """El argv partido tiene que ser LANZABLE: se comprueba con un proceso
        real (python imprimiendo sus propios argumentos), no de palabra."""
        cmd = f'"{sys.executable}" -c "import sys;print(sys.argv[1])" hola-mundo'
        argv = SM.partir_cmdline(cmd)
        salida = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        assert salida.stdout.strip() == "hola-mundo"


class TestPuertoDeArgv:

    def test_lee_el_flag(self):
        assert SM.puerto_de_argv(SM.partir_cmdline(CMDLINE_VIVA)) == 8080

    def test_forma_con_igual(self):
        assert SM.puerto_de_argv(["exe", "--port=8082"]) == 8082

    def test_sin_flag_es_8080_que_es_el_cerebro(self):
        """El default de llama-server ES 8080: tratarlo como 'sin puerto'
        haria que el arnes ignore justo al proceso peligroso."""
        assert SM.puerto_de_argv(["exe", "--model", "x.gguf"]) == 8080


class TestLineaDeComandoActual:
    """Con la lista de procesos REAL capturada de la maquina."""

    def _procesos(self, *cmdlines):
        return [{"pid": 1000 + i, "cmdline": c} for i, c in enumerate(cmdlines)]

    def test_encuentra_el_del_puerto(self, monkeypatch):
        otro = CMDLINE_VIVA.replace("--port 8080", "--port 8081")
        monkeypatch.setattr(SM, "_procesos_llama",
                            lambda: self._procesos(otro, CMDLINE_VIVA))
        info = SM.linea_de_comando_actual(8080)
        assert info["pid"] == 1001
        assert info["cmdline"] == CMDLINE_VIVA
        assert info["argv"][0].endswith("llama-server.exe")

    def test_sin_llama_servers_devuelve_None(self, monkeypatch):
        monkeypatch.setattr(SM, "_procesos_llama", lambda: [])
        assert SM.linea_de_comando_actual(8080) is None

    def test_ningun_proceso_en_ese_puerto(self, monkeypatch):
        monkeypatch.setattr(SM, "_procesos_llama",
                            lambda: self._procesos(CMDLINE_VIVA))
        assert SM.linea_de_comando_actual(8081) is None

    def test_desempata_por_quien_escucha_de_verdad(self, monkeypatch):
        """Dos procesos con --port 8080 (uno zombie que no llego a bindear):
        gana el que netstat ve escuchando en 127.0.0.1."""
        monkeypatch.setattr(SM, "_procesos_llama",
                            lambda: self._procesos(CMDLINE_VIVA, CMDLINE_VIVA))
        monkeypatch.setattr(SM, "pid_del_puerto", lambda p: 1001)
        assert SM.linea_de_comando_actual(8080)["pid"] == 1001

    def test_un_server_sin_flag_de_puerto_cuenta_como_8080(self, monkeypatch):
        pelado = r"C:\llama\llama-server.exe --model C:\m.gguf --ctx-size 4096"
        monkeypatch.setattr(SM, "_procesos_llama",
                            lambda: self._procesos(pelado))
        assert SM.linea_de_comando_actual(8080)["cmdline"] == pelado


# ---------------------------------------------------------------------------
# 2. Construccion de flags (funcion pura)
# ---------------------------------------------------------------------------

class TestConstruirCmd:

    def cmd(self, **kw):
        return SM.construir_cmd("llama-server.exe", "C:\\m.gguf",
                                kw.pop("puerto", 8099), kw.pop("ctx", 8192),
                                kw.pop("extra_flags", ()))

    def par(self, orden, flag):
        return orden[orden.index(flag) + 1]

    def test_flags_del_repo(self):
        o = self.cmd()
        assert o[0] == "llama-server.exe"
        assert self.par(o, "--model") == "C:\\m.gguf"
        assert self.par(o, "--host") == "127.0.0.1"     # nunca 0.0.0.0
        assert self.par(o, "--n-gpu-layers") == "99"
        assert self.par(o, "--flash-attn") == "on"
        assert self.par(o, "--parallel") == "1"         # 4 slots parten el ctx
        assert self.par(o, "--prio") == "2"
        assert self.par(o, "--cache-reuse") == "256"
        assert self.par(o, "--cache-ram") == "1024"
        assert "--jinja" in o                           # regimen NATIVO

    def test_sin_log_disable(self):
        """El arnes TIENE que ver por que un candidato no carga."""
        assert "--log-disable" not in self.cmd()

    def test_puerto_y_ctx_van_como_texto(self):
        o = self.cmd(puerto=8099, ctx=16384)
        assert self.par(o, "--port") == "8099"
        assert self.par(o, "--ctx-size") == "16384"
        assert all(isinstance(x, str) for x in o)

    def test_hilos_iguales_en_decode_y_batch(self):
        o = self.cmd()
        assert self.par(o, "--threads") == self.par(o, "--threads-batch")

    def test_extra_flags_se_agregan(self):
        o = self.cmd(extra_flags=["--cache-type-k", "q8_0"])
        assert o[-2:] == ["--cache-type-k", "q8_0"]

    def test_extra_pisa_el_default_sin_duplicar(self):
        """Un flag repetido no lo resuelve llama-server de forma prometida:
        el default se QUITA."""
        o = self.cmd(extra_flags=["--flash-attn", "off"])
        assert o.count("--flash-attn") == 1
        assert self.par(o, "--flash-attn") == "off"

    def test_extra_pisa_tambien_en_forma_con_igual(self):
        o = self.cmd(extra_flags=["--ctx-size=4096"])
        assert o.count("--ctx-size") == 0
        assert "--ctx-size=4096" in o

    def test_no_lleva_martillo_global(self):
        assert "/IM" not in " ".join(self.cmd())


# ---------------------------------------------------------------------------
# 3. Matar SOLO el proceso propio
# ---------------------------------------------------------------------------

class TestParar:

    def test_mata_el_proceso_de_verdad(self):
        proc = _dormilon()
        assert proc.poll() is None
        assert SM.parar(proc, timeout_s=10) is True
        assert proc.poll() is not None
        assert SM._pid_vivo(proc.pid) is False

    def test_es_idempotente(self):
        proc = _dormilon()
        SM.parar(proc, timeout_s=10)
        assert SM.parar(proc, timeout_s=10) is True     # ya muerto: exito

    def test_mata_por_pid_pelado(self):
        proc = _dormilon()
        try:
            assert SM.parar(proc.pid, timeout_s=10) is True
            assert SM._pid_vivo(proc.pid) is False
        finally:
            proc.wait(timeout=10)

    def test_solo_muere_el_pedido(self):
        """La leccion en codigo: matar uno NO puede matar al de al lado (que es
        lo que hacia taskkill /IM con la flota compartida)."""
        victima, testigo = _dormilon(), _dormilon()
        try:
            SM.parar(victima, timeout_s=10)
            assert victima.poll() is not None
            assert testigo.poll() is None
            assert SM._pid_vivo(testigo.pid) is True
        finally:
            SM.parar(testigo, timeout_s=10)

    def test_kill_es_por_pid_nunca_por_imagen(self):
        cmd = SM._cmd_kill(777)
        assert "/IM" not in cmd
        if SM.os.name == "nt":
            assert cmd == ["taskkill", "/PID", "777", "/F"]

    def test_el_modulo_no_contiene_el_martillo_global(self):
        """Chequeo ejecutable, no leccion en prosa: si alguien vuelve a
        escribir taskkill /IM aca, este test se pone rojo.

        Se mira el AST y no el texto: el modulo EXPLICA en su docstring por que
        /IM esta prohibido, y una busqueda por texto no distingue la
        advertencia del arma. Lo que se prohibe es un literal '/IM' o 'pkill'
        que pueda acabar en un subprocess."""
        fuente = Path(SM.__file__).read_text(encoding="utf-8")
        arbol = ast.parse(fuente)
        docs = set()
        for n in ast.walk(arbol):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                cuerpo = getattr(n, "body", [])
                if cuerpo and isinstance(cuerpo[0], ast.Expr) \
                        and isinstance(cuerpo[0].value, ast.Constant):
                    docs.add(id(cuerpo[0].value))
        ejecutables = [n.value for n in ast.walk(arbol)
                       if isinstance(n, ast.Constant)
                       and isinstance(n.value, str) and id(n) not in docs]
        assert not [s for s in ejecutables if "/IM" in s or "pkill" in s]

    def test_el_modulo_es_ascii(self):
        """main() imprime __doc__ y la consola del dueno es cp1252: un guion
        largo en el docstring seria un UnicodeEncodeError al pedir ayuda."""
        fuente = Path(SM.__file__).read_text(encoding="utf-8")
        no_ascii = sorted({c for c in fuente if ord(c) > 127})
        assert not no_ascii, f"caracteres no ASCII en el modulo: {no_ascii}"


# ---------------------------------------------------------------------------
# 4. Salud (servidor HTTP real, puerto efimero)
# ---------------------------------------------------------------------------

class TestSalud:

    def test_estado_ok(self):
        srv, puerto = _servidor(200)
        try:
            assert SM.estado(puerto) == "ok"
            assert SM.esperar_salud(puerto, timeout_s=5) is True
        finally:
            srv.shutdown()

    def test_503_es_cargando_no_ausente(self):
        """Un server cargando su modelo ocupa el puerto: tratarlo como ausente
        es como se arrancaba un segundo server encima."""
        srv, puerto = _servidor(503)
        try:
            assert SM.estado(puerto) == "cargando"
        finally:
            srv.shutdown()

    def test_puerto_cerrado_es_ausente(self):
        srv, puerto = _servidor(200)
        srv.shutdown()
        srv.server_close()
        assert SM.estado(puerto) == "ausente"

    def test_espera_agota_y_devuelve_False(self):
        srv, puerto = _servidor(200)
        srv.shutdown()
        srv.server_close()
        t0 = time.time()
        assert SM.esperar_salud(puerto, timeout_s=2) is False
        assert time.time() - t0 < 15          # no se cuelga

    def test_corta_apenas_muere_el_proceso(self):
        """Un modelo que no cabe en la GPU muere en segundos: esperar los 240
        completos por candidato es tiempo tirado."""
        srv, puerto = _servidor(200)
        srv.shutdown()
        srv.server_close()
        proc = _dormilon()
        SM.parar(proc, timeout_s=10)
        t0 = time.time()
        assert SM.esperar_salud(puerto, timeout_s=60, proc=proc) is False
        assert time.time() - t0 < 10


class TestArrancarNoPisaUnPuertoOcupado:

    def test_se_niega_si_ya_hay_algo_sirviendo(self, tmp_path):
        """La proteccion que impide ponerle un segundo server encima al
        cerebro: falla ANTES de mirar el binario o el GGUF."""
        srv, puerto = _servidor(200)
        try:
            with pytest.raises(RuntimeError, match="ya hay un llama-server"):
                SM.arrancar(tmp_path / "no-existe.gguf", puerto=puerto,
                            ctx=4096)
        finally:
            srv.shutdown()

    def test_tambien_si_esta_cargando(self, tmp_path):
        srv, puerto = _servidor(503)
        try:
            with pytest.raises(RuntimeError):
                SM.arrancar(tmp_path / "no-existe.gguf", puerto=puerto)
        finally:
            srv.shutdown()


class TestRestaurar:
    """Ninguno de estos tests llega a lanzar un proceso: o el original ya esta
    (y restaurar() no relanza), o restaurar() se planta ANTES de lanzar."""

    def _cmd(self, puerto):
        return CMDLINE_VIVA.replace("--port 8080", f"--port {puerto}")

    def test_no_relanza_si_EL_ORIGINAL_ya_esta(self, monkeypatch, tmp_path):
        """El puerto responde 200 Y /v1/models dice que sirve NUESTRO gguf."""
        monkeypatch.setattr(SM, "RESCATE", tmp_path / "rescate.txt")
        srv, puerto = _servidor(200, modelo=MODELO_VIVO)
        try:
            assert SM.restaurar(self._cmd(puerto)) is None
        finally:
            srv.shutdown()

    def test_un_200_AJENO_no_cuenta_como_restaurado(self, monkeypatch, tmp_path):
        """LA REGRESION QUE IMPORTA: antes, cualquier cosa que contestara 200 en
        el puerto hacia que restaurar() dijera 'ya responde, no relanzo nada' y
        devolviera None. El dueno se quedaba sin cerebro y el arnes reportaba
        exito - la averia del :8088 otra vez. Ahora, si el ocupante no es el
        original y ni siquiera es un llama-server, revienta con la linea para
        copiar y pegar (y NO mata al ocupante: no es suyo)."""
        monkeypatch.setattr(SM, "RESCATE", tmp_path / "rescate.txt")
        srv, puerto = _servidor(200, modelo=r"C:\otro\modelo-distinto.gguf")
        try:
            with pytest.raises(RuntimeError, match="otro proceso"):
                SM.restaurar(self._cmd(puerto))
            assert srv.server_address[1] == puerto      # sigue vivo: no lo mato
        finally:
            srv.shutdown()

    def test_deja_el_comando_de_rescate_en_disco(self, monkeypatch, tmp_path):
        """Ni el finally ni el atexit corren si al arnes lo matan con /F: lo
        unico que queda es este fichero."""
        rescate = tmp_path / "rescate.txt"
        monkeypatch.setattr(SM, "RESCATE", rescate)
        srv, puerto = _servidor(200, modelo=MODELO_VIVO)
        try:
            SM.restaurar(self._cmd(puerto))
        finally:
            srv.shutdown()
        assert "--ctx-size 200192" in rescate.read_text(encoding="utf-8")

    def test_cmdline_vacia_es_error(self):
        with pytest.raises(ValueError):
            SM.restaurar("")

    def test_acepta_argv_ya_partido(self, monkeypatch, tmp_path):
        monkeypatch.setattr(SM, "RESCATE", tmp_path / "rescate.txt")
        srv, puerto = _servidor(200, modelo=MODELO_VIVO)
        try:
            argv = SM.partir_cmdline(self._cmd(puerto))
            assert SM.restaurar(argv) is None
        finally:
            srv.shutdown()


class TestPrestarPuerto:
    """El prestamo es la respuesta a 'se queda el dueno sin cerebro si...?'.
    Se prueba el CAMINO, no el llama-server: los dos extremos (parar de verdad,
    restaurar de verdad) tienen sus propios tests con procesos reales; aca se
    verifica que el finally los llame SIEMPRE y en el orden correcto."""

    def _espiar(self, monkeypatch, tmp_path):
        eventos = []
        monkeypatch.setattr(SM, "RESCATE", tmp_path / "rescate.txt")
        monkeypatch.setattr(SM, "linea_de_comando_actual",
                            lambda p=8080: {"pid": 4242, "cmdline": CMDLINE_VIVA,
                                            "argv": SM.partir_cmdline(CMDLINE_VIVA)})
        monkeypatch.setattr(SM, "parar",
                            lambda proc, timeout_s=20.0: eventos.append(
                                ("parar", proc)) or True)
        monkeypatch.setattr(SM, "esperar_puerto_libre",
                            lambda p, t=30.0: True)
        monkeypatch.setattr(SM, "restaurar",
                            lambda cmd, t=300.0, log=None: eventos.append(
                                ("restaurar", cmd)))
        return eventos

    def test_restaura_en_el_camino_feliz(self, monkeypatch, tmp_path):
        ev = self._espiar(monkeypatch, tmp_path)
        with SM.prestar_puerto(8080) as original:
            assert original["pid"] == 4242
        assert [e[0] for e in ev] == ["parar", "restaurar"]
        assert ev[1][1] == CMDLINE_VIVA          # la linea EXACTA

    def test_restaura_si_el_cuerpo_revienta(self, monkeypatch, tmp_path):
        ev = self._espiar(monkeypatch, tmp_path)
        with pytest.raises(ZeroDivisionError):
            with SM.prestar_puerto(8080):
                1 / 0
        assert [e[0] for e in ev] == ["parar", "restaurar"]

    def test_restaura_con_Ctrl_C(self, monkeypatch, tmp_path):
        """KeyboardInterrupt es BaseException: un `except Exception` no la ve.
        El finally si."""
        ev = self._espiar(monkeypatch, tmp_path)
        with pytest.raises(KeyboardInterrupt):
            with SM.prestar_puerto(8080):
                raise KeyboardInterrupt
        assert [e[0] for e in ev] == ["parar", "restaurar"]

    def test_restaura_con_sys_exit(self, monkeypatch, tmp_path):
        ev = self._espiar(monkeypatch, tmp_path)
        with pytest.raises(SystemExit):
            with SM.prestar_puerto(8080):
                sys.exit(3)
        assert [e[0] for e in ev] == ["parar", "restaurar"]

    def test_restaura_si_el_modelo_no_arranca(self, monkeypatch, tmp_path):
        """El caso mas comun del arnes: el candidato no entra en VRAM."""
        ev = self._espiar(monkeypatch, tmp_path)
        with pytest.raises(RuntimeError):
            with SM.prestar_puerto(8080):
                raise RuntimeError("el candidato no levanto")
        assert [e[0] for e in ev] == ["parar", "restaurar"]

    def test_restaura_una_sola_vez(self, monkeypatch, tmp_path):
        """El atexit es cinturon, no repeticion: si el finally ya restauro, la
        salida del proceso no relanza un segundo server."""
        ev = self._espiar(monkeypatch, tmp_path)
        with SM.prestar_puerto(8080):
            pass
        SM._restaurar_pendientes()
        assert [e[0] for e in ev].count("restaurar") == 1

    def test_no_para_lo_que_no_sabe_relanzar(self, tmp_path):
        """La regla del modulo: si no se pudo leer la linea de comando del que
        ocupa el puerto, NO se lo toca. Se prueba con un servidor HTTP real que
        no es ningun llama-server."""
        srv, puerto = _servidor(200)
        try:
            with pytest.raises(RuntimeError, match="no sabria como devolverlo"):
                with SM.prestar_puerto(puerto):
                    pytest.fail("no deberia haber entrado")
        finally:
            srv.shutdown()

    def test_puerto_libre_no_inventa_nada_que_restaurar(self, monkeypatch):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
        s.close()                     # puerto realmente libre
        monkeypatch.setattr(SM, "restaurar",
                            lambda *a, **k: pytest.fail("nada que restaurar"))
        with SM.prestar_puerto(puerto) as original:
            assert original is None


# ---------------------------------------------------------------------------
# 5. ctx_seguro y pesos (GGUF reales escritos por el test)
# ---------------------------------------------------------------------------

class TestIdentidadYPuerto:
    """Lo que distingue 'el puerto responde' de 'el puerto sirve MI modelo'."""

    def test_modelo_servido_lee_v1_models(self):
        srv, puerto = _servidor(200, modelo=MODELO_VIVO)
        try:
            assert SM.modelo_servido(puerto) == Path(MODELO_VIVO).name
        finally:
            srv.shutdown()

    def test_modelo_servido_vacio_si_no_hay_forma_de_saberlo(self):
        srv, puerto = _servidor(200)          # /health si, /v1/models no
        try:
            assert SM.modelo_servido(puerto) == ""
        finally:
            srv.shutdown()

    def test_modelo_de_argv(self):
        assert (SM.modelo_de_argv(SM.partir_cmdline(CMDLINE_VIVA))
                == Path(MODELO_VIVO).name)
        assert SM.modelo_de_argv(["exe", "--model=D:\\x\\y.gguf"]) == "y.gguf"
        assert SM.modelo_de_argv(["exe", "--port", "8080"]) == ""

    def test_puerto_libre_de_verdad(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        puerto = s.getsockname()[1]
        try:
            assert SM.puerto_libre(puerto) is False
        finally:
            s.close()
        assert SM.puerto_libre(puerto) is True
        assert SM.esperar_puerto_libre(puerto, 2) is True

    def test_esperar_puerto_libre_agota_sin_colgarse(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        try:
            t0 = time.time()
            assert SM.esperar_puerto_libre(s.getsockname()[1], 1.0) is False
            assert time.time() - t0 < 10
        finally:
            s.close()

    def test_pid_del_puerto_ignora_al_vecino_de_tailscale(self):
        """Contra el netstat REAL de esta maquina: en :8080 hay DOS listeners
        (127.0.0.1 -> llama-server, y 100.110.56.37/IPv6 -> tailscaled). El que
        vuelve tiene que ser el de loopback y ser un llama-server."""
        pid = SM.pid_del_puerto(SM.PUERTO_CEREBRO)
        if pid is None:
            pytest.skip("no hay nadie escuchando en el :8080 de loopback")
        assert pid in {p["pid"] for p in SM._procesos_llama()}, (
            "pid_del_puerto devolvio un proceso que no es llama-server: "
            "es exactamente como el summoner perdio el cerebro")
        assert SM.pid_llama_del_puerto(SM.PUERTO_CEREBRO) == pid

    def test_no_muere_con_la_consola(self):
        """Windows manda el Ctrl-C a TODO el grupo de la consola: sin grupo
        propio, abortar el arnes mata tambien al server recien restaurado."""
        flags = SM._flags_proceso(despegar=False)
        if SM.os.name == "nt":
            assert flags["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
            assert not (flags["creationflags"] & subprocess.DETACHED_PROCESS)
            assert (SM._flags_proceso(True)["creationflags"]
                    & subprocess.DETACHED_PROCESS)
        else:
            assert flags["start_new_session"] is True

    def test_lanzar_no_deja_el_handle_del_log_abierto(self, tmp_path):
        """Un proceso REAL escribiendo en el log: el fichero se puede borrar
        despues, o sea que el padre no se quedo con el handle tomado."""
        log = tmp_path / "sub" / "salida.log"
        proc = SM._lanzar([sys.executable, "-c", "print('hola-log')"], log)
        proc.wait(timeout=60)
        assert "hola-log" in log.read_text(encoding="utf-8", errors="replace")
        log.unlink()          # en Windows falla si el padre lo tiene abierto


class TestPesos:

    def test_suma_las_partes_de_un_gguf_partido(self, tmp_path):
        """qwen2.5-coder-14b: 7.630 MiB la parte 1 de 8.572 totales. Contar
        solo la primera regala 942 MiB de VRAM que no existen."""
        p1 = escribir_gguf(tmp_path / "m-00001-of-00002.gguf", tam_mib=100)
        escribir_gguf(tmp_path / "m-00002-of-00002.gguf", tam_mib=900)
        assert SM.pesos_mib(p1) == pytest.approx(1000, abs=1)

    def test_fichero_suelto(self, tmp_path):
        suelto = escribir_gguf(tmp_path / "suelto.gguf", tam_mib=100)
        assert SM.pesos_mib(suelto) == pytest.approx(100, abs=1)

    def test_nombre_con_corchetes(self, tmp_path):
        """Un glob armado con el nombre del fichero trata los corchetes como
        clase de caracteres y solo encuentra la primera parte: 900 MiB de VRAM
        regalados y un ctx que no cabe."""
        p1 = escribir_gguf(tmp_path / "mix[Q4]-00001-of-00002.gguf", tam_mib=100)
        escribir_gguf(tmp_path / "mix[Q4]-00002-of-00002.gguf", tam_mib=900)
        assert SM.pesos_mib(p1) == pytest.approx(1000, abs=1)

    def test_no_suma_las_partes_de_OTRO_modelo(self, tmp_path):
        p1 = escribir_gguf(tmp_path / "a-00001-of-00002.gguf", tam_mib=100)
        escribir_gguf(tmp_path / "a-00002-of-00002.gguf", tam_mib=200)
        escribir_gguf(tmp_path / "b-00001-of-00002.gguf", tam_mib=500)
        assert SM.pesos_mib(p1) == pytest.approx(300, abs=1)


class TestCtxSeguro:

    def test_lo_limita_el_ctx_entrenado(self, tmp_path):
        g = escribir_gguf(tmp_path / "a.gguf", ctx_train=32768, tam_mib=100)
        assert SM.ctx_seguro(g, 16311) == 32768

    def test_lo_limita_la_vram(self, tmp_path):
        g = escribir_gguf(tmp_path / "a.gguf", ctx_train=32768, tam_mib=100)
        # 2000 - 100 (pesos) - 1229 (reserva) = 671 MiB para KV;
        # KV = 28*4*128*2*2 = 57.344 B/token; x0.8 de margen.
        n = SM.ctx_seguro(g, 2000)
        assert 0 < n < 32768
        assert n == int(671 * 1024 ** 2 * 0.8 / 57344) // 256 * 256

    def test_siempre_multiplo_de_256(self, tmp_path):
        g = escribir_gguf(tmp_path / "a.gguf", ctx_train=1048576, tam_mib=100)
        for vram in (2000, 4000, 8000, 16311):
            assert SM.ctx_seguro(g, vram) % 256 == 0

    def test_techo_del_arnes(self, tmp_path):
        """Un KV minusculo daria millones de tokens: arriba del techo solo se
        va con celdas MEDIDAS (summoner.ESCALERA_CTX), no con esta cuenta."""
        g = escribir_gguf(tmp_path / "chico.gguf", n_layer=4, n_head=1,
                          n_head_kv=1, head_dim=64, ctx_train=1048576,
                          tam_mib=100)
        assert SM.ctx_seguro(g, 16311) == SM.TECHO_CTX

    def test_no_cabe_ni_el_modelo(self, tmp_path):
        g = escribir_gguf(tmp_path / "gordo.gguf", tam_mib=14000)
        assert SM.ctx_seguro(g, 16311 - 8000) == 0

    def test_cabe_el_modelo_pero_no_un_ctx_util(self, tmp_path):
        g = escribir_gguf(tmp_path / "a.gguf", tam_mib=100)
        assert SM.ctx_seguro(g, 1350) == 0      # 21 MiB de KV = 307 tokens

    def test_las_partes_bajan_el_ctx(self, tmp_path):
        p1 = escribir_gguf(tmp_path / "m-00001-of-00002.gguf",
                           ctx_train=1048576, tam_mib=100)
        escribir_gguf(tmp_path / "m-00002-of-00002.gguf", tam_mib=900)
        suelto = escribir_gguf(tmp_path / "s.gguf", ctx_train=1048576,
                               tam_mib=100)
        assert SM.ctx_seguro(p1, 4000) < SM.ctx_seguro(suelto, 4000)

    def test_cabecera_incompleta_no_inventa_un_numero(self, tmp_path):
        g = escribir_gguf(tmp_path / "roto.gguf", sin_capas=True)
        with pytest.raises(ValueError, match="cabecera GGUF incompleta"):
            SM.ctx_seguro(g, 16311)

    def test_es_conservador_con_el_cerebro_real(self):
        """El limite DECLARADO en el docstring, medido: la formula de cabecera
        da 132 KB/token en Qwythos-9B (arq hibrida) donde lo real son 38 B, asi
        que esta cuenta jamas autorizaria la ventana de 200.192 que el server
        sirve hoy. Se verifica contra el GGUF real si esta en la maquina."""
        reales = list(SM.DIR_MODELOS.glob("*Qwythos*.gguf"))
        if not reales:
            pytest.skip("el GGUF de Qwythos no esta en esta maquina")
        n = SM.ctx_seguro(reales[0], SM.VRAM_TOTAL_MIB)
        assert n >= SM.CTX_MINIMO         # arranca
        assert n < 200192                 # y no promete lo que no puede medir
