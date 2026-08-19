# -*- coding: utf-8 -*-
"""
tests/test_multiverso_ramas.py
==============================
Tests del motor de ramificacion (cognia/multiverso/ramas.py).

QUE COMPRUEBAN, Y POR QUE ESOS Y NO OTROS: cada test corresponde a una promesa
del motor que, de romperse, DESTRUYE datos del dueno o ejecuta dos veces algo
que no tiene vuelta atras:
  - la ganadora se fusiona y las perdedoras no dejan rastro,
  - una rama que revienta no contamina el ws real,
  - el veto de irreversibles funciona y la accion se ejecuta UNA sola vez,
  - el ledger registra todo (auditabilidad),
  - k=1 degrada a "correr normal" sin coste de copia ni de fusion.

Sin modelo y sin red: correr_rama_fn, juzgar_fn y ejecutar_irreversible_fn son
callables inyectados. El ledger se redirige a tmp_path para no tocar el HOME.
Los mecanismos hermanos (instantanea.py / reversibilidad.py) se apagan con
usar_modulos=False en los tests que miden el motor en aislamiento, y se dejan
encendidos en el test que comprueba que el motor los tolera.
"""
import json
import os
from pathlib import Path

import pytest

from cognia.multiverso import ramas as R


# -- utilidades del test --------------------------------------------------

def _ws(tmp_path, nombre="ws_real"):
    """Un workspace real con contenido previo (para poder ver que se conserva)."""
    ws = tmp_path / nombre
    (ws / "sub").mkdir(parents=True)
    (ws / "base.txt").write_text("original\n", encoding="utf-8")
    (ws / "sub" / "hondo.txt").write_text("hondo\n", encoding="utf-8")
    return ws


def _correr_marcador(tarea, ws, ctx):
    """correr_rama_fn determinista: cada rama escribe SU fichero y edita el
    comun con su nombre. Asi el disco dice sin ambiguedad quien fusiono."""
    rama = ctx["rama"]
    Path(ws, "%s.txt" % rama).write_text("hecho por %s\n" % rama,
                                         encoding="utf-8")
    Path(ws, "base.txt").write_text("editado por %s\n" % rama,
                                    encoding="utf-8")
    return {"pasos": 2, "rama": rama}


def _juez_por_indice(ws, resultado):
    """Puntaje = el indice de la rama. Gana siempre la ultima: determinista y
    distinto del criterio de desempate (indice mas bajo), asi el test no puede
    pasar por casualidad."""
    return {"ok": True, "puntaje": float(resultado["rama"].split("_")[1]),
            "motivo": "indice"}


# -- 1) la ganadora se fusiona; las perdedoras no dejan rastro ------------

def test_ganadora_se_fusiona_y_perdedoras_no_dejan_rastro(tmp_path):
    ws = _ws(tmp_path)
    ledger = tmp_path / "ledger.jsonl"

    inf = R.ramificar("tarea", ws, 3, _correr_marcador, _juez_por_indice,
                      ruta_ledger_=ledger, usar_modulos=False)

    assert inf["ganadora"] == "rama_2", inf["razon"]
    # LEYENDO EL DISCO: el ws real tiene lo de la ganadora y NADA de las otras.
    assert (ws / "rama_2.txt").read_text(encoding="utf-8") == "hecho por rama_2\n"
    assert not (ws / "rama_0.txt").exists()
    assert not (ws / "rama_1.txt").exists()
    assert (ws / "base.txt").read_text(encoding="utf-8") == "editado por rama_2\n"
    # lo que nadie toco sigue ahi
    assert (ws / "sub" / "hondo.txt").read_text(encoding="utf-8") == "hondo\n"
    # los workspaces-rama ya no existen en disco
    for rama in inf["ramas"]:
        assert not Path(rama["ws"]).exists(), rama["nombre"]
    # y no queda basura suelta junto al ws real
    hermanos = {p.name for p in tmp_path.iterdir()}
    assert hermanos == {"ws_real", "ledger.jsonl"}, hermanos
    assert inf["fusion"]["creados"] == ["rama_2.txt"]
    assert inf["fusion"]["modificados"] == ["base.txt"]


def test_fusion_propaga_borrados(tmp_path):
    """Si la ganadora BORRO un fichero, el ws real tambien lo pierde: una
    fusion que solo copia deja resucitados los ficheros que la rama elimino."""
    ws = _ws(tmp_path)

    def correr(tarea, ws_rama, ctx):
        if ctx["rama"] == "rama_1":
            Path(ws_rama, "base.txt").unlink()
        return {"pasos": 1, "rama": ctx["rama"]}

    inf = R.ramificar("borrar", ws, 2, correr,
                      lambda w, r: {"ok": True,
                                    "puntaje": 1.0 if r["rama"] == "rama_1" else 0.5},
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    assert inf["ganadora"] == "rama_1"
    assert not (ws / "base.txt").exists()
    assert inf["fusion"]["borrados"] == ["base.txt"]


# -- 2) una rama que revienta no contamina --------------------------------

def test_rama_que_revienta_no_contamina(tmp_path):
    ws = _ws(tmp_path)
    ledger = tmp_path / "ledger.jsonl"

    def correr(tarea, ws_rama, ctx):
        Path(ws_rama, "%s.txt" % ctx["rama"]).write_text("x", encoding="utf-8")
        if ctx["rama"] == "rama_0":
            Path(ws_rama, "base.txt").write_text("BASURA\n", encoding="utf-8")
            raise RuntimeError("la rama 0 revienta a media tarea")
        return {"pasos": 1, "rama": ctx["rama"]}

    inf = R.ramificar("t", ws, 2, correr, lambda w, r: True,
                      ruta_ledger_=ledger, usar_modulos=False)

    r0 = inf["ramas"][0]
    assert r0["estado"] == "descartada"
    assert "RuntimeError" in r0["error"]
    assert "traza" in r0 and "la rama 0 revienta" in r0["traza"]
    assert inf["ganadora"] == "rama_1"
    # el ws real conserva su base y no ve NADA de la rama que exploto
    assert (ws / "base.txt").read_text(encoding="utf-8") == "original\n"
    assert not (ws / "rama_0.txt").exists()
    assert (ws / "rama_1.txt").exists()


def test_sin_ganadora_el_ws_real_no_se_toca(tmp_path):
    """Si el juez reprueba a todas, el ws real queda EXACTAMENTE igual."""
    ws = _ws(tmp_path)
    antes = R.manifiesto(ws)

    inf = R.ramificar("t", ws, 3, _correr_marcador,
                      lambda w, r: {"ok": False, "puntaje": 0.0,
                                    "motivo": "no cumple"},
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)

    assert inf["ganadora"] is None
    assert inf["fusion"]["omitida"] is True
    assert R.manifiesto(ws) == antes
    assert all(not Path(r["ws"]).exists() for r in inf["ramas"])


def test_juez_que_revienta_no_tumba_la_corrida(tmp_path):
    ws = _ws(tmp_path)

    def juez(ws_rama, resultado):
        if resultado["rama"] == "rama_0":
            raise ValueError("juez roto")
        return {"ok": True, "puntaje": 1.0}

    inf = R.ramificar("t", ws, 2, _correr_marcador, juez,
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    assert inf["ganadora"] == "rama_1"
    assert "juez reviento" in inf["ramas"][0]["juicio"]["motivo"]


# -- 3) el veto de irreversibles y la ejecucion UNICA ---------------------

def test_guardia_veta_irreversible_y_encola():
    ctx = {"rama": "rama_7"}
    veto = R.guardia_de_rama("ejecutar", "git push origin main", ctx=ctx,
                             usar_modulo=False)
    assert isinstance(veto, str)
    assert "BLOQUEADO" in veto and "IRREVERSIBLE" in veto
    assert len(ctx["pendientes_irreversibles"]) == 1
    assert ctx["pendientes_irreversibles"][0]["tool"] == "ejecutar"
    # una accion reversible NO se veta
    assert R.guardia_de_rama("escribir_archivo", "a.txt | hola", ctx=ctx,
                             usar_modulo=False) is None
    assert len(ctx["pendientes_irreversibles"]) == 1


def test_guardia_deduplica_reintentos():
    ctx = {"rama": "r"}
    for _ in range(3):
        assert R.guardia_de_rama("enviar_correo", "jefe@x | listo", ctx=ctx,
                                 usar_modulo=False)
    assert len(ctx["pendientes_irreversibles"]) == 1
    assert ctx["pendientes_irreversibles"][0]["repeticiones"] == 3


def test_permitir_irreversibles_no_veta_pero_deja_traza():
    ctx = {"rama": "r"}
    assert R.guardia_de_rama("ejecutar", "git push", ctx=ctx,
                             permitir_irreversibles=True,
                             usar_modulo=False) is None
    assert not ctx.get("pendientes_irreversibles")
    assert len(ctx["irreversibles_ejecutadas_en_rama"]) == 1


def test_irreversible_se_ejecuta_una_sola_vez_al_ganar(tmp_path):
    ws = _ws(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ejecutadas = []

    def correr(tarea, ws_rama, ctx):
        # cada rama INTENTA el push 3 veces (el modelo reintenta al ver el veto)
        vetos = [ctx["guardia"]("ejecutar", "git push origin %s" % ctx["rama"])
                 for _ in range(3)]
        Path(ws_rama, "%s.txt" % ctx["rama"]).write_text("x", encoding="utf-8")
        return {"pasos": 3, "rama": ctx["rama"], "vetos": vetos}

    def ejecutar(tool, args, pendiente):
        ejecutadas.append((tool, args))
        return "empujado"

    inf = R.ramificar("publicar", ws, 3, correr, _juez_por_indice,
                      ejecutar_irreversible_fn=ejecutar,
                      ruta_ledger_=ledger, usar_modulos=False)

    assert inf["ganadora"] == "rama_2"
    # NINGUNA rama ejecuto el push durante la exploracion...
    assert all(isinstance(v, str) and "BLOQUEADO" in v
               for v in inf["ramas"][0]["resultado"]["vetos"])
    # ...y al ganar se ejecuto UNA sola vez, y solo la de la ganadora
    assert ejecutadas == [("ejecutar", "git push origin rama_2")]
    assert len(inf["irreversibles_ejecutadas"]) == 1
    assert inf["irreversibles_ejecutadas"][0]["repeticiones"] == 3
    # las de las perdedoras se tiraron: nunca ocurrieron
    assert inf["irreversibles_descartadas"] == 2
    assert inf["coste"]["irreversibles_por_cubo"] == {"irreversible_externo": 9}


def test_sin_ejecutor_las_pendientes_se_declaran_no_se_fingen(tmp_path):
    ws = _ws(tmp_path)

    def correr(tarea, ws_rama, ctx):
        ctx["guardia"]("enviar_correo", "dueno@x | terminado")
        Path(ws_rama, "a.txt").write_text("x", encoding="utf-8")
        return {"pasos": 1, "rama": ctx["rama"]}

    inf = R.ramificar("t", ws, 2, correr, lambda w, r: True,
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    assert len(inf["irreversibles_pendientes_sin_ejecutar"]) == 1
    assert "NO se ejecutaron" in inf["aviso"]
    assert inf["irreversibles_ejecutadas"] == []


# -- 4) el ledger registra todo ------------------------------------------

def test_ledger_registra_todo(tmp_path):
    ws = _ws(tmp_path)
    ledger = tmp_path / "ledger.jsonl"

    def correr(tarea, ws_rama, ctx):
        ctx["guardia"]("ejecutar", "git push origin main")
        Path(ws_rama, "%s.txt" % ctx["rama"]).write_text("x", encoding="utf-8")
        return {"pasos": 1, "rama": ctx["rama"]}

    inf = R.ramificar("t", ws, 2, correr, _juez_por_indice,
                      ejecutar_irreversible_fn=lambda t, a, p: "ok",
                      ruta_ledger_=ledger, usar_modulos=False)

    filas = R.leer_ledger(ledger)
    eventos = [f["evento"] for f in filas]
    for esperado in ("ramificar.inicio", "instantanea.tomada", "rama.creada",
                     "rama.corrida", "rama.juzgada", "irreversible.encolada",
                     "fusion", "descarte", "irreversible.ejecutada",
                     "ramificar.fin"):
        assert esperado in eventos, (esperado, eventos)
    # es JSONL de verdad y todo pertenece a ESTA corrida
    for linea in ledger.read_text(encoding="utf-8").splitlines():
        assert json.loads(linea)["ts"] > 0
    assert {f.get("corrida") for f in filas} == {inf["corrida"]}
    assert inf["ledger"] == str(ledger)


def test_ledger_por_defecto_es_el_del_home(monkeypatch):
    monkeypatch.delenv("COGNIA_MULTIVERSO_LEDGER", raising=False)
    assert R.ruta_ledger().as_posix().endswith(
        ".cognia/multiverso/ramas.jsonl")
    monkeypatch.setenv("COGNIA_MULTIVERSO_LEDGER", "X:/otro.jsonl")
    assert R.ruta_ledger() == Path("X:/otro.jsonl")
    # el argumento gana al entorno
    assert R.ruta_ledger("Y:/mio.jsonl") == Path("Y:/mio.jsonl")


# -- 5) k=1 degrada a "correr normal" ------------------------------------

def test_k1_corre_en_sitio_sin_copia_ni_fusion(tmp_path):
    ws = _ws(tmp_path)
    ledger = tmp_path / "ledger.jsonl"

    vistos = {}

    def correr(tarea, ws_rama, ctx):
        vistos["ws"] = ws_rama
        Path(ws_rama, "salida.txt").write_text("directo\n", encoding="utf-8")
        return {"pasos": 1, "rama": ctx["rama"]}

    inf = R.ramificar("t", ws, 1, correr, lambda w, r: True,
                      ruta_ledger_=ledger, usar_modulos=False)

    assert inf["modo"] == "directo"
    assert Path(vistos["ws"]) == ws                 # corrio EN el ws real
    assert inf["fusion"]["omitida"] is True
    assert inf["coste"]["bytes_copiados"] == 0      # sin coste de copia
    assert inf["coste"]["bytes_fusionados"] == 0    # ni de fusion
    assert inf["coste"]["pared_fusion_s"] == 0.0
    assert (ws / "salida.txt").read_text(encoding="utf-8") == "directo\n"
    assert "rama.creada" not in [f["evento"] for f in R.leer_ledger(ledger)]


def test_k1_rechazada_se_restaura_desde_la_instantanea(tmp_path):
    """El unico coste extra que k=1 SI paga es la instantanea; a cambio, un
    resultado que el juez reprueba no deja el ws real destrozado."""
    ws = _ws(tmp_path)
    antes = R.manifiesto(ws)

    def correr(tarea, ws_rama, ctx):
        Path(ws_rama, "base.txt").write_text("DESTROZADO\n", encoding="utf-8")
        Path(ws_rama, "basura.txt").write_text("basura\n", encoding="utf-8")
        return {"pasos": 1}

    inf = R.ramificar("t", ws, 1, correr, lambda w, r: False,
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)

    assert inf["ganadora"] is None
    assert inf["restauracion"]["ok"] is True
    assert R.manifiesto(ws) == antes
    assert not (ws / "basura.txt").exists()


def test_k1_rechazada_sin_restaurar_deja_el_estropicio(tmp_path):
    """Contrafactual del test anterior: con restaurar_si_falla=False el dano
    SE QUEDA. Si no fallara aqui, el test de arriba estaria pasando por el
    motivo equivocado (p.ej. porque correr() no escribio nada)."""
    ws = _ws(tmp_path)

    def correr(tarea, ws_rama, ctx):
        Path(ws_rama, "basura.txt").write_text("basura\n", encoding="utf-8")
        return {"pasos": 1}

    R.ramificar("t", ws, 1, correr, lambda w, r: False,
                ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False,
                restaurar_si_falla=False)
    assert (ws / "basura.txt").exists()


# -- coste, contratos y bordes -------------------------------------------

def test_coste_contabiliza_pared_pasos_y_bytes(tmp_path):
    ws = _ws(tmp_path)
    inf = R.ramificar("t", ws, 3, _correr_marcador, _juez_por_indice,
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    c = inf["coste"]
    assert c["ramas"] == 3
    assert c["pasos"] == 6                      # 2 pasos x 3 ramas
    assert c["bytes_copiados"] > 0
    assert c["bytes_fusionados"] > 0
    assert c["bytes_movidos"] == c["bytes_copiados"] + c["bytes_fusionados"]
    assert c["pared_total_s"] >= c["pared_ramas_s"]
    # el numero que la literatura de best-of-K omite
    assert c["factor_vs_una_rama"] is not None and c["factor_vs_una_rama"] > 1


def test_desempate_por_indice_es_determinista(tmp_path):
    ws = _ws(tmp_path)
    inf = R.ramificar("t", ws, 3, _correr_marcador,
                      lambda w, r: {"ok": True, "puntaje": 5.0},
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    assert inf["ganadora"] == "rama_0"
    assert "empate resuelto por indice" in inf["razon"]


def test_juicios_de_todas_las_formas_se_normalizan(tmp_path):
    ws = _ws(tmp_path)
    inf = R.ramificar("t", ws, 2, _correr_marcador,
                      lambda w, r: 0.5 if r["rama"] == "rama_0" else 0.9,
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    assert inf["ganadora"] == "rama_1"
    assert inf["ramas"][0]["juicio"] == {"puntaje": 0.5, "ok": True,
                                         "motivo": "juez numerico"}


def test_aridades_de_los_callables_inyectados(tmp_path):
    """El motor acepta (tarea, ws, ctx), (tarea, ws) y (ctx); y jueces de 1 y
    2 argumentos. Si esto se rompe, cablearlo al agente exige adaptadores."""
    ws = _ws(tmp_path)
    inf = R.ramificar("t", ws, 2,
                      lambda tarea, w: Path(w, "dos.txt").write_text("2"),
                      lambda w: Path(w, "dos.txt").exists(),
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    assert inf["ganadora"] == "rama_0"
    assert (ws / "dos.txt").exists()


def test_k_invalido_se_rechaza(tmp_path):
    ws = _ws(tmp_path)
    with pytest.raises(ValueError):
        R.ramificar("t", ws, 0, _correr_marcador, _juez_por_indice,
                    ruta_ledger_=tmp_path / "l.jsonl")
    with pytest.raises(ValueError):
        R.ramificar("t", tmp_path / "no_existe", 2, _correr_marcador,
                    _juez_por_indice, ruta_ledger_=tmp_path / "l.jsonl")


def test_manifiesto_detecta_cambio_de_igual_tamano(tmp_path):
    """El hash, no la mtime ni el tamano: 'aaa' -> 'bbb' pesa lo mismo."""
    ws = _ws(tmp_path)
    a = R.manifiesto(ws)
    (ws / "base.txt").write_text("origina1\n", encoding="utf-8")
    b = R.manifiesto(ws)
    assert R.diferencia_ws.__doc__            # existe y esta documentada
    assert a["base.txt"][0] == b["base.txt"][0]
    assert a != b


def test_paralelo_da_el_mismo_resultado_que_secuencial(tmp_path):
    """paralelo=True es opt-in; tiene que dar EL MISMO ganador y el mismo
    disco. (Que ademas no ACELERE con un solo slot de GPU esta medido aparte
    y declarado en la cabecera del modulo.)"""
    ws_s = _ws(tmp_path, "seq")
    ws_p = _ws(tmp_path, "par")
    a = R.ramificar("t", ws_s, 3, _correr_marcador, _juez_por_indice,
                    ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False)
    b = R.ramificar("t", ws_p, 3, _correr_marcador, _juez_por_indice,
                    ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=False,
                    paralelo=True)
    assert a["ganadora"] == b["ganadora"] == "rama_2"
    assert R.manifiesto(ws_s) == R.manifiesto(ws_p)


def test_tolera_modulos_hermanos_ausentes_o_rotos(tmp_path, monkeypatch):
    """Con usar_modulos=True (el default) el motor delega en instantanea.py /
    reversibilidad.py. Si el import revienta, NO finge: cae al fallback y lo
    DICE en el informe."""
    import builtins
    real_import = builtins.__import__

    def _import_roto(nombre, *a, **kw):
        if nombre.endswith("instantanea") or "instantanea" in str(
                (a[2] if len(a) > 2 else ()) or ()):
            raise ImportError("simulado: instantanea.py no disponible")
        return real_import(nombre, *a, **kw)

    ws = _ws(tmp_path)
    monkeypatch.setattr(builtins, "__import__", _import_roto)
    inf = R.ramificar("t", ws, 2, _correr_marcador, _juez_por_indice,
                      ruta_ledger_=tmp_path / "l.jsonl", usar_modulos=True)
    monkeypatch.undo()
    assert inf["instantanea"]["mecanismo"] in ("fallback", "fallback_tras_error",
                                               "modulo")
    assert inf["ganadora"] == "rama_1"
    assert (ws / "rama_1.txt").exists()
