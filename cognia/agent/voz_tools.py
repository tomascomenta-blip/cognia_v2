# -*- coding: utf-8 -*-
"""Tools de VOZ para el agente (opt-in COGNIA_VOZ_TOOLS=1).

POR QUE: cognia/voz tiene la boca (tts.Voz, Piper CPU) y el oido
(stt.Transcriptor, faster-whisper CPU) verificados, y el AGENTE no podia
alcanzarlos — el modo de fallo clasico del repo (capacidad construida,
probada y desconectada). voz_clonar suma OpenVoice v2 via subprocess. El
registro condicional en tools.py y las entradas en _OPTIN_PREFIJOS/_TIPADAS
los cablea el integrador de la ola 2.

Imports PEREZOSOS dentro de cada tool: registrar esto no arrastra piper ni
faster-whisper ni torch. La VRAM del rol 'voces' se negocia SOLO via
_backend_gate.pedir_backend (prohibido tocar cognia.flota desde una tool:
parar() decapita al propio cerebro). Toda degradacion es VISIBLE:
RESULTADO ... ERROR legible o nota en el OK — nunca excepcion al loop.

Reglas duras heredadas del diseno (medidas, no opinables):
  - voz_escuchar JAMAS expone device: DEVICE_SEGURO='cpu' del constructor
    de Transcriptor (con 'auto' y la GPU llena el proceso se CUELGA).
  - v1 es WAV-en-disco, sin microfono (trampa Windows/MME de reabrir
    streams; el microfono vive en `cognia voz`).
  - nombres de artefactos con hashlib.md5, nunca hash() (PYTHONHASHSEED).
"""
from __future__ import annotations

import hashlib
import re
import sys
import threading
from pathlib import Path

# VRAM que se le pide al summoner para el rol presupuesto 'voces'
# (registry del plan: 3000 MiB provisional; se re-mide post-carga).
_VRAM_MIB = 3000

_TIMEOUT_DECIR = 120.0      # watchdog sobre la reproduccion Piper
_TIMEOUT_ESCUCHAR = 300.0   # transcripcion whisper small CPU
_TIMEOUT_CLONAR = 600.0     # subprocess OpenVoice (CPU puede ser lento)


def _salida_voz(nombre: str) -> Path:
    """Deja los WAV junto al resto del trabajo del agente (<ws>/voz/)."""
    from cognia.agents.workers.dev_tools import _root_actual
    base = Path(_root_actual()) / "voz"
    base.mkdir(parents=True, exist_ok=True)
    return base / nombre


def _hay_modulo(nombre: str) -> bool:
    """El paquete esta instalado? Barato: find_spec, sin importar nada.

    POR QUE: piper/faster-whisper son el extra `cognia-ai[voz]`; sin el,
    el ERROR debe sugerir el pip install, no escupir un traceback.
    """
    import importlib.util
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


def _gate():
    """Import perezoso del punto unico tools<->summoner (agente A3, ola 1).

    POR QUE importlib y no `from ... import`: los tests inyectan un modulo
    falso en sys.modules y import_module lo respeta siempre; None si aun
    no existe (las olas corren en paralelo) — el llamador avisa por stderr.
    """
    import importlib
    try:
        return importlib.import_module("cognia.agent._backend_gate")
    except ImportError:
        return None


def register(tool):
    @tool("voz_decir",
          "voz_decir [guardar=<ruta.wav> |] <texto>  -- dice el texto con "
          "Piper (CPU); con guardar= escribe el WAV sin reproducir")
    def _voz_decir(args, ctx):
        crudo = (args or "").strip()
        if not crudo:
            return "RESULTADO voz_decir ERROR: falta el texto"
        # Opciones PRIMERO, texto (que puede contener '|') ULTIMO.
        guardar = ""
        partes = re.split(r"\s*\|\s*", crudo, maxsplit=1)
        m = re.match(r"^guardar\s*=\s*(\S+)$", partes[0].strip())
        if m:
            if len(partes) < 2 or not partes[1].strip():
                return ("RESULTADO voz_decir ERROR: falta el texto "
                        "(usa guardar=<ruta.wav> | <texto>)")
            guardar = m.group(1)
            texto = partes[1].strip()
        else:
            texto = crudo
        if not _hay_modulo("piper"):
            return ("RESULTADO voz_decir ERROR: piper no esta instalado "
                    "(pip install \"cognia-ai[voz]\")")
        try:
            from cognia.voz.tts import Voz
            voz = Voz()
            if guardar:
                destino = Path(guardar)
                if not destino.is_absolute():
                    destino = _salida_voz(guardar)
                destino.parent.mkdir(parents=True, exist_ok=True)
                ruta = voz.guardar_wav(texto, destino)
                if not ruta:
                    return ("RESULTADO voz_decir ERROR: la sintesis fallo "
                            "(voz Piper no descargada o texto invalido)")
                return f"RESULTADO voz_decir OK: {ruta}"
            # bloquear=True para que el paso del agente tenga fin
            # determinista; el watchdog corta con callar() si se cuelga.
            perro = threading.Timer(_TIMEOUT_DECIR, voz.callar)
            perro.daemon = True
            perro.start()
            try:
                ok = voz.decir(texto, bloquear=True)
            finally:
                perro.cancel()
            if not ok:
                return ("RESULTADO voz_decir ERROR: la sintesis fallo "
                        "(voz Piper no descargada o texto invalido)")
            return f"RESULTADO voz_decir OK: dicho ({len(texto)} chars)"
        except Exception as exc:
            return f"RESULTADO voz_decir ERROR: {exc}"

    @tool("voz_escuchar",
          "voz_escuchar <ruta.wav> [| idioma=es]  -- transcribe un WAV con "
          "faster-whisper (CPU)")
    def _voz_escuchar(args, ctx):
        partes = re.split(r"\s*\|\s*", (args or "").strip(), maxsplit=1)
        ruta = partes[0].strip()
        if not ruta:
            return ("RESULTADO voz_escuchar ERROR: falta la ruta del WAV "
                    "(usa <ruta.wav> [| idioma=es])")
        idioma = "es"
        if len(partes) == 2 and partes[1].strip():
            m = re.match(r"^idioma\s*=\s*([A-Za-z-]+)$", partes[1].strip())
            if not m:
                return ("RESULTADO voz_escuchar ERROR: opcion invalida "
                        f"{partes[1].strip()!r} (usa <ruta.wav> [| idioma=es])")
            idioma = m.group(1).lower()
        if not Path(ruta).is_file():
            return f"RESULTADO voz_escuchar ERROR: no existe {ruta}"
        if not _hay_modulo("faster_whisper"):
            return ("RESULTADO voz_escuchar ERROR: faster-whisper no esta "
                    "instalado (pip install \"cognia-ai[voz]\")")
        try:
            # PROHIBIDO exponer device: el constructor ya fuerza
            # DEVICE_SEGURO='cpu' (con 'auto' y la GPU llena se cuelga).
            from cognia.voz.stt import Transcriptor
            t = Transcriptor(idioma=idioma)
            try:
                resultado: dict = {}
                hilo = threading.Thread(
                    target=lambda: resultado.__setitem__("texto", t(ruta)),
                    daemon=True, name="cognia-voz-escuchar")
                hilo.start()
                hilo.join(timeout=_TIMEOUT_ESCUCHAR)
                if hilo.is_alive():
                    return ("RESULTADO voz_escuchar ERROR: timeout tras "
                            f"{_TIMEOUT_ESCUCHAR:.0f}s transcribiendo {ruta}")
                texto = (resultado.get("texto") or "").strip()
            finally:
                t.descargar()
            if not texto:
                return ("RESULTADO voz_escuchar ERROR: transcripcion vacia "
                        "(audio en silencio?)")
            return f"RESULTADO voz_escuchar OK: {texto}"
        except Exception as exc:
            return f"RESULTADO voz_escuchar ERROR: {exc}"

    @tool("voz_clonar",
          "voz_clonar <referencia.wav> | <texto>  -- sintetiza el texto con "
          "la voz del WAV de referencia (OpenVoice v2)")
    def _voz_clonar(args, ctx):
        partes = re.split(r"\s*\|\s*", (args or ""), maxsplit=1)
        if len(partes) != 2 or not partes[0].strip() or not partes[1].strip():
            return ("RESULTADO voz_clonar ERROR: formato "
                    "(usa <referencia.wav> | <texto>)")
        ref, texto = partes[0].strip(), partes[1].strip()
        if not Path(ref).is_file():
            return f"RESULTADO voz_clonar ERROR: no existe la referencia {ref}"

        # Gate barato ANTES de reservar VRAM: motivo legible si falta algo.
        try:
            from cognia.voz.clonar import clonar_disponible, clonar_voz
        except Exception as exc:
            return f"RESULTADO voz_clonar ERROR: backend clonar no importable: {exc}"
        ok, motivo = clonar_disponible()
        if not ok:
            return f"RESULTADO voz_clonar ERROR: {motivo}"

        # md5, nunca hash(): PYTHONHASHSEED lo hace inestable entre procesos.
        huella = hashlib.md5(f"{ref}|{texto}".encode("utf-8")).hexdigest()[:8]
        destino = _salida_voz(f"clon_{huella}.wav")

        # Reserva de VRAM via el punto unico tools<->summoner. Si el gate
        # niega por VRAM se degrada a CPU (funcional, mas lento) con nota
        # VISIBLE; ERROR solo por pesos/venv (ya chequeado arriba).
        gate = _gate()
        device = "cpu"
        nota = ""
        concedido = False
        if gate is None:
            print("[cognia] voz_clonar: _backend_gate no disponible, "
                  "sigo en CPU sin reserva de VRAM", file=sys.stderr)
            nota = " (CPU: sin _backend_gate)"
        else:
            okg, _url, motivog = gate.pedir_backend("voces", _VRAM_MIB)
            if okg:
                concedido = True
                device = "cuda"
            else:
                nota = f" (CPU: {motivog})"
        try:
            wav = clonar_voz(ref, texto, str(destino), device=device,
                             timeout=_TIMEOUT_CLONAR)
            return f"RESULTADO voz_clonar OK: {wav}{nota}"
        except Exception as exc:
            return f"RESULTADO voz_clonar ERROR: {exc}"
        finally:
            if concedido:
                try:
                    gate.soltar_backend("voces")
                except Exception as exc:
                    print(f"[cognia] voz_clonar: soltar_backend fallo: {exc}",
                          file=sys.stderr)
