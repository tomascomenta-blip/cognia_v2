# -*- coding: utf-8 -*-
"""Difusion ESPECULATIVA: draft barato -> verificar -> refinar solo si hace falta.

PEDIDO DEL DUENO (2026-07-24): "algo que seria como el speculative decoding pero
para los modelos de difusion". El analogo correcto NO es verificar tokens (en
difusion no hay distribucion token a token que preservar): es el patron
draft-verify-refine que la literatura de video ya usa (SDVG, 2026: un drafter
chico propone bloques en 4 pasos de denoising y un router de CALIDAD DE IMAGEN
decide). Aqui:

  1. DRAFT   — SDXL-Lightning LoRA (4/8 pasos, destilacion adversarial de
               ByteDance, arXiv 2402.13929) sobre el MISMO SDXL base ya cargado:
               k candidatos a ~15x la velocidad del base.
  2. VERIFY  — un juez puntua los candidatos contra el prompt. Si hay VLM vivo
               (COGNIA_VLM_URL), juzga el; si no, una heuristica barata de alfa
               (sujeto presente + fondo limpio, la misma del gate de
               generar_transparente).
  3. ACCEPT/ — si el mejor draft pasa el gate se entrega TAL CUAL (aceptacion
     REFINE    especulativa: pagaste 4 pasos, no 25). Si no pasa, el mejor draft
               se REFINA con el base via img2img a strength baja (la mancha de
               un draft es composicion valida; el base solo pule) — que sigue
               siendo mas barato que generar de cero.

Igual que el draft-verify del LLM (0.5B borra, 14B verifica): el barato propone,
el caro solo corrige. La diferencia honesta: aqui el "verificador" es un juez de
calidad, no una garantia de distribucion identica.

Lightning exige su sampler: EulerDiscrete con timestep_spacing="trailing" y
guidance bajo (cfg<=2). Se cambia el scheduler SOLO durante el draft y se
restaura el del base para el refine.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .diffusion_backend import (AssetsError, _aplicar_estilo, _ajustar_dim,
                                _cargar_img2img, _cargar_pipeline,
                                _componer_prompt, _loras_dir, _out_dir,
                                _pixelar, _recortar_alfa)

logger = logging.getLogger(__name__)

_LIGHTNING = {
    4: "sdxl_lightning_4step_lora.safetensors",
    8: "sdxl_lightning_8step_lora.safetensors",
}
_LIGHTNING_CARGADO = set()

# Gate de aceptacion del draft (0-10 si juzga el VLM; 0-1 la heuristica se
# escala x10). Por debajo se refina con el base. Override: COGNIA_SPEC_GATE.
GATE_DEFECTO = 6.5


def lightning_disponible(pasos: int = 4) -> bool:
    return (_loras_dir() / _LIGHTNING.get(pasos, "")).exists()


def _activar_lightning(pipe, pasos: int, estilo):
    """Compone lightning + transparencia (+ estilo) y pone el sampler que
    Lightning exige. Devuelve (scheduler_original, spec_estilo)."""
    ruta = _loras_dir() / _LIGHTNING[pasos]
    if not ruta.exists():
        raise AssetsError(f"falta el LoRA Lightning de {pasos} pasos ({ruta})")
    nombre = f"lightning{pasos}"
    if nombre not in _LIGHTNING_CARGADO:
        pipe.load_lora_weights(str(ruta), adapter_name=nombre)
        _LIGHTNING_CARGADO.add(nombre)

    spec = _aplicar_estilo(pipe, estilo)   # deja transparent (+ estilo)
    activos = ["transparent", nombre] + ([estilo] if estilo else [])
    pesos = [1.0, 1.0] + ([spec["peso"]] if spec else [])
    pipe.set_adapters(activos, pesos)

    from diffusers import EulerDiscreteScheduler
    original = pipe.scheduler
    pipe.scheduler = EulerDiscreteScheduler.from_config(
        pipe.scheduler.config, timestep_spacing="trailing")
    return original, spec


def _desactivar_lightning(pipe, scheduler_original, estilo):
    pipe.scheduler = scheduler_original
    _aplicar_estilo(pipe, estilo)          # vuelve a transparent (+ estilo)


def _puntuar_heuristica(img) -> float:
    """0-10 sin VLM: sujeto presente + fondo limpio (misma logica del gate de
    generar_transparente). Barata y siempre disponible."""
    import numpy as np
    a = np.asarray(img.split()[-1])
    transp = float((a < 16).mean())
    opaco = float((a > 240).mean())
    if opaco < 0.05:
        return 1.0                          # sujeto ausente: draft malo
    return round(10.0 * min(1.0, transp * 0.6 + min(opaco, 0.5) * 0.8), 2)


def _puntuar_vlm(ruta_png: str, prompt: str) -> float | None:
    """Nota 0-10 del VLM si hay uno vivo; None si no. Reusa el arbitro visual
    (modo sin mockup: juzga contra la intencion en texto)."""
    try:
        from cognia.program_creator.arbitro_visual import (arbitrar_visual,
                                                           vlm_disponible)
        ok, _ = vlm_disponible()
        if not ok:
            return None
        r = arbitrar_visual(f"una imagen de: {prompt}", ruta_png,
                            vision_texto=prompt)
        if r and r.get("nota") is not None:
            return float(r["nota"])
        return None
    except Exception:
        return None


def generar_especulativa(prompt: str, *, estilo: str = None, negative: str = "",
                         seed: int = 12345, pasos_draft: int = 4,
                         candidatos: int = 2, gate: float = None,
                         pasos_refine: int = 14, strength_refine: float = 0.35,
                         ancho: int = 1024, alto: int = 1024,
                         asset: bool = True, recortar: bool = False,
                         salida: str = None) -> dict:
    """Genera con draft especulativo. Devuelve dict con la ruta y la traza:
      {ruta, acepto_draft, nota_draft, notas, juez, s_draft, s_refine}

    candidatos: cuantos drafts proponer (cada uno cuesta `pasos_draft` pasos).
    gate: nota 0-10 para aceptar el draft tal cual (default COGNIA_SPEC_GATE
          o 6.5). Si ningun draft la alcanza, el MEJOR se refina con el base.
    """
    import time
    if pasos_draft not in _LIGHTNING:
        raise AssetsError(f"pasos_draft debe ser {sorted(_LIGHTNING)}")
    if gate is None:
        try:
            gate = float(os.environ.get("COGNIA_SPEC_GATE", GATE_DEFECTO))
        except (TypeError, ValueError):
            gate = GATE_DEFECTO
    ancho, alto = _ajustar_dim(ancho), _ajustar_dim(alto)

    pipe = _cargar_pipeline()
    scheduler_orig, spec = _activar_lightning(pipe, pasos_draft, estilo)
    trigger = spec["trigger"] if spec else ""
    p = _componer_prompt(prompt, asset, trigger)

    import torch
    t0 = time.time()
    borradores = []
    try:
        for i in range(max(1, int(candidatos))):
            gen = torch.Generator(device="cuda").manual_seed(int(seed) + i)
            # Lightning-LoRA: guidance bajo obligatorio (cfg alto lo quema).
            img = pipe(prompt=p, negative_prompt=negative, generator=gen,
                       num_inference_steps=int(pasos_draft),
                       guidance_scale=1.5, width=ancho, height=alto,
                       num_images_per_prompt=1, return_dict=False)[0][0]
            borradores.append(img)
    finally:
        _desactivar_lightning(pipe, scheduler_orig, estilo)
    s_draft = time.time() - t0

    # ── VERIFY: juez VLM si vive, heuristica si no ─────────────────────────
    import tempfile
    notas, juez = [], "heuristica"
    for i, img in enumerate(borradores):
        fd, tmp = tempfile.mkstemp(prefix=f"spec_draft{i}_", suffix=".png")
        os.close(fd)
        img.save(tmp)
        nota = _puntuar_vlm(tmp, prompt)
        if nota is not None:
            juez = "vlm"
        else:
            nota = _puntuar_heuristica(img)
        notas.append((nota, img, tmp))
    notas.sort(key=lambda t: t[0], reverse=True)
    mejor_nota, mejor_img, mejor_tmp = notas[0]

    # ── ACCEPT o REFINE ────────────────────────────────────────────────────
    acepto = mejor_nota >= gate
    s_refine = 0.0
    if not acepto:
        t1 = time.time()
        pipe2 = _cargar_img2img()
        _aplicar_estilo(pipe2, estilo)
        gen = torch.Generator(device="cuda").manual_seed(int(seed) + 777)
        mejor_img = pipe2(prompt=p, image=mejor_img.convert("RGB"),
                          strength=float(strength_refine),
                          negative_prompt=negative, generator=gen,
                          num_inference_steps=int(pasos_refine),
                          num_images_per_prompt=1, return_dict=False)[0][0]
        s_refine = time.time() - t1

    if spec and spec.get("downscale"):
        mejor_img = _pixelar(mejor_img, spec["downscale"])
    if recortar:
        mejor_img = _recortar_alfa(mejor_img)

    if salida is None:
        h = abs(hash((prompt, estilo, seed, pasos_draft))) % (10 ** 10)
        salida = str(_out_dir() / f"spec_{h}.png")
    mejor_img.save(salida)

    for _, _, tmp in notas:
        try:
            os.remove(tmp)
        except OSError:
            pass

    return {"ruta": salida, "acepto_draft": bool(acepto),
            "nota_draft": mejor_nota, "notas": [round(n, 2) for n, _, _ in notas],
            "juez": juez, "s_draft": round(s_draft, 1),
            "s_refine": round(s_refine, 1)}
