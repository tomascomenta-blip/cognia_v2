# -*- coding: utf-8 -*-
"""CLI de imagen -> malla 3D con TripoSR — corre EN venv312gpu (torch cu128).

Contrato (patron expert_forge/cli_train.py): stdout = UNA linea JSON
{"ok": true, "ruta": ..., "verts": n, "caras": m, "seg": s} o
{"ok": false, "error": ...} con exit != 0; TODO el progreso (barras de HF,
prints del vendor) va a stderr.

POR QUE el shim torchmcubes vive AQUI y no compilado: torchmcubes es una
extension CUDA que en Windows exige MSVC — fragil y prohibido por el diseno
(regla 7: NO compilar). tsr/models/isosurface.py solo hace
`from torchmcubes import marching_cubes`; se inyecta en sys.modules un modulo
puro-Python equivalente (skimage.measure.marching_cubes, CPU, milisegundos a
res 256) ANTES de importar tsr. Cero parches al vendor.

POR QUE sin rembg: el quitar-fondo de la casa es BiRefNet
(imagen_quitar_fondo); si la imagen trae canal alfa se aplana sobre gris 0.5
(lo que hace el run.py del vendor tras su remove-bg), y si NO trae alfa se
usa tal cual con AVISO por stderr — degradacion visible, no silenciosa.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


def instalar_shim_torchmcubes() -> None:
    """Inyecta un torchmcubes puro-Python en sys.modules (idempotente).

    POR QUE los imports pesados van DENTRO de marching_cubes: este modulo se
    importa tambien desde los tests en venv312 (sin torch); la inyeccion debe
    ser barata y solo el uso real paga skimage/torch.
    """
    import types
    if "torchmcubes" in sys.modules:
        return

    def marching_cubes(rho, thresh=0.0):
        # Mismo contrato que torchmcubes.marching_cubes: recibe el campo
        # escalar (tensor 3D) y el umbral, devuelve (verts, caras) como
        # tensores torch en coordenadas de voxel — tsr los normaliza despues.
        import numpy as np
        import torch
        from skimage import measure
        campo = rho.detach().cpu().numpy()
        verts, caras, _norms, _vals = measure.marching_cubes(
            campo, level=float(thresh))
        v = torch.from_numpy(np.ascontiguousarray(verts)).float()
        f = torch.from_numpy(np.ascontiguousarray(caras).astype(np.int64))
        return v, f

    mod = types.ModuleType("torchmcubes")
    mod.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = mod


def cargar_imagen(ruta: str, lado: int = 512):
    """Abre y prepara la imagen para TripoSR (PIL RGB).

    RGBA -> aplanada sobre gris 0.5 (127): TripoSR quiere el objeto aislado
    sobre fondo neutro. Sin alfa -> se usa tal cual con AVISO (el resultado
    depende de que el fondo ya sea limpio; el input ideal viene de
    imagen_quitar_fondo). Se acota a `lado` px conservando proporcion:
    la entrada de TripoSR es chica y una foto de 4000px solo quema RAM.
    """
    from PIL import Image
    img = Image.open(ruta)
    if "A" in img.getbands():
        img = img.convert("RGBA")
        fondo = Image.new("RGBA", img.size, (127, 127, 127, 255))
        img = Image.alpha_composite(fondo, img).convert("RGB")
    else:
        print(f"[aviso] {Path(ruta).name} no tiene canal alfa: se usa tal "
              "cual (ideal: PNG RGBA de imagen_quitar_fondo)", file=sys.stderr)
        img = img.convert("RGB")
    if max(img.size) > lado:
        img.thumbnail((lado, lado))
    return img


def _fuente_modelo() -> str:
    """Dir local con los pesos si existe; si no, el repo HF (auto-descarga)."""
    local = Path.home() / ".cognia" / "models" / "triposr"
    if (local / "model.ckpt").is_file() and (local / "config.yaml").is_file():
        return str(local)
    return "stabilityai/TripoSR"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Imagen -> malla 3D (TripoSR + shim marching cubes)")
    parser.add_argument("--imagen", required=True, help="imagen del objeto")
    parser.add_argument("--salida", required=True,
                        help="ruta de la malla (.glb o .obj)")
    parser.add_argument("--formato", default="glb", choices=("glb", "obj"))
    parser.add_argument("--resolucion", type=int, default=256,
                        help="resolucion de marching cubes")
    args = parser.parse_args()

    t0 = time.monotonic()
    imagen = Path(args.imagen).resolve()
    salida = Path(args.salida).resolve()
    if not imagen.is_file():
        print(json.dumps({"ok": False, "error": f"no existe la imagen {imagen}"},
                         ensure_ascii=False))
        return 1
    salida.parent.mkdir(parents=True, exist_ok=True)

    vendor = Path(os.environ.get(
        "COGNIA_TRIPOSR_SRC",
        str(Path.home() / ".cognia" / "vendors" / "TripoSR")))
    sys.path.insert(0, str(vendor))

    # El shim TIENE que estar en sys.modules antes del primer `import tsr`
    # (tsr/models/isosurface.py importa torchmcubes al cargarse).
    instalar_shim_torchmcubes()

    # tsr y HF pueden escribir progreso a stdout y contaminarian el contrato
    # JSON: TODO stdout del trabajo pesado se desvia a stderr.
    stdout_real = sys.stdout
    sys.stdout = sys.stderr
    try:
        import torch
        from tsr.system import TSR

        fuente = _fuente_modelo()
        print(f"[tresd] cargando TripoSR desde {fuente}", file=sys.stderr)
        try:
            model = TSR.from_pretrained(
                fuente, config_name="config.yaml", weight_name="model.ckpt")
        except Exception as exc:
            raise RuntimeError(
                f"no pude cargar TripoSR desde {fuente} ({exc}); si estas "
                "offline, descarga stabilityai/TripoSR (model.ckpt + "
                "config.yaml) a ~/.cognia/models/triposr") from exc
        if hasattr(model, "renderer") and hasattr(model.renderer,
                                                  "set_chunk_size"):
            model.renderer.set_chunk_size(8192)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            print("[aviso] sin CUDA: TripoSR corre en CPU (lento)",
                  file=sys.stderr)
        model.to(device)

        img = cargar_imagen(str(imagen))
        print(f"[tresd] infiriendo scene codes en {device}", file=sys.stderr)
        with torch.no_grad():
            scene_codes = model([img], device=device)
            # La firma de extract_mesh cambio entre versiones del vendor
            # (has_vertex_color aparecio despues): probamos la nueva y caemos
            # a la vieja — sin editar el vendor.
            try:
                mallas = model.extract_mesh(
                    scene_codes, True, resolution=int(args.resolucion))
            except TypeError:
                mallas = model.extract_mesh(
                    scene_codes, resolution=int(args.resolucion))
        malla = mallas[0]
        malla.export(str(salida))
        verts = int(len(malla.vertices))
        caras = int(len(malla.faces))
        if verts == 0 or caras == 0:
            raise RuntimeError(
                f"la malla salio vacia ({verts} verts, {caras} caras): "
                "la imagen probablemente no contiene un objeto claro")
    except Exception:
        sys.stdout = stdout_real
        print(json.dumps({"ok": False, "error": traceback.format_exc()[-2000:]},
                         ensure_ascii=False))
        return 1
    finally:
        sys.stdout = stdout_real

    print(json.dumps({"ok": True, "ruta": str(salida), "verts": verts,
                      "caras": caras, "seg": round(time.monotonic() - t0, 1)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
