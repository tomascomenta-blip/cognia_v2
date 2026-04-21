"""
code_memory.py — Memoria especializada en código para Cognia
============================================================
Extiende EpisodicMemory con almacenamiento dedicado para:
  - Snippets de código (con búsqueda por lenguaje, tags y similitud)
  - Proyectos del usuario (stack, descripción, ruta)
  - Errores y sus soluciones (alta prioridad, crucial para aprendizaje)

USO:
  from code_memory import get_code_memory
  cm = get_code_memory(cognia_instance)

  cm.save_snippet("def foo(): ...", "python", "función de utilidad", ["utils"])
  cm.save_error("TypeError: ...", "en función foo()", "agregar type check")
  context = cm.get_context_for_prompt("cómo hago un loop en python")
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from logger_config import get_logger, log_db_error

logger = get_logger(__name__)

# ── Esquema de tablas propias ──────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS code_snippets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,
    language    TEXT NOT NULL DEFAULT 'python',
    description TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',       -- JSON list
    worked      INTEGER NOT NULL DEFAULT 1,        -- bool
    feedback_score REAL NOT NULL DEFAULT 1.0,     -- ajustado por ScoringEngine
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    last_used   TEXT NOT NULL,
    vector      TEXT NOT NULL DEFAULT '[]'         -- embedding opcional
);

CREATE TABLE IF NOT EXISTS code_projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    path        TEXT NOT NULL DEFAULT '',
    stack       TEXT NOT NULL DEFAULT '[]',        -- JSON list
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS code_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    error_msg   TEXT NOT NULL,
    context_    TEXT NOT NULL DEFAULT '',
    solution    TEXT NOT NULL DEFAULT '',
    language    TEXT NOT NULL DEFAULT 'python',
    resolved    INTEGER NOT NULL DEFAULT 0,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snippets_lang ON code_snippets(language);
CREATE INDEX IF NOT EXISTS idx_snippets_worked ON code_snippets(worked);
CREATE INDEX IF NOT EXISTS idx_errors_resolved ON code_errors(resolved);
"""


# ── Dataclasses de resultado ───────────────────────────────────────────────────

@dataclass
class CodeSnippet:
    """Snippet de código recuperado de la memoria."""
    id:             int
    code:           str
    language:       str
    description:    str
    tags:           list
    worked:         bool
    feedback_score: float
    similarity:     float = 0.0   # similitud semántica con la query


@dataclass
class CodeProject:
    """Proyecto registrado en la memoria."""
    id:          int
    name:        str
    path:        str
    stack:       list
    description: str
    created_at:  str


@dataclass
class CodeError:
    """Error registrado con su solución."""
    id:         int
    error_msg:  str
    context_:   str
    solution:   str
    language:   str
    resolved:   bool


# ── Clase principal ────────────────────────────────────────────────────────────

class CodeMemory:
    """
    Memoria especializada en código.

    Mantiene una conexión de SOLO escritura a la BD de Cognia (db_path),
    usando tablas propias para no interferir con EpisodicMemory.

    Interacción con el resto del sistema:
      - save_snippet/save_error → escribe en tablas propias
      - get_context_for_prompt → usa EpisodicMemory + tablas propias
      - feedback_score → es actualizado por ScoringEngine
    """

    def __init__(self, db_path: str, cognia_instance=None):
        """
        Args:
            db_path:          ruta al SQLite de Cognia
            cognia_instance:  instancia de Cognia (para embeddings opcionales)
        """
        self.db  = db_path
        self._ai = cognia_instance
        self._init_tables()
        logger.info(
            "CodeMemory inicializado",
            extra={"op": "code_memory.init", "context": f"db={db_path}"},
        )

    # ── Inicialización ─────────────────────────────────────────────────

    def _init_tables(self):
        """Crea las tablas si no existen."""
        try:
            conn = sqlite3.connect(self.db)
            conn.executescript(_DDL)
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "code_memory._init_tables", exc)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db)
        conn.text_factory = str
        return conn

    # ── API pública: guardar ───────────────────────────────────────────

    def save_snippet(
        self,
        code:        str,
        language:    str,
        description: str,
        tags:        list = None,
        worked:      bool = True,
    ) -> int:
        """
        Guarda un snippet de código en la memoria.

        Args:
            code:        código fuente
            language:    lenguaje (python, javascript, html, css, sql, etc.)
            description: qué hace el snippet
            tags:        lista de etiquetas ['bucles', 'utilidades', ...]
            worked:      si el código funcionó correctamente

        Returns:
            id del snippet guardado, o -1 si falló
        """
        tags = tags or []
        now  = datetime.now().isoformat()
        vec  = self._get_vector(f"{description} {language} {' '.join(tags)}")

        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                INSERT INTO code_snippets
                (code, language, description, tags, worked,
                 feedback_score, access_count, created_at, last_used, vector)
                VALUES (?, ?, ?, ?, ?, 1.0, 0, ?, ?, ?)
            """, (code, language.lower(), description,
                  json.dumps(tags), 1 if worked else 0,
                  now, now, json.dumps(vec)))
            snippet_id = c.lastrowid
            conn.commit()
            conn.close()
            logger.debug(
                "Snippet guardado",
                extra={"op":      "code_memory.save_snippet",
                       "context": f"id={snippet_id} lang={language} worked={worked}"},
            )
            return snippet_id
        except Exception as exc:
            log_db_error(logger, "code_memory.save_snippet", exc,
                         extra_ctx=f"lang={language} worked={worked}")
            return -1

    def save_project(
        self,
        name:        str,
        path:        str,
        stack:       list,
        description: str,
    ) -> int:
        """
        Registra un proyecto del usuario.

        Args:
            name:        nombre del proyecto (único)
            path:        ruta en disco (puede ser vacío)
            stack:       tecnologías usadas ['python', 'flask', 'sqlite']
            description: descripción breve

        Returns:
            id del proyecto, o -1 si falló
        """
        now = datetime.now().isoformat()
        try:
            conn = self._connect()
            c = conn.cursor()
            # UPSERT: si el proyecto ya existe, actualiza
            c.execute("SELECT id FROM code_projects WHERE name = ?", (name,))
            existing = c.fetchone()
            if existing:
                c.execute("""
                    UPDATE code_projects
                    SET path=?, stack=?, description=?, updated_at=?
                    WHERE name=?
                """, (path, json.dumps(stack), description, now, name))
                project_id = existing[0]
                logger.debug(
                    "Proyecto actualizado",
                    extra={"op": "code_memory.save_project",
                           "context": f"id={project_id} name={name}"},
                )
            else:
                c.execute("""
                    INSERT INTO code_projects
                    (name, path, stack, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (name, path, json.dumps(stack), description, now, now))
                project_id = c.lastrowid
                logger.info(
                    "Proyecto guardado",
                    extra={"op": "code_memory.save_project",
                           "context": f"id={project_id} name={name} stack={stack}"},
                )
            conn.commit()
            conn.close()
            return project_id
        except Exception as exc:
            log_db_error(logger, "code_memory.save_project", exc,
                         extra_ctx=f"name={name}")
            return -1

    def save_error(
        self,
        error_msg: str,
        context_:  str,
        solution:  str,
        language:  str = "python",
    ) -> int:
        """
        Guarda un error y su solución. ALTA PRIORIDAD para el asistente.

        Args:
            error_msg:  mensaje de error (traceback, descripción)
            context_:   dónde ocurrió (nombre de función, módulo, etc.)
            solution:   cómo se resolvió
            language:   lenguaje donde ocurrió el error

        Returns:
            id del error guardado, o -1 si falló
        """
        now = datetime.now().isoformat()
        try:
            conn = self._connect()
            c = conn.cursor()
            # Si ya existe el mismo error_msg, actualizar solución y marcar seen
            c.execute(
                "SELECT id FROM code_errors WHERE error_msg = ?", (error_msg[:500],)
            )
            existing = c.fetchone()
            if existing:
                c.execute("""
                    UPDATE code_errors
                    SET solution=?, context_=?, resolved=1,
                        access_count=access_count+1, last_seen=?
                    WHERE id=?
                """, (solution, context_, now, existing[0]))
                error_id = existing[0]
                logger.debug(
                    "Error existente actualizado con nueva solución",
                    extra={"op": "code_memory.save_error",
                           "context": f"id={error_id}"},
                )
            else:
                c.execute("""
                    INSERT INTO code_errors
                    (error_msg, context_, solution, language, resolved,
                     access_count, created_at, last_seen)
                    VALUES (?, ?, ?, ?, 1, 0, ?, ?)
                """, (error_msg[:500], context_[:300], solution,
                      language.lower(), now, now))
                error_id = c.lastrowid
                logger.info(
                    "Error guardado",
                    extra={"op":      "code_memory.save_error",
                           "context": f"id={error_id} lang={language}"},
                )
            conn.commit()
            conn.close()
            return error_id
        except Exception as exc:
            log_db_error(logger, "code_memory.save_error", exc,
                         extra_ctx=f"lang={language}")
            return -1

    # ── API pública: recuperar ─────────────────────────────────────────

    def search_snippets(
        self,
        query:    str,
        language: str = None,
        tags:     list = None,
        top_k:    int = 5,
        only_worked: bool = False,
    ) -> list[CodeSnippet]:
        """
        Busca snippets por lenguaje, tags y similitud semántica.

        Args:
            query:       texto de búsqueda (se convierte a vector)
            language:    filtro por lenguaje (None = todos)
            tags:        filtro por tags (se hace OR entre ellos)
            top_k:       máximo de resultados
            only_worked: si True, solo devuelve snippets que funcionaron

        Returns:
            Lista de CodeSnippet ordenada por relevancia
        """
        try:
            conn = self._connect()
            c = conn.cursor()

            # Construir WHERE
            conditions = []
            params     = []
            if language:
                conditions.append("language = ?")
                params.append(language.lower())
            if only_worked:
                conditions.append("worked = 1")

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            c.execute(f"""
                SELECT id, code, language, description, tags,
                       worked, feedback_score, vector
                FROM code_snippets {where}
                ORDER BY feedback_score DESC, access_count DESC
                LIMIT 50
            """, params)
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "code_memory.search_snippets", exc,
                         extra_ctx=f"query={query[:50]} lang={language}")
            return []

        # Calcular similitud semántica si hay vector de query
        query_vec = self._get_vector(query)
        scored    = []

        for row in rows:
            sid, code, lang, desc, tags_json, worked, fb_score, vec_json = row
            # Filtro por tags si se especificaron
            try:
                snippet_tags = json.loads(tags_json or "[]")
            except (json.JSONDecodeError, TypeError):
                snippet_tags = []

            if tags:
                tags_lower = [t.lower() for t in tags]
                if not any(t.lower() in tags_lower for t in snippet_tags):
                    continue

            # Calcular similitud
            sim = 0.5   # valor por defecto si no hay vector
            if query_vec:
                try:
                    vec = json.loads(vec_json or "[]")
                    if vec:
                        sim = self._cosine_sim(query_vec, vec)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Score combinado: similitud semántica + feedback_weight
            _fb = float(fb_score) if fb_score else 1.0
            combined = (0.70 * sim + 0.30 * min(1.0, _fb / 2.0))

            scored.append((combined, CodeSnippet(
                id=sid, code=code, language=lang,
                description=desc, tags=snippet_tags,
                worked=bool(worked), feedback_score=_fb,
                similarity=round(sim, 3),
            )))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Actualizar access_count de los top resultados
        top_ids = [s.id for _, s in scored[:top_k]]
        if top_ids:
            try:
                conn = self._connect()
                now = datetime.now().isoformat()
                for sid in top_ids:
                    conn.execute("""
                        UPDATE code_snippets
                        SET access_count = access_count + 1, last_used = ?
                        WHERE id = ?
                    """, (now, sid))
                conn.commit()
                conn.close()
            except Exception as exc:
                log_db_error(logger, "code_memory.update_access_count", exc)

        return [s for _, s in scored[:top_k]]

    def search_errors(
        self,
        error_msg: str,
        language:  str = None,
        top_k:     int = 3,
    ) -> list[CodeError]:
        """
        Busca errores similares ya resueltos.

        Args:
            error_msg: mensaje de error a buscar
            language:  filtro por lenguaje
            top_k:     máximo de resultados

        Returns:
            Lista de CodeError relevantes
        """
        try:
            conn = self._connect()
            c = conn.cursor()
            cond   = "WHERE resolved = 1"
            params = []
            if language:
                cond += " AND language = ?"
                params.append(language.lower())
            c.execute(f"""
                SELECT id, error_msg, context_, solution, language, resolved
                FROM code_errors {cond}
                ORDER BY access_count DESC
                LIMIT 30
            """, params)
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "code_memory.search_errors", exc,
                         extra_ctx=f"lang={language}")
            return []

        # Filtrado por palabras clave del error
        error_lower = error_msg.lower()
        key_terms   = [w for w in error_lower.split() if len(w) > 4]

        scored = []
        for row in rows:
            eid, emsg, ctx, sol, lang, resolved = row
            emsg_lower = emsg.lower()
            # Contar coincidencias de términos clave
            matches = sum(1 for t in key_terms if t in emsg_lower)
            if matches > 0:
                scored.append((matches, CodeError(
                    id=eid, error_msg=emsg, context_=ctx,
                    solution=sol, language=lang, resolved=bool(resolved),
                )))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def get_context_for_prompt(
        self,
        query:        str,
        language:     str = None,
        max_chars:    int = 1200,
        include_errors: bool = True,
    ) -> str:
        """
        Construye un bloque de contexto comprimido para incluir en el prompt del LLM.

        Combina snippets relevantes + errores conocidos en un formato
        compacto que no satura el contexto del modelo.

        Args:
            query:          pregunta/intención del usuario
            language:       lenguaje detectado (para filtrar)
            max_chars:      límite de caracteres del bloque
            include_errors: si True, incluye errores relevantes

        Returns:
            Bloque de texto formateado listo para insertar en el prompt
        """
        bloques = []
        chars_used = 0

        # ── Snippets relevantes ────────────────────────────────────────
        snippets = self.search_snippets(query, language=language, top_k=4,
                                        only_worked=True)
        if snippets:
            bloque_snip = ["SNIPPETS DE CÓDIGO GUARDADOS:"]
            for s in snippets:
                # Comprimir: descripción + primeras 15 líneas de código
                code_preview = "\n".join(s.code.splitlines()[:15])
                if len(s.code.splitlines()) > 15:
                    code_preview += "\n# ... (truncado)"
                entry = (
                    f"- [{s.language}] {s.description} "
                    f"(tags: {', '.join(s.tags[:3]) if s.tags else 'ninguno'}, "
                    f"funcionó: {'sí' if s.worked else 'no'}):\n"
                    f"```{s.language}\n{code_preview}\n```"
                )
                if chars_used + len(entry) > max_chars * 0.65:
                    break
                bloque_snip.append(entry)
                chars_used += len(entry)

            if len(bloque_snip) > 1:
                bloques.append("\n".join(bloque_snip))

        # ── Errores relevantes (alta prioridad para el asistente) ──────
        if include_errors:
            errors = self.search_errors(query, language=language, top_k=2)
            if errors:
                bloque_err = ["ERRORES CONOCIDOS Y SOLUCIONES:"]
                for e in errors:
                    entry = (
                        f"- Error: {e.error_msg[:150]}\n"
                        f"  Contexto: {e.context_[:100]}\n"
                        f"  Solución: {e.solution[:200]}"
                    )
                    if chars_used + len(entry) > max_chars:
                        break
                    bloque_err.append(entry)
                    chars_used += len(entry)

                if len(bloque_err) > 1:
                    bloques.append("\n".join(bloque_err))

        # ── Proyectos registrados ──────────────────────────────────────
        projects = self._get_projects_for_query(query)
        if projects:
            p = projects[0]    # proyecto más relevante
            entry = (
                f"PROYECTO ACTIVO: {p.name} | "
                f"Stack: {', '.join(p.stack[:5])} | "
                f"{p.description[:150]}"
            )
            if chars_used + len(entry) <= max_chars:
                bloques.insert(0, entry)   # al inicio del contexto

        if not bloques:
            return ""

        result = "\n\n".join(bloques)
        if len(result) > max_chars:
            result = result[:max_chars].rsplit("\n", 1)[0] + "\n# ... (contexto truncado)"

        return result

    # ── Actualización de feedback (llamada por ScoringEngine) ─────────

    def update_snippet_feedback(self, snippet_id: int, score_delta: float):
        """
        Ajusta el feedback_score de un snippet.
        Llamado por ScoringEngine cuando hay feedback positivo/negativo.

        Args:
            snippet_id:  id del snippet
            score_delta: delta a aplicar (+0.2 por feedback positivo, -0.1 por negativo)
        """
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("SELECT feedback_score FROM code_snippets WHERE id = ?",
                      (snippet_id,))
            row = c.fetchone()
            if not row:
                conn.close()
                return
            new_score = max(0.2, min(3.0, row[0] + score_delta))
            c.execute(
                "UPDATE code_snippets SET feedback_score = ? WHERE id = ?",
                (new_score, snippet_id)
            )
            conn.commit()
            conn.close()
            logger.debug(
                "Feedback de snippet actualizado",
                extra={"op":      "code_memory.update_snippet_feedback",
                       "context": f"id={snippet_id} delta={score_delta:+.2f} new={new_score:.2f}"},
            )
        except Exception as exc:
            log_db_error(logger, "code_memory.update_snippet_feedback", exc,
                         extra_ctx=f"snippet_id={snippet_id}")

    def count(self) -> dict:
        """Devuelve estadísticas rápidas de la memoria de código."""
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM code_snippets")
            snip_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM code_projects")
            proj_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM code_errors")
            err_count  = c.fetchone()[0]
            c.execute("SELECT language, COUNT(*) FROM code_snippets GROUP BY language")
            by_lang = dict(c.fetchall())
            conn.close()
            return {
                "snippets": snip_count,
                "projects": proj_count,
                "errors":   err_count,
                "by_language": by_lang,
            }
        except Exception as exc:
            log_db_error(logger, "code_memory.count", exc)
            return {"snippets": 0, "projects": 0, "errors": 0, "by_language": {}}

    # ── Helpers privados ───────────────────────────────────────────────

    def _get_vector(self, text: str) -> list:
        """Obtiene embedding del texto. Usa Cognia si está disponible."""
        if self._ai is None:
            return []
        try:
            from cognia.vectors import text_to_vector
            return text_to_vector(text[:200])
        except ImportError:
            try:
                from vectors import text_to_vector
                return text_to_vector(text[:200])
            except Exception:
                return []
        except Exception:
            return []

    @staticmethod
    def _cosine_sim(a: list, b: list) -> float:
        """Similitud coseno entre dos vectores."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot  = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _get_projects_for_query(self, query: str) -> list[CodeProject]:
        """Devuelve proyectos cuyo stack o nombre aparece en la query."""
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                SELECT id, name, path, stack, description, created_at
                FROM code_projects ORDER BY updated_at DESC LIMIT 10
            """)
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "code_memory._get_projects_for_query", exc)
            return []

        query_lower = query.lower()
        result = []
        for row in rows:
            pid, name, path, stack_json, desc, created = row
            try:
                stack = json.loads(stack_json or "[]")
            except (json.JSONDecodeError, TypeError):
                stack = []
            # Proyecto relevante si su nombre o algún elemento del stack
            # aparece en la query
            relevant = (name.lower() in query_lower or
                        any(s.lower() in query_lower for s in stack))
            if relevant:
                result.append(CodeProject(
                    id=pid, name=name, path=path, stack=stack,
                    description=desc, created_at=created,
                ))
        return result


# ── Singleton ──────────────────────────────────────────────────────────────────

_CODE_MEMORY_INSTANCE: Optional[CodeMemory] = None


def get_code_memory(cognia_instance=None, db_path: str = None) -> CodeMemory:
    """
    Devuelve la instancia singleton de CodeMemory.

    Args:
        cognia_instance: instancia de Cognia (para embeddings y db_path)
        db_path:         ruta explícita a la BD (si cognia_instance es None)
    """
    global _CODE_MEMORY_INSTANCE
    if _CODE_MEMORY_INSTANCE is None:
        if db_path is None and cognia_instance is not None:
            db_path = getattr(cognia_instance, "db", "cognia_memory.db")
        db_path = db_path or "cognia_memory.db"
        _CODE_MEMORY_INSTANCE = CodeMemory(db_path, cognia_instance)
    elif cognia_instance is not None and _CODE_MEMORY_INSTANCE._ai is None:
        # Inyectar cognia_instance si se pasó tarde
        _CODE_MEMORY_INSTANCE._ai = cognia_instance
    return _CODE_MEMORY_INSTANCE


# ── Tests básicos ──────────────────────────────────────────────────────────────

def _test_save_and_retrieve(tmp_db: str = ":memory:"):
    """Test 1: guardar y recuperar snippets, proyectos y errores."""
    cm = CodeMemory(tmp_db)

    # Snippet Python
    sid = cm.save_snippet(
        "def suma(a, b):\n    return a + b",
        "python", "función suma básica", ["aritmética", "funciones"], worked=True
    )
    assert sid > 0, "FALLO: save_snippet devolvió -1"
    print(f"  ✅ Snippet guardado (id={sid})")

    # Proyecto
    pid = cm.save_project("mi_app", "/home/user/mi_app",
                          ["python", "flask", "sqlite"], "App web personal")
    assert pid > 0, "FALLO: save_project devolvió -1"
    print(f"  ✅ Proyecto guardado (id={pid})")

    # Error
    eid = cm.save_error(
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        "en función suma()", "convertir a int antes de sumar"
    )
    assert eid > 0, "FALLO: save_error devolvió -1"
    print(f"  ✅ Error guardado (id={eid})")

    stats = cm.count()
    assert stats["snippets"] >= 1
    assert stats["projects"] >= 1
    assert stats["errors"]   >= 1
    print(f"  ✅ count() OK: {stats}")


def _test_search(tmp_db: str = ":memory:"):
    """Test 2: búsqueda de snippets y errores."""
    cm = CodeMemory(tmp_db)
    cm.save_snippet("for i in range(10): print(i)", "python",
                    "loop básico en python", ["loops"], worked=True)
    cm.save_snippet("<ul><li>item</li></ul>", "html",
                    "lista HTML básica", ["html", "listas"], worked=True)

    # Buscar por lenguaje
    py_snips = cm.search_snippets("loop", language="python", top_k=5)
    assert len(py_snips) >= 1, "FALLO: no se encontraron snippets python"
    print(f"  ✅ Búsqueda por lenguaje OK: {len(py_snips)} snippet(s)")

    # Buscar errores
    cm.save_error("NameError: name 'x' is not defined", "línea 5",
                  "declarar la variable antes de usarla")
    errors = cm.search_errors("NameError variable not defined")
    assert len(errors) >= 1, "FALLO: no se encontraron errores"
    print(f"  ✅ Búsqueda de errores OK: {len(errors)} error(es)")


def _test_context_for_prompt(tmp_db: str = ":memory:"):
    """Test 3: get_context_for_prompt devuelve texto útil."""
    cm = CodeMemory(tmp_db)
    cm.save_snippet("def factorial(n):\n    if n <= 1: return 1\n    return n * factorial(n-1)",
                    "python", "función factorial recursiva", ["recursión", "matemáticas"])
    cm.save_error("RecursionError: maximum recursion depth exceeded",
                  "en factorial()", "agregar límite o usar iterativo")

    ctx = cm.get_context_for_prompt("cómo hacer una función recursiva en python")
    assert ctx, "FALLO: get_context_for_prompt devolvió cadena vacía"
    assert "factorial" in ctx or "recursión" in ctx or "SNIPPET" in ctx
    print(f"  ✅ get_context_for_prompt OK ({len(ctx)} chars)")


def run_tests():
    """Ejecuta todos los tests de CodeMemory."""
    import tempfile, os
    print("\n🧪 Tests CodeMemory:")
    # Usar base de datos temporal en disco para que los DDL funcionen
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp = f.name
    try:
        _test_save_and_retrieve(tmp)
        _test_search(tmp)
        _test_context_for_prompt(tmp)
    finally:
        os.unlink(tmp)
    print("✅ Todos los tests pasaron.\n")


if __name__ == "__main__":
    run_tests()
