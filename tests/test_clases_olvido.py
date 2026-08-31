"""
tests/test_clases_olvido.py
===========================
El olvido del cuaderno de clases: que borre lo que sobra y NO lo que importa.

DOS DECISIONES DE MONTAJE, las dos por lecciones ya pagadas en este repo:

  - El tiempo entra SIEMPRE por parametro (`ahora=AHORA`). Un test que dependa
    del reloj de pared es una bomba: pasaria hoy y fallaria el dia que alguien
    lo corra con otro huso, o el dia que el default de 14 dias cambie.
  - `COGNIA_CLASES_DIR` a tmp_path y las demas `COGNIA_CLASES_*` BORRADAS en un
    fixture autouse. Sin lo primero los tests purgarian el cuaderno REAL del
    duenio; sin lo segundo, un umbral exportado en la shell del duenio decide
    el resultado de la suite.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime

import pytest

import cognia.clases
from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua
from cognia.clases import olvido

# Instante fijo de referencia de TODA la suite. Cualquier "hace N dias" se
# construye restando de aqui.
AHORA = datetime(2026, 8, 31, 12, 0, 0).timestamp()
DIA = 86400.0


@pytest.fixture(autouse=True)
def cuaderno_aislado(tmp_path, monkeypatch):
    """Raiz del cuaderno en tmp_path y politica en sus defaults."""
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(tmp_path / "clases"))
    for var in (olvido.ENV_ACTIVO, olvido.ENV_DIAS_AUDIO,
                olvido.ENV_DIAS_TRANSCRIPCION, olvido.ENV_FRACCION):
        monkeypatch.delenv(var, raising=False)
    yield


def _fabricar(nombre, dias, *, trozos=0, lineas=0, apuntes=None, notas=(),
              adjuntos=(), estado="cerrada"):
    """Una jornada de mentira pero de verdad: ficheros reales en disco, con la
    forma exacta que escriben captura.py y la transcripcion."""
    d = alm.dir_jornada(nombre)
    cua.guardar_jornada(cua.Jornada(nombre=nombre,
                                    inicio_epoch=AHORA - dias * DIA,
                                    fin_epoch=AHORA - dias * DIA + 3600.0,
                                    estado=estado,
                                    segundos=float(lineas * 10)))
    for i in range(trozos):
        # 4 KB por trozo: no hacen falta 960 KB reales para medir bytes.
        (d / alm.DIR_AUDIO / ("%06d.wav" % (i + 1))).write_bytes(b"\0" * 4096)
    for i in range(lineas):
        # Las claves son las que escribe `transcripcion._anotar`: 't'/'t_fin'
        # y 'tipo', NO 't0'/'t1'. Escribir aqui la forma comoda en vez de la
        # real dejaba sin ejercitar el fallback `r.get("t") / r.get("t_fin")`
        # de _compactar_transcripcion, que es el unico camino que corre en la
        # maquina del duenio.
        alm.apendar(d / alm.TRANSCRIPCION, {
            "t": i * 10.0, "t_fin": i * 10.0 + 10.0, "pausa": False,
            "tipo": cua.TIPO_TRANSCRIPCION, "fuente": "sistema",
            "texto": "Frase numero %d de la clase sobre el tema de hoy." % i})
    if apuntes is not None:
        alm.guardar_json(d / alm.APUNTES, apuntes)
    for k, texto in enumerate(notas):
        alm.apendar(d / alm.ENTRADAS, {"t": 5.0 + k, "tipo": cua.TIPO_NOTA,
                                       "texto": texto, "fuente": "usuario"})
    for k, nom in enumerate(adjuntos):
        (d / alm.DIR_ADJUNTOS / nom).write_bytes(b"PNG-de-la-pizarra" * 30)
        alm.apendar(d / alm.ENTRADAS, {"t": 6.0 + k, "tipo": cua.TIPO_IMAGEN,
                                       "adjunto": nom, "fuente": "usuario"})
    return d


def _apuntes_reales():
    return {"0": {"titulo": "Cinematica", "resumen": "MRU y MRUA",
                  "claves": ["v = d/t"], "deberes": ["problemas 3 y 4"]}}


def _acciones(filas, accion):
    return [f for f in filas if f["accion"] == accion]


# -- politica ----------------------------------------------------------------

def test_politica_defaults_y_entorno(monkeypatch):
    pol = olvido.politica()
    assert pol["dias_audio"] == olvido.DIAS_AUDIO == 14
    assert pol["dias_transcripcion"] == olvido.DIAS_TRANSCRIPCION == 45
    assert pol["activo"] is True

    monkeypatch.setenv(olvido.ENV_DIAS_AUDIO, "3")
    monkeypatch.setenv(olvido.ENV_DIAS_TRANSCRIPCION, "7")
    monkeypatch.setenv(olvido.ENV_ACTIVO, "0")
    pol = olvido.politica()
    assert (pol["dias_audio"], pol["dias_transcripcion"]) == (3, 7)
    assert pol["activo"] is False


def test_umbral_ilegible_no_degrada_a_cero(monkeypatch):
    """Un umbral mal escrito NO puede acabar en 0: eso purgaria el curso
    entero. Vuelve al default (y el warning queda en el log)."""
    monkeypatch.setenv(olvido.ENV_DIAS_AUDIO, "catorce")
    assert olvido.politica()["dias_audio"] == olvido.DIAS_AUDIO
    monkeypatch.setenv(olvido.ENV_DIAS_AUDIO, "-5")
    assert olvido.politica()["dias_audio"] == olvido.DIAS_AUDIO


def test_desactivado_no_planea_nada(monkeypatch):
    _fabricar("2026-01-10", dias=200, trozos=3)
    monkeypatch.setenv(olvido.ENV_ACTIVO, "0")
    filas = olvido.plan(ahora=AHORA)
    assert [f["accion"] for f in filas] == [olvido.ACCION_NADA]
    assert olvido.aplicar(ahora=AHORA)["acciones"] == 0
    assert olvido.plan(ahora=AHORA)[0]["por_que"].endswith(olvido.ENV_ACTIVO)


# -- (a) el audio viejo se purga y el nuevo no -------------------------------

def test_audio_viejo_se_purga_y_el_nuevo_no():
    # `lineas=80`: el audio SOLO es purgable si el STT ya escribio algo (ver
    # test_audio_sin_transcribir_no_se_purga). Sin eso este test estaria
    # comprobando justo el camino que destruye la unica copia de la clase.
    vieja = _fabricar("2026-07-01", dias=60, trozos=5, lineas=80)
    nueva = _fabricar("2026-08-29", dias=2, trozos=4, lineas=10)

    filas = olvido.plan(ahora=AHORA)
    purgas = _acciones(filas, olvido.ACCION_PURGAR_AUDIO)
    assert [f["jornada"] for f in purgas] == ["2026-07-01"]
    assert purgas[0]["bytes"] == 5 * 4096
    # plan() no toca un byte: es su contrato entero.
    assert alm.bytes_de("2026-07-01")["audio"] == 5 * 4096

    res = olvido.aplicar(ahora=AHORA)
    assert res["acciones"] == 1
    assert res["bytes_liberados"] == 5 * 4096
    assert alm.bytes_de("2026-07-01")["audio"] == 0
    assert alm.bytes_de("2026-08-29")["audio"] == 4 * 4096
    assert (vieja / alm.DIR_AUDIO).is_dir()      # la carpeta se conserva
    assert list((nueva / alm.DIR_AUDIO).glob("*.wav"))


def test_jornada_abierta_no_se_purga():
    """El grabador tiene ficheros abiertos dentro de audio/: purgar ahi no es
    olvido, es sabotaje."""
    _fabricar("2026-06-01", dias=90, trozos=3, estado="grabando")
    filas = olvido.plan(ahora=AHORA)
    assert not _acciones(filas, olvido.ACCION_PURGAR_AUDIO)
    nada = _acciones(filas, olvido.ACCION_NADA)
    assert nada and "grabando" in nada[0]["por_que"]
    assert olvido.aplicar(ahora=AHORA)["bytes_liberados"] == 0
    assert alm.bytes_de("2026-06-01")["audio"] == 3 * 4096


def test_audio_sin_transcribir_no_se_purga():
    """El unico camino del modulo que puede destruir la UNICA copia de algo.

    `transcripcion.transcribir_pendientes()` existe justo para la jornada que
    se cerro con la cola a medias y para el audio que el duenio metio por
    fuera: si el olvido se lleva esos WAV a los 14 dias, de esa clase no queda
    ni el audio ni el texto. Antes del fix esto se purgaba, y la linea que
    quedaba en la bitacora decia "ya esta transcrito" -- una constancia falsa
    de un borrado irreversible.
    """
    d = _fabricar("2026-02-02", dias=200, trozos=5)        # lineas=0: sin STT
    assert not (d / alm.TRANSCRIPCION).exists()

    filas = olvido.plan(ahora=AHORA)
    assert not _acciones(filas, olvido.ACCION_PURGAR_AUDIO)
    nada = _acciones(filas, olvido.ACCION_NADA)
    assert nada and "SIN transcribir" in nada[0]["por_que"]

    res = olvido.aplicar(ahora=AHORA)
    assert res["acciones"] == 0 and res["bytes_liberados"] == 0
    assert alm.bytes_de("2026-02-02")["audio"] == 5 * 4096

    # Y en cuanto el STT pasa, ese mismo audio SI es purgable: la regla
    # retrasa el borrado, no lo bloquea para siempre.
    for i in range(5):
        alm.apendar(d / alm.TRANSCRIPCION,
                    {"t": i * 10.0, "t_fin": i * 10.0 + 10.0,
                     "tipo": cua.TIPO_TRANSCRIPCION, "texto": "algo dicho"})
    assert olvido.aplicar(ahora=AHORA)["bytes_liberados"] == 5 * 4096


def test_transcripcion_vacia_no_habilita_la_purga():
    """Un transcripcion.jsonl de 0 bytes es "se creo y no se escribio nada",
    no "ya esta transcrito"."""
    d = _fabricar("2026-02-03", dias=200, trozos=2)
    (d / alm.TRANSCRIPCION).write_bytes(b"")
    assert not _acciones(olvido.plan(ahora=AHORA), olvido.ACCION_PURGAR_AUDIO)
    olvido.aplicar(ahora=AHORA)
    assert alm.bytes_de("2026-02-03")["audio"] == 2 * 4096


def test_jornada_sin_fecha_es_intocable():
    """Lo que no se sabe fechar no se puede declarar viejo."""
    d = alm.dir_jornada("clase-suelta")
    (d / alm.DIR_AUDIO / "000001.wav").write_bytes(b"\0" * 4096)
    filas = olvido.plan(ahora=AHORA)
    assert [f["accion"] for f in filas] == [olvido.ACCION_NADA]
    olvido.aplicar(ahora=AHORA)
    assert (d / alm.DIR_AUDIO / "000001.wav").exists()


# -- (b) y (c) la transcripcion ----------------------------------------------

def test_transcripcion_vieja_sin_apuntes_no_se_toca():
    d = _fabricar("2026-05-05", dias=120, lineas=80)      # sin apuntes
    antes = (d / alm.TRANSCRIPCION).read_bytes()

    filas = olvido.plan(ahora=AHORA)
    assert not _acciones(filas, olvido.ACCION_COMPACTAR)
    nada = _acciones(filas, olvido.ACCION_NADA)
    assert nada and "SIN apuntes" in nada[0]["por_que"]

    res = olvido.aplicar(ahora=AHORA)
    assert res["acciones"] == 0
    assert (d / alm.TRANSCRIPCION).read_bytes() == antes
    assert res["protegido"] >= 1


def test_apuntes_vacios_no_cuentan_como_producto():
    """apuntes.json existente pero vacio = "se intento y no salio". Tratarlo
    como producto destilado pierde la fuente Y el resumen."""
    d = _fabricar("2026-05-06", dias=120, lineas=80, apuntes={"0": {}})
    antes = (d / alm.TRANSCRIPCION).read_bytes()
    assert not _acciones(olvido.plan(ahora=AHORA), olvido.ACCION_COMPACTAR)
    olvido.aplicar(ahora=AHORA)
    assert (d / alm.TRANSCRIPCION).read_bytes() == antes


def test_transcripcion_vieja_con_apuntes_se_compacta():
    d = _fabricar("2026-05-07", dias=120, lineas=80, apuntes=_apuntes_reales())
    ruta = d / alm.TRANSCRIPCION
    antes = ruta.stat().st_size
    literal = " ".join(r["texto"] for r in alm.leer_jsonl(ruta))

    filas = olvido.plan(ahora=AHORA)
    compactar = _acciones(filas, olvido.ACCION_COMPACTAR)
    assert [f["jornada"] for f in compactar] == ["2026-05-07"]
    assert ruta.stat().st_size == antes            # plan() no escribio nada

    res = olvido.aplicar(ahora=AHORA)
    assert res["acciones"] == 1
    assert res["bytes_liberados"] == antes - ruta.stat().st_size > 0

    regs = alm.leer_jsonl(ruta)
    assert len(regs) == 1 and regs[0]["compactado"] is True
    assert regs[0]["lineas_originales"] == 80
    assert 0 < len(regs[0]["texto"]) < len(literal)
    # Los apuntes (el producto) siguen intactos.
    assert alm.leer_json(d / alm.APUNTES, {}) == _apuntes_reales()
    # Y el cuaderno sigue leyendo la jornada: la entrada compactada conserva
    # la forma {t0,t1,texto,fuente} que espera cuaderno.Entrada.
    sesiones = cua.sesiones_de("2026-05-07")
    assert sesiones and sesiones[0].texto_dicho() == regs[0]["texto"]


def test_no_se_recompacta_lo_ya_compactado():
    """Sin la marca `compactado`, cada corrida volveria a resumir el resumen
    hasta dejarlo en nada."""
    d = _fabricar("2026-05-08", dias=120, lineas=80, apuntes=_apuntes_reales())
    olvido.aplicar(ahora=AHORA)
    tras_una = (d / alm.TRANSCRIPCION).read_bytes()
    res = olvido.aplicar(ahora=AHORA)
    assert res["acciones"] == 0
    assert res["bytes_liberados"] == 0
    assert (d / alm.TRANSCRIPCION).read_bytes() == tras_una


def test_transcripcion_reciente_con_apuntes_no_se_toca():
    d = _fabricar("2026-08-25", dias=6, lineas=80, apuntes=_apuntes_reales())
    antes = (d / alm.TRANSCRIPCION).read_bytes()
    assert not _acciones(olvido.plan(ahora=AHORA), olvido.ACCION_COMPACTAR)
    olvido.aplicar(ahora=AHORA)
    assert (d / alm.TRANSCRIPCION).read_bytes() == antes


# -- (d) lo del usuario sobrevive a todo -------------------------------------

def test_lo_del_usuario_sobrevive_con_umbrales_a_cero(monkeypatch):
    """La prueba dura: umbrales a 0 (todo es viejo). Se lleva el audio y
    compacta la transcripcion, y aun asi la nota y el adjunto siguen ahi."""
    monkeypatch.setenv(olvido.ENV_DIAS_AUDIO, "0")
    monkeypatch.setenv(olvido.ENV_DIAS_TRANSCRIPCION, "0")
    d = _fabricar("2026-08-30", dias=1, trozos=3, lineas=80,
                  apuntes=_apuntes_reales(),
                  notas=["esto entra en el examen"],
                  adjuntos=["pizarra_0001.png"])
    entradas_antes = (d / alm.ENTRADAS).read_bytes()
    adjunto = d / alm.DIR_ADJUNTOS / "pizarra_0001.png"
    adjunto_antes = adjunto.read_bytes()

    res = olvido.aplicar(ahora=AHORA)
    assert res["acciones"] == 2                   # audio + transcripcion
    assert res["bytes_liberados"] > 3 * 4096

    assert (d / alm.ENTRADAS).read_bytes() == entradas_antes
    assert adjunto.read_bytes() == adjunto_antes
    assert alm.bytes_de("2026-08-30")["adjuntos"] > 0
    assert res["protegido"] >= 2                  # la nota y la imagen

    tipos = [e.tipo for e in cua.sesiones_de("2026-08-30")[0].del_usuario()]
    assert cua.TIPO_NOTA in tipos and cua.TIPO_IMAGEN in tipos


# -- (e) seco no borra nada y reporta lo mismo -------------------------------

def test_seco_no_borra_y_reporta_lo_mismo(monkeypatch):
    """El simulacro tiene que dar EXACTAMENTE las cifras de la corrida real:
    es lo que se mira antes de dejar borrar 40 GB.

    Se aisla `cognia.clases.apuntes` a proposito: si el destilador con modelo
    existe, su salida no es deterministica y la comparacion seco/real medirian
    la temperatura del modelo en vez del contrato del olvido.
    """
    monkeypatch.delattr(cognia.clases, "apuntes", raising=False)
    monkeypatch.setitem(sys.modules, "cognia.clases.apuntes", None)

    d = _fabricar("2026-04-10", dias=140, trozos=4, lineas=80,
                  apuntes=_apuntes_reales(), notas=["repasar esto"])
    antes = alm.bytes_de("2026-04-10")
    transcripcion_antes = (d / alm.TRANSCRIPCION).read_bytes()

    simulado = olvido.aplicar(ahora=AHORA, seco=True)
    assert alm.bytes_de("2026-04-10") == antes
    assert (d / alm.TRANSCRIPCION).read_bytes() == transcripcion_antes
    assert simulado["acciones"] == 2 and simulado["bytes_liberados"] > 0

    real = olvido.aplicar(ahora=AHORA)
    assert real == simulado
    assert alm.bytes_de("2026-04-10")["audio"] == 0
    liberado = (antes["audio"] + antes["texto"]) - \
        (alm.bytes_de("2026-04-10")["audio"] + alm.bytes_de("2026-04-10")["texto"])
    assert liberado == real["bytes_liberados"]


# -- bitacora ----------------------------------------------------------------

def test_todo_borrado_deja_constancia():
    _fabricar("2026-03-01", dias=180, trozos=6, lineas=80,
              apuntes=_apuntes_reales())
    assert olvido.bitacora() == []

    olvido.aplicar(ahora=AHORA, seco=True)
    seco = olvido.bitacora()
    assert len(seco) == 2 and all(r["seco"] is True for r in seco)

    olvido.aplicar(ahora=AHORA)
    lineas = olvido.bitacora()
    assert len(lineas) == 4                       # append-only: nada se pisa
    reales = [r for r in lineas if not r["seco"]]
    acciones = {r["accion"] for r in reales}
    assert acciones == {olvido.ACCION_PURGAR_AUDIO, olvido.ACCION_COMPACTAR}
    for r in reales:
        assert r["jornada"] == "2026-03-01"
        assert r["bytes"] > 0 and r["por_que"] and r["t"] == AHORA


def test_se_apoya_en_apuntes_compactar_si_esta():
    """El olvido NO reimplementa el resumen: si el destilador esta, lo usa.

    Este test es el que caza que el adaptador de firma se rompa (paso ya una
    vez: `compactar(texto, tope_chars)` tiene el tope como obligatorio, y sin
    pasarlo el modulo degradaba al recorte pobre sin que nadie lo notara).
    """
    pytest.importorskip("cognia.clases.apuntes")
    d = _fabricar("2026-04-11", dias=140, lineas=80, apuntes=_apuntes_reales())
    olvido.aplicar(ahora=AHORA)
    reg = alm.leer_jsonl(d / alm.TRANSCRIPCION)[0]
    assert reg["via"] == "apuntes.compactar"
    assert reg["texto"].strip()


def test_el_destilador_roto_no_tumba_la_corrida(monkeypatch):
    """Que el destilador reviente no puede abortar `aplicar` A MITAD: para
    entonces el audio de las jornadas anteriores YA se borro, y la corrida se
    iria sin devolver ni las cifras ni el detalle de lo que hizo."""
    d = _fabricar("2026-02-04", dias=200, trozos=3, lineas=80,
                  apuntes=_apuntes_reales())

    def _revienta(*_a, **_k):
        raise RuntimeError("el modelo se cayo a media compactacion")
    monkeypatch.setattr(olvido, "_pedir_compactar", _revienta)

    res = olvido.aplicar(ahora=AHORA)             # no lanza
    assert res["acciones"] == 2                   # audio Y transcripcion
    assert alm.bytes_de("2026-02-04")["audio"] == 0
    reg = alm.leer_jsonl(d / alm.TRANSCRIPCION)[0]
    assert reg["via"] == "recorte uniforme"       # degrado, no se callo
    assert reg["texto"].strip()


def test_bitacora_rota_no_tumba_la_corrida(monkeypatch):
    """`_apuntar` corre DESPUES de un borrado irreversible. Si la bitacora
    falla la accion queda sin constancia (y eso se avisa en el log), pero
    dejar subir la excepcion es peor: se pierde tambien el informe de lo que
    ya se borro."""
    _fabricar("2026-02-05", dias=200, trozos=3, lineas=80,
              apuntes=_apuntes_reales())

    def _revienta(*_a, **_k):
        raise RuntimeError("disco lleno en la raiz del cuaderno")
    monkeypatch.setattr(alm, "apendar", _revienta)

    res = olvido.aplicar(ahora=AHORA)             # no lanza
    assert res["acciones"] == 2
    assert alm.bytes_de("2026-02-05")["audio"] == 0
    assert any("purgado" in linea for linea in res["detalle"])


# -- recorte deterministico --------------------------------------------------

def test_recorte_uniforme_acorta_marca_y_reparte():
    """El camino sin modelo tiene que ser real: acorta de verdad, marca los
    saltos y llega AL FINAL del tramo (no solo al principio, que en una clase
    es pasar lista).

    Los dos numeros de aqui salen del propio contrato, no de un ojimetro: el
    tope es `objetivo` mas lo unico que el algoritmo puede aniadir despues de
    cerrar el presupuesto (el espacio y el `_SALTO` final), y "llegar al
    final" se mide como el ultimo 10% del tramo. Con el bucle anterior la
    ultima frase muestreada era la 40 de 59 y este test lo dejaba pasar,
    porque miraba `[-2]` (la penultima) contra un umbral de 30.
    """
    frases = ["Frase numero %d del tramo completo." % i for i in range(60)]
    objetivo = 400
    salida = olvido._recorte_uniforme(" ".join(frases), objetivo)

    assert len(salida) <= objetivo + 1 + len(" " + olvido._SALTO)
    assert olvido._SALTO in salida
    vistas = [int(n) for n in re.findall(r"Frase numero (\d+)", salida)]
    assert vistas and vistas[0] == 0
    assert vistas[-1] >= 0.9 * (len(frases) - 1)
    assert vistas == sorted(vistas)               # en orden, no reordenadas
