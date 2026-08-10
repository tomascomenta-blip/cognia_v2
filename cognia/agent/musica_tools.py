# -*- coding: utf-8 -*-
"""Tool de MUSICA para el agente (SymphonyGen, opt-in COGNIA_MUSICA_TOOLS=1).

POR QUE: el vendor SymphonyGen + pesos ya estan en disco y sin esta tool el
agente no puede alcanzarlos -- el modo de fallo clasico del repo (capacidad
construida y desconectada). El registro condicional en tools.py y la entrada
en _OPTIN_PREFIJOS/_TIPADAS los cablea el integrador de la ola 2.

Imports PEREZOSOS dentro de la tool: registrar esto no arrastra nada pesado.
La VRAM se negocia SOLO via _backend_gate.pedir_backend('musica', 2500)
(prohibido tocar cognia.flota desde una tool: parar() decapita al cerebro).
Toda degradacion es VISIBLE: RESULTADO ... ERROR legible o nota de OK
parcial -- nunca excepcion al loop, nunca silencio.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

# VRAM que se le pide al summoner para el rol presupuesto 'musica'
# (registry del plan: 2500 MiB provisional, pesos ~500 MB c/u; se re-mide).
_VRAM_MIB = 2500


def _salida_en_workspace(ctx) -> Path:
    """Deja los MIDI/WAV junto al resto del trabajo del agente.

    POR QUE timestamp y no hash(): PYTHONHASHSEED hace a hash() inestable
    entre procesos; el patron del repo es hashlib o timestamp.
    """
    from cognia.agents.workers.dev_tools import _root_actual
    base = Path(_root_actual()) / "musica" / f"orq_{time.strftime('%Y%m%d-%H%M%S')}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _parsear_kv(args: str) -> tuple[dict, str]:
    """Parsea 'midi=x | grupo=2 | wav=1' (solo pares k=v, orden libre).

    Devuelve (opciones, error). error != '' si hay una parte que no es k=v
    o una clave desconocida -- degradacion visible, jamas adivinar.
    """
    opciones: dict = {}
    texto = (args or "").strip()
    if not texto:
        return opciones, ""
    for parte in re.split(r"\s*\|\s*", texto):
        if not parte:
            continue
        m = re.match(r"^(\w+)\s*=\s*(.+)$", parte.strip())
        if not m:
            return {}, (f"formato invalido {parte.strip()!r} "
                        "(usa midi=<ruta> | grupo=<n> | wav=1)")
        clave, valor = m.group(1).lower(), m.group(2).strip()
        if clave not in ("midi", "grupo", "wav"):
            return {}, (f"opcion desconocida {clave!r} "
                        "(validas: midi, grupo, wav)")
        opciones[clave] = valor
    return opciones, ""


def register(tool):
    @tool("musica_orquestar",
          "musica_orquestar [midi=<ruta>] [| grupo=<n>] [| wav=1]  -- compone y "
          "orquesta una sinfonia (SymphonyGen, GPU ~2GB); sin midi= inventa la "
          "armonia; con midi= orquesta sobre esa pieza; wav=1 renderiza audio")
    def _musica_orquestar(args, ctx):
        opciones, err = _parsear_kv(args)
        if err:
            return f"RESULTADO musica_orquestar ERROR: {err}"

        midi_cond = opciones.get("midi", "")
        if midi_cond and not Path(midi_cond).is_file():
            return f"RESULTADO musica_orquestar ERROR: no existe el MIDI {midi_cond}"
        try:
            grupo = int(opciones.get("grupo", "2"))
        except ValueError:
            return ("RESULTADO musica_orquestar ERROR: grupo debe ser un entero "
                    f"(recibi {opciones.get('grupo')!r})")
        if grupo < 1:
            return "RESULTADO musica_orquestar ERROR: grupo debe ser >= 1"
        quiere_wav = opciones.get("wav", "") == "1"

        # Gate barato ANTES de reservar VRAM: motivo legible si falta algo.
        try:
            from cognia.musica import musica_disponible, orquestar
        except Exception as exc:
            return f"RESULTADO musica_orquestar ERROR: backend musica no importable: {exc}"
        ok, motivo = musica_disponible()
        if not ok:
            return f"RESULTADO musica_orquestar ERROR: {motivo}"

        # Reserva de VRAM via el punto unico tools<->summoner (agente A3,
        # ola 1 en paralelo): import perezoso tolerante; si aun no existe se
        # sigue SIN reserva pero avisando por stderr -- jamas en silencio.
        # POR QUE importlib y no `from cognia.agent import _backend_gate`:
        # esa forma resuelve el ATRIBUTO del paquete (el modulo real si otro
        # test ya lo importo) e ignora el fake que los tests inyectan en
        # sys.modules — leak de orden cazado en la suite completa (ola 2).
        # import_module respeta sys.modules siempre (patron de voz_tools).
        import importlib
        gate = None
        pedido = False
        try:
            gate = importlib.import_module("cognia.agent._backend_gate")
        except ImportError:
            print("[cognia] musica_orquestar: _backend_gate no disponible, "
                  "sigo sin reserva de VRAM", file=sys.stderr)
        if gate is not None:
            ok, _url, motivo = gate.pedir_backend("musica", _VRAM_MIB)
            if not ok:
                return f"RESULTADO musica_orquestar ERROR: {motivo}"
            pedido = True

        try:
            destino = _salida_en_workspace(ctx)
            midis = orquestar(midi_cond or None, str(destino), grupo=grupo)

            wavs: list[str] = []
            nota = ""
            if quiere_wav:
                from cognia.musica.render import fluidsynth_disponible, midi_a_wav
                okf, motivof = fluidsynth_disponible()
                if not okf:
                    # OK parcial: los MIDI ya son el artefacto; el motivo va
                    # en la respuesta para que el agente no reintente a ciegas.
                    nota = f" (sin WAV: {motivof})"
                else:
                    fallas = []
                    for m in midis:
                        try:
                            wavs.append(midi_a_wav(m))
                        except Exception as exc:
                            fallas.append(f"{Path(m).name}: {exc}")
                    if fallas:
                        nota = " (render parcial: " + "; ".join(fallas)[:300] + ")"

            nombres = ", ".join(Path(m).name for m in midis[:6])
            if len(midis) > 6:
                nombres += ", ..."
            extra_wav = f" + {len(wavs)} WAV" if wavs else ""
            return (f"RESULTADO musica_orquestar OK: {len(midis)} MIDI en "
                    f"{destino} ({nombres}){extra_wav}{nota}")
        except Exception as exc:
            return f"RESULTADO musica_orquestar ERROR: {exc}"
        finally:
            if pedido:
                try:
                    gate.soltar_backend("musica")
                except Exception as exc:
                    print(f"[cognia] musica_orquestar: soltar_backend fallo: {exc}",
                          file=sys.stderr)
