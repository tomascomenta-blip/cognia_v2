# -*- coding: utf-8 -*-
"""CLI de orquestacion SymphonyGen -- corre EN venv312gpu (torch 2.11+cu128).

Contrato (patron expert_forge/cli_train.py): stdout = UNA linea JSON
{"ok": true, "midis": [...], "seg": ...} o {"ok": false, "error": ...} con
exit != 0; TODO el progreso (incluidos los print del vendor) va a stderr.

POR QUE el parche torch.load vive AQUI y no en el vendor: arch/base_class.py
hace torch.load(model_path, map_location='cpu') sin weights_only y desde
torch 2.6 el default es weights_only=True -> UnpicklingError con los
checkpoints empaquetados (config+pesos picklean clases propias). La regla del
diseno es NO editar el vendor: se parchea la funcion antes de importar arch.
Los .pt son locales y confiables (descargados por el dueno) -- por eso
weights_only=False es aceptable.

Two-stage (README del vendor):
  sin --midi : etapa 1 (arch/harmo, stage_one_pretrained.pt) inventa el
               esqueleto armonico -> etapa 2 SIN analyze_harmo (ya es esqueleto).
  con --midi : etapa 2 directa CON analyze_harmo=True (analiza la armonia
               de la pieza del usuario).
  register_decay=1: el README lo pide para la variante reinforced+track.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Orquestacion SymphonyGen (two-stage)")
    parser.add_argument("--salida", required=True, help="directorio de salida de los .mid")
    parser.add_argument("--grupo", type=int, default=2,
                        help="variaciones por condicion (group_size)")
    parser.add_argument("--midi", default="",
                        help="MIDI de condicion armonica (opcional; sin el, etapa 1)")
    parser.add_argument("--checkpoint", default="grpo_clamp+track_epoch_6.pt",
                        help="checkpoint de etapa 2 en el dir de pesos")
    args = parser.parse_args()

    t0 = time.monotonic()

    vendor = Path(os.environ.get(
        "COGNIA_SYMPHONYGEN_SRC",
        str(Path.home() / ".cognia" / "vendors" / "symphonygen")))
    pesos = Path(os.environ.get(
        "COGNIA_SYMPHONYGEN_PESOS",
        str(Path.home() / ".cognia" / "models" / "symphonygen")))
    # arch/config.py lee estos DOS al importar (y crea WORK_DIR/tmp); si el
    # padre (symphony_backend.orquestar) ya los fijo, se respetan.
    os.environ.setdefault("ASSET_DIR", str(pesos))
    os.environ.setdefault("WORK_DIR",
                          str(Path.home() / ".cognia" / "data" / "symphonygen_work"))
    Path(os.environ["WORK_DIR"]).mkdir(parents=True, exist_ok=True)

    # Rutas absolutas ANTES del chdir al vendor (que asume rutas relativas).
    salida = Path(args.salida).resolve()
    salida.mkdir(parents=True, exist_ok=True)
    midi_cond = Path(args.midi).resolve() if args.midi else None
    if midi_cond and not midi_cond.is_file():
        print(json.dumps({"ok": False, "error": f"no existe el MIDI {midi_cond}"},
                         ensure_ascii=False))
        return 1

    sys.path.insert(0, str(vendor))
    os.chdir(vendor)

    # El vendor imprime "Saved generated song..." a stdout y contaminaria el
    # contrato JSON: TODO stdout de la generacion se desvia a stderr.
    stdout_real = sys.stdout
    sys.stdout = sys.stderr
    try:
        import torch
        _load_original = torch.load

        def _load_confiado(*a, **k):
            k.setdefault("weights_only", False)
            return _load_original(*a, **k)

        torch.load = _load_confiado

        # transformers>=5.2 renombro input_embeds->inputs_embeds y elimino
        # cache_position de create_causal_mask; el vendor (probado en 5.0/5.1)
        # llama con los nombres viejos y revienta con TypeError en 5.14. Misma
        # regla que torch.load: NO se edita el vendor, se adapta la funcion
        # ANTES de importar arch (event_decoder la importa al cargar el modulo).
        import inspect
        from transformers import masking_utils as _mask_mod
        _mask_original = _mask_mod.create_causal_mask
        _mask_params = set(inspect.signature(_mask_original).parameters)

        def _mask_adaptado(*a, **k):
            if "input_embeds" in k and "input_embeds" not in _mask_params:
                k["inputs_embeds"] = k.pop("input_embeds")
            k = {n: v for n, v in k.items() if n in _mask_params}
            return _mask_original(*a, **k)

        _mask_mod.create_causal_mask = _mask_adaptado

        if midi_cond is not None:
            cond = midi_cond
            analyze = True
        else:
            # Etapa 1: esqueleto armonico con el modelo 1D.
            from arch.harmo import generator as harmo_gen
            tmp = Path(tempfile.mkdtemp(prefix="harmo_", dir=os.environ["WORK_DIR"]))
            print(f"[etapa 1] generando esqueleto armonico en {tmp}", file=sys.stderr)
            harmo_gen.main(
                model_path=str(pesos / "stage_one_pretrained.pt"),
                num_batches=1, batch_size=1, save_dir=str(tmp))
            esqueletos = sorted(tmp.glob("*.mid"))
            if not esqueletos:
                raise RuntimeError(f"la etapa 1 no escribio ningun .mid en {tmp}")
            cond = esqueletos[0]
            analyze = False

        # Etapa 2: orquestacion 3D condicionada. Guarda en
        # <salida>/cond_<stem>/song_<g>.mid (save_gen del vendor).
        from arch.symph import generator as symph_gen
        print(f"[etapa 2] orquestando {cond.name} x{args.grupo} con {args.checkpoint}",
              file=sys.stderr)
        symph_gen.main(
            model_path=str(pesos / args.checkpoint),
            cond_midi_path_or_dir=[str(cond)],
            analyze_harmo=analyze,
            group_size=args.grupo,
            save_dir=str(salida),
            register_decay=1,
        )
        midis = sorted(str(p) for p in salida.rglob("song_*.mid"))
        if not midis:
            raise RuntimeError(f"la etapa 2 no escribio ningun song_*.mid en {salida}")
    except Exception:
        sys.stdout = stdout_real
        print(json.dumps({"ok": False, "error": traceback.format_exc()[-2000:]},
                         ensure_ascii=False))
        return 1
    finally:
        sys.stdout = stdout_real

    print(json.dumps({"ok": True, "midis": midis,
                      "seg": round(time.monotonic() - t0, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
