# -*- coding: utf-8 -*-
"""El bucle "responder o investigar" (cognia/search/responder.py).

Todo inyectado: sin red y sin GPU. Lo que se protege es la POLÍTICA, que es
lo que se puede romper sin darse cuenta:
  - una respuesta de memoria nunca sale como buena, por segura que suene;
  - una cita inventada baja la confianza en vez de subirla;
  - no encontrar la respuesta se dice, no se rellena con lo que se recuerda.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognia.search import responder as R

PAGINA = ("Manual del equipo QX-042.\n"
          "El codigo de calibracion del equipo QX-042 es 7fa31b90 y "
          "solo aparece en este informe.\n" + ("relleno. " * 200))


def _chat_falso(respuestas):
    """Devuelve las respuestas JSON en orden; registra los prompts vistos."""
    vistos = []
    it = iter(respuestas)

    def _chat(mensajes, **kw):
        vistos.append(mensajes[-1]["content"])
        return json.dumps(next(it), ensure_ascii=False)

    _chat.vistos = vistos
    return _chat


def _buscador(_consulta, _n=8):
    return [{"url": "https://docs.ejemplo.org/qx042", "titulo": "t",
             "resumen": ""}]


def _extractor(urls, cap=5):
    from cognia.search.fanout import en_paralelo
    return en_paralelo(list(urls),
                       lambda u: {"texto": PAGINA, "titulo": "QX-042"}, cap=1)


class TestPoliticaDeRespuesta:

    def test_la_memoria_sola_nunca_alcanza_manda_a_investigar(self):
        """Aunque el modelo diga que lo sabe: sin fuente es memoria."""
        chat = _chat_falso([
            {"respuesta": "7fa31b90", "lo_se": True},          # a libro cerrado
            {"consultas": ["codigo calibracion QX-042"]},      # reformulación
            {"respuesta": "7fa31b90", "encontrado": True,
             "fuente": "https://docs.ejemplo.org/qx042",
             "evidencia": "El codigo de calibracion del equipo QX-042 es 7fa31b90"},
        ])
        v = R.responder("¿codigo de QX-042?", chat_fn=chat,
                        buscar_fn=_buscador, extraer_fn=_extractor)
        # Fue a buscar pese al lo_se=True, y ahora sí tiene con qué respaldar.
        assert len(chat.vistos) == 3
        assert v.accion == "responder" and v.valor == "7fa31b90"
        assert any("verificada" in r for r in v.razones)

    def test_una_cita_inventada_no_sube_la_confianza(self):
        chat = _chat_falso([
            {"respuesta": "?", "lo_se": False},
            {"consultas": ["qx042"]},
            {"respuesta": "deadbeef", "encontrado": True,
             "fuente": "https://docs.ejemplo.org/qx042",
             "evidencia": "El codigo de calibracion del equipo QX-042 es deadbeef"},
        ])
        v = R.responder("¿codigo de QX-042?", chat_fn=chat,
                        buscar_fn=_buscador, extraer_fn=_extractor)
        assert v.razones[0].startswith("CITA NO VERIFICADA")
        assert v.confianza <= 0.5 and v.accion != "responder"

    def test_si_no_esta_en_las_fuentes_se_dice(self):
        chat = _chat_falso([
            {"respuesta": "no sé", "lo_se": False},
            {"consultas": ["qx999"]},
            {"respuesta": "", "encontrado": False, "fuente": "",
             "evidencia": ""},
        ])
        v = R.responder("¿codigo de QX-999?", chat_fn=chat,
                        buscar_fn=_buscador, extraer_fn=_extractor)
        assert v.accion in ("investigar", "abstenerse")
        assert any("no estaba" in r for r in v.razones)

    def test_sin_urls_no_finge_haber_investigado(self):
        chat = _chat_falso([
            {"respuesta": "algo", "lo_se": False},
            {"consultas": ["nada"]},
        ])
        v = R.responder("¿?", chat_fn=chat,
                        buscar_fn=lambda *a, **k: [], extraer_fn=_extractor)
        assert any("no devolvió URLs" in r for r in v.razones)

    def test_el_buscador_caido_se_reporta_como_caida(self):
        """Un buscador que revienta NO puede leerse como 'no hay resultados'."""
        def _roto(*_a, **_k):
            raise ConnectionError("baneado")

        chat = _chat_falso([
            {"respuesta": "x", "lo_se": False},
            {"consultas": ["a", "b", "c"]},
        ])
        v = R.responder("¿?", chat_fn=chat, buscar_fn=_roto,
                        extraer_fn=_extractor)
        assert any("ConnectionError" in r for r in v.razones)
