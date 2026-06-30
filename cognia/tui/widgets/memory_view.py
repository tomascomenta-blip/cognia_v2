"""
memory_view.py -- Vista Memoria de la TUI: stats del context-map + busqueda.

Que: MemoryView muestra arriba las stats reales del context-map (cuantos punteros
hay por proyecto, leidos de la DB via storage/db_pool) y debajo un Input de
busqueda que recupera spans relevantes de la memoria real (recuperacion hibrida
BM25 + vector de ContextMap) y los lista. La carga de stats y cada busqueda corren
en un WORKER en un hilo: la UI nunca se congela mientras se toca la DB.

Por que: la TUI necesita ver la memoria real sin acoplarse al REPL ni construir un
modelo cognitivo completo (caro y fragil). MemoryBackend envuelve ContextMap detras
de una API minima y PEREZOSA (nada pesado en __init__: numpy/DB se importan/abren
recien en la primera stats()/search(), disparada al ABRIR la vista, no en el boot).

Real vs placeholder: las stats (conteo de punteros por proyecto) y la busqueda
LEXICA (BM25 sobre los spans realmente indexados, resueltos lossless) son REALES.
La mitad SEMANTICA de la busqueda (re-ranking por embedding) queda como placeholder:
exige un embedder/`ai` pesado; sin el, query_text_hybrid degrada limpio a BM25-only,
que sigue siendo recuperacion real sobre la memoria. embed_fn es inyectable para
habilitar el vector cuando haya un embedder liviano disponible.

Robustez: MemoryBackend.stats()/search() estan envueltos en try/except y nunca
levantan (DB ausente, esquema nuevo, query rara) -> degradan a vacio. La vista
muestra empty-states claros: "Escribi para buscar en la memoria" / "Memoria vacia".

Convencion: codigo ASCII; los textos de UI pueden ir en UTF-8.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Static

from ..theme import COLORS, empty_state

# Presupuestos de la busqueda (acotan cuanto texto se resuelve/rankea por query).
_SEARCH_TOP_K = 20
_SEARCH_BUDGET_TOKENS = 2000
_SNIPPET_CHARS = 200


class MemoryBackend:
    """Adaptador perezoso de la memoria real (context-map) para la vista.

    Nada pesado en __init__: ContextMap (numpy + DB) se importa/abre recien en la
    primera stats()/search(). Pensado para llamarse desde un worker-thread.
    """

    def __init__(self, db_path: Optional[str] = None,
                 embed_fn: Optional[Callable[[str], object]] = None) -> None:
        self._db_path = db_path          # None -> cognia.config.DB_PATH (lo pone ContextMap)
        # embed_fn(query) -> vector, o None. Por defecto None -> busqueda BM25-only.
        self._embed_fn = embed_fn or (lambda _t: None)

    def stats(self) -> dict:
        """Conteo de punteros por proyecto del context-map. Nunca levanta.

        Devuelve {projects: [(nombre, n_punteros), ...], total_pointers: int}.
        Cualquier fallo de DB degrada a {projects: [], total_pointers: 0}.
        """
        try:
            from cognia.context.context_map import ContextMap
            base = ContextMap(db_path=self._db_path)
            per: List[tuple] = []
            total = 0
            for project in base.list_projects():
                n = ContextMap(db_path=self._db_path, project=project).stats().get("pointers", 0)
                per.append((project, n))
                total += n
            per.sort(key=lambda t: t[1], reverse=True)
            return {"projects": per, "total_pointers": total}
        except Exception:
            return {"projects": [], "total_pointers": 0}

    def search(self, query: str, limit: int = _SEARCH_TOP_K) -> List[dict]:
        """Spans relevantes de la memoria real (hibrido BM25+vector, merge por
        proyecto). Nunca levanta: cualquier fallo -> lista vacia.

        Devuelve [{score, text, source_kind, source_ref, project}, ...] por score.
        """
        try:
            from cognia.context.context_map import ContextMap
            base = ContextMap(db_path=self._db_path)
            projects = base.list_projects() or ["default"]
            merged: List[dict] = []
            for project in projects:
                cm = ContextMap(db_path=self._db_path, project=project)
                for r in cm.query_text_hybrid(
                        query, self._embed_fn,
                        budget_tokens=_SEARCH_BUDGET_TOKENS, top_k=limit):
                    d = dict(r)
                    d["project"] = project
                    merged.append(d)
            merged.sort(key=lambda d: d.get("score", 0.0), reverse=True)
            return merged[:limit]
        except Exception:
            return []


class MemoryView(Vertical):
    """Vista de memoria: stats arriba + busqueda (worker) sobre el context-map."""

    def __init__(self, backend: Optional[MemoryBackend] = None) -> None:
        super().__init__(id="memoria", classes="view")
        self.border_title = "Memoria"
        # Backend real (carga perezosa en la 1a stats/search); inyectable en tests.
        self._backend = backend
        self._stats_loaded = False

    def compose(self) -> ComposeResult:
        yield Static(self._build_stats_loading(), id="memory-stats")
        yield Input(placeholder="Escribi para buscar en la memoria...", id="memory-input")
        with VerticalScroll(id="memory-results"):
            yield Static(self._build_empty(), id="memory-output", classes="empty-state")

    # -- backend perezoso --------------------------------------------------

    def _get_backend(self) -> MemoryBackend:
        if self._backend is None:
            self._backend = MemoryBackend()
        return self._backend

    # -- stats (carga perezosa al ABRIR la vista, en un worker) ------------

    def on_show(self) -> None:
        """Al hacerse visible la vista, carga las stats UNA vez (no en el boot)."""
        if not self._stats_loaded:
            self._stats_loaded = True
            self._load_stats()

    @work(thread=True)
    def _load_stats(self) -> None:
        """Worker-thread: lee las stats (toca la DB) y las entrega a la UI."""
        try:
            stats = self._get_backend().stats()
        except Exception:
            stats = {"projects": [], "total_pointers": 0}
        self.app.call_from_thread(self._show_stats, stats)

    def _show_stats(self, stats: dict) -> None:
        """Corre en el hilo de la UI: pinta la linea de stats."""
        try:
            self.query_one("#memory-stats", Static).update(self._build_stats(stats))
        except Exception:
            pass

    # -- busqueda (worker: no bloquea la UI) -------------------------------

    @on(Input.Submitted, "#memory-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        """Enter en el input: lanza la busqueda en un worker y muestra 'buscando...'."""
        query = event.value.strip()
        if not query:
            return
        self._set_output(self._build_searching(query))
        self._run_search(query)

    @work(thread=True)
    def _run_search(self, query: str) -> None:
        """Worker-thread: recupera de la memoria real (puede tocar DB/disco)."""
        try:
            results = self._get_backend().search(query)
        except Exception:
            results = []
        self.app.call_from_thread(self._show_results, query, results)

    def _show_results(self, query: str, results: List[dict]) -> None:
        """Corre en el hilo de la UI: pinta los resultados o el empty-state."""
        if not results:
            self._set_output(self._build_no_results(query))
            return
        self._set_output(self._build_results(query, results))

    def _set_output(self, renderable: Text) -> None:
        try:
            self.query_one("#memory-output", Static).update(renderable)
        except Exception:
            pass

    # -- lectura para tests ------------------------------------------------

    def output_text(self) -> str:
        """Texto plano del area de resultados (para asserts)."""
        try:
            return self.query_one("#memory-output", Static).render().plain
        except Exception:
            return ""

    def stats_text(self) -> str:
        """Texto plano de la linea de stats (para asserts)."""
        try:
            return self.query_one("#memory-stats", Static).render().plain
        except Exception:
            return ""

    # -- renderables (Rich Text con la paleta semantica) -------------------

    @staticmethod
    def _build_stats_loading() -> Text:
        out = Text(no_wrap=True)
        out.append("Memoria  ", style=f"bold {COLORS['text']}")
        out.append("(stats al abrir la vista)", style=COLORS["muted"])
        return out

    @staticmethod
    def _build_stats(stats: dict) -> Text:
        total = int(stats.get("total_pointers", 0) or 0)
        projects = stats.get("projects", []) or []
        out = Text(no_wrap=True)
        out.append("Memoria  ", style=f"bold {COLORS['text']}")
        out.append(f"{total} punteros  ", style=f"bold {COLORS['accent']}")
        out.append(f"{len(projects)} proyectos", style=COLORS["muted"])
        if projects:
            head = "   " + ", ".join(f"{name}({n})" for name, n in projects[:5])
            out.append(head, style=COLORS["muted"])
        return out

    @staticmethod
    def _build_results(query: str, results: List[dict]) -> Text:
        out = Text()
        out.append(f"{len(results)} resultados para ", style=COLORS["muted"])
        out.append(f"'{query}'\n\n", style=f"bold {COLORS['text']}")
        for i, r in enumerate(results, 1):
            score = float(r.get("score", 0.0) or 0.0)
            project = str(r.get("project", "") or "")
            kind = str(r.get("source_kind", "") or "")
            text = str(r.get("text", "") or "").replace("\n", " ").strip()
            snippet = text[:_SNIPPET_CHARS] + ("..." if len(text) > _SNIPPET_CHARS else "")
            out.append(f"{i:>2}. ", style=f"bold {COLORS['accent']}")
            out.append(f"[{score:.2f}] ", style=COLORS["info"])
            out.append(f"{project}/{kind}\n", style=COLORS["muted"])
            out.append(f"    {snippet}\n\n", style=COLORS["text"])
        return out

    @staticmethod
    def _build_searching(query: str) -> Text:
        out = Text(justify="center")
        out.append(f"Buscando '{query}'...", style=f"italic {COLORS['muted']}")
        return out

    @staticmethod
    def _build_no_results(query: str) -> Text:
        return empty_state(
            "{ }",
            f"Sin resultados para '{query}'",
            "La memoria no tiene spans que coincidan; proba otros terminos.",
        )

    @staticmethod
    def _build_empty() -> Text:
        return empty_state(
            "{ }",
            "Escribi para buscar en la memoria",
            "Recupera spans del context-map (memoria episodica/semantica indexada).",
        )
