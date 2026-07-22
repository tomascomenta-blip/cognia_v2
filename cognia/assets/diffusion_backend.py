# -*- coding: utf-8 -*-
"""Backend de difusión para assets transparentes: SDXL + LayerDiffuse (GPU).

Genera PNG RGBA nativo (transparencia latente de LayerDiffuse, lllyasviel
arXiv 2402.17113), sin recortar fondo — mantiene semitransparencias reales
(vidrio, glow, pelo). Implementación diffusers de `rootonchair/diffuser_layerdiffuse`
(MIT); el paquete `layer_diffuse` (TransparentVAEDecoder) se toma del repo clonado
en `~/.cognia/layerdiffuse_src` (configurable por env).

Diseño:
- Imports de torch/diffusers PEREZOSOS (dentro de las funciones): importar este
  módulo en un nodo CPU no carga nada pesado.
- Pipeline cacheado (se carga una vez; ~SDXL base + VAE transparente + LoRA de
  atención). VRAM ~8-12GB -> holgado en 16GB.
- GPU obligatoria (decisión del dueño: imagen en GPU por ahora). Sin CUDA ->
  AssetsError con instrucción clara, nunca un fallo silencioso.
- Kill-switch: COGNIA_ASSETS=0 desactiva el backend.

Env de configuración:
  COGNIA_LAYERDIFFUSE_SRC  ruta al repo diffuser_layerdiffuse (default ~/.cognia/layerdiffuse_src)
  COGNIA_SDXL_MODEL        id/ruta del base SDXL (default stabilityai/stable-diffusion-xl-base-1.0)
  COGNIA_SDXL_VAE          VAE fp16-fix (default madebyollin/sdxl-vae-fp16-fix)
  COGNIA_ASSETS_OUT        dir de salida (default ~/.cognia/assets)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- constantes de pesos LayerDiffuse (verificadas 2026-07-22) ---
_ATTN_REPO = "rootonchair/diffuser_layerdiffuse"
_ATTN_NAME = "diffuser_layer_xl_transparent_attn.safetensors"
_DECODER_REPO = "LayerDiffusion/layerdiffusion-v1"
_DECODER_NAME = "vae_transparent_decoder.safetensors"

_PIPE = None  # cache del pipeline cargado


class AssetsError(RuntimeError):
    """Fallo del backend de assets (con mensaje accionable para el usuario)."""


def _src_layerdiffuse() -> Path:
    return Path(os.environ.get(
        "COGNIA_LAYERDIFFUSE_SRC",
        str(Path.home() / ".cognia" / "layerdiffuse_src")))


def _out_dir() -> Path:
    d = Path(os.environ.get("COGNIA_ASSETS_OUT",
                            str(Path.home() / ".cognia" / "assets")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def backend_disponible() -> tuple:
    """(ok, motivo). No carga modelos: solo chequea prerequisitos baratos."""
    if os.environ.get("COGNIA_ASSETS", "1") == "0":
        return False, "desactivado por COGNIA_ASSETS=0"
    try:
        import torch  # noqa
    except Exception:
        return False, "torch no instalado (usa venv312gpu)"
    if not torch.cuda.is_available():
        return False, "sin CUDA/GPU (el backend de imagen es GPU-only)"
    src = _src_layerdiffuse()
    if not (src / "layer_diffuse").is_dir():
        return False, (f"falta el paquete layer_diffuse en {src} "
                       f"(clona rootonchair/diffuser_layerdiffuse ahi)")
    return True, "ok"


def _cargar_pipeline():
    """Carga (una vez) SDXL + VAE transparente + LoRA de transparencia."""
    global _PIPE
    if _PIPE is not None:
        return _PIPE

    ok, motivo = backend_disponible()
    if not ok:
        raise AssetsError(f"backend de assets no disponible: {motivo}")

    # layer_diffuse vive en el repo clonado; lo añadimos al path.
    src = str(_src_layerdiffuse())
    if src not in sys.path:
        sys.path.insert(0, src)

    import torch
    from diffusers import StableDiffusionXLPipeline
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    from layer_diffuse.models import TransparentVAEDecoder

    modelo = os.environ.get("COGNIA_SDXL_MODEL",
                            "stabilityai/stable-diffusion-xl-base-1.0")
    vae_id = os.environ.get("COGNIA_SDXL_VAE", "madebyollin/sdxl-vae-fp16-fix")

    # VAE con decoder de transparencia (produce el canal alfa).
    vae = TransparentVAEDecoder.from_pretrained(vae_id, torch_dtype=torch.float16)
    vae.config.force_upcast = False
    decoder_path = hf_hub_download(repo_id=_DECODER_REPO, filename=_DECODER_NAME)
    vae.set_transparent_decoder(load_file(str(decoder_path)))

    pipe = StableDiffusionXLPipeline.from_pretrained(
        modelo, vae=vae, torch_dtype=torch.float16, variant="fp16",
        use_safetensors=True, add_watermarker=False,
    ).to("cuda")
    # LoRA de atención que mueve SDXL al espacio latente transparente. Se carga
    # como adapter con nombre para poder combinarla con un LoRA de estilo.
    pipe.load_lora_weights(_ATTN_REPO, weight_name=_ATTN_NAME,
                           adapter_name="transparent")
    pipe.set_adapters(["transparent"], [1.0])
    pipe.set_progress_bar_config(disable=True)

    _PIPE = pipe
    return _PIPE


def _loras_dir() -> Path:
    return Path(os.environ.get("COGNIA_LORAS_DIR",
                               str(Path.home() / ".cognia" / "loras")))


# Registro de estilos. `transparencia_nativa`: si el LoRA es compatible con
# LayerDiffuse (SDXL base / realistas suaves). Los finetunes desviados
# (Pony/NoobAI/Illustrious) rompen la transparencia nativa (issue #124) -> esos
# irían por la ruta generar+BiRefNet (pendiente F2b). `downscale`: para pixel art
# se reduce ×N con nearest-neighbor para pixel-perfect (técnica del autor).
_ESTILOS = {
    "pixel": {"archivo": "pixel-art-xl.safetensors", "trigger": "",
              "peso": 1.2, "transparencia_nativa": True, "downscale": 8},
    "pvz": {"archivo": "pvz_pvz.safetensors", "trigger": "pvz, cartoon",
            "peso": 0.9, "transparencia_nativa": True, "downscale": 0},
}
_ESTILOS_CARGADOS = set()


def estilos_disponibles() -> list:
    """Estilos cuyo LoRA está realmente en disco (usable)."""
    d = _loras_dir()
    return sorted(k for k, v in _ESTILOS.items()
                  if (d / v["archivo"]).exists())


def _aplicar_estilo(pipe, estilo):
    """Activa transparencia + (opcional) LoRA de estilo. estilo=None -> solo
    transparencia. Devuelve el dict del estilo (o None)."""
    if not estilo:
        pipe.set_adapters(["transparent"], [1.0])
        return None
    spec = _ESTILOS.get(estilo)
    if spec is None:
        raise AssetsError(f"estilo desconocido: {estilo!r} "
                          f"(validos: {sorted(_ESTILOS)})")
    ruta = _loras_dir() / spec["archivo"]
    if not ruta.exists():
        raise AssetsError(f"el LoRA del estilo '{estilo}' no esta en disco "
                          f"({ruta}); descargalo primero")
    if estilo not in _ESTILOS_CARGADOS:
        _cargar_lora_estilo(pipe, ruta, estilo)
        _ESTILOS_CARGADOS.add(estilo)
    pipe.set_adapters(["transparent", estilo], [1.0, spec["peso"]])
    return spec


def _cargar_lora_estilo(pipe, ruta, adapter_name):
    """Carga un LoRA de estilo tolerando el formato de Civitai/kohya.

    Muchos LoRAs de Civitai (kohya/SGM, claves `lora_unet_*` + `lora_te1/te2_*`)
    traen pesos de text-encoder cuyo formato rompe el loader de diffusers
    (get_peft_kwargs -> IndexError). Cuando los detectamos, cargamos SOLO las
    claves de UNet (`lora_unet_*`) — diffusers convierte el formato SGM y ahí vive
    la mayor parte del estilo. LoRAs limpios (solo-UNet, p.ej. pixel-art-xl) se
    cargan directo del fichero."""
    from safetensors.torch import load_file
    sd = load_file(str(ruta))
    if any(k.startswith("lora_te") for k in sd):
        sd = {k: v for k, v in sd.items() if k.startswith("lora_unet")}
        if not sd:
            raise AssetsError(f"LoRA '{adapter_name}' sin claves de UNet usables")
        pipe.load_lora_weights(sd, adapter_name=adapter_name)
    else:
        pipe.load_lora_weights(str(ruta), adapter_name=adapter_name)


# Sufijo de prompt que empuja al modelo a un asset aislado (mejor alfa + reuso).
_PROMPT_ASSET = (", isolated single object, centered, full object visible, "
                 "clean edges, game asset, high quality")


def _ajustar_dim(n: int) -> int:
    """El decoder RGBA de LayerDiffuse exige múltiplo de 64 (si no, falla)."""
    n = int(n) - (int(n) % 64)
    return max(64, n)


def _componer_prompt(prompt: str, asset: bool, trigger: str = "") -> str:
    """Prompt final: trigger del estilo (si hay) + prompt + sufijo de asset."""
    partes = []
    if trigger:
        partes.append(trigger)
    partes.append(prompt.strip())
    p = ", ".join(partes)
    return p + (_PROMPT_ASSET if asset else "")


def _pixelar(img, factor: int):
    """Downscale ×factor + upscale nearest -> pixel-perfect a tamaño original
    (técnica del autor de pixel-art-xl). Preserva alfa."""
    if factor and factor > 1:
        from PIL import Image
        w, h = img.size
        chico = img.resize((max(1, w // factor), max(1, h // factor)),
                           Image.NEAREST)
        return chico.resize((w, h), Image.NEAREST)
    return img


def generar_transparente(prompt: str, *, estilo: str = None, negative: str = "",
                         seed: int = 12345, pasos: int = 25,
                         ancho: int = 1024, alto: int = 1024,
                         asset: bool = True, salida: str = None) -> str:
    """Genera un PNG RGBA transparente y devuelve su ruta.

    prompt: descripción del objeto. Si `asset` (default), se añade un sufijo que
            favorece un objeto aislado (mejor transparencia y reuso como asset).
    estilo: None (SDXL base), 'pixel', 'pvz', ... (aplica LoRA + trigger + post).
    ancho/alto: múltiplos de 64 (requisito del decoder RGBA). Se ajustan si no.
    salida: ruta de PNG; por defecto ~/.cognia/assets/<hash>.png."""
    ancho = _ajustar_dim(ancho)
    alto = _ajustar_dim(alto)

    pipe = _cargar_pipeline()
    spec = _aplicar_estilo(pipe, estilo)
    trigger = spec["trigger"] if spec else ""
    p = _componer_prompt(prompt, asset, trigger)

    import torch
    gen = torch.Generator(device="cuda").manual_seed(int(seed))
    imgs = pipe(prompt=p, negative_prompt=negative, generator=gen,
                num_inference_steps=int(pasos), width=ancho, height=alto,
                num_images_per_prompt=1, return_dict=False)[0]
    img = imgs[0]  # PIL RGBA

    if spec and spec.get("downscale"):
        img = _pixelar(img, spec["downscale"])

    if salida is None:
        h = abs(hash((prompt, estilo, seed, pasos, ancho, alto))) % (10 ** 10)
        salida = str(_out_dir() / f"asset_{h}.png")
    img.save(salida)
    return salida
