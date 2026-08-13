# -*- coding: utf-8 -*-
"""
Regresion (2026-08-12): el agente escribia ficheros SIN red de seguridad.

`escribir_archivo`/`editar_archivo` sobrescriben con write_text y el unico
rastro era agent_state['files_touched'] (nombres, capado a 15, sin contenido):
si el modelo "acortaba" un fichero del dueno, el trabajo se perdia y no habia
forma de volver. Estos tests fijan el contrato de cognia/harness/checkpoints.py:
registrar antes de escribir, deshacer despues, y avisar cuando el fichero
cambio por fuera. Sin el modulo, el fichero entero falla en el import.

Todo corre contra DISCO REAL (tmp_path): sin mocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cognia.harness import checkpoints as ck


@pytest.fixture(autouse=True)
def almacen_aislado(tmp_path, monkeypatch):
    """El almacen NUNCA es el ~/.cognia real y cada test tiene su sesion."""
    monkeypatch.setenv("COGNIA_CHECKPOINTS_DIR", str(tmp_path / "checkpoints"))
    ck.nueva_sesion()


def _escribir_como_el_agente(ruta: Path, contenido: str, motivo: str) -> None:
    """Exactamente lo que haria tools.py con el checkpoint cableado."""
    previo = ruta.read_text(encoding="utf-8") if ruta.exists() else None
    ck.registrar(ruta, previo, motivo, contenido_nuevo=contenido)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


def test_deshacer_restaura_el_contenido_previo(tmp_path):
    f = tmp_path / "codigo.py"
    original = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    f.write_text(original, encoding="utf-8")

    # El modelo "acorta" el fichero: se pierde b().
    _escribir_como_el_agente(f, "def a():\n    return 1\n", "escribir_archivo")
    assert "def b" not in f.read_text(encoding="utf-8")

    resumen = ck.deshacer()
    assert "restaurado" in resumen
    # Ninguna mano externa lo toco: no debe haber aviso (multilinea en Windows
    # = CRLF en disco; si el hash se calculara en crudo, aqui saltaria falso).
    assert "AVISO" not in resumen
    assert f.read_text(encoding="utf-8") == original


def test_deshacer_borra_el_fichero_que_no_existia(tmp_path):
    f = tmp_path / "sub" / "nuevo.txt"
    _escribir_como_el_agente(f, "hola\n", "escribir_archivo")
    assert f.exists()

    resumen = ck.deshacer()
    assert "BORRADO" in resumen
    assert not f.exists()


def test_deshacer_es_idempotente(tmp_path):
    f = tmp_path / "uno.txt"
    f.write_text("viejo\n", encoding="utf-8")
    _escribir_como_el_agente(f, "nuevo\n", "escribir_archivo")

    ck.deshacer(1)
    f.write_text("editado a mano despues de deshacer\n", encoding="utf-8")
    segundo = ck.deshacer(1)

    assert "ya estaba deshecho" in segundo
    # No re-restaura: lo que el usuario escribio despues sigue intacto.
    assert f.read_text(encoding="utf-8") == "editado a mano despues de deshacer\n"


def test_avisa_si_el_fichero_cambio_despues_de_la_escritura(tmp_path):
    f = tmp_path / "compartido.txt"
    f.write_text("base\n", encoding="utf-8")
    _escribir_como_el_agente(f, "lo que escribio el agente\n", "escribir_archivo")
    f.write_text("lo que escribio el HUMANO despues\n", encoding="utf-8")

    resumen = ck.deshacer()
    assert "AVISO" in resumen and "CAMBIO" in resumen
    assert f.read_text(encoding="utf-8") == "base\n"
    # Lo descartado no se tira: queda resguardado y el resumen dice donde.
    descartados = list((Path(ck.dir_checkpoints()) / ck.sesion_actual()
                        / "blobs").glob("*-descartado.bak"))
    assert len(descartados) == 1
    assert "HUMANO" in descartados[0].read_text(encoding="utf-8")


def test_fichero_grande_no_se_versiona_y_deshacer_lo_avisa(tmp_path):
    f = tmp_path / "grande.txt"
    grande = "x" * (ck._MAX_BYTES_VERSIONADO + 10)
    f.write_text(grande, encoding="utf-8")

    entrada = ck.registrar(f, grande, "escribir_archivo", contenido_nuevo="chico")
    assert entrada["estado"] == "no_versionado"
    f.write_text("chico", encoding="utf-8")

    resumen = ck.deshacer()
    assert "NO restaurado" in resumen
    assert f.read_text(encoding="utf-8") == "chico"   # honesto: no lo toca
    # Y la entrada avanza (no traba el historial en un bucle).
    assert ck.listar()[0]["deshecho"] is True


def test_restaurar_hasta_revierte_en_bloque_y_en_orden_inverso(tmp_path):
    f = tmp_path / "acumulado.txt"
    f.write_text("v0\n", encoding="utf-8")
    for i in (1, 2, 3):
        _escribir_como_el_agente(f, f"v{i}\n", "escribir_archivo")
    otro = tmp_path / "otro.txt"
    _escribir_como_el_agente(otro, "creado\n", "escribir_archivo")

    resumen = ck.restaurar_hasta(2)
    assert "4 entrada(s)" not in resumen   # solo las #2, #3 y #4
    assert "3 entrada(s) revertida(s)" in resumen
    assert f.read_text(encoding="utf-8") == "v1\n"
    assert not otro.exists()
    # La #1 sigue viva: se puede seguir deshaciendo hasta el estado original.
    ck.deshacer()
    assert f.read_text(encoding="utf-8") == "v0\n"


def test_listar_devuelve_los_campos_y_la_mas_nueva_primero(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("aa\n", encoding="utf-8")
    _escribir_como_el_agente(a, "AA\n", "escribir_archivo")
    b = tmp_path / "b.txt"
    _escribir_como_el_agente(b, "BB\n", "editar_archivo")

    filas = ck.listar()
    assert [r["n"] for r in filas] == [2, 1]
    assert filas[0]["ruta"] == str(b.resolve())
    assert filas[0]["motivo"] == "editar_archivo"
    assert filas[0]["existia_antes"] is False
    assert filas[1]["existia_antes"] is True
    assert filas[1]["tam_previo"] == len("aa\n".encode("utf-8"))
    assert filas[0]["cuando"]


def test_diff_sesion_cuenta_lineas_mas_y_menos(tmp_path):
    f = tmp_path / "diff.txt"
    f.write_text("uno\ndos\ntres\n", encoding="utf-8")
    _escribir_como_el_agente(f, "uno\ndos\ntres\ncuatro\ncinco\n", "escribir_archivo")
    _escribir_como_el_agente(f, "uno\nDOS\ntres\ncuatro\ncinco\n", "editar_archivo")
    nuevo = tmp_path / "nacido.txt"
    _escribir_como_el_agente(nuevo, "linea\n", "escribir_archivo")

    d = ck.diff_sesion()
    por_ruta = {x["ruta"]: x for x in d["ficheros"]}
    tocado = por_ruta[str(f.resolve())]
    # Contra el estado ORIGINAL de la sesion: +cuatro +cinco +DOS, -dos.
    assert tocado["mas"] == 3 and tocado["menos"] == 1
    assert tocado["escrituras"] == 2
    creado = por_ruta[str(nuevo.resolve())]
    assert creado["mas"] == 1 and creado["menos"] == 0
    assert creado["nota"] == "creado en esta sesion"
    assert "2 fichero(s) tocado(s)" in d["texto"]


def test_none_sobre_fichero_existente_no_lo_borra(tmp_path):
    """Defensa: si el llamador pasa None (o el "" de tools.py) pero el fichero
    SI existe, manda el disco. Creerle al argumento haria que deshacer borrara
    trabajo del dueno, justo el desastre que esta pieza evita."""
    f = tmp_path / "existe.txt"
    f.write_text("contenido real\n", encoding="utf-8")

    entrada = ck.registrar(f, None, "escribir_archivo")
    assert entrada["existia_antes"] is True
    f.write_text("pisado\n", encoding="utf-8")

    ck.deshacer()
    assert f.exists()
    assert f.read_text(encoding="utf-8") == "contenido real\n"


def test_indice_append_only_y_sin_tmp_colgado(tmp_path):
    f = tmp_path / "idx.txt"
    for i in (1, 2, 3):
        _escribir_como_el_agente(f, f"v{i}\n", "escribir_archivo")
    ck.deshacer()

    dir_ses = Path(ck.dir_checkpoints()) / ck.sesion_actual()
    lineas = [json.loads(l) for l in
              (dir_ses / "indice.jsonl").read_text(encoding="utf-8").splitlines()]
    # Deshacer no borra historial: marca. Y no queda ningun .tmp a medias.
    assert [e["n"] for e in lineas] == [1, 2, 3]
    assert [e["deshecho"] for e in lineas] == [False, False, True]
    assert list(dir_ses.glob("*.tmp")) == []


def test_previo_vacio_sobre_fichero_existente_no_lo_vacia(tmp_path):
    """`tools.py` usa "" para 'no existia' (`read_text() if exists() else ""`).
    Si ese "" llega con el fichero PRESENTE (llamador que lo leyo antes de que
    otra tool lo creara, o que trunco su variable), creerle deja el fichero en
    CERO bytes al deshacer: la misma perdida de trabajo que el modulo evita.
    El docstring de registrar() promete que manda el DISCO tambien para ""."""
    f = tmp_path / "existe.txt"
    f.write_text("TRABAJO DEL DUENO\nlinea 2\n", encoding="utf-8")

    entrada = ck.registrar(f, "", "escribir_archivo", contenido_nuevo="pisado\n")
    assert entrada["existia_antes"] is True
    assert entrada["tam_previo"] == len("TRABAJO DEL DUENO\nlinea 2\n".encode())
    f.write_text("pisado\n", encoding="utf-8")

    ck.deshacer()
    assert f.read_text(encoding="utf-8") == "TRABAJO DEL DUENO\nlinea 2\n"


def test_fichero_vacio_de_verdad_sigue_registrandose(tmp_path):
    """La defensa del "" no puede romper el caso legitimo: un fichero vacio de
    verdad se relee como "" y se restaura vacio (no como 'no existia')."""
    f = tmp_path / "vacio.txt"
    f.write_text("", encoding="utf-8")

    entrada = ck.registrar(f, "", "escribir_archivo", contenido_nuevo="algo\n")
    assert entrada["existia_antes"] is True and entrada["estado"] == "guardado"
    f.write_text("algo\n", encoding="utf-8")

    ck.deshacer()
    assert f.exists() and f.read_text(encoding="utf-8") == ""


def test_restauracion_fallida_no_consume_la_entrada(tmp_path):
    """Si la reversion falla (respaldo ausente, fichero bloqueado, permisos) la
    entrada NO puede quedar marcada: marcarla la quema y el segundo /deshacer
    contesta 'ya estaba deshecho' con el fichero SIN restaurar."""
    f = tmp_path / "trabado.txt"
    f.write_text("original\n", encoding="utf-8")
    _escribir_como_el_agente(f, "nuevo\n", "escribir_archivo")
    blob = (Path(ck.dir_checkpoints()) / ck.sesion_actual() / "blobs" / "0001.bak")
    blob.unlink()                       # equivalente a EACCES / respaldo perdido

    primero = ck.deshacer()
    assert "ERROR" in primero and "PENDIENTE" in primero
    assert ck.listar()[0]["deshecho"] is False

    # Reintentable: restaurado el respaldo, el mismo /deshacer funciona.
    blob.write_text("original\n", encoding="utf-8", newline="")
    segundo = ck.deshacer()
    assert "restaurado" in segundo
    assert f.read_text(encoding="utf-8") == "original\n"
    assert ck.listar()[0]["deshecho"] is True


def test_restaurar_hasta_no_cuenta_ni_consume_las_fallidas(tmp_path):
    f = tmp_path / "bloque.txt"
    f.write_text("v0\n", encoding="utf-8")
    for i in (1, 2):
        _escribir_como_el_agente(f, f"v{i}\n", "escribir_archivo")
    (Path(ck.dir_checkpoints()) / ck.sesion_actual() / "blobs" / "0001.bak").unlink()

    resumen = ck.restaurar_hasta(1)
    assert "1 entrada(s) revertida(s)" in resumen and "1 FALLIDA(s)" in resumen
    pendientes = [r["n"] for r in ck.listar() if not r["deshecho"]]
    assert pendientes == [1]


def test_linea_corrupta_no_hace_que_se_pise_el_blob_de_otra_entrada(tmp_path):
    """`entradas[-1]['n'] + 1` reusaba el n de una entrada cuya linea se salto
    por corrupta: el blob NNNN.bak se sobrescribia y deshacer habria restaurado
    el contenido de OTRA escritura."""
    f = tmp_path / "colision.txt"
    f.write_text("v0\n", encoding="utf-8")
    for i in (1, 2):
        _escribir_como_el_agente(f, f"v{i}\n", "escribir_archivo")

    idx = Path(ck.dir_checkpoints()) / ck.sesion_actual() / "indice.jsonl"
    lineas = idx.read_text(encoding="utf-8").splitlines()
    lineas[1] = lineas[1][: len(lineas[1]) // 2]        # json truncado
    idx.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    _escribir_como_el_agente(f, "v3\n", "escribir_archivo")
    ns = [r["n"] for r in ck.listar()]
    assert len(ns) == len(set(ns)), f"n reusado: {ns}"
    blobs = Path(ck.dir_checkpoints()) / ck.sesion_actual() / "blobs"
    assert (blobs / "0002.bak").read_text(encoding="utf-8") == "v1\n"


def test_byte_invalido_en_el_indice_no_mata_el_historial(tmp_path):
    """read_text(utf-8) lanzaba UnicodeDecodeError por UN byte malo y se caian
    listar/deshacer/diff enteros — lo contrario de 'saltar la linea corrupta'."""
    f = tmp_path / "sano.txt"
    f.write_text("antes\n", encoding="utf-8")
    _escribir_como_el_agente(f, "despues\n", "escribir_archivo")
    idx = Path(ck.dir_checkpoints()) / ck.sesion_actual() / "indice.jsonl"
    with open(idx, "ab") as fh:
        fh.write(b"\xff\xfe basura no-utf8\n")

    assert [r["n"] for r in ck.listar()] == [1]
    assert "restaurado" in ck.deshacer()
    assert f.read_text(encoding="utf-8") == "antes\n"
    assert ck.diff_sesion()["sesion"] == ck.sesion_actual()


def test_registrar_nunca_lanza(tmp_path):
    """Contrato explicito del docstring: un fallo del almacen no puede abortar
    la escritura del agente. Solo se atrapaba OSError."""
    assert ck.registrar(tmp_path / "x.txt", None, motivo=object()) == {}
    assert ck.registrar(None, None, "ruta invalida") == {}
    # Y el almacen sigue usable despues del fallo.
    assert ck.registrar(tmp_path / "y.txt", None, "ok")["n"] >= 1


def test_deshacer_con_n_invalido_no_lanza(tmp_path):
    ck.registrar(tmp_path / "z.txt", None, "w")
    assert "invalido" in ck.deshacer("abc")
    assert "invalido" in ck.restaurar_hasta("abc")
    assert ck.listar()[0]["deshecho"] is False


def test_unicode_y_crlf_sobreviven_el_round_trip(tmp_path):
    """Rutas y contenido no-ASCII: el indice es JSON utf-8 y los blobs se leen
    con newline='' (sin traduccion), asi que el texto vuelve igual."""
    d = tmp_path / "café ñandú"
    d.mkdir()
    f = d / "acentuado.txt"
    original = "año\r\nmañana — ✓ 日本語\r\n"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        fh.write(original)

    _escribir_como_el_agente(f, "pisado\n", "escribir_archivo")
    ck.deshacer()
    with open(f, "r", encoding="utf-8", newline="") as fh:
        assert fh.read() == original
    assert ck.listar()[0]["ruta"] == str(f.resolve())


def test_deshacer_no_convierte_un_fichero_LF_en_CRLF(tmp_path):
    """El caso REAL: un .py del dueno en un repo (saltos LF, que es lo que deja
    git en Windows). El agente lo pisa con `write_text` (que CRLF-iza) y el
    dueno hace /deshacer. Restaurar con `write_text` devolvia el contenido pero
    con CRLF: el fichero quedaba modificado en TODAS sus lineas y el diff de
    git no volvia a cero, o sea que "deshacer" no deshacia.
    """
    f = tmp_path / "modulo.py"
    original = b"def a():\n    return 1\n\ndef b():\n    return 2\n"
    f.write_bytes(original)

    _escribir_como_el_agente(f, "def a():\n    return 1\n", "escribir_archivo")
    assert b"\r\n" in f.read_bytes()          # el agente SI CRLF-iza al escribir

    resumen = ck.deshacer()
    assert "restaurado" in resumen and "AVISO" not in resumen
    assert f.read_bytes() == original         # byte a byte, LF incluidos


def test_deshacer_conserva_CRLF_cuando_el_original_era_CRLF(tmp_path):
    """La otra mitad del contrato: no se "arregla" a LF lo que estaba en CRLF."""
    f = tmp_path / "crlf.txt"
    original = b"uno\r\ndos\r\n"
    f.write_bytes(original)

    _escribir_como_el_agente(f, "otra cosa\n", "escribir_archivo")
    ck.deshacer()
    assert f.read_bytes() == original


def test_fichero_enorme_no_se_lee_a_RAM_y_reporta_su_tamano(tmp_path):
    """Un binario/ilegible por encima del limite se descartaba DESPUES de
    leerlo entero (la proteccion del limite llegaba tarde) y la entrada
    quedaba con tam_previo=0, asi que el aviso de deshacer mentia sobre lo que
    no se respaldo. El tamaño sale del stat, antes de tocar el contenido."""
    f = tmp_path / "gordo.bin"
    tam = ck._MAX_BYTES_VERSIONADO + 4096
    f.write_bytes(b"\x00\xff" * (tam // 2))

    entrada = ck.registrar(f, None, "escribir_archivo", contenido_nuevo="x")
    assert entrada["estado"] == "no_versionado"
    assert entrada["existia_antes"] is True
    assert entrada["tam_previo"] == tam          # antes: 0
    assert str(tam) in ck.deshacer()             # el aviso dice el tamaño real
    assert f.stat().st_size == tam               # y no lo toca


def test_poda_no_borra_la_sesion_en_la_que_se_esta_escribiendo(tmp_path):
    """registrar(sesion=<vieja>) podaba justo despues de escribir y podia
    borrar el almacen recien creado."""
    f = tmp_path / "p.txt"
    vieja = ck.nueva_sesion()
    ck.nueva_sesion()                       # la sesion en curso es OTRA
    for _ in range(25):
        ck.nueva_sesion()
        ck.registrar(f, None, "relleno")

    entrada = ck.registrar(f, None, "en la vieja", sesion=vieja)
    assert entrada and vieja in ck.sesiones()
    assert [r["motivo"] for r in ck.listar(sesion=vieja)] == ["en la vieja"]


def test_poda_conserva_las_ultimas_20_sesiones(tmp_path):
    f = tmp_path / "poda.txt"
    creadas = []
    for i in range(23):
        creadas.append(ck.nueva_sesion())
        ck.registrar(f, None, f"sesion {i}")

    vivas = ck.sesiones()
    assert len(vivas) == 20
    assert set(vivas) == set(creadas[-20:])
