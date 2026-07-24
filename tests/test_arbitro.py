"""
tests/test_arbitro.py — arbitro de colisiones entre generadores

Cada test usa su propio .arbitro.json bajo tmp_path (parametro `registro`), y
fija COGNIA_ARBITRO_SOMBRA explicitamente: el default del modulo es SOMBRA
(no bloquea), y un test que no lo diga se vuelve ambiguo.
"""

import json

import pytest

from cognia import arbitro


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """Registro aislado + modo con dientes (sombra apagada) por defecto."""
    monkeypatch.setenv("COGNIA_ARBITRO_SOMBRA", "0")
    return tmp_path / ".arbitro.json"


def _escribir(p, texto):
    p.write_text(texto, encoding="utf-8")
    return p


# -- propiedad -----------------------------------------------------------------

def test_registra_propiedad_y_huella(tmp_path, reg):
    f = _escribir(tmp_path / "motor.py", "def a():\n    return 1\n")
    assert arbitro.registrar_creacion("program_creator", f, f.read_text(), registro=reg)
    assert arbitro.dueno_de(f, registro=reg) == "program_creator"

    d = json.loads(reg.read_text(encoding="utf-8"))
    entrada = list(d["propiedad"].values())[0]
    assert entrada["generador"] == "program_creator"
    # read_text() destraduce \r\n -> \n, igual que huella(): en Windows
    # write_text guarda \r\n y read_bytes() daria 90 bytes de mas.
    assert entrada["bytes"] == len(f.read_text(encoding="utf-8").encode("utf-8"))
    assert len(entrada["sha"]) == 12
    assert entrada["mtime"] > 0


def test_el_dueno_original_no_cambia_al_reescribir(tmp_path, reg):
    f = _escribir(tmp_path / "m.py", "x = 1\n")
    arbitro.registrar_creacion("gen_a", f, f.read_text(), registro=reg)
    arbitro.registrar_creacion("gen_b", f, "x = 2\n", registro=reg)
    assert arbitro.dueno_de(f, registro=reg) == "gen_a"
    entrada = list(arbitro.propiedad(registro=reg).values())[0]
    assert entrada["ultimo_escritor"] == "gen_b"


def test_archivo_nuevo_sin_dueno_es_ok(tmp_path, reg):
    v = arbitro.revisar_escritura("gen_a", tmp_path / "nuevo.py", "y = 1\n", registro=reg)
    assert v["veredicto"] == "OK"


def test_el_dueno_reescribe_lo_suyo_sin_incidente(tmp_path, reg):
    contenido = "def a():\n    return 1\n" * 5
    f = _escribir(tmp_path / "mio.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    ok, v = arbitro.permitir_escritura("gen_a", f, contenido + "# mas\n", registro=reg)
    assert ok is True and v["veredicto"] == "OK"
    assert arbitro.incidentes_pendientes(registro=reg) == []


# -- PISA_AJENO ----------------------------------------------------------------

def test_pisa_ajeno(tmp_path, reg):
    contenido = "def motor():\n    return 'trabajo del generador A'\n" * 4
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("program_creator", f, contenido, registro=reg)

    # mismo tamano aprox y sintaxis valida: el unico problema es que es ajeno
    nuevo = "def motor():\n    return 'trabajo del generador B'\n" * 4
    v = arbitro.revisar_escritura("tool_synthesis", f, nuevo, registro=reg)
    assert v["veredicto"] == "PISA_AJENO"
    assert v["generador_dueno"] == "program_creator"
    assert "motor.py" in v["detalle"]


def test_contenido_identico_no_es_colision(tmp_path, reg):
    contenido = "def motor():\n    return 1\n" * 4
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    v = arbitro.revisar_escritura("gen_b", f, contenido, registro=reg)
    assert v["veredicto"] == "OK"


# -- DESTRUYE ------------------------------------------------------------------

def test_destruye_por_tamano(tmp_path, reg):
    contenido = "# linea de trabajo real\n" * 40           # ~960 bytes
    f = _escribir(tmp_path / "grande.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)

    v = arbitro.revisar_escritura("gen_a", f, "# esqueleto\n", registro=reg)
    assert v["veredicto"] == "DESTRUYE"
    assert v["motivo"] == "perdida de tamano"
    assert "grande.py" in v["detalle"]


def test_perdida_por_debajo_del_umbral_es_ok(tmp_path, reg):
    contenido = "# linea\n" * 100                          # 800 bytes
    f = _escribir(tmp_path / "g.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    v = arbitro.revisar_escritura("gen_a", f, "# linea\n" * 60, registro=reg)  # -40%
    assert v["veredicto"] == "OK"


def test_archivo_chico_no_dispara_por_tamano(tmp_path, reg):
    f = _escribir(tmp_path / "chico.py", "x = 1\n")        # < MINIMO_BYTES
    arbitro.registrar_creacion("gen_a", f, "x = 1\n", registro=reg)
    v = arbitro.revisar_escritura("gen_a", f, "y\n", registro=reg)
    assert v["veredicto"] == "OK"


def test_destruye_por_sintaxis_rota(tmp_path, reg):
    contenido = "def motor(x):\n    return x * 2\n"
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)

    roto = contenido + "def mitad(:\n"                     # mas grande, pero no compila
    v = arbitro.revisar_escritura("gen_b", f, roto, registro=reg)
    assert v["veredicto"] == "DESTRUYE"
    assert v["motivo"] == "sintaxis rota"


def test_no_py_con_sintaxis_invalida_no_dispara(tmp_path, reg):
    contenido = "clave = valor\n" * 10
    f = _escribir(tmp_path / "config.ini", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    v = arbitro.revisar_escritura("gen_a", f, contenido + "def x(:\n", registro=reg)
    assert v["veredicto"] == "OK"


def test_destruye_gana_sobre_pisa_ajeno(tmp_path, reg):
    contenido = "# trabajo\n" * 90
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    v = arbitro.revisar_escritura("gen_b", f, "# nada\n", registro=reg)
    assert v["veredicto"] == "DESTRUYE"
    assert v["generador_dueno"] == "gen_a"        # el dueno pisado igual se nombra


# -- detener / bloqueo ---------------------------------------------------------

def test_detener_bloquea_con_sombra_apagada(tmp_path, reg):
    contenido = "# trabajo real\n" * 60
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)

    ok, v = arbitro.permitir_escritura("gen_b", f, "# nada\n", registro=reg)
    assert ok is False
    assert v["veredicto"] == "DESTRUYE"
    inc = arbitro.incidentes_pendientes(registro=reg)
    assert len(inc) == 1 and inc[0]["bloqueado"] is True and inc[0]["sombra"] is False


def test_ok_nunca_registra_incidente(tmp_path, reg):
    ok, v = arbitro.permitir_escritura("gen_a", tmp_path / "libre.py", "z = 1\n", registro=reg)
    assert ok is True
    assert arbitro.incidentes_pendientes(registro=reg) == []


# -- modo sombra ---------------------------------------------------------------

def test_modo_sombra_es_el_default(monkeypatch):
    monkeypatch.delenv("COGNIA_ARBITRO_SOMBRA", raising=False)
    assert arbitro.modo_sombra() is True
    monkeypatch.setenv("COGNIA_ARBITRO_SOMBRA", "1")
    assert arbitro.modo_sombra() is True
    monkeypatch.setenv("COGNIA_ARBITRO_SOMBRA", "0")
    assert arbitro.modo_sombra() is False


def test_sombra_registra_pero_no_bloquea(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_ARBITRO_SOMBRA", "1")
    reg = tmp_path / ".arbitro.json"
    contenido = "# trabajo real\n" * 60
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)

    ok, v = arbitro.permitir_escritura("gen_b", f, "# nada\n", registro=reg)
    assert ok is True                              # NO bloquea
    assert v["veredicto"] == "DESTRUYE"            # pero lo vio
    inc = arbitro.incidentes_pendientes(registro=reg)
    assert len(inc) == 1 and inc[0]["sombra"] is True and inc[0]["bloqueado"] is False


# -- incidentes y aviso al cerebro ---------------------------------------------

def test_incidentes_y_marcar_avisados(tmp_path, reg):
    contenido = "# trabajo\n" * 90
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    arbitro.permitir_escritura("gen_b", f, "# nada\n", registro=reg)
    arbitro.permitir_escritura("gen_c", f, "# nada2\n", registro=reg)

    pend = arbitro.incidentes_pendientes(registro=reg)
    assert len(pend) == 2
    assert arbitro.marcar_avisados([pend[0]["id"]], registro=reg) == 1
    assert len(arbitro.incidentes_pendientes(registro=reg)) == 1
    assert arbitro.marcar_avisados(registro=reg) == 1
    assert arbitro.incidentes_pendientes(registro=reg) == []


def test_aviso_para_el_cerebro(tmp_path, reg):
    contenido = "# trabajo\n" * 90                 # 900 bytes
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_dueno", f, contenido, registro=reg)
    arbitro.permitir_escritura("gen_intruso", f, "# 120 bytes de nada\n", registro=reg)

    txt = arbitro.aviso_para_el_cerebro(registro=reg)
    assert "gen_intruso" in txt and "gen_dueno" in txt
    assert "motor.py" in txt and "reduciendolo de 900 a 20 bytes" in txt
    assert "Lo detuve." in txt
    # sin marcar: siguen pendientes
    assert len(arbitro.incidentes_pendientes(registro=reg)) == 1
    assert arbitro.aviso_para_el_cerebro(registro=reg, marcar=True)
    assert arbitro.incidentes_pendientes(registro=reg) == []
    assert arbitro.aviso_para_el_cerebro(registro=reg) == ""


def test_aviso_en_sombra_dice_que_no_detuvo(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_ARBITRO_SOMBRA", "1")
    reg = tmp_path / ".arbitro.json"
    contenido = "# trabajo\n" * 90
    f = _escribir(tmp_path / "motor.py", contenido)
    arbitro.registrar_creacion("gen_a", f, contenido, registro=reg)
    arbitro.permitir_escritura("gen_b", f, "# nada\n", registro=reg)
    txt = arbitro.aviso_para_el_cerebro(registro=reg)
    assert "modo sombra" in txt and "NO lo detuve" in txt


def test_aviso_vacio_sin_incidentes(reg):
    assert arbitro.aviso_para_el_cerebro(registro=reg) == ""


# -- best-effort: el arbitro NUNCA rompe al generador --------------------------

def test_fallo_interno_no_bloquea_la_escritura(tmp_path, reg, monkeypatch):
    def _explota(*a, **k):
        raise RuntimeError("arbitro roto a proposito")

    monkeypatch.setattr(arbitro, "revisar_escritura", _explota)
    ok, v = arbitro.permitir_escritura("gen_b", tmp_path / "x.py", "x = 1\n", registro=reg)
    assert ok is True
    assert "arbitro fallo" in v["detalle"]


def test_registro_corrupto_no_rompe(tmp_path, reg):
    reg.write_text("{esto no es json", encoding="utf-8")
    v = arbitro.revisar_escritura("gen_a", tmp_path / "x.py", "x = 1\n", registro=reg)
    assert v["veredicto"] == "OK"
    assert arbitro.incidentes_pendientes(registro=reg) == []
    assert arbitro.registrar_creacion("gen_a", tmp_path / "x.py", "x = 1\n", registro=reg)


def test_revisar_no_levanta_con_registro_ilegible(tmp_path, monkeypatch):
    def _explota(*a, **k):
        raise OSError("disco en llamas")

    monkeypatch.setattr(arbitro, "cargar", _explota)
    v = arbitro.revisar_escritura("gen_a", tmp_path / "x.py", "x = 1\n")
    assert v["veredicto"] == "OK"
    assert "no pudo revisar" in v["detalle"]
    assert arbitro.detener(v) is True


def test_resumen_estado_vacio(tmp_path):
    """Sin incidentes: dice que esta limpio y en que modo corre."""
    from cognia.arbitro import resumen_estado
    reg = str(tmp_path / ".arbitro.json")
    txt = resumen_estado(reg)
    assert "modo" in txt.lower()
    assert "limpio" in txt.lower() or "Sin colisiones" in txt


def test_resumen_estado_con_incidente(tmp_path, monkeypatch):
    """Tras una colision, el resumen la nombra."""
    from cognia import arbitro
    monkeypatch.setenv("COGNIA_ARBITRO_SOMBRA", "0")
    reg = str(tmp_path / ".arbitro.json")
    arbitro.registrar_creacion("gen_a", "motor.py", "def f():\n    return 1\n" * 30, reg)
    puede, ver = arbitro.permitir_escritura("gen_b", "motor.py", "x=1\n", reg)
    assert puede is False                       # destruye -> bloqueado
    txt = arbitro.resumen_estado(reg)
    assert "motor.py" in txt and "gen_b" in txt
    assert "incidentes historicos: 1" in txt
