# -*- coding: utf-8 -*-
"""Tool VLM para el agente (ola 1 flota multimodal, 2026-08-09).

POR QUE: el VLM de :8081 existia y estaba probado, pero solo lo alcanzaba el
arbitro visual del program_creator — el modo de fallo clasico del repo
(capacidad construida y desconectada). Con vlm_mirar el loop ReAct puede MIRAR
una imagen (screenshot, PNG generado, foto) y razonar sobre lo que ve.

Opt-in: se registra solo con COGNIA_VLM_TOOLS=1 (cableado en tools.py, ola 2).
Roles: implementador E investigador (es de solo-lectura).

VRAM: la tool NO decide si el VLM cabe junto al cerebro; pide el backend via
el gate compartido (_backend_gate.pedir_backend('vlm', 3300)) y reporta el
motivo legible si no se puede. El gate puede no existir todavia (se construye
en paralelo en esta misma ola): el import es perezoso y tolerante, con
fallback directo al sondeo del arbitro (vlm_disponible/url_vlm) — degradacion
VISIBLE en el ERROR, jamas silenciosa.
"""
from __future__ import annotations

import re
from pathlib import Path

# Extensiones que _datauri_imagen sabe etiquetar con MIME correcto. Otras
# (gif, webp, bmp) se rechazan con ERROR legible en vez de mandarle al VLM
# bytes con MIME mentiroso.
_EXT_IMAGEN = (".png", ".jpg", ".jpeg")

# MiB que pide el gate para el rol vlm (VL-3B residente, plan congelado).
_VRAM_VLM_MIB = 3300


def _pedir_backend_vlm():
    """(ok, url, motivo) via el gate compartido; fallback local sin el.

    POR QUE el doble camino: _backend_gate es de otro agente de esta misma
    ola — este modulo tiene que funcionar antes, durante y despues de esa
    integracion. Sin gate, el sondeo barato del arbitro (health de :8081)
    responde lo mismo que respondera el fallback del gate para el rol vlm.
    """
    try:
        from cognia.agent._backend_gate import pedir_backend
        return pedir_backend("vlm", _VRAM_VLM_MIB)
    except ImportError:
        from cognia.program_creator.arbitro_visual import url_vlm, vlm_disponible
        ok, motivo = vlm_disponible()
        return ok, url_vlm(), ("" if ok else motivo)


def _soltar_backend_vlm() -> None:
    """Suelta el rol vlm (best-effort). Sin gate no hay reserva que soltar."""
    try:
        from cognia.agent._backend_gate import soltar_backend
        soltar_backend("vlm")
    except ImportError:
        pass    # sin summoner/gate el VLM no fue reservado por nosotros
    except Exception:
        pass    # soltar es best-effort: jamas rompe el resultado de la tool


def register(tool):
    @tool("vlm_mirar",
          "vlm_mirar <ruta_imagen> [| <pregunta>]  -- mira una imagen con el "
          "VLM y responde (descripcion si no hay pregunta)")
    def _vlm_mirar(args, ctx):
        # Formato legacy: ruta | pregunta. La pregunta es contenido libre
        # (puede contener '|') y va ULTIMA: maxsplit=1 la preserva entera.
        partes = re.split(r"\s*\|\s*", (args or "").strip(), maxsplit=1)
        ruta = partes[0].strip()
        pregunta = partes[1].strip() if len(partes) == 2 else ""
        if not ruta:
            return ("RESULTADO vlm_mirar ERROR: falta la ruta de la imagen "
                    "(usa: vlm_mirar <ruta> [| pregunta])")
        p = Path(ruta)
        if not p.is_file():
            return f"RESULTADO vlm_mirar ERROR: no existe {ruta}"
        if p.suffix.lower() not in _EXT_IMAGEN:
            return (f"RESULTADO vlm_mirar ERROR: extension "
                    f"'{p.suffix or '(ninguna)'}' no soportada "
                    f"(acepto {', '.join(_EXT_IMAGEN)})")

        concedido = False
        try:
            ok, url, motivo = _pedir_backend_vlm()
            if not ok:
                return ("RESULTADO vlm_mirar ERROR: "
                        f"{motivo or 'backend VLM no disponible'}")
            concedido = True
            # Import perezoso: registrar la tool no arrastra nada pesado.
            from cognia.program_creator.arbitro_visual import describir_imagen
            respuesta = describir_imagen(ruta, pregunta, url=(url or None))
            if not respuesta or not respuesta.strip():
                return ("RESULTADO vlm_mirar ERROR: el VLM no respondio en "
                        "180 s (¿:8081 vivo? prueba 'cognia flota estado')")
            return f"RESULTADO vlm_mirar OK: {respuesta.strip()}"
        except Exception as exc:
            return f"RESULTADO vlm_mirar ERROR: {exc}"
        finally:
            # Soltar SIEMPRE que el backend fue concedido, incluso si el VLM
            # o el POST reventaron: una reserva colgada bloquea la VRAM.
            if concedido:
                _soltar_backend_vlm()
