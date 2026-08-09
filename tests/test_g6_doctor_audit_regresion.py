# -*- coding: utf-8 -*-
"""Regresion de la revision adversarial 2026-08-01 (grupo G6: doctor + audit).

Los cuatro agujeros que cierra:

1. FALSO PASS del marcador de inferencia: `"OK" in texto.upper()` es un
   SUBSTRING, y el bigrama "ok" vive dentro de "tokens", "broken" y "look".
   Basura plausible en ingles aprobaba el chequeo que existia justamente para
   cazar basura.
2. La rama except de check_inference_speed era _warn (que devuelve True): una
   excepcion del orquestador dejaba el doctor en verde.
3. check_flota daba [OK] con 1/2 puertos vivos: con el VLM caido el arbitro
   visual no corre y nadie se entera.
4. CARRERA en la rotacion de las auditorias: el stat() y el replace() a .1
   pasaban FUERA del lock, asi que dos procesos cruzando el tope a la vez
   podian archivar el archivo FRESCO encima de la generacion recien guardada.
   Ademas leer_audit() devolvia ([], 0) tanto para "no hay nada" como para
   "no pude leer".
"""

import contextlib
import io
import json
import os
import sys
import types

import pytest

import cognia.doctor as D
from cognia import backend_activo as BA
from cognia.agent import sentinel as S


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ret = fn()
    return ret, buf.getvalue()


# ───────────────────────────── 1 y 2: el marcador de inferencia ──────────────

class _FakeResult:
    def __init__(self, text, mode="llama.cpp", toks=10):
        self.text = text
        self.mode = mode
        self.tokens_generated = toks


class _FakeOrch:
    resultado = _FakeResult("OK " * 10)
    excepcion = None

    def __init__(self, *a, **k):
        pass

    def _shards_available(self):
        return True

    def _try_load_llama(self):
        pass

    def infer(self, *a, **k):
        if type(self).excepcion is not None:
            raise type(self).excepcion
        return type(self).resultado


@pytest.fixture
def orch_falso(monkeypatch):
    mod = types.ModuleType("shattering.orchestrator")
    mod.ShatteringOrchestrator = _FakeOrch
    monkeypatch.setitem(sys.modules, "shattering.orchestrator", mod)
    monkeypatch.setattr(D, "_shard_dir", lambda: "hay_shards")
    monkeypatch.setattr(D, "_manifest_path", lambda: "manifest.json")
    _FakeOrch.excepcion = None
    _FakeOrch.resultado = _FakeResult("OK " * 10)
    yield _FakeOrch
    _FakeOrch.excepcion = None


class TestFalsoPassDelMarcador:

    @pytest.mark.parametrize("basura", [
        "tokens broken look",              # el caso exacto del reporte
        "I am looking at the tokens",
        "broken",
        "Okay, sure!",                     # 'Ok' pegado a otra palabra
    ])
    def test_basura_con_el_bigrama_ok_es_FALLO(self, orch_falso, basura):
        """Con `"OK" in texto.upper()` TODAS estas pasaban como [OK]."""
        orch_falso.resultado = _FakeResult(basura, "llama.cpp", 120)
        ret, out = _capture(D.check_inference_speed)
        assert ret is False, f"aprobo basura: {basura!r}"
        assert "[FAIL]" in out and "[OK]" not in out

    def test_un_solo_OK_suelto_no_alcanza(self, orch_falso):
        """Se piden diez; una sola aparicion es tan poco como para venir de
        cualquier prosa ('OK, here is the answer:')."""
        orch_falso.resultado = _FakeResult("OK, here is the answer:", "llama.cpp", 40)
        ret, out = _capture(D.check_inference_speed)
        assert ret is False and "[FAIL]" in out

    def test_respuesta_real_pasa(self, orch_falso):
        orch_falso.resultado = _FakeResult("OK OK OK OK OK OK OK OK OK OK",
                                           "llama.cpp", 20)
        ret, out = _capture(D.check_inference_speed)
        assert ret is True and "[OK]" in out

    def test_excepcion_del_orquestador_es_FAIL_no_WARN(self, orch_falso):
        """_warn devuelve True: el doctor terminaba 'Todo en orden' con la
        inferencia reventada."""
        orch_falso.excepcion = RuntimeError("llama_decode devolvio -1")
        ret, out = _capture(D.check_inference_speed)
        assert ret is False
        assert "[FAIL]" in out and "llama_decode" in out

    def test_falta_shattering_sigue_siendo_WARN(self, monkeypatch):
        """Dependencia opcional ausente != instalacion rota."""
        monkeypatch.setattr(D, "_shard_dir", lambda: "hay_shards")
        monkeypatch.setattr(D, "_manifest_path", lambda: "manifest.json")
        monkeypatch.setitem(sys.modules, "shattering.orchestrator", None)
        ret, out = _capture(D.check_inference_speed)
        assert ret is True and "[WARN]" in out


# ────────────────────────────────── 3: flota incompleta ─────────────────────
# WP6 2026-08-09: check_flota dejo el sondeo /health por /props (el health
# 200 no dice QUE modelo sirve el puerto: la averia del :8088). El contrato
# nuevo — apagada = FAIL con la orden exacta, :8081 caido = WARN — se cubre a
# fondo en tests/test_doctor_flota_props.py; aqui queda la version por props
# de los tres casos originales del G6.

def _props_puertos(tabla, monkeypatch):
    """tabla: {puerto: props_dict}; el resto de puertos no responde."""
    def _f(url, forzar=False):
        puerto = int(url.rsplit(":", 1)[1].split("/")[0])
        return tabla.get(puerto, {})
    monkeypatch.setattr(BA, "props", _f)


class TestFlotaIncompleta:

    def test_un_puerto_de_dos_es_WARN_y_dice_cual_falta(self, monkeypatch):
        _props_puertos({8080: {"modelo": "gpt-oss-20b-mxfp4.gguf",
                               "puerto": 8080}}, monkeypatch)
        ret, out = _capture(D.check_flota)
        assert ret is True
        assert "[WARN]" in out and "[OK]" not in out
        assert "8081" in out

    def test_los_dos_puertos_es_OK(self, monkeypatch):
        _props_puertos({8080: {"modelo": "gpt-oss-20b-mxfp4.gguf",
                               "puerto": 8080},
                        8081: {"modelo": "Qwen2.5-VL-3B.gguf",
                               "puerto": 8081}}, monkeypatch)
        ret, out = _capture(D.check_flota)
        assert ret is True and "[OK]" in out

    def test_ninguno_es_FAIL_apagada_con_la_orden(self, monkeypatch):
        # Antes era WARN (True) y el doctor terminaba "Todo en orden" con la
        # flota muerta; ahora FALLA y dice la orden exacta para arrancarla.
        _props_puertos({}, monkeypatch)
        ret, out = _capture(D.check_flota)
        assert ret is False
        assert "[FAIL]" in out and "apagada" in out
        assert "python -m cognia flota arrancar" in out


# ──────────────────────────── 4: rotacion dentro del lock ───────────────────

def _lock_tomado(path):
    """True si el lock de `path` esta tomado por alguien (probado con un
    handle NUEVO: en Windows y en POSIX un segundo descriptor del mismo
    proceso choca igual con el rango bloqueado)."""
    lock = path.with_name(path.name + ".lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    try:
        if BA.msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                BA.msvcrt.locking(fd, BA.msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            BA.msvcrt.locking(fd, BA.msvcrt.LK_UNLCK, 1)
            return False
        if BA.fcntl is not None:
            try:
                BA.fcntl.flock(fd, BA.fcntl.LOCK_EX | BA.fcntl.LOCK_NB)
            except OSError:
                return True
            BA.fcntl.flock(fd, BA.fcntl.LOCK_UN)
            return False
        pytest.skip("sin primitiva de lock en esta plataforma")
    finally:
        os.close(fd)


class TestRotacionDentroDelLock:
    """La carrera solo se cierra si el stat()+replace() corren con el lock
    tomado. En vez de una prueba de concurrencia flaky se afirma el
    INVARIANTE: cuando se ejecuta la rotacion, el lock ya esta tomado."""

    def test_backend_rota_con_el_lock_tomado(self, tmp_path, monkeypatch):
        ruta = tmp_path / "backend_audit.jsonl"
        monkeypatch.setattr(BA, "AUDIT", ruta)
        monkeypatch.setattr(BA, "_ROTAR_BYTES", 100)
        ruta.write_text("x" * 200 + "\n", encoding="utf-8")

        visto = {}
        original = BA._rotar_si_toca

        def espia(path, tope):
            visto["lock"] = _lock_tomado(path)
            return original(path, tope)

        monkeypatch.setattr(BA, "_rotar_si_toca", espia)
        BA._append({"via": "post_rotacion"})

        assert visto.get("lock") is True, "la rotacion corrio SIN el lock"
        gen1 = ruta.with_name(ruta.name + ".1")
        assert gen1.exists() and gen1.stat().st_size > 100
        filas, corruptas = BA.leer_audit()
        assert [f["via"] for f in filas] == ["post_rotacion"]

    def test_sentinel_rota_con_el_lock_tomado(self, tmp_path, monkeypatch):
        ruta = tmp_path / "sentinel_audit.jsonl"
        monkeypatch.setattr(S, "_AUDIT", ruta)
        monkeypatch.setattr(S, "_ROTAR_BYTES", 100)
        ruta.write_text("y" * 200 + "\n", encoding="utf-8")

        visto = {}
        original = BA._rotar_si_toca

        def espia(path, tope):
            visto["lock"] = _lock_tomado(path)
            return original(path, tope)

        monkeypatch.setattr(BA, "_rotar_si_toca", espia)
        S._audit("shell", "git status", "allow", "prefijo conocido")

        assert visto.get("lock") is True, "la rotacion corrio SIN el lock"
        gen1 = ruta.with_name(ruta.name + ".1")
        assert gen1.exists() and gen1.stat().st_size > 100
        lineas = ruta.read_text(encoding="utf-8").splitlines()
        assert len(lineas) == 1
        assert json.loads(lineas[0])["veredicto"] == "allow"

    def test_sentinel_usa_la_misma_implementacion(self):
        """La rotacion estaba duplicada en los dos modulos (y el bug tambien).
        Si alguien la vuelve a copiar, este test lo caza."""
        import inspect
        src = inspect.getsource(S._audit)
        assert "escribir_linea_jsonl" in src
        assert ".1" not in src and "st_size" not in src

    def test_el_lock_no_es_el_propio_jsonl(self, tmp_path, monkeypatch):
        """Bloquear el byte 0 del jsonl hacia FALLAR la lectura concurrente en
        Windows: por eso leer_audit veia ([], 0) 'vacio'. El mutex tiene que
        ser un archivo aparte."""
        ruta = tmp_path / "backend_audit.jsonl"
        monkeypatch.setattr(BA, "AUDIT", ruta)
        leido = {}

        original = BA._rotar_si_toca

        def espia(path, tope):
            # el lock esta tomado AHORA: leer el jsonl tiene que seguir siendo
            # posible (aunque este vacio en este instante)
            try:
                path.open("r", encoding="utf-8").close()
                leido["ok"] = True
            except OSError as e:
                leido["ok"] = False
                leido["err"] = str(e)
            return original(path, tope)

        monkeypatch.setattr(BA, "_rotar_si_toca", espia)
        ruta.write_text('{"via": "previa"}\n', encoding="utf-8")
        BA._append({"via": "nueva"})
        assert leido.get("ok") is True, leido.get("err")


class TestLeerAuditDistingueEstados:

    def test_sin_archivo_es_vacio_no_ilegible(self, tmp_path, monkeypatch):
        monkeypatch.setattr(BA, "AUDIT", tmp_path / "no_existe.jsonl")
        assert BA.leer_audit() == ([], 0)                 # compat
        assert BA.leer_audit(con_estado=True) == ([], 0, "vacio")

    def test_ilegible_no_se_confunde_con_vacio(self, tmp_path, monkeypatch, capsys):
        # un directorio no se puede leer como archivo: OSError, no FileNotFound
        monkeypatch.setattr(BA, "AUDIT", tmp_path)
        filas, corruptas, estado = BA.leer_audit(con_estado=True)
        assert (filas, corruptas) == ([], 0)
        assert estado == "ilegible"
        assert "NO SE PUDO LEER" in capsys.readouterr().err

    def test_con_datos_es_ok(self, tmp_path, monkeypatch):
        ruta = tmp_path / "backend_audit.jsonl"
        ruta.write_text('{"via": "a"}\nbasura\n', encoding="utf-8")
        monkeypatch.setattr(BA, "AUDIT", ruta)
        filas, corruptas, estado = BA.leer_audit(con_estado=True)
        assert [f["via"] for f in filas] == ["a"]
        assert corruptas == 1 and estado == "ok"
