# -*- coding: utf-8 -*-
"""
Tareas LARGAS: el techo real es la ventana, y el razonador no para (2026-08-30).

CAZADO USANDO EL PRODUCTO. El dueño pidió en el REPL "un Minecraft completo en
un solo HTML". Dos corridas, 48 minutos, 92.245 tokens, 8 vueltas, 7 refunds y
CERO ficheros escritos. El final del log:

    el turno se corto por max_tokens antes de emitir el tool call:
        repito el paso con max_tokens 16384 -> 32768
    el contenido no cabe en un solo tool call ni con max_tokens=32768:
        le pido al modelo que lo escriba por partes
    escribir_archivo: argumentos cortados a los 2142 chars
    HTTP 500 ... parse error at line 1, column 2144 ...
    ⚠ Turno terminado [bucle_nativo]: razon=error_backend detalle=desconocido

Tres causas encadenadas, las tres MEDIDAS contra el llama-server real
(Qwen3.8-27B-Ridge, n_ctx=65536) antes de tocar una línea:

1. EL TECHO ERA LA VENTANA, NO max_tokens. Con un prompt de 63.277 tokens y
   max_tokens=32768 llegaron 2258 tokens y total_tokens=65535 = n_ctx MENOS
   UNO. La rampa 8192→16384→32768 subía el número que no cortaba: cada vuelta
   regeneraba el mismo razonamiento y moría en la misma columna.

2. EL RAZONADOR NO TERMINA DE PENSAR. Misma petición con el contexto VACÍO
   (prompt de 369 tokens, o sea sin ninguna presión) y max_tokens=20000:
   52.535 chars de razonamiento y CERO tool calls. La misma con
   enable_thinking=false y max_tokens=4000: 0 chars de razonamiento y 10.160
   chars de tool call. Darle más tokens era darle más sitio para pensar.

3. LO YA GENERADO SE TIRABA. El modelo emitía ~2.100 chars de HTML válido y el
   bucle los descartaba para pedirle que empezara de nuevo — con el mismo
   presupuesto, o sea con el mismo final.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from cognia.agent import loop as L
from cognia.agent import presupuesto_salida as PS
from cognia.agent import rescate_parcial as RP


class _Resp:
    """Lo mínimo que el bucle mira de una respuesta."""

    def __init__(self, ok=True, error="", finish_reason="stop", tool_calls=None,
                 texto="", reasoning_content="", usage=None):
        self.ok = ok
        self.error = error
        self.finish_reason = finish_reason
        self.tool_calls = tool_calls or []
        self.texto = texto
        self.reasoning_content = reasoning_content
        self.usage = usage or {}


class _TC:
    """Un tool call con los argumentos cortados, como los marca chat_client."""

    def __init__(self, nombre, crudo, id="tc1"):
        self.nombre = nombre
        self.id = id
        self.argumentos_crudos = crudo
        self.argumentos = {}
        self.argumentos_rotos = True


SCHEMAS = [{"type": "function", "function": {"name": "escribir_archivo"}}]


@pytest.fixture(autouse=True)
def _sin_contaminar_el_contexto_vivo():
    """Estos tests corren `bucle_nativo` de verdad, y ese bucle ANOTA la
    ocupacion de la ventana en `harness.contexto_vivo`, que es estado de
    MODULO. Sin limpiarlo, la ocupacion falsa de aqui (n_ctx=65536 con un
    usage inventado) se filtraba a otros ficheros de la suite: el footer de
    `test_wp3_presentacion::test_show_footer_no_inventa_tokens` salia como
    "ctx ~100% libre" y ese test —que existe justo para que el footer NO
    invente tokens— se ponia rojo por culpa de estos.

    Se limpia ANTES y DESPUES: antes para no heredar lo de otro fichero,
    despues para no dejarlo puesto."""
    try:
        from cognia.harness import contexto_vivo as cv
    except ImportError:                       # sin el modulo no hay que limpiar
        yield
        return
    cv.reiniciar()
    yield
    cv.reiniciar()



# ── 1. La ventana es el techo ────────────────────────────────────────────────

class TestElTechoEsLaVentana:

    def test_clamp_recorta_al_hueco_REAL_medido(self):
        # El caso exacto que se midió contra el server.
        mt, motivo = PS.clamp(32768, 65536, 63277)
        assert mt == 65536 - 63277 - PS.RESERVA
        assert motivo, "el recorte tiene que ser visible, no silencioso"

    def test_sin_n_ctx_no_se_inventa_una_ventana(self):
        # CONTRAFACTUAL: un backend que no publica /props no puede hacer que
        # el bucle recorte por una ventana imaginaria.
        assert PS.clamp(32768, None, 1000) == (32768, "")
        assert PS.disponible(None, 1000) == 0

    def test_distingue_el_corte_de_VENTANA_del_de_max_tokens(self):
        # El usage REAL del corte por ventana (total_tokens = n_ctx - 1)...
        por_ventana = {"prompt_tokens": 63277, "completion_tokens": 2258,
                       "total_tokens": 65535}
        assert PS.es_corte_por_contexto(por_ventana, 65536)
        # ...y el REAL de un corte por max_tokens, con ventana de sobra.
        por_tope = {"prompt_tokens": 369, "completion_tokens": 2200,
                    "total_tokens": 2569}
        assert not PS.es_corte_por_contexto(por_tope, 65536)

    def test_un_usage_sin_prompt_tokens_no_afirma_nada(self):
        # El usage estimado por timings trae solo completion_tokens: decir
        # "es la ventana" sin saberlo dispararía compactaciones inútiles.
        assert not PS.es_corte_por_contexto({"completion_tokens": 2258}, 65536)

    def test_sin_sitio_para_trabajar_se_avisa(self):
        assert not PS.hay_sitio_para_trabajar(65536, 63277)
        assert PS.hay_sitio_para_trabajar(65536, 10000)
        # Sin n_ctx no se bloquea el turno por una ventana desconocida.
        assert PS.hay_sitio_para_trabajar(None, 10000)


# ── 2. Rescatar lo ya generado ───────────────────────────────────────────────

def _crudo_cortado(n_lineas=200, corte=2144):
    """El JSON que emite el server, cortado en la columna que mató la tarea."""
    html = ('<!DOCTYPE html>\n<html lang="es">\n<head>\n'
            '<meta charset="utf-8">\n<title>Mine</title>\n')
    html += "".join("<div class='b-%d'>celda</div>\n" % i
                    for i in range(n_lineas))
    entero = json.dumps({"path": "minecraft.html", "contenido": html},
                        ensure_ascii=False)
    return entero[:corte], html


class TestRescatarElParcial:

    def test_lo_rescatado_es_prefijo_EXACTO_del_fichero(self):
        crudo, html = _crudo_cortado()
        r = RP.partes(crudo)
        assert r and r["ruta"] == "minecraft.html"
        seguro, _ = RP.recortar_a_frontera(r["parcial"])
        # Lo que se escribe al disco tiene que ser el principio LITERAL de lo
        # que el modelo quería: si no, el fichero queda corrupto y el modelo
        # continúa desde un sitio que no existe.
        assert html.startswith(seguro)
        assert seguro.endswith("\n"), "no se deja media línea en el fichero"
        assert len(seguro) > 1500

    def test_no_rescata_lo_que_no_se_puede_rescatar(self):
        # CONTRAFACTUALES: en todos estos casos inventar sería peor que el
        # aviso de "por partes" de siempre.
        assert RP.partes('{"path": "minecr') is None          # corte en la ruta
        assert RP.partes('{"path": "a.html", "conte') is None  # corte en la clave
        assert RP.partes('{"contenido": "' + "x" * 400) is None  # sin ruta
        assert RP.partes('{"path":"a.txt","contenido":"hola') is None  # muy corto
        assert RP.partes("ruta | contenido") is None           # no es JSON
        assert RP.partes("") is None

    def test_un_corte_dentro_de_una_escapada_no_rompe_el_rescate(self):
        esc = json.dumps({"ruta": "a.txt",
                          "contenido": "linea\n" * 60 + 'dice "hola"'},
                         ensure_ascii=False)
        # Cortar 2 y 3 chars antes del final deja la cadena abierta con la
        # escapada a medias: tiene que rescatar igual, no devolver vacío.
        for k in (2, 3):
            r = RP.partes(esc[:len(esc) - k])
            assert r and len(r["parcial"]) > 300

    def test_el_ancla_dice_por_donde_seguir(self):
        crudo, _ = _crudo_cortado()
        seguro, _ = RP.recortar_a_frontera(RP.partes(crudo)["parcial"])
        assert RP.ancla(seguro, 50) == seguro[-50:]


# ── 3. El bucle, de punta a punta ────────────────────────────────────────────

class TestElBucleAnteUnaTareaLarga:

    def _correr(self, respuestas, perfil=None, run_tool=None, max_turns=4):
        vistos = []

        def _completar(mensajes, tools=None, **sampling):
            vistos.append({"max_tokens": sampling.get("max_tokens"),
                           "kwargs_plantilla": sampling.get("kwargs_plantilla"),
                           "mensajes": list(mensajes)})
            return respuestas[min(len(vistos) - 1, len(respuestas) - 1)]

        escrituras = []

        def _run(nombre, args, ctx):
            escrituras.append((nombre, args))
            return f"RESULTADO {nombre}: OK"

        res = L.bucle_nativo(
            task="un minecraft en un solo html", system="", completar=_completar,
            schemas=SCHEMAS, args_legacy=lambda n, a: "",
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda *a, **k: {"role": "tool", "content": "ok"},
            run_tool=run_tool or _run,
            ctx={}, perfil=(perfil or {"max_tokens": 1024}), history=[],
            trace=[], print_fn=lambda *a, **k: None, max_turns=max_turns)
        return res, vistos, escrituras

    def test_un_corte_por_VENTANA_no_sube_max_tokens(self):
        # ESTE es el fix. Antes: 1024 -> 2048 -> 4096, tres generaciones
        # tiradas. Ahora la ventana llena no dispara la rampa, porque subir el
        # tope no puede cambiar un corte que da n_ctx.
        cortada = _Resp(finish_reason="length", tool_calls=[],
                        usage={"prompt_tokens": 63277, "completion_tokens": 2258,
                               "total_tokens": 65535})
        buena = _Resp(finish_reason="stop", texto="listo")
        _, vistos, _ = self._correr(
            [cortada, buena], perfil={"max_tokens": 1024, "n_ctx": 65536})
        topes = [v["max_tokens"] for v in vistos]
        assert topes[1] <= topes[0], \
            f"la rampa subio el tope que no cortaba: {topes}"

    def test_un_corte_por_MAX_TOKENS_si_sube_el_tope(self):
        # CONTRAFACTUAL del anterior: con ventana de sobra la rampa histórica
        # sigue siendo lo correcto y no se toca.
        cortada = _Resp(finish_reason="length", tool_calls=[],
                        usage={"prompt_tokens": 369, "completion_tokens": 1024,
                               "total_tokens": 1393})
        buena = _Resp(finish_reason="stop", texto="listo")
        _, vistos, _ = self._correr(
            [cortada, buena], perfil={"max_tokens": 1024, "n_ctx": 65536})
        assert vistos[1]["max_tokens"] > vistos[0]["max_tokens"]

    def test_si_se_le_va_el_turno_pensando_se_apaga_el_pensamiento(self):
        # Lo medido: 52.535 chars de razonamiento y cero tool calls. La
        # respuesta correcta no es más presupuesto, es menos pensamiento.
        pensando = _Resp(finish_reason="length", tool_calls=[],
                         reasoning_content="pienso " * 5000,
                         usage={"prompt_tokens": 369, "completion_tokens": 20000,
                                "total_tokens": 20369})
        buena = _Resp(finish_reason="stop", texto="listo")
        _, vistos, _ = self._correr(
            [pensando, buena],
            perfil={"max_tokens": 1024, "n_ctx": 65536,
                    "kwargs_plantilla": {"enable_thinking": True}})
        assert vistos[0]["kwargs_plantilla"] == {"enable_thinking": True}
        assert vistos[1]["kwargs_plantilla"] == {"enable_thinking": False}, \
            "el reintento tiene que ir con el pensamiento apagado"

    def test_no_se_apaga_el_pensamiento_de_un_modelo_que_no_lo_lee(self):
        # CONTRAFACTUAL: mandar enable_thinking a una plantilla que lo ignora
        # sería fingir un control que no existe.
        pensando = _Resp(finish_reason="length", tool_calls=[],
                         reasoning_content="pienso " * 5000)
        buena = _Resp(finish_reason="stop", texto="listo")
        _, vistos, _ = self._correr([pensando, buena],
                                    perfil={"max_tokens": 1024, "n_ctx": 65536})
        assert not any(v["kwargs_plantilla"] for v in vistos)

    def test_el_parcial_de_un_tool_call_cortado_SE_ESCRIBE(self):
        # ESTE es el fix que convierte el fallo en progreso: antes se tiraban
        # los 2.100 chars y se le pedía al modelo empezar de nuevo.
        crudo, html = _crudo_cortado()
        con_corte = _Resp(finish_reason="tool_calls",
                          tool_calls=[_TC("escribir_archivo", crudo)])
        buena = _Resp(finish_reason="stop", texto="listo")
        res, _, escrituras = self._correr([con_corte, buena])
        assert escrituras, "no se escribio NADA del parcial rescatado"
        nombre, args = escrituras[0]
        assert nombre == "escribir_archivo"
        assert "minecraft.html" in args
        cuerpo = args.split("|", 1)[1].strip()
        assert html.startswith(cuerpo.split("\n")[0])

    def test_al_modelo_se_le_dice_DONDE_seguir_y_que_no_reescriba(self):
        crudo, _ = _crudo_cortado()
        con_corte = _Resp(finish_reason="tool_calls",
                          tool_calls=[_TC("escribir_archivo", crudo)])
        buena = _Resp(finish_reason="stop", texto="listo")
        hist = []

        def _completar(mensajes, tools=None, **sampling):
            hist.append(list(mensajes))
            return [con_corte, buena][min(len(hist) - 1, 1)]

        L.bucle_nativo(
            task="t", system="", completar=_completar, schemas=SCHEMAS,
            args_legacy=lambda n, a: "%s | %s" % (a.get("path"), a.get("contenido")),
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda tid, c: {"role": "tool", "content": c},
            run_tool=lambda n, a, c: f"RESULTADO {n}: OK",
            ctx={}, perfil={"max_tokens": 1024}, history=[], trace=[],
            print_fn=lambda *a, **k: None, max_turns=4)
        tools = [m["content"] for m in hist[-1] if m.get("role") == "tool"]
        assert any("PARCIAL" in t for t in tools)
        assert any("apendar_archivo" in t for t in tools)
        assert any("NO reescribas" in t for t in tools)

    def test_editar_archivo_cortado_NO_se_rescata(self):
        # CONTRAFACTUAL: media edición no es media escritura, es una edición
        # que no aplica. Escribirla corrompería el fichero.
        crudo = json.dumps({"path": "a.py", "contenido": "x" * 900},
                           ensure_ascii=False)[:600]
        con_corte = _Resp(finish_reason="tool_calls",
                          tool_calls=[_TC("editar_archivo", crudo)])
        buena = _Resp(finish_reason="stop", texto="listo")
        _, _, escrituras = self._correr([con_corte, buena])
        assert not escrituras

    def test_el_500_de_tool_call_no_cierra_con_el_backend_como_culpable(self):
        # Antes: razon=error_backend, "Agente (nativo): HTTP 500", CERO salida
        # final. Ahora cierra honesto y con lo que haya.
        rota = _Resp(ok=False, error=(
            'HTTP 500: {"error":{"code":500,"message":"Failed to parse tool '
            'call arguments as JSON: parse error at line 1, column 2144'))
        res, _, _ = self._correr([rota], perfil={"max_tokens": 1024,
                                                 "n_ctx": 65536})
        assert res["texto"], "una tarea larga no puede acabar SIN salida final"
        assert "no pudo hablar con el modelo" not in res["texto"], \
            "el backend no es el culpable de un tool call cortado"


class TestElRescateNoDestruye:
    """El arreglo no puede convertirse en el fallo que este repo ya sufrio:
    una escritura 'de recuperacion' que se come un fichero entero."""

    def test_no_machaca_un_fichero_que_ya_tiene_MAS_contenido(self, tmp_path,
                                                              monkeypatch):
        import os
        from cognia.agents.workers import dev_tools
        monkeypatch.setattr(dev_tools, "_root_actual", lambda: str(tmp_path))
        completo = tmp_path / "minecraft.html"
        completo.write_text("X" * 50000, encoding="utf-8")

        crudo, _ = _crudo_cortado()
        escrituras = []
        res = L._rescatar_escritura(
            _TC("escribir_archivo", crudo), crudo, {},
            lambda n, a, c: escrituras.append((n, a)) or "RESULTADO ok",
            lambda *a, **k: None)
        assert not escrituras, "sobrescribio un fichero mas grande"
        assert res and "ERROR" in res and "apendar_archivo" in res
        assert completo.read_text(encoding="utf-8") == "X" * 50000

    def test_si_no_existe_si_rescata(self, tmp_path, monkeypatch):
        from cognia.agents.workers import dev_tools
        monkeypatch.setattr(dev_tools, "_root_actual", lambda: str(tmp_path))
        crudo, _ = _crudo_cortado()
        escrituras = []
        res = L._rescatar_escritura(
            _TC("escribir_archivo", crudo), crudo, {},
            lambda n, a, c: (escrituras.append((n, a)), "RESULTADO ok")[1],
            lambda *a, **k: None)
        assert escrituras, "no rescato nada habiendo sitio"
        assert "PARCIAL" in res
