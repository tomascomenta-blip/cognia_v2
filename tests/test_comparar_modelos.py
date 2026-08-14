# -*- coding: utf-8 -*-
"""Regresion de scripts/comparar_modelos.py (2026-08-13).

Solo funciones PURAS: nada aqui para, arranca ni consulta ningun llama-server
(la suite corre en maquinas sin GPU y no puede tocar el :8080 del dueno). Lo que
se fija aqui es exactamente lo que rompe un barrido sin que se note:

  - el clon del comando cambia SOLO --model/--ctx-size (si tocara los threads o
    el flash-attn, la tabla compararia configuraciones y no modelos)
  - el ctx NO es fijo: 200192 es de Qwythos, y un denso de 14B con esa ventana
    no arranca
  - un draft de otra familia no viaja al candidato
  - el veredicto ordena por BANCO antes que por tok/s
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
for _p in (str(_RAIZ), str(_RAIZ / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import comparar_modelos as cm     # noqa: E402

# Linea REAL leida del proceso vivo el 2026-08-13 (pid 2784).
LINEA_REAL = (
    r"C:\Users\usuario\.cognia\llama\llama-server.exe --model "
    r"C:\Users\usuario\.cognia\models\Huihui-Qwythos-9B-Claude-Mythos-5-1M-"
    r"abliterated-Q4_K.gguf --host 127.0.0.1 --port 8080 --ctx-size 200192 "
    r"--parallel 1 --n-gpu-layers 99 --threads 12 --threads-batch 12 "
    r"--cache-reuse 256 --cache-ram 1024 --prio 2 --flash-attn on "
    r"--log-disable --spec-type ngram-mod")


def test_argv_de_linea_parsea_la_linea_real():
    argv = cm.argv_de_linea(LINEA_REAL)
    assert argv[0].endswith("llama-server.exe")
    assert argv[argv.index("--ctx-size") + 1] == "200192"
    assert argv[argv.index("--parallel") + 1] == "1"


def test_clon_cambia_solo_modelo_y_ctx():
    argv = cm.argv_de_linea(LINEA_REAL)
    cand = cm.argv_candidato(argv, Path("no-usado.exe"), Path("X.gguf"),
                             8080, 16384, False)
    assert cand[cand.index("--model") + 1] == "X.gguf"
    assert cand[cand.index("--ctx-size") + 1] == "16384"
    # todo lo demas, intacto: mismos flags y mismo largo
    assert len(cand) == len(argv)
    for flag in ("--threads", "--threads-batch", "--cache-reuse", "--cache-ram",
                 "--prio", "--flash-attn", "--log-disable", "--spec-type",
                 "--parallel", "--n-gpu-layers", "--host"):
        assert flag in cand
    assert "--jinja" not in cand          # el server del dueno no lo lleva
    assert "--jinja" in cm.argv_candidato(argv, Path("x.exe"), Path("X.gguf"),
                                          8080, 16384, True)


def test_clon_saca_el_draft_de_otra_familia():
    argv = ["l.exe", "--model=viejo.gguf", "-c", "8192",
            "--spec-draft-model", "d.gguf", "--spec-type", "draft-simple",
            "--port", "8080"]
    cand = cm.argv_candidato(argv, Path("x.exe"), Path("Y.gguf"), 8080, 4096,
                             False)
    assert "--spec-draft-model" not in cand and "d.gguf" not in cand
    assert "--spec-type" not in cand      # sin draft model no tiene sentido
    assert "--model=Y.gguf" in cand       # forma --flag=valor soportada
    assert cand[cand.index("-c") + 1] == "4096"


def test_ctx_no_es_fijo():
    assert cm.ctx_de_modelo("Huihui-Qwythos-9B.gguf", 16384, {})[0] == 200192
    assert cm.ctx_de_modelo("OpenReasoning-Nemotron-14B.Q4_K_M.gguf",
                            16384, {})[0] < 200192
    assert cm.ctx_de_modelo("modelo-nunca-visto.gguf", 16384, {})[0] == 16384
    assert cm.ctx_de_modelo("Huihui-Qwythos-9B.gguf", 16384,
                            {"qwythos": 4096})[0] == 4096


def test_puntaje_del_banco():
    assert cm._puntaje("E2E CAMINO FELIZ: 4/5 OK en 1.4 min") == "4/5"
    assert cm._puntaje("sin numeros") == ""


def test_veredicto_pone_el_banco_por_encima_de_los_tok_s():
    filas = [
        {"modelo": "rapido_malo", "arranco": True, "tok_s": 99.0,
         "banco": {"ok": False, "puntaje": "1/5"}},
        {"modelo": "lento_ok", "arranco": True, "tok_s": 10.0,
         "banco": {"ok": True, "puntaje": "5/5"}},
        {"modelo": "muerto", "arranco": False, "tok_s": None, "banco": {}},
    ]
    assert [f["modelo"] for f in cm.ordenar_veredicto(filas)] == [
        "lento_ok", "rapido_malo", "muerto"]


def test_restaurar_sin_original_no_hace_nada():
    assert cm.restaurar({}, 1, Path("."))["estado"] == "nada que restaurar"


# --------------------------------------------------------------------------
# Regresiones de la revision adversarial (2026-08-13). Cada una fija un camino
# por el que el dueno se quedaba sin cerebro o la tabla mentia.
# --------------------------------------------------------------------------

def _original_falso(tmp_path):
    return {"pid": 1, "linea": "x.exe --model m.gguf", "argv": ["x.exe"],
            "puerto": 65099, "modelo_ruta": "m.gguf",
            "log_dir": str(tmp_path)}


def _reset_restauracion():
    cm._RESTAURADO = False
    cm._INTENTOS_RESTAURACION = 0


def test_un_fallo_de_restauracion_deja_el_cinturon_armado(tmp_path,
                                                          monkeypatch):
    """El bug: _RESTAURADO se ponia en True AL ENTRAR, asi que si el relanzado
    fallaba, el atexit ya no reintentaba. Un fallo tiene que dejar la puerta
    abierta al segundo intento."""
    _reset_restauracion()
    monkeypatch.setattr(cm, "estado_puerto", lambda p: "ausente")
    monkeypatch.setattr(cm, "pid_del_llama", lambda p: 0)
    monkeypatch.setattr(cm, "lanzar", lambda *a, **k: (_ for _ in ()).throw(
        OSError("el exe no existe")))
    r = cm.restaurar(_original_falso(tmp_path), 1, tmp_path)
    assert r["estado"] == "fallo"
    assert cm._RESTAURADO is False          # <-- el cinturon sigue armado
    assert cm._INTENTOS_RESTAURACION == 1
    _reset_restauracion()


def test_la_restauracion_no_reintenta_para_siempre(tmp_path, monkeypatch):
    _reset_restauracion()
    monkeypatch.setattr(cm, "estado_puerto", lambda p: "ausente")
    monkeypatch.setattr(cm, "pid_del_llama", lambda p: 0)
    monkeypatch.setattr(cm, "lanzar", lambda *a, **k: (_ for _ in ()).throw(
        OSError("nope")))
    orig = _original_falso(tmp_path)
    assert cm.restaurar(orig, 1, tmp_path)["estado"] == "fallo"
    assert cm.restaurar(orig, 1, tmp_path)["estado"] == "fallo"
    tercero = cm.restaurar(orig, 1, tmp_path)
    assert "agotados" in tercero["motivo"]   # no mata y relanza en bucle
    _reset_restauracion()


def test_las_senales_se_ignoran_durante_la_restauracion(tmp_path, monkeypatch):
    """Un SEGUNDO Ctrl-C mientras carga el modelo no puede abortar esto."""
    import signal as _sig
    _reset_restauracion()
    visto = {}

    def _espia(original, espera, log_dir):
        visto["sigint"] = _sig.getsignal(_sig.SIGINT)
        return {"estado": "restaurado"}

    previo = _sig.getsignal(_sig.SIGINT)
    monkeypatch.setattr(cm, "_restaurar_una_vez", _espia)
    cm.restaurar(_original_falso(tmp_path), 1, tmp_path)
    assert visto["sigint"] is _sig.SIG_IGN            # ignorado mientras dura
    assert _sig.getsignal(_sig.SIGINT) is previo      # y devuelto al salir
    _reset_restauracion()


def test_un_banco_que_devuelve_False_o_1_NO_es_OK():
    """El bug que hacia mentir la tabla: `r in (0, True, None)` da True para
    False (False == 0) y para 1 (1 == True), o sea que un banco fallado se
    anotaba como aprobado."""
    assert cm._ok_de_resultado(False) is False
    assert cm._ok_de_resultado(1) is False        # convencion de exit code
    assert cm._ok_de_resultado(0) is True
    assert cm._ok_de_resultado(True) is True
    assert cm._ok_de_resultado(None) is True      # corrio y no se quejo
    assert cm._ok_de_resultado({"ok": False}) is False
    assert cm._ok_de_resultado({"ok": True}) is True


def test_un_banco_importado_que_hace_sys_exit_no_tumba_el_barrido(monkeypatch):
    """e2e_happy_path.main() TERMINA en sys.exit: SystemExit es BaseException y
    se escapaba del except Exception, matando el barrido en el primer modelo."""
    import types
    mod = types.ModuleType("banco_falso_sysexit")
    mod.main = lambda: (_ for _ in ()).throw(SystemExit(1))
    sys.modules["banco_falso_sysexit"] = mod
    try:
        r = cm.correr_banco("py:banco_falso_sysexit:main", 65099, 5, "python")
    finally:
        sys.modules.pop("banco_falso_sysexit", None)
    assert r["ok"] is False and r["codigo"] == 1     # y devolvio, no exploto

    mod2 = types.ModuleType("banco_falso_ok")
    mod2.main = lambda: (_ for _ in ()).throw(SystemExit(0))
    sys.modules["banco_falso_ok"] = mod2
    try:
        assert cm.correr_banco("py:banco_falso_ok:main", 65099, 5,
                               "python")["ok"] is True
    finally:
        sys.modules.pop("banco_falso_ok", None)


def test_la_linea_de_comando_conserva_los_espacios_dobles():
    """Una ruta con dos espacios seguidos tiene que sobrevivir al parseo: si se
    colapsa, la restauracion relanza un --model que no existe."""
    linea = r'C:\l\llama-server.exe --model "C:\Mis  Modelos\a b.gguf" -c 8192'
    argv = cm.argv_de_linea(linea)
    assert r"C:\Mis  Modelos\a b.gguf" in argv     # dos espacios, sin comillas
    cand = cm.argv_candidato(argv, Path("x.exe"), Path(r"C:\otro dir\y.gguf"),
                             8080, 4096, False)
    assert cand[cand.index("--model") + 1] == r"C:\otro dir\y.gguf"


def test_la_restauracion_NO_mata_un_server_que_no_lanzo(tmp_path, monkeypatch):
    """Incidente real del 2026-08-13: un arnes de pruebas importo el modulo,
    dejo _ORIGINAL con puerto 8080 y el atexit MATO el llama-server de verdad
    del dueno para relanzar una linea de mentira. La restauracion solo puede
    parar PIDs que lanzo ella misma."""
    _reset_restauracion()
    matados = []
    monkeypatch.setattr(cm, "estado_puerto", lambda p: "ausente")
    monkeypatch.setattr(cm, "pid_del_llama", lambda p: 2784)      # el del dueno
    monkeypatch.setattr(cm, "parar_pid",
                        lambda pid, puerto, espera: matados.append(pid) or True)
    monkeypatch.setattr(cm, "lanzar", lambda *a, **k: pytest.fail(
        "no deberia haber llegado a relanzar nada"))
    monkeypatch.setattr(cm, "_LANZADOS", set())                   # no es nuestro
    r = cm.restaurar(_original_falso(tmp_path), 1, tmp_path)
    assert matados == []                     # <-- no lo toco
    assert r["estado"] == "fallo" and "ajeno" in r["motivo"]
    _reset_restauracion()


def test_la_restauracion_SI_para_al_candidato_que_lanzo(tmp_path, monkeypatch):
    _reset_restauracion()
    matados = []
    monkeypatch.setattr(cm, "estado_puerto", lambda p: "ausente")
    monkeypatch.setattr(cm, "pid_del_llama", lambda p: 4242)
    monkeypatch.setattr(cm, "parar_pid",
                        lambda pid, puerto, espera: matados.append(pid) or True)
    monkeypatch.setattr(cm, "lanzar", lambda *a, **k: (_ for _ in ()).throw(
        OSError("hasta aca llego el test")))
    monkeypatch.setattr(cm, "_LANZADOS", {4242})                  # ese si
    cm.restaurar(_original_falso(tmp_path), 1, tmp_path)
    assert matados == [4242]
    _reset_restauracion()


def test_vram_de_multiparte_suma_los_trozos(tmp_path):
    for n in (1, 2):
        (tmp_path / f"m[x]-0000{n}-of-00002.gguf").write_bytes(b"0" * 1000)
    gb = cm.vram_estimada_gb(tmp_path / "m[x]-00001-of-00002.gguf", 0)
    assert gb == 2000 / 1e9        # los DOS trozos, con '[' en el nombre
    # y un fichero que no existe no revienta el plan
    assert cm.vram_estimada_gb(tmp_path / "no-existe.gguf", 0) == 0.0
