"""EL punto unico tools <-> summoner (plan integrado, conflicto C1).

POR QUE existe: summoner.ensure() LEVANTA SummonerError; si cada tool lo
llamara directo, cada una tendria que traducir la excepcion y ademas
tolerar que el summoner no exista todavia (ola 1 corre en paralelo).
Este modulo traduce a la tupla plana (ok, url, motivo) y absorbe tres
mundos sin que las tools lo noten:
  1. summoner presente  -> ensure()/liberar() de verdad
  2. summoner apagado   -> COGNIA_SUMMONER=0 fuerza el fallback local
                           (util para depurar tools sin orquestacion)
  3. summoner ausente   -> ImportError cae al mismo fallback local

Fallback local: rol 'vlm' sondea el backend ya conocido (arbitro_visual);
el resto solo verifica que la VRAM libre medida (nvidia-smi) alcance, sin
levantar nada. La degradacion es siempre VISIBLE: cada False viene con un
motivo accionable.
"""

import os
import sys


def pedir_backend(rol: str, mib_necesarios: int) -> tuple:
    """(ok, url, motivo). url puede ser '' (roles presupuesto no tienen).

    POR QUE la tupla y no la excepcion: las tools reportan al modelo en
    texto plano; un motivo str se inserta en la respuesta ERROR sin
    try/except por familia. Solo SummonerError se traduce - cualquier otra
    excepcion del summoner es un bug y debe verse, no taparse."""
    if os.environ.get("COGNIA_SUMMONER", "1").strip() == "0":
        return _fallback_local(rol, mib_necesarios)
    try:
        from cognia import summoner
    except ImportError:
        return _fallback_local(rol, mib_necesarios)
    try:
        r = summoner.ensure(rol)
        return True, (r.get("url") or ""), ""
    except summoner.SummonerError as e:
        return False, "", str(e)


def soltar_backend(rol: str) -> None:
    """Libera el rol best-effort (para el finally de las tools).

    POR QUE nunca lanza: se llama en finally; una excepcion aqui taparia
    el error real de la tool. Pero el fallo se IMPRIME a stderr - la
    degradacion silenciosa esta prohibida en este repo."""
    try:
        from cognia import summoner
    except ImportError:
        return    # sin summoner no hay nada que soltar
    try:
        summoner.liberar(rol)
    except Exception as e:
        print(f"[backend_gate] soltar_backend({rol}) fallo: {e}",
              file=sys.stderr)


def _fallback_local(rol: str, mib_necesarios: int) -> tuple:
    """Camino sin summoner: sondeo directo del mundo, sin levantar procesos.

    POR QUE 'vlm' es especial: ya existe un backend conocido con URL y
    health-check (arbitro_visual); para el resto lo unico honesto que se
    puede afirmar sin summoner es 'la VRAM libre alcanza o no'."""
    if rol == "vlm":
        try:
            from cognia.program_creator import arbitro_visual
        except ImportError as e:
            return False, "", f"sin summoner y sin arbitro_visual ({e})"
        ok, motivo = arbitro_visual.vlm_disponible()
        if ok:
            return True, arbitro_visual.url_vlm(), ""
        return False, "", motivo
    libre, motivo = _vram_libre_mib()
    if libre < 0:
        return False, "", motivo
    if libre >= mib_necesarios:
        return True, "", ""
    return False, "", (
        f"VRAM libre {libre} MiB < {mib_necesarios} MiB para el rol "
        f"'{rol}' (libera la GPU - p.ej. 'python -m cognia.flota parar' - "
        f"o habilita el summoner quitando COGNIA_SUMMONER=0)")


def _vram_libre_mib() -> tuple:
    """(mib_libres, motivo). -1 si no se pudo medir.

    POR QUE -1 y no 0: 'no pude medir' NO es 'no hay memoria'; confundirlos
    seria degradar en silencio. El motivo dice que fallo exactamente."""
    import subprocess
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except Exception as e:
        return -1, f"nvidia-smi no corre ({e})"
    if r.returncode != 0:
        err = (r.stderr or "").strip()[:200]
        return -1, f"nvidia-smi fallo (rc={r.returncode}): {err}"
    megas = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    if not megas:
        return -1, f"nvidia-smi sin cifras: {r.stdout.strip()[:200]}"
    return max(megas), ""
