"""
tests/test_flujos_grabador.py
=============================
Tests del grabador de flujos (cognia/flujos/grabador.py).

Sin modelo y sin red: el grabador no llama al LLM ni a run_tool -- recibe los
hechos ya ocurridos. La unica dependencia externa es el bus de eventos, y aca
se usa el BUS REAL emitiendo eventos de verdad (nada de mocks: un doble del bus
solo probaria que el doble funciona).
"""
from __future__ import annotations

import json

import pytest

from cognia.flujos import grabador as G


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    """Cada test con su propio directorio, y sin estado de proceso filtrado.

    El estado global (_abiertas, _suscrito) es del MODULO, y pytest importa el
    modulo una sola vez para toda la suite: sin este saneo, un test que deja
    una grabacion abierta le mete pasos a los siguientes.
    """
    monkeypatch.setenv("COGNIA_FLUJOS_DIR", str(tmp_path / "flujos"))
    G.desuscribir()
    with G._lock:
        G._abiertas.clear()
    yield
    G.desuscribir()
    with G._lock:
        G._abiertas.clear()


def _lineas(ruta) -> list:
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------------------------------------------------------------------
# Grabacion completa
# ---------------------------------------------------------------------------

def test_grabacion_completa_de_punta_a_punta(tmp_path):
    gid = G.iniciar(titulo="arreglar el parser", tarea="arregla parser.py",
                    workspace=str(tmp_path), capturar_bus=False)
    assert gid and G.grabando() and G.abiertas() == [gid]

    p1 = G.registrar_paso(gid, "leer_archivo", "parser.py offset=1 limit=50",
                          ok=True, resumen_resultado="RESULTADO leer_archivo parser.py: ...",
                          duracion_s=0.12, paso_agente=1)
    p2 = G.registrar_paso(gid, "escribir_archivo", "parser.py | def f():\n    pass",
                          ok=True, resumen_resultado="RESULTADO escribir_archivo parser.py: OK",
                          duracion_s=0.30, paso_agente=2)
    p3 = G.registrar_paso(gid, "ejecutar", "python parser.py | timeout=60",
                          ok=False, resumen_resultado="RESULTADO ejecutar (exit 1): Traceback",
                          duracion_s=1.5, paso_agente=3)

    assert [p["n"] for p in (p1, p2, p3)] == [1, 2, 3]
    assert p1["ficheros_tocados"] == ["parser.py"]
    assert p3["comando"] == "python parser.py"
    assert p3["exit_code"] == 1
    assert p1["exit_code"] is None          # leer_archivo no declara exit code
    assert p2["via_bus"] is False

    ruta = G.cerrar(gid, resultado="parser arreglado", ok=True)
    assert ruta and not G.grabando()

    # El fichero: cabecera + 3 pasos + cierre, en orden y append-only.
    filas = _lineas(ruta)
    assert [f["tipo"] for f in filas] == ["cabecera", "paso", "paso", "paso",
                                          "cierre"]

    g = G.cargar(gid)
    assert g is not None
    assert g.titulo == "arreglar el parser"
    assert g.tarea == "arregla parser.py"
    assert g.workspace == str(tmp_path)
    assert g.cerrada is True and g.ok is True
    assert g.resultado == "parser arreglado"
    assert len(g.pasos) == 3 and g.lineas_malas == 0
    assert g.ts_fin >= g.ts_inicio > 0 and g.duracion_s() >= 0.0

    # Un paso FALLIDO se graba como fallido: la grabacion es un registro de
    # hechos, no un procedimiento verificado.
    assert g.pasos[2]["ok"] is False

    # listar / borrar
    fila = [f for f in G.listar() if f["id"] == gid]
    assert len(fila) == 1 and fila[0]["pasos"] == 3 and fila[0]["cerrada"]
    assert G.borrar(gid) is True
    assert G.cargar(gid) is None
    assert G.borrar(gid) is False


def test_registrar_en_id_desconocido_devuelve_none_y_no_lanza():
    # Instrumentacion: devuelve valores, no lanza en el camino caliente.
    assert G.registrar_paso("no-existe", "leer_archivo", "x.py") is None
    assert G.cerrar("no-existe") == ""
    assert G.cargar("no-existe") is None
    assert G.listar() == []


def test_anotar_corrige_la_cabecera_sin_reescribir(tmp_path):
    gid = G.iniciar(titulo="", tarea="", workspace="", capturar_bus=False)
    assert G.anotar(gid, "tarea", "la tarea de verdad") is True
    assert G.anotar(gid, "titulo", "titulo puesto despues") is True
    assert G.anotar(gid, "campo_inventado", "x") is False
    G.cerrar(gid, "listo", ok=True)

    filas = _lineas(G.ruta_de(gid))
    # La cabecera original SIGUE ahi (append-only: nada se reescribio).
    assert filas[0]["tipo"] == "cabecera" and filas[0]["tarea"] == ""
    g = G.cargar(gid)
    assert g.tarea == "la tarea de verdad"
    assert g.titulo == "titulo puesto despues"


def test_id_no_escapa_del_directorio():
    # Un id que llega de afuera nunca se concatena crudo a una ruta.
    ruta = G.ruta_de("../../fuera")
    assert ruta.parent == G.dir_grabaciones()
    # Los separadores desaparecen: el id queda como un NOMBRE, no como una
    # ruta. Los puntos sobreviven (son legales en un nombre) pero ya no
    # pueden subir de directorio.
    assert "/" not in ruta.name and "\\" not in ruta.name
    assert ruta.name == ".._.._fuera.jsonl"
    assert G.ruta_de("").name == "sin_id.jsonl"


# ---------------------------------------------------------------------------
# Supervivencia a un fichero a medias (el caso NORMAL de un crash)
# ---------------------------------------------------------------------------

def test_cargar_sobrevive_a_lineas_corruptas_y_a_una_grabacion_a_medias():
    gid = G.iniciar(titulo="tarea que revienta", tarea="algo",
                    capturar_bus=False)
    G.registrar_paso(gid, "leer_archivo", "a.py", ok=True,
                     resumen_resultado="RESULTADO leer_archivo a.py: ...")
    G.registrar_paso(gid, "tests", "tests/test_a.py", ok=True,
                     resumen_resultado="RESULTADO ejecutar: 3 passed")
    ruta = G.ruta_de(gid)

    # Simula el crash a mitad de escritura: media linea JSON pegada al final,
    # que es exactamente lo que deja un proceso muerto entre write y flush.
    with open(ruta, "a", encoding="utf-8") as f:
        f.write('{"tipo": "paso", "n": 3, "tool": "escribir_arch')

    g = G.cargar(gid)
    assert g is not None
    assert len(g.pasos) == 2            # se lee hasta donde llega
    assert g.lineas_malas == 1
    assert g.cerrada is False           # murio sin cierre, y se nota
    assert g.ok is False
    assert g.pasos[1]["tool"] == "tests"

    # Y listar() no se cae por una grabacion rota.
    fila = [f for f in G.listar() if f["id"] == gid]
    assert fila and fila[0]["cerrada"] is False and fila[0]["lineas_malas"] == 1


def test_cargar_tolera_basura_intercalada(tmp_path):
    gid = G.iniciar(titulo="t", tarea="x", capturar_bus=False)
    ruta = G.ruta_de(gid)
    with open(ruta, "a", encoding="utf-8") as f:
        f.write("esto no es json\n")
        f.write("[1, 2, 3]\n")           # json valido pero no es un dict
        f.write('{"tipo": "desconocido"}\n')
    G.registrar_paso(gid, "leer_archivo", "b.py")
    G.cerrar(gid, "ok", ok=True)

    g = G.cargar(gid)
    assert len(g.pasos) == 1
    assert g.lineas_malas == 3
    assert g.cerrada is True


# ---------------------------------------------------------------------------
# derivar_ficheros: los protocolos de args reales de cognia/agent/tools.py
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool,args,esperado", [
    # leer_archivo <path> [offset=N] [limit=M]
    ("leer_archivo", "cognia/agent/loop.py", ["cognia/agent/loop.py"]),
    ("leer_archivo", "loop.py offset=200 limit=50", ["loop.py"]),
    ("leer_archivo", "loop.py limit=50 offset=200", ["loop.py"]),
    ("leer_archivo", '"con espacio.py"', ["con espacio.py"]),
    # escribir_archivo <path> | <contenido>
    ("escribir_archivo", "web/index.html | <html>x=1|2</html>",
     ["web/index.html"]),
    # editar_archivo <path> | <bloques SEARCH/REPLACE>
    ("editar_archivo",
     "motor.py | <<<<<<< SEARCH\ndef f():\n=======\ndef g():\n>>>>>>> REPLACE",
     ["motor.py"]),
    # apendar_archivo <path> | <texto>
    ("apendar_archivo", "bitacora.txt | tercera linea", ["bitacora.txt"]),
    # borrar_archivo <path>
    ("borrar_archivo", "tmp/basura.txt", ["tmp/basura.txt"]),
    ("borrar_archivo", "'tmp/basura.txt'", ["tmp/basura.txt"]),
    # tests <ruta>
    ("tests", "tests/test_foo.py", ["tests/test_foo.py"]),
])
def test_derivar_ficheros_por_protocolo(tool, args, esperado):
    assert G.derivar_ficheros(args, tool) == esperado


@pytest.mark.parametrize("tool,args", [
    # ejecutar: un comando de shell puede tocar CUALQUIER cosa. Lista vacia =
    # "no lo se". Adivinar aca seria fabricar un dato para decidir.
    ("ejecutar", "python scripts/build.py > salida.txt"),
    ("ejecutar", "rm -rf build | timeout=60"),
    ("ejecutar_fondo", "python -m http.server 8000"),
    # Sin '|' la llamada ni siquiera es valida para la tool: no se inventa ruta.
    ("escribir_archivo", "index.html sin pipe"),
    ("editar_archivo", "motor.py"),
    # Tool que no conocemos.
    ("git_commit", "arreglo el parser"),
    ("tool_del_futuro", "lo que sea"),
    # Args vacios.
    ("leer_archivo", "   "),
    ("", "x.py"),
])
def test_derivar_ficheros_es_honesta_cuando_no_sabe(tool, args):
    assert G.derivar_ficheros(args, tool) == []


def test_derivar_ficheros_contra_el_armador_real_de_args():
    """Ancla el parser al productor REAL de esos strings.

    `args_legacy` (cognia/agent/tool_schemas.py) es quien convierte el tool
    call del modelo en el string que recibe run_tool -- y es exactamente lo que
    el bucle emite como `args`. Si alguien cambia el formato de un armador, el
    grabador empieza a derivar ficheros equivocados EN SILENCIO; este test lo
    convierte en un fallo ruidoso.
    """
    from cognia.agent.tool_schemas import args_legacy

    casos = [
        ("leer_archivo", {"path": "cognia/cli.py", "offset": 10, "limit": 50},
         ["cognia/cli.py"]),
        ("escribir_archivo", {"path": "web/index.html",
                              "contenido": "<html>|x</html>"},
         ["web/index.html"]),
        ("editar_archivo", {"path": "motor.py",
                            "bloques": "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE"},
         ["motor.py"]),
        ("apendar_archivo", {"path": "bitacora.txt", "texto": "linea"},
         ["bitacora.txt"]),
        ("borrar_archivo", {"path": "tmp/x.txt"}, ["tmp/x.txt"]),
        ("ejecutar", {"comando": "pytest -q", "timeout": 60}, []),
        ("tests", {"ruta": "tests/test_foo.py"}, ["tests/test_foo.py"]),
    ]
    for tool, argumentos, esperado in casos:
        s = args_legacy(tool, argumentos)
        assert G.derivar_ficheros(s, tool) == esperado, (tool, s)
    assert G.derivar_comando(args_legacy("ejecutar", {"comando": "pytest -q"}),
                             "ejecutar") == "pytest -q"


def test_derivar_comando_solo_para_shell():
    assert G.derivar_comando("pytest -q | timeout=180", "ejecutar") == "pytest -q"
    assert G.derivar_comando("pytest -q | cwd=C:/repo | timeout=180",
                             "ejecutar") == "pytest -q"
    assert G.derivar_comando("python -m http.server", "ejecutar_fondo") == \
        "python -m http.server"
    # Un '=' que NO es una clave del protocolo no se toca.
    assert G.derivar_comando("echo hola=1", "ejecutar") == "echo hola=1"
    assert G.derivar_comando("a.py | contenido", "escribir_archivo") == ""
    assert G.derivar_comando("tests/test_a.py", "tests") == ""


def test_derivar_exit_code():
    assert G.derivar_exit_code("RESULTADO ejecutar: hola", "ejecutar") == 0
    assert G.derivar_exit_code("RESULTADO ejecutar (exit 1): Traceback",
                               "ejecutar") == 1
    assert G.derivar_exit_code("RESULTADO ejecutar (exit -9): matado",
                               "ejecutar") == -9
    # tests tambien pasa por _shell, asi que declara el exit igual.
    assert G.derivar_exit_code("RESULTADO ejecutar (exit 2): 1 failed",
                               "tests") == 2
    # None NO es 0: un timeout o un bloqueo del sentinel no tienen exit code.
    assert G.derivar_exit_code("RESULTADO ejecutar ERROR: timeout tras 30s",
                               "ejecutar") is None
    assert G.derivar_exit_code("RESULTADO leer_archivo a.py: ...",
                               "leer_archivo") is None
    assert G.derivar_exit_code("", "ejecutar") is None


# ---------------------------------------------------------------------------
# Bus REAL: se emiten eventos de verdad por cognia.ux.events
# ---------------------------------------------------------------------------

def test_suscripcion_al_bus_real_graba_los_pasos():
    from cognia.ux import events as ev

    assert G.suscribir() is True
    assert G.suscribir() is True          # idempotente
    gid = G.iniciar(titulo="desde el bus", tarea="", workspace="")

    # TareaInicio rellena la tarea que la grabacion no tenia.
    ev.emitir(ev.TareaInicio(tarea="arregla el parser", modo="agente",
                             modelo="qwythos-9b"))
    ev.emitir(ev.ToolInicio(tool="leer_archivo", args="parser.py", paso=1))
    ev.emitir(ev.ToolFin(tool="leer_archivo", args="parser.py", ok=True,
                         resumen="RESULTADO leer_archivo parser.py: 42 lineas",
                         duracion_s=0.05, paso=1))
    ev.emitir(ev.ToolFin(tool="ejecutar", args="pytest -q | timeout=60",
                         ok=False,
                         resumen="RESULTADO ejecutar (exit 1): 1 failed",
                         duracion_s=2.0, paso=2))
    # Eventos que no son del grabador: no ensucian la trayectoria.
    ev.emitir(ev.TokenTexto(texto="bla"))
    ev.emitir(ev.Aviso(texto="algo", origen="test"))

    G.cerrar(gid, resultado="listo", ok=True)
    g = G.cargar(gid)

    assert g.tarea == "arregla el parser"      # anotada por TareaInicio
    assert [p["tool"] for p in g.pasos] == ["leer_archivo", "ejecutar"]
    assert [p["n"] for p in g.pasos] == [1, 2]
    assert [p["paso_agente"] for p in g.pasos] == [1, 2]
    assert g.pasos[0]["ficheros_tocados"] == ["parser.py"]
    assert g.pasos[1]["ok"] is False and g.pasos[1]["exit_code"] == 1
    assert g.pasos[1]["comando"] == "pytest -q"
    # Marcado como venido del bus: sus args pueden estar recortados a 120
    # chars por loop.py y el consumidor NO puede reproducirlos a ciegas.
    assert all(p["via_bus"] for p in g.pasos)


def test_desuscribir_deja_de_grabar():
    from cognia.ux import events as ev

    G.suscribir()
    gid = G.iniciar(titulo="corta", tarea="t")
    ev.emitir(ev.ToolFin(tool="leer_archivo", args="a.py", ok=True,
                         resumen="ok", duracion_s=0.1, paso=1))
    assert G.desuscribir() is True
    assert G.desuscribir() is True        # idempotente
    ev.emitir(ev.ToolFin(tool="leer_archivo", args="b.py", ok=True,
                         resumen="ok", duracion_s=0.1, paso=2))
    G.cerrar(gid, "fin", ok=True)

    g = G.cargar(gid)
    assert [p["ficheros_tocados"] for p in g.pasos] == [["a.py"]]


def test_sin_grabacion_abierta_el_bus_no_escribe_nada():
    from cognia.ux import events as ev

    G.suscribir()
    ev.emitir(ev.ToolFin(tool="leer_archivo", args="a.py", ok=True,
                         resumen="ok", duracion_s=0.1, paso=1))
    assert G.listar() == []


def test_capturar_bus_false_no_duplica_los_pasos():
    """La decision 3 del modulo: UN solo productor de pasos por grabacion.

    Con capturar_bus=False el bus no graba, asi que el cableado puede pasar el
    args COMPLETO desde el bucle sin que cada paso salga dos veces.
    """
    from cognia.ux import events as ev

    G.suscribir()
    gid = G.iniciar(titulo="manual", tarea="t", capturar_bus=False)
    contenido = "x" * 300          # mas largo que el recorte de 120 del bus
    ev.emitir(ev.ToolFin(tool="escribir_archivo",
                         args=f"a.py | {contenido}"[:120], ok=True,
                         resumen="RESULTADO escribir_archivo a.py: OK",
                         duracion_s=0.1, paso=1))
    G.registrar_paso(gid, "escribir_archivo", f"a.py | {contenido}", ok=True,
                     resumen_resultado="RESULTADO escribir_archivo a.py: OK",
                     duracion_s=0.1, paso_agente=1)
    G.cerrar(gid, "fin", ok=True)

    g = G.cargar(gid)
    assert len(g.pasos) == 1
    assert g.pasos[0]["via_bus"] is False
    assert len(g.pasos[0]["args"]) == len(f"a.py | {contenido}")


def test_dos_grabaciones_abiertas_reciben_el_mismo_evento():
    from cognia.ux import events as ev

    G.suscribir()
    a = G.iniciar(titulo="A", tarea="t")
    b = G.iniciar(titulo="B", tarea="t")
    ev.emitir(ev.ToolFin(tool="listar", args=".", ok=True, resumen="ok",
                         duracion_s=0.0, paso=1))
    G.cerrar(a, "fin", ok=True)
    G.cerrar(b, "fin", ok=True)
    assert len(G.cargar(a).pasos) == 1
    assert len(G.cargar(b).pasos) == 1
