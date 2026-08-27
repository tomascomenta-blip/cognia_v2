"""
Tests de los MCP externos: los servidores que el dueno ya tiene configurados
para otros clientes de IA, usados desde Cognia (2026-08-26).

Sin red y sin subprocesos de verdad salvo donde se dice: el servidor MCP se
simula con un script de Python que habla el protocolo por stdin/stdout, que es
EXACTAMENTE lo que hace un servidor real. Asi el transporte se prueba de punta
a punta -- framing NDJSON incluido -- sin depender de que npx o Roblox Studio
esten instalados en la maquina que corra la suite.
"""
import json
import os
import sys
import textwrap

import pytest

from cognia.mcp_externos import (ClienteStdio, ORIGENES, ServidorExterno,
                                 _entrada_a_servidor, descubrir,
                                 formatear_descubiertos)
from cognia.mcp_libre import ErrorMCP


# ── un servidor MCP de mentira, pero con el protocolo de verdad ────────────

SERVIDOR_FALSO = textwrap.dedent('''
    import json, sys
    # Un servidor MCP stdio real: un JSON por linea, y logs a stderr (que es
    # justo lo que NO debe colarse en el canal).
    print("aviso de arranque que no es JSON", file=sys.stderr, flush=True)
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        msg = json.loads(linea)
        met, mid = msg.get("method"), msg.get("id")
        if met == "notifications/initialized":
            continue                      # notificacion: no se contesta
        if met == "initialize":
            r = {"protocolVersion": "2024-11-05",
                 "serverInfo": {"name": "falso", "version": "9.9"}}
        elif met == "tools/list":
            r = {"tools": [{"name": "saluda", "description": "dice hola",
                            "inputSchema": {"type": "object",
                                            "properties": {"a_quien": {"type": "string"}},
                                            "required": ["a_quien"]}}]}
        elif met == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            if (msg.get("params") or {}).get("name") == "rompe":
                r = {"content": [{"type": "text", "text": "algo salio mal"}],
                     "isError": True}
            else:
                r = {"content": [{"type": "text",
                                  "text": "hola " + str(args.get("a_quien", "?"))}]}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "error": {"code": -32601, "message": "metodo desconocido"}}),
                  flush=True)
            continue
        # Ruido a proposito: una notificacion del servidor ANTES de la
        # respuesta. Un cliente que tome "el primer renglon" se la come.
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message",
                          "params": {"level": "info"}}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": r}), flush=True)
''')


@pytest.fixture
def servidor(tmp_path):
    ruta = tmp_path / "servidor_falso.py"
    ruta.write_text(SERVIDOR_FALSO, encoding="utf-8")
    cli = ClienteStdio(sys.executable, ["-u", str(ruta)])
    try:
        yield cli
    finally:
        cli.cerrar()


# ── el transporte ──────────────────────────────────────────────────────────

def test_handshake_y_listado_contra_un_servidor_stdio_real(servidor):
    """El ciclo entero: initialize -> initialized -> tools/list."""
    info = servidor.conectar()
    assert info["serverInfo"]["name"] == "falso"
    assert servidor.servidor.get("version") == "9.9"
    hs = servidor.listar_herramientas()
    assert [h.nombre for h in hs] == ["saluda"]
    assert hs[0].esquema["required"] == ["a_quien"]


def test_ejecutar_una_herramienta(servidor):
    assert servidor.llamar("saluda", {"a_quien": "Tomas"}) == "hola Tomas"


def test_un_fallo_de_la_tool_no_se_confunde_con_uno_del_transporte(servidor):
    """`isError` es del protocolo: la llamada FUE bien y la herramienta fallo.
    Verlos iguales haria pensar que el servidor esta roto."""
    out = servidor.llamar("rompe", {})
    assert "ERROR de la herramienta 'rompe'" in out
    assert "algo salio mal" in out


def test_las_notificaciones_del_servidor_no_se_toman_por_la_respuesta(servidor):
    """El servidor falso mete una notificacion ANTES de cada respuesta. Un
    cliente que lea "el primer renglon que llegue" devolveria eso. Se lee
    hasta encontrar el id pedido."""
    servidor.conectar()
    for _ in range(3):
        assert servidor.llamar("saluda", {"a_quien": "x"}) == "hola x"


def test_stderr_no_contamina_el_canal(servidor):
    """El servidor escribe en stderr al arrancar. Si eso entrara en el canal
    JSON-RPC, el parseo reventaria en el primer mensaje."""
    servidor.conectar()
    assert any("aviso de arranque" in l for l in servidor._stderr)
    assert servidor.llamar("saluda", {"a_quien": "y"}) == "hola y"


def test_un_comando_que_no_existe_dice_QUE_comando(tmp_path):
    c = ClienteStdio("no_existe_este_binario_xyz", [])
    with pytest.raises(ErrorMCP) as exc:
        c.conectar()
    assert "no_existe_este_binario_xyz" in str(exc.value)


def test_un_servidor_que_muere_al_arrancar_reporta_su_stderr(tmp_path):
    """Sin el diagnostico de stderr, un servidor que revienta al arrancar sale
    como un timeout mudo y no hay forma de saber por que."""
    ruta = tmp_path / "muere.py"
    ruta.write_text("import sys; print('faltan dependencias', file=sys.stderr)",
                    encoding="utf-8")
    c = ClienteStdio(sys.executable, ["-u", str(ruta)])
    try:
        with pytest.raises(ErrorMCP) as exc:
            c.conectar()
        assert "faltan dependencias" in str(exc.value)
    finally:
        c.cerrar()


def test_cerrar_es_idempotente_y_no_lanza(servidor):
    servidor.conectar()
    servidor.cerrar()
    servidor.cerrar()          # no revienta
    assert servidor.conectado is False


def test_sirve_de_context_manager(tmp_path):
    ruta = tmp_path / "s.py"
    ruta.write_text(SERVIDOR_FALSO, encoding="utf-8")
    with ClienteStdio(sys.executable, ["-u", str(ruta)]) as c:
        assert c.llamar("saluda", {"a_quien": "z"}) == "hola z"
    assert c._proc is None


# ── el descubrimiento ──────────────────────────────────────────────────────

def test_lee_el_formato_de_claude_code_incluidos_los_proyectos(tmp_path,
                                                               monkeypatch):
    """Claude Code declara servidores GLOBALES y por PROYECTO. El MCP de
    Roblox del dueno vive justo en la rama de proyecto, asi que ignorarla
    dejaria fuera el caso que motivo todo esto."""
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({
        "mcpServers": {"global1": {"type": "stdio", "command": "npx",
                                   "args": ["-y", "algo"]}},
        "projects": {"C:/proy": {"mcpServers": {
            "Roblox_Studio": {"command": "cmd.exe", "args": ["/c", "mcp.bat"]}}}},
    }), encoding="utf-8")
    monkeypatch.setattr("cognia.mcp_externos.ORIGENES",
                        [{"cliente": "Claude Code", "ruta": str(cfg),
                          "forma": "claude_code"}])
    srv = {s.nombre: s for s in descubrir()}
    assert set(srv) == {"global1", "Roblox_Studio"}
    assert srv["Roblox_Studio"].alcance == "C:/proy"
    assert srv["Roblox_Studio"].comando == "cmd.exe"
    assert srv["global1"].alcance == "global"


def test_se_puede_pedir_solo_lo_global(tmp_path, monkeypatch):
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({
        "mcpServers": {"g": {"command": "x"}},
        "projects": {"p": {"mcpServers": {"solo_proy": {"command": "y"}}}},
    }), encoding="utf-8")
    monkeypatch.setattr("cognia.mcp_externos.ORIGENES",
                        [{"cliente": "Claude Code", "ruta": str(cfg),
                          "forma": "claude_code"}])
    assert [s.nombre for s in descubrir(incluir_proyectos=False)] == ["g"]


def test_un_servidor_remoto_se_reconoce_como_tal():
    s = _entrada_a_servidor("remoto", {"url": "https://x/mcp"}, "test")
    assert s.es_stdio is False and s.url == "https://x/mcp"
    s2 = _entrada_a_servidor("local", {"command": "npx"}, "test")
    assert s2.es_stdio is True


def test_una_entrada_ilegible_no_rompe_el_descubrimiento():
    assert _entrada_a_servidor("x", {}, "test") is None
    assert _entrada_a_servidor("x", "no soy un dict", "test") is None


def test_un_config_que_no_existe_o_esta_roto_no_lanza(tmp_path, monkeypatch):
    roto = tmp_path / "roto.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr("cognia.mcp_externos.ORIGENES", [
        {"cliente": "A", "ruta": str(tmp_path / "no_existe.json"), "forma": "plano"},
        {"cliente": "B", "ruta": str(roto), "forma": "plano"},
    ])
    assert descubrir() == []
    assert "No encontre ningun servidor" in formatear_descubiertos([])


def test_el_dedupe_respeta_el_orden_de_ORIGENES(tmp_path, monkeypatch):
    """`context7` esta en Claude Code Y en los libres. Gana el primero de la
    lista, y el listado dice de donde salio."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"mcpServers": {"dup": {"command": "primero"}}}),
                 encoding="utf-8")
    b.write_text(json.dumps({"mcpServers": {"dup": {"command": "segundo"}}}),
                 encoding="utf-8")
    monkeypatch.setattr("cognia.mcp_externos.ORIGENES", [
        {"cliente": "A", "ruta": str(a), "forma": "plano"},
        {"cliente": "B", "ruta": str(b), "forma": "plano"},
    ])
    srv = descubrir()
    assert len(srv) == 1 and srv[0].comando == "primero" and srv[0].origen == "A"


def test_todos_los_ORIGENES_tienen_la_forma_esperada():
    """Punto de extension: agregar un cliente de IA nuevo es agregar una
    entrada aqui. Este test fija el contrato de esa entrada."""
    for o in ORIGENES:
        assert set(o) == {"cliente", "ruta", "forma"}
        assert o["forma"] in ("claude_code", "plano", "vscode")
        assert os.path.isabs(o["ruta"]), o


# ── las tools del agente ───────────────────────────────────────────────────
# Se prueban en un SUBPROCESO y no con importlib.reload: el registro de las
# tools ocurre al importar cognia.agent.tools, y recargarlo deja a tools_mcp
# cacheado en sys.modules con el decorador `tool` del modulo VIEJO -- el
# registry nuevo sale vacio y el test mediria el aislamiento, no el codigo.
# Un proceso limpio por caso es exactamente el estado en que arranca el CLI.

def _en_proceso_limpio(codigo, flag):
    """Corre `codigo` con COGNIA_MCP=flag y devuelve su stdout."""
    import subprocess
    env = dict(os.environ, COGNIA_MCP=flag, PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=120)
    assert r.returncode == 0, r.stderr[-600:]
    return r.stdout.strip()


def test_opt_in_DURO_el_flag_apagado_no_registra_nada():
    """Un servidor MCP es codigo de TERCEROS. Con el flag apagado la tool no
    puede existir en el registry: run_tool ejecuta cualquier nombre que este
    en TOOLS, asi que "registrar siempre y filtrar el catalogo" no seria
    opt-in -- seria una tool activa que el modelo simplemente no ve anunciada.
    """
    out = _en_proceso_limpio(
        "from cognia.agent.tools import TOOLS, run_tool;"
        "print([n for n in TOOLS if n.startswith('mcp')]);"
        "print(run_tool('mcp', 'x | y', {}))", "0")
    assert "[]" in out
    assert "DESHABILITADA" in out and "COGNIA_MCP=1" in out


def test_con_el_flag_encendido_se_registran_DOS_y_no_estan_en_CORE():
    """Dos entradas, no 186: el A/B del repo (2026-07-25) midio que un
    catalogo de 46 herramientas baja el camino feliz de 4,25/5 a 2,5/5, y los
    cinco servidores del dueno suman 186 herramientas."""
    out = _en_proceso_limpio(
        "from cognia.agent.tools import TOOLS, CORE_TOOLS;"
        "print(sorted(n for n in TOOLS if n.startswith('mcp')));"
        "print([n for n in CORE_TOOLS if n.startswith('mcp')])", "1")
    assert "['mcp', 'mcp_herramientas']" in out
    assert out.strip().endswith("[]")        # ninguna en CORE_TOOLS


def test_la_tool_mcp_esta_marcada_peligrosa():
    """Ejecuta codigo de terceros: el gate tiene que poder tratarla como tal."""
    out = _en_proceso_limpio(
        "from cognia.agent.tools import TOOLS; print(TOOLS['mcp']['danger'])", "1")
    assert out == "True"


def test_argumentos_que_no_son_JSON_lo_dicen_y_muestran_lo_recibido():
    """El fallo tipico es mandar el JSON partido por el '|' del protocolo
    texto. Sin ver el crudo no hay forma de saberlo."""
    out = _en_proceso_limpio(
        "from cognia.agent.tools import run_tool;"
        "print(run_tool('mcp', 'srv | tool | {esto no es json', {}))", "1")
    assert "no son JSON valido" in out and "{esto no es json" in out


def test_un_servidor_desconocido_dice_cuales_hay():
    out = _en_proceso_limpio(
        "from cognia.agent.tools import run_tool;"
        "print(run_tool('mcp', 'no_existe_xyz | x | {}', {}))", "1")
    assert "no configurado" in out and "Hay:" in out
