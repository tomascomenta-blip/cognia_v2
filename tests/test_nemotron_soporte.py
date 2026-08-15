"""
Soporte Nemotron (2026-08-14) — Cognia se construyo sobre Qwen y el primer
modelo de otra familia que entro destapo tres cosas que fallaban EN SILENCIO:

1. `_perfil_auto` decidia el system prompt con una lista LITERAL de tamanos
   ('32b' y '20b' estaban, '30b' no) -> el 30B recibia el prompt del 3B.
2. El razonamiento de Nemotron no viaja por `reasoning_effort` (eso es de
   harmony) sino por `chat_template_kwargs.enable_thinking`, y no habia
   canal para mandarlo.
3. El sampling del modelo lo declara su propio GGUF (1.0/0.95) y no habia
   familia que lo fijara.

Cada test de aca falla sin el fix. El contrafactual (que Qwen/harmony no
cambien ni un byte) esta en cada bloque.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia import system_prompt as SP
from cognia.agent import model_profiles as MP


class TestPerfilAutoPorTamano:

    def test_nemotron_30b_recibe_el_prompt_completo(self, monkeypatch):
        # El bug exacto: '30b' no estaba en la lista literal.
        monkeypatch.setenv("LLAMA_GGUF_PATH",
                           "nemotron-3.5-lightning-30b-a3b-Q4_0.gguf")
        monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
        assert SP._perfil_auto() == "completo"

    def test_los_tamanos_de_siempre_siguen_completos(self, monkeypatch):
        monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
        for nombre in ("Huihui-Qwythos-9B-abliterated-Q4_K.gguf",
                       "gpt-oss-20b-MXFP4.gguf",
                       "qwen2.5-coder-14b-instruct-q4_k_m.gguf"):
            monkeypatch.setenv("LLAMA_GGUF_PATH", nombre)
            assert SP._perfil_auto() == "completo", nombre

    def test_el_chico_sigue_compacto(self, monkeypatch):
        monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
        for nombre in ("qwen2.5-coder-0.5b-instruct-q8_0.gguf",
                       "Qwen3-1.7B-Q4_K_M.gguf",
                       "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"):
            monkeypatch.setenv("LLAMA_GGUF_PATH", nombre)
            assert SP._perfil_auto() == "compacto", nombre

    def test_el_override_por_entorno_sigue_ganando(self, monkeypatch):
        monkeypatch.setenv("LLAMA_GGUF_PATH", "nemotron-30b.gguf")
        monkeypatch.setenv("COGNIA_SYSTEM_PROMPT_PERFIL", "minimo")
        assert SP._perfil_auto() == "minimo"


class TestFamiliaNemotron:

    def test_sampling_es_el_que_declara_su_gguf(self):
        cfg, fam = MP._cfg_familia("nemotron-3.5-lightning-30b-a3b-q4_0.gguf")
        # 'nemotron-3.5' y no 'nemotron': el OpenReasoning-Nemotron-14B es
        # otra familia (Qwen2.5 destilado) y con la clave corta se llevaba
        # este sampling y un enable_thinking que su plantilla no lee.
        assert fam == "nemotron-3.5"
        assert cfg["temperature"] == 1.0 and cfg["top_p"] == 0.95

    def test_no_usa_reasoning_effort(self):
        # reasoning_effort es de harmony; mandarselo a Nemotron seria fingir
        # un control que su template no lee.
        cfg, _ = MP._cfg_familia("nemotron-3.5-lightning-30b-a3b-q4_0.gguf")
        assert cfg.get("usa_effort") is False

    def test_qwythos_intacto(self):
        cfg, fam = MP._cfg_familia("huihui-qwythos-9b-q4_k.gguf")
        assert fam == "qwythos"
        assert cfg["temperature"] == 0.7 and cfg["top_p"] == 0.8


class TestKwargsPlantilla:

    def test_nemotron_pide_enable_thinking(self, monkeypatch):
        monkeypatch.delenv("COGNIA_THINKING", raising=False)
        cfg, _ = MP._cfg_familia("nemotron-3.5-lightning-30b-a3b-q4_0.gguf")
        assert MP._kwargs_plantilla(cfg) == {"enable_thinking": True}

    def test_el_entorno_lo_apaga(self, monkeypatch):
        monkeypatch.setenv("COGNIA_THINKING", "off")
        cfg, _ = MP._cfg_familia("nemotron-3.5-lightning-30b-a3b-q4_0.gguf")
        assert MP._kwargs_plantilla(cfg) == {"enable_thinking": False}

    def test_familias_sin_piensa_no_mandan_nada(self, monkeypatch):
        # CONTRAFACTUAL: el body de Qwen/harmony no puede cambiar.
        monkeypatch.setenv("COGNIA_THINKING", "off")
        for modelo in ("huihui-qwythos-9b-q4_k.gguf", "gpt-oss-20b-mxfp4.gguf",
                       "un-modelo-desconocido.gguf"):
            cfg, _ = MP._cfg_familia(modelo)
            assert MP._kwargs_plantilla(cfg or {}) == {}, modelo


class TestSondaNoConfundeLengthConIncapacidad:
    """El fallo REAL del 2026-08-14: la sonda daba 256 tokens, Nemotron los
    gastaba pensando, el tool call salia truncado y el veredicto era 'no
    soporta tools / le falta --jinja'. Un 30B con tools nativas perfectas
    acababa en regimen de texto legacy por un presupuesto mal puesto."""

    def _server_falso(self, monkeypatch, respuestas):
        """Devuelve las respuestas en orden y registra los bodies enviados."""
        from cognia.agent import capacidad as CAP
        import json as _json
        enviados = []

        class _R:
            def __init__(self, payload):
                self._p = payload

            def read(self):
                return _json.dumps(self._p).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        it = iter(respuestas)

        def _urlopen(req, timeout=None):
            enviados.append(_json.loads(req.data.decode("utf-8")))
            return _R(next(it))

        monkeypatch.setattr(CAP.urllib.request, "urlopen", _urlopen)
        monkeypatch.setattr(CAP, "_modelo_de",
                            lambda url: "nemotron-3.5-lightning-30b-a3b-q4_0.gguf")
        return enviados

    _TRUNCADO = {"choices": [{"finish_reason": "length", "message": {
        "tool_calls": [{"function": {"name": "ping",
                                     "arguments": '{"x":"hola'}}]}}]}
    _BUENO = {"choices": [{"finish_reason": "tool_calls", "message": {
        "tool_calls": [{"function": {"name": "ping",
                                     "arguments": '{"x":"hola"}'}}]}}]}

    def test_reintenta_cuando_el_presupuesto_degollo_el_tool_call(
            self, monkeypatch):
        from cognia.agent import capacidad as CAP
        enviados = self._server_falso(monkeypatch,
                                      [self._TRUNCADO, self._BUENO])
        r = CAP.sondar("http://127.0.0.1:9")
        assert r["soporta_tools"] is True
        assert "presupuesto" in r["motivo"]
        # El reintento tiene que ensanchar el presupuesto Y apagar el
        # pensamiento: si solo repitiera la misma peticion seria adivinar.
        assert enviados[0]["max_tokens"] == 256
        assert enviados[1]["max_tokens"] == 1024
        assert enviados[1]["chat_template_kwargs"] == {"enable_thinking": False}

    def test_si_ni_con_presupuesto_llama_el_motivo_dice_la_verdad(
            self, monkeypatch):
        from cognia.agent import capacidad as CAP
        vacio = {"choices": [{"finish_reason": "length", "message": {}}]}
        self._server_falso(monkeypatch, [vacio, vacio])
        r = CAP.sondar("http://127.0.0.1:9")
        assert r["soporta_tools"] is False
        # NO puede acusar a --jinja: el server dijo 'length', no 'prosa'.
        assert "jinja" not in r["motivo"]
        assert "sin tokens" in r["motivo"]

    def test_un_modelo_que_de_verdad_no_sabe_sigue_reprobando(
            self, monkeypatch):
        from cognia.agent import capacidad as CAP
        prosa = {"choices": [{"finish_reason": "stop",
                              "message": {"content": "pong!"}}]}
        enviados = self._server_falso(monkeypatch, [prosa])
        r = CAP.sondar("http://127.0.0.1:9")
        assert r["soporta_tools"] is False
        assert "jinja" in r["motivo"]        # aca la sospecha SI corresponde
        assert len(enviados) == 1            # y no gasta un reintento inutil


class TestChatClientMergea:

    def test_kwargs_plantilla_no_pisa_reasoning_effort(self, monkeypatch):
        """Los dos ejes viajan por el mismo campo: el merge tiene que
        conservar ambos, no quedarse con el ultimo."""
        from cognia.agent import chat_client as CC
        capturado = {}

        class _Resp:
            status = 200

            def read(self):
                return b'{"choices":[{"message":{"content":"ok"},' \
                       b'"finish_reason":"stop"}]}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_urlopen(req, timeout=None):
            import json as _json
            capturado.update(_json.loads(req.data.decode("utf-8")))
            return _Resp()

        monkeypatch.setattr(CC.urllib.request, "urlopen", _fake_urlopen)
        CC.completar([{"role": "user", "content": "hola"}],
                     reasoning_effort="low",
                     kwargs_plantilla={"enable_thinking": False})
        assert capturado["chat_template_kwargs"] == {
            "reasoning_effort": "low", "enable_thinking": False}

    def test_sin_kwargs_el_body_es_el_de_siempre(self, monkeypatch):
        from cognia.agent import chat_client as CC
        capturado = {}

        class _Resp:
            def read(self):
                return b'{"choices":[{"message":{"content":"ok"},' \
                       b'"finish_reason":"stop"}]}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_urlopen(req, timeout=None):
            import json as _json
            capturado.update(_json.loads(req.data.decode("utf-8")))
            return _Resp()

        monkeypatch.setattr(CC.urllib.request, "urlopen", _fake_urlopen)
        CC.completar([{"role": "user", "content": "hola"}])
        assert "chat_template_kwargs" not in capturado


class TestLaTerceraTablaQueCasaPorSubstring:
    """El perfil de arranque casaba 'nemotron' a secas y se llevaba al
    OpenReasoning-Nemotron-14B (denso, ctx viable 16.384) y a la cabeza MTP.
    El combo 'pensar-en-lazo' arranca justamente --modelo OpenReasoning: le
    habría pedido un KV de 1M sobre 48 capas densas (~103 GB) en una placa de
    16 GB. Misma colisión que ya se arregló en flota.CEREBROS."""

    def test_el_14b_no_recibe_el_perfil_del_30b(self):
        from pathlib import Path
        from scripts import servir_modelo as SM
        assert SM.perfil_arranque(
            Path("OpenReasoning-Nemotron-14B.Q4_K_M.gguf")) == {}

    def test_la_cabeza_mtp_tampoco(self):
        from pathlib import Path
        from scripts import servir_modelo as SM
        assert SM.perfil_arranque(Path("nemotron-mtp-Q4_0.gguf")) == {}

    def test_el_35_si(self):
        from pathlib import Path
        from scripts import servir_modelo as SM
        p = SM.perfil_arranque(
            Path("nemotron-3.5-lightning-30b-a3b-Q4_0.gguf"))
        assert p.get("ctx") == 1048576

    def test_el_comando_del_14b_sigue_siendo_el_historico(self):
        """El contrafactual que el comentario declara y que no se cumplía."""
        from pathlib import Path
        from scripts import servir_modelo as SM
        modelo = Path("OpenReasoning-Nemotron-14B.Q4_K_M.gguf")
        perfil = SM.perfil_arranque(modelo)
        cmd = SM.construir_cmd(Path("llama-server.exe"), modelo, 8080, 8192,
                               no_mmap=perfil.get("no_mmap", False),
                               batch=perfil.get("batch", 0),
                               ubatch=perfil.get("ubatch", 0))
        assert "--no-mmap" not in cmd and "1048576" not in cmd
        assert cmd[cmd.index("--ctx-size") + 1] == "8192"

    def test_el_patron_mas_largo_gana_sin_depender_del_orden(self):
        from pathlib import Path
        from scripts import servir_modelo as SM
        SM.PERFILES_ARRANQUE["nemotron"] = {"ctx": 999}
        try:
            p = SM.perfil_arranque(
                Path("nemotron-3.5-lightning-30b-a3b-Q4_0.gguf"))
            assert p["ctx"] == 1048576      # gana 'nemotron-3.5', el largo
        finally:
            del SM.PERFILES_ARRANQUE["nemotron"]


class TestElReintentoNoJuzgaElTruncado:

    def test_si_el_reintento_no_llama_no_se_juzga_el_call_cortado(
            self, monkeypatch):
        """Antes: el reintento fallaba, quedaba el tool call TRUNCADO de la
        primera pasada y el veredicto era 'sus arguments no son JSON válido'
        — culpando al modelo de un corte nuestro."""
        from cognia.agent import capacidad as CAP
        import json as _json

        truncado = {"choices": [{"finish_reason": "length", "message": {
            "tool_calls": [{"function": {"name": "ping",
                                         "arguments": '{"x":"hola'}}]}}]}
        vacio = {"choices": [{"finish_reason": "length", "message": {}}]}
        it = iter([truncado, vacio])

        class _R:
            def __init__(self, p):
                self._p = p

            def read(self):
                return _json.dumps(self._p).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(CAP.urllib.request, "urlopen",
                            lambda req, timeout=None: _R(next(it)))
        monkeypatch.setattr(CAP, "_modelo_de", lambda url: "nemotron-3.5.gguf")
        r = CAP.sondar("http://127.0.0.1:9")
        assert r["soporta_tools"] is False
        assert "sin tokens" in r["motivo"]
        assert "JSON" not in r["motivo"]     # ya no acusa de JSON inválido


class TestElReplNoMienteElModelo:
    """e2e 2026-08-15: con Nemotron servido en :8080, `/modelo` decia
    "Qwythos ... server no arrancado" CUATRO LINEAS debajo de su propio
    banner, que decia Nemotron. La causa: el REPL construye el orquestador
    perezosamente, y sin el, la funcion caia directo a LLAMA_GGUF_PATH sin
    preguntarle nunca al server."""

    def test_sin_orquestador_igual_pregunta_al_server(self, monkeypatch):
        from cognia import cli
        import cognia.backend_activo as BA
        monkeypatch.setattr(BA, "props",
                            lambda url, forzar=False: {
                                "modelo": "el-que-sirve.gguf"})
        assert "el-que-sirve.gguf" in cli._modelo_activo_nombre(None)
        assert "server vivo" in cli._modelo_activo_nombre(None)

    def test_sin_server_sigue_diciendo_lo_configurado(self, monkeypatch):
        # Contrafactual: sin backend, el camino viejo intacto.
        from cognia import cli
        import cognia.backend_activo as BA
        monkeypatch.setattr(BA, "props",
                            lambda url, forzar=False: (_ for _ in ()).throw(
                                OSError("no hay server")))
        monkeypatch.setenv("LLAMA_GGUF_PATH", r"C:\m\configurado.gguf")
        salida = cli._modelo_activo_nombre(None)
        assert "configurado.gguf" in salida and "no arrancado" in salida


class TestNglExplicitoDegradabaElServer:
    """El hallazgo de la noche que mas rendimiento devolvio: pasar
    `--n-gpu-layers 99` sobre un MoE que no cabe entero impide que --fit
    reparta, empuja la VRAM a 15.835 de 16.311 MiB y el driver spillea a RAM.
    Medido: 113 tok/s de prefill contra 1.878 sin el flag (16,6x)."""

    def test_nemotron_arranca_sin_ngl_para_que_fit_reparta(self):
        from pathlib import Path
        from scripts import servir_modelo as SM
        perfil = SM.perfil_arranque(
            Path("nemotron-3.5-lightning-30b-a3b-Q4_0.gguf"))
        cmd = SM.construir_cmd("e", "m", 8080, perfil["ctx"],
                               ngl=perfil.get("ngl", 99))
        assert "--n-gpu-layers" not in cmd

    def test_los_demas_modelos_conservan_ngl_99(self):
        # Contrafactual: un modelo que cabe entero quiere sus capas en GPU.
        from scripts import servir_modelo as SM
        cmd = SM.construir_cmd("e", "m", 8080, 8192)
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "99"

    def test_el_timeout_usa_la_velocidad_del_server_SANO(self):
        # 39 tok/s (server arreglado), no los 14 del server degradado: cablear
        # el 14 habria dejado documentada una averia propia como si fuera una
        # propiedad del modelo.
        from cognia.agent import chat_client as CC
        assert CC._TOK_S_POR_FAMILIA["nemotron"] == 39.0
        # y con esa velocidad, Nemotron ya no necesita timeout extendido para
        # una tarea normal: cae en el piso historico.
        assert CC.timeout_para("nemotron-3.5.gguf", 4096) == 300.0
