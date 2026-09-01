# -*- coding: utf-8 -*-
"""
tests/test_clases_documento.py
==============================
El documento por materia (cognia/clases/documento.py) contra DISCO de verdad.

Nada de mocks: cada test escribe su diario y su instantanea en un tmp_path y
los relee. Lo que puede fallar aqui es justo lo que un mock taparia -- que la
instantanea y el diario se desincronicen, que una linea rota se coma la
siguiente operacion, que dos hilos calculen el mismo id --, asi que se prueba
sobre ficheros reales.

QUE SE COMPRUEBA (lo caro, no lo obvio)
  - LA REGLA DE ORO: un bloque fijado por el duenio no lo reescribe ni lo
    borra la IA. Se comprueba por las dos puertas Y metiendo la operacion a
    mano en el diario, que es la unica forma de ver si la regla vive en el
    codigo o solo en el llamante.
  - La IDEMPOTENCIA del volcado desde los apuntes: dos pasadas iguales no
    duplican, una pasada mas corta limpia lo sobrante, y lo que el duenio
    corrigio se respeta y queda ANOTADO.
  - La RECONSTRUCCION desde el diario cuando la instantanea no esta (o cuando
    la ultima linea se corto a mitad, que es el corte real), y la de VUELTA:
    perder el diario entero o su cola no puede costar el documento ni reciclar
    un id.
  - El ORDEN, que es explicito, y los IDS, que no se reciclan al borrar.
  - Que una operacion IMPOSIBLE del diario ('mover' a un destino que no
    existe) no se lleve el bloque por delante al reproducirla.
  - Que un separador de linea de Unicode (U+2028, el que se cuela pegando de
    un PDF) no parta una linea del diario.
  - Dos hilos escribiendo a la vez.

AISLAMIENTO. COGNIA_CLASES_DIR se desvia a tmp_path en un fixture autouse y
se COMPRUEBA el desvio: sin eso estos tests escribirian documentos de mentira
en el cuaderno real del duenio (~/.cognia/clases). El estado de degradacion
del modulo (log-once) se limpia en el mismo fixture: si no, el primer test que
rompa el diario dejaria mudos a los siguientes.
"""

import json
import threading

import pytest

from cognia.clases import almacen as alm
from cognia.clases import documento as doc


# ── aislamiento ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    raiz = tmp_path / "clases"
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(raiz))
    # Verificacion, no fe: si el desvio no cogiera, los asserts de abajo
    # seguirian pasando mientras se escribe en el cuaderno de verdad.
    assert alm.raiz() == raiz.resolve() or alm.raiz() == raiz
    monkeypatch.delenv("COGNIA_DOC_OPS_INSTANTANEA", raising=False)
    doc._avisos_dados.clear()
    doc._ultimo_fallo.clear()
    yield


def _apuntes(**cambios) -> dict:
    """Un dict con la forma que devuelve apuntes.generar (las claves fijas de
    apuntes._plantilla). Se construye aqui y no se llama al generador: lo que
    se prueba es el VOLCADO, y arrastrar el modelo o el extractivo meteria en
    este test fallos que no son suyos."""
    base = {"titulo": "Movimiento rectilineo uniforme",
            "resumen": "Hoy se ha visto la relacion entre velocidad, espacio "
                       "y tiempo.",
            "claves": ["la velocidad es constante", "la aceleracion es cero"],
            "definiciones": [{"termino": "MRU",
                              "definicion": "movimiento a velocidad constante"}],
            "formulas": ["v = e/t", "e = v*t"],
            "deberes": ["ejercicios 3 y 4 de la pagina 21"],
            "dudas": ["por que se desprecia el rozamiento"],
            "examen": ["entra el apartado de graficas"],
            "chars_entrada": 100, "chars_salida": 50,
            "via": "extractivo", "aviso": ""}
    base.update(cambios)
    return base


# ── LA REGLA DE ORO ──────────────────────────────────────────────────────────

def test_la_ia_no_reescribe_lo_que_toco_el_duenio():
    b = doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO, "borrador de la IA")
    assert b.fijado is False and b.origen == doc.ORIGEN_IA

    tocado = doc.editar("Fisica", b.id, texto="lo que dijo el profe de verdad")
    # La regla de oro, primera mitad: tocarlo el duenio lo fija.
    assert tocado.fijado is True and tocado.origen == doc.ORIGEN_DUENIO

    informe = doc.escribir_ia("Fisica", b.id, texto="version refinada")
    assert informe["ok"] is False
    assert "fijo el duenio" in informe["motivo"]

    # Y en disco sigue lo del duenio, no lo de la IA.
    assert doc.abrir("Fisica").bloque(b.id).texto == "lo que dijo el profe de verdad"

    # Se ANOTA: un respeto silencioso no se distingue de un refinado que no
    # llego a correr.
    anotaciones = doc.respetados("Fisica")
    assert [a["id"] for a in anotaciones] == [b.id]
    assert anotaciones[0]["que"] == "editar"


def test_la_ia_no_borra_lo_que_toco_el_duenio():
    b = doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO, "borrador")
    doc.editar("Fisica", b.id, texto="mio")

    informe = doc.borrar_ia("Fisica", b.id)
    assert informe["ok"] is False
    assert doc.abrir("Fisica").bloque(b.id) is not None
    assert [a["que"] for a in doc.respetados("Fisica")] == ["borrar"]


def test_la_regla_vive_en_el_codigo_no_en_el_llamante():
    """Una operacion de la IA METIDA A MANO en el diario tampoco se aplica.

    Es la prueba de que la regla esta en el embudo (_aplicar) y no en las
    puertas: si viviera en escribir_ia, bastaria escribir la linea a pelo --
    o llamar a la puerta del duenio desde el refinado -- para saltarsela.
    """
    b = doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO, "borrador")
    doc.editar("Fisica", b.id, texto="lo mio")

    alm.apendar(doc.ruta_diario("Fisica"),
                {"op": "editar", "id": b.id, "texto": "PISADO POR LA IA",
                 "quien": doc.ORIGEN_IA, "t": 0.0})

    reabierto = doc.abrir("Fisica")
    assert reabierto.bloque(b.id).texto == "lo mio"
    assert any("descartada" in a for a in reabierto.avisos)


def test_desfijar_es_la_unica_forma_de_devolverselo_a_la_ia():
    b = doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO, "borrador")
    doc.editar("Fisica", b.id, texto="mio")
    assert doc.escribir_ia("Fisica", b.id, texto="x")["ok"] is False

    doc.fijar("Fisica", b.id, False)
    assert doc.escribir_ia("Fisica", b.id, texto="refinado")["ok"] is True
    assert doc.abrir("Fisica").bloque(b.id).texto == "refinado"


def test_mover_del_duenio_tambien_fija():
    a = doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO, "uno")
    b = doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO, "dos")
    doc.mover("Fisica", b.id, al_principio=True)
    d = doc.abrir("Fisica")
    assert [x.id for x in d.bloques] == [b.id, a.id]
    assert d.bloque(b.id).fijado is True


# ── Volcado desde los apuntes ────────────────────────────────────────────────

def test_volcar_los_mismos_apuntes_dos_veces_no_duplica():
    clave = "2026-08-31@0"
    primero = doc.desde_apuntes("Fisica", _apuntes(), clave)
    d1 = doc.abrir("Fisica")
    assert len(primero["creados"]) == len(d1.bloques)

    segundo = doc.desde_apuntes("Fisica", _apuntes(), clave)
    d2 = doc.abrir("Fisica")
    assert segundo["creados"] == [] and segundo["actualizados"] == []
    assert len(segundo["sin_cambio"]) == len(d1.bloques)
    assert [b.id for b in d2.bloques] == [b.id for b in d1.bloques]
    assert [b.texto for b in d2.bloques] == [b.texto for b in d1.bloques]


def test_volcar_apuntes_nuevos_reescribe_en_su_sitio():
    clave = "2026-08-31@0"
    doc.desde_apuntes("Fisica", _apuntes(), clave)
    orden = [b.id for b in doc.abrir("Fisica").bloques]

    informe = doc.desde_apuntes(
        "Fisica", _apuntes(resumen="Otro resumen, esta vez del modelo."), clave)
    d = doc.abrir("Fisica")
    assert len(informe["actualizados"]) == 1
    assert [b.id for b in d.bloques] == orden          # no se mueve de sitio
    resumen = [b for b in d.bloques if b.tipo == doc.TIPO_PARRAFO][0]
    assert resumen.texto == "Otro resumen, esta vez del modelo."


def test_volcar_apuntes_respeta_lo_que_corrigio_el_duenio():
    clave = "2026-08-31@0"
    doc.desde_apuntes("Fisica", _apuntes(), clave)
    resumen = [b for b in doc.abrir("Fisica").bloques
               if b.tipo == doc.TIPO_PARRAFO][0]
    doc.editar("Fisica", resumen.id, texto="ESTO LO ESCRIBI YO")

    informe = doc.desde_apuntes(
        "Fisica", _apuntes(resumen="el modelo cambio de opinion"), clave)

    assert resumen.id in informe["respetados"]
    assert doc.abrir("Fisica").bloque(resumen.id).texto == "ESTO LO ESCRIBI YO"
    # Y queda constancia de que se respeto, con la sesion en el motivo.
    anotado = [a for a in doc.respetados("Fisica") if a["id"] == resumen.id]
    assert anotado and clave in anotado[0]["motivo"]


def test_volcar_dos_veces_lo_mismo_no_escribe_nada_aunque_haya_fijados():
    """La idempotencia tambien vale para el DIARIO.

    Antes, con un bloque fijado, cada pasada apendaba otra anotacion
    'respetado' aunque los apuntes fueran identicos: el refinado de fondo
    convertia el diario en un contador de pasadas y `estado()` iba subiendo
    solo. Se sigue INFORMANDO del respeto (quien llama tiene que saberlo),
    pero no se escribe nada nuevo.
    """
    clave = "2026-08-31@0"
    doc.desde_apuntes("Fisica", _apuntes(), clave)
    resumen = [b for b in doc.abrir("Fisica").bloques
               if b.tipo == doc.TIPO_PARRAFO][0]
    doc.editar("Fisica", resumen.id, texto="ESTO LO ESCRIBI YO")

    apuntes = _apuntes(resumen="el modelo cambio de opinion")
    primero = doc.desde_apuntes("Fisica", apuntes, clave)
    assert primero["respetados"] == [resumen.id]
    ops = doc.abrir("Fisica").ops
    assert len(doc.respetados("Fisica")) == 1

    segundo = doc.desde_apuntes("Fisica", apuntes, clave)
    assert segundo["respetados"] == [resumen.id]        # se sigue informando
    assert segundo["creados"] == [] and segundo["actualizados"] == []
    assert doc.abrir("Fisica").ops == ops               # ni una linea nueva
    assert len(doc.respetados("Fisica")) == 1
    assert doc.abrir("Fisica").bloque(resumen.id).texto == "ESTO LO ESCRIBI YO"


def test_un_sobrante_fijado_se_respeta_una_vez_y_no_una_por_pasada():
    """Lo mismo por el otro camino: el bloque que los apuntes ya no generan.

    Se anota una vez que no se puede borrar y ya; repetir la anotacion en
    cada pasada no aniade informacion, solo diario.
    """
    clave = "2026-08-31@0"
    doc.desde_apuntes("Fisica", _apuntes(), clave)
    formula = [b for b in doc.abrir("Fisica").bloques
               if b.tipo == doc.TIPO_FORMULA][1]
    doc.editar("Fisica", formula.id, texto="e = v*t (asi lo puso el profe)")

    cortos = _apuntes(formulas=["v = e/t"])
    doc.desde_apuntes("Fisica", cortos, clave)
    ops = doc.abrir("Fisica").ops

    informe = doc.desde_apuntes("Fisica", cortos, clave)
    assert informe["respetados"] == [formula.id]
    assert informe["borrados"] == []
    assert doc.abrir("Fisica").ops == ops
    assert [a["que"] for a in doc.respetados("Fisica")] == ["borrar"]
    assert doc.abrir("Fisica").bloque(formula.id) is not None


def test_volcar_apuntes_mas_cortos_limpia_lo_sobrante():
    clave = "2026-08-31@0"
    doc.desde_apuntes("Fisica", _apuntes(), clave)
    formulas = [b for b in doc.abrir("Fisica").bloques
                if b.tipo == doc.TIPO_FORMULA]
    assert len(formulas) == 2

    informe = doc.desde_apuntes("Fisica", _apuntes(formulas=["v = e/t"]), clave)
    assert informe["borrados"] == [formulas[1].id]
    assert len([b for b in doc.abrir("Fisica").bloques
                if b.tipo == doc.TIPO_FORMULA]) == 1


def test_volcar_apuntes_no_toca_los_de_otra_sesion_ni_lo_del_duenio():
    doc.desde_apuntes("Fisica", _apuntes(), "2026-08-31@0")
    doc.desde_apuntes("Fisica", _apuntes(titulo="Segunda hora"),
                      "2026-08-31@3000")
    mio = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "nota mia suelta")

    antes = len(doc.abrir("Fisica").bloques)
    doc.desde_apuntes("Fisica", _apuntes(formulas=[]), "2026-08-31@0")
    d = doc.abrir("Fisica")
    # Se van las 2 formulas de la primera sesion y nada mas.
    assert len(d.bloques) == antes - 2
    assert d.bloque(mio.id) is not None
    assert any(b.texto == "Segunda hora" for b in d.bloques)


def test_desde_apuntes_sin_clave_da_un_error_legible():
    with pytest.raises(doc.ErrorDocumento) as exc:
        doc.desde_apuntes("Fisica", _apuntes(), "")
    assert "clave estable" in str(exc.value)


# ── Persistencia: reconstruccion y cortes ────────────────────────────────────

def test_se_reconstruye_desde_el_diario_sin_instantanea():
    doc.desde_apuntes("Fisica", _apuntes(), "2026-08-31@0")
    b = doc.abrir("Fisica").bloques[1]
    doc.editar("Fisica", b.id, texto="corregido a mano")
    doc.mover("Fisica", b.id, al_principio=True)
    esperado = doc.a_markdown("Fisica")

    doc.ruta_instantanea("Fisica").unlink()

    d = doc.abrir("Fisica")
    assert doc.volcar(d) == esperado
    assert d.bloque(b.id).texto == "corregido a mano"
    assert d.bloque(b.id).fijado is True
    assert d.bloques[0].id == b.id


def test_la_instantanea_acota_lo_que_hay_que_reproducir(monkeypatch):
    """La promesa de la instantanea no es "no queda diario que reproducir"
    (siempre queda la ultima operacion), es que lo pendiente esta ACOTADO por
    el knob y que compactar lo deja a cero."""
    monkeypatch.setenv("COGNIA_DOC_OPS_INSTANTANEA", "2")
    for i in range(6):
        doc.aniadir("Fisica", doc.TIPO_PARRAFO, "linea %d" % i)

    d = doc.abrir("Fisica")
    assert d.ops == len(doc._lineas(doc.ruta_diario("Fisica")))
    assert 0 <= d.ops - d.ops_instantanea < 2
    guardado = json.loads(doc.ruta_instantanea("Fisica").read_text("utf-8"))
    assert guardado["ops"] == d.ops_instantanea
    assert guardado["siguiente"] == 6

    entero = doc.compactar("Fisica")
    assert entero.ops == entero.ops_instantanea
    guardado = json.loads(doc.ruta_instantanea("Fisica").read_text("utf-8"))
    assert len(guardado["bloques"]) == 6


def test_una_linea_rota_no_se_lleva_el_documento():
    """El corte de verdad: el proceso muere en mitad de una escritura.

    La linea a medias se salta al leer, y -- lo que costaria caro si no se
    hiciera -- la SIGUIENTE operacion no se pega a esa basura: se cierra la
    linea antes de apendar.
    """
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "lo de antes del corte")
    ruta = doc.ruta_diario("Fisica")
    with ruta.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"op": "aniadir", "bloque": {"id": "b0099", "tip')  # sin \n

    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "lo de despues del corte")

    d = doc.abrir("Fisica")
    assert [x.id for x in d.bloques] == [a.id, b.id]
    assert d.bloque(b.id).texto == "lo de despues del corte"
    assert doc.ultimo_fallo().get("donde")
    # La linea nueva entro entera y sola, no pegada a la rota.
    lineas = doc._lineas(ruta)
    assert json.loads(lineas[-1])["bloque"]["texto"] == "lo de despues del corte"


def test_una_instantanea_adelantada_no_congela_el_documento(monkeypatch):
    """Instantanea que dice mas operaciones de las que tiene el diario.

    POR QUE ESTE TEST ESTA ESCRITO ASI. La version anterior solo reabria y
    miraba los bloques, y eso sale IGUAL con guardia y sin ella: sin guardia,
    `lineas[999:]` esta vacia y tampoco se reproduce nada, asi que el estado
    coincide. Pasaba por el motivo equivocado (comprobado borrando el guardia:
    seguia verde). Lo que discrimina de verdad es lo que queda DESPUES:

      1. que se DIGA (sin guardia no hay degradacion ninguna);
      2. que el indice quede acotado por el diario -- sin guardia
         `ops_instantanea` vale 999 y "cuanto llevo sin compactar" sale
         NEGATIVO, o sea que la instantanea no se reescribe nunca mas;
      3. y lo que eso cuesta: con el indice pegado en 999, cada apertura
         siguiente parte de la instantanea vieja y se COME lo escrito desde
         entonces. Sin guardia, de los tres bloques nuevos solo sobrevive el
         ultimo.
    """
    monkeypatch.setenv("COGNIA_DOC_OPS_INSTANTANEA", "2")
    doc.aniadir("Fisica", doc.TIPO_PARRAFO, "una")
    doc.compactar("Fisica")
    ruta = doc.ruta_instantanea("Fisica")
    crudo = json.loads(ruta.read_text("utf-8"))
    crudo["ops"] = 999
    ruta.write_text(json.dumps(crudo), encoding="utf-8")

    d = doc.abrir("Fisica")
    assert [b.texto for b in d.bloques] == ["una"]
    assert d.ops == len(doc._lineas(doc.ruta_diario("Fisica")))

    # (1) se dice, y se dice quien
    assert (doc.ultimo_fallo().get("donde")
            == "clases.documento.instantanea_adelantada")
    # (2) el indice no puede apuntar a una linea que no existe
    assert d.ops_instantanea <= d.ops
    assert doc.estado("Fisica")["ops_sin_compactar"] >= 0

    # (3) y lo escrito a partir de ahora no se pierde
    for i in range(3):
        doc.aniadir("Fisica", doc.TIPO_PARRAFO, "mas %d" % i)
    assert [b.texto for b in doc.abrir("Fisica").bloques] == [
        "una", "mas 0", "mas 1", "mas 2"]
    guardado = json.loads(ruta.read_text("utf-8"))
    assert guardado["ops"] <= len(doc._lineas(doc.ruta_diario("Fisica")))
    assert len(guardado["bloques"]) == 4


def test_truncar_el_diario_no_recicla_ningun_id():
    """El diario pierde la cola y el siguiente bloque NO hereda un id usado.

    Es el caso caro: un id reciclado es peor que un id perdido. La referencia
    guardada (en un meta, en un apunte, en un mensaje del chat) deja de
    apuntar al bloque que era y pasa a apuntar a uno nuevo -- por ejemplo el
    que el duenio tenia fijado. El contador tiene que sobrevivir a la perdida
    del diario, y por eso va DENTRO de la instantanea.
    """
    ids = [doc.aniadir("Fisica", doc.TIPO_PARRAFO, "linea %d" % i).id
           for i in range(3)]
    doc.compactar("Fisica")

    ruta = doc.ruta_diario("Fisica")
    lineas = doc._lineas(ruta)
    assert len(lineas) == 4                      # crear + 3 aniadir
    # Truncado por la cola: copia a medias, restauracion vieja, disco lleno.
    ruta.write_text("\n".join(lineas[:2]) + "\n", encoding="utf-8",
                    newline="\n")

    d = doc.abrir("Fisica")
    # El estado NO se ha perdido: lo tenia la instantanea (el docstring del
    # modulo lo promete: perder el diario cuesta el historial, no el estado).
    assert [b.id for b in d.bloques] == ids

    nuevo = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "despues del truncado")
    assert nuevo.id not in ids
    assert doc._num_id(nuevo.id) > doc._num_id(ids[-1])

    todos = [b.id for b in doc.abrir("Fisica").bloques]
    assert todos == ids + [nuevo.id]
    assert len(set(todos)) == len(todos)


def test_perder_el_diario_entero_no_borra_el_documento():
    """Sin diario queda la instantanea: se pierde el historial, no el estado.

    Y el contador tampoco: el bloque siguiente no puede llamarse como uno que
    ya existio, aunque no quede ni una linea de diario que lo recuerde.
    """
    ids = [doc.aniadir("Fisica", doc.TIPO_PARRAFO, "linea %d" % i).id
           for i in range(3)]
    doc.borrar("Fisica", ids[1])                 # un id quemado que ya no vive
    doc.compactar("Fisica")
    doc.ruta_diario("Fisica").unlink()

    d = doc.abrir("Fisica")
    assert [b.id for b in d.bloques] == [ids[0], ids[2]]
    assert [b.texto for b in d.bloques] == ["linea 0", "linea 2"]
    assert doc.respetados("Fisica") == []        # el historial si se fue

    nuevo = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "despues de perderlo todo")
    assert nuevo.id not in ids
    assert [b.id for b in doc.abrir("Fisica").bloques] == [ids[0], ids[2],
                                                           nuevo.id]


def test_una_linea_que_no_es_un_registro_no_tira_el_documento():
    """JSON valido que no es un registro: `"texto"`, un numero, una lista.

    No es lo mismo que una linea cortada a mitad (esa no parsea y ya se
    saltaba): esta parsea, llegaba a `_aplicar` y reventaba con AttributeError
    -- una excepcion que NO es ErrorDocumento, asi que se escapaba de la
    reconstruccion y se llevaba el documento entero al abrirlo. Lo mete
    cualquiera que toque el diario con un editor.
    """
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "lo que ya estaba")
    ruta = doc.ruta_diario("Fisica")
    with ruta.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write('"una linea que es JSON pero no un registro"\n')
        fh.write("[1, 2, 3]\n")

    d = doc.abrir("Fisica")
    assert [x.id for x in d.bloques] == [a.id]
    assert len([x for x in d.avisos if "ilegible" in x]) == 2
    assert doc.ultimo_fallo().get("donde") == "clases.documento.linea_ilegible"
    # Y se sigue pudiendo escribir encima.
    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "lo de despues")
    assert [x.id for x in doc.abrir("Fisica").bloques] == [a.id, b.id]


def test_una_instantanea_sin_contador_no_recicla_el_id_de_un_borrado():
    """Instantanea vieja (o con el contador corrupto) y diario ENTERO.

    El contador se persiste desde hoy, pero puede faltar: una instantanea
    escrita por una version anterior no lo trae. Los bloques vivos no bastan
    para reconstruirlo -- el id de uno BORRADO no esta en ninguno --, asi que
    en ese caso degradado hay que ir a buscarlo al diario, que es la tercera
    fuente.
    """
    ids = [doc.aniadir("Fisica", doc.TIPO_PARRAFO, "linea %d" % i).id
           for i in range(3)]
    doc.borrar("Fisica", ids[2])                 # el id mas alto ya no vive
    doc.compactar("Fisica")

    ruta = doc.ruta_instantanea("Fisica")
    crudo = json.loads(ruta.read_text("utf-8"))
    crudo.pop("siguiente")                       # instantanea de antes
    ruta.write_text(json.dumps(crudo), encoding="utf-8")

    nuevo = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "el de despues")
    assert nuevo.id not in ids
    assert doc._num_id(nuevo.id) > doc._num_id(ids[2])


def test_una_instantanea_sin_contador_y_sin_diario_respeta_los_vivos():
    """Lo mismo pero sin diario: la ultima fuente son los bloques VIVOS.

    HONESTIDAD: aqui el id de un bloque BORRADO si se puede reciclar -- no
    queda nada que lo recuerde, ni contador ni diario ni bloque. Lo que no
    puede pasar es reciclar el id de uno que sigue en el documento, que es lo
    que convertiria un bloque nuevo en el bloque fijado del duenio.
    """
    ids = [doc.aniadir("Fisica", doc.TIPO_PARRAFO, "linea %d" % i).id
           for i in range(3)]
    doc.compactar("Fisica")

    ruta = doc.ruta_instantanea("Fisica")
    crudo = json.loads(ruta.read_text("utf-8"))
    crudo.pop("siguiente")
    ruta.write_text(json.dumps(crudo), encoding="utf-8")
    doc.ruta_diario("Fisica").unlink()

    nuevo = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "el de despues")
    assert nuevo.id not in ids
    todos = [b.id for b in doc.abrir("Fisica").bloques]
    assert todos == ids + [nuevo.id]
    assert len(set(todos)) == len(todos)


def test_un_mover_imposible_del_diario_no_se_lleva_el_bloque_por_delante():
    """El destino de 'mover' se valida ANTES de sacar el bloque de la lista.

    Es LA prueba de esa prevalidacion: al reproducir el diario el estado es
    acumulativo, asi que sacar el bloque y morir despues buscando el destino
    lo borraria del documento para siempre. Por la puerta de escritura no se
    veria (ahi el estado se descarta al fallar), asi que las dos operaciones
    imposibles se meten a mano en el diario -- un destino que no existe y un
    bloque movido tras si mismo -- y se reproduce todo.
    """
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "A")
    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "B")

    alm.apendar(doc.ruta_diario("Fisica"),
                {"op": "mover", "id": b.id, "tras": "b9999",
                 "quien": doc.ORIGEN_DUENIO, "t": 0.0})
    alm.apendar(doc.ruta_diario("Fisica"),
                {"op": "mover", "id": a.id, "tras": a.id,
                 "quien": doc.ORIGEN_DUENIO, "t": 0.0})
    # A reproducirlo TODO desde el diario (con el knob por defecto todavia no
    # hay instantanea que borrar, pero si la hubiera es la que taparia el bug).
    doc.ruta_instantanea("Fisica").unlink(missing_ok=True)

    d = doc.abrir("Fisica")
    assert [x.id for x in d.bloques] == [a.id, b.id]
    assert len([x for x in d.avisos if "descartada" in x]) == 2


def test_un_mover_imposible_por_la_puerta_da_un_error_legible():
    """La otra mitad: por la puerta se falla ANTES de tocar nada y se dice
    por que. El documento se queda como estaba."""
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "A")
    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "B")

    with pytest.raises(doc.ErrorDocumento) as exc:
        doc.mover("Fisica", b.id, tras="b9999")
    assert "b9999" in str(exc.value) and b.id in str(exc.value)
    with pytest.raises(doc.ErrorDocumento) as exc:
        doc.mover("Fisica", b.id, tras=b.id)
    assert "si mismo" in str(exc.value)

    assert [x.id for x in doc.abrir("Fisica").bloques] == [a.id, b.id]
    # Y ninguna de las dos llego al diario: 'crear' + los dos 'aniadir'.
    assert len(doc._lineas(doc.ruta_diario("Fisica"))) == 3


def test_un_separador_de_linea_de_pdf_no_parte_el_diario():
    """U+2028 y U+2029 pegados de un PDF no pueden partir una linea del diario.

    `json.dumps(ensure_ascii=False)` NO los escapa (ni a U+0085), asi que
    viajan CRUDOS dentro de la linea. `str.splitlines()` corta por ellos y
    `str.split("\\n")` no: si `_lineas` usara splitlines, ese bloque contaria
    como cuatro lineas, las cuatro mitades dejarian de ser JSON, el bloque
    desapareceria y ademas descuadraria el indice de la instantanea, que es un
    numero de LINEAS. Es la mitad de unos apuntes: sale de copiar un PDF.
    """
    raro = "del PDF:\u2028segunda linea\u2029otro parrafo\x85y una NEL"
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, raro)
    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "lo de despues")

    ruta = doc.ruta_diario("Fisica")
    en_disco = ruta.read_text("utf-8")
    # Crudos en el fichero, sin escapar: por eso pueden partir la linea.
    assert "\u2028" in en_disco and "\u2029" in en_disco
    assert len(doc._lineas(ruta)) == 3                     # crear + 2 aniadir
    assert len(en_disco.splitlines()) == 6                 # lo que se evita

    # Reconstruccion entera desde el diario: ahi es donde se pagaria el corte.
    doc.ruta_instantanea("Fisica").unlink(missing_ok=True)
    d = doc.abrir("Fisica")
    assert [x.id for x in d.bloques] == [a.id, b.id]
    assert d.bloque(a.id).texto == raro
    assert d.avisos == []
    assert doc.buscar("Fisica", "segunda linea")[0].id == a.id


# ── Orden e ids ──────────────────────────────────────────────────────────────

def test_el_orden_es_explicito_y_sobrevive_al_disco():
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "A")
    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "B")
    c = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "C")
    d_ = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "D", tras=a.id)
    doc.mover("Fisica", c.id, al_principio=True)

    esperado = [c.id, a.id, d_.id, b.id]
    assert [x.id for x in doc.abrir("Fisica").bloques] == esperado
    doc.compactar("Fisica")
    assert [x.id for x in doc.abrir("Fisica").bloques] == esperado


def test_los_ids_no_se_reciclan_al_borrar():
    a = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "A")
    b = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "B")
    doc.borrar("Fisica", b.id)
    c = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "C")
    assert c.id not in (a.id, b.id)
    assert doc._num_id(c.id) > doc._num_id(b.id)

    # Y el contador sobrevive a perder la instantanea (se rehace del diario:
    # cada 'aniadir' que se relee lo empuja, tambien el del bloque borrado).
    doc.compactar("Fisica")
    doc.ruta_instantanea("Fisica").unlink()
    d = doc.aniadir("Fisica", doc.TIPO_PARRAFO, "D")
    assert d.id not in (a.id, b.id, c.id)


def test_dos_hilos_escribiendo_no_corrompen_el_documento():
    """El refinado de fondo y el duenio a la vez. Sin el lock esto da ids
    repetidos (dos hilos leen el mismo contador) o una instantanea escrita
    desde un estado a medio aplicar."""
    fallos = []

    def escribir(quien):
        try:
            for i in range(25):
                if quien == "ia":
                    doc.aniadir_ia("Fisica", doc.TIPO_PARRAFO,
                                   "ia %d" % i)
                else:
                    doc.aniadir("Fisica", doc.TIPO_PARRAFO, "duenio %d" % i)
        except Exception as exc:            # pragma: no cover - solo si falla
            fallos.append("%s: %s" % (type(exc).__name__, exc))

    hilos = [threading.Thread(target=escribir, args=(q,))
             for q in ("ia", "duenio")]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert fallos == []
    d = doc.abrir("Fisica")
    assert len(d.bloques) == 50
    assert len(set(b.id for b in d.bloques)) == 50

    # El diario esta entero: todas las lineas parsean y reconstruyen lo mismo.
    lineas = doc._lineas(doc.ruta_diario("Fisica"))
    for linea in lineas:
        json.loads(linea)
    doc.ruta_instantanea("Fisica").unlink()
    rehecho = doc.abrir("Fisica")
    assert [b.id for b in rehecho.bloques] == [b.id for b in d.bloques]


# ── Validacion, busqueda y volcado a markdown ────────────────────────────────

def test_un_tipo_inventado_da_un_error_legible():
    with pytest.raises(doc.ErrorDocumento) as exc:
        doc.aniadir("Fisica", "diapositiva", "x")
    assert "diapositiva" in str(exc.value) and "parrafo" in str(exc.value)


def test_un_id_que_no_existe_da_un_error_legible():
    doc.abrir("Fisica")
    with pytest.raises(doc.ErrorDocumento) as exc:
        doc.editar("Fisica", "b9999", texto="x")
    assert "b9999" in str(exc.value) and "Fisica" in str(exc.value)


def test_una_meta_que_no_es_json_no_toca_el_documento():
    doc.abrir("Fisica")
    with pytest.raises(doc.ErrorDocumento):
        doc.aniadir("Fisica", doc.TIPO_IMAGEN, "pizarra",
                    meta={"adjunto": object()})
    assert doc.abrir("Fisica").bloques == []


def test_la_meta_del_tipo_se_rellena_y_lo_ajeno_se_conserva():
    b = doc.aniadir("Fisica", doc.TIPO_FORMULA, "v = e/t",
                    meta={"latex": "v = \\frac{e}{t}", "fuente": "pizarra"})
    guardado = doc.abrir("Fisica").bloque(b.id)
    assert guardado.meta["latex"] == "v = \\frac{e}{t}"
    assert guardado.meta["png"] == ""          # default del tipo
    assert guardado.meta["fuente"] == "pizarra"  # clave ajena, no se pierde


def test_buscar_ignora_tildes_y_mayusculas():
    doc.aniadir("Fisica", doc.TIPO_PARRAFO, "La aceleracion es la derivada")
    doc.aniadir("Fisica", doc.TIPO_PARRAFO, "Nada que ver")
    encontrados = doc.buscar("Fisica", "ACELERACION")
    assert len(encontrados) == 1
    assert doc.buscar("Fisica", "derivada")[0].texto.startswith("La acele")
    assert doc.buscar("Fisica", "   ") == []


def test_markdown_pone_la_decoracion_de_cada_tipo():
    doc.desde_apuntes("Fisica", _apuntes(), "2026-08-31@0")
    md = doc.a_markdown("Fisica")
    assert md.startswith("# Movimiento rectilineo uniforme")
    assert "$$\nv = e/t\n$$" in md
    assert "- [ ] ejercicios 3 y 4 de la pagina 21" in md
    assert "- (duda) por que se desprecia el rozamiento" in md
    assert "- la velocidad es constante" in md


def test_estado_es_la_puerta_de_diagnostico():
    vacio = doc.estado()
    assert vacio["documentos"] == []

    doc.desde_apuntes("Fisica", _apuntes(), "2026-08-31@0")
    b = doc.abrir("Fisica").bloques[0]
    doc.editar("Fisica", b.id, texto="mio")
    doc.escribir_ia("Fisica", b.id, texto="no deberia entrar")

    est = doc.estado("Fisica")
    assert est["documentos"] == ["Fisica"]
    assert est["bloques"] > 0
    assert est["fijados"] == 1
    assert est["respetados"] == 1
    assert est["ops_sin_compactar"] >= 0


def test_estado_cuenta_bloques_respetados_no_lineas_del_diario():
    """`respetados` es "cuantos bloques no pudo tocar la IA", no "cuantas
    lineas hay en el diario".

    Contar lineas daba un numero que solo sube: tres refinados que se topan
    con el MISMO parrafo del duenio daban "respetados: 3" sobre un documento
    con un solo bloque fijado, o sea que el diagnostico decia cuantas veces
    corrio el refinado y lo hacia pasar por cuanto hay. Las dos cosas
    interesan, pero son dos numeros.
    """
    clave = "2026-08-31@0"
    doc.desde_apuntes("Fisica", _apuntes(), clave)
    resumen = [b for b in doc.abrir("Fisica").bloques
               if b.tipo == doc.TIPO_PARRAFO][0]
    doc.editar("Fisica", resumen.id, texto="ESTO LO ESCRIBI YO")

    # Tres pasadas con apuntes DISTINTOS: tres intentos de verdad, uno por
    # pasada (con los mismos apuntes no se anotaria ninguno, ver el test de
    # idempotencia).
    for i in range(3):
        doc.desde_apuntes("Fisica",
                          _apuntes(resumen="version %d del modelo" % i), clave)

    est = doc.estado("Fisica")
    assert est["fijados"] == 1
    assert est["respetados"] == 1               # UN bloque
    assert est["anotaciones_respetado"] == 3    # TRES intentos


def test_una_materia_vacia_no_crea_un_documento_sin_nombre():
    """almacen._seguro convierte "" en 'sin-nombre': sin la comprobacion,
    unos apuntes reales acababan guardados en una materia que el duenio no
    puede encontrar."""
    with pytest.raises(doc.ErrorDocumento):
        doc.abrir("   ")
    with pytest.raises(doc.ErrorDocumento):
        doc.aniadir("", doc.TIPO_PARRAFO, "algo")
    assert doc.documentos() == []


def test_abrir_sin_crear_no_escribe_nada():
    d = doc.abrir("Fisica", crear=False)
    assert d.bloques == []
    assert not doc.ruta_diario("Fisica").exists()
    assert doc.documentos() == []
