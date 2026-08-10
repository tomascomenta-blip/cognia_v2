# -*- coding: utf-8 -*-
"""
descargar_qwythos_hf.py — descarga REANUDABLE e IDEMPOTENTE de la base HF
de Qwythos-9B para el entrenamiento QLoRA (plan LoRA Qwythos 2026-08-09).

POR QUE existe: el adapter LoRA debe entrenarse y convertirse contra la base
EXACTA del GGUF servido (huihui-ai/Huihui-Qwythos-9B-Claude-Mythos-5-1M-
abliterated); entrenar sobre un pariente "parecido" invalida la conversion.
El archivo gordo es model.safetensors (~19,3 GB) y en esta red hf-xet /
huggingface_hub se cuelga (leccion del repo, expert_forge/get_base_model.py),
asi que se baja con curl.exe -C - (reanuda byte a byte).

POR QUE es idempotente: YA hay una descarga previa en curso/parcial en el
destino (hf_hub dejo un *.incomplete en .cache/huggingface/download). Este
script: (1) saltea archivos completos (tamano local == remoto), (2) reanuda
parciales con -C -, (3) si detecta el parcial de hf_hub y NADIE lo esta
escribiendo (no crece en la ventana de observacion), lo ADOPTA como parcial
propio y lo reanuda con curl; si SI crece, aborta visible (exit 3) para no
duplicar 19 GB de descarga en paralelo.

Uso (CPU, sin GPU):
  venv312\\Scripts\\python.exe scripts\\descargar_qwythos_hf.py
      [--dest %USERPROFILE%\\.cognia\\models\\qwythos-9b-base]
      [--esperar] [--solo-verificar]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = "huihui-ai/Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated"
DEST_DEFAULT = Path.home() / ".cognia" / "models" / "qwythos-9b-base"

# Solo lo que el entrenamiento y la conversion necesitan. NO se bajan los
# preprocessor de video/vision (diseno_finetune (c)). chat_template.jinja es
# OBLIGATORIO: es la plantilla que llama-server aplica con --jinja y la que
# usa el masking del trainer; sin ella el dataset se renderizaria contra otra
# plantilla (asimetria de instrumento, leccion F1 del prereg de LoRAs).
ARCHIVOS = [
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "chat_template.jinja",
    "model.safetensors",
]

MARGEN_DISCO_BYTES = 2 * 1024 ** 3   # 2 GB de colchon sobre lo pendiente


def _url(nombre: str) -> str:
    return "https://huggingface.co/%s/resolve/main/%s" % (REPO, nombre)


def tamano_remoto(nombre: str, timeout: float = 60.0) -> int:
    """Content-Length del archivo en HF via curl -sIL (HEAD siguiendo
    redirects al CDN). -1 si no se pudo determinar (se degrada visible:
    el plan pasa a 'bajar' sin verificacion de tamano)."""
    try:
        r = subprocess.run(
            ["curl.exe", "-sIL", "--max-time", str(int(timeout)), _url(nombre)],
            capture_output=True, text=True, timeout=timeout + 10)
    except Exception as exc:
        print("  AVISO: HEAD fallo para %s: %s" % (nombre, exc))
        return -1
    if r.returncode != 0:
        return -1
    # Con -L hay varios bloques de headers; vale el ULTIMO content-length
    # (el del CDN que sirve los bytes). x-linked-size es el fallback de HF.
    ultimo, linked = -1, -1
    for linea in (r.stdout or "").splitlines():
        low = linea.lower().strip()
        if low.startswith("content-length:"):
            try:
                ultimo = int(low.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif low.startswith("x-linked-size:"):
            try:
                linked = int(low.split(":", 1)[1].strip())
            except ValueError:
                pass
    return ultimo if ultimo > 0 else linked


def plan_para(local: int, remoto: int) -> str:
    """Decision pura por archivo: 'saltar' | 'reanudar' | 'bajar' |
    'conflicto'. local=0 significa ausente. remoto<=0 = tamano desconocido
    (se baja igual, sin poder verificar — visible en el resumen)."""
    if remoto <= 0:
        return "saltar" if local > 0 else "bajar"
    if local == remoto:
        return "saltar"
    if local == 0:
        return "bajar"
    if local < remoto:
        return "reanudar"
    return "conflicto"   # local MAS grande que el remoto: corrupto o repo cambio


def incomplete_de(dest: Path) -> Path | None:
    """El parcial *.incomplete mas grande que dejo hf_hub bajo
    <dest>/.cache/huggingface/download (o None). Es el model.safetensors
    a medio bajar de la descarga previa."""
    carpeta = dest / ".cache" / "huggingface" / "download"
    if not carpeta.is_dir():
        return None
    parciales = sorted(carpeta.glob("*.incomplete"),
                       key=lambda p: p.stat().st_size, reverse=True)
    return parciales[0] if parciales else None


def creciendo(ruta: Path, espera_s: float = 6.0) -> bool:
    """True si el archivo crecio durante la ventana: otro proceso lo esta
    escribiendo AHORA. Dos stats separados por espera_s (senal real de
    actividad; el mtime/lock de hf_hub no alcanza para saberlo)."""
    try:
        antes = ruta.stat().st_size
        time.sleep(espera_s)
        despues = ruta.stat().st_size
    except OSError:
        return False
    return despues > antes


def cabecera_safetensors_ok(ruta: Path) -> tuple[bool, str]:
    """Chequeo barato de integridad sin cargar 19 GB: los primeros 8 bytes
    son el largo little-endian del header JSON; se lee y parsea solo eso."""
    try:
        with open(ruta, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if n <= 0 or n > 200 * 1024 * 1024:
                return False, "largo de header absurdo: %d" % n
            json.loads(f.read(n).decode("utf-8"))
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _curl_bajar(nombre: str, target: Path) -> None:
    """curl -C - : baja o reanuda target. Levanta RuntimeError si falla
    (degradacion visible, jamas silenciosa)."""
    cmd = ["curl.exe", "-L", "--fail", "--retry", "10", "--retry-all-errors",
           "-C", "-", "--no-progress-meter", "-o", str(target), _url(nombre)]
    print("  bajando/reanudando %s ..." % nombre, flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError("curl fallo (%d) bajando %s" % (r.returncode, nombre))


def _chequear_disco(dest: Path, pendiente: int) -> None:
    libre = shutil.disk_usage(dest).free
    if libre < pendiente + MARGEN_DISCO_BYTES:
        raise RuntimeError(
            "disco insuficiente: libres %.1f GB, pendientes %.1f GB + margen"
            % (libre / 1024 ** 3, pendiente / 1024 ** 3))


def verificar(dest: Path, tamanos: dict[str, int]) -> list[str]:
    """Lista de problemas (vacia = todo OK). Verifica presencia, tamano
    exacto contra el remoto (si se conoce) y header del safetensors."""
    problemas = []
    for nombre in ARCHIVOS:
        target = dest / nombre
        if not target.is_file() or target.stat().st_size == 0:
            problemas.append("falta %s" % nombre)
            continue
        remoto = tamanos.get(nombre, -1)
        local = target.stat().st_size
        if remoto > 0 and local != remoto:
            problemas.append("%s: local %d != remoto %d" % (nombre, local, remoto))
    st = dest / "model.safetensors"
    if st.is_file() and st.stat().st_size > 0:
        ok, motivo = cabecera_safetensors_ok(st)
        if not ok:
            problemas.append("header safetensors invalido: %s" % motivo)
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dest", default=str(DEST_DEFAULT))
    ap.add_argument("--esperar", action="store_true",
                    help="si otro proceso esta bajando el safetensors, "
                         "esperar a que termine en vez de abortar")
    ap.add_argument("--solo-verificar", action="store_true",
                    help="no baja nada: verifica lo presente y sale")
    args = ap.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    print("repo   : %s" % REPO)
    print("destino: %s" % dest)

    tamanos = {n: tamano_remoto(n) for n in ARCHIVOS}
    for n, t in tamanos.items():
        if t <= 0:
            print("  AVISO: tamano remoto desconocido para %s "
                  "(sin verificacion de bytes)" % n)

    if args.solo_verificar:
        problemas = verificar(dest, tamanos)
        for p in problemas:
            print("  PROBLEMA: %s" % p)
        print("VERIFICACION: %s" % ("OK" if not problemas else "FALLA"))
        return 0 if not problemas else 1

    # --- manejo del parcial de hf_hub (la descarga previa en curso) -------
    st_target = dest / "model.safetensors"
    parcial = incomplete_de(dest)
    if parcial is not None and not (st_target.is_file()
                                    and st_target.stat().st_size > 0):
        print("parcial hf_hub detectado: %s (%.2f GB)"
              % (parcial.name, parcial.stat().st_size / 1024 ** 3))
        while creciendo(parcial):
            if not args.esperar:
                print("OTRO proceso esta bajando el safetensors AHORA "
                      "(el parcial crece). Abortando para no duplicar 19 GB; "
                      "re-ejecutar cuando termine, o pasar --esperar.")
                return 3
            print("  descarga ajena activa; esperando 60 s ...", flush=True)
            time.sleep(60)
        # hf_hub baja secuencial (hf-xet/hf_transfer no corren en esta red):
        # el parcial es un prefijo valido del archivo -> se adopta y curl
        # reanuda desde ese byte. Idempotente: si ya fue adoptado, no esta.
        print("  adoptando parcial como model.safetensors y reanudando con curl")
        os.replace(parcial, st_target)

    # --- plan por archivo -------------------------------------------------
    pendiente = 0
    planes: dict[str, str] = {}
    for nombre in ARCHIVOS:
        target = dest / nombre
        local = target.stat().st_size if target.is_file() else 0
        accion = plan_para(local, tamanos[nombre])
        planes[nombre] = accion
        if accion == "conflicto":
            print("CONFLICTO en %s: local %d > remoto %d — borrar a mano y "
                  "re-correr (no se pisa nada en silencio)"
                  % (nombre, local, tamanos[nombre]))
            return 2
        if accion in ("bajar", "reanudar"):
            pendiente += max(0, tamanos[nombre] - local)
        print("  %-32s %s" % (nombre, accion))

    if pendiente:
        _chequear_disco(dest, pendiente)

    for nombre in ARCHIVOS:
        if planes[nombre] in ("bajar", "reanudar"):
            _curl_bajar(nombre, dest / nombre)

    problemas = verificar(dest, tamanos)
    for p in problemas:
        print("  PROBLEMA: %s" % p)
    print("DESCARGA: %s" % ("COMPLETA" if not problemas else "INCOMPLETA"))
    return 0 if not problemas else 1


if __name__ == "__main__":
    sys.exit(main())
