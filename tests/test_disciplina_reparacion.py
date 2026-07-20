"""
Tests for the repair circuit breaker (cognia/disciplina/) and its wiring into
the tool-synthesis self-repair loop.

Fija el caso real que lo motivo: el 2026-07-19, arreglar el ranking de
relevancia de este repo costo CUATRO intentos; los tres primeros fueron
parches sobre el sintoma. El disyuntor tiene que cortar en el segundo.

Offline: no network, no LLM.
"""

import types

import pytest

from cognia.agent import tool_synthesis as TS
from cognia.disciplina import (
    Disyuntor,
    HUELLA_REPETIDA_CORTA,
    huella_de_texto,
    normalizar,
)

TRACEBACK = '''Traceback (most recent call last):
  File "C:\\Users\\usuario\\Desktop\\cognia_v2\\cognia\\x.py", line 42, in run
    valor = calcular(entrada)
AssertionError: se esperaba 3 pero llego 7
'''


# ── Normalizacion ───────────────────────────────────────────────────────

def test_normalizar_borra_lo_que_cambia_entre_corridas():
    a = normalizar("objeto en 0xdeadbeef a las 2026-07-19T10:00:00 en line 42")
    b = normalizar("objeto en 0x00ff11 a las 2026-07-19T23:59:59 en line 907")
    assert a == b, "direcciones, timestamps y numeros de linea no deben diferenciar"


def test_normalizar_conserva_el_mensaje_real():
    assert "se esperaba" in normalizar("AssertionError: se esperaba 3")


def test_misma_falla_distinta_corrida_es_la_misma_huella():
    """
    Si esto falla, el disyuntor queda MUERTO en silencio: cada intento
    parece un sintoma nuevo y nunca dispara.
    """
    otro = TRACEBACK.replace("line 42", "line 55").replace("0x", "0x")
    assert huella_de_texto(TRACEBACK).clave() == huella_de_texto(otro).clave()


def test_fallas_distintas_son_huellas_distintas():
    a = huella_de_texto(TRACEBACK)
    b = huella_de_texto("ZeroDivisionError: division by zero")
    assert a.clave() != b.clave()


def test_huella_extrae_tipo_y_marcos():
    h = huella_de_texto(TRACEBACK)
    assert h.tipo == "AssertionError"
    assert h.marcos == (("x.py", "run"),)


def test_archivo_temporal_aleatorio_no_cambia_la_huella():
    """
    Regresion medida: el sandbox ejecuta el codigo generado en un temporal de
    nombre aleatorio. Con el nombre crudo en los marcos, dos fallos IDENTICOS
    daban huellas distintas y el disyuntor no disparaba NUNCA. Un mecanismo de
    seguridad muerto en silencio es peor que no tenerlo.
    """
    import tempfile
    tmp = tempfile.gettempdir()
    plantilla = ('error de ejecucion: Traceback (most recent call last):\n'
                 '  File "{ruta}", line 16, in <module>\n'
                 '    print(run(\'x\'))\n')
    a = huella_de_texto(plantilla.format(ruta=f"{tmp}\\cognia_prog_uqu_v78_.py"))
    b = huella_de_texto(plantilla.format(ruta=f"{tmp}\\cognia_prog_nqhqvbmk.py"))
    assert a.clave() == b.clave()
    assert a.marcos == (("<temp>", "<module>"),)


def test_archivos_distintos_del_repo_si_se_distinguen():
    """Normalizar los temporales no debe borrar la discriminacion util."""
    plantilla = ('Traceback (most recent call last):\n'
                 '  File "C:\\\\repo\\\\cognia\\\\{arch}", line 3, in run\n'
                 'ValueError: x\n')
    a = huella_de_texto(plantilla.format(arch="alfa.py"))
    b = huella_de_texto(plantilla.format(arch="beta.py"))
    assert a.marcos != b.marcos


def test_huella_de_texto_sin_traceback_igual_sirve():
    h = huella_de_texto("verificacion fallo: falta import re")
    assert h.clave()
    assert "import re" in h.mensaje


# ── Condiciones de disparo ──────────────────────────────────────────────

def _fallar(d, texto, veces=1, hubo_cambio=True):
    for _ in range(veces):
        d.registrar(huella_de_texto(texto), ok=False, hubo_cambio=hubo_cambio)


def test_d6_corta_cuando_el_sintoma_no_se_mueve():
    """El corazon del disyuntor: escribiste dos veces y el sintoma es identico."""
    d = Disyuntor("t")
    _fallar(d, TRACEBACK)
    assert d.motivo_corte() is None, "un solo intento no es una espiral"
    _fallar(d, TRACEBACK)
    assert d.motivo_corte() == "D6"


def test_progreso_real_no_dispara():
    """Si cada intento cambia el sintoma, se esta avanzando: no cortar."""
    d = Disyuntor("t")
    _fallar(d, "AssertionError: falta el import")
    _fallar(d, "ZeroDivisionError: division by zero")
    assert d.motivo_corte() is None


def test_un_verde_corta_la_racha():
    """
    Regresion medida el 2026-07-20: el disyuntor se quedaba disparado PARA
    SIEMPRE. Tras dos fallos con la misma huella y un arreglo CORRECTO,
    motivo_corte() seguia devolviendo D6, y un fallo nuevo y distinto devolvia
    D1. Una vez que saltaba ya no dejaba trabajar aunque el problema estuviera
    resuelto, asi que cualquier lazo de reparacion apoyado en el se bloqueaba
    entero.

    Es la misma regla que reset_por_intervencion: si hay progreso dentro de la
    ventana, solo cuentan los eventos posteriores. Un verde es progreso.
    """
    d = Disyuntor("t")
    _fallar(d, "AssertionError: ranking incorrecto", veces=2)
    assert d.motivo_corte() == "D6", "sin verde de por medio SI debe cortar"

    d.registrar(huella_de_texto("todo verde"), ok=True)
    assert d.motivo_corte() is None, "el arreglo exitoso corta la racha"

    _fallar(d, "TypeError: otra cosa distinta")
    assert d.motivo_corte() is None, "un fallo nuevo tras el verde no es bucle"


def test_tras_el_verde_sigue_cortando_si_se_repite():
    """El verde no es una amnistia: si se vuelve a parchear en seco, corta."""
    d = Disyuntor("t")
    _fallar(d, "AssertionError: uno", veces=2)
    d.registrar(huella_de_texto("todo verde"), ok=True)
    _fallar(d, "TypeError: dos", veces=2)

    assert d.motivo_corte() == "D6"


def test_exploracion_sin_editar_no_cuenta():
    """
    El falso positivo que hace que la gente desactive estas cosas: castigar
    la depuracion sana. Leer y probar hipotesis sin escribir no es parchear.
    """
    d = Disyuntor("t")
    _fallar(d, TRACEBACK, veces=5, hubo_cambio=False)
    assert d.motivo_corte() is None
    assert d._esteriles() == []


def test_d1_limite_duro_de_intentos():
    """Umbral de Aider: max_reflections = 3, hardcodeado en su base_coder."""
    d = Disyuntor("t", max_intentos=3)
    for i in range(3):
        _fallar(d, f"error distinto numero {i}")
    assert d.motivo_corte() == "D1"


def test_d6b_detecta_el_ciclo():
    """Vuelve a un sintoma que ya se creia superado: esta dando vueltas."""
    d = Disyuntor("t")
    _fallar(d, "error A")
    _fallar(d, "error B")
    _fallar(d, "error A")
    assert d.motivo_corte() in ("D6b", "D1")


# ── Reset y escalada ────────────────────────────────────────────────────

def test_intervencion_humana_resetea():
    d = Disyuntor("t")
    _fallar(d, TRACEBACK, veces=HUELLA_REPETIDA_CORTA)
    assert d.motivo_corte() == "D6"
    d.reset_por_intervencion()
    assert d.motivo_corte() is None


def test_reinicio_limpio_no_borra_los_cortes():
    """
    El contador de cortes tiene que sobrevivir para que el SEGUNDO disparo
    pueda escalar. Si se borrara, el agente daria vueltas para siempre
    reiniciandose limpio.
    """
    d = Disyuntor("t")
    _fallar(d, TRACEBACK, veces=HUELLA_REPETIDA_CORTA)
    d.anotar_corte()
    d.reiniciar_limpio()
    assert d.intentos == []
    assert d.cortes == 1


def test_segundo_disparo_ordena_escalar_no_reintentar():
    d = Disyuntor("t")
    _fallar(d, TRACEBACK, veces=HUELLA_REPETIDA_CORTA)
    primera = d.orden_de_modo_raiz()
    assert "MODO RAIZ" in primera
    assert "SEGUNDO DISPARO" not in primera

    segunda = d.orden_de_modo_raiz()
    assert "SEGUNDO DISPARO" in segunda
    assert "Pedir ayuda" in segunda


def test_la_orden_no_dice_respira_hondo():
    """
    Huang et al. (ICLR 2024): auto-corregirse sin verificador externo EMPEORA
    el resultado. El respiro profundo va como corte estructural, nunca como
    instruccion al modelo.
    """
    d = Disyuntor("t")
    _fallar(d, TRACEBACK, veces=HUELLA_REPETIDA_CORTA)
    orden = d.orden_de_modo_raiz().lower()
    for prohibido in ("respira", "piensa mejor", "esfuerzate", "con calma"):
        assert prohibido not in orden
    assert "reproduccion minima" in orden
    assert "medir" in orden


def test_persiste_en_jsonl(tmp_path):
    log = tmp_path / "r.jsonl"
    d = Disyuntor("mi tarea", ruta_log=log)
    _fallar(d, TRACEBACK, veces=2)
    lineas = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 2
    assert "mi tarea" in lineas[0]


# ── Integracion con el bucle real de tool_synthesis ─────────────────────

ROTO = "def run(args: str) -> str:\n    return undefined_name(args)\n"


class _OrchRoto:
    """Devuelve siempre el mismo codigo roto y anota los prompts recibidos."""

    def __init__(self):
        self.prompts = []

    def infer(self, prompt):
        self.prompts.append(prompt)
        return types.SimpleNamespace(text=ROTO)

    def reparaciones(self):
        """Un prompt de reparacion es el que lleva dentro el codigo anterior."""
        return [p for p in self.prompts if ROTO in p]

    def generaciones(self):
        return [p for p in self.prompts if ROTO not in p]


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(TS, "GENERATED_DIR", tmp_path / "gen")
    monkeypatch.setattr(TS, "MANIFEST_PATH", tmp_path / "gen" / "_manifest.json")


def _spec():
    return TS.ToolSpec(name="rota", doc="d", purpose="p",
                       test_input="x", expect_contains="x")


def test_el_bucle_deja_de_reparar_sobre_codigo_roto():
    """
    LA PRUEBA QUE IMPORTA. Sin disyuntor el bucle hace 1 generacion + 2
    reparaciones, y las dos reparaciones parten del mismo codigo roto: es
    parche sobre parche. Con disyuntor, al ver que el sintoma no se movio,
    tira el codigo y REGENERA de cero.
    """
    orch = _OrchRoto()
    res = TS.synthesize_and_register(_spec(), orch=orch, max_attempts=3)

    assert not res["ok"]
    assert len(orch.generaciones()) == 2, "debe regenerar limpio tras el corte"
    assert len(orch.reparaciones()) == 1, "solo una reparacion antes de cortar"


def test_sin_fallos_no_interfiere():
    """Sin falsos positivos: si el primer intento sirve, nada se activa."""
    bueno = "def run(args: str) -> str:\n    return args\n"
    orch = types.SimpleNamespace(
        infer=lambda p: types.SimpleNamespace(text=bueno)
    )
    res = TS.synthesize_and_register(_spec(), orch=orch, max_attempts=3)
    assert res["ok"] and res["attempts"] == 1
