# -*- coding: utf-8 -*-
"""
tests/test_motor_workflows_techos.py — los cuatro agujeros que impedian crecer
==============================================================================
Cada bloque falla sin su fix y pasa con el. Sin red y sin GPU: `completar_fn`
inyectado como stub (la verificacion contra :8080 va aparte, en el informe).

1. EL TRUNCADO NO SE TIRA. `finish_reason=length` cobraba los tokens y borraba
   el texto. Medido antes del fix contra :8080: pedir "los numeros del 1 al
   400" con max_tokens=1024 devolvia {"_error": ...} SIN `_crudo`, con 1.076
   tokens cobrados y 23,7 s de pared en la basura.
2. LAS CONSTANTES SE ABREN. MAX_PASOS / MAX_TOKENS_PASO / presupuesto eran
   constantes de modulo: 6 x 2048 = 12.288 tokens de salida por corrida y no
   habia forma de moverlo sin editar el fichero.
3. EL CLAMP SILENCIOSO. Pedir max_tokens=64 y llamar con 1024 sin decirlo
   convierte en mentira cualquier tabla que anote "pedi 64".
4. LA TOOL DEVUELVE RUTA. El texto entero entraba al historial y
   `loop.py:_recortar_mensajes` lo dejaba en 200 chars al pasar el 80% del
   n_ctx: un documento largo se perdia ENTERO y sin copia.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field

import pytest

from cognia.ux import events as ux
from cognia.agent.workflows import agente, corrida
from cognia.harness import offloading as off
from cognia.harness import tools_harness as TH
from cognia.harness import workflows_adapter as WA


@dataclass
class _Resp:
    texto: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 10,
                                                 "completion_tokens": 5})
    error: str = ""


class _Stub:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, mensajes, **kw):
        self.llamadas.append({"mensajes": mensajes, "kw": kw})
        if not self.respuestas:
            raise AssertionError("stub sin respuestas: llamada de mas")
        return self.respuestas.pop(0)


@pytest.fixture
def dir_wf(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_WORKFLOWS_DIR", str(tmp_path))
    return tmp_path


def _corrida(nombre="techos", **kw):
    return corrida(nombre, print_fn=lambda *a, **k: None, **kw)


# ── 1. el truncado conserva lo pagado ────────────────────────────────────────

PARCIAL = ",".join(str(n) for n in range(1, 284))       # lo que da 1024 tokens


def test_truncado_devuelve_el_parcial_en_crudo(dir_wf):
    c = _corrida()
    stub = _Stub([_Resp(texto=PARCIAL, finish_reason="length",
                        usage={"prompt_tokens": 52, "completion_tokens": 1024})])
    r = agente(c, "los numeros del 1 al 400", max_tokens=1024, completar_fn=stub)
    c.cerrar()
    assert "_error" in r and "truncada" in r["_error"]
    assert r.get("_crudo") == PARCIAL, (
        "el texto ya estaba pagado (1024 completion_tokens) y se tiro")
    assert c.presupuesto.gastado() == 1076       # se cobro igual, con o sin fix


def test_el_truncado_no_se_sirve_como_resultado_en_un_resume(dir_wf):
    # El parcial es para el CALLER de este turno, NO para la cache: servirlo en
    # un resume seria devolver una respuesta incompleta como si estuviese bien.
    c1 = _corrida()
    agente(c1, "p", max_tokens=1024,
           completar_fn=_Stub([_Resp(texto=PARCIAL, finish_reason="length")]))
    c1.cerrar()
    c2 = _corrida(resume_de=c1.run_id)
    stub = _Stub([_Resp(texto="entero")])
    r = agente(c2, "p", max_tokens=1024, completar_fn=stub)
    c2.cerrar()
    assert r == "entero" and len(stub.llamadas) == 1, (
        "un truncado no puede volver de la cache: hay que re-pedirlo")


def test_el_adaptador_muestra_el_parcial_en_el_consolidado():
    salida = WA._consolidar(
        ["contar hasta 400"],
        [{"_error": "salida truncada (finish_reason=length): ...",
          "_crudo": PARCIAL}])
    assert "ERROR" in salida, "sigue siendo un fallo"
    assert "1,2,3" in salida and "283" in salida, (
        "el parcial pagado tiene que llegar al modelo, no solo el ERROR")


def test_un_error_sin_parcial_no_inventa_bloque():
    salida = WA._consolidar(["x"], [{"_error": "backend caido"}])
    assert "YA GENERADO" not in salida


# ── 2. los topes se abren por entorno, con defectos intactos ─────────────────

def test_los_defectos_no_cambian(monkeypatch):
    for v in (WA._ENV_PASOS, WA._ENV_TOKENS_PASO, WA._ENV_PRESUPUESTO):
        monkeypatch.delenv(v, raising=False)
    assert WA.max_pasos() == WA.MAX_PASOS == 6
    assert WA.max_tokens_paso() == WA.MAX_TOKENS_PASO == 2048
    assert WA.presupuesto_defecto() == WA.PRESUPUESTO_DEFECTO == 60_000


def test_el_entorno_sube_los_tres(monkeypatch):
    monkeypatch.setenv(WA._ENV_PASOS, "12")
    monkeypatch.setenv(WA._ENV_TOKENS_PASO, "8192")
    monkeypatch.setenv(WA._ENV_PRESUPUESTO, "250000")
    assert (WA.max_pasos(), WA.max_tokens_paso(),
            WA.presupuesto_defecto()) == (12, 8192, 250_000)


def test_el_tope_duro_acota_y_avisa(monkeypatch):
    monkeypatch.setenv(WA._ENV_PASOS, "9999")
    with pytest.warns(RuntimeWarning, match="tope"):
        assert WA.max_pasos() == WA.TOPE_PASOS


@pytest.mark.parametrize("valor", ["abc", "0", "-3", ""])
def test_un_env_invalido_cae_al_defecto(monkeypatch, valor):
    # Basura -> el defecto, y con warning cuando hay algo que avisar (la
    # cadena vacia es "no hay override", no un dedazo: esa no avisa).
    monkeypatch.setenv(WA._ENV_PASOS, valor)
    with warnings.catch_warnings(record=True) as vistos:
        warnings.simplefilter("always")
        assert WA.max_pasos() == WA.MAX_PASOS
    assert bool(vistos) == bool(valor.strip()), (
        f"{valor!r}: el aviso tiene que salir si y solo si el env dice algo")


def test_ejecutar_usa_el_tope_de_pasos_del_entorno(monkeypatch, dir_wf):
    # 8 subtareas: con el defecto se cortan a 6; con el override llegan las 8.
    llamadas = []

    def _agente_falso(c, prompt, **kw):
        llamadas.append(kw.get("max_tokens"))
        return "ok"

    import cognia.agent.workflows as WF
    monkeypatch.setattr(WF, "agente", _agente_falso)
    pasos = "; ".join(f"tarea {i}" for i in range(1, 9))

    monkeypatch.delenv(WA._ENV_PASOS, raising=False)
    assert WA.ejecutar(pasos, modo="secuencial")["pasos"] == 6

    llamadas.clear()
    monkeypatch.setenv(WA._ENV_PASOS, "8")
    monkeypatch.setenv(WA._ENV_TOKENS_PASO, "4096")
    res = WA.ejecutar(pasos, modo="secuencial")
    assert res["pasos"] == 8
    assert llamadas == [4096] * 8, "el override de tokens/paso no llego a agente()"


def test_el_presupuesto_explicito_del_caller_gana_al_entorno(monkeypatch, dir_wf):
    monkeypatch.setenv(WA._ENV_PRESUPUESTO, "999")
    vistos = {}

    import cognia.agent.workflows as WF
    real = WF.corrida

    def _espia(nombre, presupuesto_tokens=None, **kw):
        vistos["p"] = presupuesto_tokens
        return real(nombre, presupuesto_tokens=presupuesto_tokens, **kw)

    monkeypatch.setattr(WF, "corrida", _espia)
    monkeypatch.setattr(WF, "agente", lambda c, p, **kw: "ok")
    WA.ejecutar("uno", modo="secuencial", presupuesto=1234)
    assert vistos["p"] == 1234
    WA.ejecutar("uno", modo="secuencial")
    assert vistos["p"] == 999, "sin presupuesto explicito manda el entorno"


# ── 3. el clamp se ve ────────────────────────────────────────────────────────

def _avisos_de(fn):
    """Los Aviso emitidos al bus durante fn(). Devuelve (resultado, textos)."""
    capturados = []
    ux.suscribir(capturados.append)
    try:
        out = fn()
    finally:
        ux.desuscribir(capturados.append)
    return out, [e.texto for e in capturados if isinstance(e, ux.Aviso)]


def _lineas_journal(c, tipo):
    """Las lineas de `tipo` del journal. Se lee del fichero y no de un mock:
    la constancia solo cuenta si llego a disco."""
    out = []
    for ln in open(c.dir / "journal.jsonl", encoding="utf-8"):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("tipo") == tipo:
            out.append(d)
    return out


def test_el_clamp_avisa_una_vez_y_se_anota_siempre(dir_wf):
    from cognia.agent.model_profiles import MIN_TOKENS_RAZONADOR
    c = _corrida()

    def _correr():
        for _ in range(3):
            agente(c, "hola", max_tokens=64,
                   completar_fn=_Stub([_Resp(texto="x")]))

    _, avisos = _avisos_de(_correr)
    c.cerrar()
    clamps = [a for a in avisos if "se subio a" in a]
    assert len(clamps) == 1, (
        f"un aviso por corrida y valor pedido, no {len(clamps)}")
    assert "64" in clamps[0] and str(MIN_TOKENS_RAZONADOR) in clamps[0]
    assert len(_lineas_journal(c, "clamp_max_tokens")) == 3, (
        "el journal es contabilidad: lleva la linea de LOS TRES agentes")


def test_sin_clamp_no_hay_aviso(dir_wf):
    c = _corrida()
    _, avisos = _avisos_de(
        lambda: agente(c, "hola", max_tokens=4096,
                       completar_fn=_Stub([_Resp(texto="x")])))
    c.cerrar()
    assert not [a for a in avisos if "se subio a" in a]
    assert _lineas_journal(c, "clamp_max_tokens") == []


# ── 4. la tool devuelve ruta + resumen + como consultarlo ────────────────────

@pytest.fixture
def offload_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "off"))
    off._SESION = None
    yield tmp_path
    off._SESION = None


def _envelope(texto):
    return {"ok": True, "texto": texto, "run_id": "20260817-000000-t",
            "pasos": 3, "tokens": 100, "cancelados": 0, "critica": None,
            "error": ""}


def test_el_camino_corto_llega_ENTERO_y_sin_cabeceras_nuevas(monkeypatch,
                                                             offload_tmp):
    corto = "--- paso 1: uno\nSi.\n\n--- paso 2: dos\nNo.\n(2 pasos completados)"
    monkeypatch.setattr(TH._WF, "ejecutar", lambda *a, **k: _envelope(corto))
    salida = TH._workflow("uno; dos", {})
    assert salida == (
        "RESULTADO workflow (3 pasos, 100 tokens, corrida 20260817-000000-t):\n"
        + corto), "un workflow de tres frases no puede cambiar ni un byte"
    assert not list((offload_tmp / "off").rglob("*.txt")), (
        "el camino corto no toca disco")


def test_el_documento_largo_vuelve_como_ruta_resumen_y_receta(monkeypatch,
                                                              offload_tmp):
    largo = "\n".join(f"linea {i} del informe con texto de relleno" * 3
                      for i in range(1, 601))
    assert len(largo.encode()) > TH.UMBRAL_TEXTO_WORKFLOW
    monkeypatch.setattr(TH._WF, "ejecutar", lambda *a, **k: _envelope(largo))
    salida = TH._workflow("redacta el informe", {})

    assert len(salida.encode()) < len(largo.encode()) / 5, (
        "el resumen tiene que ser MUCHO mas chico que el documento")
    # 1) la ruta, y el fichero con el documento COMPLETO detras
    marca = "EL TEXTO COMPLETO ESTA EN DISCO"
    assert marca in salida
    ruta = salida.split(marca)[1].splitlines()[1].strip()
    assert open(ruta, encoding="utf-8").read() == largo, (
        "lo guardado tiene que ser el documento entero, no el resumen")
    # 2) el resumen, con principio y final de verdad
    assert "linea 1 del informe" in salida and "linea 600 del informe" in salida
    # 3) las dos formas de consultarlo, y la orden de NO repetirlo
    assert "leer_archivo" in salida and "recuperar res:" in salida
    assert "NO vuelvas a lanzar el workflow" in salida


def test_si_el_disco_falla_vuelve_el_texto_ENTERO(monkeypatch, offload_tmp):
    # Esta es la UNICA copia del trabajo: degradar a un resumen sin fichero
    # seria perder tokens ya pagados. Peor para la ventana, pero no se pierde.
    largo = "x" * (TH.UMBRAL_TEXTO_WORKFLOW + 500)
    monkeypatch.setattr(TH._WF, "ejecutar", lambda *a, **k: _envelope(largo))
    monkeypatch.setattr(off, "guardar",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disco")))
    salida = TH._workflow("uno", {})
    assert largo in salida


def test_el_umbral_se_puede_mover_por_entorno(monkeypatch):
    monkeypatch.setenv(TH._ENV_UMBRAL_WORKFLOW, "150")
    assert TH._umbral_texto_workflow() == 150
    monkeypatch.setenv(TH._ENV_UMBRAL_WORKFLOW, "basura")
    assert TH._umbral_texto_workflow() == TH.UMBRAL_TEXTO_WORKFLOW
    monkeypatch.setenv(TH._ENV_UMBRAL_WORKFLOW, "0")
    assert TH._umbral_texto_workflow() == TH.UMBRAL_TEXTO_WORKFLOW


def test_ruta_de_resuelve_y_rechaza_lo_que_no_es_handle(offload_tmp):
    h = off.guardar("contenido\n", tool="workflow", args="x")
    ruta = off.ruta_de(h)
    assert ruta and open(ruta, encoding="utf-8").read() == "contenido\n"
    for basura in ("", None, "res:../../etc/passwd", "../../x", "res:zzz"):
        assert off.ruta_de(basura) == ""
