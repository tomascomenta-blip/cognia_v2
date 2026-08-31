"""
cognia/clases/almacen.py
========================
Persistencia INCREMENTAL de una jornada de clases.

POR QUE ASI. Una jornada son 5-7 horas de grabacion. Cualquier diseno que
guarde "al final" pierde la manana entera si el portatil se suspende, si el
REPL muere o si se va la luz -- y eso no es un caso raro, es el caso NORMAL
de un dia de clase. Aqui todo se escribe segun pasa:

  - Los hechos van a ficheros JSONL **append-only**, una linea por hecho. Un
    fichero a medio escribir pierde COMO MUCHO la ultima linea, y leerlo
    salta esa linea sin romperse.
  - El estado mutable (que materia va, si esta pausado) va a un JSON chico
    que se escribe de forma ATOMICA (fichero temporal + os.replace), que en
    Windows es lo unico que no deja un JSON truncado si el proceso muere en
    mitad del write.
  - El audio va en TROZOS numerados, no en un WAV gigante: un WAV de 6 horas
    con la cabecera sin cerrar es un fichero ilegible; 700 trozos de 30 s
    son 699 trozos buenos y uno malo.

Nada aqui sabe de audio, de materias ni del modelo: es solo el disco.

DISPOSICION EN DISCO

    ~/.cognia/clases/
      jornadas/
        2026-08-31/
          jornada.json          estado (atomico)
          transcripcion.jsonl   {t0,t1,texto,fuente}      append-only
          entradas.jsonl        {t,tipo,...}              append-only
          cortes.jsonl          {t,materia,confianza,por} append-only
          audio/000001.wav      trozos crudos (purgables)
          adjuntos/...          imagenes y clips del usuario
          apuntes.json          apuntes generados (atomico)
      cuaderno.json             indice global de materias (atomico)
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

# Nombre de los ficheros. En constantes porque los lee tambien la vista HTML
# y el olvido, y una errata suelta en uno de los tres deja un cuaderno mudo.
JORNADA = "jornada.json"
TRANSCRIPCION = "transcripcion.jsonl"
ENTRADAS = "entradas.jsonl"
CORTES = "cortes.jsonl"
APUNTES = "apuntes.json"
DIR_AUDIO = "audio"
DIR_ADJUNTOS = "adjuntos"
INDICE = "cuaderno.json"


def raiz() -> Path:
    """~/.cognia/clases, creada. COGNIA_CLASES_DIR la mueve (util en tests:
    sin esto los tests escribirian en el cuaderno REAL del dueno)."""
    env = os.environ.get("COGNIA_CLASES_DIR", "").strip()
    base = Path(env) if env else Path.home() / ".cognia" / "clases"
    base.mkdir(parents=True, exist_ok=True)
    return base


def dir_jornada(nombre: str) -> Path:
    d = raiz() / "jornadas" / _seguro(nombre)
    (d / DIR_AUDIO).mkdir(parents=True, exist_ok=True)
    (d / DIR_ADJUNTOS).mkdir(parents=True, exist_ok=True)
    return d


def _seguro(nombre: str) -> str:
    """Un nombre de jornada/materia que venga del usuario NO puede salirse de
    la carpeta. Se filtra a lo que es seguro en un nombre de fichero en
    Windows y se recorta; vacio -> 'sin-nombre'."""
    limpio = "".join(c if (c.isalnum() or c in " -_.") else "-"
                     for c in (nombre or "").strip())
    limpio = limpio.strip(" .-")[:80]
    return limpio or "sin-nombre"


# ── JSONL append-only ────────────────────────────────────────────────────────

def apendar(ruta: Path, registro: dict) -> None:
    """Una linea JSON al final, con flush. El flush no es opcional: sin el,
    los ultimos minutos de clase viven en el buffer del proceso y se pierden
    justo en el corte que este fichero existe para sobrevivir."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def leer_jsonl(ruta: Path) -> list:
    """Los registros de un JSONL, SALTANDO las lineas rotas.

    La ultima linea de un fichero que se corto a mitad no es JSON. Reventar
    ahi tiraria la jornada entera por el ultimo medio segundo: se salta y se
    sigue, que es justo para lo que se eligio el formato.
    """
    if not ruta.exists():
        return []
    fuera = []
    with ruta.open("r", encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                fuera.append(json.loads(linea))
            except ValueError:
                continue
    return fuera


# ── JSON atomico ─────────────────────────────────────────────────────────────

def guardar_json(ruta: Path, datos) -> None:
    """Escribe con fichero temporal + os.replace (atomico en NTFS).

    Un `open(w)` normal trunca el fichero ANTES de escribir: si el proceso
    muere ahi, el estado de la jornada queda en 0 bytes y la manana entera
    pasa a ser irrecuperable aunque los JSONL esten intactos.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def leer_json(ruta: Path, defecto=None):
    """El JSON, o `defecto` si no esta o esta roto. Nunca lanza: un indice
    corrupto no puede impedir grabar la clase de hoy."""
    if not ruta.exists():
        return defecto
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return defecto


# ── Adjuntos ─────────────────────────────────────────────────────────────────

def copiar_adjunto(jornada: str, origen, prefijo: str = "adj") -> str:
    """Copia un fichero del usuario DENTRO de la jornada y devuelve su nombre.

    Se copia y no se referencia la ruta original a proposito: el cuaderno
    tiene que seguir enseniando la foto de la pizarra dentro de seis meses,
    cuando esa captura ya no este en Descargas.
    """
    origen = Path(origen).expanduser()
    if not origen.is_file():
        raise FileNotFoundError(str(origen))
    destino_dir = dir_jornada(jornada) / DIR_ADJUNTOS
    n = 1 + sum(1 for _ in destino_dir.glob(prefijo + "_*"))
    destino = destino_dir / ("%s_%04d%s" % (prefijo, n, origen.suffix.lower()))
    shutil.copy2(origen, destino)
    return destino.name


def ruta_adjunto(jornada: str, nombre: str) -> Path:
    return dir_jornada(jornada) / DIR_ADJUNTOS / _seguro(nombre)


# ── Jornadas ─────────────────────────────────────────────────────────────────

def jornadas() -> list:
    """Nombres de jornada, de la mas nueva a la mas vieja."""
    base = raiz() / "jornadas"
    if not base.is_dir():
        return []
    return sorted((d.name for d in base.iterdir() if d.is_dir()), reverse=True)


def bytes_de(jornada: str) -> dict:
    """{'audio': n, 'adjuntos': n, 'texto': n} en bytes. Lo usa el olvido para
    decidir que purgar y el /grabar-clase estado para no mentir sobre lo que
    ocupa el cuaderno."""
    d = dir_jornada(jornada)
    def _suma(p):
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    texto = sum(f.stat().st_size for f in d.glob("*.json*") if f.is_file())
    return {"audio": _suma(d / DIR_AUDIO),
            "adjuntos": _suma(d / DIR_ADJUNTOS),
            "texto": texto}
