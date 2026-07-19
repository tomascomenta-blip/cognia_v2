"""
cognia/voz/jarvis.py
====================
El punto de arranque: ata las siete piezas y deja a Cognia escuchando.

    .\\venv312\\Scripts\\python.exe -m cognia.voz.jarvis

    --palabra     que palabra despierta (default: hey_jarvis)
    --modelo-stt  tamaño de Whisper (default: small)
    --device-stt  cpu | cuda  (default: cpu, ver stt.py)
    --umbral      sensibilidad del wake word 0..1 (default: 0.5)
    --sin-voz     contesta por pantalla en vez de hablar
    --listar      muestra palabras y voces disponibles y sale

OJO CON "CEREBRO": todavia no existe. openWakeWord trae 6 modelos preentrenados
(alexa, hey_jarvis, hey_mycroft, hey_rhasspy, timer, weather) y entrenar uno
propio es el gate J1 del plan. Hasta entonces hay que decir **"hey jarvis"**.
Cuando el modelo de "cerebro" exista, se pasa con --palabra y nada mas cambia.

El flujo es el del plan (seccion 2.3): la palabra despierta, se graba hasta el
silencio, se transcribe, el texto entra al motor de Cognia POR LA MISMA PUERTA
que usa el CLI, y la respuesta se dice en voz. No hay un cerebro nuevo: se le
dan oidos y boca al que ya estaba.
"""

import argparse
import sys

import numpy as np

from cognia.voz.sesion import SesionVoz
from cognia.voz.stt import TASA_WHISPER, Transcriptor
from cognia.voz.tts import Voz, voces_instaladas
from cognia.voz.wake import (CHUNK_MUESTRAS, TASA_MUESTREO, DetectorPalabra,
                             modelos_disponibles)

PALABRA_POR_DEFECTO = "hey_jarvis"
# Energia RMS por debajo de la cual se considera silencio. Calibrado a ojo sobre
# int16; --umbral-silencio lo ajusta si el ambiente es ruidoso.
SILENCIO_RMS = 500.0
SILENCIO_SEG = 1.2          # cuanto silencio corta la frase
FRASE_MAXIMA_SEG = 15.0     # tope duro: nadie habla 15 s de corrido a un asistente


def grabar_frase(tasa: int = TASA_MUESTREO, umbral_rms: float = SILENCIO_RMS,
                 silencio_seg: float = SILENCIO_SEG,
                 maximo_seg: float = FRASE_MAXIMA_SEG,
                 dispositivo=None) -> np.ndarray:
    """Graba del microfono hasta que el usuario deja de hablar.

    Corta por silencio sostenido y no por un tiempo fijo, porque un asistente
    que corta a los 5 segundos exactos interrumpe a la mitad de la frase. El
    tope maximo existe igual para que un ruido continuo no grabe para siempre.
    """
    import sounddevice as sd

    trozos, silenciosos = [], 0
    trozos_de_silencio = int(silencio_seg * tasa / CHUNK_MUESTRAS)
    trozos_maximos = int(maximo_seg * tasa / CHUNK_MUESTRAS)
    hablo = False

    with sd.InputStream(samplerate=tasa, blocksize=CHUNK_MUESTRAS,
                        dtype="int16", channels=1, device=dispositivo) as flujo:
        for _ in range(trozos_maximos):
            datos, _overflow = flujo.read(CHUNK_MUESTRAS)
            muestras = np.asarray(datos, dtype=np.int16).reshape(-1)
            trozos.append(muestras)
            rms = float(np.sqrt(np.mean(muestras.astype(np.float64) ** 2)))
            if rms >= umbral_rms:
                hablo = True
                silenciosos = 0
            elif hablo:
                silenciosos += 1
                if silenciosos >= trozos_de_silencio:
                    break
    if not trozos:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(trozos).astype(np.float32) / 32768.0
    return audio if hablo else np.zeros(0, dtype=np.float32)


def _construir_cerebro():
    """El motor de Cognia, entrando por la misma puerta que usa el CLI."""
    from cognia.first_run import apply_config
    apply_config()
    from cognia.cognia import Cognia
    from respuestas_articuladas import responder_articulado
    ai = Cognia()
    return lambda texto: responder_articulado(ai, texto)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cognia escuchando (Jarvis)")
    ap.add_argument("--palabra", default=PALABRA_POR_DEFECTO)
    ap.add_argument("--modelo-stt", default="small")
    ap.add_argument("--device-stt", default="cpu", choices=("cpu", "cuda"))
    ap.add_argument("--umbral", type=float, default=0.5)
    ap.add_argument("--umbral-silencio", type=float, default=SILENCIO_RMS)
    ap.add_argument("--sin-voz", action="store_true")
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args(argv)

    if args.listar:
        print("palabras de activacion:", ", ".join(modelos_disponibles()) or "(ninguna)")
        print("voces instaladas      :", ", ".join(voces_instaladas()) or "(ninguna)")
        print("\n'cerebro' todavia no existe: hay que entrenarla (gate J1).")
        return 0

    disponibles = modelos_disponibles()
    if args.palabra not in disponibles:
        print("La palabra %r no esta disponible." % args.palabra)
        print("Hay: %s" % (", ".join(disponibles) or "(ninguna)"))
        return 1

    print("Cargando... (la primera vez tarda: Whisper y la voz se cargan una vez)")
    detector = DetectorPalabra(palabras=[args.palabra], umbral=args.umbral)
    transcriptor = Transcriptor(modelo=args.modelo_stt, device=args.device_stt)
    voz = None if args.sin_voz else Voz()
    if voz is not None:
        voz.sintetizar("listo")        # precarga: 1.2 s ahora, 45 ms despues
    sesion = SesionVoz(transcriptor=transcriptor,
                       cerebro=_construir_cerebro(), voz=voz)

    import sounddevice as sd
    print("\nCognia escuchando. Deci \"%s\" y despues hablale."
          % args.palabra.replace("_", " "))
    print("Ctrl+C para salir.\n")

    try:
        with sd.InputStream(samplerate=TASA_MUESTREO, blocksize=CHUNK_MUESTRAS,
                            dtype="int16", channels=1) as flujo:
            while True:
                datos, _ = flujo.read(CHUNK_MUESTRAS)
                trozo = np.asarray(datos, dtype=np.int16).reshape(-1)
                if not detector.detecto(trozo):
                    continue
                # Se cierra el flujo de escucha antes de grabar para no tener
                # dos streams peleando por el mismo microfono.
                flujo.stop()
                print("[te escucho]", flush=True)
                sesion.al_detectar_palabra(args.palabra)
                audio = grabar_frase(umbral_rms=args.umbral_silencio)
                if audio.size == 0:
                    print("[no escuche nada]\n")
                    sesion.dormir()
                    flujo.start()
                    continue
                turno = sesion.procesar_turno(audio)
                if turno.get("ok"):
                    print("  vos    :", turno["texto"])
                    print("  cognia :", turno["respuesta"][:400], "\n")
                else:
                    print("  (%s)\n" % turno.get("motivo"))
                flujo.start()
    except KeyboardInterrupt:
        print("\nListo, me duermo.")
    finally:
        transcriptor.descargar()
        if voz is not None:
            voz.callar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
