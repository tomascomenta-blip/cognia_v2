# Flota multimodal de Cognia — setup de entornos (2026-08-09)

Rutas y flags para que la flota multimodal quede operativa tras un reinicio.
Todo opt-in: sin estos flags, el agente corre exactamente igual que antes.

## Cerebro y contexto
- Cerebro: `Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf` en :8080.
- Contexto MEDIDO en la RTX 5060 Ti 16 GB (escalera con sonda de aguja):
  - KV `q8_0` hasta **524.288** tokens (15,6 GB).
  - KV `q4_0` hasta **1.010.176** tokens (~1 M, sonda 16 s, 15,8 GB).
  - `COGNIA_CTX_MAX` default 1010176; `summoner.escalar_ctx(n)` relanza a celda medida.

## Summoner (VRAM cero en reposo)
- `cognia/summoner.py`: el cerebro summonea VLM/imagen/3D/voces/música bajo demanda
  y los libera por PID; jobs pesados evictan el cerebro y lo restauran.
- `python -m cognia.flota estado` muestra qué roles están vivos/dormidos.

## Tools multimodales (opt-in por familia)
| Familia | Flag | Backend | Pesos |
|---|---|---|---|
| voz_* | `COGNIA_VOZ_TOOLS=1` | Piper (TTS) + faster-whisper (STT) CPU, OpenVoice v2 (clonación) | `~/.cognia/models/openvoice_v2` |
| vlm_* | `COGNIA_VLM_TOOLS=1` | Qwen2.5-VL-7B en :8081 | en disco |
| imagen_* | `COGNIA_IMG_TOOLS=1` | SDXL + LayerDiffuse (worker matable :8096) | HF cache |
| musica_* | `COGNIA_MUSICA_TOOLS=1` | SymphonyGen (MIDI sinfónico) + fluidsynth | `~/.cognia/models/symphonygen` |
| tresd_* | `COGNIA_3D_TOOLS=1` | TripoSR (imagen→malla) | `~/.cognia/models/triposr` |

## Entornos por vendor (pins de transformers incompatibles con el venv312gpu 5.14)
- **SymphonyGen** (transformers 5.1.0): `COGNIA_SYMPHONYGEN_PY=<repo>/venv_sym/Scripts/python.exe`
  (torch 2.8 + transformers 5.1). VERIFICADO: genera `song_N.mid` (2 etapas) + WAV con fluidsynth.
- **TripoSR** (transformers 4.35.0): necesita su propio venv (pin distinto); pendiente crear
  `COGNIA_TRIPOSR_PY`. Sin él, el `tresd_generar` reprueba el ViT bajo transformers 5.14.
- **fluidsynth**: portable en `~/.cognia/vendors/fluidsynth/bin` (agregar al PATH) o
  `winget install FluidSynth.FluidSynth`. Soundfont: `~/.cognia/models/FluidR3_GM.sf2` (`COGNIA_SOUNDFONT`).

## Fine-tuning (LoRA propio) — veredicto
Ver `PREREG_LORA_QWYTHOS_20260809.md` (ENMIENDA 1) y `b4_loras/f2_smoke_qwythos_tools_v1.json`:
el pipeline (captura de trazas → dataset → trainer → gates) está COMPLETO y verificado, pero
Qwen3.5-9B multimodal híbrido NO entrena con QLoRA en 16 GB (pico ~29,5 GB). Captura de trazas
(`COGNIA_TRAZAS=1`) y dataset quedan operativos para cuando haya GPU ≥24 GB o se cambie el cerebro.
