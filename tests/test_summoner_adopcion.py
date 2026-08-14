"""
tests/test_summoner_adopcion.py
===============================
C3 (2026-08-13): el summoner ADOPTA el llama-server que ya sirve el puerto, y
deja de confundir a tailscaled con el cerebro.

REGLA DE ESTE FICHERO: ni un solo test toca el :8080 vivo, ni arranca ni mata
un proceso. Lo que se inyecta es la salida REAL de `netstat -ano` capturada de
esta maquina el 2026-08-13 (con la linea de tailscale ANTES que la de
loopback, que es el orden que producia la averia) y la lista de procesos que
devuelve CIM. Los cuatro sintomas MEDIDOS que estos tests fijan:

  1. _pid_dueno_del_puerto(20872, 8080) devolvia False siendo 20872 EL
     llama-server -> liberar() borraba la entrada del rol y NO mataba: la VRAM
     (12,8 GB) no se liberaba nunca e invocar() esperaba 30 s en vano.
  2. Con summoner.json VACIO y el :8080 respondiendo Qwythos, ensure('cerebro')
     retornaba sin escribir estado: `cognia flota estado` decia en la misma
     salida ":8080 RESPONDE - Qwythos" y "cerebro rancio (pid 18388 muerto)",
     vivos() daba {} y el planificador no podia evictar al cerebro.
  3. escalar_ctx devolvia el n_ctx que DECLARA la celda, descartando el que
     /props MIDE.
  4. El cerebro declaraba 11000 MiB de VRAM y lo medido son 12807.

Y el quinto, de flota: parar() era un martillo por nombre de imagen que
mataba TODOS los llama-server de la maquina, y arrancar() lo disparaba solo.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from cognia import flota as F
from cognia import puertos as P
from cognia import summoner as S

RAIZ = Path(__file__).resolve().parent.parent

PID_LLAMA = 20872        # el cerebro, en 127.0.0.1:8080
PID_TAILSCALE = 7520     # tailscaled, en 100.110.56.37:8080 (y su IPv6)

CMDLINE_LLAMA = (
    r"C:\Users\usuario\.cognia\llama\llama-server.exe --model "
    r"C:\Users\usuario\.cognia\models\Huihui-Qwythos-9B-Q4_K.gguf "
    r"--host 127.0.0.1 --port 8080 --ctx-size 200192 --parallel 1"
)

# `netstat -ano` de esta maquina, 2026-08-13. El orden importa y es el REAL:
# tailscaled aparece PRIMERO. Cualquier busqueda que se quede con la primera
# linea que contenga ':8080 ' y LISTENING concluye que el cerebro no es dueno
# de su puerto -- exactamente la averia que este fichero vigila.
NETSTAT_REAL = """
Conexiones activas

  Proto  Direccion local        Direccion remota       Estado           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1544
  TCP    100.110.56.37:8080     0.0.0.0:0              LISTENING       7520
  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       20872
  TCP    127.0.0.1:8080         127.0.0.1:55507        TIME_WAIT       0
  TCP    127.0.0.1:8080         127.0.0.1:55551        TIME_WAIT       0
  TCP    [fd7a:115c:a1e0::1]:8080  [::]:0              LISTENING       7520
  TCP    127.0.0.1:8081         0.0.0.0:0              LISTENING       9001
  TCP    [::]:445               [::]:0                 LISTENING       4
"""


class _Sondas:
    """Lo que la maquina 'contesta' en el test: netstat fijo, la lista de
    procesos llama-server de CIM y quien esta vivo para tasklist."""

    def __init__(self):
        self.netstat = NETSTAT_REAL
        self.procesos = [{"pid": PID_LLAMA, "cmdline": CMDLINE_LLAMA}]
        self.vivos = {PID_LLAMA, PID_TAILSCALE, 9001}
        self.ejecutados: list[list] = []


@pytest.fixture
def maquina(monkeypatch):
    """Windows simulado con netstat/CIM/tasklist FIJOS.

    Se parchea subprocess.run tal como lo ve cognia.puertos (que es el modulo
    subprocess global): cualquier proceso que no sea uno de los tres esperados
    revienta el test en vez de ejecutarse de verdad. Asi ningun test de este
    fichero puede tocar la maquina por accidente."""
    sondas = _Sondas()

    def fake_run(cmd, *a, **k):
        cmd = list(cmd)
        sondas.ejecutados.append(cmd)
        exe = str(cmd[0]).lower()
        if exe.startswith("netstat"):
            return subprocess.CompletedProcess(cmd, 0, sondas.netstat, "")
        if exe.startswith("powershell"):
            crudo = json.dumps([{"ProcessId": p["pid"],
                                 "CommandLine": p["cmdline"]}
                                for p in sondas.procesos])
            return subprocess.CompletedProcess(cmd, 0, crudo, "")
        if exe.startswith("tasklist"):
            pedido = cmd[cmd.index("/FI") + 1].split()[-1]
            salida = (f"proc.exe   {pedido} Console  1  100 K"
                      if int(pedido) in sondas.vivos else "INFO: no tasks")
            return subprocess.CompletedProcess(cmd, 0, salida, "")
        raise AssertionError(f"el test no debia ejecutar: {cmd}")

    monkeypatch.setattr(P.os, "name", "nt")
    monkeypatch.setattr(S.sys, "platform", "win32")
    monkeypatch.setattr(P.subprocess, "run", fake_run)
    return sondas


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Estado del summoner en tmp, reloj congelado, sin sleeps (calcado de
    tests/test_summoner.py: misma seam, mismo contrato)."""
    monkeypatch.setenv("COGNIA_SUMMONER_STATE", str(tmp_path / "summoner.json"))
    monkeypatch.setattr(S, "_ahora", lambda: 1000.0)
    monkeypatch.setattr(S, "_dormir", lambda s: None)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. cognia/puertos.py: quien escucha de verdad
# ---------------------------------------------------------------------------

def test_el_fixture_pone_a_tailscale_primero():
    """Si alguien 'ordena' el netstat de arriba, los tests de abajo dejan de
    probar nada: el bug era justo el ORDEN de las lineas."""
    assert (NETSTAT_REAL.index("100.110.56.37:8080")
            < NETSTAT_REAL.index("127.0.0.1:8080"))


def test_pid_del_puerto_devuelve_el_de_loopback_no_el_de_tailscale(maquina):
    assert P.pid_del_puerto(8080) == PID_LLAMA
    assert P.pid_del_puerto(8081) == 9001
    assert P.pid_del_puerto(9999) is None      # nadie escucha: no se inventa


def test_pid_llama_del_puerto_exige_que_sea_un_llama_server(maquina):
    assert P.pid_llama_del_puerto(8080) == PID_LLAMA
    # el :8081 lo tiene un proceso que CIM no lista como llama-server: matarlo
    # seria peor que la averia que se esta arreglando
    assert P.pid_llama_del_puerto(8081) is None
    maquina.procesos = []
    assert P.pid_llama_del_puerto(8080) is None


def test_servidor_modelo_reexporta_sin_duplicar():
    """scripts/ no viaja en el wheel: la fuente de verdad es el paquete y el
    script re-exporta. Dos copias del mismo netstat es como el :8088 sirvio un
    modelo retirado durante semanas."""
    sys.path.insert(0, str(RAIZ))
    from scripts import servidor_modelo as SM
    assert SM.pid_del_puerto is P.pid_del_puerto
    assert SM.pid_llama_del_puerto is P.pid_llama_del_puerto
    assert SM._procesos_llama is P.procesos_llama
    fuente = (RAIZ / "scripts" / "servidor_modelo.py").read_text(
        encoding="utf-8", errors="replace")
    assert "def pid_del_puerto" not in fuente
    assert "def pid_llama_del_puerto" not in fuente


# ---------------------------------------------------------------------------
# 2. El bug del vecino: liberar() perdia al cerebro
# ---------------------------------------------------------------------------

def test_pid_dueno_del_puerto_reconoce_al_cerebro_pese_a_tailscale(maquina):
    """REGRESION: pre-fix esto devolvia False para el PID del cerebro porque
    la primera linea con ':8080 ' y LISTENING es la de tailscaled."""
    assert S._pid_dueno_del_puerto(PID_LLAMA, 8080) is True
    assert S._pid_dueno_del_puerto(PID_TAILSCALE, 8080) is False
    assert S._pid_dueno_del_puerto(PID_LLAMA, 9999) is None   # sin listener


def test_liberar_el_cerebro_mata_de_verdad(sandbox, maquina, monkeypatch):
    """REGRESION del sintoma caro: con el dueno mal resuelto, liberar() borraba
    la entrada, NO mataba y la VRAM no volvia nunca."""
    estado = S._leer_estado()
    estado["roles"]["cerebro"] = {"pid": PID_LLAMA, "puerto": 8080,
                                  "t_arranque": 1000.0, "t_ultima": 1000.0}
    S._guardar_estado(estado)
    muertos = []
    monkeypatch.setattr(S, "_matar_pid", lambda pid: muertos.append(pid))
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    monkeypatch.setattr(S, "_invalidar_caches", lambda: None)
    assert S.liberar("cerebro") is True
    assert muertos == [PID_LLAMA], "no mato al cerebro: la VRAM se queda tomada"
    assert S._leer_estado()["roles"] == {}


def test_liberar_sigue_sin_matar_a_un_inocente(sandbox, maquina, monkeypatch):
    """El otro lado de la moneda: si el puerto lo tiene OTRO pid, no se mata."""
    estado = S._leer_estado()
    estado["roles"]["cerebro"] = {"pid": 4242, "puerto": 8080,
                                  "t_arranque": 1000.0, "t_ultima": 1000.0}
    S._guardar_estado(estado)
    maquina.vivos.add(4242)
    monkeypatch.setattr(S, "_matar_pid",
                        lambda pid: pytest.fail("mato a un inocente"))
    monkeypatch.setattr(S, "_invalidar_caches", lambda: None)
    assert S.liberar("cerebro") is False
    assert S._leer_estado()["roles"] == {}


# ---------------------------------------------------------------------------
# 3. ADOPCION: el server vivo entra al estado
# ---------------------------------------------------------------------------

PROPS_CEREBRO = {"modelo": "Huihui-Qwythos-9B-Q4_K.gguf", "n_ctx": 200192,
                 "puerto": 8080}


def test_ensure_adopta_el_server_vivo_con_estado_vacio(sandbox, maquina,
                                                       monkeypatch):
    """EL caso del informe: :8080 respondiendo Qwythos y summoner.json vacio.
    Pre-fix: ensure devolvia ok, vivos() seguia en {} y nadie podia evictar."""
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props", lambda url: dict(PROPS_CEREBRO))
    monkeypatch.setattr(S, "_lanzar",
                        lambda *a: pytest.fail("relanzo un server que ya vivia"))
    assert S._leer_estado()["roles"] == {}

    r = S.ensure("cerebro")
    assert r["ok"] and r["arranque_frio"] is False
    assert r["pid"] == PID_LLAMA

    vivos = S.vivos()
    assert vivos["cerebro"]["pid"] == PID_LLAMA
    entrada = S._leer_estado()["roles"]["cerebro"]
    assert entrada["adoptada"] is True
    # MEDIDO de /props, no declarado por la celda del registry
    assert entrada["n_ctx"] == 200192
    assert entrada["modelo"] == "Huihui-Qwythos-9B-Q4_K.gguf"
    assert entrada["cache"] == "", "el cache no sale de /props: no se inventa"


def test_flota_estado_deja_de_contradecirse(sandbox, maquina, monkeypatch):
    """El sintoma que veia el dueno: ':8080 RESPONDE - Qwythos' junto a
    'cerebro rancio/dormido' en la MISMA salida."""
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props", lambda url: dict(PROPS_CEREBRO))
    assert S.estado_roles()["cerebro"] == "dormido"     # antes de adoptar
    S.ensure("cerebro")
    linea = S.estado_roles()["cerebro"]
    assert linea.startswith(f"VIVO pid={PID_LLAMA} :8080")
    assert "Qwythos" in linea


def test_ensure_adopta_tambien_una_entrada_rancia(sandbox, maquina, monkeypatch):
    """PID viejo muerto en el estado + el server correcto vivo: la entrada se
    corrige al PID que escucha AHORA (antes quedaba 'rancio' para siempre)."""
    estado = S._leer_estado()
    estado["roles"]["cerebro"] = {"pid": 18388, "puerto": 8080,
                                  "t_arranque": 1.0, "t_ultima": 1.0}
    S._guardar_estado(estado)
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props", lambda url: dict(PROPS_CEREBRO))
    r = S.ensure("cerebro")
    assert r["pid"] == PID_LLAMA
    assert S._leer_estado()["roles"]["cerebro"]["pid"] == PID_LLAMA


def test_ensure_no_registra_lo_que_no_es_un_llama_server(sandbox, maquina,
                                                         monkeypatch, capsys):
    """Sin PID confirmado NO se inventa entrada (registrar un pid ajeno como
    'cerebro' termina en un kill a ciegas, solo que mas tarde)."""
    maquina.procesos = []          # CIM no ve ningun llama-server
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props", lambda url: dict(PROPS_CEREBRO))
    r = S.ensure("cerebro")
    assert r["ok"] is True         # el server sirve: no se rompe nada
    assert S._leer_estado()["roles"] == {}
    assert "no pude confirmar" in capsys.readouterr().err


def test_adoptar_no_toca_el_puerto_si_el_pid_guardado_vive(sandbox, maquina,
                                                           monkeypatch):
    """Camino caliente: con nuestro PID vivo no se consulta netstat/CIM (dos
    subprocesos por cada ensure serian un peaje por request)."""
    estado = S._leer_estado()
    estado["roles"]["cerebro"] = {"pid": PID_LLAMA, "puerto": 8080,
                                  "t_arranque": 1000.0, "t_ultima": 1000.0}
    S._guardar_estado(estado)
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (200, None))
    monkeypatch.setattr(S, "_props", lambda url: dict(PROPS_CEREBRO))
    maquina.ejecutados.clear()
    r = S.ensure("cerebro")
    assert r["pid"] == PID_LLAMA
    assert not [c for c in maquina.ejecutados
                if str(c[0]).lower().startswith(("netstat", "powershell"))]


# ---------------------------------------------------------------------------
# 4. escalar_ctx devuelve lo MEDIDO
# ---------------------------------------------------------------------------

def test_escalar_ctx_devuelve_el_n_ctx_medido(sandbox, monkeypatch):
    monkeypatch.setattr(S, "_props", lambda url: {"n_ctx": 32768})
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    monkeypatch.setattr(S, "ensure",
                        lambda rol, **kw: {"ok": True, "pid": 5,
                                           "n_ctx": 200192})
    r = S.escalar_ctx(140000)
    assert r["n_ctx"] == 200192 and r["relanzado"] is True


def test_escalar_ctx_falla_si_el_medido_no_es_el_de_la_celda(sandbox,
                                                             monkeypatch):
    """--fit auto-reduce en silencio: devolver el n_ctx de la celda seria
    publicar una ventana fantasma que el server no esta sirviendo."""
    monkeypatch.setattr(S, "_props", lambda url: {"n_ctx": 32768})
    monkeypatch.setattr(S, "_salud", lambda puerto, timeout=3.0: (None, None))
    monkeypatch.setattr(S, "ensure",
                        lambda rol, **kw: {"ok": True, "pid": 5,
                                           "n_ctx": 131072})
    with pytest.raises(S.SummonerError, match="131072"):
        S.escalar_ctx(140000)


# ---------------------------------------------------------------------------
# 5. La VRAM del cerebro sale de la celda MEDIDA
# ---------------------------------------------------------------------------

VRAM_MEDIDA_CEREBRO = 12807      # nvidia-smi, cerebro sirviendo 200192 en f16


def test_vram_del_cerebro_cubre_lo_medido(sandbox):
    assert S.ROLES["cerebro"]["vram_mib"] >= VRAM_MEDIDA_CEREBRO
    # estado vacio -> el --ctx del registry (32768), cuya celda no tiene VRAM
    # medida: se usa la primera celda MEDIDA que la cubre (200192/f16 = 12852)
    assert S.vram_cerebro_mib() == 12852


def test_vram_del_cerebro_sigue_a_la_celda_en_uso(sandbox):
    estado = S._leer_estado()
    estado["roles"]["cerebro"] = {"pid": 1, "puerto": 8080, "n_ctx": 262144,
                                  "cache": "q8_0", "t_ultima": 1000.0}
    S._guardar_estado(estado)
    assert S.vram_cerebro_mib() == 11621        # celda 262144/q8_0, 2026-08-09
    assert S._vram_rol("cerebro") == 11621
    assert S._vram_rol("vlm") == 3300           # el resto lo declara el registry


def test_cabe_sin_cerebro_suelta_lo_medido(sandbox, monkeypatch):
    """Con 15000 MiB tomados, 'imagen' (12000+512) SOLO cabe si evictar al
    cerebro suelta lo medido: con los 11000 declarados daba 'no cabe'."""
    monkeypatch.setattr(S, "vram_mib", lambda: (15000, 16311))
    estado = S._leer_estado()
    estado["roles"]["cerebro"] = {"pid": 1, "puerto": 8080, "n_ctx": 200192,
                                  "t_ultima": 1000.0}
    S._guardar_estado(estado)
    assert S.cabe("imagen", con_cerebro=True)[0] is False
    ok, motivo = S.cabe("imagen", con_cerebro=False)
    assert ok, motivo


# ---------------------------------------------------------------------------
# 6. flota.parar: por PID, no por nombre de imagen
# ---------------------------------------------------------------------------

@pytest.fixture
def flota_sin_matar(monkeypatch):
    """Registra los comandos de kill en vez de ejecutarlos."""
    ordenes = []

    def fake_run(cmd, *a, **k):
        ordenes.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), 0, "", "")

    monkeypatch.setattr(F.subprocess, "run", fake_run)
    return ordenes


def test_parar_mata_por_pid_y_respeta_lo_ajeno(monkeypatch, flota_sin_matar,
                                               capsys):
    monkeypatch.setattr(P, "pid_llama_del_puerto",
                        lambda puerto: PID_LLAMA if puerto == 8080 else None)
    monkeypatch.setattr(P, "pid_del_puerto",
                        lambda puerto: PID_TAILSCALE if puerto == 8081 else None)
    assert F.parar() == 0
    assert flota_sin_matar == [F._cmd_kill(PID_LLAMA)]
    for orden in flota_sin_matar:
        assert "/IM" not in orden and "llama-server.exe" not in orden
    salida = capsys.readouterr().out
    assert f":8080 detenido (pid {PID_LLAMA})" in salida
    assert f":8081 lo ocupa el pid {PID_TAILSCALE}" in salida


def test_parar_sin_flota_viva_no_ejecuta_nada(monkeypatch, flota_sin_matar,
                                              capsys):
    monkeypatch.setattr(P, "pid_llama_del_puerto", lambda puerto: None)
    monkeypatch.setattr(P, "pid_del_puerto", lambda puerto: None)
    assert F.parar() == 0
    assert flota_sin_matar == []
    assert "No habia llama-server de la flota vivo" in capsys.readouterr().out


def test_el_martillo_global_solo_con_todos(flota_sin_matar):
    assert F.parar(todos=True) == 0
    assert len(flota_sin_matar) == 1
    orden = flota_sin_matar[0]
    assert ("/IM" in orden) if F.os.name == "nt" else ("pkill" in orden[0])


def test_cli_parar_no_pide_el_martillo_por_su_cuenta(monkeypatch):
    pedidos = []
    monkeypatch.setattr(F, "parar",
                        lambda todos=False: pedidos.append(todos) or 0)
    assert F.main(["parar"]) == 0
    assert F.main(["parar", "--todos"]) == 0
    assert pedidos == [False, True]


def test_el_kill_global_vive_solo_en_parar_todos():
    """Gemelo del test de scripts/servidor_modelo.py: se prohibe el LITERAL
    ejecutable, no la palabra (los comentarios explican el arma y no son el
    arma). Fuera de _parar_todos, ningun string de flota.py puede llevar '/IM'
    ni 'pkill'."""
    fuente = (RAIZ / "cognia" / "flota.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    permitido = [n for n in ast.walk(arbol)
                 if isinstance(n, ast.FunctionDef) and n.name == "_parar_todos"]
    assert len(permitido) == 1
    ini, fin = permitido[0].lineno, permitido[0].end_lineno
    docstrings = set()
    for n in ast.walk(arbol):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            cuerpo = getattr(n, "body", [])
            if cuerpo and isinstance(cuerpo[0], ast.Expr) \
                    and isinstance(cuerpo[0].value, ast.Constant):
                docstrings.add(id(cuerpo[0].value))
    culpables = [n.lineno for n in ast.walk(arbol)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docstrings
                 and ("/IM" in n.value or "pkill" in n.value)
                 and not (ini <= n.lineno <= fin)]
    assert not culpables, (
        f"martillo global fuera de _parar_todos, lineas {culpables}")
