# -*- coding: utf-8 -*-
"""COMMIT 2PC -- la compuerta corre ANTES de destruir (ESPEC 2.3, 9.3, 10.1).

Los cinco obligatorios del encargo:
  - banda permanente CORROMPIDA -> ABORTA (el que sostiene todo lo demas);
  - MODO ANCHO no destruye el contexto y se CUENTA;
  - Q<3/3 no mata la tarea;
  - un proceso matado a mitad de commit deja el libro consistente;
  - el loop ALTERNANTE se detecta (el caso que LOOP-A no ve).
"""

import json

import pytest

from cognia.agents import goal_contract as gc
from cognia.tx import bandas, commit, gates
from cognia.tx import libro as L


# --------------------------------------------------------------- utilidades

def _sembrar(lib, artefacto=None):
    """Ciclo 0: objetivo, restriccion, definicion y 2 trazadores. Devuelve el
    estado de canal con los trazadores (los mismos IDs que van al LIBRO)."""
    lib.append({"t": "objetivo", "op": "add", "id": "P-000", "banda": "P",
                "quien": "usuario", "origen": "usuario",
                "texto": "cablear el canal de estado al bucle",
                "prov": {"tipo": "dada", "cita": "cablear el canal",
                         "ref": "tarea#0"}}, ciclo=0)
    lib.append({"t": "restriccion", "op": "add", "id": "P-001", "banda": "P",
                "quien": "usuario", "origen": "usuario",
                "clave": "regla:venv", "valor": "si",
                "texto": "usar SIEMPRE venv312 y nunca el python global",
                "prov": {"tipo": "dada", "cita": "venv312",
                         "ref": "CLAUDE.md#12"}}, ciclo=0)
    estado = {"trazadores": []}
    for ident, texto in (("TRZ-4A9C31", "TRZ-4A9C31: el umbral acordado es 612"),
                         ("TRZ-B71E02", "TRZ-B71E02: no publicar sin firma")):
        lib.append({"t": "trazador", "op": "add", "id": "T-" + ident[4:],
                    "banda": "T", "quien": "harness", "origen": "derivado",
                    "texto": texto,
                    "prov": {"tipo": "derivada", "fn": "canal.sembrar_trazadores",
                             "base": ["semilla:19"]}}, ciclo=0)
        estado["trazadores"].append({"id": ident, "tipo": "valor",
                                     "texto": texto, "ts": 0})
    if artefacto:
        ruta, sha = artefacto
        lib.append({"t": "fichero", "op": "add", "id": "A-004", "banda": "A",
                    "quien": "harness", "origen": "medido",
                    "clave": "archivo:" + ruta, "valor": sha,
                    "texto": "artefacto de la tarea", "estado": "verificado",
                    "critico": True,
                    "prov": {"tipo": "ejecutada", "cmd": "escribir_archivo",
                             "cwd": ".", "exit_code": 0,
                             "salida_sha": sha}}, ciclo=0)
    return estado


def _trabajo(lib, ciclo, cmd="pytest -q", exit_code=0):
    """Un evento MEDIDO en el ciclo: sin esto G6 (ciclo mudo) suspende."""
    return lib.append({"t": "comando", "op": "add", "banda": "E",
                       "quien": "harness", "origen": "medido",
                       "clave": "cmd:" + cmd, "valor": exit_code,
                       "texto": cmd,
                       "prov": {"tipo": "ejecutada", "cmd": "ejecutar",
                                "cwd": ".", "exit_code": exit_code,
                                "salida_sha": "aa00bb",
                                "ruta_destino": ""}}, ciclo=ciclo)


def _contrato(tmp_path, n_ok=1):
    """Un contrato BARATO (ESPEC 9.5): `file_exists` sobre ficheros del
    workspace. Nada de pytest de 40 s en la ruta del gate."""
    specs = []
    for i in range(2):
        p = tmp_path / ("meta%d.txt" % i)
        if i < n_ok:
            p.write_text("ok", encoding="utf-8")
        specs.append({"kind": "file_exists", "path": p.name,
                      "description": "meta %d" % i})
    return gc.GoalContract.from_spec("cablear", specs, workspace=str(tmp_path))


def _responder_perfecto(preguntas, estado):
    """La sesion nueva contesta citando literalmente lo que se le pide."""
    def responder(_texto):
        return "\n".join([str(p["esperado"]) for p in preguntas] +
                         [t["id"] for t in estado["trazadores"]])
    return responder


def _ctx(lib, tmp_path, estado, ciclo=1, **kw):
    eventos = lib.leer()
    ctx = {
        "libro": lib,
        "ciclo": ciclo,
        "sha_p0": bandas.sha_banda_permanente(eventos),
        "estado_canal": estado,
        "contrato": _contrato(tmp_path),
        "workspace": str(tmp_path),
        "salud": commit.salud_nueva(),
        "destruido": [],
    }
    ctx["destruir"] = lambda proy: ctx["destruido"].append(proy)
    ctx["responder"] = _responder_perfecto(
        gates.preguntas_de_control(eventos), estado)
    ctx.update(kw)
    return ctx


@pytest.fixture
def lib(tmp_path):
    return L.Libro(str(tmp_path / "libro"))


# ================================================================ el camino feliz

def test_commit_verde_destruye_y_deja_hecho(lib, tmp_path):
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    res = commit.ejecutar(ctx)
    assert res["salida"] == "HECHO", res["detalle"]
    assert res["destruido"] is True and len(ctx["destruido"]) == 1
    assert res["q"]["ok"] and res["g2"]["ok"]
    assert ctx["salud"]["anchos"] == 0
    # La constancia queda en el LIBRO, no solo en el dict de vuelta.
    assert any(e["t"] == "tx" and e.get("id", "").startswith("TX-")
               for e in lib.leer())


def _sembrar_estado(lib):
    """Reconstruye el estado de canal (trazadores) leyendo el LIBRO."""
    estado = {"trazadores": []}
    for e in lib.leer():
        if e["t"] == "trazador":
            ident = e["texto"].split(":")[0].strip()
            estado["trazadores"].append({"id": ident, "tipo": "valor",
                                         "texto": e["texto"], "ts": 0})
    return estado


# ============================================ G1: la banda permanente corrompida

def test_banda_permanente_corrompida_aborta(lib, tmp_path):
    """EL TEST QUE SOSTIENE TODO.

    Si la cabecera permanente deja de ser byte-identica y el reset sigue
    adelante, la tarea pierde el contrato sin que ningun otro gate lo note:
    todos los demas miran el MUNDO, no la memoria. Aqui se borra una
    restriccion (una de las 3 mutaciones de `/tx mutar`) y se exige que el
    contexto viejo NO se destruya.
    """
    _sembrar(lib)
    _trabajo(lib, 1)
    estado = _sembrar_estado(lib)
    ctx = _ctx(lib, tmp_path, estado)
    sha_bueno = ctx["sha_p0"]

    # La mutacion: la restriccion se retracta, asi que la banda P ya no es la
    # que el dueno tecleo. `sha_p0` sigue siendo el del ciclo 0.
    lib.append({"t": "restriccion", "op": "invalidate", "id": "P-001",
                "banda": "P", "quien": "harness", "origen": "derivado",
                "texto": "restriccion borrada por la mutacion",
                "prov": {"tipo": "derivada", "fn": "test", "base": []}}, ciclo=1)

    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO", res["detalle"]
    assert res["destruido"] is False
    assert ctx["destruido"] == [], "el contexto viejo SIGUE VIVO"
    g1 = [f for f in res["fallos"] if f["gate"] == "G1"]
    assert g1 and sha_bueno in g1[0]["detalle"]
    assert ctx["salud"]["anchos"] == 1


def test_sha_p0_ausente_no_aprueba(lib, tmp_path):
    """Un gate sin referencia contra la que comparar NO aprueba."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib), sha_p0=None)
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO"
    assert any(f["gate"] == "G1" for f in res["fallos"])


# ============================================================== G3 artefactos

def test_g3_sha_de_artefacto_cambiado_aborta(lib, tmp_path):
    """C1: el fichero se edito FUERA del agente. La ventana cree una cosa y el
    disco dice otra; destruir aqui capitalizaria una victoria inexistente."""
    art = tmp_path / "canal.py"
    art.write_text("version buena\n", encoding="utf-8")
    from cognia.tx.claves import sha_de_fichero
    _sembrar(lib, artefacto=("canal.py", sha_de_fichero(str(art))))
    _trabajo(lib, 1)
    art.write_text("alguien lo cambio por detras\n", encoding="utf-8")

    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO"
    assert ctx["destruido"] == []
    assert any(f["gate"] == "G3" for f in res["fallos"])


def test_g3_verde_cuando_el_disco_coincide(lib, tmp_path):
    art = tmp_path / "canal.py"
    art.write_text("version buena\n", encoding="utf-8")
    from cognia.tx.claves import sha_de_fichero
    _sembrar(lib, artefacto=("canal.py", sha_de_fichero(str(art))))
    _trabajo(lib, 1)
    res = commit.ejecutar(_ctx(lib, tmp_path, _sembrar_estado(lib)))
    assert res["salida"] == "HECHO", res["detalle"]


# ============================================================== G4 y G5 y G6

def test_g4_contradiccion_por_clave_aborta(lib, tmp_path):
    """GROUP BY clave HAVING COUNT(DISTINCT valor) > 1. Cero LLM."""
    _sembrar(lib)
    for ident, valor in (("F-1", "aa11bb22cc33dd"), ("F-2", "99887766554433")):
        lib.append({"t": "hecho", "op": "add", "id": ident, "banda": "F",
                    "quien": "harness", "origen": "medido",
                    "clave": "archivo:cognia/estado/canal.py", "valor": valor,
                    "texto": "sha de canal.py", "estado": "verificado",
                    "prov": {"tipo": "derivada", "fn": "f", "base": []}}, ciclo=1)
    _trabajo(lib, 1)
    res = commit.ejecutar(_ctx(lib, tmp_path, _sembrar_estado(lib)))
    assert res["salida"] == "ANCHO"
    assert any(f["gate"] == "G4" for f in res["fallos"])


def test_g4_ignora_dec_y_nota(lib, tmp_path):
    """Punto ciego DECLARADO: dos opiniones del modelo no son una
    contradiccion medible. Si entrasen, G4 abortaria resets por desacuerdos
    del modelo consigo mismo."""
    _sembrar(lib)
    for ident, valor in (("D-1", "jsonl"), ("D-2", "pickle")):
        lib.append({"t": "decision", "op": "add", "id": ident, "banda": "D",
                    "quien": "ejecutor", "origen": "modelo", "conf": 0.3,
                    "clave": "dec:serializacion", "valor": valor,
                    "texto": "serializar en " + valor, "estado": "verificado",
                    "prov": {"tipo": "derivada", "fn": "decidir",
                             "base": []}}, ciclo=1)
    _trabajo(lib, 1)
    res = commit.ejecutar(_ctx(lib, tmp_path, _sembrar_estado(lib)))
    assert res["salida"] == "HECHO", res["detalle"]


def test_g5_retroceso_de_progreso_aborta(lib, tmp_path):
    """Retroceso del contrato = deriva, por definicion (ESPEC 10.2)."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    ctx["salud"]["progreso"] = 2          # el ciclo anterior tenia 2 de 2
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO"
    g5 = [f for f in res["fallos"] if f["gate"] == "G5"]
    assert g5 and "1 de 2" in g5[0]["detalle"]


def test_g5_sin_contrato_no_aprueba(lib, tmp_path):
    _sembrar(lib)
    _trabajo(lib, 1)
    res = commit.ejecutar(_ctx(lib, tmp_path, _sembrar_estado(lib), contrato=None))
    assert res["salida"] == "ANCHO"
    assert any(f["gate"] == "G5" for f in res["fallos"])


def test_g6_ciclo_mudo_aborta_y_dos_seguidos_cortan(lib, tmp_path):
    """Un ciclo de pura prosa es un punto fijo determinista que LOOP-A/B/C no
    ven. G6 es la unica defensa contra el."""
    _sembrar(lib)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib), ciclo=1)
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO"
    assert any(f["gate"] == "G6" for f in res["fallos"])

    ctx["ciclo"] = 2
    res2 = commit.ejecutar(ctx)
    assert res2["salida"] == "HARD_STOP"
    assert "mudos seguidos" in res2["detalle"]


def test_g6_no_cuenta_lo_bloqueado_como_actividad(lib, tmp_path):
    """P0-1: un comando bloqueado por el sentinel baja a origen='derivado'. Si
    contase, un ciclo entero de llamadas bloqueadas pasaria por productivo."""
    _sembrar(lib)
    lib.append({"t": "comando", "op": "add", "banda": "E", "quien": "harness",
                "origen": "derivado", "clave": "cmd:rm -rf /", "valor": None,
                "texto": "BLOQUEADO por Sentinel",
                "prov": {"tipo": "derivada", "fn": "interceptor.envelope",
                         "base": ["exit_code:None"], "sin_exit": True}}, ciclo=1)
    res = commit.ejecutar(_ctx(lib, tmp_path, _sembrar_estado(lib)))
    assert any(f["gate"] == "G6" for f in res["fallos"])


# ====================================================== MODO ANCHO y escalera

def test_modo_ancho_no_destruye_y_se_cuenta(lib, tmp_path):
    """EL SEGUNDO OBLIGATORIO. La salida del gate en rojo NO es abortar la
    tarea: es no resetear -- el brazo que midio recall 1,000."""
    _sembrar(lib)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    salidas = []
    for ciclo in (1, 2, 3):
        ctx["ciclo"] = ciclo
        ctx["salud"]["mudos_seguidos"] = 0       # aisla el conteo de G6
        _trabajo(lib, ciclo, cmd="pytest -q %d" % ciclo)
        ctx["sha_p0"] = "no-es-el-sha-de-nadie"  # G1 en rojo los 3 ciclos
        salidas.append(commit.ejecutar(ctx)["salida"])
    assert salidas == ["ANCHO", "ANCHO", "ANCHO"]
    assert ctx["destruido"] == [], "en ningun ciclo se destruyo la ventana"
    assert ctx["salud"]["anchos"] == 3
    assert ctx["salud"]["anchos_seguidos"] == 3

    # El 4o ya no puede: el brazo ancho no es caro, DEGRADA EN SILENCIO.
    ctx["ciclo"] = 4
    ctx["salud"]["mudos_seguidos"] = 0
    _trabajo(lib, 4)
    res = commit.ejecutar(ctx)
    assert res["salida"] == "HARD_STOP"
    assert "CONSECUTIVOS" in res["detalle"]
    assert ctx["destruido"] == []


def test_un_commit_verde_reinicia_los_anchos_seguidos(lib, tmp_path):
    """El contador es de anchos CONSECUTIVOS: un reset bueno lo pone a cero."""
    _sembrar(lib)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    _trabajo(lib, 1)
    bueno = ctx["sha_p0"]
    ctx["sha_p0"] = "roto"
    assert commit.ejecutar(ctx)["salida"] == "ANCHO"
    assert ctx["salud"]["anchos_seguidos"] == 1
    ctx["ciclo"] = 2
    ctx["sha_p0"] = bueno
    _trabajo(lib, 2, cmd="pytest -q dos")
    assert commit.ejecutar(ctx)["salida"] == "HECHO"
    assert ctx["salud"]["anchos_seguidos"] == 0
    assert ctx["salud"]["anchos"] == 1, "el total NO se reinicia: es salud visible"


def test_banda_permanente_que_no_cabe_es_hard_stop_sin_escalera(lib, tmp_path):
    """Antes que truncar la banda P, un agente que se planta (ESPEC 9.4)."""
    _sembrar(lib)
    for i in range(30):
        lib.append({"t": "restriccion", "op": "add", "id": "P-%03X" % (16 + i),
                    "banda": "P", "quien": "usuario", "origen": "usuario",
                    "texto": ("R%02d " % i) + "x" * 380,
                    "prov": {"tipo": "dada", "cita": "x", "ref": "y"}}, ciclo=0)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    res = commit.ejecutar(ctx)
    assert res["salida"] == "HARD_STOP"
    assert "poda humana" in res["detalle"]
    assert ctx["destruido"] == []


# ============================================================= Q1..Q3 y G2

def test_q_menor_que_3_de_3_no_mata_la_tarea(lib, tmp_path):
    """EL TERCER OBLIGATORIO. Asimetria declarada: un falso negativo de Q
    cuesta cientos de ciclos de degradacion silenciosa; un falso positivo
    cuesta UN ciclo ancho."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    ctx["responder"] = lambda _t: "si claro, ya me acuerdo de todo"
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO", res["detalle"]
    assert res["salida"] != "HARD_STOP"
    assert res["destruido"] is True, "esta rama SI destruyo: Q se mide despues"
    assert res["q"]["aciertos"] == 0 and res["q"]["total"] == 3
    assert res["reintentos"] == 1, "hubo recitacion verbatim y un reintento"
    assert ctx["salud"]["anchos"] == 1


def test_la_recitacion_verbatim_recupera_el_ciclo(lib, tmp_path):
    """c4: primero la recitacion, y solo si sigue fallando se cuenta ancho."""
    _sembrar(lib)
    _trabajo(lib, 1)
    estado = _sembrar_estado(lib)
    ctx = _ctx(lib, tmp_path, estado)
    preguntas = gates.preguntas_de_control(lib.leer())
    bueno = "\n".join([p["esperado"] for p in preguntas] +
                      [t["id"] for t in estado["trazadores"]])
    llamadas = []

    def responder(texto):
        llamadas.append(texto)
        return "no me acuerdo" if len(llamadas) == 1 else bueno

    ctx["responder"] = responder
    res = commit.ejecutar(ctx)
    assert res["salida"] == "HECHO", res["detalle"]
    assert res["reintentos"] == 1
    assert "RECITACION" in llamadas[1]
    assert ctx["salud"]["anchos"] == 0


def test_g2_se_mide_sobre_la_respuesta_no_sobre_la_proyeccion(lib, tmp_path):
    """P0-4 / ESPEC 6.5. El modelo recita las preguntas pero NO cita los
    trazadores: la proyeccion los lleva verbatim, asi que medir sobre ella
    daria 2/2 y no informaria de nada."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    preguntas = gates.preguntas_de_control(lib.leer())
    # Las respuestas de las preguntas SIN los IDs de trazador. La Q3 es
    # justamente un trazador, asi que se responde solo Q1 y Q2.
    ctx["responder"] = lambda _t: "\n".join(
        p["esperado"] for p in preguntas if not str(p["esperado"]).startswith("TRZ-"))
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO"
    assert res["g2"]["ok"] is False
    assert res["g2"]["datos"]["presentes"] == 0
    # y sobre la proyeccion habrian salido los 2 de 2: eso es la tautologia.
    from cognia.estado import canal
    d = canal.assert_integridad_proyeccion(ctx["estado_canal"], res["proyeccion"])
    assert d["integridad_ok"] is True and d["mide_lectura"] is False


def test_sin_canal_de_respuesta_no_destruye(lib, tmp_path):
    """Destruir sin poder medir Q seria el vacio silencioso."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib), responder=None)
    res = commit.ejecutar(ctx)
    assert res["salida"] == "ANCHO"
    assert ctx["destruido"] == []
    assert "no puedo medir Q" in res["detalle"]


def test_las_preguntas_no_contienen_su_respuesta(lib, tmp_path):
    """Si el enunciado llevara la respuesta, Q mediria cero."""
    _sembrar(lib)
    for p in gates.preguntas_de_control(lib.leer()):
        assert not gates.acierta(p["esperado"], p["pregunta"])


def test_la_correccion_no_admite_parafrasis(lib):
    """El fuzzy de `canal._presente` puntua "presente" una parafrasis CON EL ID
    PERDIDO (ESPEC 6.4). Aqui solo entra la cadena literal."""
    assert gates.acierta("usar SIEMPRE venv312",
                         "La restriccion dice: usar siempre VENV312.")
    assert not gates.acierta("usar SIEMPRE venv312",
                             "hay que usar el entorno virtual del repo siempre")


# ==================================================================== loops

def test_loop_alternante_se_detecta(lib, tmp_path):
    """EL QUINTO OBLIGATORIO -- el caso que el adversario marco como no
    cazable. El agente hace A, deshace en B, vuelve a A: ninguna firma se
    repite CONSECUTIVAMENTE, asi que LOOP-A se queda a 1 para siempre."""
    hist = [{"ciclo": k, "firma": ("aaa" if k % 2 else "bbb"),
             "criterios": frozenset()} for k in range(1, 5)]
    assert gates.detectar_loop(hist[:2])["loop"] is None, "LOOP-A no lo ve"
    d = gates.detectar_loop(hist)
    assert d["loop"] == "LOOP-ALT" and d["periodo"] == 2

    # Y si el progreso AVANZA, oscilar no es un bucle: es trabajo.
    con_avance = [dict(h, criterios=frozenset({"C%d" % (i // 2)}))
                  for i, h in enumerate(hist)]
    assert gates.detectar_loop(con_avance)["loop"] is None


def test_loop_a_misma_firma_dos_ciclos_seguidos(lib):
    hist = [{"ciclo": k, "firma": "zzz", "criterios": frozenset()}
            for k in (1, 2)]
    d = gates.detectar_loop(hist)
    assert d["loop"] == "LOOP-A" and d["repeticiones"] == 2


def test_la_firma_del_ciclo_ignora_el_orden_de_las_acciones(lib):
    """Repetir las mismas 8 acciones en otro orden es el MISMO ciclo."""
    a = [{"ciclo": 1, "t": "comando", "clave": "cmd:uno",
          "prov": {"cmd": "ejecutar", "ruta_destino": "x.py"}},
         {"ciclo": 1, "t": "comando", "clave": "cmd:dos",
          "prov": {"cmd": "ejecutar", "ruta_destino": "y.py"}}]
    assert gates.firma_ciclo(a, 1) == gates.firma_ciclo(list(reversed(a)), 1)


def test_tres_loops_cortan_la_tarea(lib, tmp_path):
    """LOOP-A tres veces -> FALLO-LOOP (ESPEC 9.2)."""
    _sembrar(lib)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    salidas = []
    for ciclo in (1, 2, 3, 4):
        ctx["ciclo"] = ciclo
        ctx["salud"]["mudos_seguidos"] = 0
        ctx["salud"]["anchos_seguidos"] = 0
        # Mismo trabajo exacto todos los ciclos: la firma no cambia.
        lib.append({"t": "comando", "op": "add", "banda": "E",
                    "quien": "harness", "origen": "medido",
                    "clave": "cmd:pytest -q", "valor": 1, "texto": "pytest -q",
                    "prov": {"tipo": "ejecutada", "cmd": "ejecutar", "cwd": ".",
                             "exit_code": 1, "salida_sha": "aa",
                             "ruta_destino": "x.py"}}, ciclo=ciclo)
        salidas.append(commit.ejecutar(ctx)["salida"])
    assert salidas[-1] == "HARD_STOP"
    assert ctx["salud"]["loops"] >= commit.MAX_LOOPS


# ================================================= corte a mitad de commit

def test_proceso_matado_a_mitad_de_commit_deja_el_libro_consistente(lib, tmp_path):
    """EL CUARTO OBLIGATORIO. Se simula el corte: el `tx/prepare` se escribio y
    la siguiente linea quedo a medias.

    Lo que se exige: el libro se lee entero hasta la ultima linea VALIDA, la
    cadena `prev` sigue cerrando, el commit siguiente funciona, y el descarte
    queda REGISTRADO (ESPEC 8.4: lo dice, no lo esconde).
    """
    _sembrar(lib)
    _trabajo(lib, 1)
    n_antes = len(lib.leer())

    # El proceso muere justo despues del prepare, con la escritura a medias.
    commit._append_tx(lib, 1, "prepare ciclo 1", clave="cfg:tx.prepare", valor=1)
    with open(lib.ruta, "a", encoding="utf-8", newline="") as fh:
        fh.write('{"n":99,"t":"tx","op":"add","ban')

    diag = {}
    resucitado = L.Libro(lib.dir)
    eventos = resucitado.leer(diag=diag)
    assert len(eventos) == n_antes + 1
    assert diag["truncadas"] == 1
    assert [e["n"] for e in eventos] == list(range(1, len(eventos) + 1))
    assert eventos[-1]["prev"] == eventos[-2]["sha"]

    # Y el ciclo siguiente commitea sin arrastrar la basura.
    ctx = _ctx(resucitado, tmp_path, _sembrar_estado(resucitado), ciclo=2)
    _trabajo(resucitado, 2, cmd="pytest -q dos")
    res = commit.ejecutar(ctx)
    assert res["salida"] == "HECHO", res["detalle"]
    finales = resucitado.leer()
    assert any(e["t"] == "contradiccion" and e.get("clave") == "cfg:libro.cola_parcial"
               for e in finales), "el descarte quedo registrado"
    assert resucitado.fsck()["ok"] is True


# ============================================================ /tx probar y REPL

def test_preparar_solo_no_destruye_nada(lib, tmp_path):
    """`/tx probar`: corre los gates AHORA contra el contexto vivo, sin resetear."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib))
    prep = commit.preparar(ctx)
    assert prep["abre"] is True
    assert ctx["destruido"] == []
    assert {v["gate"] for v in prep["gates"]} == {"G1", "G3", "G4", "G5", "G6"}, \
        "G2 NO corre en PREPARE: se mide sobre la respuesta, tras destruir"


def test_el_fuzzy_se_calcula_y_no_vota(lib, tmp_path):
    """ESPEC 6.4: si el fuzzy pasa y un exacto falla, ABORTA."""
    _sembrar(lib)
    _trabajo(lib, 1)
    ctx = _ctx(lib, tmp_path, _sembrar_estado(lib), sha_p0="roto")
    res = commit.ejecutar(ctx)
    assert res["fuzzy"] is not None, "se calcula y se muestra"
    assert res["salida"] == "ANCHO", "y no vota"


def test_linea_repl_dice_lo_que_paso(lib, tmp_path):
    _sembrar(lib)
    _trabajo(lib, 1)
    res = commit.ejecutar(_ctx(lib, tmp_path, _sembrar_estado(lib)))
    linea = commit.linea_repl(res, 1)
    assert linea.startswith("[TX] c1 HECHO")
    assert "Q 3/3" in linea and "trz 2/2" in linea


# =====================================================================
# REGRESION 2026-08-19 -- los gates que median CERO y no lo decian
# =====================================================================

def test_el_interceptor_escribe_la_banda_A_y_G3_deja_de_medir_cero(tmp_path):
    """G3 filtraba `banda == 'A'` y el UNICO sitio del repo que escribia banda
    'A' era `driver._mut_sha_falseado`, o sea el propio drill: `/tx mutar` se
    fabricaba su testigo para salir 3/3. `claves.canonica()` -- la funcion que
    produce 'archivo:<ruta>' con el sha del disco -- NO LA LLAMABA NADIE, porque
    `interceptor.envelope` cableaba a mano `clave='cmd:'+name`.

    Medido antes del arreglo: `g3_artefactos` sobre los eventos que produce de
    verdad el interceptor daba {'ok': True, 'detalle': 'artefactos 0/0'}. Una
    tarea de 500 ciclos que escribe 40 ficheros salia verde 500 veces.
    """
    from cognia.harness import interceptor
    ruta = tmp_path / "salida.txt"
    ruta.write_text("hola\n", encoding="utf-8")
    ev = interceptor.envelope("escribir_archivo", "%s | hola" % ruta,
                              {"workspace": str(tmp_path)}, "escrito", True)
    assert ev["banda"] == "A"
    assert ev["clave"].startswith("archivo:")
    assert ev["estado"] == "verificado"
    assert ev["op"] == "amend", "id estable por ruta: una fila viva por fichero"

    fila = dict(ev, n=1, ciclo=1)
    v = gates.g3_artefactos([fila], workspace=str(tmp_path))
    assert v["ok"] is True and v["datos"]["total"] == 1

    # Y ahora SI suspende cuando alguien toca el fichero por fuera (C1).
    ruta.write_text("otra cosa\n", encoding="utf-8")
    v2 = gates.g3_artefactos([fila], workspace=str(tmp_path))
    assert v2["ok"] is False and "sha cambio" in v2["detalle"]


def test_dos_escrituras_del_mismo_fichero_no_dejan_G3_en_rojo(tmp_path):
    """Con un id nuevo por escritura, el fold dejaria vivas TODAS las versiones
    y G3 compararia el disco contra el sha VIEJO: rojo para siempre a la
    segunda edicion. El id se deriva de la RUTA y el op es `amend`."""
    from cognia.harness import interceptor
    ruta = tmp_path / "a.txt"
    filas = []
    for i, contenido in enumerate(("uno\n", "dos\n"), 1):
        ruta.write_text(contenido, encoding="utf-8")
        ev = interceptor.envelope("escribir_archivo", "%s | x" % ruta,
                                  {"workspace": str(tmp_path)}, "ok", True)
        filas.append(dict(ev, n=i, ciclo=1))
    assert filas[0]["id"] == filas[1]["id"]
    v = gates.g3_artefactos(filas, workspace=str(tmp_path))
    assert v["ok"] is True and v["datos"]["total"] == 1


def test_g3_y_g4_vacios_lo_DICEN(tmp_path):
    """Un gate que aprueba porque no hay nada que mirar no puede verse igual
    que uno que aprueba habiendo mirado. `vacia` es lo que el CLI pinta en
    ambar."""
    assert gates.g3_artefactos([])["datos"]["vacia"] is True
    v = gates.g4_contradicciones([])
    assert v["ok"] is True and v["datos"]["vacia"] is True
    assert "candidatas" in v["detalle"]


def test_preparar_dice_que_el_LIBRO_esta_CORRUPTO(tmp_path):
    """`Libro.leer(diag=...)` se diseno para que 'enterarse sea posible
    SIEMPRE', y los dos consumidores de la ruta caliente lo llamaban sin diag.
    Un libro corrompido en medio devolvia su prefijo en silencio y el unico
    gate que reaccionaba era G6 diciendo '0 eventos medidos' -- la causa
    equivocada."""
    lib = L.Libro(str(tmp_path / "t"))
    _sembrar(lib)
    _trabajo(lib, 1)
    with open(lib.ruta, "ab") as fh:
        fh.write(b'{"t":"hecho"')                    # cola cortada
    prep = commit.preparar({"libro": lib, "ciclo": 1, "sha_p0": "x",
                            "contrato": None})
    p2 = [v for v in prep["gates"] if v["gate"] == "p2"]
    assert p2 and p2[0]["ok"] is False
    assert "LIBRO CORRUPTO" in p2[0]["detalle"]
    assert prep["diag"]["truncadas"] == 1
    assert "LIBRO CORRUPTO" in commit._corrupto({"diag": prep["diag"]})


def test_g5_no_inventa_un_retroceso_al_saltar_un_criterio_caro(tmp_path):
    """EL CASO QUE CERRABA EL RESET PARA SIEMPRE. `check(solo_baratos=True)`
    sacaba el criterio caro del recuento, asi que `satisfied_count` BAJABA solo
    por haberlo saltado; G5 comparaba ese numero crudo contra el del ciclo
    anterior y reportaba 'progreso 1 -> 0' -- un RETROCESO que no ocurrio.
    `flaky` estaba vacio (el saltado tiene timeout=False), asi que no entraba
    la rama que lo excusa: `prep['abre']` quedaba en False, el commit no se
    ejecutaba y `salud['progreso']` -- que solo se actualiza en las salidas
    HECHO/ANCHO -- se quedaba clavado en el valor alto. El ciclo siguiente
    repetia el mismo FALLO.
    """
    import sys
    py = sys.executable
    contrato = gc.GoalContract.from_spec("g", [
        {"kind": "command_succeeds", "command": '%s -c "raise SystemExit(1)"' % py,
         "description": "barato que FALLA"},
        {"kind": "command_succeeds",
         "command": '%s -c "import time; time.sleep(6)"' % py,
         "description": "caro que PASA"}])
    c1 = contrato.check(solo_baratos=True)
    assert (c1.satisfied_count, c1.total) == (1, 2)
    v = gates.g5_monotonia(contrato, progreso_previo=c1.satisfied_count)
    assert v["ok"] is True, v["detalle"]
    assert v["datos"]["progreso"] == 1 and v["datos"]["total"] == 2
    assert v["datos"]["heredados"] == 1
    assert "heredado" in v["detalle"]
