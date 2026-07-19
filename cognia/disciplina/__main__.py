"""
CLI de disciplina de reparacion.

En vez de correr el comando de verificacion a pelo mientras arreglas algo, lo
corres a traves de esto. Lleva la cuenta de los intentos sobre el MISMO
sintoma y te corta cuando estas parchando en vez de resolviendo.

    python -m cognia.disciplina verificar "pytest tests/test_x.py -q"
    python -m cognia.disciplina estado
    python -m cognia.disciplina reset        # tras intervencion humana real
    python -m cognia.disciplina historial

El caso que motivo esto, medido el 2026-07-19 en este mismo repo: arreglar el
ranking de relevancia costo CUATRO intentos. Los tres primeros fueron parches
sobre el sintoma (peso fijo -> orden de aparicion -> sustantivo+modificador) y
solo el cuarto ataco la causa: una descripcion de GitHub de 64.765 caracteres
que hacia coincidir terminos por azar. Con este disyuntor el corte habria
llegado en el intento 2, antes de los otros dos parches.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .reparacion import Disyuntor, Intento, huella_de_texto

# El estado vive en el repo, no en temp: sobrevive reinicios y se puede mirar.
DIR_ESTADO = Path(".disciplina")


def _id_tarea(comando: str) -> str:
    """El comando de verificacion identifica la tarea."""
    return hashlib.sha1(comando.encode("utf-8")).hexdigest()[:10]


def _ruta(comando: str) -> Path:
    return DIR_ESTADO / f"{_id_tarea(comando)}.jsonl"


def _cargar(comando: str) -> Disyuntor:
    """Reconstruye el disyuntor desde el JSONL append-only."""
    d = Disyuntor(tarea=comando, ruta_log=_ruta(comando))
    ruta = _ruta(comando)
    if not ruta.exists():
        return d

    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            reg = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if reg.get("evento") == "reset":
            d.intentos.clear()
            continue
        d.intentos.append(Intento(
            n           = reg.get("n", len(d.intentos) + 1),
            clave       = reg.get("clave", ""),
            ok          = reg.get("ok", False),
            hubo_cambio = reg.get("hubo_cambio", True),
            nota        = reg.get("nota", ""),
            t           = reg.get("t", 0.0),
        ))
    return d


def cmd_verificar(comando: str, sin_cambio: bool = False) -> int:
    """
    Corre el comando de verificacion y registra el intento.

    Args:
        comando:    la linea a ejecutar (pytest, un script, lo que sea)
        sin_cambio: marcar el intento como exploracion, no como parche. Leer y
                    probar hipotesis sin editar no debe contar para el corte.
    """
    print(f"[disciplina] $ {comando}")
    proc = subprocess.run(comando, shell=True, capture_output=True, text=True)
    salida = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print(salida.rstrip()[-4000:])

    ok = proc.returncode == 0
    d  = _cargar(comando)
    d.registrar(
        huella_de_texto(salida),
        ok          = ok,
        hubo_cambio = not sin_cambio,
        nota        = f"exit={proc.returncode}",
    )

    if ok:
        print(f"\n[disciplina] VERDE tras {len(d.intentos)} intento(s). "
              f"Contador limpio para la proxima.")
        return 0

    motivo = d.motivo_corte()
    if motivo:
        print(d.orden_de_modo_raiz())
        # Codigo de salida distinto del fallo normal: se puede enganchar.
        return 3

    esteriles = len([i for i in d.intentos if not i.ok and i.hubo_cambio])
    print(f"\n[disciplina] Falla. Intentos esteriles sobre este sintoma: "
          f"{esteriles}. Corte a los {d.max_intentos}.")
    return 1


def cmd_estado(comando: str) -> int:
    d = _cargar(comando)
    if not d.intentos:
        print("[disciplina] Sin intentos registrados.")
        return 0
    print(f"[disciplina] tarea: {comando}")
    print(f"  intentos: {len(d.intentos)}   diagnostico: {d.diagnostico()}")
    for i in d.intentos[-10:]:
        marca = "OK " if i.ok else ("XX " if i.hubo_cambio else ".. ")
        print(f"  {marca} #{i.n} huella={i.clave} {i.nota}")
    return 0


def cmd_reset(comando: str) -> int:
    """
    Resetea el contador. Solo por intervencion humana REAL.

    No usar para 'seguir intentando': el reset existe porque hablar con una
    persona es progreso, no para saltarse el corte.
    """
    ruta = _ruta(comando)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"evento": "reset"}) + "\n")
    print("[disciplina] Contador reseteado por intervencion.")
    return 0


def cmd_historial() -> int:
    if not DIR_ESTADO.exists():
        print("[disciplina] Sin historial.")
        return 0
    for ruta in sorted(DIR_ESTADO.glob("*.jsonl")):
        lineas = [l for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lineas:
            continue
        try:
            primero = json.loads(lineas[0])
        except json.JSONDecodeError:
            continue
        print(f"  {ruta.stem}  {len(lineas)} eventos  {primero.get('tarea','')[:60]}")
    return 0


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__)
        return 2

    accion = argv[0]
    sin_cambio = "--sin-cambio" in argv
    resto = [a for a in argv[1:] if a != "--sin-cambio"]
    comando = " ".join(resto).strip()

    if accion == "historial":
        return cmd_historial()
    if not comando:
        print(f"[disciplina] Falta el comando. Uso: {accion} \"<comando>\"")
        return 2
    if accion == "verificar":
        return cmd_verificar(comando, sin_cambio=sin_cambio)
    if accion == "estado":
        return cmd_estado(comando)
    if accion == "reset":
        return cmd_reset(comando)

    print(f"[disciplina] Accion desconocida: {accion}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
