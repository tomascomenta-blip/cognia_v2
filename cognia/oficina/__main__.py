"""Arranque de la oficina: python -m cognia.oficina [--puerto 8766] [--sin-modelo]

Levanta el dashboard en http://127.0.0.1:<puerto> y el motor jefe/directores/
trabajadores sobre el backend REAL de Cognia (mismo camino que el CLI).
--sin-modelo: solo dashboard + estado (ver/editar/detener); las metas quedan
pendientes hasta que un motor con modelo las procese. Honesto: sin modelo no
se simula trabajo.
"""
import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(description="Oficina de trabajo agéntica de Cognia")
    # 8766: el 8765 es del cognia_desktop_api (colisión cazada en el e2e
    # 2026-07-15: /oficina dejaba un server residual que pisaba al desktop).
    ap.add_argument("--puerto", type=int, default=8766)
    ap.add_argument("--estado", default=os.path.join(os.getcwd(), "oficina_estado.json"))
    ap.add_argument("--sin-modelo", action="store_true",
                    help="solo dashboard/control, sin motor (no carga el 3B)")
    args = ap.parse_args()

    # MISMO camino de arranque que el CLI: sin esto, el producto INSTALADO
    # no veía LLAMA_GGUF_PATH/LLAMA_SERVER_PATH de ~/.cognia/config.env y el
    # motor corría "sin backend de inferencia" (cazado e2e 2026-07-15: los
    # trabajadores devolvían el error como resultado).
    try:
        from cognia.first_run import apply_config
        apply_config()
    except Exception:
        pass

    from cognia.oficina.estado import Oficina
    from cognia.oficina.server import crear_server

    of = Oficina(args.estado)
    motor = None
    if not args.sin_modelo:
        try:
            from cognia.cli import Cognia
            from cognia.oficina.motor import Motor
            print("[oficina] cargando backend de Cognia (mismo camino que el CLI)...")
            ai = Cognia()
            motor = Motor(of, ai=ai)
            motor.start()
            print("[oficina] motor arriba (jefe/directores/trabajadores)")
        except Exception as e:
            print(f"[oficina] SIN MOTOR: el modelo no cargó ({e}). "
                  "El dashboard funciona igual; las metas quedan pendientes.")

    srv = crear_server(of, puerto=args.puerto)
    print(f"[oficina] dashboard: http://127.0.0.1:{args.puerto}  (Ctrl+C corta)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if motor is not None:
            motor.stop()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
