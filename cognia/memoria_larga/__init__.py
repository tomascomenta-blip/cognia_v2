# -*- coding: utf-8 -*-
"""memoria_larga — memoria externa jerárquica + retrieval híbrido + context builder.

Convierte la ventana de ~60k del modelo en un WORKING SET dinámico: el historial
completo de una tarea vive FUERA de la conversación (SQLite propio con FTS5 +
vectores + relaciones), y cada llamada recibe solo lo necesario para continuar.

    historial → extracción → almacén (L0-L4) → retrieval híbrido → reranking
             → context builder (presupuestos) → contexto activo → LLM

Diseño (2026-09-04, tras auditar el arnés: scratchpad/auditoria_memoria/*.md):
- NO sustituye la compactación existente por otro resumen: cuando el contexto se
  acerca al límite se hace un REBUILD (extraer → guardar → checkpoint → limpiar →
  recuperar → reconstruir), y el prompt resultante es UN bloque construido +
  la cola reciente, con un solo splice (regla del prompt cache de llama.cpp).
- Reusa: `cognia.estado.canal` (L0/L1 verificado desde el disco),
  `cognia.agent.estado_tarea` + `bitacora` (durabilidad), `cognia.cognia_embedding`
  (MiniLM en CPU, perezoso), `harness/offloading` (texto completo de tools).
- Almacén PROPIO: `~/.cognia/memoria_larga.db` (WAL). No toca `cognia_memory.db`
  (39 tablas, ya explotó a 1,8 GB una vez; su pool tiene stalls documentados).
- Todo degrada avisando: sin embeddings → FTS5 solo; sin FTS5 → LIKE; sin DB →
  memoria en RAM de la sesión; sin checkpoint → volcado de emergencia a JSON.

CONTRATO (lo implementan los módulos hermanos; este fichero es la única fuente):

`Memoria` (dataclass, tabla `memorias`):
    id: int · tipo: str (uno de TIPOS) · nivel: int (0-4, ver NIVELES) ·
    contenido: str · resumen: str (≤200 chars, para el prompt) · fuente: str
    ('user'|'assistant'|'tool:<nombre>'|'sistema'|'modelo') · task_id: str ·
    session_id: str · paso: int · timestamp: float · importancia: int (1-5) ·
    confianza: float (0-1) · tags: list[str] · entidades: list[str] ·
    entidad: str (clave canónica para contradicciones, ej. 'base de datos') ·
    valor: str (ej. 'PostgreSQL') · estado: str ('vigente'|'superada'|'fusionada'|'descartada') ·
    valid_from: float · valid_until: float|None · supersedes: int|None ·
    superseded_by: int|None · referencias: list[str] (handles de offload, rutas, ids de mensaje) ·
    hash: str (sha1 del contenido normalizado) · tokens: int (estimados).

`Relacion` (tabla `relaciones`): origen_id, destino_id, tipo (RELACIONES), peso, timestamp.

`Almacen` (almacen.py):
    Almacen(ruta_db=None)                       -> abre/crea; ruta por defecto ~/.cognia/memoria_larga.db
    .guardar(memoria) -> int                    -> inserta (dedup ANTES: ver dedup.py), devuelve id
    .guardar_lote(memorias) -> list[int]
    .obtener(id) -> Memoria|None
    .buscar_lexico(consulta, task_id=None, tipos=None, limite=50, solo_vigentes=True) -> list[(Memoria, score_bm25)]
    .buscar_vector(vector, task_id=None, tipos=None, limite=50, solo_vigentes=True) -> list[(Memoria, cos)]
    .vector(id) / .guardar_vector(id, vector: list[float])   (BLOB float32, tabla `vectores`)
    .por_entidad(entidad, task_id=None) -> list[Memoria]     (vigentes primero)
    .relacionar(origen_id, destino_id, tipo, peso=1.0) / .vecinos(id, tipos=None, saltos=1) -> list[(Memoria, tipo, dist)]
    .actualizar(id, **campos) ; .superar(vieja_id, nueva_id)  (estado='superada', valid_until, supersedes/superseded_by + relación 'supersedes')
    .recientes(task_id, limite) ; .contar(task_id=None) -> dict por tipo/estado ; .estadisticas() -> dict
    .checkpoint_guardar(cp: dict) -> int ; .checkpoint_ultimo(task_id=None, cwd=None) ; .checkpoints(task_id) ; (tabla `checkpoints`)
    .cerrar()

`extraccion.py`:
    extraer(role, texto, *, tool=None, task_id, session_id, paso, ok=None) -> list[Memoria]
        Sin modelo. Reglas por tipo (decision, restriccion, error, solucion, hecho, codigo,
        fichero, test, objetivo, pendiente, nota) con importancia 1-5 según PRIORIDAD.
        Devuelve [] para relleno ("ok", "dale", listados sin señal). NUNCA lanza.
    extraer_simbolos(texto_resultado_leer_archivo) -> list[dict(nombre, clase, fichero, linea, firma, doc)]

`dedup.py`:
    es_duplicada(almacen, memoria, umbral_cos=0.92) -> Memoria|None   (hash exacto, luego FTS+cos)
    fusionar(almacen, existente, nueva) -> Memoria   (conserva referencias de ambas, sube confianza)

`contradicciones.py`:
    detectar(almacen, memoria) -> Memoria|None      (misma `entidad`+tipo, `valor` distinto, vigente)
    resolver(almacen, vieja, nueva) -> None          (superar; historial queda: vieja.estado='superada')
    historial(almacen, entidad, task_id=None) -> list[Memoria]  (cadena por supersedes, vieja→nueva)

`retrieval.py`:
    Recuperador(almacen, pesos=None)                 pesos: dict con PESOS_DEFECTO como base
    .buscar(consulta, *, task_id=None, intencion='', ficheros_abiertos=(), limite=12,
            presupuesto_tokens=None, explicar=False) -> Resultado
        Resultado: .memorias: list[Memoria], .candidatos: int, .seleccionados: int,
                   .explicaciones: dict[id -> dict(semantic, lexical, task, importance, recency,
                   confidence, graph, redundancy, contradiction, obsolescence, score)],
                   .tokens: int, .latencia_ms: float, .via: str ('hibrido'|'lexico'|'like')
    Combina: FTS5 (bm25) + coseno (si hay embeddings) + filtros (task_id, vigentes) +
    grafo (1 salto por 'supersedes'/'caused_by'/'modifies') + reranker con `pesos`;
    resta redundancia (MMR contra ya seleccionadas), contradicción (superadas fuera
    salvo que se pidan) y obsolescencia (valid_until pasado).
    .embeber(textos) -> list[list[float]]|None  (perezoso; cache persistente en tabla `vectores`)

PESOS_DEFECTO: ver la constante (medidos con scripts/memoria_larga/optimizar_pesos.py).

Los módulos que quedan a cargo del integrador: contexto.py (ContextManager/builder),
checkpoint.py, recuperacion.py, observabilidad.py, y el cableado en agent/loop.py y cli.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import time

TIPOS = ("objetivo", "decision", "restriccion", "error", "solucion", "hecho", "codigo",
         "fichero", "test", "pendiente", "nota", "estado")
NIVELES = {0: "working", 1: "task", 2: "episodic", 3: "semantic", 4: "project"}
NIVEL_POR_TIPO = {"objetivo": 1, "pendiente": 1, "estado": 1, "decision": 2, "restriccion": 1,
                  "error": 2, "solucion": 2, "test": 2, "fichero": 2, "nota": 2,
                  "hecho": 3, "codigo": 4}
RELACIONES = ("supersedes", "caused_by", "solves", "modifies", "contains", "uses",
              "depends_on", "related_to")
PRIORIDAD = {5: "requisitos, decisiones críticas, arquitectura, restricciones, hechos esenciales",
             4: "resultados importantes, errores importantes, soluciones",
             3: "información útil", 2: "secundaria", 1: "redundante o temporal"}
# PESOS MEDIDOS (scripts/memoria_larga/optimizar_pesos.py, 2026-09-04): media de los
# optimos de dos semillas, elegida por ser la unica con recall 1,0 en los CUATRO
# datasets (100k s7, 100k s13, 300k s21, 1M s7): objetivo medio 1,10 frente a 0,98
# de los pesos de partida (semantic .30/lexical .25/...). El optimo de una sola
# semilla sobreajusta (s7 pierde recall en s13). Se re-optimizan con el banco.
PESOS_DEFECTO = {"semantic": 0.107, "lexical": 0.245, "task": 0.036, "importance": 0.208,
                 "recency": 0.096, "confidence": 0.075, "graph": 0.152, "type_match": 0.11,
                 "redundancy": -0.234, "contradiction": -0.487, "obsolescence": -0.221}
# `type_match` (añadido tras el banco 2026-09-04): la consulta nombra el TIPO de
# memoria ("¿qué restricciones...?", "¿cómo funciona la función...?"); casarlo
# con `Memoria.tipo` es la señal de metadata más barata y la que más recall daba.
TIPO_POR_PALABRA = {
    "restriccion": ("restric", "prohib", "nunca", "no negociable", "jamás", "jamas", "regla"),
    "decision": ("decisi", "decid", "elegi", "usamos", "arquitectura", "adopt"),
    "error": ("error", "fall", "excepci", "traceback", "bug", "rompi"),
    "solucion": ("soluci", "resolv", "arregl", "fix"),
    "codigo": ("funcion", "función", "def ", "clase", "cómo funciona", "como funciona", "método", "metodo", "símbolo"),
    "pendiente": ("pendiente", "falta", "próximo paso", "proximo paso", "todo"),
    "objetivo": ("objetivo", "tarea original", "qué pediste", "que pediste"),
}
ENV_ACTIVO = "COGNIA_MEMORIA_LARGA"


@dataclass
class Memoria:
    tipo: str
    contenido: str
    id: int | None = None
    nivel: int = 2
    resumen: str = ""
    fuente: str = "sistema"
    task_id: str = ""
    session_id: str = ""
    paso: int = 0
    timestamp: float = field(default_factory=time.time)
    importancia: int = 3
    confianza: float = 0.7
    tags: list = field(default_factory=list)
    entidades: list = field(default_factory=list)
    entidad: str = ""
    valor: str = ""
    estado: str = "vigente"
    valid_from: float = field(default_factory=time.time)
    valid_until: float | None = None
    supersedes: int | None = None
    superseded_by: int | None = None
    referencias: list = field(default_factory=list)
    hash: str = ""
    tokens: int = 0

    def a_dict(self) -> dict:
        return asdict(self)

    def linea(self) -> str:
        """Una línea para el prompt: tipo, resumen (o contenido corto), entidad=valor."""
        base = self.resumen or self.contenido[:200].replace("\n", " ")
        ev = f" [{self.entidad} = {self.valor}]" if self.entidad and self.valor else ""
        return f"- ({self.tipo}, imp {self.importancia}) {base}{ev}"


@dataclass
class Relacion:
    origen_id: int
    destino_id: int
    tipo: str
    peso: float = 1.0
    timestamp: float = field(default_factory=time.time)


def activo() -> bool:
    import os
    return os.environ.get(ENV_ACTIVO, "1").strip().lower() not in ("0", "no", "off", "false")


def herramienta_buscar(args: str, ctx: dict) -> str:
    """La tool `memoria_buscar` del modelo (implementada en cli.py para no cargar nada al importar)."""
    from cognia.memoria_larga.cli import herramienta_buscar as _hb
    return _hb(args, ctx)


__all__ = ["Memoria", "Relacion", "TIPOS", "NIVELES", "NIVEL_POR_TIPO", "RELACIONES",
           "PRIORIDAD", "PESOS_DEFECTO", "TIPO_POR_PALABRA", "ENV_ACTIVO", "activo", "herramienta_buscar"]
