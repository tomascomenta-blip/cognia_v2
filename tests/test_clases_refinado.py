# -*- coding: utf-8 -*-
"""
tests/test_clases_refinado.py
=============================
El REFINADO QUE SE HACE SOLO mientras la clase pasa (cognia/clases/refinado.py).

Lo que se prueba aqui es exactamente lo que hace que la pieza sea barata y no
destructiva:

  - dos vueltas seguidas NO le pagan al modelo el mismo tramo dos veces (la
    marca de agua `chars_entrada` avanza) y no borran ninguna clave previa de
    apuntes.json;
  - con el modelo caido no se pierde ni un char y queda el aviso, pero un
    aviso NUNCA crea una entrada nueva (eso haria que `olvido` comprimiera la
    transcripcion de una clase sin apuntes);
  - el disyuntor apaga el refinado tras dos vueltas esteriles;
  - el volcado a bloques respeta lo que el duenio fijo.

EL MODELO SE SIMULA INYECTANDO UN GENERADOR FALSO por el parametro `generar`
de `ciclo`/`tick`, nunca llamando al de verdad: el modelo local del duenio
tarda ~13 s por ventana y no esta arriba, asi que un test que lo llamara no se
correria nunca -- que es la unica forma segura de que estos caminos no se
prueben. Lo que si se prueba contra el modulo real es que el refinado habla
por `llm_local` y NO por `orch.infer`, y que fuerza el re-sondeo del backend.

AISLAMIENTO: COGNIA_CLASES_DIR a tmp_path, la config del refinado limpia, el
estado de modulo (que es de proceso, como la jornada) reseteado, y la cache de
backend de `llm_local` puesta a "no hay" para que ningun test salga a la red.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime

import pytest

from cognia import llm_local as llm
from cognia.clases import almacen as alm
from cognia.clases import apuntes as ap
from cognia.clases import cuaderno as cua
from cognia.clases import documento as doc
from cognia.clases import jornada as jor
from cognia.clases import olvido as olv
from cognia.clases import refinado as ref

JORNADA = "2026-08-31"


@pytest.fixture(autouse=True)
def _aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path / "clases"))
    monkeypatch.delenv(ref.ENV_ACTIVO, raising=False)
    monkeypatch.delenv(ref.ENV_PERIODO, raising=False)
    monkeypatch.delenv("COGNIA_COMPACT_CAP", raising=False)
    monkeypatch.delenv("COGNIA_COMPACT", raising=False)
    # El estado del refinado es de PROCESO (vive en el hilo vigia de una
    # jornada viva): sin esto, el disyuntor de un test apagaria la jornada del
    # siguiente y los avisos ya dichos no volverian a decirse.
    monkeypatch.setattr(ref, "_ESTADO", {})
    monkeypatch.setattr(ref, "_vueltas_totales", 0)
    monkeypatch.setattr(ref, "_avisos_dados", set())
    monkeypatch.setattr(ref, "_ultimo_fallo", {})
    # "Ya se sondeo y no hay backend": detectar_backend() devuelve None sin
    # tocar la red (llm_local.py:125). Y el sondeo REAL se corta ademas por
    # debajo, porque el re-sondeo forzado (que es justo lo que esta pieza
    # hace cada 4 vueltas) ignora esa cache: sin esto, la suite sale a la red
    # de la maquina del duenio y un test tardaba 120 s en el timeout de
    # generacion contra lo que hubiera escuchando en el 8080.
    monkeypatch.setattr(llm, "_backend", {})
    monkeypatch.setattr(llm, "_sondear", lambda url, ruta: False)
    monkeypatch.setattr(llm, "_modelos_ollama", lambda url: [])
    monkeypatch.delenv("COGNIA_LLM_URL", raising=False)
    # El olvido entra en varios tests de aqui (comprime la transcripcion de una
    # jornada con apuntes): sus umbrales tienen que ser los de fabrica, no los
    # que el duenio tenga puestos en su shell.
    for var in (olv.ENV_ACTIVO, olv.ENV_DIAS_AUDIO, olv.ENV_DIAS_TRANSCRIPCION,
                olv.ENV_FRACCION):
        monkeypatch.delenv(var, raising=False)


# ── Una clase de verdad, troceada como la deja la captura ────────────────────

def _texto_de_clase(partes: int = 80) -> list:
    """Una clase larga, con cada trozo IDENTIFICABLE.

    El marcador "Parte numero N" es lo que permite comprobar QUE tramo vio el
    modelo en cada vuelta, que es el corazon de esta pieza: sin el, "no
    reprocesa" no se puede distinguir de "reprocesa y da lo mismo".
    """
    return [
        "Parte numero %d: seguimos con el tema y ahora vemos como se calcula "
        "el valor que corresponde a este apartado, que es el que suele caer "
        "en los ejercicios de final de tema y el que mas cuesta al principio "
        "porque hay que fijarse en las unidades." % i
        for i in range(1, partes + 1)
    ]


def _grabar(nombre: str = JORNADA, materia: str = "Fisica",
            partes: int = 80) -> str:
    """Deja una jornada en disco (transcripcion + un corte de materia) y
    devuelve el texto dicho completo, que es contra lo que se comprueban las
    marcas de agua."""
    d = alm.dir_jornada(nombre)
    t = 0.0
    for trozo in _texto_de_clase(partes):
        alm.apendar(d / alm.TRANSCRIPCION,
                    {"t": t, "tipo": cua.TIPO_TRANSCRIPCION, "texto": trozo,
                     "t_fin": t + 20.0, "fuente": "sistema"})
        t += 20.0
    if materia:
        alm.apendar(d / alm.CORTES,
                    {"t": 0.0, "materia": materia, "confianza": 1.0,
                     "por": "manual"})
    return cua.sesiones_de(nombre)[0].texto_dicho()


def _clave(nombre: str = JORNADA) -> str:
    return ap.clave_de_sesion(nombre, cua.sesiones_de(nombre)[0])


def _mapa(nombre: str = JORNADA) -> dict:
    return alm.leer_json(alm.dir_jornada(nombre) / alm.APUNTES, {}) or {}


def _regs(nombre: str = JORNADA) -> list:
    """La transcripcion literal tal cual esta en disco."""
    return alm.leer_jsonl(alm.dir_jornada(nombre) / alm.TRANSCRIPCION)


def _muy_tarde(nombre: str = JORNADA, dias: float = 200.0) -> float:
    """Un 'ahora' desde el que la jornada ya paso todos los umbrales del
    olvido. Se calcula del nombre (que es la fecha) para no depender del reloj
    de la maquina, igual que hace `olvido._edad_dias`."""
    return datetime.strptime(nombre[:10], "%Y-%m-%d").timestamp() + dias * 86400.0


def _filas_transcripcion(ahora: float) -> list:
    return [f for f in olv.plan(ahora=ahora)
            if f["objetivo"] == alm.TRANSCRIPCION]


class GeneradorFalso:
    """El modelo, simulado. Guarda los prompts y responde en el formato
    etiquetado que `apuntes._parsear` sabe leer, con el numero de parte que
    venia dentro del fragmento: asi la respuesta DEPENDE del tramo y se puede
    comprobar que cada vuelta vio uno distinto."""

    def __init__(self, mudo: bool = False):
        self.prompts: list = []
        self.mudo = mudo

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.mudo:
            return ""
        partes = re.findall(r"Parte numero (\d+)", prompt)
        if not partes:
            return ""
        return "\n".join(["CLAVE: la idea de la parte %s" % p for p in partes[:3]]
                         + ["DEBER: repasar la parte %s" % partes[0]])

    def partes(self) -> list:
        """Los numeros de parte que el modelo llego a VER, en orden."""
        fuera = []
        for p in self.prompts:
            fuera.extend(int(x) for x in re.findall(r"Parte numero (\d+)", p))
        return fuera


# ── Dos vueltas: la marca de agua avanza ─────────────────────────────────────

def test_una_vuelta_solo_paga_las_ventanas_del_lote():
    """Lo que hace barata la pieza: NO son las 13 llamadas de regenerar la
    sesion, son las dos del lote."""
    _grabar()
    g = GeneradorFalso()
    res = ref.ciclo(JORNADA, generar=g)
    assert res["estado"] == "refinado"
    assert res["llamadas"] == ref.MAX_VENTANAS_VUELTA == 2
    assert len(g.prompts) == 2


def test_dos_vueltas_no_reprocesan_el_mismo_tramo():
    texto = _grabar()
    g1 = GeneradorFalso()
    ref.ciclo(JORNADA, generar=g1)
    marca1 = _mapa()[_clave()]["chars_entrada"]
    assert 0 < marca1 < len(texto)

    g2 = GeneradorFalso()
    ref.ciclo(JORNADA, generar=g2)
    marca2 = _mapa()[_clave()]["chars_entrada"]

    # La marca avanza, y lo que se le manda al modelo en la segunda vuelta
    # sale ENTERO de lo que quedaba por detras de la primera marca.
    assert marca2 > marca1
    pendiente = texto[marca1:]
    for prompt in g2.prompts:
        fragmento = prompt.split("FRAGMENTO:\n", 1)[1].strip()
        assert fragmento in pendiente
    # Y las partes de la clase que ve la segunda vuelta son posteriores a las
    # de la primera: nada se pide dos veces.
    assert min(g2.partes()) > max(g1.partes())


def test_dos_vueltas_no_borran_ninguna_clave_previa():
    """La decision 4 de apuntes.py, aqui: se FUNDE sobre lo que hay. Ni las
    ortografias que la vista pinta ('puntos_clave') ni lo que el duenio metio
    a mano pueden desaparecer porque pase el refinado."""
    _grabar()
    clave = _clave()
    ruta = alm.dir_jornada(JORNADA) / alm.APUNTES
    alm.guardar_json(ruta, {clave: {"claves": ["lo de siempre"],
                                    "puntos_clave": ["ortografia vieja"],
                                    "mio": "esto lo escribi yo",
                                    "chars_entrada": 0},
                            "otra-jornada@0": {"claves": ["de otra sesion"]}})

    g = GeneradorFalso()
    ref.ciclo(JORNADA, generar=g)
    ref.ciclo(JORNADA, generar=g)

    mapa = _mapa()
    entrada = mapa[clave]
    assert entrada["puntos_clave"] == ["ortografia vieja"]
    assert entrada["mio"] == "esto lo escribi yo"
    assert "lo de siempre" in entrada["claves"]     # lo previo, delante
    assert len(entrada["claves"]) > 1               # y lo nuevo, detras
    assert mapa["otra-jornada@0"] == {"claves": ["de otra sesion"]}


def test_lo_marcado_importante_se_ve_ya_en_caliente():
    """La garantia dura de apuntes.py no espera al cierre: es deterministica y
    gratis, asi que se aplica en cada vuelta."""
    _grabar()
    alm.apendar(alm.dir_jornada(JORNADA) / alm.ENTRADAS,
                {"t": 30.0, "tipo": cua.TIPO_NOTA, "fuente": "usuario",
                 "texto": "OJO: esto lo pregunta seguro", "importante": True})
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    entrada = _mapa()[_clave()]
    assert "OJO: esto lo pregunta seguro" in entrada["claves"] + entrada["examen"]


# ── El modelo caido ──────────────────────────────────────────────────────────

def test_con_el_modelo_caido_no_se_pierde_nada_y_queda_el_aviso():
    texto = _grabar()
    mudo = GeneradorFalso(mudo=True)
    res = ref.ciclo(JORNADA, generar=mudo)

    assert res["estado"] == "sin-modelo"
    assert res["llamadas"] == 2 and res["mudas"] == 2
    # La marca NO avanza: ese tramo se vuelve a pedir cuando el modelo vuelva.
    assert _mapa().get(_clave(), {}).get("chars_entrada", 0) == 0
    assert any("no esta arriba" in a or "no emitio" in a for a in res["avisos"])
    assert ref.estado(JORNADA)["jornadas"][JORNADA]["avisos"]

    # Y cuando vuelve, se procesa desde el principio del tramo pendiente.
    bueno = GeneradorFalso()
    ref.ciclo(JORNADA, generar=bueno)
    assert bueno.partes()[0] == 1
    assert 0 < _mapa()[_clave()]["chars_entrada"] <= len(texto)


def test_un_aviso_no_crea_entrada_en_apuntes_json():
    """Si esto se rompe, `olvido` comprime la transcripcion de una clase que
    NO tiene apuntes: una entrada con solo un aviso es truthy y
    `olvido._hay_apuntes` cuenta cualquier valor truthy."""
    _grabar()
    ref.ciclo(JORNADA, generar=GeneradorFalso(mudo=True))
    assert _clave() not in _mapa()
    assert olv._hay_apuntes(JORNADA) is False


def test_con_apuntes_previos_el_aviso_si_queda_en_el_campo_aviso():
    _grabar()
    clave = _clave()
    alm.guardar_json(alm.dir_jornada(JORNADA) / alm.APUNTES,
                     {clave: {"claves": ["algo de la primera media hora"],
                              "chars_entrada": 10}})
    ref.ciclo(JORNADA, generar=GeneradorFalso(mudo=True))
    entrada = _mapa()[clave]
    assert "no esta arriba" in entrada["aviso"] or "no emitio" in entrada["aviso"]
    assert entrada["claves"] == ["algo de la primera media hora"]
    assert entrada["chars_entrada"] == 10          # la marca sigue donde estaba


def test_un_modelo_que_no_rinde_no_se_cuenta_como_un_modelo_mudo(monkeypatch):
    """MEDIDO el 2026-08-31: el 8080 de esta maquina contesta /health y luego
    se come el timeout entero. "No emitio nada util" y "tarda mas de lo que un
    trabajo de fondo puede esperar" se arreglan de forma distinta, asi que el
    aviso tiene que distinguirlos."""
    monkeypatch.setattr(ref, "TIMEOUT_VENTANA", 0)   # toda llamada es "lenta"
    _grabar()
    res = ref.ciclo(JORNADA, generar=GeneradorFalso(mudo=True))
    assert res["lentas"] == res["llamadas"] == 2
    assert any("no rinde" in a for a in res["avisos"])


# ── El disyuntor ─────────────────────────────────────────────────────────────

def test_el_disyuntor_apaga_el_refinado_tras_dos_vueltas_esteriles():
    """Regla 11 de CLAUDE.md: al segundo intento esteril, parar. Aqui el
    'intento' es una vuelta que llamo al modelo y no saco nada."""
    _grabar()
    mudo = GeneradorFalso(mudo=True)
    primera = ref.ciclo(JORNADA, generar=mudo)
    assert primera["apagado"] == ""

    segunda = ref.ciclo(JORNADA, generar=mudo)
    assert "APAGADO" in segunda["apagado"]
    assert ref.SUBCOMANDO_CLI in segunda["apagado"]

    # Y a partir de ahi no se vuelve a llamar al modelo en esa jornada.
    llamadas = len(mudo.prompts)
    tercera = ref.ciclo(JORNADA, generar=mudo)
    assert tercera["estado"] == "apagado"
    assert len(mudo.prompts) == llamadas
    assert ref.estado(JORNADA)["jornadas"][JORNADA]["apagado"]


def test_forzar_no_reabre_lo_que_apago_el_disyuntor_pero_encender_si():
    """Un 'forzar' automatico que saltara el disyuntor lo dejaria muerto. La
    unica vuelta atras es la intervencion humana (`/grabar-clase refinado on`)."""
    _grabar()
    mudo = GeneradorFalso(mudo=True)
    ref.ciclo(JORNADA, generar=mudo)
    ref.ciclo(JORNADA, generar=mudo)
    assert ref.tick(JORNADA, generar=mudo, forzar=True)["estado"] == "apagado"

    ref.encender(JORNADA)
    res = ref.tick(JORNADA, generar=GeneradorFalso(), forzar=True)
    assert res["estado"] == "refinado"


# ── El volcado a bloques ─────────────────────────────────────────────────────

def test_el_volcado_a_bloques_respeta_lo_fijado():
    _grabar(materia="Fisica")
    clave = _clave()
    res = ref.ciclo(JORNADA, generar=GeneradorFalso())
    assert res["documento"][clave]["creados"]

    # El duenio corrige el bloque de las claves y lo fija.
    bloque = [b for b in doc.abrir("Fisica").bloques
              if b.meta.get(doc.CLAVE_REF) == "%s#claves" % clave][0]
    doc.editar("Fisica", bloque.id, texto="- lo escribi yo a mano")
    doc.fijar("Fisica", bloque.id, True)

    res2 = ref.ciclo(JORNADA, generar=GeneradorFalso())
    assert bloque.id in res2["documento"][clave]["respetados"]
    otra_vez = [b for b in doc.abrir("Fisica").bloques if b.id == bloque.id][0]
    assert otra_vez.texto == "- lo escribi yo a mano"


def test_no_se_vuelca_mientras_la_materia_es_sin_clasificar():
    """Volcar a 'Sin clasificar' deja bloques huerfanos en un documento que
    nadie abre; en cuanto la deteccion pone nombre, sube todo de golpe (el
    volcado es idempotente por ref)."""
    _grabar(materia="")
    res = ref.ciclo(JORNADA, generar=GeneradorFalso())
    assert res["estado"] == "refinado"
    assert res["documento"] == {}
    assert doc.documentos() == []


# ── El cierre: la cola que nadie mas va a procesar ───────────────────────────

def test_lo_que_queda_por_refinar_se_DICE_en_el_aviso():
    """`apuntes.generar` devuelve unos apuntes ya escritos tal cual, asi que
    la cola que el refinado no proceso no la procesa nadie al cerrar. Eso
    tiene que leerse en la hoja, no descubrirse echando de menos el ultimo
    cuarto de hora."""
    texto = _grabar()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    entrada = _mapa()[_clave()]
    assert entrada["chars_entrada"] < len(texto)
    assert "quedan" in entrada["aviso"] and "por refinar" in entrada["aviso"]


def test_cerrar_vacia_la_cola_que_el_ritmo_normal_deja_fuera():
    """La cola tipica del cierre son los ultimos minutos de clase: MENOS de
    MIN_TRAMO_CHARS, o sea justo lo que una vuelta normal se salta a proposito
    porque habria otra vuelta detras. Al cerrar ya no la hay."""
    _grabar(partes=20)
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    alm.apendar(alm.dir_jornada(JORNADA) / alm.TRANSCRIPCION,
                {"t": 9000.0, "tipo": cua.TIPO_TRANSCRIPCION, "t_fin": 9010.0,
                 "texto": "Parte numero 99: y con esto cerramos el tema de "
                          "hoy, la semana que viene traed la calculadora."})
    texto = cua.sesiones_de(JORNADA)[0].texto_dicho()
    cola = len(texto) - _mapa()[_clave()]["chars_entrada"]
    assert ref.MIN_TRAMO_CIERRE < cola < ref.MIN_TRAMO_CHARS

    # El ritmo normal la deja fuera (habria otra vuelta detras)...
    assert ref.ciclo(JORNADA, generar=GeneradorFalso())["estado"] == "sin-tramo"
    # ...y el cierre la recoge.
    g = GeneradorFalso()
    res = ref.cerrar(JORNADA, generar=g)
    assert res["estado"] == "cerrado"
    assert 99 in g.partes()
    entrada = _mapa()[_clave()]
    assert entrada["chars_entrada"] == len(texto)
    assert res["llamadas"] <= ref.MAX_VUELTAS_CIERRE * ref.MAX_VENTANAS_VUELTA
    assert len(entrada["claves"]) > 1


def test_cerrar_no_reabre_lo_que_apago_el_disyuntor():
    """Vaciar la cola no puede ser la puerta de atras del disyuntor: seria un
    reintento automatico disfrazado, que es lo que prohibe la regla 11."""
    _grabar()
    mudo = GeneradorFalso(mudo=True)
    ref.ciclo(JORNADA, generar=mudo)
    ref.ciclo(JORNADA, generar=mudo)
    antes = len(mudo.prompts)
    res = ref.cerrar(JORNADA, generar=mudo)
    assert res["estado"] == "apagado"
    assert len(mudo.prompts) == antes


# ── El backend: por llm_local, con re-sondeo, y sin llenar el log ────────────

def test_habla_por_llm_local_y_nunca_por_orch_infer(monkeypatch):
    vistos = {}

    def _fake_generar(prompt, **kw):
        vistos.update(kw)
        return "CLAVE: lo que dijo el modelo de verdad"

    monkeypatch.setattr(llm, "_backend", {"tipo": "llama", "url": "http://x"})
    monkeypatch.setattr(llm, "generar", _fake_generar)
    assert ref._generar_por_llm("hola").startswith("CLAVE:")
    assert vistos["via"] == ref.VIA_LLM == "clases.refinado"
    assert vistos["max_tokens"] == ap._TOK_VENTANA
    # Y con el techo de espera del refinado, no con los 120 s del chat: aqui
    # el que espera es el hilo vigia, que ademas tiene que detectar materias.
    assert vistos["timeout"] == ref.TIMEOUT_VENTANA < llm.TIMEOUT_GEN


def test_sin_backend_no_se_llama_al_modelo_ni_se_llena_el_log(monkeypatch):
    """`llm_local.generar` sin backend escribe en backend_audit.jsonl y grita
    por stderr en CADA llamada. Con dos ventanas cada cinco minutos eso son
    cientos de gritos por una sola noticia."""
    llamadas = []
    gritos = []
    monkeypatch.setattr(llm, "generar",
                        lambda *a, **k: llamadas.append(1))
    from cognia import backend_activo
    monkeypatch.setattr(backend_activo, "sin_backend",
                        lambda via, detalle="": gritos.append(via))

    assert ref._generar_por_llm("hola") == ""
    assert ref._generar_por_llm("hola otra vez") == ""
    assert llamadas == []
    assert gritos == [ref.VIA_LLM]          # se anota UNA vez, no dos


def test_se_fuerza_el_resondeo_cada_cuatro_vueltas(monkeypatch):
    """`llm_local._backend` es cache pegajosa de proceso: sin esto, un widget
    que arranco con la flota apagada no se entera nunca de que el duenio la
    levanto."""
    forzados = []
    monkeypatch.setattr(llm, "detectar_backend",
                        lambda forzar=False: forzados.append(forzar) or None)
    for _ in range(ref.CADA_CUANTAS_VUELTAS_RESONDEO * 2):
        ref._resondear_si_toca()
    assert forzados == [True, True]         # la vuelta 0 y la 4


def test_el_ciclo_de_verdad_resondea(monkeypatch):
    """El re-sondeo va en el ciclo REAL (con el generador propio), no solo en
    la funcion suelta."""
    _grabar()
    forzados = []
    monkeypatch.setattr(llm, "detectar_backend",
                        lambda forzar=False: forzados.append(forzar) or None)
    res = ref.ciclo(JORNADA)
    assert True in forzados
    assert res["estado"] == "sin-modelo"    # no hay backend: degrada limpio


# ── Config y puerta de diagnostico ───────────────────────────────────────────

def test_config_on_off_y_periodo(monkeypatch):
    assert ref.activo() is True             # default sensato: encendido
    assert ref.periodo() == ref.PERIODO_DEFECTO
    monkeypatch.setenv(ref.ENV_ACTIVO, "off")
    assert ref.activo() is False
    monkeypatch.setenv(ref.ENV_ACTIVO, "1")
    assert ref.activo() is True
    monkeypatch.setenv(ref.ENV_PERIODO, "600")
    assert ref.periodo() == 600.0
    # Un valor absurdo no puede dejar el subsistema mudo NI hacerlo girar sin
    # freno: se acota y se DICE.
    monkeypatch.setenv(ref.ENV_PERIODO, "0")
    assert ref.periodo() == ref.PERIODO_MINIMO
    assert "por debajo del minimo" in ref.ultimo_fallo()["motivo"]
    monkeypatch.setenv(ref.ENV_ACTIVO, "quiza")
    assert ref.activo() is True
    assert "no es un si/no" in ref.ultimo_fallo()["motivo"]


def test_tick_respeta_el_periodo_y_el_interruptor(monkeypatch):
    _grabar()
    g = GeneradorFalso()
    assert ref.tick(JORNADA, generar=g, ahora=1000.0)["estado"] == "refinado"
    # Antes de que pase el periodo no se vuelve a llamar al modelo.
    assert ref.tick(JORNADA, generar=g, ahora=1010.0)["estado"] == "todavia-no"
    assert ref.tick(JORNADA, generar=g,
                    ahora=1000.0 + ref.PERIODO_DEFECTO)["estado"] == "refinado"
    monkeypatch.setenv(ref.ENV_ACTIVO, "0")
    assert ref.tick(JORNADA, generar=g, ahora=9000.0)["estado"] == "off"
    # Apagado por config, 'ahora' del duenio sigue funcionando.
    assert ref.tick(JORNADA, generar=g, ahora=9000.0,
                    forzar=True)["estado"] in ("refinado", "sin-tramo")


def test_estado_es_la_puerta_de_diagnostico():
    _grabar()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    st = ref.estado(JORNADA)
    assert st["activo"] is True
    assert st["periodo"] == ref.PERIODO_DEFECTO
    assert st["subcomando"] == "/grabar-clase refinado"
    assert st["env"] == {"activo": ref.ENV_ACTIVO, "periodo": ref.ENV_PERIODO}
    assert st["backend"] == "ninguno (sin LLM local)"
    j = st["jornadas"][JORNADA]
    assert j["vueltas"] == 1 and j["llamadas"] == 2 and j["aniadidos"] > 0
    assert j["apagado"] == ""


# ── El enganche en el vigia de la jornada ────────────────────────────────────

class GrabadorFalso:
    """Lo minimo que el vigia le pide al grabador: el reloj."""

    def __init__(self):
        self._t = 12.5
        self.cola = None
        self.avisos: list = []
        self.mudo = False
        self.parado = False

    def parar(self) -> None:
        """`JornadaViva.parar()` lo llama antes de cerrar. Aqui no hay
        dispositivo que cerrar, pero se deja constancia para que un test pueda
        comprobar que el cierre llego a pasar por el grabador."""
        self.parado = True


def test_el_vigia_llama_al_refinado_en_cada_vuelta(monkeypatch):
    monkeypatch.setattr(jor, "PERIODO_DETECCION", 0.01)
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    vueltas = []
    monkeypatch.setattr(jv, "_refinar_en_caliente", lambda: vueltas.append(1))
    hilo = threading.Thread(target=jv._bucle_vigia, daemon=True)
    hilo.start()
    limite = time.time() + 5.0
    while not vueltas and time.time() < limite:
        time.sleep(0.01)
    jv._parar.set()
    hilo.join(timeout=5.0)
    assert vueltas, "el vigia no llamo al refinado"


def test_los_avisos_del_refinado_suben_a_la_jornada_y_no_se_repiten():
    """El vigia corre cada 90 s: si el mismo 'el modelo no esta arriba' subiera
    en cada vuelta, en una manana enterraria cualquier otro aviso."""
    _grabar()
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    jv._refinar_en_caliente()
    assert any("no esta arriba" in a or "no emitio" in a for a in jv.avisos)
    cuantos = len(jv.avisos)
    ref.encender(JORNADA)                   # deshace el apagado del disyuntor
    jv._refinar_en_caliente()
    assert len(jv.avisos) == cuantos


def test_el_vigia_sobrevive_a_un_refinado_que_revienta(monkeypatch):
    """Resistencia: perder los apuntes en caliente es molesto, perder la clase
    es irreparable."""
    monkeypatch.setattr(ref, "tick",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    jv._refinar_en_caliente()               # no levanta
    assert any("boom" in a for a in jv.avisos)


# ── El troceo del tramo ──────────────────────────────────────────────────────

def test_el_lote_dice_exactamente_cuanto_avanza_la_marca():
    """Si el avance no coincidiera con lo procesado se perderia texto en
    silencio (avanzando de mas) o se pagaria dos veces (avanzando de menos)."""
    tramo = "  " + " ".join("palabra%04d" % i for i in range(2000))
    ventanas, avance = ref._lote_de_vuelta(tramo, 2)
    assert len(ventanas) == 2
    # Lo procesado empieza donde empieza el tramo y termina en el avance.
    assert tramo[:avance].strip().endswith(ventanas[-1][-20:])
    assert ventanas[0] in tramo[:avance]
    assert avance < len(tramo)              # queda cola para la vuelta siguiente


def test_un_tramo_corto_no_molesta_al_modelo():
    """400 chars son ~30 s de habla: pagar 13 s de razonamiento por frase y
    media es peor negocio que esperar a la vuelta siguiente."""
    d = alm.dir_jornada(JORNADA)
    alm.apendar(d / alm.TRANSCRIPCION,
                {"t": 0.0, "tipo": cua.TIPO_TRANSCRIPCION, "t_fin": 5.0,
                 "texto": "bueno, vamos a empezar la clase de hoy"})
    g = GeneradorFalso()
    res = ref.ciclo(JORNADA, generar=g)
    assert res["estado"] == "sin-tramo"
    assert g.prompts == []


def test_el_tope_del_acumulado_no_borra_lo_que_ya_habia(monkeypatch):
    """El tope existe para que apuntes.json no crezca sin fin, no para tirar
    lo que ya esta escrito."""
    monkeypatch.setattr(ref, "MAX_ACUMULADO", 2)
    _grabar()
    clave = _clave()
    alm.guardar_json(alm.dir_jornada(JORNADA) / alm.APUNTES,
                     {clave: {"claves": ["una", "dos"], "chars_entrada": 0}})
    res = ref.ciclo(JORNADA, generar=GeneradorFalso())
    entrada = _mapa()[clave]
    assert entrada["claves"] == ["una", "dos"]
    assert any("tope" in a for a in res["avisos"])


def test_el_fichero_queda_json_valido_y_legible_por_el_cuaderno():
    """Verificacion de punta a punta: lo que escribe el refinado tiene que
    volver por la puerta de lectura normal del cuaderno."""
    _grabar()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    crudo = (alm.dir_jornada(JORNADA) / alm.APUNTES).read_text(encoding="utf-8")
    json.loads(crudo)
    sesion = cua.sesiones_de(JORNADA)[0]
    assert sesion.apuntes["via"] == ref.VIA_REFINADO
    assert sesion.apuntes["claves"]
    assert sesion.apuntes["titulo"].startswith("Fisica")
    assert sesion.apuntes["resumen"]
    assert sesion.apuntes["chars_salida"] > 0


# ── GRAVE 1: el enganche del cierre (jornada.parar) ──────────────────────────

def test_parar_vacia_la_cola_del_refinado_antes_de_generar_apuntes(monkeypatch):
    """SIN ESTE ENGANCHE EL ULTIMO TRAMO DE CLASE NO LO REFINA NADIE.

    `apuntes.generar` devuelve tal cual unos apuntes que ya existen, asi que
    en cuanto el refinado escribio la primera entrada, `generar_apuntes()` ya
    no vuelve a mirar esa sesion. La cola que el refinado deje pendiente al
    sonar el timbre se pierde para siempre si `parar()` no llama a `cerrar()`.
    """
    texto = _grabar(partes=30)      # mas clase de la que cabe en una vuelta
    g = GeneradorFalso()
    # El refinado del cierre usa su propia puerta al modelo (no recibe
    # `generar`): se sustituye la puerta, que es lo que hace la maquina real.
    monkeypatch.setattr(ref, "_generar_por_llm", g)

    ref.ciclo(JORNADA, generar=g)                   # el ritmo normal deja cola
    marca = _mapa()[_clave()]["chars_entrada"]
    assert marca < len(texto), "el ciclo ya proceso la clase entera"

    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    res = jv.parar()

    assert res["refinado"]["estado"] in ("cerrado", "refinado")
    entrada = _mapa()[_clave()]
    assert entrada["chars_entrada"] > marca, \
        "parar() no vacio la cola: el final de la clase se quedo sin refinar"
    assert ref.cobertura(JORNADA)["completo"] is True
    # Y el modelo vio de verdad el ultimo trozo de la clase.
    assert 30 in g.partes()


def test_parar_refina_ANTES_de_generar_apuntes(monkeypatch):
    """El orden importa tanto como el enganche: si `cerrar()` corriera
    DESPUES, `generar_apuntes` ya habria devuelto los apuntes a medias como
    definitivos."""
    _grabar(partes=20)
    orden = []
    monkeypatch.setattr(ref, "cerrar",
                        lambda *a, **k: orden.append("refinado") or {})
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    monkeypatch.setattr(jv, "generar_apuntes",
                        lambda: orden.append("apuntes") or {})
    jv.parar()
    assert orden == ["refinado", "apuntes"], orden


def test_el_cierre_sobrevive_a_un_refinado_que_revienta(monkeypatch):
    """Misma resistencia que el vigia: perder el ultimo tramo es molesto,
    perder el cierre de la jornada (y el lock) es peor."""
    _grabar(partes=5)
    monkeypatch.setattr(ref, "cerrar",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    jv = jor.JornadaViva(JORNADA, grabador=GrabadorFalso())
    res = jv.parar()                                # no levanta
    assert res["refinado"] == {}
    assert any("boom" in a for a in jv.avisos)


# ── GRAVE 2: el aviso del apagado ni miente ni pisa al veraz ─────────────────

def test_el_aviso_del_apagado_no_miente_y_no_pisa_al_veraz():
    """El campo 'aviso' es la UNICA ventana del duenio a por que no hay
    apuntes. Decia dos cosas falsas ("nada se ha perdido", "los apuntes se
    generan al cerrar" -- que es justo lo que NO pasa cuando ya hay una
    entrada escrita) y ademas machacaba el aviso que si decia la verdad: el
    que pone cuantos chars quedan por refinar."""
    _grabar()
    clave = _clave()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    veraz = _mapa()[clave]["aviso"]
    assert "quedan" in veraz and "por refinar" in veraz

    mudo = GeneradorFalso(mudo=True)
    res = {}
    for _ in range(4):
        res = ref.ciclo(JORNADA, generar=mudo)
        if res.get("apagado"):
            break
    assert res["apagado"], "el disyuntor no llego a apagar"

    aviso = _mapa()[clave]["aviso"]
    assert "APAGADO" in aviso
    assert veraz in aviso, \
        "el aviso del apagado borro la cifra de lo que queda: %r" % aviso
    # Y no repite las dos mentiras.
    assert "Nada se ha perdido" not in aviso
    assert "los apuntes se generan al cerrar" not in aviso
    assert "NO lo recoge el cierre" in aviso
    assert ref.SUBCOMANDO_CLI in aviso              # la salida, dicha


def test_el_aviso_no_crece_sin_fin_repitiendo_lo_mismo():
    """Se concatena, asi que hay que comprobar que el mismo texto no entra dos
    veces: el vigia corre cada 90 s y el campo lo pinta la vista."""
    _grabar()
    clave = _clave()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    mudo = GeneradorFalso(mudo=True)
    ref.ciclo(JORNADA, generar=mudo)
    uno = _mapa()[clave]["aviso"]
    ref.encender(JORNADA)                           # deshace el apagado si hubo
    ref.ciclo(JORNADA, generar=mudo)
    dos = _mapa()[clave]["aviso"]
    assert dos == uno, "el mismo aviso se pego dos veces: %r" % dos


# ── GRAVE 3: unos apuntes a medias no dejan comprimir la fuente ──────────────

def test_apuntes_a_medias_no_dejan_comprimir_la_transcripcion():
    """LA PERDIDA DE DATOS. El refinado escribe apuntes del principio de la
    clase; `olvido._hay_apuntes` ve "ya hay apuntes" y comprime la
    transcripcion literal a un 30% muestreado. La fuente del tramo que NADIE
    resumio desaparece, y compactar no es reversible."""
    texto = _grabar()
    ref.ciclo(JORNADA, generar=GeneradorFalso())    # solo el principio
    entrada = _mapa()[_clave()]
    assert entrada["chars_entrada"] < len(texto)
    assert olv._hay_apuntes(JORNADA) is True        # el sintoma que enganiaba

    ahora = _muy_tarde()
    filas = _filas_transcripcion(ahora)
    assert filas and all(f["accion"] == olv.ACCION_NADA for f in filas), \
        "el olvido pensaba comprimir una clase resumida a medias: %s" % filas
    assert any("SIN resumir" in f["por_que"] for f in filas)

    olv.aplicar(ahora=ahora)                        # la pasada de verdad
    regs = _regs()
    assert not any(r.get("compactado") for r in regs)
    entero = " ".join(str(r.get("texto") or "") for r in regs)
    assert "Parte numero 80" in entero, \
        "se perdio la fuente del tramo que nadie resumio"
    assert len(regs) == 80


def test_con_el_refinado_terminado_la_transcripcion_si_se_compacta():
    """El control positivo: la proteccion no puede ser "no compactar nunca".
    En cuanto la cobertura es total (lo que deja `cerrar()`), el olvido hace
    su trabajo."""
    _grabar(partes=12)
    ref.cerrar(JORNADA, generar=GeneradorFalso())
    info = ref.cobertura(JORNADA)
    assert info["toco_el_refinado"] is True and info["completo"] is True

    ahora = _muy_tarde()
    assert [f["accion"] for f in _filas_transcripcion(ahora)] \
        == [olv.ACCION_COMPACTAR]
    olv.aplicar(ahora=ahora)
    assert all(r.get("compactado") for r in _regs())


def test_la_cobertura_no_juzga_unos_apuntes_que_no_escribio_el_refinado():
    """Esta pieza solo puede juzgar lo suyo: unos apuntes de otra version (sin
    marca de agua) tienen que seguir compactandose como siempre, o la
    proteccion nueva congelaria el olvido de todo el curso anterior."""
    _grabar()
    alm.guardar_json(alm.dir_jornada(JORNADA) / alm.APUNTES,
                     {_clave(): {"titulo": "Cinematica", "claves": ["v = d/t"]}})
    info = ref.cobertura(JORNADA)
    assert info["toco_el_refinado"] is False
    assert olv._sin_refinar(JORNADA) == ""
    assert [f["accion"] for f in _filas_transcripcion(_muy_tarde())] \
        == [olv.ACCION_COMPACTAR]


def test_una_sesion_sin_apuntes_tambien_protege_la_transcripcion():
    """El mismo agujero por la otra puerta: `_hay_apuntes` mira la jornada
    ENTERA con un `any()`, asi que una jornada de dos clases con apuntes de la
    primera y nada de la segunda tambien se comprimia."""
    _grabar()
    alm.apendar(alm.dir_jornada(JORNADA) / alm.CORTES,
                {"t": 800.0, "materia": "Latin", "confianza": 1.0,
                 "por": "manual"})
    sesiones = cua.sesiones_de(JORNADA)
    assert len(sesiones) == 2
    claves = ap.claves_de_jornada(JORNADA, sesiones)[0]
    # La primera clase, refinada entera; la segunda, sin tocar.
    alm.guardar_json(alm.dir_jornada(JORNADA) / alm.APUNTES,
                     {claves[0]: {"claves": ["lo de Fisica"],
                                  "via": ref.VIA_REFINADO,
                                  "chars_entrada": len(sesiones[0].texto_dicho())}})
    info = ref.cobertura(JORNADA)
    assert info["completo"] is False and info["pendiente"] > 0
    assert "SIN resumir" in olv._sin_refinar(JORNADA)


def test_si_la_cobertura_revienta_no_se_comprime(monkeypatch):
    """Lo que no se puede verificar no se destruye. Y se dice: un olvido que
    deja de compactar en silencio es el mismo vacio mudo de siempre."""
    _grabar()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    monkeypatch.setattr(ref, "cobertura",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disco")))
    motivo = olv._sin_refinar(JORNADA)
    assert "no se pudo comprobar" in motivo and "disco" in motivo
    assert [f["accion"] for f in _filas_transcripcion(_muy_tarde())] \
        == [olv.ACCION_NADA]


def test_una_marca_de_agua_corrupta_protege_en_vez_de_arriesgar():
    _grabar()
    alm.guardar_json(alm.dir_jornada(JORNADA) / alm.APUNTES,
                     {_clave(): {"claves": ["algo"], "via": ref.VIA_REFINADO,
                                 "chars_entrada": "no soy un numero"}})
    info = ref.cobertura(JORNADA)
    assert info["completo"] is False
    assert "chars_entrada" in ref.ultimo_fallo()["motivo"]


# ── GRAVE 4: encender() es la unica salida, y funciona ───────────────────────

def test_encender_es_la_unica_salida_de_un_refinado_apagado():
    """Sin esta funcion (o sin la linea que la cablea en el CLI), un refinado
    que el disyuntor apago a las 9:10 sigue apagado el resto del dia y el
    duenio no tiene ninguna tecla que lo devuelva."""
    _grabar()
    mudo = GeneradorFalso(mudo=True)
    ref.ciclo(JORNADA, generar=mudo)
    ref.ciclo(JORNADA, generar=mudo)
    assert ref.estado(JORNADA)["jornadas"][JORNADA]["apagado"]

    res = ref.encender(JORNADA)
    assert res["encendido"] is True
    assert "APAGADO" in res["venia_apagado"]
    j = ref.estado(JORNADA)["jornadas"][JORNADA]
    assert j["apagado"] == ""
    assert j["esteriles"] == 0, "la ventana del disyuntor no se reseteo"

    # Y VUELVE A TRABAJAR de verdad: que el flag quede a '' no basta.
    g = GeneradorFalso()
    assert ref.ciclo(JORNADA, generar=g)["estado"] == "refinado"
    assert g.prompts

    # Encender no desarma el disyuntor para siempre: si el modelo sigue
    # caido, vuelve a apagar.
    ref.ciclo(JORNADA, generar=mudo)
    ref.ciclo(JORNADA, generar=mudo)
    assert ref.estado(JORNADA)["jornadas"][JORNADA]["apagado"]


def test_encender_una_jornada_que_no_estaba_apagada_no_rompe_nada():
    _grabar()
    res = ref.encender(JORNADA)
    assert res["venia_apagado"] == ""
    assert ref.ciclo(JORNADA, generar=GeneradorFalso())["estado"] == "refinado"


# ── Promesas del contrato que no tenian test que las discriminara ────────────

def test_el_titulo_y_el_resumen_del_duenio_no_se_pisan():
    """La pieza corre cada 5 minutos sobre el mismo fichero: si pisara lo que
    el duenio corrigio, corregir seria inutil."""
    _grabar()
    clave = _clave()
    alm.guardar_json(alm.dir_jornada(JORNADA) / alm.APUNTES,
                     {clave: {"titulo": "Cinematica: cae en el examen",
                              "resumen": "esto lo escribi yo a mano",
                              "claves": ["algo"], "chars_entrada": 0}})
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    entrada = _mapa()[clave]
    assert entrada["titulo"] == "Cinematica: cae en el examen"
    assert entrada["resumen"] == "esto lo escribi yo a mano"


def test_el_resumen_QUE_ESCRIBIMOS_NOSOTROS_si_se_refresca():
    """La otra mitad de la promesa: un resumen de los primeros 90 s congelado
    toda la clase no sirve de nada. Solo se rehace el que dejamos nosotros la
    vuelta anterior, que es lo que distingue los dos casos sin adivinar."""
    _grabar(partes=10)
    clave = _clave()
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    uno = _mapa()[clave]["resumen"]
    assert uno
    # La clase SIGUE: entra materia nueva y el resumen tiene que moverse con
    # ella (por eso hay que anadir transcripcion, no repetir la vuelta).
    alm.apendar(alm.dir_jornada(JORNADA) / alm.TRANSCRIPCION,
                {"t": 9000.0, "tipo": cua.TIPO_TRANSCRIPCION, "t_fin": 9010.0,
                 "texto": "Parte numero 99: y ahora la ley de Ohm dice que la "
                          "tension es la corriente por la resistencia. " * 12})
    ref.ciclo(JORNADA, generar=GeneradorFalso())
    dos = _mapa()[clave]["resumen"]
    assert dos and dos != uno, "el resumen se quedo congelado en el principio"


def test_cerrar_no_gira_mas_de_MAX_VUELTAS_CIERRE_veces(monkeypatch):
    """El tope existe para que vaciar la cola nunca cueste MAS que haber
    generado la sesion de una vez (apuntes._MAX_VENTANAS = 12 llamadas). Sin
    el, una clase de 45 000 chars pediria vueltas hasta acabarla."""
    monkeypatch.setattr(ref, "MAX_VUELTAS_CIERRE", 2)
    texto = _grabar(partes=200)
    g = GeneradorFalso()
    res = ref.cerrar(JORNADA, generar=g)
    assert res["llamadas"] == 2 * ref.MAX_VENTANAS_VUELTA
    # Y lo que no cupo NO se da por procesado: la marca se queda donde toca.
    assert _mapa()[_clave()]["chars_entrada"] < len(texto)


def test_una_vuelta_sin_tramo_nuevo_no_paga_el_sondeo(monkeypatch):
    """El sondeo forzado cuesta hasta 2 s por backend candidato (~4 s de hilo
    vigia bloqueado). En una jornada sin tramo nuevo -- la recien abierta, y
    la que ya se cerro -- no hay a quien preguntarle nada, y ese tiempo es el
    que el vigia no dedica a detectar materias."""
    sondeos = []
    monkeypatch.setattr(llm, "detectar_backend",
                        lambda forzar=False: sondeos.append(forzar) or None)
    assert ref.ciclo(JORNADA)["estado"] == "sin-tramo"
    assert sondeos == []
    # Y en cuanto hay tramo, se sondea antes de llamar (la decision 2).
    _grabar(partes=5)
    assert ref.ciclo(JORNADA)["estado"] == "sin-modelo"
    assert True in sondeos
