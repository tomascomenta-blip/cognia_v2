"""
La FAMILIA del modelo sale de los METADATOS, no del nombre del fichero.

LA AVERIA QUE CUBREN (2026-08-17). El cerebro principal de la casa es
``Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf`` y el repo lo
declaraba "Qwen2.5 abliterado" en dos sitios (cognia/flota.py:63 y
cognia/agent/model_profiles.py:65). El GGUF dice otra cosa:

    general.architecture      = qwen35
    general.base_model.0.name = Qwen3.5 9B

El coste no era documental. La tabla ``_FAMILIAS_NATIVAS`` decide por SUBSTRING
DEL NOMBRE y a la entrada 'qwythos' le faltaba ``piensa``, asi que
``_kwargs_plantilla`` devolvia {} SIEMPRE: ``COGNIA_THINKING=off`` era un no-op
mudo sobre el cerebro principal — el usuario apagaba el pensamiento y el modelo
seguia pensando. La plantilla del propio GGUF lee ``enable_thinking`` (esta
verificado abajo, y renderizada da ``<think>\\n\\n</think>`` con False).

Los dos fixes que cubren estos tests:
  1. `_conducta_medida`: piensa/usa_effort se LEEN de la plantilla que sirve el
     server. La regla reproduce EXACTO las 5 entradas escritas a mano y tapa la
     sexta (qwythos).
  2. `familia_por_arch`: si el nombre no casa con ninguna tabla, decide
     `general.architecture`. Renombrar el GGUF deja de borrarle el sampling.

Los tests que necesitan el GGUF real de 5,7 GB se saltan si no esta (la suite
tiene que correr en una maquina sin la flota bajada); el resto usa un GGUF
SINTETICO escrito byte a byte por `_gguf_minimo`, que es lo que hace que el
lector de cabeceras se pruebe de verdad y no contra un mock.
"""
import json
import os
import struct
from pathlib import Path

import pytest

import cognia.backend_activo as ba
from cognia.agent import capacidad, gguf_meta
from cognia.agent import model_profiles as MP

MODELOS = Path.home() / ".cognia" / "models"
QWYTHOS = MODELOS / "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf"


# ── GGUF sintetico (cabecera KV valida, sin tensores) ───────────────────────

def _kv_str(clave: str, valor: str) -> bytes:
    k, v = clave.encode(), valor.encode()
    return (struct.pack("<Q", len(k)) + k + struct.pack("<I", 8)
            + struct.pack("<Q", len(v)) + v)


def _kv_u32(clave: str, valor: int) -> bytes:
    k = clave.encode()
    return (struct.pack("<Q", len(k)) + k + struct.pack("<I", 4)
            + struct.pack("<I", valor))


def _kv_arr_str(clave: str, valores: list) -> bytes:
    """Array de strings: es lo que hace grande a una cabecera real (el
    vocabulario son 151.936 entradas) y lo que el lector tiene que SALTAR."""
    k = clave.encode()
    out = [struct.pack("<Q", len(k)), k, struct.pack("<I", 9),
           struct.pack("<I", 8), struct.pack("<Q", len(valores))]
    for v in valores:
        b = v.encode()
        out += [struct.pack("<Q", len(b)), b]
    return b"".join(out)


def _gguf_minimo(destino: Path, arch: str, plantilla: str = "",
                 vocab: int = 500) -> Path:
    campos = [_kv_str("general.architecture", arch),
              _kv_str("general.name", f"sintetico {arch}"),
              _kv_u32(f"{arch}.block_count", 33),
              _kv_u32(f"{arch}.context_length", 1048576),
              _kv_arr_str("tokenizer.ggml.tokens",
                          [f"tok{i}" for i in range(vocab)])]
    if plantilla:
        campos.append(_kv_str("tokenizer.chat_template", plantilla))
    cuerpo = b"".join(campos)
    destino.write_bytes(b"GGUF" + struct.pack("<I", 3)
                        + struct.pack("<Q", 0)            # tensor_count
                        + struct.pack("<Q", len(campos))  # metadata_kv_count
                        + cuerpo)
    return destino


# ── El lector de metadatos ──────────────────────────────────────────────────

class TestGgufMeta:
    def test_lee_arch_y_plantilla_de_un_gguf_sintetico(self, tmp_path):
        p = _gguf_minimo(tmp_path / "x.gguf", "qwen35", "{{ enable_thinking }}")
        gguf_meta.resetear_cache()
        m = gguf_meta.meta(p)
        assert m["arch"] == "qwen35"
        assert m["n_ctx_train"] == 1048576
        assert m["bloques"] == 33
        assert "enable_thinking" in m["plantilla"]

    def test_salta_arrays_grandes_sin_materializarlos(self, tmp_path):
        """El bug del primer intento: un tope unico de 8 MB para leer Y saltar
        daba {} en Qwythos y gpt-oss, cuyo vocabulario+merges pasa de 8 MB."""
        p = _gguf_minimo(tmp_path / "gordo.gguf", "qwen35", "hola", vocab=200000)
        assert p.stat().st_size > 2 * 1024 * 1024
        gguf_meta.resetear_cache()
        assert gguf_meta.meta(p)["arch"] == "qwen35"

    def test_fichero_que_no_es_gguf_devuelve_vacio(self, tmp_path):
        malo = tmp_path / "no.gguf"
        malo.write_bytes(b"esto no es un gguf" * 100)
        gguf_meta.resetear_cache()
        assert gguf_meta.meta(malo) == {}

    def test_fichero_ausente_devuelve_vacio(self, tmp_path):
        gguf_meta.resetear_cache()
        assert gguf_meta.meta(tmp_path / "no-existe.gguf") == {}

    def test_cabecera_truncada_devuelve_vacio(self, tmp_path):
        """Un GGUF a medio bajar no puede tumbar el camino del agente."""
        p = _gguf_minimo(tmp_path / "medio.gguf", "qwen35", "hola")
        crudo = p.read_bytes()
        p.write_bytes(crudo[:len(crudo) // 2])
        gguf_meta.resetear_cache()
        assert gguf_meta.meta(p) == {}

    @pytest.mark.skipif(not QWYTHOS.exists(), reason="el GGUF de Qwythos no esta")
    def test_qwythos_es_qwen35_y_no_qwen25(self):
        """EL HALLAZGO, contra el fichero real."""
        gguf_meta.resetear_cache()
        m = gguf_meta.meta(QWYTHOS)
        assert m["arch"] == "qwen35"
        assert m["base"] == "Qwen3.5 9B"
        assert m["n_ctx_train"] == 1048576
        assert "enable_thinking" in m["plantilla"]


# ── La conducta se MIDE de la plantilla ─────────────────────────────────────

class TestConductaMedida:
    def test_plantilla_con_enable_thinking_da_piensa(self):
        assert MP._conducta_medida("{% if enable_thinking %}x{% endif %}",
                                   {})["piensa"] is True

    def test_plantilla_sin_enable_thinking_no_piensa(self):
        assert MP._conducta_medida("{{ messages }}", {})["piensa"] is False

    def test_caps_del_server_gana_al_substring(self):
        """llama-server ya parsea la plantilla y publica
        chat_template_caps.supports_reasoning_effort: si viene, manda."""
        medido = MP._conducta_medida("reasoning_effort esta en el texto",
                                     {"supports_reasoning_effort": False})
        assert medido["usa_effort"] is False

    def test_sin_plantilla_no_inventa_nada(self):
        """Server que no publica chat_template: no se decide nada (y el perfil
        se queda con lo que diga la tabla, como siempre)."""
        assert MP._conducta_medida("", {}) == {}

    @pytest.mark.skipif(not QWYTHOS.exists(), reason="el GGUF de Qwythos no esta")
    def test_reproduce_la_tabla_escrita_a_mano(self):
        """LA EVIDENCIA de que la regla medida puede reemplazar a la tabla:
        sobre los GGUF de esta maquina da exactamente lo que decia el dict, y
        ademas rellena qwythos, que era el que faltaba."""
        esperado = {
            "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf":
                {"piensa": True, "usa_effort": False},     # <- el que faltaba
            "gpt-oss-20b-MXFP4.gguf":
                {"piensa": False, "usa_effort": True},
            "nemotron-3.5-lightning-30b-a3b-Q4_0.gguf":
                {"piensa": True, "usa_effort": False},
            "qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf":
                {"piensa": False, "usa_effort": False},
            "OpenReasoning-Nemotron-14B.Q4_K_M.gguf":
                {"piensa": False, "usa_effort": False},
        }
        vistos = 0
        for nombre, quiero in esperado.items():
            ruta = MODELOS / nombre
            if not ruta.exists():
                continue
            vistos += 1
            gguf_meta.resetear_cache()
            plantilla = gguf_meta.meta(ruta).get("plantilla", "")
            assert MP._conducta_medida(plantilla, {}) == quiero, nombre
        assert vistos >= 2, "hacen falta al menos dos GGUF para que compare algo"


# ── El perfil completo ──────────────────────────────────────────────────────

_PLANTILLA_PIENSA = ("{%- if enable_thinking is defined and enable_thinking "
                     "is false %}<think>\n\n</think>{%- else %}<think>{%- endif %}")

URL = "http://127.0.0.1:8080"


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch, tmp_path):
    for var in ("COGNIA_AGENT_TOOLS", "COGNIA_AGENT_LEGACY", "COGNIA_THINKING",
                "COGNIA_REASONING_EFFORT", "COGNIA_LLM_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))
    monkeypatch.setattr(ba, "_props_cache", {})
    monkeypatch.setattr(ba, "_props_sello", {})
    monkeypatch.setattr(capacidad, "_mem", {})
    gguf_meta.resetear_cache()


def _servidor(monkeypatch, modelo, ruta="", plantilla="", caps=None):
    datos = {"modelo": modelo, "ruta": str(ruta), "n_ctx": 32768,
             "puerto": 8080, "sampling": {}, "plantilla": plantilla,
             "caps": dict(caps or {})}
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: dict(datos))
    monkeypatch.setattr(capacidad, "soporta_tools",
                        lambda url="", forzar=False: True)
    monkeypatch.setattr(capacidad, "medicion",
                        lambda url="", forzar=False: {"soporta_tools": True,
                                                      "motivo": "doble"})


class TestPerfilConMetadatos:
    def test_qwythos_recibe_enable_thinking(self, monkeypatch):
        """EL FIX. Antes salia sin kwargs_plantilla porque la entrada
        'qwythos' de la tabla no declaraba `piensa`."""
        _servidor(monkeypatch, "huihui-qwythos-9b-q4_k.gguf",
                  plantilla=_PLANTILLA_PIENSA)
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["familia"] == "qwythos"
        assert p["kwargs_plantilla"] == {"enable_thinking": True}
        assert p["conducta_medida"]["piensa"] is True

    def test_cognia_thinking_off_apaga_de_verdad(self, monkeypatch):
        """El knob que era mudo sobre el cerebro principal."""
        monkeypatch.setenv("COGNIA_THINKING", "off")
        _servidor(monkeypatch, "huihui-qwythos-9b-q4_k.gguf",
                  plantilla=_PLANTILLA_PIENSA)
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["kwargs_plantilla"] == {"enable_thinking": False}

    def test_modelo_sin_thinking_manda_el_body_historico(self, monkeypatch):
        """Contrafactual: una plantilla que NO lee enable_thinking no puede
        empezar a recibirlo (el body tiene que salir byte-identico)."""
        _servidor(monkeypatch, "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
                  plantilla="{{ messages }}")
        p = MP.perfil_del_agente(URL, forzar=True)
        assert "kwargs_plantilla" not in p
        assert p["reasoning_effort"] == ""

    def test_plantilla_con_effort_no_inventa_low(self, monkeypatch):
        """usa_effort MEDIDO (no de la tabla) habilita COGNIA_REASONING_EFFORT
        pero NO le cambia el default al modelo: sin env, el esfuerzo se lo
        queda el server."""
        _servidor(monkeypatch, "modelo-nuevo-13b.gguf",
                  plantilla="{{ reasoning_effort }}")
        assert MP.perfil_del_agente(URL, forzar=True)["reasoning_effort"] == ""
        monkeypatch.setenv("COGNIA_REASONING_EFFORT", "high")
        ba._props_cache.clear()
        assert MP.perfil_del_agente(URL, forzar=True)["reasoning_effort"] == "high"

    def test_gpt_oss_sigue_con_low(self, monkeypatch):
        """Y la familia que SI tiene el 'low' medido no lo pierde."""
        _servidor(monkeypatch, "gpt-oss-20b-mxfp4.gguf",
                  plantilla="{{ reasoning_effort }}")
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["reasoning_effort"] == "low"
        assert p["temperature"] == 1.0 and p["top_p"] == 1.0

    def test_gguf_renombrado_conserva_su_sampling(self, monkeypatch, tmp_path):
        """LA BOMBA DEL NOMBRE. El mismo modelo con otro nombre de fichero:
        por substring no casa con nada; por arquitectura, si."""
        ruta = _gguf_minimo(tmp_path / "cerebro-de-la-casa.gguf", "qwen35",
                            _PLANTILLA_PIENSA)
        _servidor(monkeypatch, "cerebro-de-la-casa.gguf", ruta=ruta,
                  plantilla=_PLANTILLA_PIENSA)
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["familia"] == "qwythos"
        assert p["arch"] == "qwen35"
        assert p["temperature"] == 0.7 and p["top_p"] == 0.8
        assert "arch del GGUF" in p["sampling_origen"]

    def test_el_nombre_sigue_ganandole_al_arch(self, monkeypatch, tmp_path):
        """El backstop es BACKSTOP: no puede pisar a quien ya funcionaba."""
        ruta = _gguf_minimo(tmp_path / "gpt-oss-20b-mxfp4.gguf", "qwen35")
        _servidor(monkeypatch, "gpt-oss-20b-mxfp4.gguf", ruta=ruta)
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["familia"] == "gpt-oss"
        assert p["temperature"] == 1.0
        assert "nombre del fichero" in p["sampling_origen"]

    def test_arch_desconocida_no_inventa_familia(self, monkeypatch, tmp_path):
        """'qwen2' y 'qwen3' NO estan mapeadas a proposito: son arquitecturas
        con decenas de modelos distintos y elegirles sampling seria volver a
        declarar en vez de medir."""
        ruta = _gguf_minimo(tmp_path / "raro.gguf", "qwen2")
        _servidor(monkeypatch, "raro.gguf", ruta=ruta)
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["familia"] == ""
        assert p["arch"] == "qwen2"

    def test_ruta_ilegible_no_rompe_el_perfil(self, monkeypatch):
        """Server remoto: /props trae una ruta que en ESTA maquina no existe."""
        _servidor(monkeypatch, "algo.gguf", ruta="Z:/no/existe/algo.gguf")
        p = MP.perfil_del_agente(URL, forzar=True)
        assert p["tools"] == "nativo"
        assert "arch" not in p


# ── /props transporta los datos crudos ──────────────────────────────────────

class TestPropsCrudos:
    def test_props_expone_ruta_plantilla_y_caps(self, monkeypatch):
        crudo = {
            "model_path": "C:/m/qwythos.gguf",
            "default_generation_settings": {"n_ctx": 32768,
                                            "params": {"temperature": 0.8}},
            "chat_template": "{{ enable_thinking }}",
            "chat_template_caps": {"supports_reasoning_effort": False},
        }

        class _Resp:
            def read(self):
                return json.dumps(crudo).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(ba.urllib.request, "urlopen",
                            lambda *a, **k: _Resp())
        p = ba.props(URL, forzar=True)
        assert p["modelo"] == "qwythos.gguf"
        assert p["ruta"] == "C:/m/qwythos.gguf"
        assert p["plantilla"] == "{{ enable_thinking }}"
        assert p["caps"] == {"supports_reasoning_effort": False}
        assert p["n_ctx"] == 32768


# ── La sonda de capacidad tambien apaga el pensamiento ──────────────────────

class TestSondaApagaElPensamiento:
    """El reintento de capacidad.medicion() ante finish_reason='length' apaga
    el pensamiento 'donde se puede'. 'Donde se puede' lo decidia la misma
    tabla por nombre, asi que con QWYTHOS -- el razonador que mas gasta en
    pensar y el que motivo el reintento -- salia SIN apagarlo. Server HTTP de
    verdad (no dobles de urlopen), igual que test_capacidad_nativa."""

    def test_reintento_manda_enable_thinking_false(self, monkeypatch, tmp_path):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        gguf = _gguf_minimo(tmp_path / "huihui-qwythos-9b-q4_k.gguf",
                            "qwen35", _PLANTILLA_PIENSA)
        cuerpos = []

        class _H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _responder(self, payload):
                cuerpo = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def do_GET(self):
                self._responder({
                    "model_path": str(gguf),
                    "chat_template": _PLANTILLA_PIENSA,
                    "chat_template_caps": {"supports_reasoning_effort": False},
                    "default_generation_settings": {"n_ctx": 4096}})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                cuerpos.append(json.loads(self.rfile.read(n) or b"{}"))
                # 'length' en la primera -> dispara el reintento.
                self._responder({"choices": [{
                    "finish_reason": "length" if len(cuerpos) == 1 else "stop",
                    "message": {"content": "..."}}]})

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            capacidad.medicion(url, forzar=True)
        finally:
            srv.shutdown()
            srv.server_close()

        assert len(cuerpos) == 2, "no hubo reintento"
        assert cuerpos[0].get("chat_template_kwargs") is None
        assert cuerpos[1]["chat_template_kwargs"] == {"enable_thinking": False}
