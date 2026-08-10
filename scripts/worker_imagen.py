# -*- coding: utf-8 -*-
"""Worker de imagen del summoner (rol "imagen", puerto 8096, venv312gpu).

POR QUE es un subproceso: cognia.assets cachea el pipeline SDXL en un global
(_PIPE) SIN codigo de unload — y no se escribe un unload de diffusers en esta
sesion. Matar este proceso ES el unload; el summoner lo lanza y lo mata segun
la VRAM. Se corre con el python de GPU:

    venv312gpu\\Scripts\\python.exe scripts\\worker_imagen.py --puerto 8096

Payload de /job (contrato congelado en plan_olas.md, agente B):
    {"op": "generar"|"editar"|"quitar_fondo", ...kwargs de cognia.assets}
    -> {"ok": true, "ruta": "<png>"} | {"ok": false, "error": "..."}

La salida SIEMPRE va a una ruta explicita bajo COGNIA_ASSETS_OUT (default
~/.cognia/assets): el artefacto sobrevive en disco aunque el restore del
cerebro falle despues del job.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# El worker corre con venv312gpu, donde cognia NO esta instalado como paquete:
# se importa directo del repo (este script vive en <repo>/scripts/).
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_OPS = ("generar", "editar", "quitar_fondo")


def _dir_salida() -> Path:
    d = Path(os.environ.get("COGNIA_ASSETS_OUT",
                            str(Path.home() / ".cognia" / "assets")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ruta_salida(op: str) -> str:
    # Nombre unico por timestamp+pid: dos jobs seguidos no se pisan y el
    # llamador siempre recibe la ruta exacta en la respuesta.
    return str(_dir_salida() / ("%s_%d_%d.png" % (op, int(time.time() * 1000),
                                                  os.getpid())))


def manejar(payload: dict) -> dict:
    """Ejecuta una op de cognia.assets. Devuelve {"ok", "ruta"} o {"ok": False, "error"}.

    Los errores esperables (op invalida, backend ausente, kwargs faltantes)
    vuelven como {"ok": false} SIN traceback: son diagnosticos, no bugs. Las
    excepciones inesperadas las convierte summoner_worker.servir() en
    {"ok": false, "error": tb} sin matar al worker.
    """
    op = payload.get("op", "")
    if op not in _OPS:
        return {"ok": False,
                "error": "op desconocida: %r (validas: %s)" % (op, list(_OPS))}

    # Import perezoso: torch/diffusers recien se tocan cuando llega un job.
    from cognia import assets

    # Gate barato ANTES de intentar cargar nada (degradacion VISIBLE con el
    # motivo real, no un ImportError criptico minutos despues).
    # quitar_fondo usa BiRefNet, que no necesita el src de LayerDiffuse: su
    # gate propio evita reprobar un matting sano por un prerequisito ajeno.
    if op == "quitar_fondo":
        ok, motivo = assets.birefnet_disponible()
    else:
        ok, motivo = assets.backend_disponible()
    if not ok:
        return {"ok": False, "error": "backend de assets no disponible: %s" % motivo}

    kwargs = {k: v for k, v in payload.items() if k != "op"}
    # salida explicita SIEMPRE: quitar_fondo con salida=None devuelve una
    # PIL.Image (no serializable) y el artefacto debe quedar en disco.
    kwargs.setdefault("salida", _ruta_salida(op))

    if op == "generar":
        prompt = kwargs.pop("prompt", None)
        if not prompt:
            return {"ok": False, "error": "generar requiere 'prompt'"}
        ruta = assets.generar_transparente(prompt, **kwargs)
    elif op == "editar":
        imagen = kwargs.pop("imagen", None)
        prompt = kwargs.pop("prompt", None)
        if not imagen or not prompt:
            return {"ok": False, "error": "editar requiere 'imagen' y 'prompt'"}
        ruta = assets.editar_transparente(imagen, prompt, **kwargs)
    else:  # quitar_fondo
        entrada = kwargs.pop("entrada", None) or kwargs.pop("imagen", None)
        if not entrada:
            return {"ok": False,
                    "error": "quitar_fondo requiere 'entrada' (ruta de imagen)"}
        ruta = assets.quitar_fondo(entrada, **kwargs)

    return {"ok": True, "ruta": str(ruta)}


def precargar() -> None:
    """Carga el pipeline SDXL ANTES de abrir el puerto (COGNIA_WORKER_PRELOAD=1).

    POR QUE fallar aca es correcto: si el backend no esta disponible con
    preload pedido, mejor que el worker NO abra el puerto y el summoner vea
    "murio al arrancar" + este motivo en el log, a que abra y cada job muera.
    """
    from cognia import assets
    ok, motivo = assets.backend_disponible()
    if not ok:
        raise RuntimeError("backend de assets no disponible: %s" % motivo)
    # _cargar_pipeline es privado pero del mismo repo: es exactamente "cargar
    # el modelo", que es lo unico que el preload significa para este rol.
    from cognia.assets import diffusion_backend
    diffusion_backend._cargar_pipeline()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Worker de imagen del summoner (cognia.assets en venv312gpu)")
    ap.add_argument("--puerto", type=int, default=8096,
                    help="puerto local (default 8096, registro del summoner)")
    args = ap.parse_args(argv)

    from cognia.summoner_worker import servir
    # cargar_fn solo con PRELOAD=1: cognia.assets YA carga perezoso dentro de
    # cada op (con gate por-op). Pasar precargar tambien en modo perezoso
    # haria que el gate de LayerDiffuse frene un quitar_fondo (BiRefNet) sano.
    cargar = precargar if os.environ.get("COGNIA_WORKER_PRELOAD", "0") == "1" else None
    print("[worker_imagen] sirviendo en 127.0.0.1:%d (pid %d)"
          % (args.puerto, os.getpid()), file=sys.stderr)
    sys.stderr.flush()
    servir(args.puerto, "imagen", cargar, manejar)
    print("[worker_imagen] apagado limpio", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
