# -*- coding: utf-8 -*-
"""Recorte universal de fondo (matting) con BiRefNet — fallback de transparencia.

LayerDiffuse produce RGBA nativo, pero SOLO sobre SDXL base / realistas suaves;
sobre finetunes desviados (Pony/NoobAI/Illustrious) rompe y deja fondo SÓLIDO
(issue #124), y tampoco cubre bien personajes de cuerpo entero. Para esos casos
el plan (PLAN_ASSETS_IA.md, subsistema A) manda: generar sobre fondo neutro +
recortar con BiRefNet, el segmentador de foreground SOTA y ABIERTO.

Modelo: `ZhengPeng7/BiRefNet` (MIT — apto comercial, a diferencia de RMBG-2.0 que
es no-comercial). Devuelve una máscara de foreground que se pega como canal alfa.

Diseño (igual que diffusion_backend):
- Imports de torch/transformers/torchvision PEREZOSOS: importar este módulo en un
  nodo CPU no carga nada pesado.
- Modelo cacheado (se carga una vez). ~1GB, ~1-2GB VRAM en inferencia.
- GPU obligatoria (coherente con el subsistema de imagen). Sin CUDA -> AssetsError.
- Kill-switch heredado: COGNIA_ASSETS=0 desactiva todo el subsistema.

Env de configuración:
  COGNIA_BIREFNET_MODEL  id/ruta del modelo BiRefNet (default ZhengPeng7/BiRefNet)
"""
from __future__ import annotations

import os

from .diffusion_backend import AssetsError, _out_dir

_BIREFNET_REPO = "ZhengPeng7/BiRefNet"
_MODEL = None  # cache del modelo cargado
# Normalización ImageNet (la que BiRefNet espera) y tamaño de entrada canónico.
_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]
_INPUT_SIZE = 1024


def _cargar_birefnet():
    """Carga (una vez) BiRefNet en GPU, fp16, eval. Reusa el chequeo de
    prerequisitos del backend de difusión (torch + CUDA + kill-switch)."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if os.environ.get("COGNIA_ASSETS", "1") == "0":
        raise AssetsError("backend de assets desactivado por COGNIA_ASSETS=0")
    try:
        import torch
    except Exception as e:  # pragma: no cover - depende del entorno
        raise AssetsError("torch no instalado (usa venv312gpu)") from e
    if not torch.cuda.is_available():
        raise AssetsError("sin CUDA/GPU (BiRefNet corre en GPU en este subsistema)")

    from transformers import AutoModelForImageSegmentation

    repo = os.environ.get("COGNIA_BIREFNET_MODEL", _BIREFNET_REPO)
    modelo = AutoModelForImageSegmentation.from_pretrained(
        repo, trust_remote_code=True)
    modelo.to("cuda").eval().half()
    _MODEL = modelo
    return _MODEL


def _mascara_foreground(img_rgb):
    """Corre BiRefNet sobre una PIL RGB y devuelve la máscara de foreground
    (PIL 'L' del tamaño original: 255=objeto, 0=fondo)."""
    import torch
    from torchvision import transforms

    modelo = _cargar_birefnet()
    tf = transforms.Compose([
        transforms.Resize((_INPUT_SIZE, _INPUT_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(_IMAGENET_MEAN, _IMAGENET_STD),
    ])
    x = tf(img_rgb).unsqueeze(0).to("cuda").half()
    with torch.no_grad():
        pred = modelo(x)[-1].sigmoid().cpu()[0].squeeze()
    mask = transforms.ToPILImage()(pred)
    return mask.resize(img_rgb.size)


def _combinar_alfa(mask, alfa_actual):
    """Combina la máscara de BiRefNet con el alfa ya presente en la imagen: usa
    la máscara donde el alfa original era >0, y fuerza 0 donde ya era transparente.
    Así BiRefNet nunca 'resucita' píxeles que LayerDiffuse ya dejó transparentes.
    Puro PIL (testeable sin GPU)."""
    from PIL import Image
    presente = alfa_actual.point(lambda a: 255 if a > 0 else 0)
    return Image.composite(mask, Image.new("L", mask.size, 0), presente)


def quitar_fondo(entrada, *, salida: str = None, aplicar_alfa: bool = True):
    """Quita el fondo de una imagen con BiRefNet y devuelve un PNG RGBA.

    entrada: ruta a una imagen o una PIL.Image (RGB o RGBA; se aplana a RGB antes
             de segmentar — el fondo original se ignora, BiRefNet decide el sujeto).
    aplicar_alfa: si True (default) la máscara se multiplica con cualquier alfa ya
             presente (no "resucita" píxeles que ya eran transparentes).
    salida: ruta de PNG; None -> devuelve la PIL.Image RGBA (sin escribir a disco).

    Devuelve la ruta (si `salida`) o la PIL.Image RGBA.
    """
    from PIL import Image

    if isinstance(entrada, (str, os.PathLike)):
        img = Image.open(entrada)
    else:
        img = entrada
    img = img.convert("RGBA")

    mask = _mascara_foreground(img.convert("RGB"))
    if aplicar_alfa:
        mask = _combinar_alfa(mask, img.split()[-1])
    out = img.copy()
    out.putalpha(mask)

    if salida is None:
        return out
    out.save(salida)
    return salida


def birefnet_disponible() -> tuple:
    """(ok, motivo). No descarga el modelo: solo chequea prerequisitos baratos."""
    if os.environ.get("COGNIA_ASSETS", "1") == "0":
        return False, "desactivado por COGNIA_ASSETS=0"
    try:
        import torch  # noqa
    except Exception:
        return False, "torch no instalado (usa venv312gpu)"
    if not torch.cuda.is_available():
        return False, "sin CUDA/GPU (BiRefNet es GPU-only en este subsistema)"
    try:
        import transformers  # noqa
        import torchvision  # noqa
    except Exception:
        return False, "faltan transformers/torchvision (usa venv312gpu)"
    return True, "ok"
