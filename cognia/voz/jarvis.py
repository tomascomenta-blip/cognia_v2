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
import time

import numpy as np

from cognia.voz.sesion import SesionVoz
from cognia.voz.stt import TASA_WHISPER, Transcriptor
from cognia.voz.tts import Voz, voces_instaladas
from cognia.voz.wake import (CHUNK_MUESTRAS, TASA_MUESTREO, DetectorPalabra,
                             modelos_disponibles)

PALABRA_POR_DEFECTO = "hey_jarvis"
# Energia RMS por debajo de la cual se considera silencio.
#
# ESTE NUMERO NO SE ADIVINA, SE MIDE. La primera version lo dejo en 500 "a ojo"
# y fallo con un microfono real: el wake word disparaba, pero el grabador
# descartaba la voz entera como silencio porque ese Realtek entrega niveles muy
# por debajo de 500. Ahora se calibra contra el ambiente al arrancar
# (`calibrar_silencio`) y este valor queda solo como tope de seguridad para que
# un ambiente ruidoso no deje el umbral por las nubes.
SILENCIO_RMS = 500.0
SILENCIO_MINIMO = 15.0      # piso: por debajo, cualquier soplido seria "habla"
SILENCIO_SEG = 1.2          # cuanto silencio corta la frase
FRASE_MAXIMA_SEG = 15.0     # tope duro: nadie habla 15 s de corrido a un asistente


def _con_ganancia(datos, ganancia: float = 1.0) -> np.ndarray:
    """int16 crudo -> int16 amplificado, sin desbordar.

    Existe para microfonos cuyo nivel de entrada esta muy bajo en Windows: el
    navegador los hace funcionar porque aplica ganancia automatica, y la captura
    cruda entrega picos de ~40 sobre 32768 que ningun detector reconoce como
    voz. El arreglo de fondo es subir el nivel en Windows; esto es la red.
    """
    muestras = np.asarray(datos, dtype=np.int16).reshape(-1)
    if ganancia == 1.0:
        return muestras
    ampliado = muestras.astype(np.float32) * ganancia
    return np.clip(ampliado, -32768, 32767).astype(np.int16)


def calibrar_desde(flujo, segundos: float = 1.0, factor: float = 3.0,
                   tasa: int = TASA_MUESTREO) -> float:
    """Mide el ruido ambiente USANDO UN FLUJO YA ABIERTO y devuelve el umbral
    de "esto es voz".

    Recibe el flujo en vez de abrir el suyo por una razon medida: en Windows con
    el host MME, cerrar un stream de captura y abrir otro enseguida deja el
    segundo BLOQUEADO — el proceso quedaba vivo, con 0% de CPU, sin leer nada, y
    el asistente no detectaba mas la palabra de activacion. Las detecciones
    funcionaban antes de agregar la calibracion y dejaron de funcionar despues;
    eso fue lo que delato la causa. Un solo flujo para todo el proceso.

    El umbral queda `factor` veces por encima del ruido de fondo, acotado entre
    SILENCIO_MINIMO y SILENCIO_RMS. Existe porque un valor fijo no puede
    funcionar: cada microfono entrega niveles distintos segun su ganancia, y el
    500 puesto a ojo descartaba la voz del dueño como si fuera silencio.
    """
    try:
        muestras = []
        for _ in range(max(1, int(segundos * tasa / CHUNK_MUESTRAS))):
            datos, _o = flujo.read(CHUNK_MUESTRAS)
            muestras.append(np.asarray(datos, dtype=np.int16).reshape(-1))
        if not muestras:
            return SILENCIO_MINIMO
        fondo = np.concatenate(muestras).astype(np.float64)
        rms = float(np.sqrt(np.mean(fondo ** 2)))
        return float(min(max(rms * factor, SILENCIO_MINIMO), SILENCIO_RMS))
    except Exception:
        return SILENCIO_MINIMO


def grabar_frase_desde(flujo, tasa: int = TASA_MUESTREO,
                       umbral_rms: float = SILENCIO_RMS,
                       silencio_seg: float = SILENCIO_SEG,
                       maximo_seg: float = FRASE_MAXIMA_SEG,
                       ganancia: float = 1.0) -> np.ndarray:
    """Graba, DESDE UN FLUJO YA ABIERTO, hasta que el usuario deja de hablar.

    Corta por silencio sostenido y no por un tiempo fijo, porque un asistente
    que corta a los 5 segundos exactos interrumpe a la mitad de la frase. El
    tope maximo existe igual para que un ruido continuo no grabe para siempre.

    Igual que `calibrar_desde`, reutiliza el flujo en vez de abrir uno propio:
    en Windows/MME cerrar un stream de captura y abrir otro deja el segundo
    colgado sin leer nada (ver la nota en calibrar_desde).
    """
    trozos, silenciosos = [], 0
    trozos_de_silencio = int(silencio_seg * tasa / CHUNK_MUESTRAS)
    trozos_maximos = int(maximo_seg * tasa / CHUNK_MUESTRAS)
    hablo = False

    for _ in range(trozos_maximos):
        datos, _overflow = flujo.read(CHUNK_MUESTRAS)
        muestras = _con_ganancia(datos, ganancia)
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
    ap.add_argument("--umbral-silencio", type=float, default=None,
                    help="RMS que separa voz de silencio; por defecto se "
                         "CALIBRA contra el ruido ambiente al arrancar")
    ap.add_argument("--sin-voz", action="store_true")
    ap.add_argument("--ganancia", type=float, default=1.0, metavar="X",
                    help="multiplica el audio por X antes de procesarlo. Para "
                         "microfonos con el nivel de entrada muy bajo, donde el "
                         "navegador funciona porque aplica ganancia automatica "
                         "y la captura cruda no. Con picos de ~40 sobre 32768, "
                         "una ganancia de 100 los lleva a un nivel usable")
    ap.add_argument("--ver-puntaje", type=float, default=None, metavar="MIN",
                    help="imprime el puntaje del wake word cuando supera MIN "
                         "(ej: 0.05). Sirve para ver CUAN CERCA quedo de "
                         "activarse en vez de adivinar el umbral")
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
    umbral_silencio = args.umbral_silencio
    print("Ctrl+C para salir.")

    # Que se desenchufe el microfono no puede matar al asistente: es un fallo
    # transitorio, no un error de programa. Paso de verdad durante una prueba y
    # el proceso murio con un stacktrace de PortAudio. Ahora se reabre el flujo
    # y se sigue esperando, avisando una sola vez para no llenar la pantalla.
    fallos = 0
    while True:
      try:
        with sd.InputStream(samplerate=TASA_MUESTREO, blocksize=CHUNK_MUESTRAS,
                            dtype="int16", channels=1) as flujo:
            if fallos:
                print("[microfono de vuelta]\n", flush=True)
                fallos = 0
            if umbral_silencio is None:
                umbral_silencio = calibrar_desde(flujo)
                print("Ruido ambiente -> umbral de voz: %.0f" % umbral_silencio)
            print("\nCognia escuchando. Deci \"%s\" y despues hablale.\n"
                  % args.palabra.replace("_", " "), flush=True)
            while True:
                datos, _ = flujo.read(CHUNK_MUESTRAS)
                trozo = _con_ganancia(datos, args.ganancia)
                detectada = detector.detecto(trozo)
                if args.ver_puntaje is not None:
                    # Medir en vez de adivinar: muestra cuanto puntuo cada
                    # intento, para saber si falta bajar el umbral o si la
                    # palabra directamente no se esta reconociendo.
                    pico = max(detector.ultimos_puntajes.values(), default=0.0)
                    if pico >= args.ver_puntaje:
                        print("   [puntaje %.3f / umbral %.2f]" % (pico, args.umbral),
                              flush=True)
                if not detectada:
                    continue
                # NO se cierra el flujo: se graba del MISMO stream. Cerrarlo y
                # reabrirlo colgaba el proceso en Windows/MME (ver calibrar_desde).
                print("[te escucho]", flush=True)
                sesion.al_detectar_palabra(args.palabra)
                audio = grabar_frase_desde(flujo, umbral_rms=umbral_silencio,
                                           ganancia=args.ganancia)
                if audio.size == 0:
                    print("[no escuche nada — proba --umbral-silencio mas bajo "
                          "que %.0f]\n" % umbral_silencio, flush=True)
                    sesion.dormir()
                    continue
                turno = sesion.procesar_turno(audio)
                if turno.get("ok"):
                    print("  vos    :", turno["texto"], flush=True)
                    print("  cognia :", turno["respuesta"][:400], "\n", flush=True)
                else:
                    print("  (%s)\n" % turno.get("motivo"), flush=True)
      except KeyboardInterrupt:
        print("\nListo, me duermo.")
        break
      except Exception as exc:
        fallos += 1
        if fallos == 1:
            print("\n[sin microfono: %s]" % str(exc).split("\n")[0][:70])
            print("[reintentando cada 2 s; volve a enchufarlo cuando quieras]",
                  flush=True)
        sesion.dormir()
        time.sleep(2.0)

    try:
        pass
    finally:
        transcriptor.descargar()
        if voz is not None:
            voz.callar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
