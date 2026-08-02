# -*- coding: utf-8 -*-
"""
scripts/limpiar_seed_duplicado.py
=================================
Limpieza UNA VEZ de los duplicados del seed estatico en episodic_memory.

CONTEXTO (auditoria 2026-08-01): seed_static reinyectaba ~130 hechos en cada
arranque sin comprobar existencia -> 220.780 filas de seed con solo 134 textos
distintos (1.97 GB de DB, top-k envenenado por copias). El bug de reinyeccion
ya esta corregido en cognia/knowledge/knowledge_seeder.py; este script repara
el DANO ACUMULADO borrando las copias y dejando UNA fila por texto.

BORRA DATOS: correr solo con decision explicita del dueno.

TRES GUARDAS (auditoria de la fase de reparacion, 2026-08-01):
  1. El patron de label usa ESCAPE: en LIKE, '_' es comodin de UN caracter, asi
     que 'conocimiento_%' tambien casaba 'conocimientos_personales'. Con
     ESCAPE '\\' el guion bajo es literal y solo casan los labels que produce
     seed_static. El patron vive en knowledge_seeder.SEED_LABEL_PATTERN para
     que script y seeder no puedan divergir.
  2. Whitelist de TEXTOS: solo se borran filas cuya observation es LITERALMENTE
     uno de los hechos de _STATIC_SEEDS. Una memoria del usuario no puede ser
     tocada aunque llevara un label de seed, porque su texto no esta en la
     lista.
  3. Se conserva una fila ACTIVA (forgotten=0) por texto cuando existe; solo si
     todas las copias de ese texto estan olvidadas se conserva una olvidada.
     Con MIN(id) a secas podia sobrevivir una fila forgotten=1 y borrarse la
     unica copia activa del hecho.

Uso:
    venv312/Scripts/python.exe scripts/limpiar_seed_duplicado.py           # dry-run
    venv312/Scripts/python.exe scripts/limpiar_seed_duplicado.py --aplicar # borra + VACUUM
"""

import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognia.config import DB_PATH
from cognia.knowledge.knowledge_seeder import (
    SEED_LABEL_PATTERN,
    SEED_LABEL_WHERE,
    seed_observations,
)
from storage.db_pool import db_connect_pooled


def _seed_cte(n_textos: int) -> str:
    """CTE 'seed' = filas candidatas, y 'keep' = la fila que sobrevive por texto.

    Candidata = label de seed (con ESCAPE) Y texto en la whitelist. 'keep'
    prefiere la fila activa mas antigua; si el texto solo tiene filas olvidadas,
    conserva la olvidada mas antigua (no se pierde el hecho).
    """
    marcadores = ",".join("?" * n_textos)
    return f"""
        WITH seed AS (
            SELECT id, observation, forgotten FROM episodic_memory
            WHERE {SEED_LABEL_WHERE}
              AND observation IN ({marcadores})
        ),
        keep AS (
            SELECT MIN(id) AS id FROM seed WHERE forgotten = 0 GROUP BY observation
            UNION
            SELECT MIN(id) AS id FROM seed
            WHERE observation NOT IN (SELECT observation FROM seed WHERE forgotten = 0)
            GROUP BY observation
        )
    """


def _params(textos) -> tuple:
    return (SEED_LABEL_PATTERN,) + tuple(textos)


def _informe(conn, textos) -> dict:
    """Conteos REALES antes de tocar nada."""
    p = _params(textos)
    cte = _seed_cte(len(textos))

    total_label = conn.execute(
        f"SELECT COUNT(*) FROM episodic_memory WHERE {SEED_LABEL_WHERE}",
        (SEED_LABEL_PATTERN,),
    ).fetchone()[0]
    candidatas, distintas = conn.execute(
        f"{cte} SELECT COUNT(*), COUNT(DISTINCT observation) FROM seed", p
    ).fetchone()
    a_borrar = conn.execute(
        f"{cte} SELECT COUNT(*) FROM seed WHERE id NOT IN (SELECT id FROM keep)", p
    ).fetchone()[0]
    no_seed = conn.execute(
        f"SELECT COUNT(*) FROM episodic_memory WHERE NOT ({SEED_LABEL_WHERE})"
        " OR label IS NULL",
        (SEED_LABEL_PATTERN,),
    ).fetchone()[0]
    return {
        "total_label": total_label,
        "candidatas": candidatas,
        "distintas": distintas,
        "a_borrar": a_borrar,
        "label_sin_whitelist": total_label - candidatas,
        "no_seed": no_seed,
    }


def _backup(db_path: str) -> str:
    """Backup ANTES de borrar. Devuelve la ruta creada; si falla, el script ABORTA.

    Via preferida: 'VACUUM INTO' -> snapshot transaccionalmente consistente en UN
    solo archivo, aunque otro proceso este escribiendo. Fallback (SQLite viejo):
    copiar el trio .db/-wal/-shm tras cerrar el pool, porque con WAL parte de los
    datos vive en el sidecar y copiar solo el .db daria un backup incompleto.
    El fallback NO es atomico: correrlo con Cognia cerrado.
    """
    destino = f"{db_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    conn = db_connect_pooled(db_path)
    try:
        conn.execute("VACUUM INTO ?", (destino,))
        return destino
    except Exception as e:
        print(f"  (VACUUM INTO no disponible: {e}; copio los archivos)")
    finally:
        conn.close()

    from storage.db_pool import close_pool
    close_pool(db_path)  # que nadie de ESTE proceso escriba mientras copiamos
    shutil.copy2(db_path, destino)
    for suf in ("-wal", "-shm"):
        if os.path.exists(db_path + suf):
            shutil.copy2(db_path + suf, destino + suf)
    return destino


def _contar_filas(db_path: str) -> int:
    """Filas de episodic_memory en 'db_path'. Se usa para verificar el backup."""
    from storage.db_pool import close_pool
    conn = db_connect_pooled(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    finally:
        conn.close()
        close_pool(db_path)  # soltar el handle del backup (Windows)


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    textos = sorted(seed_observations())

    conn = db_connect_pooled(DB_PATH)
    try:
        inf = _informe(conn, textos)
        print(f"DB: {DB_PATH}")
        print(f"Filas con label de seed (ESCAPE): {inf['total_label']}")
        print(f"  candidatas (texto en la whitelist de {len(textos)} hechos): "
              f"{inf['candidatas']} | textos distintos: {inf['distintas']}")
        print(f"  label de seed pero texto DESCONOCIDO (NO se tocan): "
              f"{inf['label_sin_whitelist']}")
        print(f"Filas que NO son seed (memorias del usuario, intocables): {inf['no_seed']}")
        print(f"DUPLICADOS A BORRAR: {inf['a_borrar']}")

        if not aplicar:
            print("DRY-RUN: nada borrado. Ejecutar con --aplicar para limpiar.")
            return 0
        if inf["a_borrar"] == 0:
            print("Nada que borrar.")
            return 0
    finally:
        conn.close()

    # Backup obligatorio antes de cualquier DELETE, y VERIFICADO: un backup que
    # no se puede abrir y contar no es un backup.
    try:
        bak = _backup(DB_PATH)
        filas_bak = _contar_filas(bak)
        if filas_bak <= 0:
            raise RuntimeError(f"el backup tiene {filas_bak} filas")
        print(f"Backup: {bak} ({os.path.getsize(bak) / (1024 * 1024):.1f} MB, "
              f"{filas_bak} filas legibles)")
    except Exception as e:
        print(f"ABORTADO: no se pudo hacer/verificar el backup ({e}). No se borro nada.")
        return 1

    conn = db_connect_pooled(DB_PATH)
    try:
        conn.execute(
            f"{_seed_cte(len(textos))} DELETE FROM episodic_memory "
            "WHERE id IN (SELECT id FROM seed) AND id NOT IN (SELECT id FROM keep)",
            _params(textos),
        )
        conn.commit()
        despues = _informe(conn, textos)
    finally:
        conn.close()

    # cursor.rowcount devuelve -1 en un DELETE con CTE (WITH ...): el conteo
    # real se saca del informe antes/despues, que ademas es la verificacion.
    borradas = inf["candidatas"] - despues["candidatas"]
    print(f"Borradas {borradas} filas duplicadas (previsto {inf['a_borrar']}).")
    # Postcondicion REAL: las memorias del usuario quedaron intactas y sobrevive
    # una fila por texto sembrado.
    ok = (despues["no_seed"] == inf["no_seed"]
          and despues["candidatas"] == inf["distintas"]
          and despues["a_borrar"] == 0
          and borradas == inf["a_borrar"]
          and despues["label_sin_whitelist"] == inf["label_sin_whitelist"])
    print(f"CHECK memorias del usuario intactas: {inf['no_seed']} -> "
          f"{despues['no_seed']} | seed: {inf['candidatas']} -> "
          f"{despues['candidatas']} (esperado {inf['distintas']})")
    if not ok:
        print("AVISO: la postcondicion NO se cumplio. Backup disponible arriba.")
        return 1

    # VACUUM en conexion dedicada (checkpoint WAL incluido) para devolver
    # el espacio al filesystem; ~1.9 GB -> decenas de MB.
    from storage.db_pool import vacuum
    vacuum(DB_PATH)
    print("VACUUM completado.")
    # invalidar el cache persistido del VectorCache (quedo con las copias)
    base = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "vector_cache")
    for ruta in (base + ".npy", base + ".meta.json"):
        try:
            os.remove(ruta)
            print(f"Cache invalidado: {ruta}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
