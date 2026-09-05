# -*- coding: utf-8 -*-
"""retrieval.py — retrieval híbrido de memoria_larga (contrato en __init__.py).

    Recuperador(almacen, pesos=None, embebedor=None)
    .buscar(consulta, *, task_id=None, intencion='', ficheros_abiertos=(), limite=12,
            presupuesto_tokens=None, explicar=False) -> Resultado
    .embeber(textos) -> list[list[float]] | None

Algoritmo: FTS5 (OR, +bonus si están TODOS los términos) ∪ coseno ∪
recientes ∪ 1 salto de grafo ∪ ficheros abiertos → 10 señales en [0,1] →
score = Σ pesos·señal → selección greedy con MMR (redundancia recalculada tras
cada elección) hasta `limite` o `presupuesto_tokens`.

Todo degrada avisando (logging.warning): sin vectores → léxico; sin FTS →
LIKE (`via='like'`); si todo falla → Resultado vacío con `via='error'`.
Los vectores de memorias sin vector se calculan UNA vez y se guardan con
`almacen.guardar_vector` (caché persistente).
"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from . import Memoria, PESOS_DEFECTO, TIPO_POR_PALABRA
from .reranker import cargar_pesos, normalizar_pesos, puntuar

_log = logging.getLogger(__name__)

TOP_LEXICO = 50
TOP_VECTOR = 50
TOP_RECIENTES = 8
TOP_GRAFO = 10
TOP_TIPO = 20        # candidatos del tipo que la consulta nombra
TOP_ENTIDAD = 6      # por termino de la consulta que casa con `entidad`
TIPOS_GRAFO = ("supersedes", "caused_by", "solves", "modifies")
CHARS_POR_TOKEN = 3.7
CACHE_MAX = 128
CACHE_TTL_S = 30.0
RE_HISTORIAL = re.compile(r"historial|antes|cambi[oó]|por qu[eé]|anterior|versiones", re.IGNORECASE)
# Selección: se corta cuando el score cae por debajo de CORTE_RELATIVO × el mejor
# (env COGNIA_MEMORIA_CORTE_REL), nunca antes de MIN_SELECCION elegidas.
CORTE_RELATIVO = float(os.environ.get("COGNIA_MEMORIA_CORTE_REL", "0.60") or 0.60)
MIN_SELECCION = int(os.environ.get("COGNIA_MEMORIA_MIN_SEL", "3") or 3)
RE_TOKEN = re.compile(r"\w+", re.UNICODE)
# Palabras vacías mínimas (es/en): solo para no inflar la consulta OR; si TODO
# son vacías se usan igual (mejor un match pobre que ninguno).
STOPWORDS = frozenset("""
a al algo ante como con cual cuando de del desde donde e el ella ellos en entre era es esa
ese eso esta este esto fue ha hay la las le lo los mas más me mi muy ni no nos o para pero
por que qué se si sí sin sobre su sus te tu un una uno unos y ya
the a an and or of to in on for is are was were be it this that with as at by from
""".split())


@dataclass
class Resultado:
    memorias: list = field(default_factory=list)
    candidatos: int = 0
    seleccionados: int = 0
    explicaciones: dict = field(default_factory=dict)
    tokens: int = 0
    latencia_ms: float = 0.0
    via: str = "lexico"


# ---------------------------------------------------------------- utilidades

def tokenizar(texto: str) -> list[str]:
    """Tokens en minúscula, solo \\w+ (FTS5 unicode61 parte igual por puntuación)."""
    return [t.lower() for t in RE_TOKEN.findall(texto or "") if len(t) >= 2 or t.isdigit()]


def terminos_consulta(texto: str) -> list[str]:
    """Términos útiles para FTS: sin comillas/`*`/paréntesis/`:`, sin `-` inicial,
    sin repetidos y sin vacías (salvo que no quede nada)."""
    limpio = re.sub(r'["*():]', " ", texto or "")
    limpio = re.sub(r"(^|\s)-+", r"\1", limpio)
    vistos: list[str] = []
    for t in tokenizar(limpio):
        if t not in vistos:
            vistos.append(t)
    utiles = [t for t in vistos if t not in STOPWORDS]
    return utiles or vistos


def estimar_tokens(m: Memoria) -> int:
    if m.tokens and m.tokens > 0:
        return int(m.tokens)
    return max(1, int(math.ceil(len(m.contenido or "") / CHARS_POR_TOKEN)))


def coseno(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, num / (na * nb)))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _nombres_fichero(ruta: str) -> set[str]:
    r = (ruta or "").replace("\\", "/").strip()
    if not r:
        return set()
    base = r.rsplit("/", 1)[-1]
    return {r, base, base.rsplit(".", 1)[0]}


# ---------------------------------------------------------------- Recuperador

class Recuperador:
    """Retrieval híbrido con reranker configurable y explicaciones por memoria."""

    def __init__(self, almacen, pesos: dict | None = None, embebedor=None):
        self.almacen = almacen
        self.pesos = normalizar_pesos(pesos) if pesos is not None else cargar_pesos()
        if embebedor is None:
            from .embeddings import embebedor_compartido
            embebedor = embebedor_compartido()
        self.embebedor = embebedor
        self._cache: OrderedDict = OrderedDict()
        self._cache_version = None
        self.ultimo_aviso: str = ""

    # --- helpers de degradación ---------------------------------------
    def _avisar(self, origen: str, e: Exception) -> None:
        self.ultimo_aviso = f"{origen}: {type(e).__name__}: {e}"
        _log.warning("memoria_larga.retrieval degradado en %s: %s: %s", origen, type(e).__name__, e)

    def embeber(self, textos: list[str]):
        if self.embebedor is None:
            return None
        try:
            return self.embebedor.embeber(list(textos))
        except Exception as e:  # noqa: BLE001
            self._avisar("embeber", e)
            return None

    # --- caché ----------------------------------------------------------
    def _clave_cache(self, consulta, task_id, intencion, ficheros, limite, presupuesto, explicar):
        return (consulta, task_id, intencion, tuple(ficheros), limite, presupuesto, explicar)

    def _cache_get(self, clave):
        version = getattr(self.almacen, "version", None)
        if version is not None:
            if version != self._cache_version:
                self._cache.clear()
                self._cache_version = version
                return None
        ent = self._cache.get(clave)
        if ent is None:
            return None
        sellado, res = ent
        if version is None and (time.time() - sellado) > CACHE_TTL_S:
            del self._cache[clave]
            return None
        self._cache.move_to_end(clave)
        return res

    def _cache_put(self, clave, res) -> None:
        self._cache[clave] = (time.time(), res)
        self._cache.move_to_end(clave)
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)

    def invalidar_cache(self) -> None:
        self._cache.clear()

    # --- vectores -------------------------------------------------------
    def _vector_de(self, m: Memoria):
        """Vector persistido de la memoria, o None (sin recalcular aquí)."""
        if m.id is None:
            return None
        try:
            return self.almacen.vector(m.id)
        except Exception as e:  # noqa: BLE001
            self._avisar("vector", e)
            return None

    def _completar_vectores(self, faltan: list[Memoria]) -> dict:
        """Embebe en lote las memorias sin vector y las guarda (caché persistente)."""
        if not faltan:
            return {}
        vecs = self.embeber([m.resumen or m.contenido for m in faltan])
        if not vecs:
            return {}
        salida = {}
        for m, v in zip(faltan, vecs):
            salida[m.id] = v
            try:
                self.almacen.guardar_vector(m.id, v)
            except Exception as e:  # noqa: BLE001
                self._avisar("guardar_vector", e)
        return salida

    # --- búsqueda -------------------------------------------------------
    def buscar(self, consulta: str, *, task_id: str | None = None, intencion: str = "",
               ficheros_abiertos=(), limite: int = 12, presupuesto_tokens: int | None = None,
               explicar: bool = False) -> Resultado:
        t0 = time.perf_counter()
        ficheros = tuple(ficheros_abiertos or ())
        clave = self._clave_cache(consulta, task_id, intencion, ficheros, limite,
                                  presupuesto_tokens, explicar)
        try:
            cacheado = self._cache_get(clave)
            if cacheado is not None:
                return cacheado
            res = self._buscar(consulta, task_id, intencion, ficheros, limite,
                               presupuesto_tokens, explicar)
        except Exception as e:  # noqa: BLE001 — nunca romper el turno del agente
            self._avisar("buscar", e)
            res = Resultado(via="error")
        res.latencia_ms = (time.perf_counter() - t0) * 1000.0
        if res.via != "error":
            self._cache_put(clave, res)
        return res

    def _buscar(self, consulta, task_id, intencion, ficheros, limite, presupuesto, explicar):
        ahora = time.time()
        texto = " ".join(p for p in (consulta or "", intencion or "") if p).strip()
        pedir_historial = bool(RE_HISTORIAL.search(texto))
        terminos = terminos_consulta(texto)
        tiene_fts = bool(getattr(self.almacen, "fts5", getattr(self.almacen, "tiene_fts", True)))
        via = "lexico" if tiene_fts else "like"

        cand: dict[int, Memoria] = {}
        bm25: dict[int, float] = {}
        and_hit: set[int] = set()
        cos: dict[int, float] = {}
        por_grafo: set[int] = set()
        con_relaciones: set[int] = set()
        origen: dict[int, set] = {}

        def agregar(m: Memoria, de: str) -> bool:
            if m is None or m.id is None:
                return False
            if m.estado not in ("vigente", "superada"):
                return False
            if m.estado == "superada" and not pedir_historial:
                return False
            cand.setdefault(m.id, m)
            origen.setdefault(m.id, set()).add(de)
            return True

        # a) léxico. La consulta va como TEXTO PLANO: el almacén construye el MATCH
        # (cada término entre comillas, unidos por OR; sin FTS5 cae a LIKE). El
        # bonus "AND" se calcula aquí: todas las palabras de la consulta presentes.
        if terminos:
            try:
                for m, s in self.almacen.buscar_lexico(" ".join(terminos), limite=TOP_LEXICO,
                                                       solo_vigentes=not pedir_historial):
                    if agregar(m, "lexico"):
                        bm25[m.id] = abs(float(s or 0.0))
            except Exception as e:  # noqa: BLE001
                self._avisar("buscar_lexico", e)

        # a2) METADATA (banco 2026-09-04, semilla 21): "cache" era tambien un modulo
        # del relleno y cientos de lecturas/tests lo mencionaban; la decision
        # "para la cache usamos Redis" no entraba ni en los 50 candidatos
        # lexicos. Dos filtros baratos y precisos: candidatos del TIPO que la
        # consulta nombra, y cruce de cada termino con `entidad` (la clave
        # canonica de decisiones/restricciones/simbolos).
        texto_low = texto.lower()
        tipos_pedidos = {tipo for tipo, claves in TIPO_POR_PALABRA.items()
                         if any(c in texto_low for c in claves)}
        if terminos and tipos_pedidos:
            try:
                for m, s in self.almacen.buscar_lexico(" ".join(terminos), tipos=sorted(tipos_pedidos),
                                                       limite=TOP_TIPO, solo_vigentes=not pedir_historial):
                    if agregar(m, "tipo"):
                        bm25.setdefault(m.id, abs(float(s or 0.0)))
            except Exception as e:  # noqa: BLE001
                self._avisar("buscar_lexico(tipos)", e)
        for t in terminos:
            if len(t) < 4:
                continue
            try:
                for m in (self.almacen.por_entidad(t, solo_vigentes=not pedir_historial) or [])[:TOP_ENTIDAD]:
                    agregar(m, "entidad")
            except TypeError:
                try:
                    for m in (self.almacen.por_entidad(t) or [])[:TOP_ENTIDAD]:
                        agregar(m, "entidad")
                except Exception as e:  # noqa: BLE001
                    self._avisar("por_entidad", e)
                    break
            except Exception as e:  # noqa: BLE001
                self._avisar("por_entidad", e)
                break

        # b) vectorial
        qv = None
        vecs_q = self.embeber([texto]) if texto else None
        if vecs_q:
            qv = vecs_q[0]
            try:
                for m, c in self.almacen.buscar_vector(qv, limite=TOP_VECTOR,
                                                       solo_vigentes=not pedir_historial):
                    if agregar(m, "vector"):
                        cos[m.id] = float(c)
                via = "hibrido"
            except Exception as e:  # noqa: BLE001
                self._avisar("buscar_vector", e)

        # c) recientes de la tarea
        if task_id:
            try:
                for m in self.almacen.recientes(task_id, TOP_RECIENTES) or []:
                    agregar(m, "reciente")
            except Exception as e:  # noqa: BLE001
                self._avisar("recientes", e)

        # d) ficheros abiertos → memorias por entidad
        for f in ficheros:
            for nombre in _nombres_fichero(f):
                try:
                    for m in self.almacen.por_entidad(nombre) or []:
                        agregar(m, "fichero")
                except Exception as e:  # noqa: BLE001
                    self._avisar("por_entidad", e)
                    break
        if ficheros:
            claves = set()
            for f in ficheros:
                claves |= {n.lower() for n in _nombres_fichero(f)}
            for m in list(cand.values()):
                if any(str(e).replace("\\", "/").lower() in claves
                       or str(e).replace("\\", "/").lower().rsplit("/", 1)[-1] in claves
                       for e in (m.entidades or [])):
                    origen[m.id].add("fichero")

        # e) grafo: 1 salto desde los 10 mejores preliminares
        prelim = sorted(cand.values(), key=lambda m: (bm25.get(m.id, 0.0) > 0) * 1
                        + cos.get(m.id, 0.0), reverse=True)[:TOP_GRAFO]
        for m in prelim:
            try:
                vecinos = self.almacen.vecinos(m.id, tipos=TIPOS_GRAFO, saltos=1) or []
            except Exception as e:  # noqa: BLE001
                self._avisar("vecinos", e)
                break
            if vecinos:
                con_relaciones.add(m.id)
            for v, _tipo, _dist in vecinos:
                if agregar(v, "grafo"):
                    por_grafo.add(v.id)

        # f) historial pedido: completar cadenas supersedes vieja→nueva. Las
        # de la cadena van a `cadena_ids`: se les perdona la penalización de
        # contradicción y la redundancia (comparten casi todo el texto con la
        # vigente, y justo por eso se pidieron).
        cadena_ids: set[int] = set()
        if pedir_historial:
            for m in list(cand.values()):
                for attr in ("supersedes", "superseded_by"):
                    vistos = set()
                    cur = m
                    while getattr(cur, attr, None) is not None and cur.id not in vistos:
                        vistos.add(cur.id)
                        try:
                            otra = self.almacen.obtener(getattr(cur, attr))
                        except Exception as e:  # noqa: BLE001
                            self._avisar("obtener", e)
                            otra = None
                        if otra is None:
                            break
                        if agregar(otra, "cadena"):
                            por_grafo.add(otra.id)
                        cadena_ids.add(otra.id)
                        cadena_ids.add(m.id)
                        cur = otra

        if not cand:
            return Resultado(via=via)

        # g) vectores de candidatas que llegaron sin coseno (caché persistente)
        if qv is not None:
            faltan = []
            for m in cand.values():
                if m.id in cos:
                    continue
                v = self._vector_de(m)
                if v:
                    cos[m.id] = coseno(qv, v)
                else:
                    faltan.append(m)
            for mid, v in self._completar_vectores(faltan).items():
                cos[mid] = coseno(qv, v)

        # h) señales
        max_bm = max(bm25.values(), default=0.0) or 1.0
        max_paso = max((m.paso or 0) for m in cand.values())
        tokens_cand = {m.id: set(tokenizar(m.contenido)) | set(tokenizar(m.resumen)) for m in cand.values()}
        if len(terminos) >= 2:
            conj = set(terminos)
            and_hit = {mid for mid, toks in tokens_cand.items() if conj <= toks}
        # tipo que la consulta NOMBRA: senal de metadata `type_match` (tipos_pedidos
        # ya calculado arriba, en a2).
        senales: dict[int, dict] = {}
        for m in cand.values():
            lex = bm25.get(m.id, 0.0) / max_bm
            if m.id in and_hit:
                lex = min(1.0, lex + 0.2)
            if task_id:
                tarea = 1.0 if m.task_id == task_id else (0.5 if not m.task_id else 0.2)
            else:
                tarea = 0.5
            edad_h = max(0.0, (ahora - float(m.timestamp or ahora)) / 3600.0)
            rec = math.exp(-edad_h / 48.0)
            if max_paso > 0 and m.paso:
                rec = 0.5 * rec + 0.5 * (m.paso / max_paso)
            if m.id in por_grafo or (m.supersedes is not None and m.estado == "vigente"):
                grafo = 1.0
            elif m.id in con_relaciones or m.supersedes is not None or m.superseded_by is not None:
                grafo = 0.5
            else:
                grafo = 0.0
            senales[m.id] = {
                "semantic": (cos[m.id] + 1.0) / 2.0 if m.id in cos else 0.0,
                "lexical": max(0.0, min(1.0, lex)),
                "task": tarea,
                "importance": max(0.0, min(1.0, (m.importancia or 0) / 5.0)),
                "recency": max(0.0, min(1.0, rec)),
                "confidence": max(0.0, min(1.0, float(m.confianza or 0.0))),
                "graph": grafo,
                "type_match": 1.0 if (tipos_pedidos and m.tipo in tipos_pedidos) else 0.0,
                "redundancy": 0.0,
                "contradiction": (0.2 if m.id in cadena_ids else 1.0) if m.estado == "superada" else 0.0,
                "obsolescence": 1.0 if (m.valid_until is not None and m.valid_until <= ahora) else 0.0,
            }

        # i) selección greedy + MMR (redundancia = máx Jaccard con las ya elegidas)
        w_red = self.pesos.get("redundancy", PESOS_DEFECTO["redundancy"])
        base = {mid: puntuar(s, self.pesos) - w_red * s["redundancy"] for mid, s in senales.items()}
        pendientes = set(cand.keys())
        elegidas: list[Memoria] = []
        tokens_sel: dict[int, set] = {}
        total_tokens = 0
        explicaciones: dict[int, dict] = {}
        # Corte RELATIVO (banco 2026-09-04): rellenar siempre `limite` metía
        # 10 memorias de relleno por cada hecho útil (precisión 0,09). Se para
        # cuando el score cae por debajo de una fracción del mejor, con un
        # mínimo de MIN_SELECCION para no quedarse corto en consultas vagas.
        corte_rel = CORTE_RELATIVO
        mejor_global = None
        while pendientes and len(elegidas) < max(0, int(limite)):
            mejor_id, mejor_score = None, None
            for mid in pendientes:
                red = 0.0 if mid in cadena_ids else max(
                    (jaccard(tokens_cand[mid], t) for t in tokens_sel.values()), default=0.0)
                senales[mid]["redundancy"] = red
                sc = base[mid] + w_red * red
                if mejor_score is None or sc > mejor_score or (sc == mejor_score and mid < mejor_id):
                    mejor_id, mejor_score = mid, sc
            if mejor_global is None:
                mejor_global = mejor_score
            if (len(elegidas) >= MIN_SELECCION and mejor_global > 0
                    and mejor_score < mejor_global * corte_rel):
                break
            m = cand[mejor_id]
            pendientes.discard(mejor_id)
            coste = estimar_tokens(m)
            if presupuesto is not None and total_tokens + coste > presupuesto:
                continue  # no cabe; probar con las siguientes (pueden ser más cortas)
            elegidas.append(m)
            tokens_sel[mejor_id] = tokens_cand[mejor_id]
            total_tokens += coste
            exp = dict(senales[mejor_id])
            exp["score"] = round(mejor_score, 6)
            if explicar:
                exp["motivo"] = self._motivo(m, exp, origen.get(mejor_id, set()))
            explicaciones[mejor_id] = exp

        # La cadena pedida ("historial de X") entra ENTERA aunque el corte
        # relativo o el limite la dejaran fuera: es lo que se preguntó.
        if cadena_ids:
            for mid in sorted(cadena_ids, key=lambda i: (cand[i].timestamp or 0)):
                if mid in pendientes and mid in cand:
                    m = cand[mid]
                    coste = estimar_tokens(m)
                    if presupuesto is not None and total_tokens + coste > presupuesto:
                        continue
                    pendientes.discard(mid)
                    elegidas.append(m)
                    total_tokens += coste
                    exp = dict(senales[mid])
                    exp["score"] = round(base[mid], 6)
                    if explicar:
                        exp["motivo"] = self._motivo(m, exp, origen.get(mid, set())) + "; cadena pedida"
                    explicaciones[mid] = exp
            elegidas.sort(key=lambda m: -explicaciones[m.id]["score"])
        return Resultado(memorias=elegidas, candidatos=len(cand), seleccionados=len(elegidas),
                         explicaciones=explicaciones, tokens=total_tokens, via=via)

    @staticmethod
    def _motivo(m: Memoria, s: dict, origen: set) -> str:
        partes = [f"llegó por {', '.join(sorted(origen)) or '?'}"]
        top = sorted((k for k in PESOS_DEFECTO if s.get(k, 0) > 0),
                     key=lambda k: -abs(PESOS_DEFECTO[k] * s[k]))[:3]
        partes.append("señales: " + ", ".join(f"{k}={s[k]:.2f}" for k in top))
        if s.get("contradiction"):
            partes.append("SUPERADA (solo porque se pidió historial)")
        if s.get("obsolescence"):
            partes.append("caducada (valid_until pasado)")
        if s.get("redundancy", 0) > 0.5:
            partes.append(f"redundante con lo ya elegido ({s['redundancy']:.2f})")
        return f"{m.tipo} imp {m.importancia}: " + "; ".join(partes)


__all__ = ["Recuperador", "Resultado", "tokenizar", "terminos_consulta",
           "estimar_tokens", "coseno", "jaccard"]
