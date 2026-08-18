"""
Soporte Qwen3.8-27B Ridge (2026-08-18) — el modelo que rompio el supuesto
"una arquitectura = un modelo".

Qwen3.8-27B declara `general.architecture = qwen35`, LA MISMA que Qwythos-9B,
que es el cerebro principal de la casa y tiene otro sampling (0.7/0.8 contra
1.0/0.95). El backstop por arquitectura de model_profiles copiaba el sampling
de la familia mapeada, y ese cfg PISA lo que /props declara (_sampling_base):
un Qwen3.8 renombrado se llevaba el sampling de su vecino de arquitectura, y
encima con la autoridad del backstop. Eso es lo que arregla familia_por_arch.

Y flota.combo_de_modelo era la ultima tabla del repo que casaba por substring
SIN ordenar por longitud: el resultado dependia de en que linea se escribio la
entrada.

Cada test de aca falla sin el fix. El contrafactual (que Qwythos, Nemotron y el
coder-14b no cambien ni un byte) va en cada bloque.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia import flota as FL
from cognia import system_prompt as SP
from cognia.agent import model_profiles as MP
from scripts import servir_modelo as SM

_RIDGE = "Qwen3.8-27B-Ridge-3.7bpw.gguf"


class TestFamiliaQwen38:

    def test_sampling_es_el_que_declara_su_gguf(self):
        cfg, fam = MP._cfg_familia(_RIDGE.lower())
        assert fam == "qwen3.8"
        assert cfg["temperature"] == 1.0 and cfg["top_p"] == 0.95

    def test_no_declara_usa_effort_porque_se_MIDE(self):
        # Yo escribi aqui usa_effort=False dando por hecho que reasoning_effort
        # era de harmony. La plantilla REAL del gguf dice que si lo soporta, o
        # sea que la declaracion a mano le apagaba un control que tiene.
        cfg, _ = MP._cfg_familia(_RIDGE.lower())
        assert "usa_effort" not in cfg

    def test_la_plantilla_real_declara_pensamiento_y_effort(self):
        # La fuente de verdad es la plantilla servida, no esta tabla.
        from cognia.agent.gguf_meta import meta
        ruta = Path.home() / ".cognia" / "models" / _RIDGE
        if not ruta.is_file():
            import pytest
            pytest.skip("el Ridge no esta instalado en esta maquina")
        conducta = MP._conducta_medida(meta(str(ruta)).get("plantilla", ""), {})
        assert conducta == {"piensa": True, "usa_effort": True}

    def test_no_declara_piensa(self):
        # `piensa` lo MIDE _conducta_medida() sobre la plantilla servida.
        # Declararlo aca repetiria el fallo que dejo COGNIA_THINKING mudo.
        cfg, _ = MP._cfg_familia(_RIDGE.lower())
        assert "piensa" not in cfg

    def test_qwythos_y_nemotron_intactos(self):
        cfg, fam = MP._cfg_familia("huihui-qwythos-9b-q4_k.gguf")
        assert fam == "qwythos" and cfg["temperature"] == 0.7
        cfg, fam = MP._cfg_familia("nemotron-3.5-lightning-30b-a3b-q4_0.gguf")
        assert fam == "nemotron-3.5" and cfg["top_p"] == 0.95

    def test_los_qwen3_chicos_no_se_llevan_esta_familia(self):
        # CONTRAFACTUAL de la clave: 'qwen3.8' no puede casar con Qwen3-4B ni
        # con Qwen3-1.7B (por eso la clave lleva el .8 y no es 'qwen3').
        for nombre in ("qwen3-4b-thinking-2507-q4_k_m.gguf",
                       "qwen3-1.7b-q4_k_m.gguf"):
            _, fam = MP._cfg_familia(nombre)
            assert fam != "qwen3.8", nombre


class TestBackstopArchYaNoEsUnivoco:
    """El fallo REAL: dos modelos, una arquitectura, dos samplings."""

    def _meta_falsa(self, monkeypatch, payload):
        import cognia.agent.gguf_meta as GM
        monkeypatch.setattr(GM, "meta", lambda ruta: dict(payload))

    def test_renombrado_conserva_su_propio_sampling(self, monkeypatch):
        # Nombre que NO casa con ninguna familia -> cae al backstop por arch.
        # Sin el fix devuelve 0.7/0.8 (el de Qwythos) para un Qwen3.8.
        self._meta_falsa(monkeypatch, {
            "arch": "qwen35",
            "sampling": {"temperature": 1.0, "top_p": 0.95},
        })
        cfg, fam = MP.familia_por_arch("modelo-sin-nombre-reconocible.gguf")
        assert fam == "qwythos"           # la familia de implementacion, si
        assert cfg["temperature"] == 1.0  # el sampling, del FICHERO
        assert cfg["top_p"] == 0.95

    def test_qwythos_por_arch_sigue_en_lo_suyo(self, monkeypatch):
        # CONTRAFACTUAL: su gguf NO declara general.sampling.* -> la familia
        # sigue siendo la unica fuente y nada cambia.
        self._meta_falsa(monkeypatch, {"arch": "qwen35"})
        cfg, fam = MP.familia_por_arch("cualquiera.gguf")
        assert fam == "qwythos"
        assert cfg["temperature"] == 0.7 and cfg["top_p"] == 0.8

    def test_solo_propaga_claves_de_sampling(self, monkeypatch):
        # Un gguf con basura en sampling no puede inyectar claves al cfg.
        self._meta_falsa(monkeypatch, {
            "arch": "qwen35",
            "sampling": {"temperature": 1.0, "top_k": 20, "inventado": 9},
        })
        cfg, _ = MP.familia_por_arch("x.gguf")
        assert cfg["temperature"] == 1.0
        assert "top_k" not in cfg and "inventado" not in cfg

    def test_arch_desconocida_sigue_devolviendo_nada(self, monkeypatch):
        self._meta_falsa(monkeypatch, {"arch": "arquitectura-marciana"})
        assert MP.familia_por_arch("x.gguf") == (None, "")


class TestComboDeModeloOrdenaPorLongitud:

    def test_el_ridge_cae_en_su_combo(self):
        assert FL.combo_de_modelo(_RIDGE) == "pensar-qwen38"
        assert "pensar-qwen38" in FL.COMBOS

    def test_los_de_siempre_no_se_mueven(self):
        # CONTRAFACTUAL completo de la tabla con los gguf de esta maquina.
        esperado = {
            "nemotron-3.5-lightning-30b-a3b-Q4_0.gguf": "pensar-nemotron",
            "OpenReasoning-Nemotron-14B.Q4_K_M.gguf": "pensar-en-lazo",
            "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf":
                "pensar-qwythos",
            "qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf":
                "construir",
            "gpt-oss-20b-MXFP4.gguf": "pensar",
            "UIGEN-X-8B.Q8_0.gguf": "construir-ui",
        }
        for nombre, combo in esperado.items():
            assert FL.combo_de_modelo(nombre) == combo, nombre

    def test_el_orden_de_escritura_deja_de_importar(self, monkeypatch):
        # El bug estructural: con las claves al reves, 'nemotron' (mas corta)
        # se llevaba al Nemotron 3.5 al combo del OpenReasoning-14B.
        al_reves = dict(reversed(list(FL.CEREBROS.items())))
        monkeypatch.setattr(FL, "CEREBROS", al_reves)
        assert FL.combo_de_modelo(
            "nemotron-3.5-lightning-30b-a3b-Q4_0.gguf") == "pensar-nemotron"
        assert FL.combo_de_modelo(_RIDGE) == "pensar-qwen38"

    def test_los_qwen3_chicos_no_son_cerebros_de_este_combo(self):
        for nombre in ("Qwen3-4B-Thinking-2507-Q4_K_M.gguf",
                       "Qwen3-1.7B-Q4_K_M.gguf"):
            assert FL.combo_de_modelo(nombre) != "pensar-qwen38", nombre


class TestPromptCompletoParaEl27B:

    def test_27b_recibe_el_prompt_completo(self, monkeypatch):
        # No-regresion de la regla generica (NNb >= 7): '27b' nunca estuvo en
        # ninguna lista literal y aun asi tiene que salir completo.
        monkeypatch.setenv("LLAMA_GGUF_PATH", _RIDGE)
        monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
        assert SP._perfil_auto() == "completo"

    def test_el_3_7bpw_del_nombre_no_lo_hace_chico(self, monkeypatch):
        # El nombre lleva '3.7bpw': el (?<![\d.]) del regex evita leerlo como
        # un '7b' (que daria completo por el motivo equivocado) — lo que
        # decide tiene que ser el 27b.
        monkeypatch.setenv("LLAMA_GGUF_PATH", "Modelito-3.7bpw.gguf")
        monkeypatch.delenv("COGNIA_SYSTEM_PROMPT_PERFIL", raising=False)
        assert SP._perfil_auto() == "compacto"


class TestArranqueConMTP:
    """MTP nativo: la cabeza vive DENTRO del gguf (qwen35.nextn_predict_layers
    = 1, blk.64 en Q6_K), asi que no hay draft externo que buscar."""

    def test_el_perfil_pide_mtp_con_n_max_2(self):
        perfil = SM.perfil_arranque(_RIDGE)
        # n=2 y no 4: el 4 gana 3% en codigo y PIERDE 20% en prosa (medido).
        assert perfil.get("spec_mtp") == 2

    def test_el_ctx_del_perfil_es_el_que_CABE(self):
        # 65.536 (13.657 MiB) y no 131.072 (15.961 de 16.311: 350 MiB de
        # margen) ni 262.144, que arranca, dice servir 262.144 y responde
        # PERO a 11 tok/s contra 31 — la RAM del sistema sirviendo el KV que
        # no cabe. "Arranca y responde" no es "cabe".
        assert SM.perfil_arranque(_RIDGE)["ctx"] == 65536

    def test_el_perfil_lleva_su_mmproj(self):
        # Es multimodal nativo; el proyector NO se carga salvo --vision.
        assert SM.perfil_arranque(_RIDGE)["mmproj"].startswith("mmproj-Qwen3.8")

    def test_el_comando_lleva_draft_mtp_y_no_draft_externo(self, monkeypatch):
        # Sin --spec-type el server IGNORA la cabeza MTP en silencio, igual que
        # ignora --spec-draft-model sin draft-simple.
        monkeypatch.setattr(sys, "argv", ["servir_modelo.py", "--modelo",
                                          "Ridge", "--listar"])
        perfil = SM.perfil_arranque(_RIDGE)
        cmd = SM.construir_cmd("exe", _RIDGE, 8080, perfil["ctx"],
                               ctk=perfil["ctk"], ctv=perfil["ctv"])
        assert "--cache-type-k" in cmd and "q8_0" in cmd
        # el arranque real agrega los flags de MTP tras el comando base
        assert "--spec-draft-model" not in cmd

    def test_nemotron_no_quedo_con_mtp(self):
        # CONTRAFACTUAL: el perfil de al lado no gana flags por vecindad.
        perfil = SM.perfil_arranque("nemotron-3.5-lightning-30b-a3b-Q4_0.gguf")
        assert not perfil.get("spec_mtp")
        assert perfil.get("sin_draft") is True

    def test_sin_perfil_no_hay_nada(self):
        assert SM.perfil_arranque(
            "qwen2.5-coder-14b-instruct-q4_k_m.gguf") == {}

class TestCabezaMTPSeLeeDelFichero:
    """La cabeza MTP se detecta LEYENDO el gguf (<arch>.nextn_predict_layers),
    no adivinando por el nombre. El coste de equivocarse es silencioso: el
    server acepta --spec-type draft-mtp sobre un modelo sin cabeza y sirve
    igual, sin acelerar y sin decir nada."""

    def _modelos(self):
        return Path.home() / ".cognia" / "models"

    def test_qwythos_declara_su_cabeza(self):
        # HALLAZGO 2026-08-18: el cerebro principal SIEMPRE tuvo cabeza MTP
        # (33 bloques = 32 + 1) y corre con ngram-mod (1.056x medido). O sea
        # que draft-mtp es una via sin explorar tambien para el, no solo para
        # el 27B nuevo.
        from cognia.agent.gguf_meta import meta
        ruta = (self._modelos()
                / "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf")
        if not ruta.is_file():
            import pytest
            pytest.skip("gguf no instalado en esta maquina")
        m = meta(str(ruta))
        assert m.get("mtp_capas") == 1
        assert m.get("bloques") == 33

    def test_un_modelo_sin_cabeza_no_la_inventa(self):
        # CONTRAFACTUAL: Nemotron 3.5 no declara nextn_predict_layers.
        from cognia.agent.gguf_meta import meta
        ruta = self._modelos() / "nemotron-3.5-lightning-30b-a3b-Q4_0.gguf"
        if not ruta.is_file():
            import pytest
            pytest.skip("gguf no instalado en esta maquina")
        assert meta(str(ruta)).get("mtp_capas") is None

    def test_el_ridge_declara_una_cabeza_de_65_bloques(self):
        from cognia.agent.gguf_meta import meta
        ruta = self._modelos() / _RIDGE
        if not ruta.is_file():
            import pytest
            pytest.skip("el Ridge todavia no esta descargado")
        m = meta(str(ruta))
        assert m.get("arch") == "qwen35"
        assert m.get("mtp_capas") == 1
        assert m.get("bloques") == 65
        assert m.get("n_ctx_train") == 262144
        assert m.get("sampling") == {"temperature": 1.0, "top_p": 0.95}
