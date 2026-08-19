# -*- coding: utf-8 -*-
"""
DSH · el tool call que se corta a mitad (2026-08-18).

CAZADO USANDO EL PRODUCTO, no leyendo código: se le pidió al CLI una tarea
normal — "hazme una landing page bonita para una cafetería, en un solo html" —
y a los 100 segundos el workspace estaba VACÍO. En el log:

    HTTP 500: Failed to parse tool call arguments as JSON
    ... column 860: invalid string: missing closing quote;
    last read: '"<!DOCTYPE html>\\n<html lang=\\"es\\">\\n<head>\\n  <meta charset

El modelo emitió `escribir_archivo` con el HTML dentro y el presupuesto del
turno se acabó a mitad de la cadena JSON. Según dónde caiga el corte hay dos
caras del MISMO fallo, y las dos acababan igual de mal:

  1. El server no puede parsear y devuelve HTTP 500  → resp.ok = False.
  2. El corte cae fuera de la cadena → turno limpio, finish_reason='length' y
     CERO tool_calls. Esta es la peor: se parece a "el modelo decidió no usar
     herramientas", así que el bucle culpaba al MODELO de un problema de
     PRESUPUESTO.

Ninguna se reintentaba. Reproducido a mano contra el server real: con
max_tokens=700 y una landing page pedida por tool call →
`finish_reason: length, tool_calls: 0, tokens generados: 700`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.agent import loop as L


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


SCHEMAS = [{"type": "function", "function": {"name": "escribir_archivo"}}]


class TestDetectarElCorte:

    def test_el_500_del_server_es_un_corte(self):
        # El mensaje REAL que devolvió llama-server en la corrida que lo cazó.
        resp = _Resp(ok=False, error=(
            'HTTP 500 de http://127.0.0.1:8080: {"error":{"code":500,"message":'
            '"Failed to parse tool call arguments as JSON: '
            '[json.exception.parse_error.101] parse error at line 1, column 860'))
        assert L._corte_en_tool_call(resp, SCHEMAS)

    def test_length_sin_tool_calls_es_un_corte(self):
        # La cara silenciosa: parece "no quiso usar herramientas".
        resp = _Resp(finish_reason="length", tool_calls=[])
        assert L._corte_en_tool_call(resp, SCHEMAS)

    def test_cerrar_con_stop_NO_es_un_corte(self):
        # CONTRAFACTUAL: cerrar sin tools es el contrato del régimen nativo.
        resp = _Resp(finish_reason="stop", texto="ya está")
        assert L._corte_en_tool_call(resp, SCHEMAS) == ""

    def test_sin_tools_ofrecidas_no_hay_corte_de_tool_call(self):
        # Un turno de chat largo que se trunca no es este problema.
        resp = _Resp(finish_reason="length", tool_calls=[])
        assert L._corte_en_tool_call(resp, []) == ""

    def test_un_error_cualquiera_del_server_no_se_confunde(self):
        # Si el server está caído no se reintenta subiendo tokens: es otro
        # problema y confundirlos escondería el de verdad.
        resp = _Resp(ok=False, error="Connection refused")
        assert L._corte_en_tool_call(resp, SCHEMAS) == ""

    def test_un_turno_con_tool_calls_nunca_es_corte(self):
        resp = _Resp(finish_reason="length",
                     tool_calls=[{"function": {"name": "escribir_archivo"}}])
        assert L._corte_en_tool_call(resp, SCHEMAS) == ""


class TestElBucleReintentaConMasPresupuesto:
    """Lo que importa no es detectarlo: es que la tarea SALGA adelante."""

    def _correr(self, respuestas, perfil=None):
        """Corre el bucle con un `completar` guionizado. Devuelve (res, vistos)."""
        vistos = []

        def _completar(mensajes, tools=None, **sampling):
            vistos.append({"max_tokens": sampling.get("max_tokens"),
                           "mensajes": list(mensajes)})
            return respuestas[min(len(vistos) - 1, len(respuestas) - 1)]

        res = L.bucle_nativo(
            task="escribe una landing page", system="", completar=_completar,
            schemas=SCHEMAS, args_legacy=lambda *a, **k: "",
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda *a, **k: {"role": "tool", "content": "ok"},
            run_tool=lambda *a, **k: "RESULTADO escribir_archivo: ok",
            ctx={}, perfil=(perfil or {"max_tokens": 1024}), history=[],
            trace=[], print_fn=lambda *a, **k: None, max_turns=4)
        return res, vistos

    def test_sube_el_presupuesto_y_repite_el_MISMO_paso(self):
        cortada = _Resp(finish_reason="length", tool_calls=[])
        buena = _Resp(finish_reason="stop", texto="listo, escrita")
        res, vistos = self._correr([cortada, buena])
        # Sin el fix: una sola llamada y la tarea muere "sin usar herramientas".
        assert len(vistos) >= 2
        assert vistos[1]["max_tokens"] > vistos[0]["max_tokens"], \
            "el reintento tiene que ir con MAS presupuesto"
        assert res["texto"] == "listo, escrita"

    def test_el_500_de_parseo_tambien_se_reintenta(self):
        rota = _Resp(ok=False, error="Failed to parse tool call arguments as JSON")
        buena = _Resp(finish_reason="stop", texto="ok")
        res, vistos = self._correr([rota, buena])
        assert len(vistos) >= 2
        assert vistos[1]["max_tokens"] > vistos[0]["max_tokens"]
        assert res["texto"] == "ok"

    def test_si_no_alcanza_le_dice_al_modelo_que_escriba_por_partes(self):
        # Techo alcanzado: en vez de morir callado, se le da una salida.
        cortada = _Resp(finish_reason="length", tool_calls=[])
        res, vistos = self._correr([cortada])
        textos = [m.get("content", "") for v in vistos for m in v["mensajes"]
                  if m.get("role") == "user"]
        assert any("POR PARTES" in t for t in textos), \
            "hay que decirle al modelo como salir del atasco"

    def test_no_reintenta_para_siempre(self):
        cortada = _Resp(finish_reason="length", tool_calls=[])
        _, vistos = self._correr([cortada])
        # 2 reintentos + el aviso: no puede quedarse en bucle quemando GPU.
        assert len(vistos) <= 6, f"demasiadas llamadas: {len(vistos)}"

    def test_un_turno_normal_no_paga_reintentos(self):
        # CONTRAFACTUAL: el camino feliz hace UNA llamada, como siempre.
        buena = _Resp(finish_reason="stop", texto="hecho")
        res, vistos = self._correr([buena])
        assert len(vistos) == 1
        assert res["texto"] == "hecho"


class TestArgumentosRotosNoSeEjecutan:
    """LA CAUSA RAIZ, y el fallo mas caro de los tres.

    chat_client YA marcaba `argumentos_rotos=True` cuando el JSON del tool call
    no parseaba... y el bucle no miraba la marca: llamaba a la tool con el crudo
    sin parsear. La tool recibia basura y se quejaba de lo que le tocara. En la
    corrida real el modelo mando

        {"path":"cafeteria.html","contenido":"<!DOCTYPE html>...   <- cortado

    y el agente recibio "ERROR: path outside agent workspace". O sea: se puso a
    arreglar la RUTA (que era correcta) mientras el problema era el TAMANO del
    contenido. Tres intentos persiguiendo el sintoma equivocado, 100 segundos y
    el workspace vacio.

    Verificado end-to-end tras el fix: la misma tarea escribe un index.html de
    23.370 chars con estilos.
    """

    class _TC:
        def __init__(self, roto=True):
            self.id = "call_1"
            self.nombre = "escribir_archivo"
            self.argumentos = {"args": '{"path":"x.html","contenido":"<!DOC'}
            self.argumentos_crudos = '{"path":"x.html","contenido":"<!DOC'
            self.argumentos_rotos = roto

    def test_el_detector_ve_los_argumentos_rotos(self):
        resp = _Resp(finish_reason="tool_calls", tool_calls=[self._TC()])
        assert L._corte_en_tool_call(resp, SCHEMAS)

    def test_un_tool_call_sano_no_dispara_nada(self):
        resp = _Resp(finish_reason="tool_calls",
                     tool_calls=[self._TC(roto=False)])
        assert L._corte_en_tool_call(resp, SCHEMAS) == ""

    def test_la_tool_NO_se_ejecuta_con_argumentos_rotos(self):
        """Sin el fix, run_tool recibia el crudo y la tool inventaba un error
        sobre la ruta. Aqui se comprueba que ni siquiera se la llama."""
        ejecutadas = []
        respuestas = [_Resp(finish_reason="tool_calls",
                            tool_calls=[self._TC()]),
                      _Resp(finish_reason="stop", texto="ok")]
        vistos = []

        def _completar(mensajes, tools=None, **sampling):
            vistos.append(sampling.get("max_tokens"))
            return respuestas[min(len(vistos) - 1, len(respuestas) - 1)]

        res = L.bucle_nativo(
            task="escribe una pagina", system="", completar=_completar,
            schemas=SCHEMAS, args_legacy=lambda *a, **k: "",
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda tid, txt: {"role": "tool", "content": txt},
            run_tool=lambda n, a, c: ejecutadas.append(n) or "RESULTADO ok",
            ctx={}, perfil={"max_tokens": 1024}, history=[], trace=[],
            print_fn=lambda *a, **k: None, max_turns=3)
        assert ejecutadas == [],             "no se puede llamar a la tool con argumentos que no parsean"
        assert res["texto"] == "ok"

    def test_el_mensaje_al_modelo_apunta_al_problema_REAL(self):
        """El agente tiene que enterarse de que sobra CONTENIDO, no de que la
        ruta esta mal: si no, arregla lo que no toca."""
        mensajes_tool = []

        def _completar(mensajes, tools=None, **sampling):
            # SIEMPRE rota: se agota la rampa, se inyecta el aviso y el bucle
            # acaba llegando al for de ejecucion, que es donde se le contesta
            # a la llamada rota. Ese turno tool es lo que se mide aqui.
            return _Resp(finish_reason="tool_calls", tool_calls=[self._TC()])

        L.bucle_nativo(
            task="escribe una pagina", system="", completar=_completar,
            schemas=SCHEMAS, args_legacy=lambda *a, **k: "",
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda tid, txt: mensajes_tool.append(txt) or
                                          {"role": "tool", "content": txt},
            run_tool=lambda *a, **k: "RESULTADO ok",
            ctx={}, perfil={"max_tokens": 8192}, history=[], trace=[],
            print_fn=lambda *a, **k: None, max_turns=3)
        assert mensajes_tool, "el modelo tiene que recibir un turno tool"
        texto = " ".join(mensajes_tool)
        assert "CORTADOS" in texto
        assert "POR PARTES" in texto.upper()
        assert "workspace" not in texto,             "el mensaje no puede culpar a la ruta: ese era el bug"


class TestLoQueLaRevisionAdversarialCazo:
    """Tres agentes revisores encontraron esto en el arreglo de arriba, el mismo
    dia que se escribio. Los dos primeros eran de gravedad ALTA."""

    def test_una_respuesta_larga_truncada_NO_es_un_tool_call_cortado(self):
        # El bug: una respuesta final en prosa que se corta por presupuesto
        # llega igual (length + cero tool_calls). Se reintentaba TRES veces y
        # encima se le inyectaba al modelo un "escribe el fichero por partes"
        # que no venia a cuento -- en una tarea que no escribia ningun fichero.
        larga = _Resp(finish_reason="length", tool_calls=[],
                      texto="x" * 400)
        assert L._corte_en_tool_call(larga, SCHEMAS) == ""

    def test_un_turno_sin_texto_sigue_siendo_corte(self):
        # CONTRAFACTUAL: el caso real (cero texto, cero tools) no se pierde.
        vacio = _Resp(finish_reason="length", tool_calls=[], texto="")
        assert L._corte_en_tool_call(vacio, SCHEMAS)

    def test_un_tool_call_SANO_no_se_tira_por_culpa_de_uno_roto(self):
        # El bug: con dos tool calls en el turno y uno solo cortado, se
        # descartaba el turno ENTERO y el trabajo bueno se perdia.
        class _TC:
            def __init__(self, roto):
                self.id, self.nombre = "c", "escribir_archivo"
                self.argumentos, self.argumentos_crudos = {}, "{"
                self.argumentos_rotos = roto

        mixto = _Resp(finish_reason="tool_calls",
                      tool_calls=[_TC(True), _TC(False)])
        assert L._corte_en_tool_call(mixto, SCHEMAS) == ""
        todas_rotas = _Resp(finish_reason="tool_calls",
                            tool_calls=[_TC(True), _TC(True)])
        assert L._corte_en_tool_call(todas_rotas, SCHEMAS)


class TestLaRampaDePresupuesto:
    """Lo que la verificacion adversarial midio del reintento en si."""

    def _correr(self, respuestas, perfil):
        vistos = []

        def _completar(mensajes, tools=None, **sampling):
            vistos.append(sampling.get("max_tokens"))
            return respuestas[min(len(vistos) - 1, len(respuestas) - 1)]

        L.bucle_nativo(
            task="t", system="", completar=_completar, schemas=SCHEMAS,
            args_legacy=lambda *a, **k: "",
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda tid, txt: {"role": "tool", "content": txt},
            run_tool=lambda *a, **k: "RESULTADO ok",
            ctx={}, perfil=perfil, history=[], trace=[],
            print_fn=lambda *a, **k: None, max_turns=4)
        return vistos

    def test_el_techo_es_relativo_al_perfil(self):
        # Con un perfil de 32768 y techo fijo de 16384 la rampa no corria: 0
        # reintentos y un aviso que decia "no cabe ni con 32768" sin haberlo
        # probado con mas.
        cortada = _Resp(finish_reason="length", tool_calls=[], texto="")
        vistos = self._correr([cortada], {"max_tokens": 32768})
        assert max(vistos) > 32768, f"la rampa no subio: {vistos}"

    def test_el_presupuesto_vuelve_a_su_sitio_en_el_paso_siguiente(self):
        """La subida es para ESE paso. Si persiste, el resto de la tarea corre
        con un techo que nadie pidio (lo midio la revision adversarial)."""
        class _TCSano:
            id, nombre = "c1", "leer_archivo"
            argumentos, argumentos_crudos = {}, "{}"
            argumentos_rotos = False

        guion = [
            # paso 1: se corta, se reintenta (sube), y acaba con una tool sana
            _Resp(finish_reason="length", tool_calls=[], texto=""),
            _Resp(finish_reason="length", tool_calls=[], texto=""),
            _Resp(finish_reason="tool_calls", tool_calls=[_TCSano()]),
            # paso 2: turno normal -> tiene que ir con el presupuesto del perfil
            _Resp(finish_reason="stop", texto="listo"),
        ]
        vistos = []

        def _completar(mensajes, tools=None, **sampling):
            vistos.append(sampling.get("max_tokens"))
            return guion[min(len(vistos) - 1, len(guion) - 1)]

        L.bucle_nativo(
            task="t", system="", completar=_completar, schemas=SCHEMAS,
            args_legacy=lambda *a, **k: "",
            mensaje_assistant=lambda r: {"role": "assistant", "content": ""},
            mensaje_tool=lambda tid, txt: {"role": "tool", "content": txt},
            run_tool=lambda *a, **k: "RESULTADO ok",
            ctx={}, perfil={"max_tokens": 4096}, history=[], trace=[],
            print_fn=lambda *a, **k: None, max_turns=4)
        assert vistos[0] == 4096
        assert vistos[1] > 4096, f"no subio en el paso 1: {vistos}"
        assert vistos[-1] == 4096, f"quedo el presupuesto subido: {vistos}"


class TestCortadoNoEsLoMismoQueMalformado:
    """La regresion que introdujo el propio arreglo: un JSON raro pero COMPLETO
    (comillas simples) lo rescataba args_legacy y la tool corria. Bloquear los
    dos por igual rompia un caso que funcionaba."""

    def test_distingue_los_dos(self):
        assert L._parece_cortado('{"path":"x","contenido":"<!DOC')      # cortado
        assert L._parece_cortado("")                                    # vacio
        assert not L._parece_cortado("{'path': 'a.txt'}")               # raro
        assert not L._parece_cortado('{"path":"a.txt"}')                # sano

    def test_una_llave_sin_cerrar_es_corte(self):
        assert L._parece_cortado('{"a": {"b": 1}')

    def test_las_comillas_escapadas_no_confunden(self):
        assert not L._parece_cortado('{"t":"dice \\"hola\\" y ya"}')

