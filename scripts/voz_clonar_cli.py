# -*- coding: utf-8 -*-
"""CLI de clonacion de voz OpenVoice v2 — corre EN venv312gpu (torch cu128).

Contrato (patron expert_forge/cli_train.py): stdout = UNA linea JSON
{"ok": true, "wav": ..., "seg": ...} o {"ok": false, "error": ...} con
exit != 0; TODO el progreso (incluidos los print de melo/openvoice) va a
stderr.

Flujo (demo oficial de OpenVoice v2):
  1. MeloTTS sintetiza el texto a un WAV base con la voz generica del
     idioma (espanol nativo: MeloTTS-Spanish, se auto-descarga de HF).
  2. se_extractor saca el embedding de timbre del WAV de referencia.
  3. ToneColorConverter convierte el WAV base al timbre de la referencia.

POR QUE la carga es perezosa (imports dentro de main): compilar/inspeccionar
este archivo no puede arrastrar torch, y el fallo de un import se reporta
por el contrato JSON, no como traceback pelado en stdout.

POR QUE se redirige sys.stdout a stderr durante la generacion: melo y
openvoice imprimen progreso a stdout y contaminarian el contrato JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Codigos de idioma de MeloTTS; el archivo ses/<clave>.pth de OpenVoice v2
# usa la clave del speaker en minusculas ('ES' -> es.pth, 'EN-US' -> en-us.pth).
_MELO_IDIOMAS = {
    "es": "ES", "en": "EN", "fr": "FR", "zh": "ZH",
    "ja": "JP", "jp": "JP", "ko": "KR", "kr": "KR",
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _fallo(stdout_real, motivo: str) -> int:
    """Imprime el JSON de fallo por el stdout REAL y devuelve exit != 0."""
    print(json.dumps({"ok": False, "error": motivo}, ensure_ascii=False),
          file=stdout_real, flush=True)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clonacion de voz OpenVoice v2 (MeloTTS + ToneColorConverter)")
    parser.add_argument("--referencia", required=True,
                        help="WAV con la voz a clonar (>= 6 s)")
    parser.add_argument("--texto", required=True, help="texto a sintetizar")
    parser.add_argument("--salida", required=True, help="ruta del WAV clonado")
    parser.add_argument("--idioma", default="es",
                        help="codigo de idioma (default es)")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"),
                        help="device para torch (default cpu)")
    args = parser.parse_args()

    t0 = time.monotonic()
    stdout_real = sys.stdout

    referencia = Path(args.referencia).resolve()
    salida = Path(args.salida).resolve()
    if not referencia.is_file():
        return _fallo(stdout_real, f"no existe el WAV de referencia {referencia}")
    lang = _MELO_IDIOMAS.get(args.idioma.strip().lower())
    if not lang:
        return _fallo(stdout_real,
                      f"idioma {args.idioma!r} no soportado "
                      f"(validos: {', '.join(sorted(_MELO_IDIOMAS))})")

    dir_ov = Path(os.environ.get(
        "COGNIA_OPENVOICE_DIR",
        str(Path.home() / ".cognia" / "models" / "openvoice_v2")))
    conv = dir_ov / "converter"
    if not (conv / "checkpoint.pth").is_file():
        return _fallo(stdout_real,
                      f"faltan los pesos OpenVoice v2 en {dir_ov} "
                      "(converter/checkpoint.pth; HF myshell-ai/OpenVoiceV2 "
                      "o fija COGNIA_OPENVOICE_DIR)")
    salida.parent.mkdir(parents=True, exist_ok=True)

    base_wav = ""
    # Progreso de los vendors a stderr para no romper el contrato JSON.
    sys.stdout = sys.stderr
    try:
        _log("[voz_clonar] cargando torch...")
        import torch

        device = args.device
        if device == "cuda" and not torch.cuda.is_available():
            # Degradacion VISIBLE, no silenciosa: se avisa y se sigue en CPU.
            _log("[voz_clonar] cuda pedido pero no disponible -> CPU")
            device = "cpu"

        _log("[voz_clonar] cargando ToneColorConverter...")
        from openvoice import se_extractor
        from openvoice.api import ToneColorConverter
        converter = ToneColorConverter(str(conv / "config.json"), device=device)
        converter.load_ckpt(str(conv / "checkpoint.pth"))

        _log("[voz_clonar] extrayendo timbre de la referencia...")
        tgt_se, _nombre = se_extractor.get_se(str(referencia), converter, vad=True)

        _log(f"[voz_clonar] sintetizando base con MeloTTS ({lang})...")
        from melo.api import TTS
        modelo = TTS(language=lang, device=device)
        spk2id = modelo.hps.data.spk2id
        clave = next(iter(spk2id))          # p.ej. 'ES'; EN trae variantes
        fd, base_wav = tempfile.mkstemp(suffix=".wav", prefix="ov_base_")
        os.close(fd)
        modelo.tts_to_file(args.texto, spk2id[clave], base_wav, speed=1.0)

        ses = dir_ov / "base_speakers" / "ses" / (
            clave.lower().replace("_", "-") + ".pth")
        if not ses.is_file():
            raise FileNotFoundError(
                f"falta el embedding base {ses} (base_speakers/ses/ de "
                "HF myshell-ai/OpenVoiceV2)")
        src_se = torch.load(str(ses), map_location=device)

        _log("[voz_clonar] convirtiendo timbre...")
        converter.convert(audio_src_path=base_wav, src_se=src_se,
                          tgt_se=tgt_se, output_path=str(salida),
                          message="@MyShell")
        seg = round(time.monotonic() - t0, 2)
    except Exception as exc:
        sys.stdout = stdout_real
        _log(traceback.format_exc())
        return _fallo(stdout_real, f"{type(exc).__name__}: {exc}")
    finally:
        sys.stdout = stdout_real
        if base_wav:
            try:
                os.unlink(base_wav)
            except OSError:
                pass

    if not salida.is_file():
        return _fallo(stdout_real,
                      f"la conversion termino sin error pero no escribio {salida}")
    print(json.dumps({"ok": True, "wav": str(salida), "seg": seg},
                     ensure_ascii=False), flush=True)
    _log(f"[voz_clonar] listo en {seg}s -> {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
