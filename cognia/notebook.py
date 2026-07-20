# -*- coding: utf-8 -*-
"""Cuaderno inteligente (Open Notebook nativo).

Mandato 2026-07-14: "Open Notebook -> cuaderno inteligente interno." Open
Notebook combina NOTAS + FUENTES (documentos) + PREGUNTAS sobre ambos. Cognia
ya tiene las tres piezas por separado: SmartNotesEngine (notas), ingest.py
(fuentes -> memoria episódica) y la memoria episódica (recuperación vectorial).
Este módulo las ORQUESTA en un cuaderno único, sin duplicar almacenamiento:

- las notas se guardan como notas de SmartNotesEngine (no una tabla nueva);
- las fuentes se ingieren con ingest.ingest_file (van a la memoria episódica)
  y se registran como una nota de tipo 'fuente' (el índice del cuaderno);
- consultar() recupera de la memoria episódica los fragmentos relevantes
  (RAG de RECUPERACIÓN, sin generación LLM: barato, no compite con el modelo).

Es una CAPACIDAD INTERNA (para que Cognia la use como tool), no una UI: el
agente puede tomar notas, sumar fuentes y consultarlas dentro de una tarea.
"""
from typing import Optional

TIPO_FUENTE = "fuente"


class Cuaderno:
    """Cuaderno = notas + fuentes ingeridas + consulta sobre la memoria."""

    def __init__(self, ai=None, db_path: Optional[str] = None,
                 cuaderno_id: str = "default"):
        self.ai = ai
        self.cuaderno_id = cuaderno_id
        from cognia.notes.smart_notes import SmartNotesEngine
        self._notas = SmartNotesEngine(
            db_path=db_path or getattr(ai, "db", None))

    # ── notas ───────────────────────────────────────────────────────────
    def anotar(self, contenido: str, tipo: str = "fact") -> int:
        """Agrega una nota al cuaderno. Devuelve su id."""
        return self._notas.add_note(
            content=contenido.strip()[:2000], note_type=tipo,
            session_id=self.cuaderno_id, source="cuaderno")

    def notas(self, tipo: Optional[str] = None, limite: int = 20) -> list:
        return self._notas.get_notes(session_id=self.cuaderno_id,
                                     note_type=tipo, limit=limite)

    # ── fuentes ─────────────────────────────────────────────────────────
    def agregar_fuente(self, path: str) -> dict:
        """Ingiere un documento a la memoria y lo indexa como fuente del
        cuaderno. Requiere `ai` (para la memoria episódica)."""
        if self.ai is None:
            return {"error": "cuaderno sin `ai`: no puedo ingerir fuentes"}
        from cognia.ingest import ingest_file
        res = ingest_file(self.ai, path)
        if "error" in res:
            return res
        etiqueta = f"{res['archivo']} ({res['chunks']} fragmentos)"
        self._notas.add_note(content=etiqueta, note_type=TIPO_FUENTE,
                             session_id=self.cuaderno_id, source=path)
        return res

    def fuentes(self, limite: int = 50) -> list:
        return self._notas.get_notes(session_id=self.cuaderno_id,
                                     note_type=TIPO_FUENTE, limit=limite)

    # ── consulta (RAG de recuperación, sin LLM) ─────────────────────────
    def consultar(self, pregunta: str, top_k: int = 5) -> list:
        """Fragmentos más relevantes de la memoria para la pregunta. Barato:
        búsqueda vectorial (episodic_fast ~2ms), sin generación."""
        if self.ai is None:
            return []
        try:
            from cognia.vectors import text_to_vector
        except ImportError:
            from vectors import text_to_vector
        vec = text_to_vector(pregunta.strip())
        hits = self.ai.episodic.retrieve_similar(vec, top_k=top_k)
        # retrieve_similar devuelve dicts con 'observation'/'similarity'
        # (misma forma que consume la tool `recordar`). Piso de coseno
        # conservador: descarta el ruido ~0 y ordena por similitud.
        SIM_FLOOR = 0.1
        rel = sorted((h for h in (hits or [])
                      if isinstance(h, dict)
                      and h.get("similarity", 0.0) >= SIM_FLOOR),
                     key=lambda h: h.get("similarity", 0.0), reverse=True)
        return [{"texto": h.get("observation", ""),
                 "score": round(h.get("similarity", 0.0), 3)} for h in rel]

    def resumen(self) -> dict:
        notas = self.notas(limite=1000)
        n_fuentes = sum(1 for n in notas if n.get("note_type") == TIPO_FUENTE)
        return {"cuaderno": self.cuaderno_id,
                "notas": len(notas) - n_fuentes,
                "fuentes": n_fuentes}
