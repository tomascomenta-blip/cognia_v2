# -*- coding: utf-8 -*-
"""PROYECTOR -- `proyectar` es una funcion PURA del LIBRO (ESPEC 5.1, I2).

Los dos que la ESPEC 14.2 exige nominalmente:
  - proyectar es puro: 100 llamadas, mismo sha;
  - una decision cae SOLA cuando su base se invalida.
"""

from cognia.tx import bandas


def _ev(n, **kw):
    base = {"n": n, "ciclo": 0, "op": "add", "quien": "harness",
            "origen": "derivado", "conf": 1.0, "refs": [], "texto": "",
            "prov": {"tipo": "derivada", "fn": "f", "base": []}}
    base.update(kw)
    return base


def _libro_minimo():
    return [
        _ev(1, t="objetivo", id="P-000", banda="P", origen="usuario",
            quien="usuario", texto="cablear el canal de estado",
            prov={"tipo": "dada", "cita": "cablear", "ref": "tarea#0"}),
        _ev(2, t="restriccion", id="P-001", banda="P", origen="usuario",
            quien="usuario", clave="regla:venv", valor="si",
            texto="usar SIEMPRE venv312",
            prov={"tipo": "dada", "cita": "venv312", "ref": "CLAUDE.md#12"}),
        _ev(3, t="trazador", id="T-4A9C31", banda="T",
            texto="TRZ-4A9C31: el umbral acordado es 612"),
        _ev(4, t="fichero", id="A-004", banda="A", origen="medido",
            clave="archivo:cognia/estado/canal.py", valor="e77a01b3c4d980",
            texto="canal.py editado", estado="verificado", critico=True,
            prov={"tipo": "ejecutada", "cmd": "editar_archivo", "cwd": ".",
                  "exit_code": 0, "salida_sha": "3b91ff"}),
    ]


def test_proyectar_es_puro_100_llamadas(monkeypatch):
    """EL TEST NOMINAL de la definicion-de-hecho del MVP (14.2 d)."""
    eventos = _libro_minimo()
    shas = {bandas.sha14(bandas.proyectar(eventos)) for _ in range(100)}
    assert len(shas) == 1


def test_proyectar_no_depende_del_orden_de_llegada_del_dict():
    """Mismo libro, misma salida byte a byte: el render ordena por `n`, no por
    el orden de iteracion del dict del fold."""
    eventos = _libro_minimo()
    a = bandas.proyectar(eventos)
    b = bandas.proyectar(list(reversed(eventos)))
    assert a == b


def test_la_banda_x_no_se_proyecta_nunca():
    """X es lo que MUERE en el reset: prosa, razonamiento, trazas crudas."""
    eventos = _libro_minimo() + [
        _ev(5, t="afirmacion", id="X-005", banda="X", origen="modelo", conf=0.3,
            texto="creo que render ya respeta el orden",
            prov={"tipo": "dicha"})]
    proy = bandas.proyectar(eventos)
    assert "creo que render" not in proy
    assert "X-005" not in proy


def test_una_decision_cae_cuando_su_base_se_invalida():
    """EL TEST NOMINAL. Sin esta poda, una conclusion sobrevive al hecho que la
    sostenia: es el agujero por el que entra la alucinacion persistente."""
    eventos = _libro_minimo() + [
        _ev(5, t="hecho", id="F-119", banda="F", origen="citado", conf=0.9,
            texto="conservacion() devuelve dos recalls", estado="verificado",
            prov={"tipo": "leida", "ruta": "canal.py", "cita": "x",
                  "sha_fuente": "e77a01b3c4d980"}),
        _ev(6, t="decision", id="D-011", banda="D", origen="modelo", conf=0.3,
            clave="dec:jsonl_no_pickle", valor="jsonl",
            texto="serializar en jsonl y no en pickle",
            prov={"tipo": "derivada", "fn": "decidir", "base": ["F-119"]}),
    ]
    estado = bandas.fold(eventos)
    assert "D-011" not in estado["invalidados"]

    muertos = eventos + [_ev(7, t="hecho", id="F-119", banda="F", op="invalidate",
                             texto="el hecho se retracta")]
    estado2 = bandas.fold(muertos)
    assert "F-119" in estado2["invalidados"]
    assert "D-011" in estado2["invalidados"], "la decision cae SOLA con su base"
    # No se borra: se marca en su sitio (regla generacional, ESPEC 5.2).
    proy = bandas.proyectar(muertos)
    assert "+[D-011]" in proy


def test_el_amend_no_manda_la_fila_al_final():
    """La POSICION la fija el primer `add`. Mandarla al final reescribiria el
    prefijo y pagaria la rehidratacion entera (~24x)."""
    eventos = _libro_minimo() + [
        _ev(5, t="restriccion", id="P-002", banda="P", origen="usuario",
            quien="usuario", texto="segunda restriccion",
            prov={"tipo": "dada", "cita": "x", "ref": "y"}),
        _ev(6, t="restriccion", id="P-001", banda="P", op="amend",
            origen="usuario", quien="usuario", clave="regla:venv", valor="si",
            texto="usar SIEMPRE venv312 (matizado)",
            prov={"tipo": "dada", "cita": "venv312", "ref": "CLAUDE.md#12"}),
    ]
    proy = bandas.render_banda_permanente(eventos)
    lineas = [l for l in proy.splitlines() if l.strip().startswith(("[", "+["))]
    ids = [l.split("]")[0].lstrip(" +[") for l in lineas]
    assert ids == ["P-000", "P-001", "P-002"]


def test_la_banda_p_no_pasa_por_topes():
    """Si no cabe: HARD_STOP, nunca recorte. La seleccion de restricciones
    midio recall 0,526 y la cascada 0,083, siempre en silencio."""
    largas = _libro_minimo() + [
        _ev(10 + i, t="restriccion", id="P-%03d" % (10 + i), banda="P",
            origen="usuario", quien="usuario", texto="R%02d " % i + "x" * 380,
            prov={"tipo": "dada", "cita": "x", "ref": "y"})
        for i in range(30)]
    informe = {}
    proy = bandas.proyectar(largas, topes={"P": 10}, informe=informe)
    for i in range(30):
        assert "P-%03d" % (10 + i) in proy, "ninguna restriccion se recorta"
    assert informe["p_desborda"] is True
    assert informe["bandas"]["P"]["fuera"] == 0


def test_las_contradicciones_vivas_van_sin_tope():
    """Bloquean el cierre de la tarea: recortarlas seria esconderlas."""
    eventos = _libro_minimo() + [
        _ev(20 + i, t="contradiccion", id="C-%03d" % i, banda="E",
            origen="medido", clave="archivo:x%d.py" % i, valor="aa",
            texto="sha registrado != sha en disco " + "y" * 200)
        for i in range(12)]
    informe = {}
    proy = bandas.proyectar(eventos, informe=informe)
    for i in range(12):
        assert "C-%03d" % i in proy


def test_el_tope_que_recorta_lo_dice():
    """Un recorte silencioso es un vacio silencioso. La linea de colapso es la
    puerta a `libro_grep`."""
    eventos = _libro_minimo() + [
        _ev(30 + i, t="hecho", id="F-%03d" % i, banda="F", origen="medido",
            texto="hecho %d " % i + "z" * 200, estado="verificado")
        for i in range(30)]
    informe = {}
    proy = bandas.proyectar(eventos, informe=informe)
    assert informe["bandas"]["F"]["fuera"] > 0
    assert "libro_grep" in proy


def test_sha_banda_permanente_ignora_el_resto_del_libro():
    """G1 no puede abortar porque desbordo la banda F: si `sha_P0` dependiera
    de la proyeccion entera, abortaria por el motivo equivocado."""
    a = bandas.sha_banda_permanente(_libro_minimo())
    ruidoso = _libro_minimo() + [
        _ev(40 + i, t="hecho", id="F-%03d" % i, banda="F", origen="medido",
            texto="ruido %d" % i) for i in range(50)]
    assert bandas.sha_banda_permanente(ruidoso) == a


def test_robar_topes_nunca_apaga_una_banda():
    """Una banda a 0 no es "mas barata": es una banda apagada, y apagar N apaga
    el anti-loop."""
    nuevos = bandas.robar_topes({}, "F", cuanto=10000)
    assert nuevos["N"] >= 60 and nuevos["A"] >= 60
    assert nuevos["F"] > bandas.TOPES["F"]
    assert bandas.robar_topes({}, "P")["N"] == bandas.TOPES["N"], "P no roba"


def test_la_poda_entiende_la_base_QUE_ESCRIBE_tools_decidir():
    """REGRESION 2026-08-19. `tools._decidir` -- el UNICO productor real de
    decisiones -- escribe `prov.base = ['n:813', 'n:815']`, no ids. El fold
    comparaba esa cadena contra un conjunto de IDS ('F-0100'), asi que la poda
    por dependencia no disparo NUNCA en produccion: una decision sobrevivia
    intacta y sin marca al hecho medido que la sostenia, y se seguia
    proyectando en la banda D despues de cada reset.

    El test de arriba pasaba porque construye la base a mano como ['F-119'],
    un formato que ningun productor emite: pasaba por el motivo equivocado.
    """
    eventos = _libro_minimo() + [
        _ev(5, t="hecho", id="F-0100", banda="F", origen="medido", conf=1.0,
            texto="el comando dio exit 0", estado="verificado",
            prov={"tipo": "ejecutada", "cmd": "pytest", "exit_code": 0}),
        _ev(6, t="decision", id="D-0002", banda="D", origen="derivado",
            texto="seguimos por aqui",
            prov={"tipo": "derivada", "fn": "tool.decidir", "base": ["n:5"]}),
        # Y una decision encima de la decision: la poda tiene que ser
        # transitiva o la cadena se corta en el primer eslabon.
        _ev(7, t="decision", id="D-0003", banda="D", origen="derivado",
            texto="y de ahi esto otro",
            prov={"tipo": "derivada", "fn": "tool.decidir", "base": ["n:6"]}),
    ]
    assert "D-0002" not in bandas.fold(eventos)["invalidados"]

    muertos = eventos + [_ev(8, t="hecho", id="F-0100", banda="F",
                             op="invalidate", texto="se retracta")]
    estado = bandas.fold(muertos)
    assert "D-0002" in estado["invalidados"], "la decision cae con su base 'n:'"
    assert "D-0003" in estado["invalidados"], "y la que se apoyaba en ella"
