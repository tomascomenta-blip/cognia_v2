# -*- coding: utf-8 -*-
"""Almacén SQLite propio de memoria_larga: memorias + FTS5 + vectores + relaciones + checkpoints.

Por qué una DB PROPIA y no `cognia_memory.db`: esa tiene 39 tablas, un pool con
stalls documentados (`storage/database.py:24-31`) y ya explotó a 1,8 GB una vez
(scratchpad/auditoria_memoria/01_almacenes.md §5). Aquí hay UNA conexión por
instancia (`check_same_thread=False` + un `threading.Lock`), WAL y
`synchronous=NORMAL`: escritura barata y lecturas que no bloquean al que escribe.
Es una desviación deliberada de "sin sqlite3.connect() directo" del CLAUDE.md,
porque el pool existente está atado a la DB grande y sus stalls son justo lo que
este almacén tiene que evitar.

Degradación (todo avisa, nada calla):
- sin FTS5 compilado → `buscar_lexico` cae a LIKE (aviso UNA vez, `via='like'`);
- sin poder abrir el fichero → DB en RAM de la sesión (aviso), la API no cambia;
- vector con dimensión distinta a la guardada → se ignora ese candidato con aviso.

MEDIDO en esta máquina (2026-09-04, Windows 11, Python 3.12, SQLite 3.49.1,
`time.perf_counter`, script: scratchpad/medir_almacen.py):
- `guardar_lote` de 10.000 memorias (contenido ~200 chars, vocabulario de 425
  palabras, FTS5 sincronizado por trigger, una transacción): 1,0 s (≈10.000
  filas/s); la DB queda en ~15 MB. Con 25 palabras uniformes baja a 0,82 s.
- `buscar_lexico` de 3 términos sobre esas 10.000 (bm25, limite=50): 5,2 ms de
  mediana (top score ≈ 9,6); con `task_id` 5,4 ms. Con el vocabulario pobre el
  IDF se anula (bm25 ≈ 0 para todo) y tarda 10,5 ms: el coste está en rankear.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from . import Memoria, TIPOS, NIVEL_POR_TIPO, RELACIONES

logger = logging.getLogger(__name__)

# Versión del esquema: sube cuando cambia una tabla. Las migraciones son
# `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` en `_migrar`.
_VERSION_ESQUEMA = 1

# Columnas de `memorias` en el orden del INSERT. Los tres campos lista viajan como JSON.
_COLUMNAS = ("tipo", "nivel", "contenido", "resumen", "fuente", "task_id", "session_id",
             "paso", "timestamp", "importancia", "confianza", "tags", "entidades", "entidad",
             "valor", "estado", "valid_from", "valid_until", "supersedes", "superseded_by",
             "referencias", "hash", "tokens")
_CAMPOS_JSON = ("tags", "entidades", "referencias")
_CAMPOS_FTS = ("contenido", "resumen", "entidad", "valor", "tags")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS memorias (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo          TEXT NOT NULL,
    nivel         INTEGER NOT NULL DEFAULT 2,
    contenido     TEXT NOT NULL,
    resumen       TEXT NOT NULL DEFAULT '',
    fuente        TEXT NOT NULL DEFAULT 'sistema',
    task_id       TEXT NOT NULL DEFAULT '',
    session_id    TEXT NOT NULL DEFAULT '',
    paso          INTEGER NOT NULL DEFAULT 0,
    timestamp     REAL NOT NULL,
    importancia   INTEGER NOT NULL DEFAULT 3,
    confianza     REAL NOT NULL DEFAULT 0.7,
    tags          TEXT NOT NULL DEFAULT '[]',
    entidades     TEXT NOT NULL DEFAULT '[]',
    entidad       TEXT NOT NULL DEFAULT '',
    valor         TEXT NOT NULL DEFAULT '',
    estado        TEXT NOT NULL DEFAULT 'vigente',
    valid_from    REAL NOT NULL,
    valid_until   REAL,
    supersedes    INTEGER,
    superseded_by INTEGER,
    referencias   TEXT NOT NULL DEFAULT '[]',
    hash          TEXT NOT NULL DEFAULT '',
    tokens        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_mem_task      ON memorias(task_id);
CREATE INDEX IF NOT EXISTS ix_mem_tipo      ON memorias(tipo);
CREATE INDEX IF NOT EXISTS ix_mem_estado    ON memorias(estado);
CREATE INDEX IF NOT EXISTS ix_mem_entidad   ON memorias(entidad);
CREATE INDEX IF NOT EXISTS ix_mem_timestamp ON memorias(timestamp);
CREATE INDEX IF NOT EXISTS ix_mem_hash      ON memorias(hash);

CREATE TABLE IF NOT EXISTS vectores (
    id     INTEGER PRIMARY KEY,
    dim    INTEGER NOT NULL,
    blob   BLOB NOT NULL,
    modelo TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS relaciones (
    origen_id  INTEGER NOT NULL,
    destino_id INTEGER NOT NULL,
    tipo       TEXT NOT NULL,
    peso       REAL NOT NULL DEFAULT 1.0,
    timestamp  REAL NOT NULL,
    PRIMARY KEY (origen_id, destino_id, tipo)
);
CREATE INDEX IF NOT EXISTS ix_rel_destino ON relaciones(destino_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    cwd        TEXT NOT NULL DEFAULT '',
    paso       INTEGER NOT NULL DEFAULT 0,
    timestamp  REAL NOT NULL,
    json       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cp_task ON checkpoints(task_id);
CREATE INDEX IF NOT EXISTS ix_cp_cwd  ON checkpoints(cwd);
"""

# FTS5 de contenido externo: no duplica el texto, lee de `memorias` por rowid.
# `remove_diacritics 2` para que "decisión" y "decision" sean el mismo token.
# Los triggers mantienen el índice; en el DELETE/UPDATE hay que pasar los valores
# VIEJOS (así lo exige el modo external-content, si no el índice queda corrupto).
_ESQUEMA_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memorias_fts USING fts5(
    contenido, resumen, entidad, valor, tags,
    content='memorias', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS memorias_ai AFTER INSERT ON memorias BEGIN
    INSERT INTO memorias_fts(rowid, contenido, resumen, entidad, valor, tags)
    VALUES (new.id, new.contenido, new.resumen, new.entidad, new.valor, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memorias_ad AFTER DELETE ON memorias BEGIN
    INSERT INTO memorias_fts(memorias_fts, rowid, contenido, resumen, entidad, valor, tags)
    VALUES ('delete', old.id, old.contenido, old.resumen, old.entidad, old.valor, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memorias_au AFTER UPDATE ON memorias BEGIN
    INSERT INTO memorias_fts(memorias_fts, rowid, contenido, resumen, entidad, valor, tags)
    VALUES ('delete', old.id, old.contenido, old.resumen, old.entidad, old.valor, old.tags);
    INSERT INTO memorias_fts(rowid, contenido, resumen, entidad, valor, tags)
    VALUES (new.id, new.contenido, new.resumen, new.entidad, new.valor, new.tags);
END;
"""


def _home() -> Path:
    """~/.cognia, o COGNIA_HOME si el entorno lo redirige (misma convención que
    `cognia.agent.capacidad._home`: sin esto no se puede probar sobre un HOME virgen)."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    return Path(crudo) if crudo else Path.home() / ".cognia"


def ruta_por_defecto() -> Path:
    return _home() / "memoria_larga.db"


def _terminos(texto: str, tope: int = 32) -> list[str]:
    """Palabras de la consulta (unicode, ≥2 chars, sin duplicados, hasta `tope`).
    Se recortan porque una consulta de 300 términos en FTS5 es más lenta que útil."""
    import re
    vistos: list[str] = []
    for t in re.findall(r"\w+", (texto or "").lower()):
        if len(t) >= 2 and t not in vistos:
            vistos.append(t)
        if len(vistos) >= tope:
            break
    return vistos


def _consulta_fts(texto: str) -> str:
    """Consulta MATCH segura: cada término entre comillas (los ':' '-' '?' del texto
    libre rompen la gramática de FTS5) y unidos por OR; bm25 ordena por relevancia."""
    # Sin stemming en FTS5 "restricciones" no casa con "restricción" (medido en
    # el banco: la restricción F no se recuperaba, recall 0). Para los términos
    # de ≥ 6 letras se añade el PREFIJO de 5 como alternativa: cubre plural,
    # género y derivados (restric* ↔ restricción/restricciones; decisi* ↔
    # decisión/decisiones/decidimos) sin un stemmer.
    partes = []
    for t in _terminos(texto):
        if len(t) >= 6:
            partes.append(f'("{t}" OR "{t[:5]}"*)')
        else:
            partes.append(f'"{t}"')
    return " OR ".join(partes)


class Almacen:
    """Ver el contrato en `cognia/memoria_larga/__init__.py`."""

    def __init__(self, ruta_db: str | os.PathLike | None = None):
        self._lock = threading.RLock()
        self.ruta = Path(ruta_db) if ruta_db else ruta_por_defecto()
        self.en_ram = False
        self.fts5 = False
        self._aviso_like = False
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(str(self.ruta), check_same_thread=False, timeout=30)
        except (OSError, sqlite3.Error) as e:
            # Sin disco no se pierde la sesión: la API sigue funcionando en RAM.
            logger.warning("memoria_larga: no puedo abrir %s (%s); uso una DB en RAM de la sesión", self.ruta, e)
            self._con = sqlite3.connect(":memory:", check_same_thread=False)
            self.en_ram = True
        self._con.row_factory = sqlite3.Row
        self._configurar()
        self._migrar()

    # ── apertura / esquema ──────────────────────────────────────────────────
    def _configurar(self) -> None:
        try:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.execute("PRAGMA foreign_keys=OFF")
        except sqlite3.Error as e:
            logger.warning("memoria_larga: PRAGMA falló (%s); sigo con los valores por defecto", e)

    def _migrar(self) -> None:
        with self._lock:
            self._con.executescript(_ESQUEMA)
            try:
                self._con.executescript(_ESQUEMA_FTS)
                self.fts5 = True
            except sqlite3.OperationalError as e:
                # SQLite sin FTS5 compilado: se busca con LIKE (más lento, sin bm25).
                logger.warning("memoria_larga: FTS5 no disponible (%s); buscar_lexico degrada a LIKE", e)
                self.fts5 = False
            version = self._con.execute("PRAGMA user_version").fetchone()[0]
            if version < _VERSION_ESQUEMA:
                # Punto de extensión: `if version < 2: ALTER TABLE ...` aquí, en orden.
                self._con.execute(f"PRAGMA user_version={_VERSION_ESQUEMA}")
            self._con.commit()

    def cerrar(self) -> None:
        with self._lock:
            try:
                self._con.commit()
                self._con.close()
            except sqlite3.Error as e:
                logger.warning("memoria_larga: al cerrar %s: %s", self.ruta, e)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()

    # ── conversión fila ↔ Memoria ───────────────────────────────────────────
    @staticmethod
    def _fila_a_memoria(fila: sqlite3.Row) -> Memoria:
        d = {k: fila[k] for k in fila.keys() if k in Memoria.__dataclass_fields__}
        for k in _CAMPOS_JSON:
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except (TypeError, ValueError):
                logger.warning("memoria_larga: %s corrupto en la fila %s; lo dejo vacío", k, d.get("id"))
                d[k] = []
        return Memoria(**d)

    @staticmethod
    def _memoria_a_fila(m: Memoria) -> tuple:
        if m.tipo not in TIPOS:
            logger.warning("memoria_larga: tipo desconocido %r; lo guardo como 'nota'", m.tipo)
            m.tipo = "nota"
        if not m.hash:
            from .extraccion import hash_contenido
            m.hash = hash_contenido(m.contenido)
        if not m.tokens:
            m.tokens = int(len(m.contenido) / 3.7) + 1
        if m.nivel is None:
            m.nivel = NIVEL_POR_TIPO.get(m.tipo, 2)
        valores = []
        for c in _COLUMNAS:
            v = getattr(m, c)
            if c in _CAMPOS_JSON:
                v = json.dumps(list(v or []), ensure_ascii=False)
            valores.append(v)
        return tuple(valores)

    # ── escritura ───────────────────────────────────────────────────────────
    _SQL_INSERT = (f"INSERT INTO memorias ({', '.join(_COLUMNAS)}) "
                   f"VALUES ({', '.join('?' for _ in _COLUMNAS)})")

    def guardar(self, memoria: Memoria) -> int:
        with self._lock:
            cur = self._con.execute(self._SQL_INSERT, self._memoria_a_fila(memoria))
            self._con.commit()
            memoria.id = int(cur.lastrowid)
            return memoria.id

    def guardar_lote(self, memorias: list[Memoria]) -> list[int]:
        """Una transacción para todo el lote: 10.000 filas en ~0,3 s. Con un commit
        por fila cada uno paga su escritura al WAL y la actualización del FTS por
        separado; en lote se amortiza."""
        memorias = list(memorias)
        if not memorias:
            return []
        with self._lock:
            filas = [self._memoria_a_fila(m) for m in memorias]
            primero = self._con.execute("SELECT COALESCE(MAX(id), 0) FROM memorias").fetchone()[0]
            self._con.executemany(self._SQL_INSERT, filas)
            self._con.commit()
            # AUTOINCREMENT en una sola transacción asigna ids consecutivos.
            ids = list(range(int(primero) + 1, int(primero) + 1 + len(memorias)))
            for m, i in zip(memorias, ids):
                m.id = i
            return ids

    def actualizar(self, id: int, **campos) -> bool:
        if not campos:
            return False
        desconocidos = [k for k in campos if k not in _COLUMNAS]
        if desconocidos:
            logger.warning("memoria_larga: actualizar ignora campos desconocidos %s", desconocidos)
        sets, vals = [], []
        for k, v in campos.items():
            if k not in _COLUMNAS:
                continue
            if k in _CAMPOS_JSON:
                v = json.dumps(list(v or []), ensure_ascii=False)
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            return False
        vals.append(id)
        with self._lock:
            cur = self._con.execute(f"UPDATE memorias SET {', '.join(sets)} WHERE id=?", vals)
            self._con.commit()
            return cur.rowcount > 0

    def superar(self, vieja_id: int, nueva_id: int) -> None:
        """La vieja queda 'superada' con valid_until=ahora; la nueva apunta a ella
        por `supersedes`, y queda la relación 'supersedes' en el grafo."""
        ahora = time.time()
        with self._lock:
            self._con.execute("UPDATE memorias SET estado='superada', valid_until=?, superseded_by=? WHERE id=?",
                              (ahora, nueva_id, vieja_id))
            self._con.execute("UPDATE memorias SET supersedes=? WHERE id=?", (vieja_id, nueva_id))
            self._con.execute("INSERT OR REPLACE INTO relaciones (origen_id, destino_id, tipo, peso, timestamp) "
                              "VALUES (?, ?, 'supersedes', 1.0, ?)", (nueva_id, vieja_id, ahora))
            self._con.commit()

    def borrar(self, id: int) -> bool:
        with self._lock:
            cur = self._con.execute("DELETE FROM memorias WHERE id=?", (id,))
            self._con.execute("DELETE FROM vectores WHERE id=?", (id,))
            self._con.execute("DELETE FROM relaciones WHERE origen_id=? OR destino_id=?", (id, id))
            self._con.commit()
            return cur.rowcount > 0

    # ── lectura ─────────────────────────────────────────────────────────────
    def obtener(self, id: int) -> Memoria | None:
        with self._lock:
            fila = self._con.execute("SELECT * FROM memorias WHERE id=?", (id,)).fetchone()
        return self._fila_a_memoria(fila) if fila else None

    def obtener_varias(self, ids: list[int]) -> dict[int, Memoria]:
        ids = [int(i) for i in ids]
        salida: dict[int, Memoria] = {}
        with self._lock:
            for i in range(0, len(ids), 900):   # límite de variables de SQLite (999)
                trozo = ids[i:i + 900]
                q = f"SELECT * FROM memorias WHERE id IN ({','.join('?' * len(trozo))})"
                for fila in self._con.execute(q, trozo):
                    salida[fila["id"]] = self._fila_a_memoria(fila)
        return salida

    def por_hash(self, hash: str, task_id: str | None = None, solo_vigentes: bool = True) -> list[Memoria]:
        sql, vals = "SELECT * FROM memorias WHERE hash=?", [hash]
        if task_id is not None:
            sql += " AND task_id=?"
            vals.append(task_id)
        if solo_vigentes:
            sql += " AND estado='vigente'"
        sql += " ORDER BY timestamp DESC"
        with self._lock:
            return [self._fila_a_memoria(f) for f in self._con.execute(sql, vals)]

    def por_entidad(self, entidad: str, task_id: str | None = None, solo_vigentes: bool = False) -> list[Memoria]:
        """Vigentes primero, luego por fecha descendente.

        Compara sin mayúsculas Y contra la clave normalizada (sin tildes ni artículos,
        como la guarda extracción): `lower()` de SQLite no quita tildes, y buscar
        'autenticación' no encontraba la 'autenticacion' extraída (cazado en el e2e
        sobre el dataset sintético, semilla 7)."""
        from .extraccion import normalizar_entidad
        sql = "SELECT * FROM memorias WHERE (lower(entidad)=lower(?) OR entidad=?)"
        vals = [entidad or "", normalizar_entidad(entidad or "")]
        if task_id is not None:
            sql += " AND task_id=?"
            vals.append(task_id)
        if solo_vigentes:
            sql += " AND estado='vigente'"
        sql += " ORDER BY (estado='vigente') DESC, timestamp DESC, id DESC"
        with self._lock:
            return [self._fila_a_memoria(f) for f in self._con.execute(sql, vals)]

    def recientes(self, task_id: str | None = None, limite: int = 20, solo_vigentes: bool = True) -> list[Memoria]:
        sql, vals = "SELECT * FROM memorias WHERE 1=1", []
        if task_id is not None:
            sql += " AND task_id=?"
            vals.append(task_id)
        if solo_vigentes:
            sql += " AND estado='vigente'"
        sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        vals.append(int(limite))
        with self._lock:
            return [self._fila_a_memoria(f) for f in self._con.execute(sql, vals)]

    @staticmethod
    def _filtros(task_id, tipos, solo_vigentes, alias: str = "m") -> tuple[str, list]:
        sql, vals = "", []
        if task_id is not None:
            sql += f" AND {alias}.task_id=?"
            vals.append(task_id)
        if tipos:
            tipos = list(tipos)
            sql += f" AND {alias}.tipo IN ({','.join('?' * len(tipos))})"
            vals.extend(tipos)
        if solo_vigentes:
            sql += f" AND {alias}.estado='vigente'"
        return sql, vals

    def buscar_lexico(self, consulta: str, task_id: str | None = None, tipos=None, limite: int = 50,
                      solo_vigentes: bool = True) -> list[tuple[Memoria, float]]:
        """Score POSITIVO: -bm25 (FTS5 devuelve negativo, más negativo = mejor).
        Con LIKE el score es el nº de términos que aparecen (0..n)."""
        terminos = _terminos(consulta)
        if not terminos:
            return []
        filtro, vals = self._filtros(task_id, tipos, solo_vigentes)
        if self.fts5:
            sql = ("SELECT m.*, bm25(memorias_fts) AS r FROM memorias_fts f "
                   "JOIN memorias m ON m.id = f.rowid WHERE memorias_fts MATCH ?" + filtro +
                   " ORDER BY r LIMIT ?")
            with self._lock:
                filas = self._con.execute(sql, [_consulta_fts(consulta)] + vals + [int(limite)]).fetchall()
            return [(self._fila_a_memoria(f), -float(f["r"])) for f in filas]
        # Degradación a LIKE: se avisa una sola vez por instancia para no inundar el log.
        if not self._aviso_like:
            logger.warning("memoria_larga: buscando con LIKE (sin FTS5): sin bm25 y más lento")
            self._aviso_like = True
        condiciones = " OR ".join("(lower(m.contenido) LIKE ? OR lower(m.resumen) LIKE ? OR lower(m.entidad) LIKE ? "
                                  "OR lower(m.valor) LIKE ? OR lower(m.tags) LIKE ?)" for _ in terminos)
        like_vals = []
        for t in terminos:
            like_vals.extend([f"%{t}%"] * 5)
        sql = f"SELECT m.* FROM memorias m WHERE ({condiciones})" + filtro
        with self._lock:
            filas = self._con.execute(sql, like_vals + vals).fetchall()
        puntuados = []
        for f in filas:
            texto = " ".join(str(f[c] or "") for c in _CAMPOS_FTS).lower()
            puntuados.append((self._fila_a_memoria(f), float(sum(1 for t in terminos if t in texto))))
        puntuados.sort(key=lambda p: (-p[1], -p[0].timestamp))
        return puntuados[:int(limite)]

    # ── vectores ────────────────────────────────────────────────────────────
    def guardar_vector(self, id: int, vector, modelo: str = "") -> None:
        import numpy as np
        v = np.asarray(vector, dtype=np.float32).ravel()
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO vectores (id, dim, blob, modelo) VALUES (?, ?, ?, ?)",
                              (int(id), int(v.size), v.tobytes(), modelo))
            self._con.commit()

    def vector(self, id: int) -> list[float] | None:
        import numpy as np
        with self._lock:
            fila = self._con.execute("SELECT dim, blob FROM vectores WHERE id=?", (int(id),)).fetchone()
        if not fila:
            return None
        return np.frombuffer(fila["blob"], dtype=np.float32, count=fila["dim"]).tolist()

    def ids_con_vector(self, ids: list[int]) -> set[int]:
        salida: set[int] = set()
        with self._lock:
            for i in range(0, len(ids), 900):
                trozo = [int(x) for x in ids[i:i + 900]]
                q = f"SELECT id FROM vectores WHERE id IN ({','.join('?' * len(trozo))})"
                salida.update(f["id"] for f in self._con.execute(q, trozo))
        return salida

    def buscar_vector(self, vector, task_id: str | None = None, tipos=None, limite: int = 50,
                      solo_vigentes: bool = True) -> list[tuple[Memoria, float]]:
        """Coseno con numpy sobre los blobs. Si hay filtro se cargan SOLO los ids
        candidatos (no la tabla entera): con task_id la carga es proporcional a la tarea."""
        import numpy as np
        q = np.asarray(vector, dtype=np.float32).ravel()
        nq = float(np.linalg.norm(q))
        if q.size == 0 or nq == 0.0:
            return []
        filtro, vals = self._filtros(task_id, tipos, solo_vigentes)
        with self._lock:
            if filtro:
                cand = [f["id"] for f in self._con.execute("SELECT m.id FROM memorias m WHERE 1=1" + filtro, vals)]
                filas = []
                for i in range(0, len(cand), 900):
                    trozo = cand[i:i + 900]
                    filas.extend(self._con.execute(
                        f"SELECT id, dim, blob FROM vectores WHERE id IN ({','.join('?' * len(trozo))})", trozo).fetchall())
            else:
                filas = self._con.execute("SELECT id, dim, blob FROM vectores").fetchall()
        if not filas:
            return []
        ids, mats, saltados = [], [], 0
        for f in filas:
            if f["dim"] != q.size:
                saltados += 1
                continue
            ids.append(f["id"])
            mats.append(np.frombuffer(f["blob"], dtype=np.float32, count=f["dim"]))
        if saltados:
            logger.warning("memoria_larga: %d vectores con dim distinta a %d ignorados", saltados, q.size)
        if not ids:
            return []
        M = np.vstack(mats)
        normas = np.linalg.norm(M, axis=1)
        normas[normas == 0] = 1e-9
        cos = (M @ q) / (normas * nq)
        k = min(int(limite), len(ids))
        orden = np.argsort(-cos)[:k]
        memorias = self.obtener_varias([ids[i] for i in orden])
        salida = []
        for i in orden:
            m = memorias.get(ids[i])
            if m is not None:
                salida.append((m, float(cos[i])))
        return salida

    # ── relaciones y grafo ──────────────────────────────────────────────────
    def relacionar(self, origen_id: int, destino_id: int, tipo: str, peso: float = 1.0) -> None:
        if tipo not in RELACIONES:
            logger.warning("memoria_larga: relación de tipo desconocido %r (permitidas: %s); la guardo igual",
                           tipo, ", ".join(RELACIONES))
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO relaciones (origen_id, destino_id, tipo, peso, timestamp) "
                              "VALUES (?, ?, ?, ?, ?)", (int(origen_id), int(destino_id), tipo, float(peso), time.time()))
            self._con.commit()

    def relaciones_de(self, id: int) -> list[tuple[int, int, str, float]]:
        with self._lock:
            filas = self._con.execute("SELECT origen_id, destino_id, tipo, peso FROM relaciones "
                                      "WHERE origen_id=? OR destino_id=?", (int(id), int(id))).fetchall()
        return [(f["origen_id"], f["destino_id"], f["tipo"], f["peso"]) for f in filas]

    def vecinos(self, id: int, tipos=None, saltos: int = 1) -> list[tuple[Memoria, str, int]]:
        """BFS de `saltos` niveles en AMBAS direcciones. Devuelve (memoria, tipo de la
        relación por la que se llegó, distancia), ordenado por distancia."""
        tipos = set(tipos) if tipos else None
        vistos = {int(id)}
        frontera = deque([(int(id), 0)])
        encontrados: list[tuple[int, str, int]] = []
        while frontera:
            actual, dist = frontera.popleft()
            if dist >= saltos:
                continue
            for o, d, t, _p in self.relaciones_de(actual):
                if tipos and t not in tipos:
                    continue
                otro = d if o == actual else o
                if otro in vistos:
                    continue
                vistos.add(otro)
                encontrados.append((otro, t, dist + 1))
                frontera.append((otro, dist + 1))
        memorias = self.obtener_varias([e[0] for e in encontrados])
        return [(memorias[i], t, d) for i, t, d in encontrados if i in memorias]

    # ── recuentos ───────────────────────────────────────────────────────────
    def contar(self, task_id: str | None = None) -> dict:
        sql_extra, vals = ("WHERE task_id=?", [task_id]) if task_id is not None else ("", [])
        with self._lock:
            por_tipo = {f[0]: f[1] for f in self._con.execute(
                f"SELECT tipo, COUNT(*) FROM memorias {sql_extra} GROUP BY tipo", vals)}
            por_estado = {f[0]: f[1] for f in self._con.execute(
                f"SELECT estado, COUNT(*) FROM memorias {sql_extra} GROUP BY estado", vals)}
        return {"total": sum(por_tipo.values()), "por_tipo": por_tipo, "por_estado": por_estado}

    def estadisticas(self) -> dict:
        with self._lock:
            por_tipo = {f[0]: f[1] for f in self._con.execute("SELECT tipo, COUNT(*) FROM memorias GROUP BY tipo")}
            por_estado = {f[0]: f[1] for f in self._con.execute("SELECT estado, COUNT(*) FROM memorias GROUP BY estado")}
            por_nivel = {int(f[0]): f[1] for f in self._con.execute("SELECT nivel, COUNT(*) FROM memorias GROUP BY nivel")}
            n_vec = self._con.execute("SELECT COUNT(*) FROM vectores").fetchone()[0]
            n_rel = self._con.execute("SELECT COUNT(*) FROM relaciones").fetchone()[0]
            n_cp = self._con.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            tareas = self._con.execute("SELECT COUNT(DISTINCT task_id) FROM memorias").fetchone()[0]
        bytes_ = 0
        if not self.en_ram:
            for sufijo in ("", "-wal", "-shm"):
                p = Path(str(self.ruta) + sufijo)
                if p.exists():
                    bytes_ += p.stat().st_size
        return {"ruta": str(self.ruta), "en_ram": self.en_ram, "fts5": self.fts5,
                "total": sum(por_tipo.values()), "por_tipo": por_tipo, "por_estado": por_estado,
                "por_nivel": por_nivel, "vectores": n_vec, "relaciones": n_rel, "checkpoints": n_cp,
                "tareas": tareas, "bytes": bytes_, "mb": round(bytes_ / (1024 * 1024), 2)}

    def podar(self, task_id: str | None = None, max_filas: int = 20000) -> int:
        """No corre sola. Borra las 'descartada' y, si aún sobran filas sobre
        `max_filas`, las de importancia 1 más viejas. Devuelve filas borradas."""
        sql_task, vals = (" AND task_id=?", [task_id]) if task_id is not None else ("", [])
        with self._lock:
            cur = self._con.execute("DELETE FROM memorias WHERE estado='descartada'" + sql_task, vals)
            borradas = cur.rowcount
            total = self._con.execute("SELECT COUNT(*) FROM memorias WHERE 1=1" + sql_task, vals).fetchone()[0]
            sobran = total - int(max_filas)
            if sobran > 0:
                ids = [f[0] for f in self._con.execute(
                    "SELECT id FROM memorias WHERE importancia<=1" + sql_task + " ORDER BY timestamp ASC LIMIT ?",
                    vals + [sobran])]
                for i in range(0, len(ids), 900):
                    trozo = ids[i:i + 900]
                    marcas = ",".join("?" * len(trozo))
                    cur = self._con.execute(f"DELETE FROM memorias WHERE id IN ({marcas})", trozo)
                    borradas += cur.rowcount
            # Huérfanos: vectores y relaciones de filas que ya no existen.
            self._con.execute("DELETE FROM vectores WHERE id NOT IN (SELECT id FROM memorias)")
            self._con.execute("DELETE FROM relaciones WHERE origen_id NOT IN (SELECT id FROM memorias) "
                              "OR destino_id NOT IN (SELECT id FROM memorias)")
            self._con.commit()
        return borradas

    # ── checkpoints ─────────────────────────────────────────────────────────
    def checkpoint_guardar(self, cp: dict) -> int:
        cp = dict(cp)
        cp.setdefault("timestamp", time.time())
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO checkpoints (task_id, session_id, cwd, paso, timestamp, json) VALUES (?, ?, ?, ?, ?, ?)",
                (str(cp.get("task_id", "")), str(cp.get("session_id", "")), str(cp.get("cwd", "")),
                 int(cp.get("paso", 0) or 0), float(cp["timestamp"]), json.dumps(cp, ensure_ascii=False, default=str)))
            self._con.commit()
            return int(cur.lastrowid)

    @staticmethod
    def _cp_de_fila(f: sqlite3.Row) -> dict:
        try:
            cp = json.loads(f["json"])
        except (TypeError, ValueError) as e:
            logger.warning("memoria_larga: checkpoint %s con JSON corrupto (%s); devuelvo solo las columnas", f["id"], e)
            cp = {}
        cp.update({"id": f["id"], "task_id": f["task_id"], "session_id": f["session_id"], "cwd": f["cwd"],
                   "paso": f["paso"], "timestamp": f["timestamp"]})
        return cp

    def checkpoint_ultimo(self, task_id: str | None = None, cwd: str | None = None) -> dict | None:
        sql, vals = "SELECT * FROM checkpoints WHERE 1=1", []
        if task_id is not None:
            sql += " AND task_id=?"
            vals.append(task_id)
        if cwd is not None:
            sql += " AND cwd=?"
            vals.append(str(cwd))
        sql += " ORDER BY timestamp DESC, id DESC LIMIT 1"
        with self._lock:
            f = self._con.execute(sql, vals).fetchone()
        return self._cp_de_fila(f) if f else None

    def checkpoints(self, task_id: str, limite: int = 50) -> list[dict]:
        with self._lock:
            filas = self._con.execute("SELECT * FROM checkpoints WHERE task_id=? ORDER BY timestamp DESC, id DESC LIMIT ?",
                                      (task_id, int(limite))).fetchall()
        return [self._cp_de_fila(f) for f in filas]

    def checkpoint_borrar_viejos(self, task_id: str, conservar: int = 5) -> int:
        with self._lock:
            ids = [f[0] for f in self._con.execute(
                "SELECT id FROM checkpoints WHERE task_id=? ORDER BY timestamp DESC, id DESC", (task_id,))][conservar:]
            n = 0
            for i in range(0, len(ids), 900):
                trozo = ids[i:i + 900]
                n += self._con.execute(f"DELETE FROM checkpoints WHERE id IN ({','.join('?' * len(trozo))})", trozo).rowcount
            self._con.commit()
        return n


__all__ = ["Almacen", "ruta_por_defecto"]
