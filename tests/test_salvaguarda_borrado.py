# -*- coding: utf-8 -*-
"""
tests/test_salvaguarda_borrado.py
=================================
Regresion de la PERDIDA DE DATOS REAL del 2026-08-25: tres capturas del dueno
(105.605 / 189.239 / 207.974 bytes) borradas por el agente con
COGNIA_ACCESO_TOTAL=1 y NO recuperables — `del` no pasa por la papelera de
Windows y no habia instantanea.

La causa inmediata fue un agujero del clasificador (`cd <carpeta> && del *`
se juzgaba por segmentos y el `cd` era invisible para el `del`), y ese
agujero lo cierra tests/test_sentinel_gate_shell.py. Lo que mide ESTE fichero
es lo otro: que un borrado masivo no dependa SOLO de acertar el juicio.

    1. PAPELERA      lo que quita borrar_archivo se mueve a
                     ~/.cognia/papelera/<dia>/<lote>/ con su ruta original
                     debajo; /deshacer-borrado lo devuelve BYTE A BYTE.
    2. INVENTARIO    la lista (ruta + bytes + mtime + sha256) se escribe en
                     el indice jsonl ANTES de mover nada.
    3. TOPE          mas de N ficheros (config 'borrado_max_ficheros',
                     default 10) exige confirmacion HUMANA aunque
                     COGNIA_ACCESO_TOTAL=1 y aunque el modo de permiso sea
                     'bypass'.
    4. NUNCA DURO    si la papelera falla, los ficheros se quedan donde
                     estan; jamas se degrada a unlink().

NADA se ejecuta fuera de tmp_path: el sandbox son 12 ficheros de mentira y el
workspace del agente se re-apunta ahi. Lo del shell se mide con evaluar_shell
(juicio, sin ejecutar) y con el audit del centinela redirigido a tmp.
"""
from __future__ import annotations

import hashlib
import json

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T
from cognia.harness import papelera as P


# ── sandbox ────────────────────────────────────────────────────────────────

def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Workspace del agente + papelera, los dos dentro de tmp_path."""
    ws = tmp_path / "sandbox"
    ws.mkdir()
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("COGNIA_PAPELERA_DIR", str(tmp_path / "papelera"))
    monkeypatch.delenv("COGNIA_BORRADO_MAX_FICHEROS", raising=False)
    monkeypatch.delenv("BORRADO_MAX_FICHEROS", raising=False)
    monkeypatch.delenv("COGNIA_ACCESO_TOTAL", raising=False)
    # El config.env del dueno no decide el veredicto de un test.
    monkeypatch.setattr(P, "_config", lambda clave: {
        "borrado_max_ficheros": "", "borrado_papelera": "",
        "borrado_papelera_dias": ""}.get(clave, ""))
    return ws


def _sembrar(ws, n=12, prefijo="captura"):
    """n ficheros con contenido DISTINTO (para probar identidad byte a byte)."""
    hechos = []
    for i in range(n):
        f = ws / f"{prefijo}_{i:02d}.png"
        f.write_bytes(bytes([i]) * (100 + i) + b"\x00\xff datos " + str(i).encode())
        hechos.append(f)
    return hechos


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _indice(tmp_path):
    dia = P._dia()
    return P.dir_papelera() / dia / "indice.jsonl"


def _lineas(tmp_path):
    ruta = _indice(tmp_path)
    if not ruta.is_file():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


# ── 1. PAPELERA: borrar no destruye ────────────────────────────────────────

def test_un_borrado_va_a_la_papelera_y_no_desaparece(sandbox, tmp_path):
    f = sandbox / "temporal.txt"
    f.write_text("contenido que importa", encoding="utf-8")
    antes = _sha(f)

    out = T.run_tool("borrar_archivo", "temporal.txt", _ctx())

    assert "OK" in out and "papelera" in out
    assert not f.exists()                       # del workspace SI se fue
    movidos = [l for l in _lineas(tmp_path) if l.get("evento") == "movido"]
    assert len(movidos) == 1
    copia = tmp_path / "papelera"                # sigue existiendo, entero
    encontrados = [p for p in copia.rglob("temporal.txt")]
    assert len(encontrados) == 1
    assert _sha(encontrados[0]) == antes


def test_la_papelera_conserva_la_ruta_original(sandbox, tmp_path):
    sub = sandbox / "fotos" / "2026"
    sub.mkdir(parents=True)
    f = sub / "a.png"
    f.write_bytes(b"png")
    T.run_tool("borrar_archivo", str(f), _ctx())
    movido = [l for l in _lineas(tmp_path) if l.get("evento") == "movido"][0]
    destino = movido["destino"].replace("\\", "/")
    # La ruta ORIGINAL viaja debajo del lote (sin los dos puntos de la unidad)
    # MIENTRAS quepa: desde el 2026-08-25, si el destino se pasa de MAX_PATH la
    # clave se aplana (ver _clave_ruta) porque un borrado ya aprobado no puede
    # fallar por la longitud. En los dos casos la verdad esta en el indice, que
    # es lo que lee restaurar(): eso es lo que se afirma aqui.
    assert movido["ruta"] == str(f)
    if len(str(f)) + len(str(P.dir_papelera())) < 200:
        assert destino.endswith("fotos/2026/a.png")
    else:
        assert destino.endswith("a.png")            # nombre plano y corto
    assert P.restaurar()["restaurados"]
    assert f.read_bytes() == b"png"


# ── 2. INVENTARIO ANTES de mover ───────────────────────────────────────────

def test_el_inventario_se_escribe_antes_de_mover(sandbox, tmp_path):
    ficheros = _sembrar(sandbox, 12)
    esperado = {str(f): f.stat().st_size for f in ficheros}

    T.run_tool("borrar_archivo", "*.png", _ctx(confirm=lambda k, d: True))

    filas = _lineas(tmp_path)
    eventos = [l["evento"] for l in filas]
    # cabecera -> las 12 lineas de inventario -> recien despues los movimientos
    assert eventos[0] == "lote"
    assert eventos[1:13] == ["inventario"] * 12
    assert eventos[13:25] == ["movido"] * 12
    inv = {l["ruta"]: l for l in filas if l["evento"] == "inventario"}
    assert {r: v["bytes"] for r, v in inv.items()} == esperado
    for fila in inv.values():
        assert fila["mtime"] and fila["sha256"]      # ruta + bytes + mtime (+sha)


def test_el_inventario_sobrevive_a_que_el_movimiento_falle(sandbox, tmp_path,
                                                           monkeypatch):
    """Si mover falla, el fichero SIGUE en su sitio y el indice lo cuenta.

    Lo que nunca puede pasar es que un fallo de papelera degrade a unlink()."""
    ficheros = _sembrar(sandbox, 3)
    import shutil as _sh
    monkeypatch.setattr(P.shutil, "move",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))

    out = T.run_tool("borrar_archivo", "*.png", _ctx())

    assert "ERROR" in out and "siguen en su sitio" in out
    assert all(f.exists() for f in ficheros)     # NADA se perdio
    filas = _lineas(tmp_path)
    assert [l["evento"] for l in filas if l["evento"] == "inventario"]
    assert len([l for l in filas if l["evento"] == "fallo"]) == 3


# ── 3. TOPE DE VOLUMEN ─────────────────────────────────────────────────────

def test_doce_ficheros_pasan_del_tope_y_exigen_confirmacion(sandbox):
    ficheros = _sembrar(sandbox, 12)
    out = T.run_tool("borrar_archivo", "*.png", _ctx())      # sin canal
    assert "BLOQUEADO" in out and "12" in out and "10" in out
    assert all(f.exists() for f in ficheros)


def test_diez_ficheros_no_llegan_al_tope(sandbox):
    ficheros = _sembrar(sandbox, 10)
    out = T.run_tool("borrar_archivo", "*.png", _ctx())
    assert "OK" in out and not any(f.exists() for f in ficheros)


def test_acceso_total_no_salta_el_tope(sandbox, monkeypatch):
    """El flag que auto-aprueba los CONFIRM del centinela NO toca este freno.

    Es el escenario exacto de la perdida: sesion del control remoto con
    COGNIA_ACCESO_TOTAL=1, donde cualquier gate que se apague por config ya
    estaba apagado."""
    monkeypatch.setenv("COGNIA_ACCESO_TOTAL", "1")
    ficheros = _sembrar(sandbox, 12)
    out = T.run_tool("borrar_archivo", "*.png", _ctx())
    assert "BLOQUEADO" in out
    assert all(f.exists() for f in ficheros)


def test_el_modo_bypass_tampoco_salta_el_tope(monkeypatch):
    from cognia.console import permissions as perm
    monkeypatch.setenv("COGNIA_PERMISSION_MODE", "bypass")
    assert perm.needs_confirmation("shell_exec", "git status") is False
    assert perm.needs_confirmation("borrado_masivo", "borrar 12 ficheros") is True


def test_el_dueno_confirma_y_entonces_si_borra(sandbox, tmp_path):
    ficheros = _sembrar(sandbox, 12)
    vistos = []

    def _confirm(kind, detalle):
        vistos.append((kind, detalle))
        return True

    out = T.run_tool("borrar_archivo", "*.png", _ctx(confirm=_confirm))

    assert "OK" in out and not any(f.exists() for f in ficheros)
    # la peticion dice CUANTOS y EN QUE CARPETA (requisito del dueno)
    assert vistos and vistos[0][0] == "borrado_masivo"
    assert "12" in vistos[0][1] and str(sandbox) in vistos[0][1]


def test_el_tope_es_configurable(sandbox, monkeypatch):
    monkeypatch.setenv("COGNIA_BORRADO_MAX_FICHEROS", "2")
    monkeypatch.setattr(P, "_config", lambda clave: (
        "2" if clave == "borrado_max_ficheros" else ""))
    ficheros = _sembrar(sandbox, 3)
    assert P.tope_ficheros() == 2
    out = T.run_tool("borrar_archivo", "*.png", _ctx())
    assert "BLOQUEADO" in out and all(f.exists() for f in ficheros)


def test_un_tope_absurdo_cae_al_default(sandbox, monkeypatch):
    for valor in ("0", "-3", "muchos", ""):
        monkeypatch.setattr(P, "_config", lambda c, v=valor: (
            v if c == "borrado_max_ficheros" else ""))
        assert P.tope_ficheros() == 10


# ── 4. RESTAURACION byte-identica ──────────────────────────────────────────

def test_los_doce_se_restauran_byte_identicos(sandbox):
    ficheros = _sembrar(sandbox, 12)
    antes = {str(f): _sha(f) for f in ficheros}

    T.run_tool("borrar_archivo", "*.png", _ctx(confirm=lambda k, d: True))
    assert not any(f.exists() for f in ficheros)

    res = P.restaurar()

    assert res["ok"] and len(res["restaurados"]) == 12
    assert not res["fallos"] and not res["conflictos"]
    assert {str(f): _sha(f) for f in ficheros} == antes


def test_restaurar_no_pisa_lo_que_hay_ahora(sandbox):
    f = sandbox / "a.txt"
    f.write_text("viejo", encoding="utf-8")
    T.run_tool("borrar_archivo", "a.txt", _ctx())
    f.write_text("NUEVO", encoding="utf-8")          # el dueno lo rehizo

    res = P.restaurar()

    assert res["ok"] and res["conflictos"]
    assert f.read_text(encoding="utf-8") == "NUEVO"  # lo de ahora NO se toca
    assert (sandbox / "a.restaurado-1.txt").read_text(encoding="utf-8") == "viejo"


def test_restaurar_dos_veces_no_inventa_nada(sandbox):
    _sembrar(sandbox, 2)
    T.run_tool("borrar_archivo", "*.png", _ctx())
    assert P.restaurar()["ok"]
    segundo = P.restaurar()
    assert segundo["ok"] is False and "restaurar" in segundo["error"]


def test_lotes_lista_lo_que_hay_en_la_papelera(sandbox):
    _sembrar(sandbox, 2, prefijo="uno")
    T.run_tool("borrar_archivo", "uno_00.png", _ctx())
    T.run_tool("borrar_archivo", "uno_01.png", _ctx())
    lotes = P.lotes()
    assert len(lotes) == 2 and all(len(l["restaurables"]) == 1 for l in lotes)
    # el mas NUEVO primero: restaurar() sin argumento coge ese
    assert P.restaurar()["lote"] == lotes[0]["lote"]


# ── 5. lo de siempre sigue igual ───────────────────────────────────────────

def test_fuera_del_workspace_lo_decide_un_humano(sandbox, tmp_path):
    """Cambio del 2026-08-25 (tarde): una ruta de fuera ya no es un ERROR
    seco -- eso dejaba a Cognia sin poder limpiar NADA del dueno, ni
    preguntando (medido tecleando: tres bloqueos y "no logro la tarea").
    Ahora la via REVERSIBLE puede salir del workspace si un humano lo
    confirma en el turno; sin canal humano se niega, que es el escenario
    exacto del incidente (remoto desatendido). El borrado por shell, que no
    tiene vuelta atras, sigue siendo BLOCK para todos."""
    fuera = tmp_path / "fuera.txt"
    fuera.write_text("del dueno", encoding="utf-8")
    # sin canal humano
    out = T.run_tool("borrar_archivo", str(fuera), {})
    assert "BLOQUEADO" in out and fuera.exists()
    # el dueno dice que no
    out = T.run_tool("borrar_archivo", str(fuera), {"confirm": lambda *a: False})
    assert "BLOQUEADO" in out and fuera.exists()
    # el dueno dice que si: a la papelera, recuperable
    out = T.run_tool("borrar_archivo", str(fuera), {"confirm": lambda *a: True})
    assert "OK" in out and not fuera.exists()
    P.restaurar()
    assert fuera.read_text(encoding="utf-8") == "del dueno"


def test_directorio_e_inexistente_siguen_siendo_error(sandbox):
    assert "no existe" in T.run_tool("borrar_archivo", "nada.txt", _ctx())
    (sandbox / "carpeta").mkdir()
    out = T.run_tool("borrar_archivo", "carpeta", _ctx())
    assert "ERROR" in out and (sandbox / "carpeta").is_dir()


def test_un_comodin_que_no_casa_no_borra_nada(sandbox):
    _sembrar(sandbox, 2)
    out = T.run_tool("borrar_archivo", "*.jpg", _ctx())
    assert "ERROR" in out and "ningun fichero coincide" in out


def test_varias_rutas_separadas_por_pipe(sandbox):
    a, b = sandbox / "a.txt", sandbox / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    out = T.run_tool("borrar_archivo", "a.txt | b.txt", _ctx())
    assert "OK" in out and not a.exists() and not b.exists()
    assert P.restaurar()["ok"] and a.read_text(encoding="utf-8") == "a"


# ── 6. el gate del SHELL nombra la puerta buena ────────────────────────────

def test_el_gate_manda_a_la_tool_de_papelera(tmp_path, monkeypatch):
    """Un borrado por shell no se puede interceptar desde Python: lo unico
    que se puede hacer es que la negativa diga cual es la via reversible.

    Solo JUICIO: evaluar_shell no ejecuta nada. El audit se redirige a tmp."""
    import cognia.agent.sentinel as S
    monkeypatch.setattr(S, "_AUDIT", tmp_path / "audit.jsonl")

    ok, msg = S.evaluar_shell(r'del "C:\Users\usuario\Pictures\Screenshots\*.png"', {})
    assert ok is False
    assert "borrar_archivo" in msg and "papelera" in msg

    # y no se cuela como consejo donde no viene a cuento
    ok2, msg2 = S.evaluar_shell("shutdown /s /t 0", {})
    assert ok2 is False and "borrar_archivo" not in msg2


def test_la_puerta_del_cli_existe():
    """CLAUDE.md: sin puerta visible, la capacidad no esta entregada."""
    import cognia.cli as cli
    assert callable(cli._slash_deshacer_borrado)
    assert "/deshacer-borrado" in cli._CMD_DESCRIPTIONS


def test_un_nombre_con_corchetes_no_se_confunde_con_un_comodin(sandbox):
    f = sandbox / "captura [1].png"
    f.write_bytes(b"x")
    out = T.run_tool("borrar_archivo", "captura [1].png", _ctx())
    assert "OK" in out and not f.exists()
    assert P.restaurar()["ok"] and f.read_bytes() == b"x"


def test_el_modo_sistema_dice_donde_esta_lo_borrado(sandbox, monkeypatch):
    """Con borrado_papelera=sistema el fichero va a la papelera de Windows y
    NO se puede restaurar desde aqui. El limite se dice, no se calla."""
    f = sandbox / "x.txt"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(P, "_a_sistema", lambda p: "")      # sin tocar el SO
    P.enviar([str(f)], motivo="prueba", forzar_modo="sistema")
    res = P.restaurar()
    assert res["ok"] is False and "papelera de Windows" in res["error"]


def test_una_ruta_larga_no_rompe_la_papelera(tmp_path, monkeypatch):
    """MAX_PATH: el destino sumaba la ruta original ENTERA bajo el lote y en
    Windows reventaba con "[WinError 206] ... demasiado largo" -- con el dueno
    ya habiendo confirmado el borrado. Un borrado APROBADO que falla es peor
    que uno denegado: el agente lo reintenta por otras vias (medido el
    2026-08-25 tecleando: tras el fallo probo `del` y `move`).

    Ahora, cuando el destino se pasa, la clave es un nombre plano y corto; la
    ruta original vive en el indice y restaurar() la usa igual."""
    monkeypatch.setenv("COGNIA_PAPELERA_DIR", str(tmp_path / "papelera"))
    # Dos tramos largos y un nombre largo: pasa de 200 chars sin llegar al
    # limite que impide CREARLO (Windows no deja ni mkdir por encima de 260).
    hondo = tmp_path / ("d" * 60)
    hondo.mkdir(parents=True)
    f = hondo / ("Captura de pantalla 2026-08-21 120000 " + "x" * 20 + ".png")
    f.write_text("captura", encoding="utf-8")
    assert len(str(f)) > 200, len(str(f))

    parte = P.enviar([str(f)], motivo="ruta larga", tool="test")
    assert not parte["fallos"], parte["fallos"]
    assert len(parte["movidos"]) == 1
    assert not f.exists()

    assert P.restaurar()["restaurados"]
    assert f.read_text(encoding="utf-8") == "captura"
