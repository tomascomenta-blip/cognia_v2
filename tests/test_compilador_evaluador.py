# -*- coding: utf-8 -*-
"""Tests del EXAMEN del compilador de herramientas (cognia/compilador/evaluador.py).

Lo que se fija aqui es la regla que hace util al evaluador y que es facil de
romper sin darse cuenta: UNA FASE QUE NO SE PUDO EJECUTAR NO APRUEBA. El fallo
tipico de este repo es el vacio silencioso -- un examen que no corrio y un
examen que salio verde se ven igual desde fuera si nadie lo comprueba -- y un
compilador que se auto-aprueba por no haber podido probarse es exactamente esa
trampa, pero escribiendo en cli.py.

Casi todo se prueba con ejecutores INYECTADOS por parametro (el repo hace asi
la inyeccion en todas partes): fabricar un espec de mentira y una funcion que
devuelve la salida que se quiere examinar deja los asserts en milisegundos, sin
arrancar cuatro subprocesos por caso. Los dos ultimos tests SI arrancan el REPL
de verdad, porque la fase 4 no significa nada si no se ha visto teclear.
"""
import io
import sys

import pytest

from cognia.compilador import evaluador as ev


# ── utilidades de mentira ────────────────────────────────────────────────────

def _espec(**kw):
    base = {"cmd": "/prueba-falsa", "nombre": "prueba_falsa",
            "descripcion": "comando de mentira para el examen",
            "criterios": [{"invocacion": "/prueba-falsa", "espera": "hola"}]}
    base.update(kw)
    return base


def _fase(nombre, ok=True, detalle="fabricada", salida=""):
    """Ejecutor inyectable que devuelve siempre lo mismo y cuenta llamadas."""
    llamadas = []

    def _f(plazo):
        llamadas.append(plazo)
        return {"fase": nombre, "ok": ok, "detalle": detalle, "salida": salida}

    _f.llamadas = llamadas
    return _f


def _todas_verdes():
    return {n: _fase(n, True) for n in ev.ORDEN}


# ── veredicto ────────────────────────────────────────────────────────────────

def test_las_cinco_verdes_aprueban():
    r = ev.evaluar(_espec(), fases=_todas_verdes())
    assert r["veredicto"] == "aprobada"
    assert [f["fase"] for f in r["fases"]] == list(ev.ORDEN)
    assert all(f["ok"] for f in r["fases"])
    assert "aprobada" in r["motivo"]


def test_una_fase_roja_rechaza():
    fases = _todas_verdes()
    fases["tests"] = _fase("tests", ok=False, detalle="pytest fallo (codigo 1)")
    r = ev.evaluar(_espec(), fases=fases)
    assert r["veredicto"] == "rechazada"
    assert "tests" in r["motivo"]
    # Las fases posteriores NO son bloqueantes: se ejecutan igual para que el
    # duenio vea toda la evidencia y no solo el primer sintoma.
    assert fases["invocacion"].llamadas
    assert fases["criterios"].llamadas


def test_criterios_rojos_rechazan_aunque_todo_lo_demas_este_verde():
    """La postcondicion del duenio manda: un comando que arranca, no revienta
    y no hace lo que se pidio esta rechazado."""
    fases = _todas_verdes()
    fases["criterios"] = _fase("criterios", ok=False,
                               detalle="0/1 criterios del duenio cumplidos")
    r = ev.evaluar(_espec(), fases=fases)
    assert r["veredicto"] == "rechazada"
    assert "criterios" in r["motivo"]


# ── "no se pudo ejecutar" NO es aprobado ─────────────────────────────────────

def test_una_fase_que_revienta_no_cuenta_como_aprobada():
    def _explota(plazo):
        raise RuntimeError("el ejecutor se cayo")

    fases = _todas_verdes()
    fases["invocacion"] = _explota
    r = ev.evaluar(_espec(), fases=fases)
    f4 = [f for f in r["fases"] if f["fase"] == "invocacion"][0]
    assert f4["ok"] is False
    assert "NO SE PUDO EJECUTAR" in f4["detalle"]
    assert r["veredicto"] == "rechazada"


def test_un_ejecutor_que_devuelve_basura_no_aprueba():
    """Ausencia de examen no es aprobado, ni siquiera cuando la ausencia viene
    disfrazada de None."""
    fases = _todas_verdes()
    fases["tests"] = lambda plazo: None
    r = ev.evaluar(_espec(), fases=fases)
    f3 = [f for f in r["fases"] if f["fase"] == "tests"][0]
    assert f3["ok"] is False
    assert r["veredicto"] == "rechazada"


def test_una_fase_sin_claves_se_completa_como_suspenso():
    fases = _todas_verdes()
    fases["criterios"] = lambda plazo: {}
    r = ev.evaluar(_espec(), fases=fases)
    f5 = [f for f in r["fases"] if f["fase"] == "criterios"][0]
    assert f5 == {"fase": "criterios", "ok": False, "detalle": "", "salida": ""}
    assert r["veredicto"] == "rechazada"


# ── el corte en la primera fase que invalida ─────────────────────────────────

def test_guardianes_rojos_no_llegan_a_la_invocacion():
    """El caso que pide el contrato: si el comando esta mal puesto, no se
    arranca el REPL para verlo fallar por el mismo motivo."""
    fases = _todas_verdes()
    fases["guardianes"] = _fase("guardianes", ok=False,
                                detalle="guardianes ROJOS: 2 failed")
    r = ev.evaluar(_espec(), fases=fases)
    assert r["veredicto"] == "rechazada"
    assert fases["tests"].llamadas == []
    assert fases["invocacion"].llamadas == []
    assert fases["criterios"].llamadas == []
    for nombre in ("tests", "invocacion", "criterios"):
        f = [x for x in r["fases"] if x["fase"] == nombre][0]
        assert f["ok"] is False
        assert "guardianes" in f["detalle"]


def test_sintaxis_rota_tampoco_sigue():
    fases = _todas_verdes()
    fases["sintaxis"] = _fase("sintaxis", ok=False, detalle="no compilan: cli")
    r = ev.evaluar(_espec(), fases=fases)
    assert fases["guardianes"].llamadas == []
    assert all(not f["ok"] for f in r["fases"])
    assert r["veredicto"] == "rechazada"


def test_el_orden_de_las_fases_es_el_del_contrato():
    r = ev.evaluar(_espec(), fases=_todas_verdes())
    assert [f["fase"] for f in r["fases"]] == [
        "sintaxis", "guardianes", "tests", "invocacion", "criterios"]


# ── presupuesto de tiempo ────────────────────────────────────────────────────

def _reloj(saltos):
    """Reloj falso: devuelve la siguiente marca de la lista en cada consulta."""
    estado = {"i": 0}

    def _t():
        i = min(estado["i"], len(saltos) - 1)
        estado["i"] += 1
        return saltos[i]

    return _t


def test_cada_fase_recibe_un_plazo_acotado_por_su_tope():
    fases = _todas_verdes()
    ev.evaluar(_espec(), timeout=100000, fases=fases)
    for nombre, f in fases.items():
        assert f.llamadas[0] == ev.TOPES[nombre], nombre


def test_el_plazo_se_encoge_con_lo_que_queda_del_presupuesto():
    fases = _todas_verdes()
    # arranque=0; antes de cada fase el reloj marca 0, 10, 20, 30, 40.
    ev.evaluar(_espec(), timeout=45, fases=fases,
               reloj=_reloj([0, 0, 10, 20, 30, 40]))
    assert fases["sintaxis"].llamadas == [min(ev.TOPES["sintaxis"], 45)]
    assert fases["guardianes"].llamadas == [35]
    assert fases["tests"].llamadas == [25]
    assert fases["invocacion"].llamadas == [15]
    assert fases["criterios"].llamadas == [5]


def test_el_presupuesto_agotado_suspende_lo_que_no_se_examino():
    """Si se acaba el tiempo, las fases que faltan NO se dan por buenas."""
    fases = _todas_verdes()
    r = ev.evaluar(_espec(), timeout=30, fases=fases,
                   reloj=_reloj([0, 0, 10, 40, 50, 60]))
    assert fases["sintaxis"].llamadas and fases["guardianes"].llamadas
    assert fases["tests"].llamadas == []
    assert fases["invocacion"].llamadas == []
    for nombre in ("tests", "invocacion", "criterios"):
        f = [x for x in r["fases"] if x["fase"] == nombre][0]
        assert f["ok"] is False
        assert "presupuesto" in f["detalle"]
    assert r["veredicto"] == "rechazada"


# ── fase 1: sintaxis ─────────────────────────────────────────────────────────

def test_sintaxis_compila_los_tocables_y_el_modulo_de_apoyo():
    leidos = []

    def _leer(rel):
        leidos.append(rel)
        return "x = 1\n"

    r = ev.fase_sintaxis(_espec(modulo="cognia/herramientas/falsa.py"),
                         leer=_leer)
    assert r["ok"] is True
    assert set(ev.TOCABLES).issubset(set(leidos))
    assert "cognia/herramientas/falsa.py" in leidos


def test_sintaxis_caza_el_fichero_roto_y_dice_cual():
    def _leer(rel):
        return "def f(:\n" if rel.endswith("falsa.py") else "x = 1\n"

    r = ev.fase_sintaxis(_espec(modulo="falsa.py"), leer=_leer)
    assert r["ok"] is False
    assert "falsa.py" in r["detalle"]
    assert "SyntaxError" in r["salida"]


def test_sintaxis_un_modulo_declarado_que_no_existe_no_aprueba():
    def _leer(rel):
        if rel.endswith("fantasma.py"):
            raise OSError("no existe")
        return "x = 1\n"

    r = ev.fase_sintaxis(_espec(modulo="fantasma.py"), leer=_leer)
    assert r["ok"] is False
    assert "NO SE PUDO LEER" in r["salida"]


def test_sintaxis_del_repo_real_esta_en_verde():
    """Ejecuta de verdad: los tres tocables del repo compilan ahora mismo."""
    r = ev.fase_sintaxis({})
    assert r["ok"] is True, r["salida"]


# ── fase 2: guardianes ───────────────────────────────────────────────────────

def test_guardianes_verdes():
    r = ev.fase_guardianes({}, correr=lambda t: {"ok": True, "resumen": "4 passed"})
    assert r["ok"] is True
    assert "4 passed" in r["salida"]


def test_guardianes_rojos_traen_los_fallos_en_la_salida():
    r = ev.fase_guardianes({}, correr=lambda t: {
        "ok": False, "resumen": "1 failed, 3 passed",
        "fallos": ["FAILED tests/test_harness_ayuda.py::test_topes"]})
    assert r["ok"] is False
    assert "test_topes" in r["salida"]


def test_guardianes_que_no_se_pudieron_correr_no_aprueban():
    def _revienta(t):
        raise OSError("pytest no esta")

    r = ev.fase_guardianes({}, correr=_revienta)
    assert r["ok"] is False
    assert "NO SE PUDO EJECUTAR" in r["detalle"]


def test_guardianes_reciben_el_plazo():
    vistos = []
    ev.fase_guardianes({}, plazo=42, correr=lambda t: vistos.append(t) or {"ok": True})
    assert vistos == [42]


# ── fase 3: tests ────────────────────────────────────────────────────────────

def _ejecutor(codigo, salida="", registro=None):
    def _e(cmd, plazo):
        if registro is not None:
            registro.append((cmd, plazo))
        return codigo, salida
    return _e


def test_tests_verdes():
    reg = []
    r = ev.fase_tests("tests/test_compilador_evaluador.py", plazo=77,
                      ejecutar=_ejecutor(0, "3 passed", reg))
    assert r["ok"] is True
    cmd, plazo = reg[0]
    # con ESTE interprete y en subproceso: el modulo recien reescrito esta
    # cacheado en sys.modules y un pytest interno juzgaria codigo viejo
    assert cmd[0] == sys.executable and cmd[1:3] == ["-m", "pytest"]
    assert plazo == 77


def test_tests_rojos_rechazan_y_guardan_la_salida_real():
    r = ev.fase_tests("tests/test_compilador_evaluador.py",
                      ejecutar=_ejecutor(1, "E   assert False\n1 failed"))
    assert r["ok"] is False
    assert "1 failed" in r["salida"]


def test_tests_sin_ruta_no_aprueban():
    r = ev.fase_tests("", espec={})
    assert r["ok"] is False
    assert "NO HAY TESTS" in r["detalle"]


def test_tests_de_un_fichero_inexistente_no_aprueban():
    r = ev.fase_tests("tests/no_existe_este_fichero.py")
    assert r["ok"] is False
    assert "no existen" in r["detalle"]


def test_un_fichero_sin_tests_recolectados_no_aprueba():
    """pytest sale con codigo 5 cuando no recolecto nada: examen en blanco."""
    r = ev.fase_tests("tests/test_compilador_evaluador.py",
                      ejecutar=_ejecutor(5, "no tests ran"))
    assert r["ok"] is False
    assert "NINGUN test" in r["detalle"]


def test_tests_con_timeout_no_aprueban():
    r = ev.fase_tests("tests/test_compilador_evaluador.py",
                      ejecutar=_ejecutor(None, "TIMEOUT tras 600s"))
    assert r["ok"] is False
    assert "NO SE PUDO EJECUTAR" in r["detalle"]
    assert "TIMEOUT" in r["salida"]


def test_la_ruta_de_tests_puede_venir_en_el_espec():
    r = ev.fase_tests("", espec=_espec(ruta_tests="tests/test_compilador_evaluador.py"),
                      ejecutar=_ejecutor(0, "1 passed"))
    assert r["ok"] is True


# ── fase 4: invocacion real ──────────────────────────────────────────────────

_BANNER = "\x1b[32mbanner de cognia\x1b[0m\ncognia> "


def _repl_falso(respuesta, codigo=0, registro=None):
    def _t(linea, plazo):
        if registro is not None:
            registro.append((linea, plazo))
        return codigo, _BANNER + respuesta + "\ncognia> \nHasta luego.\n"
    return _t


def test_invocacion_verde_cuando_el_comando_responde():
    reg = []
    r = ev.fase_invocacion(_espec(), plazo=30,
                           teclear=_repl_falso("clima: 21 grados", registro=reg))
    assert r["ok"] is True
    assert reg == [("/prueba-falsa", 30)]


def test_invocacion_rechaza_el_comando_que_no_esta_despachado():
    def _t(linea, plazo):
        return 0, _BANNER + ("Comando desconocido: /prueba-falsa\n"
                             "No existe el comando\ncognia> \nHasta luego.\n")

    r = ev.fase_invocacion(_espec(), teclear=_t)
    assert r["ok"] is False
    assert "no reconoce" in r["detalle"]


def test_invocacion_rechaza_el_traceback():
    r = ev.fase_invocacion(_espec(), teclear=_repl_falso(
        "Traceback (most recent call last):\n  File x\nValueError: x"))
    assert r["ok"] is False
    assert "traceback" in r["detalle"]
    assert "ValueError" in r["salida"]


def test_invocacion_rechaza_la_puerta_muda():
    """Un comando que no imprime NADA es indistinguible de uno roto: ese es el
    vacio silencioso que CLAUDE.md prohibe dejar pasar."""
    r = ev.fase_invocacion(_espec(), teclear=_repl_falso("   "))
    assert r["ok"] is False
    assert "muda" in r["detalle"]


def test_invocacion_rechaza_el_repl_que_murio():
    r = ev.fase_invocacion(_espec(), teclear=_repl_falso("algo", codigo=1))
    assert r["ok"] is False
    assert "codigo 1" in r["detalle"]


def test_invocacion_con_timeout_no_aprueba():
    r = ev.fase_invocacion(_espec(),
                           teclear=lambda l, p: (None, "TIMEOUT: el REPL no volvio"))
    assert r["ok"] is False
    assert "NO SE PUDO EJECUTAR" in r["detalle"]


def test_invocacion_sin_comando_en_el_espec_no_aprueba():
    r = ev.fase_invocacion({}, teclear=_repl_falso("lo que sea"))
    assert r["ok"] is False


# ── fase 5: criterios del duenio ─────────────────────────────────────────────

def test_criterio_cumplido():
    r = ev.fase_criterios(_espec(criterios=[{"invocacion": "/x ver",
                                             "espera": "temperatura"}]),
                          teclear=_repl_falso("la temperatura es 21"))
    assert r["ok"] is True
    assert "1/1" in r["detalle"]


def test_criterio_incumplido_ensena_lo_que_si_salio():
    r = ev.fase_criterios(_espec(criterios=[{"invocacion": "/x", "espera": "lluvia"}]),
                          teclear=_repl_falso("la temperatura es 21"))
    assert r["ok"] is False
    assert "lluvia" in r["salida"]
    assert "temperatura" in r["salida"]      # la salida REAL, para poder verlo


def test_el_criterio_aguanta_el_color_y_el_salto_de_linea_de_rich():
    """rich envuelve las lineas largas y pinta el prompt en truecolor: comparar
    en crudo daria un rechazo falso."""
    def _t(linea, plazo):
        return 0, ("cognia> \x1b[38;2;166;255;77mla ventana del\nmodelo "
                   "es\x1b[0m grande\ncognia> \nHasta luego.\n")

    r = ev.fase_criterios(_espec(criterios=[{"espera": "La Ventana Del Modelo Es"}]),
                          teclear=_t)
    assert r["ok"] is True, r["salida"]


def test_varios_criterios_se_reparten_el_plazo():
    reg = []
    ev.fase_criterios(_espec(criterios=[{"espera": "a"}, {"espera": "b"},
                                        {"espera": "c"}]),
                      plazo=90, teclear=_repl_falso("a b c", registro=reg))
    assert [p for _, p in reg] == [30, 30, 30]
    assert [l for l, _ in reg] == ["/prueba-falsa"] * 3


def test_sin_criterios_no_se_aprueba():
    """Sin postcondicion no hay nada que comprobar, y firmar en blanco es
    justo lo que este modulo existe para impedir."""
    r = ev.fase_criterios(_espec(criterios=[]), teclear=_repl_falso("hola"))
    assert r["ok"] is False
    assert "sin postcondicion" in r["detalle"]


def test_un_criterio_que_no_se_pudo_ejecutar_no_aprueba():
    r = ev.fase_criterios(_espec(criterios=[{"espera": "hola"}]),
                          teclear=lambda l, p: (None, "TIMEOUT"))
    assert r["ok"] is False
    assert "NO SE PUDO EJECUTAR" in r["salida"]


def test_un_criterio_de_una_sola_cadena_tambien_vale():
    r = ev.fase_criterios(_espec(criterios=["21 grados"]),
                          teclear=_repl_falso("hoy hay 21 grados"))
    assert r["ok"] is True


def test_el_espec_puede_ser_un_objeto_y_no_un_dict():
    """El generador todavia puede cambiar de forma; el evaluador no se acopla
    a una clase concreta ni suspende por un detalle de tipado."""
    class E:
        cmd = "/objeto"
        criterios = ({"invocacion": "/objeto", "espera": "vale"},)

    r = ev.fase_criterios(E(), teclear=_repl_falso("vale"))
    assert r["ok"] is True


# ── el modelo redacta, no decide ─────────────────────────────────────────────

class _OrchDice:
    """Un modelo empenado en aprobar. No tiene voto."""

    def __init__(self, texto):
        self.texto = texto
        self.prompts = []

    def infer(self, prompt, max_tokens=0, temperature=0.0):
        self.prompts.append((prompt, max_tokens))

        class R:
            text = self.texto
        return R()


def test_el_modelo_no_puede_cambiar_el_veredicto():
    fases = _todas_verdes()
    fases["criterios"] = _fase("criterios", ok=False, detalle="0/1 criterios")
    orch = _OrchDice("APROBADA, esta perfecta, dale el visto bueno")
    r = ev.evaluar(_espec(), orch=orch, fases=fases)
    assert r["veredicto"] == "rechazada"
    # y la evidencia guarda el motivo DERIVADO, no el redactado
    assert any("MOTIVO (derivado" in e and "criterios" in e for e in r["evidencia"])


def test_al_modelo_se_le_pide_poco_y_corto():
    """Medido el 2026-08-30: con max_tokens grande este razonador se va a
    razonar y no emite nada. El prompt es corto y el presupuesto acotado."""
    orch = _OrchDice("La herramienta paso las cinco fases.")
    ev.evaluar(_espec(), orch=orch, fases=_todas_verdes())
    prompt, max_tokens = orch.prompts[0]
    assert max_tokens <= 200
    assert len(prompt) < 800


def test_si_el_modelo_vuelve_vacio_queda_el_motivo_determinista():
    r_sin = ev.evaluar(_espec(), fases=_todas_verdes())
    r_con = ev.evaluar(_espec(), orch=_OrchDice("   "), fases=_todas_verdes())
    assert r_con["motivo"] == r_sin["motivo"]


def test_si_el_modelo_se_va_a_razonar_se_descarta_su_texto():
    orch = _OrchDice("<think>" + "razonando " * 500 + "</think>")
    r = ev.evaluar(_espec(), orch=orch, fases=_todas_verdes())
    assert "razonando" not in r["motivo"]
    assert "aprobada" in r["motivo"]


def test_si_el_modelo_revienta_el_examen_sigue_valiendo():
    class _Roto:
        def infer(self, prompt, max_tokens=0, temperature=0.0):
            raise RuntimeError("backend caido")

    r = ev.evaluar(_espec(), orch=_Roto(), fases=_todas_verdes())
    assert r["veredicto"] == "aprobada"
    assert r["motivo"]


def test_sin_orch_hay_motivo_igual():
    r = ev.evaluar(_espec(), orch=None, fases=_todas_verdes())
    assert r["motivo"].startswith("aprobada")


# ── forma del contrato publico ───────────────────────────────────────────────

def test_la_forma_del_resultado_es_la_del_contrato():
    r = ev.evaluar(_espec(), fases=_todas_verdes())
    assert set(r) == {"veredicto", "fases", "evidencia", "motivo"}
    assert r["veredicto"] in ("aprobada", "rechazada")
    assert isinstance(r["evidencia"], list)
    assert all(isinstance(e, str) for e in r["evidencia"])
    for f in r["fases"]:
        assert set(f) >= {"fase", "ok", "detalle", "salida"}
        assert isinstance(f["ok"], bool)


def test_la_salida_se_recorta_pero_conserva_principio_y_final():
    """La salida REAL viaja en el resultado (el duenio tiene que poder ver por
    que se rechazo) pero acotada: un pytest largo son megabytes."""
    largo = "INICIO" + ("x" * 50000) + "FINAL"
    r = ev.fase_tests("tests/test_compilador_evaluador.py",
                      ejecutar=_ejecutor(1, largo))
    assert r["ok"] is False
    assert len(r["salida"]) < ev.TOPE_SALIDA + 200
    assert r["salida"].startswith("INICIO") and r["salida"].endswith("FINAL")
    assert "recortado" in r["salida"]


def test_los_tocables_son_los_mismos_que_toca_el_injertador():
    """La copia de la lista no puede quedarse vieja: un fichero que el injerto
    toca y el examen no compila es un agujero por el que pasa sintaxis rota."""
    from cognia.compilador import injertador as inj
    assert tuple(ev.TOCABLES) == tuple(inj.TOCABLES)


def test_estado_es_la_puerta_de_diagnostico():
    e = ev.estado()
    assert e["fases"] == list(ev.ORDEN)
    assert e["interprete"] == sys.executable
    assert e["guardianes"] and e["tocables"]


def test_el_modulo_no_tiene_except_pass_mudo():
    """Regla dura del repo: 'no lo cablearon' y 'se rompio' no pueden verse
    igual desde fuera."""
    fuente = io.open(ev.__file__, encoding="utf-8").read()
    assert "except Exception:\n        pass" not in fuente
    assert ": pass" not in fuente


# ── EJECUCION REAL: el REPL de verdad (esto es lo que no puede fingirse) ─────

def test_invocacion_real_de_un_comando_que_existe():
    """Arranca `python -m cognia` de verdad y teclea /ventana.

    Sin este test, la fase 4 seria una promesa: todo lo de arriba usa un REPL
    de mentira. Medido: ~2 s por invocacion.
    """
    r = ev.fase_invocacion({"cmd": "/ventana"}, plazo=240)
    assert r["ok"] is True, r["salida"][-1500:]
    assert "ventana" in ev._normalizar(r["salida"])


def test_invocacion_real_de_un_comando_que_no_existe_se_rechaza():
    """El contrafactual: si aprobase esto tambien, la fase 4 no mediria nada."""
    r = ev.fase_invocacion({"cmd": "/comando-inventado-para-el-examen"}, plazo=240)
    assert r["ok"] is False
    assert "no reconoce" in r["detalle"], r["salida"][-1500:]
