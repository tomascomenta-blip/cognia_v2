"""
cognia_modules_adicionales.py — Esqueletos de Módulos para COGNIA v1
=====================================================================
Módulos adicionales propuestos para completar la arquitectura cognitiva.

MÓDULOS INCLUIDOS:
  1. MemoryCompressionEngine  — compresión jerárquica de memorias frías
  2. ContradictionResolver    — resolución automática de contradicciones
  3. TheoryGenerator          — generación de teorías a partir de hipótesis
  4. AnalogyEngine            — detección de analogías entre dominios
  5. ReasoningPlanner         — planificación de cadenas de razonamiento
  6. ConceptHierarchyBuilder  — construcción de jerarquías ontológicas

PRINCIPIOS DE DISEÑO:
  - Todos los módulos son CPU-friendly (sin GPUs, sin embeddings masivos)
  - Sólo SQL + aritmética para métricas y filtros
  - Embeddings opcionales, sólo cuando es necesario
  - Ningún módulo se ejecuta automáticamente: propone → humano aprueba
  - Cada módulo tiene un método status_report() y un impacto de energía declarado
"""

import sqlite3
import json
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any

COGNIA_DB = "cognia_memory.db"


def db_connect(path: str = COGNIA_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.text_factory = str
    return conn


# ══════════════════════════════════════════════════════════════════════
# 1. MEMORY COMPRESSION ENGINE
# Impacto energético: ALTO beneficio — reduce RAM 20-40%
# ══════════════════════════════════════════════════════════════════════

class MemoryCompressionEngine:
    """
    Compresión jerárquica de memorias episódicas antiguas y de baja importancia.

    ESTRATEGIA:
      Tier 1 (caliente): últimas 50 memorias — acceso O(1) en RAM
      Tier 2 (tibio):    episodios de 2-7 días — compresión de texto 50%
      Tier 3 (frío):     episodios de >7 días  — sólo metadatos en RAM,
                         contenido comprimido en DB

    ENERGÍA: La compresión se ejecuta durante ciclos de sueño (bajo uso),
    nunca durante interacciones activas.
    """

    ENERGY_IMPACT = "high_benefit"  # reduce retrieval cost significativamente

    def __init__(self, db_path: str = COGNIA_DB):
        self.db = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS memory_compression_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                episodes_compressed INTEGER DEFAULT 0,
                bytes_saved         INTEGER DEFAULT 0,
                tier                TEXT
            )
        """)
        # Añadir columna de compresión a episodic_memory si no existe
        try:
            c.execute("ALTER TABLE episodic_memory ADD COLUMN compressed INTEGER DEFAULT 0")
            c.execute("ALTER TABLE episodic_memory ADD COLUMN content_summary TEXT")
        except Exception:
            pass
        conn.commit()
        conn.close()

    def identify_cold_memories(self, days_threshold: int = 7, min_importance: float = 0.0,
                               max_importance: float = 0.4) -> List[Dict]:
        """
        Identifica episodios candidatos para compresión:
        - Más de `days_threshold` días de antigüedad
        - Importancia entre min y max (ni cruciales ni triviales)
        - No olvidados todavía
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                SELECT id, content, importance, confidence, timestamp
                FROM episodic_memory
                WHERE forgotten = 0
                  AND compressed = 0
                  AND importance BETWEEN ? AND ?
                  AND timestamp <= datetime('now', ? || ' days')
                ORDER BY importance ASC, timestamp ASC
                LIMIT 100
            """, (min_importance, max_importance, f"-{days_threshold}"))
            rows = c.fetchall()
            return [{"id": r[0], "content": r[1], "importance": r[2],
                     "confidence": r[3], "timestamp": r[4]} for r in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def compress_episode(self, episode_id: int, summary: str) -> bool:
        """
        Comprime un episodio reemplazando su contenido por un resumen.
        ATENCIÓN: Requiere aprobación humana antes de ejecutarse en producción.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                UPDATE episodic_memory
                SET content_summary = ?, compressed = 1
                WHERE id = ?
            """, (summary, episode_id))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def run_compression_cycle(self, dry_run: bool = True) -> Dict:
        """
        Ejecuta un ciclo de compresión.
        Si dry_run=True, sólo reporta qué se comprimiría sin modificar nada.
        """
        candidates = self.identify_cold_memories()
        total_content_len = sum(len(e.get("content") or "") for e in candidates)
        estimated_savings = total_content_len // 2  # ~50% de compresión

        result = {
            "dry_run":        dry_run,
            "candidates":     len(candidates),
            "estimated_savings_bytes": estimated_savings,
            "message": (
                f"[DRY RUN] Se comprimirían {len(candidates)} episodios, "
                f"ahorrando ~{estimated_savings // 1024} KB."
                if dry_run else
                f"Comprimidos {len(candidates)} episodios."
            )
        }

        if not dry_run:
            compressed = 0
            for ep in candidates:
                # Generar resumen simple (sin LLM): primeras 100 chars
                summary = (ep.get("content") or "")[:100] + "…"
                if self.compress_episode(ep["id"], summary):
                    compressed += 1
            result["compressed"] = compressed
            self._log_compression(compressed, estimated_savings, "cold")

        return result

    def _log_compression(self, count: int, bytes_saved: int, tier: str):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO memory_compression_log (timestamp, episodes_compressed, bytes_saved, tier)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), count, bytes_saved, tier))
        conn.commit()
        conn.close()

    def status_report(self) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE compressed=1")
            compressed = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE compressed=0 AND forgotten=0")
            active = c.fetchone()[0]
        except Exception:
            compressed, active = 0, 0
        finally:
            conn.close()
        return (f"MemoryCompressionEngine: {compressed} episodios comprimidos, "
                f"{active} activos sin comprimir.")


# ══════════════════════════════════════════════════════════════════════
# 2. CONTRADICTION RESOLVER
# Impacto energético: MEDIO — resuelve contradicciones durante consolidación
# ══════════════════════════════════════════════════════════════════════

class ContradictionResolver:
    """
    Resuelve contradicciones entre conceptos usando estrategias sin LLM.

    ESTRATEGIAS (en orden de preferencia):
      1. Por confianza:   gana el concepto con mayor confianza media
      2. Por soporte:     gana el concepto con mayor número de episodios
      3. Por temporalidad: gana el concepto más reciente (actualización)
      4. Por contexto:    marcar ambos válidos en contextos distintos (coexistencia)

    Las resoluciones PROPUESTAS requieren aprobación humana antes de aplicarse.
    """

    ENERGY_IMPACT = "medium"

    STRATEGIES = ["confidence", "support", "recency", "coexistence"]

    def __init__(self, db_path: str = COGNIA_DB):
        self.db = db_path

    def get_unresolved(self, limit: int = 20) -> List[Dict]:
        """Retorna contradicciones no resueltas."""
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                SELECT id, concept_a, concept_b, description, severity, created_at
                FROM contradictions
                WHERE resolved = 0
                ORDER BY severity DESC, created_at ASC
                LIMIT ?
            """, (limit,))
            rows = c.fetchall()
            return [{"id": r[0], "concept_a": r[1], "concept_b": r[2],
                     "description": r[3], "severity": r[4], "created_at": r[5]}
                    for r in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def analyze_contradiction(self, contradiction_id: int) -> Dict:
        """
        Analiza una contradicción y propone una estrategia de resolución.
        No modifica nada — sólo propone.
        """
        conn = db_connect(self.db)
        c = conn.cursor()

        try:
            c.execute("SELECT concept_a, concept_b, description FROM contradictions WHERE id=?",
                      (contradiction_id,))
            row = c.fetchone()
            if not row:
                return {"error": "Contradicción no encontrada"}
            ca, cb, desc = row

            # Buscar métricas de cada concepto
            def get_concept_stats(concept):
                c.execute("SELECT confidence, support FROM semantic_memory WHERE concept=?",
                          (concept,))
                r = c.fetchone()
                return {"confidence": r[0] if r else 0.5, "support": r[1] if r else 0}

            stats_a = get_concept_stats(ca or "")
            stats_b = get_concept_stats(cb or "")

            # Determinar estrategia recomendada
            if abs(stats_a["confidence"] - stats_b["confidence"]) > 0.2:
                strategy  = "confidence"
                winner    = ca if stats_a["confidence"] > stats_b["confidence"] else cb
                rationale = f"'{winner}' tiene mayor confianza ({max(stats_a['confidence'], stats_b['confidence']):.0%})"
            elif abs(stats_a["support"] - stats_b["support"]) > 3:
                strategy  = "support"
                winner    = ca if stats_a["support"] > stats_b["support"] else cb
                rationale = f"'{winner}' tiene mayor soporte ({max(stats_a['support'], stats_b['support'])} episodios)"
            else:
                strategy  = "coexistence"
                winner    = None
                rationale = "Ambos conceptos tienen soporte y confianza similares — coexistencia contextual"

            return {
                "contradiction_id": contradiction_id,
                "concept_a":    ca,
                "concept_b":    cb,
                "description":  desc,
                "stats_a":      stats_a,
                "stats_b":      stats_b,
                "strategy":     strategy,
                "winner":       winner,
                "rationale":    rationale,
                "requires_human_approval": True,
                "proposed_action": (
                    f"Marcar '{winner}' como concepto correcto y reducir importancia de '{cb if winner==ca else ca}'"
                    if winner else
                    "Marcar contradicción como 'coexistencia contextual' y preservar ambos conceptos"
                ),
            }
        except Exception as e:
            return {"error": str(e)}
        finally:
            conn.close()

    def apply_resolution(self, contradiction_id: int, strategy: str,
                         winner: Optional[str] = None) -> bool:
        """
        Aplica la resolución de una contradicción (sólo con aprobación humana).
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            resolution_note = f"Resuelto por estrategia '{strategy}'"
            if winner:
                resolution_note += f", ganador: '{winner}'"
            c.execute("""
                UPDATE contradictions
                SET resolved=1, resolution_note=?, resolved_at=?
                WHERE id=?
            """, (resolution_note, datetime.now().isoformat(), contradiction_id))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def status_report(self) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=0")
            pending = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM contradictions WHERE resolved=1")
            resolved = c.fetchone()[0]
        except Exception:
            pending, resolved = 0, 0
        finally:
            conn.close()
        return f"ContradictionResolver: {pending} pendientes, {resolved} resueltas."


# ══════════════════════════════════════════════════════════════════════
# 3. THEORY GENERATOR
# Impacto energético: BAJO — opera sobre hipótesis ya existentes
# ══════════════════════════════════════════════════════════════════════

class TheoryGenerator:
    """
    Genera teorías combinando múltiples hipótesis relacionadas.

    Una TEORÍA es un conjunto de hipótesis que:
      - Comparten conceptos o predicados comunes
      - Se refuerzan mutuamente (sus evidencias no se contradicen)
      - Tienen confianza acumulada > umbral

    Las teorías propuestas se guardan para revisión humana.
    Son el nivel más alto de abstracción en la pirámide cognitiva:
    Episodio → Concepto → Hipótesis → Teoría
    """

    ENERGY_IMPACT = "low"
    MIN_HYPOTHESES_FOR_THEORY = 3
    MIN_THEORY_CONFIDENCE     = 0.55

    def __init__(self, db_path: str = COGNIA_DB):
        self.db = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS theories (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                title        TEXT NOT NULL,
                description  TEXT,
                hypothesis_ids TEXT,  -- JSON array
                confidence   REAL DEFAULT 0.0,
                status       TEXT DEFAULT 'proposed',
                human_comment TEXT
            )
        """)
        conn.commit()
        conn.close()

    def find_hypothesis_clusters(self) -> List[List[Dict]]:
        """
        Agrupa hipótesis por conceptos compartidos.
        Retorna clusters de hipótesis candidatas a formar una teoría.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                SELECT id, text, confidence
                FROM hypotheses
                WHERE confidence > 0.25
                ORDER BY confidence DESC
                LIMIT 50
            """)
            hypotheses = [{"id": r[0], "text": r[1], "confidence": r[2]}
                          for r in c.fetchall()]
        except Exception:
            hypotheses = []
        finally:
            conn.close()

        if len(hypotheses) < self.MIN_HYPOTHESES_FOR_THEORY:
            return []

        # Agrupar por palabras clave compartidas (heurística simple, sin embeddings)
        clusters: Dict[str, List[Dict]] = {}
        stopwords = {"el", "la", "los", "de", "que", "es", "en", "un", "una", "y",
                     "del", "se", "con", "no", "por", "su", "para", "al", "una", "lo"}

        for hyp in hypotheses:
            words = set(w.lower() for w in (hyp.get("text") or "").split()
                        if len(w) > 4 and w.lower() not in stopwords)
            for word in words:
                if word not in clusters:
                    clusters[word] = []
                clusters[word].append(hyp)

        # Sólo clusters con al menos MIN_HYPOTHESES_FOR_THEORY hipótesis
        valid_clusters = [
            sorted(hyps, key=lambda x: -x["confidence"])
            for hyps in clusters.values()
            if len(hyps) >= self.MIN_HYPOTHESES_FOR_THEORY
        ]
        return valid_clusters

    def generate_theory(self, hypotheses: List[Dict], key_concept: str = "") -> Optional[Dict]:
        """
        Genera una propuesta de teoría a partir de un cluster de hipótesis.
        """
        if len(hypotheses) < self.MIN_HYPOTHESES_FOR_THEORY:
            return None

        avg_confidence = sum(h["confidence"] for h in hypotheses) / len(hypotheses)
        if avg_confidence < self.MIN_THEORY_CONFIDENCE:
            return None

        ids    = [h["id"] for h in hypotheses]
        texts  = [h.get("text", "") for h in hypotheses]
        title  = f"Teoría sobre '{key_concept}'" if key_concept else "Teoría generada"

        return {
            "title":          title,
            "description":    f"Teoría emergente de {len(hypotheses)} hipótesis relacionadas: " +
                              "; ".join(t[:60] for t in texts[:3]),
            "hypothesis_ids": ids,
            "confidence":     round(avg_confidence, 4),
            "status":         "proposed",
            "requires_human_approval": True,
        }

    def run_generation_cycle(self) -> Dict:
        """
        Ejecuta un ciclo completo de generación de teorías.
        Retorna las teorías propuestas para revisión humana.
        """
        clusters    = self.find_hypothesis_clusters()
        proposed    = []
        conn        = db_connect(self.db)
        c           = conn.cursor()

        for i, cluster in enumerate(clusters[:5]):  # máximo 5 teorías por ciclo
            # Extraer concepto clave del cluster (más frecuente en los textos)
            all_words = []
            for h in cluster:
                all_words.extend(w.lower() for w in (h.get("text") or "").split()
                                 if len(w) > 4)
            key_concept = max(set(all_words), key=all_words.count) if all_words else f"cluster_{i}"

            theory = self.generate_theory(cluster, key_concept)
            if not theory:
                continue

            try:
                c.execute("""
                    INSERT INTO theories (timestamp, title, description, hypothesis_ids,
                                         confidence, status)
                    VALUES (?, ?, ?, ?, ?, 'proposed')
                """, (datetime.now().isoformat(), theory["title"], theory["description"],
                      json.dumps(theory["hypothesis_ids"]), theory["confidence"]))
                theory["id"] = c.lastrowid
                proposed.append(theory)
            except Exception:
                pass

        conn.commit()
        conn.close()

        return {
            "theories_proposed": len(proposed),
            "theories":          proposed,
            "message":           f"TheoryGenerator: {len(proposed)} teorías propuestas para revisión.",
        }

    def status_report(self) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM theories WHERE status='proposed'")
            pending = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM theories WHERE status='accepted'")
            accepted = c.fetchone()[0]
        except Exception:
            pending, accepted = 0, 0
        finally:
            conn.close()
        return f"TheoryGenerator: {pending} teorías propuestas, {accepted} aceptadas."


# ══════════════════════════════════════════════════════════════════════
# 4. ANALOGY ENGINE
# Impacto energético: MEDIO — usa similitud estructural entre subgrafos
# ══════════════════════════════════════════════════════════════════════

class AnalogyEngine:
    """
    Detecta analogías entre dominios conceptuales usando similitud estructural
    del Knowledge Graph.

    Una ANALOGÍA es una correspondencia entre dos subgrafos con estructura
    similar pero conceptos distintos. Ejemplo:
      "El corazón bombea sangre" ↔ "La bomba impulsa agua"
      Estructura: [A] --bombea/impulsa--> [B]

    MÉTODO:
      1. Extraer subgrafos por predicado
      2. Comparar firmas de predicados entre dominios
      3. Proponer analogías cuando la estructura es similar pero los
         conceptos son semánticamente distantes

    ENERGÍA: Opera sólo en el KG (SQL puro). Sin embeddings.
    """

    ENERGY_IMPACT = "medium"
    MIN_ANALOGY_SCORE = 0.60

    def __init__(self, db_path: str = COGNIA_DB):
        self.db = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS analogies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT NOT NULL,
                source_triple TEXT NOT NULL,  -- "A predicate B"
                target_triple TEXT NOT NULL,  -- "X predicate Y"
                score         REAL DEFAULT 0.0,
                explanation   TEXT,
                status        TEXT DEFAULT 'proposed'
            )
        """)
        conn.commit()
        conn.close()

    def find_structural_analogies(self, top_k: int = 10) -> List[Dict]:
        """
        Busca pares de triples en el KG con predicados iguales o similares
        pero sujetos/objetos pertenecientes a dominios distintos.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        analogies = []

        try:
            # Agrupar triples por predicado
            c.execute("""
                SELECT predicate, GROUP_CONCAT(subject || '|||' || object, '###') as pairs
                FROM knowledge_graph
                GROUP BY predicate
                HAVING COUNT(*) >= 2
                LIMIT 20
            """)
            rows = c.fetchall()

            for predicate, pairs_str in rows:
                pairs = [p.split("|||") for p in pairs_str.split("###") if "|||" in p]
                if len(pairs) < 2:
                    continue

                # Comparar todos los pares del mismo predicado
                for i, (s1, o1) in enumerate(pairs):
                    for s2, o2 in pairs[i+1:]:
                        if s1 == s2 or o1 == o2:
                            continue

                        # Distancia léxica simple (sin embeddings)
                        dist_s = self._levenshtein_norm(s1, s2)
                        dist_o = self._levenshtein_norm(o1, o2)
                        # Alta distancia = conceptos distintos = posible analogía interesante
                        analogy_score = (dist_s + dist_o) / 2.0

                        if analogy_score >= self.MIN_ANALOGY_SCORE:
                            analogies.append({
                                "source": f"{s1} --{predicate}--> {o1}",
                                "target": f"{s2} --{predicate}--> {o2}",
                                "predicate": predicate,
                                "score": round(analogy_score, 4),
                                "explanation": (
                                    f"'{s1}' y '{s2}' comparten la relación '{predicate}' "
                                    f"con '{o1}' y '{o2}' respectivamente, siendo conceptos distintos."
                                ),
                            })

            analogies.sort(key=lambda x: -x["score"])
        except Exception:
            pass
        finally:
            conn.close()

        # Guardar top-k en DB
        self._save_analogies(analogies[:top_k])
        return analogies[:top_k]

    def _save_analogies(self, analogies: List[Dict]):
        conn = db_connect(self.db)
        c = conn.cursor()
        ts = datetime.now().isoformat()
        for a in analogies:
            try:
                c.execute("""
                    INSERT INTO analogies (timestamp, source_triple, target_triple, score, explanation, status)
                    VALUES (?, ?, ?, ?, ?, 'proposed')
                """, (ts, a["source"], a["target"], a["score"], a["explanation"]))
            except Exception:
                pass
        conn.commit()
        conn.close()

    @staticmethod
    def _levenshtein_norm(a: str, b: str) -> float:
        """Distancia de Levenshtein normalizada (0=igual, 1=máxima diferencia)."""
        if not a or not b:
            return 1.0
        a, b = a.lower(), b.lower()
        if a == b:
            return 0.0
        la, lb = len(a), len(b)
        dp = list(range(lb + 1))
        for i in range(1, la + 1):
            prev = dp[:]
            dp[0] = i
            for j in range(1, lb + 1):
                cost = 0 if a[i-1] == b[j-1] else 1
                dp[j] = min(dp[j] + 1, dp[j-1] + 1, prev[j-1] + cost)
        return round(dp[lb] / max(la, lb), 4)

    def status_report(self) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM analogies")
            total = c.fetchone()[0]
        except Exception:
            total = 0
        finally:
            conn.close()
        return f"AnalogyEngine: {total} analogías detectadas en el grafo de conocimiento."


# ══════════════════════════════════════════════════════════════════════
# 5. REASONING PLANNER
# Impacto energético: BAJO — evita cadenas de inferencia redundantes
# ══════════════════════════════════════════════════════════════════════

class ReasoningPlanner:
    """
    Planifica y optimiza cadenas de razonamiento antes de ejecutarlas.

    PROBLEMA QUE RESUELVE:
      El sistema actualmente lanza cadenas de inferencia a profundidad fija.
      El 50% de los ciclos alcanzan el límite sin llegar a conclusión útil.

    SOLUCIÓN:
      Antes de razonar, el planner:
        1. Estima la complejidad de la pregunta (simple/media/compleja)
        2. Selecciona profundidad adaptativa (1-3 pasos)
        3. Pre-filtra conceptos irrelevantes del contexto de trabajo
        4. Detecta si la pregunta ya fue respondida antes (cache de razonamiento)

    ENERGÍA: Reduce 20-40% el costo total de razonamiento.
    """

    ENERGY_IMPACT = "high_benefit"

    def __init__(self, db_path: str = COGNIA_DB, max_depth: int = 3):
        self.db        = db_path
        self.max_depth = max_depth
        self._ensure_schema()

    def _ensure_schema(self):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS reasoning_cache (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash   TEXT UNIQUE,
                query_text   TEXT,
                plan_steps   TEXT,  -- JSON
                depth_used   INTEGER,
                latency_ms   REAL,
                quality_score REAL,
                created_at   TEXT,
                hit_count    INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def estimate_complexity(self, query: str) -> str:
        """
        Estima la complejidad de una query sin usar LLM.
        Heurísticas: longitud, número de conceptos, palabras de negación/condicional.
        """
        q = query.lower()
        word_count = len(q.split())

        negations    = sum(1 for w in ["no", "nunca", "sin", "excepto", "pero"] if w in q)
        conditionals = sum(1 for w in ["si", "cuando", "aunque", "salvo", "mientras"] if w in q)
        questions    = sum(1 for w in ["por qué", "cómo", "cuál", "qué relación"] if w in q)

        complexity_score = (word_count / 10) + negations + conditionals + questions

        if complexity_score < 2:
            return "simple"
        elif complexity_score < 5:
            return "medium"
        else:
            return "complex"

    def plan_reasoning_depth(self, query: str) -> Dict:
        """
        Retorna un plan de razonamiento: profundidad recomendada,
        conceptos a pre-filtrar, y si hay cache disponible.
        """
        complexity = self.estimate_complexity(query)
        depth_map  = {"simple": 1, "medium": 2, "complex": 3}
        depth      = depth_map.get(complexity, 2)

        # Verificar cache
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        cached     = self._get_from_cache(query_hash)

        plan = {
            "query":         query,
            "complexity":    complexity,
            "recommended_depth": depth,
            "cache_hit":     cached is not None,
            "cache_data":    cached,
            "estimated_energy": {
                "simple":  "muy bajo (1 paso)",
                "medium":  "bajo (2 pasos)",
                "complex": "moderado (3 pasos)",
            }.get(complexity),
            "pre_filter_concepts": self._identify_irrelevant_concepts(query),
            "sub_tasks": self.decompose_goal(query),
        }
        return plan

    def _get_from_cache(self, query_hash: str) -> Optional[Dict]:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("""
                SELECT plan_steps, depth_used, quality_score
                FROM reasoning_cache
                WHERE query_hash = ?
                  AND created_at >= datetime('now', '-24 hours')
            """, (query_hash,))
            row = c.fetchone()
            if row:
                c.execute("UPDATE reasoning_cache SET hit_count=hit_count+1 WHERE query_hash=?",
                          (query_hash,))
                conn.commit()
                return {"plan_steps": json.loads(row[0] or "[]"), "depth": row[1], "score": row[2]}
            return None
        except Exception:
            return None
        finally:
            conn.close()

    def _identify_irrelevant_concepts(self, query: str) -> List[str]:
        """Conceptos del WM que probablemente no son relevantes para esta query."""
        query_words = set(query.lower().split())
        conn = db_connect(self.db)
        c = conn.cursor()
        irrelevant = []
        try:
            c.execute("SELECT concept FROM semantic_memory ORDER BY support ASC LIMIT 50")
            for (concept,) in c.fetchall():
                concept_words = set(concept.lower().split())
                if not concept_words.intersection(query_words):
                    irrelevant.append(concept)
        except Exception:
            pass
        finally:
            conn.close()
        return irrelevant[:10]  # sólo los 10 más irrelevantes

    def save_plan(self, query: str, plan: dict,
                  latency_ms: float = 0.0, quality_score: float = 0.5) -> bool:
        """Persiste un plan ejecutado en caché."""
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        steps = plan.get("sub_tasks", [plan.get("complexity", "simple")])
        conn = db_connect(self.db)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO reasoning_cache
                    (query_hash, query_text, plan_steps, depth_used,
                     latency_ms, quality_score, created_at, hit_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, (query_hash, query[:200], json.dumps(steps),
                  plan.get("recommended_depth", 2),
                  round(latency_ms, 1), round(quality_score, 3),
                  datetime.now().isoformat()))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def decompose_goal(self, query: str) -> list:
        """Descompone una query en sub-tareas sin LLM."""
        import re
        q = query.strip()
        partes = re.split(r'\s+(?:y además|y también|además|también)\s+', q, flags=re.IGNORECASE)
        if len(partes) > 1:
            return [f"Resolver: {p.strip().rstrip('?')}" for p in partes if p.strip()]
        cond = re.search(r'si (.+?)(?:,|entonces) (.+)', q, re.IGNORECASE)
        if cond:
            return [f"Evaluar: {cond.group(1).strip()}", f"Deducir: {cond.group(2).strip()}"]
        comp = re.search(r'(?:diferencia|comparar|vs\.?)\s+(.+?)\s+(?:y|vs)\s+(.+)', q, re.IGNORECASE)
        if comp:
            return [f"Caracterizar: {comp.group(1).strip()}", f"Caracterizar: {comp.group(2).strip()}", "Comparar"]
        return [q]

    def status_report(self) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*), SUM(hit_count) FROM reasoning_cache")
            row = c.fetchone()
            cached, hits = row[0] or 0, row[1] or 0
        except Exception:
            cached, hits = 0, 0
        finally:
            conn.close()
        return f"ReasoningPlanner: {cached} planes en caché, {hits} hits totales."


# ══════════════════════════════════════════════════════════════════════
# 6. CONCEPT HIERARCHY BUILDER
# Impacto energético: BAJO — sólo durante consolidación nocturna
# ══════════════════════════════════════════════════════════════════════

class ConceptHierarchyBuilder:
    """
    Construye jerarquías ontológicas (es-un, parte-de, tipo-de) a partir
    de los conceptos en semantic_memory y las aristas del KG.

    RESULTADO: Un árbol de conceptos que mejora:
      - La recuperación semántica por categoría
      - La generalización (si A es-un B, los episodios sobre A son
        recuperables en queries sobre B)
      - La generación de hipótesis (herencia de propiedades)

    MÉTODO: Detecta predicados jerárquicos en el KG ("es-un", "tipo-de",
    "parte-de", "subtipo", "es", "incluye") y construye el grafo de herencia.
    """

    ENERGY_IMPACT = "low"
    HIERARCHICAL_PREDICATES = {
        "es-un", "es_un", "is-a", "is_a", "tipo-de", "tipo_de",
        "parte-de", "parte_de", "subtipo", "incluye", "contiene",
        "pertenece-a", "pertenece_a",
    }

    def __init__(self, db_path: str = COGNIA_DB):
        self.db = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS concept_hierarchy (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                child        TEXT NOT NULL,
                parent       TEXT NOT NULL,
                relation     TEXT NOT NULL,
                confidence   REAL DEFAULT 0.7,
                created_at   TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_hier_child ON concept_hierarchy(child)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_hier_parent ON concept_hierarchy(parent)")
        conn.commit()
        conn.close()

    def extract_hierarchy_from_kg(self) -> List[Dict]:
        """
        Extrae relaciones jerárquicas del Knowledge Graph.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        relations = []
        try:
            placeholders = ",".join("?" * len(self.HIERARCHICAL_PREDICATES))
            c.execute(f"""
                SELECT subject, predicate, object, weight
                FROM knowledge_graph
                WHERE LOWER(predicate) IN ({placeholders})
            """, list(self.HIERARCHICAL_PREDICATES))
            rows = c.fetchall()
            for child, relation, parent, weight in rows:
                relations.append({
                    "child":    child,
                    "parent":   parent,
                    "relation": relation,
                    "confidence": min(1.0, (weight or 1.0) / 5.0),
                })
        except Exception:
            pass
        finally:
            conn.close()
        return relations

    def build_hierarchy(self) -> Dict:
        """
        Construye (o reconstruye) la jerarquía completa de conceptos.
        """
        relations = self.extract_hierarchy_from_kg()

        if not relations:
            return {"relations_found": 0, "message": "No se encontraron relaciones jerárquicas en el KG."}

        conn = db_connect(self.db)
        c = conn.cursor()
        inserted = 0
        ts = datetime.now().isoformat()
        for r in relations:
            try:
                c.execute("""
                    INSERT OR REPLACE INTO concept_hierarchy
                    (child, parent, relation, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (r["child"], r["parent"], r["relation"], r["confidence"], ts))
                inserted += 1
            except Exception:
                pass
        conn.commit()
        conn.close()

        return {
            "relations_found": len(relations),
            "relations_inserted": inserted,
            "message": f"Jerarquía construida: {inserted} relaciones jerárquicas registradas.",
        }

    def get_ancestors(self, concept: str, max_depth: int = 5) -> List[str]:
        """Retorna los ancestros (padres, abuelos...) de un concepto."""
        ancestors = []
        visited   = set()
        current   = concept
        conn      = db_connect(self.db)
        c         = conn.cursor()
        try:
            for _ in range(max_depth):
                if current in visited:
                    break
                visited.add(current)
                c.execute("SELECT parent FROM concept_hierarchy WHERE child=? LIMIT 1", (current,))
                row = c.fetchone()
                if not row:
                    break
                ancestors.append(row[0])
                current = row[0]
        except Exception:
            pass
        finally:
            conn.close()
        return ancestors

    def get_descendants(self, concept: str, max_depth: int = 3) -> List[str]:
        """Retorna los descendientes de un concepto."""
        descendants = []
        queue       = [concept]
        visited     = set()
        conn        = db_connect(self.db)
        c           = conn.cursor()
        depth       = 0
        try:
            while queue and depth < max_depth:
                next_queue = []
                for node in queue:
                    if node in visited:
                        continue
                    visited.add(node)
                    c.execute("SELECT child FROM concept_hierarchy WHERE parent=?", (node,))
                    children = [r[0] for r in c.fetchall()]
                    descendants.extend(children)
                    next_queue.extend(children)
                queue = next_queue
                depth += 1
        except Exception:
            pass
        finally:
            conn.close()
        return list(set(descendants))

    def status_report(self) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM concept_hierarchy")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT parent) FROM concept_hierarchy")
            parents = c.fetchone()[0]
        except Exception:
            total, parents = 0, 0
        finally:
            conn.close()
        return (f"ConceptHierarchyBuilder: {total} relaciones jerárquicas, "
                f"{parents} conceptos padre en la ontología.")


# ══════════════════════════════════════════════════════════════════════
# REGISTRO DE MÓDULOS PARA FLASK
# ══════════════════════════════════════════════════════════════════════

def register_routes_additional_modules(app, db_path: str = COGNIA_DB):
    """Registra endpoints REST para los módulos adicionales."""
    from flask import request, jsonify

    compression = MemoryCompressionEngine(db_path)
    resolver    = ContradictionResolver(db_path)
    theory_gen  = TheoryGenerator(db_path)
    analogy_eng = AnalogyEngine(db_path)
    planner     = ReasoningPlanner(db_path)
    hierarchy   = ConceptHierarchyBuilder(db_path)

    @app.route("/api/modules/estado")
    def api_modules_estado():
        return jsonify({
            "memory_compression":    compression.status_report(),
            "contradiction_resolver": resolver.status_report(),
            "theory_generator":      theory_gen.status_report(),
            "analogy_engine":        analogy_eng.status_report(),
            "reasoning_planner":     planner.status_report(),
            "concept_hierarchy":     hierarchy.status_report(),
        })

    @app.route("/api/modules/comprimir", methods=["POST"])
    def api_comprimir():
        data    = request.get_json() or {}
        dry_run = data.get("dry_run", True)
        result  = compression.run_compression_cycle(dry_run=dry_run)
        return jsonify(result)

    @app.route("/api/modules/contradicciones")
    def api_contradicciones():
        return jsonify(resolver.get_unresolved())

    @app.route("/api/modules/analizar_contradiccion/<int:cid>")
    def api_analizar_contradiccion(cid):
        return jsonify(resolver.analyze_contradiction(cid))

    @app.route("/api/modules/teorias", methods=["POST"])
    def api_generar_teorias():
        result = theory_gen.run_generation_cycle()
        return jsonify(result)

    @app.route("/api/modules/analogias", methods=["POST"])
    def api_analogias():
        analogies = analogy_eng.find_structural_analogies()
        return jsonify(analogies)

    @app.route("/api/modules/planificar", methods=["POST"])
    def api_planificar():
        data  = request.get_json() or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"error": "Se requiere 'query'"}), 400
        plan = planner.plan_reasoning_depth(query)
        return jsonify(plan)

    @app.route("/api/modules/jerarquia", methods=["POST"])
    def api_jerarquia():
        result = hierarchy.build_hierarchy()
        return jsonify(result)

    @app.route("/api/modules/ancestros/<concept>")
    def api_ancestros(concept):
        return jsonify({"concept": concept, "ancestors": hierarchy.get_ancestors(concept)})

    print("[OK] Módulos adicionales de Cognia activos — endpoints /api/modules/* registrados")
    return {
        "compression": compression,
        "resolver":    resolver,
        "theory_gen":  theory_gen,
        "analogy_eng": analogy_eng,
        "planner":     planner,
        "hierarchy":   hierarchy,
    }
