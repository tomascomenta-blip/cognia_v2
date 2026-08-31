"""
tests/test_compilador_bitacora.py
=================================
La bitacora del compilador de herramientas.

QUE SE PRUEBA Y POR QUE. La bitacora es lo que convierte un compilador que
edita cli.py en un cambio auditable, asi que lo que hay que probar no es que
"escriba un fichero" sino las tres preguntas que tiene que poder contestar
meses despues: que se creo, con que evidencia, y como se deshace. Ademas se
prueba el caso feo que motivo el formato JSONL: un fichero cortado a mitad.

CON LAS FORMAS REALES DE LOS VECINOS. Los ayudantes de aqui abajo no inventan
un contrato comodo: copian lo que producen de verdad `especificacion.py`
(criterios {'invocacion','espera'}), `injertador.injertar()` y
`evaluador.evaluar()` ({'veredicto','fases','evidencia','motivo'}). La version
anterior de este fichero fabricaba criterios {'texto','ok'} que no produce
ningun modulo del repo, y por eso pasaba en verde mientras la ficha de una
compilacion REAL imprimia "aprobada (0/3 criterios)" y el enunciado de cada
criterio en json.dumps crudo. Un test con una forma inventada aprueba el
codigo por el motivo equivocado.

Todo corre con COGNIA_COMPILADOR_DIR apuntando a tmp_path, y lo fuerza un
fixture AUTOUSE: sin eso los tests escribirian en la bitacora REAL del duenio,
y una bitacora con /demo-* de prueba dentro es una bitacora en la que ya no se
puede confiar. Que sea autouse y no una cortesia de cada test es a proposito:
basta olvidarse una vez para ensuciar ~/.cognia.

El reloj entra por parametro (`ahora=`): ni un solo assert depende de cuando
se corre la suite.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cognia.compilador import bitacora as bit


# El 2026-08-31 12:00:00 en tiempo local; cualquier constante vale, lo que
# importa es que sea FIJA. Los tests comparan orden, no fechas de pared.
T0 = 1788000000.0


@pytest.fixture(autouse=True)
def _jamas_el_home_del_duenio(tmp_path, monkeypatch):
    """Ningun test de este fichero puede escribir en ~/.cognia. Autouse."""
    monkeypatch.setenv("COGNIA_COMPILADOR_DIR", str(tmp_path / "compilador"))


@pytest.fixture()
def bita(tmp_path):
    """Bitacora aislada en tmp_path. Devuelve el modulo ya redirigido."""
    assert bit.dir_bitacora() == (tmp_path / "compilador")
    return bit


def _espec(cmd="/resumir-pdf"):
    """Una espec como la que produce `especificacion.py`: dict plano.

    Los criterios llevan la forma REAL ({'invocacion','espera'}), que es la
    unica que `evaluador.fase_criterios()` sabe teclear.
    """
    return {
        "cmd": cmd,
        "nombre": "resumir_pdf",
        "descripcion": "resume un PDF largo en 10 lineas",
        "peticion": "quiero un comando que me resuma pdfs",
        "criterios": [
            {"invocacion": "%s ver informe.pdf" % cmd,
             "espera": "acepta una ruta de PDF"},
            {"invocacion": "%s ver no-existe.pdf" % cmd,
             "espera": "no revienta si el fichero no existe"},
        ],
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
    """Lo que devuelve evaluador.evaluar(): veredicto + las CINCO fases.

    No trae un ok por criterio: trae las fases que se EJECUTARON. Esa es la
    evidencia que la ficha tiene que guardar y ensenar.
    """
    return {
        "veredicto": "aprobada" if ok else "rechazada",
        "fases": [
            {"fase": "sintaxis", "ok": True, "detalle": "compila", "salida": ""},
            {"fase": "guardianes", "ok": True, "detalle": "4 verdes", "salida": ""},
            {"fase": "tests", "ok": True, "detalle": "3 passed", "salida": ""},
            {"fase": "invocacion", "ok": True, "detalle": "no lanza", "salida": ""},
            {"fase": "criterios", "ok": ok,
             "detalle": ("2/2 criterios del duenio cumplidos" if ok
                         else "1/2 criterios del duenio cumplidos"),
             "salida": ""},
        ],
        "evidencia": ["VEREDICTO: %s" % ("aprobada" if ok else "rechazada")],
        "motivo": "todo verde" if ok else "fallo la fase criterios",
    }


def _codigo_del_generador():
    """El dict ENTERO que `orquesta.py` le pasa a registrar(codigo=...).

    Lleva fuente Y metadatos ('via', 'ruta_modulo', 'ruta_tests'): la bitacora
    tiene que saber cual es cual.
    """
    return {"handler": "def _slash_resumir_pdf(arg=''):\n    pass\n",
            "modulo": "# modulo generado\n",
            "ruta_modulo": "cognia/herramientas/resumir_pdf.py",
            "tests": "def test_resumir():\n    pass\n",
            "ruta_tests": "tests/test_resumir_pdf.py",
            "via": "modelo"}


# ── El ciclo completo ────────────────────────────────────────────────────────

def test_ciclo_completo_registrar_listar_obtener_marcar_ficha(bita):
    f = bita.registrar(_espec(), _injerto(), _evaluacion(),
                       codigo=_codigo_del_generador(), ahora=T0)
    assert f["cmd"] == "/resumir-pdf"
    assert f["estado"] == "viva"

    # listar la ve
    filas = bita.listar()
    assert [x["cmd"] for x in filas] == ["/resumir-pdf"]
    assert filas[0]["veredicto"] == "aprobada"
    assert filas[0]["copia"] == "20260831-120000-resumir-pdf"

    # obtener trae la EVIDENCIA, no solo el nombre
    ev = bita.obtener("/resumir-pdf")
    assert ev["evaluacion"]["veredicto"] == "aprobada"
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
    assert "aprobada" in texto
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


# ── La evidencia: criterios y fases con la forma REAL ────────────────────────

def test_los_criterios_se_guardan_legibles_no_en_json_crudo(bita):
    """El criterio real es {'invocacion','espera'}, no {'texto'}.

    Leyendo solo los alias de 'texto', el enunciado que quedaba en la ficha
    era el json.dumps del criterio entero -- ilegible justo en el sitio donde
    se contesta "que se le pedia a esta herramienta".
    """
    bita.registrar(_espec("/crit"), _injerto(), _evaluacion(), ahora=T0)
    crit = bita.obtener("/crit")["criterios"]
    assert crit[0]["texto"] == "/crit ver informe.pdf -> acepta una ruta de PDF"
    assert not any(c["texto"].lstrip().startswith("{") for c in crit)


def test_las_fases_ejecutadas_quedan_en_la_ficha(bita):
    """El evaluador marca FASES, no criterios; sin ellas no hay evidencia.

    `evaluar()` devuelve las cinco fases que corrio con su detalle, y el
    veredicto sale de ellas. Guardar solo la palabra "aprobada" es guardar la
    conclusion y tirar la prueba.
    """
    bita.registrar(_espec("/fases"), _injerto(), _evaluacion(), ahora=T0)
    fases = bita.obtener("/fases")["fases"]
    assert [x["fase"] for x in fases] == ["sintaxis", "guardianes", "tests",
                                          "invocacion", "criterios"]
    assert all(x["ok"] is True for x in fases)
    texto = bita.ficha("/fases")
    assert "2/2 criterios del duenio cumplidos" in texto
    assert "[ok] guardianes" in texto


def test_no_inventa_un_cero_de_criterios_que_nadie_juzgo(bita):
    """"0/2 criterios" bajo un veredicto "aprobada" es una mentira.

    Nadie marco los criterios uno a uno (el evaluador marca las fases), y
    contar los None como fallos hace que la ficha de una compilacion perfecta
    se lea como dos criterios incumplidos.
    """
    bita.registrar(_espec("/cero"), _injerto(), _evaluacion(), ahora=T0)
    texto = bita.ficha("/cero")
    assert "0/2 criterios" not in texto
    assert "sin marcar uno a uno" in texto


def test_tambien_entiende_criterios_ya_juzgados(bita):
    """Si alguien SI trae el ok por criterio, se cuenta de verdad."""
    ev = dict(_evaluacion(), criterios=[
        {"texto": "acepta una ruta de PDF", "ok": True},
        {"texto": "no revienta si no existe", "ok": False}])
    bita.registrar(_espec("/juzgados"), _injerto(), ev, ahora=T0)
    crit = bita.obtener("/juzgados")["criterios"]
    assert [c["ok"] for c in crit] == [True, False]
    assert "(1/2 criterios)" in bita.ficha("/juzgados")


def test_una_evaluacion_con_pruebas_en_dict_no_se_desarma(bita):
    """'pruebas' como dict se iteraba y daba las CLAVES como criterios."""
    ev = dict(_evaluacion(), pruebas={"ok": True, "salida": "3 passed"})
    bita.registrar(_espec("/pruebas"), _injerto(), ev, ahora=T0)
    textos = [c["texto"] for c in bita.obtener("/pruebas")["criterios"]]
    assert "ok" not in textos and "salida" not in textos
    assert textos[0].startswith("/pruebas ver")


def test_solo_se_guarda_como_codigo_lo_que_es_codigo(bita):
    """orquesta pasa el dict entero del generador, con rutas y 'via' dentro.

    Escribirlas dejaba un via.py con la palabra "modelo" dentro y tres lineas
    "codigo <clave> ...py" en la ficha que no son el codigo de nada.
    """
    f = bita.registrar(_espec("/gen"), _injerto(), _evaluacion(),
                       codigo=_codigo_del_generador(), ahora=T0)
    assert sorted(f["codigo"]) == ["handler", "modulo", "tests"]
    assert not (Path(f["ruta"]) / "via.py").exists()
    assert not (Path(f["ruta"]) / "ruta_tests.py").exists()


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


def test_una_espec_circular_no_tira_el_registro(bita, caplog):
    """El injerto YA esta hecho: quedarse sin registro es el peor estado.

    json.dumps(default=str) no cubre una referencia circular ni una clave
    rara: lanza. Y lanzar aqui deja cli.py editado y la bitacora vacia.
    """
    espec = _espec("/circular")
    espec["yo"] = espec                      # se muerde la cola
    with caplog.at_level(logging.ERROR):
        f = bita.registrar(espec, _injerto(), _evaluacion(), ahora=T0)
    assert f["cmd"] == "/circular"
    assert "no serializable" in caplog.text  # y no se calla
    assert bita.obtener("/circular")["estado"] == "viva"


def test_registrar_sin_comando_grita(bita):
    with pytest.raises(ValueError):
        bita.registrar({"descripcion": "sin cmd"}, {"ok": True}, {})


# ── La clave del comando: una sola, en todas las puertas ─────────────────────

def test_marcar_sin_barra_encuentra_lo_registrado_con_barra(bita):
    """El fallo mas caro que tenia: un RECHAZO que se leia como aprobado.

    `registrar` anadia la barra que faltase y `marcar` no, asi que
    `orquesta._registrar()` daba de alta '/x' y marcaba 'x': el marcado se
    perdia con un warning y la herramienta rechazada por el evaluador se
    quedaba 'viva' en el indice.
    """
    bita.registrar({"cmd": "sin-barra", "nombre": "sb",
                    "criterios": ["algo"]},
                   _injerto(), _evaluacion(ok=False), ahora=T0)
    assert bita.listar()[0]["cmd"] == "/sin-barra"

    tras = bita.marcar("sin-barra", "fallida", motivo="rechazada", ahora=T0 + 1)
    assert tras.get("estado") == "fallida"
    assert bita.listar(estado="viva") == []
    assert bita.obtener("sin-barra")["estado"] == "fallida"
    assert bita.obtener("/sin-barra")["estado"] == "fallida"
    assert [e["evento"] for e in bita.eventos("sin-barra")] == \
        [e["evento"] for e in bita.eventos("/sin-barra")]
    assert "[fallida]" in bita.ficha("sin-barra")


def test_marcar_sin_motivo_no_borra_el_diagnostico_del_injerto(bita):
    """El motivo de una ficha fallida es la unica razon registrada."""
    malo = _injerto(ok=False)
    malo["motivo"] = "ErrorInjerto: no encuentro el ancla"
    bita.registrar(_espec("/sin-ancla"), malo, {}, ahora=T0)
    bita.marcar("/sin-ancla", "retirada", ahora=T0 + 1)
    assert "no encuentro el ancla" in bita.obtener("/sin-ancla")["motivo"]
    # y un motivo NUEVO si manda
    bita.marcar("/sin-ancla", "retirada", motivo="ya no hace falta", ahora=T0 + 2)
    assert bita.obtener("/sin-ancla")["motivo"] == "ya no hace falta"
    # las dos vias (indice vivo y reconstruccion) tienen que coincidir
    (bita.dir_bitacora() / bit.INDICE).unlink()
    assert bita.listar(estado="retirada")[0]["motivo"] == "ya no hace falta"


def test_la_ficha_se_lee_de_la_bitacora_activa_no_de_una_ruta_rancia(bita,
                                                                    tmp_path):
    """La 'ruta' guardada es absoluta y de otra maquina/carpeta.

    Honrarla a ciegas hace que se sirva la evidencia de OTRA bitacora.
    """
    bita.registrar(_espec("/mudanza"), _injerto(), _evaluacion(), ahora=T0)
    ajena = tmp_path / "otra-bitacora" / "fichas" / "mudanza"
    ajena.mkdir(parents=True)
    (ajena / "ficha.json").write_text(
        json.dumps({"cmd": "/mudanza", "descripcion": "FICHA AJENA",
                    "estado": "viva"}), encoding="utf-8")

    ruta_idx = bita.dir_bitacora() / bit.INDICE
    idx = json.loads(ruta_idx.read_text(encoding="utf-8"))
    idx["comandos"]["/mudanza"]["ruta"] = str(ajena)
    ruta_idx.write_text(json.dumps(idx), encoding="utf-8")

    assert bita.obtener("/mudanza")["descripcion"] != "FICHA AJENA"


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
    assert bita.obtener("/uno")["veredicto"] == "aprobada"
    # y la reconstruccion deja el indice sano otra vez
    assert json.loads((bita.dir_bitacora() / bit.INDICE)
                      .read_text(encoding="utf-8"))["comandos"].keys() >= {"/uno", "/dos"}


def test_si_se_pierde_el_alta_la_reconstruccion_AVISA(bita, caplog):
    """Un comando no puede desaparecer de listar() en silencio.

    Si la linea rota es justo el 'creada', sus eventos posteriores quedan
    huerfanos y el comando se cae del indice. Callarlo es el vacio silencioso
    de siempre: "no lo hubo" y "se perdio" tienen que verse distintos.
    """
    bita.registrar(_espec("/huerfano"), _injerto(), _evaluacion(), ahora=T0)
    bita.marcar("/huerfano", "retirada", motivo="importante", ahora=T0 + 1)

    ruta = bita.dir_bitacora() / bit.EVENTOS
    vivas = [l for l in ruta.read_text(encoding="utf-8").splitlines()
             if not ('"/huerfano"' in l and '"creada"' in l)]
    ruta.write_text("\n".join(vivas) + "\n", encoding="utf-8")
    (bita.dir_bitacora() / bit.INDICE).unlink()

    with caplog.at_level(logging.WARNING):
        assert bita.listar() == []
    assert "SIN alta" in caplog.text and "/huerfano" in caplog.text


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


# ── El aislamiento, comprobado ───────────────────────────────────────────────

def test_sin_la_env_var_caeria_en_el_home_y_por_eso_va_el_autouse(monkeypatch,
                                                                 tmp_path):
    """Se comprueba con un HOME falso: tocar el de verdad es el fallo grave.

    Sin COGNIA_COMPILADOR_DIR la bitacora vive en ~/.cognia/compilador y
    `dir_bitacora()` ademas la CREA. Un solo test que se olvide del fixture
    mete /demo-* en los datos reales del duenio, asi que el redirigido es
    autouse y esto documenta por que.
    """
    falso = tmp_path / "home-falso"
    monkeypatch.delenv("COGNIA_COMPILADOR_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: falso))
    assert bit.dir_bitacora() == falso / ".cognia" / "compilador"
    assert falso.is_dir()                    # la crea, por eso nunca la real


def test_la_bitacora_solo_escribe_dentro_de_tmp_path(bita, tmp_path):
    bita.registrar(_espec("/aislada"), _injerto(), _evaluacion(),
                   codigo=_codigo_del_generador(), ahora=T0)
    escritos = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert escritos, "no escribio nada: el test no estaria probando nada"
    for p in escritos:
        assert tmp_path in p.parents or p.is_relative_to(tmp_path)
