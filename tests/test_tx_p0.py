# -*- coding: utf-8 -*-
"""P0 del subsistema TX/LIBRO -- los prerrequisitos de la ESPEC seccion 14.1.

Cada bloque trae al menos UN test que FALLA sin su arreglo. No son tests de
"la funcion devuelve un dict": son las cuatro mentiras que el instrumento
contaba y que estos arreglos callan.

  P0-1  run_tool devuelve el returncode REAL (y 'ok' deja de salir de una regex
        sobre 120 chars).
  P0-2  la escritura del LIBRO fuera de los 'except Exception: pass'.
  P0-3  el contrato resuelve rutas contra el WORKSPACE y admite criterio barato.
  P0-4  G2 se mide sobre la RESPUESTA del modelo, no sobre la proyeccion.
"""

import os
import sys

import pytest

from cognia.agent import tools
from cognia.agents import goal_contract as gc
from cognia.estado import canal
from cognia.harness import interceptor
from cognia.tx.errores import LibroCaido


# =====================================================================
# P0-1 -- el exit code real
# =====================================================================

@pytest.fixture
def shell_corre(monkeypatch):
    """Deja que el shell se EJECUTE de verdad.

    El sentinel esta en default-deny y sin canal de confirmacion manda a
    CONFIRM cualquier cosa fuera de su allowlist -- incluido un 'exit 3'. Sin
    esto, la mitad de los tests de P0-1 medirian el bloqueo en vez de medir el
    exit code. (Que el bloqueo tambien deje _exit=None se comprueba aparte, en
    test_p01_comando_bloqueado_no_produce_exit_cero.)
    """
    monkeypatch.setenv("COGNIA_AUTONOMOUS", "1")


def test_p01_shell_escribe_el_exit_real(shell_corre):
    """_shell deja el returncode en el ctx. Sin el arreglo no hay clave."""
    ctx = {}
    out = tools._shell("exit 3", ctx, timeout=30)
    assert ctx["_exit"] == 3, out


def test_p01_shell_exito_escribe_cero(shell_corre):
    ctx = {}
    tools._shell("exit 0", ctx, timeout=30)
    assert ctx["_exit"] == 0


def test_p01_comando_bloqueado_no_produce_exit_cero(monkeypatch):
    """EL TEST OBLIGATORIO. Un comando que el sentinel BLOQUEA no se ejecuto
    nunca: no puede llegar con exit 0 ni con ok=True.

    Sin el arreglo: `ctx['_exit']` no existe y el mensaje 'RESULTADO ejecutar:
    BLOQUEADO por Sentinel (...)' no contiene \\bERROR\\b en los 120 primeros
    chars, asi que la regex daba ok=True -- una victoria sobre un comando que
    jamas corrio.
    """
    monkeypatch.setattr(tools, "_marcar_exit", tools._marcar_exit)

    def _bloqueado(cmd, ctx=None):
        return False, "RESULTADO ejecutar: BLOQUEADO por Sentinel (destructivo)."

    monkeypatch.setattr("cognia.agent.sentinel.evaluar_shell", _bloqueado)

    ctx = {}
    salida = tools._shell("rm -rf /", ctx, timeout=30)
    assert "BLOQUEADO" in salida
    # None, NO 0: sin exit real no hay medicion.
    assert ctx["_exit"] is None
    assert ctx["_exit"] != 0

    # Y el mismo comando a traves de run_tool tiene que dar ok=False.
    vistos = []
    monkeypatch.setattr(tools, "_record_usage",
                        lambda name, ok: vistos.append((name, ok)))
    tools.run_tool("ejecutar", "rm -rf /", {})
    assert vistos == [("ejecutar", False)], vistos


def test_p01_pytest_que_falla_no_produce_ok_true(monkeypatch, shell_corre):
    """EL SEGUNDO TEST OBLIGATORIO. Un pytest con exit 1.

    Sin el arreglo la salida es 'RESULTADO ejecutar (exit 1): ...' -- sin
    ERROR en la cabeza -- y ok salia True.
    """
    vistos = []
    monkeypatch.setattr(tools, "_record_usage",
                        lambda name, ok: vistos.append((name, ok)))
    salida = tools.run_tool(
        "ejecutar",
        '"%s" -c "import sys; print(\'1 failed\'); sys.exit(1)"' % sys.executable,
        {})
    assert "exit 1" in salida, salida
    assert vistos == [("ejecutar", False)], vistos


def test_p01_exit_cero_sigue_siendo_ok(monkeypatch, shell_corre):
    """No-regresion: el arreglo solo puede TUMBAR un ok, nunca inventarlo."""
    vistos = []
    monkeypatch.setattr(tools, "_record_usage",
                        lambda name, ok: vistos.append((name, ok)))
    tools.run_tool("ejecutar", '"%s" -c "print(42)"' % sys.executable, {})
    assert vistos == [("ejecutar", True)], vistos


def test_p01_tool_que_no_es_shell_no_toca_ok(monkeypatch):
    """Una tool que no pasa por el shell no tiene exit: 'ok' lo sigue
    decidiendo la regex, exactamente como antes."""
    vistos = []
    monkeypatch.setattr(tools, "_record_usage",
                        lambda name, ok: vistos.append((name, ok)))
    tools.run_tool("leer_archivo", __file__, {})
    assert vistos == [("leer_archivo", True)], vistos


def test_p01_exit_no_se_filtra_a_la_llamada_siguiente(monkeypatch, shell_corre):
    """El exit se hace pop: un exit rancio marcando fallida la tool siguiente
    seria el bug del 'evento sellado con el reloj rancio'."""
    ctx = {}
    vistos = []
    monkeypatch.setattr(tools, "_record_usage",
                        lambda name, ok: vistos.append((name, ok)))
    tools.run_tool("ejecutar", "exit 7", ctx)
    assert "_exit" not in ctx
    tools.run_tool("leer_archivo", __file__, ctx)
    assert vistos == [("ejecutar", False), ("leer_archivo", True)], vistos


def test_p01_el_exit_llega_al_interceptor(monkeypatch, shell_corre):
    """run_tool propaga exit_code a interceptor.despues (es de donde el LIBRO
    saca la provenance)."""
    recibidos = []

    def _fake_despues(name, args, ctx, out, ok, exit_code=None):
        recibidos.append(exit_code)
        return out

    monkeypatch.setattr("cognia.harness.interceptor.despues", _fake_despues)
    tools.run_tool("ejecutar", "exit 5", {})
    assert recibidos == [5], recibidos


# =====================================================================
# P0-1 (b) -- la regla None != 0 en la provenance
# =====================================================================

def test_p01_envelope_sin_exit_no_es_medido():
    """La regla que justifica todo P0-1: sin exit real, origen NO puede ser
    'medido' ni prov.tipo puede ser 'ejecutada'."""
    ev = interceptor.envelope("ejecutar", "rm -rf /", {}, "BLOQUEADO", False,
                              exit_code=None)
    assert ev["origen"] != "medido"
    assert ev["prov"]["tipo"] != "ejecutada"
    assert "exit_code" not in ev["prov"]
    assert ev["prov"]["sin_exit"] is True
    assert ev["exit_code"] is None


def test_p01_envelope_con_exit_si_es_medido():
    ev = interceptor.envelope("ejecutar", "pytest", {}, "salida", False,
                              exit_code=1)
    assert ev["origen"] == "medido"
    assert ev["conf"] == 1.0
    assert ev["prov"]["tipo"] == "ejecutada"
    assert ev["prov"]["exit_code"] == 1
    # 'pytest' -> clave `test:` y valor booleano (ESPEC 3.4, claves.canonica).
    assert ev["clave"].startswith("test:") and ev["valor"] is False
    otro = interceptor.envelope("ejecutar", "git status", {}, "s", False,
                                exit_code=1)
    assert otro["clave"].startswith("cmd:") and otro["valor"] == 1


def test_p01_envelope_exit_cero_no_se_confunde_con_none():
    con_cero = interceptor.envelope("ejecutar", "x", {}, "ok", True, exit_code=0)
    sin_nada = interceptor.envelope("ejecutar", "x", {}, "ok", True, exit_code=None)
    assert con_cero["origen"] == "medido"
    assert sin_nada["origen"] != "medido"
    assert con_cero["prov"]["exit_code"] == 0


def test_p01_envelope_no_acepta_un_bool_como_exit():
    """True == 1 en Python. Un bool colandose como exit code convertiria un
    'ok' del modelo en 'medido'."""
    ev = interceptor.envelope("ejecutar", "x", {}, "ok", True, exit_code=True)
    assert ev["origen"] != "medido"


# =====================================================================
# P0-2 -- el LIBRO no vive bajo un 'except Exception: pass'
# =====================================================================

def test_p02_apagado_es_no_op(monkeypatch):
    """Con COGNIA_TX apagado el hueco no existe: ni se mira el paquete."""
    monkeypatch.delenv("COGNIA_TX", raising=False)
    llamadas = []
    monkeypatch.setattr(interceptor, "_avisar_libro_ausente",
                        lambda: llamadas.append(1))
    interceptor._libro("ejecutar", "x", {}, "salida", True, 0)
    assert llamadas == []


def test_p02_encendido_y_sin_almacen_avisa_pero_no_para(monkeypatch):
    """'todavia no construido' NO es 'roto': no puede parar el ciclo, pero
    tampoco puede callarse."""
    monkeypatch.setenv("COGNIA_TX", "1")
    monkeypatch.setattr(interceptor, "_LIBRO_AVISADO", [])
    avisos = []
    monkeypatch.setattr(interceptor, "_avisar_libro_ausente",
                        lambda: avisos.append(1))
    monkeypatch.setattr("importlib.util.find_spec", lambda nombre: None)
    interceptor._libro("ejecutar", "x", {}, "salida", True, 0)
    assert avisos == [1]


def test_p02_fallo_de_escritura_lanza_libro_caido(monkeypatch):
    """EL TEST DE P0-2. Un disco lleno no puede apagar la memoria en silencio.

    Sin el arreglo, la escritura habria vivido bajo uno de los 11
    'except Exception: pass' de interceptor.py y esto pasaria sin excepcion.
    """
    monkeypatch.setenv("COGNIA_TX", "1")

    class _Almacen:
        @staticmethod
        def registrar_tool(evento, ctx=None):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr("importlib.util.find_spec", lambda nombre: object())
    monkeypatch.setitem(sys.modules, "cognia.tx.libro", _Almacen)
    # Y el ATRIBUTO del paquete, no solo sys.modules: `from cognia.tx import
    # libro` hace getattr sobre el paquete, asi que en cuanto CUALQUIER test
    # anterior haya importado el almacen de verdad, parchear sys.modules solo
    # deja de llegar al codigo bajo prueba y esto pasa por el motivo
    # equivocado (mide el import, no el contrato de P0-2).
    import cognia.tx as _paquete_tx
    monkeypatch.setattr(_paquete_tx, "libro", _Almacen, raising=False)

    with pytest.raises(LibroCaido) as exc:
        interceptor._libro("ejecutar", "x", {}, "salida", True, 0)
    assert "No space left" in str(exc.value)
    assert isinstance(exc.value.causa, OSError)


def test_p02_libro_caido_sube_por_despues(monkeypatch):
    """La excepcion tiene que ATRAVESAR despues(), que es lo que run_tool
    llama. Si despues la tragase, el contrato no valdria nada."""
    monkeypatch.setenv("COGNIA_TX", "1")
    monkeypatch.setattr(interceptor, "_libro",
                        lambda *a, **k: (_ for _ in ()).throw(
                            LibroCaido("prueba", None)))
    with pytest.raises(LibroCaido):
        interceptor.despues("ejecutar", "x", {}, "salida", True, exit_code=0)


def test_p02_libro_caido_sube_por_run_tool(monkeypatch):
    """Y tiene que atravesar tambien el 'except Exception' de run_tool, que es
    el que traga TODO lo demas del arnes."""
    def _revienta(name, args, ctx, out, ok, exit_code=None):
        raise LibroCaido("no pude escribir", OSError("disco"))

    monkeypatch.setattr("cognia.harness.interceptor.despues", _revienta)
    monkeypatch.setattr(tools, "_record_usage", lambda name, ok: None)
    with pytest.raises(LibroCaido):
        tools.run_tool("leer_archivo", __file__, {})


def test_p02_otros_fallos_del_arnes_siguen_sin_parar_el_ciclo(monkeypatch):
    """No-regresion del contrato viejo: lo que NO es LibroCaido se sigue
    degradando a 'no hacer nada'. El agente tiene que sobrevivir al arnes."""
    def _revienta(name, args, ctx, out, ok, exit_code=None):
        raise RuntimeError("una capa cualquiera del arnes se rompio")

    monkeypatch.setattr("cognia.harness.interceptor.despues", _revienta)
    monkeypatch.setattr(tools, "_record_usage", lambda name, ok: None)
    salida = tools.run_tool("leer_archivo", __file__, {})
    assert isinstance(salida, str)


# =====================================================================
# P0-3 -- workspace, criterio barato y timeout
# =====================================================================

def test_p03_file_exists_resuelve_contra_el_workspace(tmp_path, monkeypatch):
    """EL TEST DE P0-3. Un criterio relativo tiene que mirar el WORKSPACE.

    Sin el arreglo se resolvia contra el CWD del proceso: si el agente escribio
    en su workspace, el criterio decia 'missing' sobre un fichero que existe.
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "entregable.py").write_text("x = 1\n", encoding="utf-8")

    otro = tmp_path / "otro_cwd"
    otro.mkdir()
    monkeypatch.chdir(otro)

    sin_ws = gc.GoalContract.from_spec(
        "g", [{"kind": "file_exists", "path": "entregable.py", "description": "d"}])
    assert sin_ws.check().complete is False        # el bug viejo, cristalizado

    con_ws = gc.GoalContract.from_spec(
        "g", [{"kind": "file_exists", "path": "entregable.py", "description": "d"}],
        workspace=str(ws))
    assert con_ws.check().complete is True


def test_p03_file_exists_no_da_falso_pass_por_homonimo(tmp_path, monkeypatch):
    """El caso PEOR del bug: un fichero con el mismo nombre en el CWD del
    proceso daba PASS sobre un artefacto que la tarea nunca produjo."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    otro = tmp_path / "otro_cwd"
    otro.mkdir()
    (otro / "entregable.py").write_text("no es el mio\n", encoding="utf-8")
    monkeypatch.chdir(otro)

    con_ws = gc.GoalContract.from_spec(
        "g", [{"kind": "file_exists", "path": "entregable.py", "description": "d"}],
        workspace=str(ws))
    assert con_ws.check().complete is False


def test_p03_comando_corre_con_cwd_del_workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "marca.txt").write_text("aqui\n", encoding="utf-8")
    contrato = gc.GoalContract.from_spec(
        "g",
        [{"kind": "command_succeeds",
          "command": '"%s" -c "import os,sys; sys.exit(0 if os.path.exists(\'marca.txt\') else 9)"' % sys.executable,
          "description": "corre en el workspace"}],
        workspace=str(ws))
    st = contrato.check()
    assert st.complete is True, gc.format_status(st)


def test_p03_timeout_configurable_por_env(monkeypatch):
    monkeypatch.setenv(gc._TIMEOUT_ENV, "7")
    assert gc._timeout_default() == 7
    monkeypatch.setenv(gc._TIMEOUT_ENV, "basura")
    assert gc._timeout_default() == gc._COMMAND_TIMEOUT_SECONDS
    monkeypatch.setenv(gc._TIMEOUT_ENV, "99999")
    assert gc._timeout_default() == gc._TIMEOUT_MAX


def test_p03_timeout_por_criterio_gana_al_default(monkeypatch):
    monkeypatch.setenv(gc._TIMEOUT_ENV, "45")
    assert gc.timeout_de({"timeout": 2}) == 2
    assert gc.timeout_de({}) == 45


def test_p03_timeout_no_cuenta_como_fail():
    """ESPEC 9.5: un criterio que se pasa de tiempo es flaky del instrumento,
    no evidencia de nada. Se marca aparte para que no dispare rollback."""
    contrato = gc.GoalContract.from_spec(
        "g",
        [{"kind": "command_succeeds",
          "command": '"%s" -c "import time; time.sleep(5)"' % sys.executable,
          "timeout": 1,
          "description": "lento a proposito"}])
    st = contrato.check()
    assert st.results[0].satisfied is False
    assert st.results[0].timeout is True
    assert "[TO]" in gc.format_status(st)


def test_p03_coste_ms_se_mide_y_no_se_declara():
    contrato = gc.GoalContract.from_spec(
        "g", [{"kind": "file_exists", "path": __file__, "description": "d"}])
    st = contrato.check()
    assert st.results[0].coste_ms is not None
    assert st.results[0].coste_ms >= 0
    assert contrato.coste_ms[0] == st.results[0].coste_ms


def test_p03_solo_baratos_salta_el_caro_sin_contarlo_como_pass():
    """La regla del criterio barato. Un criterio caro se SALTA por ciclo, y
    saltarlo no puede ni aprobar ni suspender el contrato."""
    contrato = gc.GoalContract.from_spec(
        "g",
        [{"kind": "file_exists", "path": __file__, "description": "barato"},
         {"kind": "file_exists", "path": __file__, "description": "caro"}])
    contrato.check()                       # primera pasada: mide costes
    contrato.coste_ms[1] = gc.CRITERIO_BARATO_MS + 1   # el caro, medido

    st = contrato.check(solo_baratos=True)
    # El saltado NO desaparece del recuento: hereda su ultimo veredicto medido
    # (ESPEC 9.5, "mismos bytes -> mismo exit"). Tirarlo hacia que
    # satisfied_count bajase SOLO por haber saltado el criterio, y G5 leia ese
    # descenso como RETROCESO y cerraba el reset para siempre.
    assert st.total == 2
    assert st.satisfied_count == 2
    assert st.heredados == 1
    assert "HEREDADO" in st.results[1].detail
    assert st.results[1].heredado is True
    # Y `complete` NO puede decir que si con un criterio sin reejecutar.
    assert st.complete is False

    entero = contrato.check()
    assert entero.total == 2               # el cierre los corre todos
    assert entero.heredados == 0 and entero.complete is True


def test_p03_criterio_nunca_medido_no_se_salta():
    """Un criterio sin coste conocido se ejecuta una vez: es la unica forma de
    saber lo que cuesta (se mide, no se declara)."""
    contrato = gc.GoalContract.from_spec(
        "g", [{"kind": "file_exists", "path": __file__, "description": "d"}])
    st = contrato.check(solo_baratos=True)
    assert st.total == 1
    assert contrato.coste_ms[0] is not None


def test_p03_sin_workspace_se_comporta_como_antes(tmp_path, monkeypatch):
    """No-regresion: los llamadores actuales no pasan workspace y tienen que
    seguir resolviendo contra el CWD."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "aqui.txt").write_text("x", encoding="utf-8")
    contrato = gc.GoalContract.from_spec(
        "g", [{"kind": "file_exists", "path": "aqui.txt", "description": "d"}])
    assert contrato.check().complete is True


# =====================================================================
# P0-4 -- G2 sobre la respuesta, no sobre la proyeccion
# =====================================================================

def _estado_con_trazadores():
    e = canal.EstadoVerificado(objetivo="o", turno="t1")
    canal.sembrar_trazadores(e, k=3, semilla=19)
    return e


def test_p04_la_proyeccion_no_mide_lectura():
    """EL TEST DE P0-4. La proyeccion es salida de una funcion pura que acaba
    de escribir los trazadores: recall 1,0 SIEMPRE, informacion cero.

    Sin el arreglo, ese 1,0 se leia como 'G2 pasa'. Ahora el mismo 1,0 viene
    con mide_lectura=False y no puede conceder nada.
    """
    e = _estado_con_trazadores()
    proyeccion = " ".join(t["texto"] for t in e["trazadores"])
    d = canal.comprobar_trazadores(e, proyeccion,
                                   fuente=canal.FUENTE_PROYECCION)
    assert d["recall"] == 1.0
    assert d["mide_lectura"] is False


def test_p04_la_respuesta_del_modelo_si_mide():
    e = _estado_con_trazadores()
    respuesta = "Anotado: " + e["trazadores"][0]["id"]
    d = canal.g2_sobre_respuesta(e, respuesta)
    assert d["fuente"] == canal.FUENTE_RESPUESTA
    assert d["mide_lectura"] is True
    assert d["recall"] == 1 / 3.0


def test_p04_respuesta_vacia_no_es_no_leyo():
    """0 trazadores en 0 chars no es 'el modelo no leyo': es 'no hubo
    respuesta'. Son decisiones distintas (reintentar vs abortar el reset)."""
    e = _estado_con_trazadores()
    d = canal.g2_sobre_respuesta(e, "   ")
    assert d["recall"] == 0.0
    assert d["mide_lectura"] is False
    assert "VACIA" in d["motivo"]


def test_p04_assert_de_integridad_dice_lo_que_es():
    e = _estado_con_trazadores()
    proyeccion = " ".join(t["texto"] for t in e["trazadores"])
    d = canal.assert_integridad_proyeccion(e, proyeccion)
    assert d["integridad_ok"] is True
    assert d["mide_lectura"] is False

    roto = canal.assert_integridad_proyeccion(e, "el proyector no escribio nada")
    assert roto["integridad_ok"] is False


def test_p04_fuente_por_defecto_no_concede_nada():
    """Quien no declara la fuente no puede afirmar que midio: default
    conservador, y los llamadores viejos siguen leyendo 'recall' igual."""
    e = _estado_con_trazadores()
    texto = " ".join(t["texto"] for t in e["trazadores"])
    d = canal.comprobar_trazadores(e, texto)
    assert d["recall"] == 1.0                 # contrato viejo intacto
    assert d["fuente"] == canal.FUENTE_DESCONOCIDA
    assert d["mide_lectura"] is False


# =====================================================================
# La puerta en el CLI (regla vinculante del repo) y el opt-in
# =====================================================================

def test_puerta_tx_en_ayuda():
    from cognia import cli
    assert "/tx" in cli._CMD_DESCRIPTIONS
    assert "/tx" in cli.COMMANDS


def test_tx_apagado_por_defecto(monkeypatch):
    """OPT-IN no negociable: sin COGNIA_TX, el subsistema no corre."""
    monkeypatch.delenv("COGNIA_TX", raising=False)
    assert interceptor._activo("COGNIA_TX") is False


# =====================================================================
# REGRESION 2026-08-19 -- P0-1 no llegaba a su consumidor real
# =====================================================================

def test_p01_run_tool_publica_el_exit_real_para_el_bucle(tmp_path, shell_corre):
    """El `ok` corregido por P0-1 NO SALIA de `run_tool`: solo alimentaba
    `_record_usage`, un `emit` sin suscriptores y el LIBRO (opt-in). El bucle
    nativo se calculaba el suyo con la MISMA regex que P0-1 vino a sustituir.

    Verificado de punta a punta: `run_tool('tests', <suite en rojo>)` devuelve
    'RESULTADO ejecutar (exit 1): F ...' y la regex de loop.py daba tool_ok=True.
    Con eso, en el mismo turno se escribia `exit: 0` en el canal de estado (que
    documenta "su exit code REAL"), el presupuesto por progreso contaba una
    suite ROJA como avance verificado y la parada verificada de Hermes recibia
    evidencia de que la verificacion paso.
    """
    import re
    fichero = tmp_path / "test_rojo.py"
    fichero.write_text("def test_x():\n    assert 1 == 2\n", encoding="utf-8")
    ctx = {"confirm": lambda *a, **k: True}
    out = tools.run_tool("tests", str(fichero), ctx)

    assert ctx["_ultimo_exit"] == 1, "el exit REAL, disponible para el bucle"
    assert ctx["_ultimo_ok"] is False
    # La regex sola habria dicho que si: ese es el bug que esto cierra.
    assert not re.search(r"\bERROR\b", out.split("\n", 1)[0][:120])


def test_p01_el_bucle_usa_el_exit_y_no_la_regex():
    """El consumidor, comprobado en el FUENTE: `loop.py` tiene que leer
    `_ultimo_ok`/`_ultimo_exit` y anotar el comando con su exit real en vez de
    fabricar `0 if tool_ok else 1`."""
    import inspect
    from cognia.agent import loop
    fuente = inspect.getsource(loop)
    assert "_ultimo_ok" in fuente and "_ultimo_exit" in fuente
    assert "_canal.anotar_comando(_estado, args_str[:200],\n" \
           "                                                  _exit_real, resultado)" in fuente


def test_p01_un_resultado_especulado_no_hereda_el_exit_anterior():
    """El ctx viaja entre turnos. Si un resultado servido por la especulacion
    (que no pasa por run_tool) leyera el `_ultimo_exit` del turno anterior,
    seria el bug del 'evento sellado con el reloj rancio'."""
    import inspect
    from cognia.agent import loop
    fuente = inspect.getsource(loop)
    assert 'ctx.pop("_ultimo_exit", None)' in fuente
    assert 'ctx.pop("_ultimo_ok", None)' in fuente
