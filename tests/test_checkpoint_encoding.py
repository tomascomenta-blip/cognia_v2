# -*- coding: utf-8 -*-
"""
Regresion (2026-08-13): la red de seguridad guardaba el fichero YA corrompido.

DOS defectos, los dos reproducidos en disco antes de parchear:

(1) ENCODING. `interceptor._leer_previo` leia con `errors='replace'`, y ese
    valor es LO UNICO que ve `checkpoints.registrar` sobre el estado previo.
    Sobre un fichero latin-1 devolvia texto NO vacio lleno de U+FFFD, asi que
    la defensa de `registrar` (releer el disco y marcar 'no_versionado' cuando
    no es utf-8) no reponia nada: el blob se guardaba corrupto con
    estado='guardado' y /deshacer escribia los U+FFFD ENCIMA del original
    contestando "restaurado". La red destruyendo el fichero que venia a salvar.
    Medido antes del fix:
        bytes originales  b'... ni\\xf1o, a\\xf1o, coraz\\xf3n\\n'
        tras /deshacer    b'... ni\\xef\\xbf\\xbdo, a\\xef\\xbf\\xbdo, ...'
        deshacer -> "restaurado al estado previo (35 chars)"

(2) WORKSPACE. `interceptor.raiz_proyecto` importaba AGENT_WORKSPACE_ROOT como
    constante de IMPORT-TIME mientras las tools escriben por
    `dev_tools._root_actual()` (call-time). Si el workspace cambiaba despues del
    primer import (REPL largo, servidor remoto que fija el ws por sesion), el
    checkpoint se registraba en el workspace VIEJO y la escritura quedaba SIN
    RED. Es el mismo bug que dev_tools ya cazo en 2026-07-21.

Todo corre contra DISCO REAL (tmp_path) y comprueba BYTES: comparar `str` es
justo lo que no distingue un acento de un U+FFFD despues de decodificar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cognia.agents.workers import dev_tools
from cognia.harness import checkpoints as ck
from cognia.harness import interceptor

# Contenido latin-1 con acentos: NO es utf-8 decodificable.
_LATIN1 = "cafe con leche: ni\xf1o, a\xf1o, coraz\xf3n\n".encode("latin-1")
# El U+FFFD (REPLACEMENT CHARACTER) tal como queda en disco al escribirlo utf-8.
_FFFD = "�".encode("utf-8")


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    """Almacen, workspace y sesion propios. Nunca el ~/.cognia real."""
    monkeypatch.setenv("COGNIA_CHECKPOINTS_DIR", str(tmp_path / "checkpoints"))
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir(exist_ok=True)
    # La variable de modulo tiene precedencia sobre la env var en
    # `_root_actual()`; se deja en su valor de import para que mande la env var,
    # que es lo que estos tests mueven.
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", dev_tools._ROOT_DE_IMPORT)
    ck.nueva_sesion()
    yield
    ck._SESION = None


def _escribe_el_agente(ruta: Path, nuevo: bytes, ctx: dict | None = None) -> dict:
    """El camino REAL: interceptor.antes (que registra el checkpoint) y despues
    la escritura de la tool. Devuelve la entrada del checkpoint."""
    ctx = ctx if ctx is not None else {}
    interceptor.antes("escribir_archivo", f"{ruta} | contenido", ctx)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(nuevo)
    return ctx.get("_harness_checkpoint") or {}


# ── (1) encoding ──────────────────────────────────────────────────────────────

def test_leer_previo_devuelve_none_sobre_latin1(tmp_path):
    """El lector del interceptor no debe inventar U+FFFD: o el texto exacto, o
    None. Sin esto, `registrar` cree al llamador y guarda basura."""
    f = tmp_path / "ws" / "acentos.txt"
    f.write_bytes(_LATIN1)
    assert interceptor._leer_previo(f) is None


def test_leer_previo_conserva_los_saltos_exactos(tmp_path):
    """utf-8 con CRLF: se respalda TAL CUAL (newline=''), no normalizado; si no,
    /deshacer convierte un fichero LF del dueno en CRLF entero."""
    f = tmp_path / "ws" / "crlf.txt"
    f.write_bytes(b"uno\r\ndos\r\n")
    assert interceptor._leer_previo(f) == "uno\r\ndos\r\n"


def test_latin1_queda_no_versionado_y_deshacer_avisa(tmp_path):
    """El caso completo: fichero latin-1 -> estado='no_versionado' y /deshacer
    AVISA en vez de decir "restaurado" sobre un fichero destruido."""
    f = tmp_path / "ws" / "acentos.txt"
    f.write_bytes(_LATIN1)

    entrada = _escribe_el_agente(f, b"lo que escribio el agente\n")

    assert entrada.get("estado") == "no_versionado", entrada
    assert not entrada.get("blob"), "no debe existir blob de un previo ilegible"
    # El tamaño real del disco, no el 0 que dejaba la lectura fallida.
    assert entrada.get("tam_previo") == len(_LATIN1)

    resumen = ck.deshacer()
    assert "NO restaurado" in resumen, resumen
    assert "restaurado al estado previo" not in resumen, resumen

    # Y sobre todo: NADIE escribio U+FFFD en el fichero del dueno.
    assert _FFFD not in f.read_bytes()


def test_registrar_ignora_el_texto_corrupto_del_llamador(tmp_path):
    """La defensa vive en el ALMACEN, no solo en el interceptor: cualquier
    llamador que lea con errors='replace' (tools.py lo hacia) recibe el mismo
    veredicto. Manda el DISCO."""
    f = tmp_path / "ws" / "otro.txt"
    f.write_bytes(_LATIN1)
    corrupto = f.read_bytes().decode("utf-8", errors="replace")
    assert "�" in corrupto          # el llamador trae basura, no vacio

    entrada = ck.registrar(f, corrupto, "escribir_archivo")
    assert entrada.get("estado") == "no_versionado", entrada
    assert not entrada.get("blob")


def test_utf8_con_acentos_sigue_restaurando_byte_exacto(tmp_path):
    """Control: lo que SI es utf-8 debe seguir versionandose y volver IDENTICO
    en bytes. Un fix que apagara el respaldo entero tambien pasaria los tests de
    arriba; este es el que lo impide."""
    f = tmp_path / "ws" / "bueno.py"
    original = "# niño año corazón\r\ndef a():\r\n    return 1\r\n".encode("utf-8")
    f.write_bytes(original)

    entrada = _escribe_el_agente(f, b"def a():\n    return 2\n")
    assert entrada.get("estado") == "guardado", entrada

    resumen = ck.deshacer()
    assert "restaurado" in resumen, resumen
    assert f.read_bytes() == original


# ── (2) workspace call-time ───────────────────────────────────────────────────

def test_el_checkpoint_sigue_al_workspace_que_cambio(tmp_path, monkeypatch):
    """Cambiar COGNIA_AGENT_WORKSPACE DESPUES de importar dev_tools tiene que
    mover tambien el checkpoint: la tool escribe por _root_actual(), y si el
    interceptor se queda en el workspace de import la escritura va sin red."""
    nuevo = tmp_path / "ws_nuevo"
    nuevo.mkdir()
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(nuevo))

    ctx: dict = {}
    interceptor.antes("escribir_archivo", "relativo.txt | hola", ctx)
    entrada = ctx.get("_harness_checkpoint") or {}

    registrada = Path(entrada.get("ruta", ""))
    assert registrada == (nuevo / "relativo.txt").resolve(), entrada
    # Y la raiz que ve el resto del arnes (hooks, verificacion) es la misma.
    assert interceptor.raiz_proyecto({}) == Path(str(nuevo))


def test_el_ctx_sigue_mandando_sobre_el_workspace(tmp_path, monkeypatch):
    """El workspace del ctx (el que pasa el servidor remoto por sesion) sigue
    ganando: el fix no debe atarlo todo a la env var."""
    otro = tmp_path / "ws_del_ctx"
    otro.mkdir()
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path / "ws"))
    assert interceptor.raiz_proyecto({"workspace": str(otro)}) == otro
