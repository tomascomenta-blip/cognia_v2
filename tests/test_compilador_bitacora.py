"""
tests/test_compilador_bitacora.py
=================================
La bitacora del compilador de herramientas.

QUE SE PRUEBA Y POR QUE. La bitacora es lo que convierte un compilador que
edita cli.py en un cambio auditable, asi que lo que hay que probar no es que
"escriba un fichero" sino las tres preguntas que tiene que poder contestar
meses despues: que se creo, con que evidencia, y como se deshace. Ademas se
prueba el caso feo que motivo el formato JSONL: un fichero cortado a mitad.

Todo corre con COGNIA_COMPILADOR_DIR apuntando a tmp_path. Sin eso los tests
escribirian en la bitacora REAL del duenio, y una bitacora con /demo-* de
prueba dentro es una bitacora en la que ya no se puede confiar.

El reloj entra por parametro (`ahora=`): ni un solo assert depende de cuando
se corre la suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cognia.compilador import bitacora as bit


# El 2026-08-31 12:00:00 en tiempo local; cualquier constante vale, lo que
# importa es que sea FIJA. Los tests comparan orden, no fechas de pared.
T0 = 1788000000.0


@pytest.fixture()
def bita(tmp_path, monkeypatch):
    """Bitacora aislada en tmp_path. Devuelve el modulo ya redirigido."""
    monkeypatch.setenv("COGNIA_COMPILADOR_DIR", str(tmp_path / "compilador"))
    assert bit.dir_bitacora() == (tmp_path / "compilador")
    return bit


def _espec(cmd="/resumir-pdf"):
    """Una espec como la que produce el generador: dict plano."""
    return {
        "cmd": cmd,
        "nombre": "resumir_pdf",
        "descripcion": "resume un PDF largo en 10 lineas",
        "peticion": "quiero un comando que me resuma pdfs",
        "criterios": ["acepta una ruta de PDF",
                      "no revienta si el fichero no existe"],
    }


def _injerto(ok=True):
    """Lo que devuelve injertador.injertar(), con la forma real."""
    return {"ok": ok,
            "sitios": ["descripcion", "funcion", "despacho", "cubo",
                       "categoria"],
            "copia": "20260831-120000-resumir-pdf",
            "motivo": "",
            "categoria": "Documentos",
            "cubo": "AVANZADO",
            "guardianes": {"ok": True, "resumen": "42 passed in 3.10s",
                           "codigo": 0}}


def _evaluacion(ok=True):
    return {"veredicto": "APTA" if ok else "NO APTA",
            "ok": ok,
            "criterios": [{"texto": "acepta una ruta de PDF", "ok": True},
                          {"texto": "no revienta si el fichero no existe",
                           "ok": ok}]}


# ── El ciclo completo ────────────────────────────────────────────────────────

def test_ciclo_completo_registrar_listar_obtener_marcar_ficha(bita):
    f = bita.registrar(_espec(), _injerto(), _evaluacion(),
                       codigo={"handler": "def _slash_resumir_pdf(arg=''):\n    pass\n",
                               "modulo": "# modulo generado\n"},
                       ahora=T0)
    assert f["cmd"] == "/resumir-pdf"
    assert f["estado"] == "viva"

    # listar la ve
    filas = bita.listar()
    assert [x["cmd"] for x in filas] == ["/resumir-pdf"]
    assert filas[0]["veredicto"] == "APTA"
    assert filas[0]["copia"] == "20260831-120000-resumir-pdf"

    # obtener trae la EVIDENCIA, no solo el nombre
    ev = bita.obtener("/resumir-pdf")
    assert ev["evaluacion"]["veredicto"] == "APTA"
    assert ev["espec"]["peticion"] == "quiero un comando que me resuma pdfs"
    assert ev["sitios"] == _injerto()["sitios"]
    assert ev["guardianes"]["resumen"] == "42 passed in 3.10s"
    assert len(ev["criterios"]) == 2

    # el codigo esta EN DISCO, no referenciado al fuente
    handler = Path(ev["codigo"]["handler"])
    assert handler.is_file()
    assert "def _slash_resumir_pdf" in handler.read_text(encoding="utf-8")

    # marcar retirada
    tras = bita.marcar("/resumir-pdf", "retirada",
                       motivo="la pidio retirar el duenio", ahora=T0 + 60)
    assert tras["estado"] == "retirada"

    # listar(estado='viva') ya no la trae; listar() SI (es un historial)
    assert bita.listar(estado="viva") == []
    assert [x["cmd"] for x in bita.listar()] == ["/resumir-pdf"]
    assert bita.listar(estado="retirada")[0]["motivo"] == "la pidio retirar el duenio"

    # la ficha legible menciona veredicto y criterios
    texto = bita.ficha("/resumir-pdf")
    assert "APTA" in texto
    assert "acepta una ruta de PDF" in texto
    assert "no revienta si el fichero no existe" in texto
    assert "retirada" in texto
    assert "20260831-120000-resumir-pdf" in texto      # como revertir


def test_obtener_de_lo_que_no_esta_es_vacio_y_ficha_lo_dice(bita):
    assert bita.obtener("/no-existe") == {}
    assert "No hay ficha" in bita.ficha("/no-existe")


def test_injerto_fallido_queda_fallida_no_viva(bita):
    """El estado sale del INJERTO, no de la evaluacion.

    Un comando cuyo codigo era perfecto pero que no entro al CLI NO esta
    vivo. Confundirlos es exactamente el fallo que la bitacora existe para
    evitar: creer que hay una puerta donde no la hay.
    """
    malo = _injerto(ok=False)
    malo["motivo"] = "ErrorInjerto: no encuentro el ancla (repo restaurado)"
    f = bita.registrar(_espec("/roto"), malo, _evaluacion(ok=True), ahora=T0)
    assert f["estado"] == "fallida"
    assert bita.listar(estado="viva") == []
    assert "no encuentro el ancla" in bita.ficha("/roto")


def test_sin_evaluacion_lo_dice_en_vez_de_callar(bita):
    """No evaluado y evaluado mal tienen que verse DISTINTOS desde fuera."""
    f = bita.registrar(_espec("/sin-eval"), _injerto(), {}, ahora=T0)
    assert f["veredicto"] == "sin evaluar"
    assert "sin evaluar" in bita.ficha("/sin-eval")


# ── Orden, reloj y validacion ────────────────────────────────────────────────

def test_listar_ordena_de_mas_nueva_a_mas_vieja_con_reloj_inyectado(bita):
    bita.registrar(_espec("/vieja"), _injerto(), _evaluacion(), ahora=T0)
    bita.registrar(_espec("/nueva"), _injerto(), _evaluacion(), ahora=T0 + 999)
    assert [x["cmd"] for x in bita.listar()] == ["/nueva", "/vieja"]
    assert bita.obtener("/vieja")["cuando"] == T0


def test_estado_invalido_grita(bita):
    bita.registrar(_espec(), _injerto(), _evaluacion(), ahora=T0)
    with pytest.raises(ValueError):
        bita.marcar("/resumir-pdf", "zombie")
    with pytest.raises(ValueError):
        bita.listar(estado="zombie")


def test_marcar_lo_no_registrado_devuelve_vacio(bita):
    assert bita.marcar("/fantasma", "retirada") == {}


def test_espec_como_objeto_tambien_vale(bita):
    """El generador puede devolver una dataclase en vez de un dict.

    La bitacora no puede ser el punto donde se pierde el registro de un
    injerto YA HECHO por una diferencia de tipo entre modulos vecinos.
    """
    class Espec:
        def __init__(self):
            self.cmd = "/desde-objeto"
            self.nombre = "desde_objeto"
            self.descripcion = "una espec que no es dict"
            self.criterios = ["hace algo"]

    f = bita.registrar(Espec(), _injerto(), _evaluacion(), ahora=T0)
    assert f["cmd"] == "/desde-objeto"
    assert bita.obtener("/desde-objeto")["descripcion"] == "una espec que no es dict"


def test_registrar_sin_comando_grita(bita):
    with pytest.raises(ValueError):
        bita.registrar({"descripcion": "sin cmd"}, {"ok": True}, {})


# ── Lo feo: ficheros a medio escribir ────────────────────────────────────────

def test_una_linea_rota_al_final_del_jsonl_no_rompe_listar(bita):
    """El motivo por el que los eventos son JSONL append-only.

    Se corta la ultima linea (proceso muerto a mitad de write) Y se borra el
    indice, para que listar tenga que RECONSTRUIR leyendo ese JSONL roto. Sin
    borrar el indice el test pasaria sin tocar el fichero roto: pasaria por
    el motivo equivocado.
    """
    bita.registrar(_espec("/uno"), _injerto(), _evaluacion(), ahora=T0)
    bita.registrar(_espec("/dos"), _injerto(), _evaluacion(), ahora=T0 + 10)

    ruta = bita.dir_bitacora() / bit.EVENTOS
    with ruta.open("a", encoding="utf-8") as fh:
        fh.write('{"t": 123, "evento": "crea')          # cortada a mitad

    (bita.dir_bitacora() / bit.INDICE).unlink()

    filas = bita.listar()
    assert [x["cmd"] for x in filas] == ["/dos", "/uno"]
    assert bita.obtener("/uno")["veredicto"] == "APTA"
    # y la reconstruccion deja el indice sano otra vez
    assert json.loads((bita.dir_bitacora() / bit.INDICE)
                      .read_text(encoding="utf-8"))["comandos"].keys() >= {"/uno", "/dos"}


def test_las_marcas_sobreviven_a_perder_el_indice(bita):
    """El JSONL es la verdad; el indice es cache derivable."""
    bita.registrar(_espec("/marcada"), _injerto(), _evaluacion(), ahora=T0)
    bita.marcar("/marcada", "retirada", motivo="ya no hace falta", ahora=T0 + 5)
    (bita.dir_bitacora() / bit.INDICE).unlink()

    filas = bita.listar(estado="retirada")
    assert [x["cmd"] for x in filas] == ["/marcada"]
    assert filas[0]["motivo"] == "ya no hace falta"


def test_eventos_son_append_only(bita):
    """Nada se reescribe: cada paso deja su linea y ninguna desaparece."""
    bita.registrar(_espec("/hist"), _injerto(), _evaluacion(), ahora=T0)
    bita.marcar("/hist", "retirada", ahora=T0 + 1)
    bita.marcar("/hist", "viva", motivo="rehecha", ahora=T0 + 2)
    tipos = [e["evento"] for e in bita.eventos("/hist")]
    assert tipos == ["creada", "evaluada", "marcada", "marcada"]
    assert bita.obtener("/hist")["estado"] == "viva"
