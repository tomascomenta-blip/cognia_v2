"""
CLI de disciplina de reparacion.

En vez de correr el comando de verificacion a pelo mientras arreglas algo, lo
corres a traves de esto. Lleva la cuenta de los intentos sobre el MISMO
sintoma y te corta cuando estas parchando en vez de resolviendo.

    python -m cognia.disciplina verificar "pytest tests/test_x.py -q"
    python -m cognia.disciplina verificar --sombra "pytest ..."  # registra sin cortar
    python -m cognia.disciplina estado
    python -m cognia.disciplina reset        # tras intervencion humana real
    python -m cognia.disciplina historial
    python -m cognia.disciplina sombra-informe   # ¿aciertan los disparos?

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

from .reparacion import DIR_ESTADO, Disyuntor, Intento, huella_de_texto

# Umbral de calibracion del modo sombra (plan INVESTIGACION_Y_ANTIRUIDO):
# los umbrales del disyuntor vienen de Aider/OpenHands, no de datos propios.
# Se aceptan si al menos esta fraccion de los disparos precedio a un bucle
# realmente esteril (ver `_evaluar_disparos` para la definicion operativa).
ACEPTACION_MINIMA = 0.60


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
        if reg.get("evento"):
            # "disparo"/"disparo_sombra" (u otros eventos futuros) no son
            # intentos: meterlos en la ventana como Intento con clave vacia
            # falsearia el conteo de esteriles y podria disparar el corte
            # con datos fantasma.
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


def cmd_verificar(comando: str, sin_cambio: bool = False,
                  sombra: bool = False) -> int:
    """
    Corre el comando de verificacion y registra el intento.

    Args:
        comando:    la linea a ejecutar (pytest, un script, lo que sea)
        sin_cambio: marcar el intento como exploracion, no como parche. Leer y
                    probar hipotesis sin editar no debe contar para el corte.
        sombra:     MODO SOMBRA — registra el disparo pero NO corta (exit 1
                    normal en vez de 3). Para calibrar los umbrales con datos
                    propios antes de fiarse del corte: los actuales vienen de
                    Aider/OpenHands, no de este repo.
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
    if motivo and sombra:
        # El disparo queda en el JSONL para el informe de aceptacion, pero
        # el flujo sigue como un fallo normal: registrar sin actuar.
        d.persistir_evento("disparo_sombra", motivo=motivo,
                           intento=len(d.intentos))
        print(f"\n[disciplina] SOMBRA: aqui habria cortado "
              f"({d.diagnostico()}). Registrado; se sigue.")
        return 1
    if motivo:
        d.persistir_evento("disparo", motivo=motivo, intento=len(d.intentos))
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


def _evaluar_disparos(lineas: list) -> list:
    """
    Evalua cada disparo de un JSONL contra lo que paso DESPUES.

    Definicion operativa, fijada ANTES de tener datos (2026-08-01):
      - FALSO POSITIVO: el primer intento CON CAMBIO posterior al disparo es
        verde y no hubo reset en medio — el corte habria bloqueado justo el
        parche que arreglaba.
      - ACIERTO: cualquier otro caso — el verde tardo 2+ parches mas, o no
        llego nunca, o solo llego tras intervencion humana (reset): el bucle
        era realmente esteril y cortar habria ahorrado trabajo.

    Devuelve [{"motivo", "acierto": bool, "razon"}].
    """
    regs = []
    for linea in lineas:
        try:
            regs.append(json.loads(linea))
        except json.JSONDecodeError:
            continue

    salida = []
    for idx, reg in enumerate(regs):
        if reg.get("evento") not in ("disparo", "disparo_sombra"):
            continue
        acierto, razon = True, "sin verde posterior"
        for post in regs[idx + 1:]:
            if post.get("evento") == "reset":
                acierto, razon = True, "verde solo tras reset"
                break
            if post.get("evento"):
                continue
            if not post.get("hubo_cambio", True):
                continue                      # exploracion: no es un parche
            if post.get("ok"):
                acierto, razon = False, "el parche siguiente era el bueno"
            else:
                acierto, razon = True, "el bucle siguio esteril"
            break
        salida.append({"motivo": reg.get("motivo", "?"),
                       "acierto": acierto, "razon": razon})
    return salida


def cmd_sombra_informe() -> int:
    """
    ¿Aciertan los disparos del disyuntor? Aceptacion = aciertos / disparos.

    Los umbrales se aceptan con datos propios si la aceptacion es
    >= ACEPTACION_MINIMA (60%). Con pocos disparos el numero no decide nada
    y el informe lo dice.
    """
    if not DIR_ESTADO.exists():
        print("[disciplina] Sin datos: no existe .disciplina/")
        return 0
    todos = []
    for ruta in sorted(DIR_ESTADO.glob("*.jsonl")):
        lineas = [l for l in ruta.read_text(encoding="utf-8").splitlines()
                  if l.strip()]
        for ev in _evaluar_disparos(lineas):
            todos.append({**ev, "log": ruta.stem})

    if not todos:
        print("[disciplina] Sin disparos registrados todavia. Correr con "
              "--sombra (o dejar que el corte real dispare) para acumular.")
        return 0

    aciertos = [e for e in todos if e["acierto"]]
    tasa = len(aciertos) / len(todos)
    print(f"[disciplina] disparos: {len(todos)}   aciertos: {len(aciertos)}   "
          f"falsos positivos: {len(todos) - len(aciertos)}")
    print(f"  aceptacion: {tasa:.0%}   (umbral {ACEPTACION_MINIMA:.0%})")
    por_motivo = {}
    for e in todos:
        por_motivo.setdefault(e["motivo"], [0, 0])
        por_motivo[e["motivo"]][0] += 1
        por_motivo[e["motivo"]][1] += int(e["acierto"])
    for motivo, (n, ok) in sorted(por_motivo.items()):
        print(f"  {motivo:<4} {ok}/{n} aciertan")
    for e in todos:
        marca = "OK " if e["acierto"] else "FP "
        print(f"  {marca} [{e['log']}] {e['motivo']}: {e['razon']}")
    if len(todos) < 10:
        print(f"  ({len(todos)} disparos: numero orientativo, no decide "
              f"— se necesitan mas datos)")
    elif tasa >= ACEPTACION_MINIMA:
        print("  UMBRALES ACEPTADOS con datos propios.")
    else:
        print("  UMBRALES EN DUDA: revisar antes de fiarse del corte.")
    return 0


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__)
        return 2

    accion = argv[0]
    sin_cambio = "--sin-cambio" in argv
    sombra = "--sombra" in argv
    resto = [a for a in argv[1:] if a not in ("--sin-cambio", "--sombra")]
    comando = " ".join(resto).strip()

    if accion == "historial":
        return cmd_historial()
    if accion == "sombra-informe":
        return cmd_sombra_informe()
    if not comando:
        print(f"[disciplina] Falta el comando. Uso: {accion} \"<comando>\"")
        return 2
    if accion == "verificar":
        return cmd_verificar(comando, sin_cambio=sin_cambio, sombra=sombra)
    if accion == "estado":
        return cmd_estado(comando)
    if accion == "reset":
        return cmd_reset(comando)

    print(f"[disciplina] Accion desconocida: {accion}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
