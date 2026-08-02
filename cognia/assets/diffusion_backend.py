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
        return False, ("sin CUDA/GPU (el backend de imagen es GPU-only; "
                       "usa venv312gpu, que trae torch con CUDA)")
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


def _recortar_alfa(img, margen: int = 8):
    """Recorta la imagen RGBA al bounding-box de su canal alfa (+ margen). Deja
    el asset ajustado (sin el gran borde transparente) -> listo para juego/web."""
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return img
    l, t, r, b = bbox
    w, h = img.size
    return img.crop((max(0, l - margen), max(0, t - margen),
                     min(w, r + margen), min(h, b + margen)))


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


def frac_transparente(img) -> float:
    """Fracción de píxeles casi-transparentes (alfa<16). Métrica de 'qué tan
    limpio quedó el fondo' — LayerDiffuse no siempre lo deja transparente."""
    import numpy as np
    a = np.asarray(img.split()[-1])
    return float((a < 16).mean())


_METODOS = ("auto", "layerdiffuse", "birefnet")


def _debe_rescatar(metodo: str, spec, frac: float, min_transp: float) -> bool:
    """Router de transparencia: decide si, tras generar con LayerDiffuse, hay que
    recortar con BiRefNet (fallback universal). Lógica pura -> testeable sin GPU.

    - metodo='birefnet': siempre recorta con BiRefNet (fuerza la vía + recorte).
    - metodo='layerdiffuse': nunca (transparencia nativa pura).
    - metodo='auto':
        * estilo incompatible con LayerDiffuse (transparencia_nativa=False,
          p.ej. Pony/NoobAI/Illustrious que dejan fondo sólido, issue #124) -> sí.
        * si el gate está activo (min_transp>0) y LayerDiffuse no lo alcanzó
          (fondo aún opaco) -> sí (rescate del gate).
        * si no -> no (LayerDiffuse nativo basta)."""
    if metodo == "birefnet":
        return True
    if metodo == "layerdiffuse":
        return False
    # auto:
    if spec is not None and not spec.get("transparencia_nativa", True):
        return True
    if min_transp > 0 and frac < min_transp:
        return True
    return False


def generar_transparente(prompt: str, *, estilo: str = None, negative: str = "",
                         seed: int = 12345, pasos: int = 25,
                         ancho: int = 1024, alto: int = 1024,
                         asset: bool = True, recortar: bool = False,
                         min_transp: float = 0.0, reintentos: int = 2,
                         metodo: str = "auto", salida: str = None) -> str:
    """Genera un PNG RGBA transparente y devuelve su ruta.

    prompt: descripción del objeto. Si `asset` (default), se añade un sufijo que
            favorece un objeto aislado (mejor transparencia y reuso como asset).
    estilo: None (SDXL base), 'pixel', 'pvz', ... (aplica LoRA + trigger + post).
    recortar: si True, recorta al bounding-box del alfa (asset ajustado, game-ready).
    min_transp: gate de calidad de transparencia (0=off). Si el fondo no queda lo
            bastante transparente (LayerDiffuse tiene variancia por seed), reintenta
            con otras seeds hasta `reintentos` y se queda con el MEJOR alfa.
    metodo: router de transparencia — 'auto' (LayerDiffuse nativo, con rescate
            BiRefNet si el estilo es incompatible o el gate no se alcanza),
            'layerdiffuse' (nativo puro, sin BiRefNet) o 'birefnet' (siempre recorta
            con BiRefNet tras generar; para full-body o finetunes incompatibles).
    ancho/alto: múltiplos de 64 (requisito del decoder RGBA). Se ajustan si no.
    salida: ruta de PNG; por defecto ~/.cognia/assets/<hash>.png."""
    if metodo not in _METODOS:
        raise AssetsError(f"metodo invalido: {metodo!r} (validos: {list(_METODOS)})")
    ancho = _ajustar_dim(ancho)
    alto = _ajustar_dim(alto)

    pipe = _cargar_pipeline()
    spec = _aplicar_estilo(pipe, estilo)
    trigger = spec["trigger"] if spec else ""
    p = _componer_prompt(prompt, asset, trigger)

    import numpy as np
    import torch
    intentos = 1 + max(0, int(reintentos)) if min_transp > 0 else 1
    # El sujeto debe OCUPAR algo: sin este piso, el gate premiaría imágenes casi
    # vacías (muy transparentes) donde el objeto salió diminuto/fragmentado.
    OPACO_MIN = 0.10
    mejor_img, mejor_score = None, -1.0
    for i in range(intentos):
        gen = torch.Generator(device="cuda").manual_seed(int(seed) + i)
        imgs = pipe(prompt=p, negative_prompt=negative, generator=gen,
                    num_inference_steps=int(pasos), width=ancho, height=alto,
                    num_images_per_prompt=1, return_dict=False)[0]
        img = imgs[0]  # PIL RGBA
        a = np.asarray(img.split()[-1])
        transp = float((a < 16).mean())
        opaco = float((a > 240).mean())
        # Score: fondo limpio pero con sujeto presente. Penaliza sujeto ausente.
        score = transp if opaco >= OPACO_MIN else transp * 0.1
        if score > mejor_score:
            mejor_img, mejor_score = img, score
        if transp >= min_transp and opaco >= OPACO_MIN:  # limpio y con sujeto -> corta
            break
    img = mejor_img

    # Router de transparencia: si LayerDiffuse no basta (estilo incompatible o el
    # gate quedó corto) o se pidió BiRefNet explícito, recortar con BiRefNet.
    if _debe_rescatar(metodo, spec, frac_transparente(img), min_transp):
        from .matting import quitar_fondo
        img = quitar_fondo(img)  # PIL RGBA con el fondo segmentado por BiRefNet

    if spec and spec.get("downscale"):
        img = _pixelar(img, spec["downscale"])
    if recortar:
        img = _recortar_alfa(img)

    if salida is None:
        h = abs(hash((prompt, estilo, seed, pasos, ancho, alto))) % (10 ** 10)
        salida = str(_out_dir() / f"asset_{h}.png")
    img.save(salida)
    return salida


# ── Edicion (img2img): editar una imagen YA HECHA ───────────────────────────
# Pedido del dueno: "que el modelo de imagenes pueda editar imagenes ya hechas".
# txt2img crea desde cero; esto TOMA una imagen y la transforma segun un prompt,
# conservando la composicion (strength controla cuanto se aparta del original).
# Reusa los MISMOS componentes del pipeline transparente (VAE transparente + LoRA
# de atencion): el encoder de SDXL es estandar (codifica RGB) y el decoder
# transparente re-deriva el alfa a la salida -> la edicion sigue saliendo RGBA.

_PIPE_IMG2IMG = None  # cache del pipeline img2img (comparte componentes con _PIPE)


def _cargar_img2img():
    """Pipeline img2img que COMPARTE los componentes del txt2img (no recarga
    pesos ni VRAM): mismo UNet con la LoRA, mismo VAE transparente."""
    global _PIPE_IMG2IMG
    if _PIPE_IMG2IMG is not None:
        return _PIPE_IMG2IMG
    base = _cargar_pipeline()
    from diffusers import StableDiffusionXLImg2ImgPipeline
    pipe = StableDiffusionXLImg2ImgPipeline(**base.components)
    pipe.set_progress_bar_config(disable=True)
    # El VAE transparente (TransparentVAEDecoder) trae un latents_std/mean
    # malformado (escalar) que el prepare_latents de img2img intenta reshapear a
    # [1,4,1,1] y revienta ("shape invalid for input of size 1"). SDXL base no
    # usa esa normalizacion: con ambos en None, diffusers cae al camino correcto
    # (scaling_factor). Seguro tambien para txt2img, que no los lee.
    try:
        pipe.vae.config.latents_mean = None
        pipe.vae.config.latents_std = None
    except Exception:
        pass
    _PIPE_IMG2IMG = pipe
    return _PIPE_IMG2IMG


def editar_transparente(imagen, prompt: str, *, estilo: str = None,
                        negative: str = "", seed: int = 12345, pasos: int = 30,
                        strength: float = 0.6, asset: bool = True,
                        recortar: bool = False, metodo: str = "auto",
                        min_transp: float = 0.0, salida: str = None) -> str:
    """Edita una imagen EXISTENTE segun `prompt` (img2img SDXL + transparencia).

    imagen:   ruta a un PNG/JPG o un PIL.Image. Se lleva a RGB para codificar
              (el decoder transparente re-deriva el alfa a la salida).
    prompt:   como debe cambiar / quedar la imagen.
    strength: 0..1 — cuanto se aparta del original. 0.2 = retoque sutil,
              0.6 = cambio notable conservando la composicion, 0.9 = casi reinventa.
    estilo:   igual que en generar_transparente (aplica LoRA + trigger si hay).
    El resto de parametros se comportan como en generar_transparente.
    Devuelve la ruta del PNG RGBA editado."""
    if metodo not in _METODOS:
        raise AssetsError(f"metodo invalido: {metodo!r} (validos: {list(_METODOS)})")
    strength = max(0.0, min(1.0, float(strength)))

    from PIL import Image
    if isinstance(imagen, (str, Path)):
        src = Image.open(imagen)
    else:
        src = imagen
    # El encoder de SDXL codifica RGB. Una imagen con alfa se compone sobre
    # blanco para no meter basura en los canales de color al codificar.
    if src.mode in ("RGBA", "LA", "P"):
        rgba = src.convert("RGBA")
        fondo = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        fondo.alpha_composite(rgba)
        src = fondo.convert("RGB")
    else:
        src = src.convert("RGB")
    # Dimensiones al multiplo de 64 que exige el decoder RGBA.
    src = src.resize((_ajustar_dim(src.width), _ajustar_dim(src.height)))

    pipe = _cargar_img2img()
    spec = _aplicar_estilo(pipe, estilo)
    trigger = spec["trigger"] if spec else ""
    p = _componer_prompt(prompt, asset, trigger)

    import torch
    gen = torch.Generator(device="cuda").manual_seed(int(seed))
    imgs = pipe(prompt=p, image=src, strength=strength, negative_prompt=negative,
                generator=gen, num_inference_steps=int(pasos),
                num_images_per_prompt=1, return_dict=False)[0]
    img = imgs[0]  # PIL RGBA (decoder transparente)

    if _debe_rescatar(metodo, spec, frac_transparente(img), min_transp):
        from .matting import quitar_fondo
        img = quitar_fondo(img)
    if spec and spec.get("downscale"):
        img = _pixelar(img, spec["downscale"])
    if recortar:
        img = _recortar_alfa(img)

    if salida is None:
        h = abs(hash((prompt, estilo, seed, pasos, strength))) % (10 ** 10)
        salida = str(_out_dir() / f"editado_{h}.png")
    img.save(salida)
    return salida
