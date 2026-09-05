# -*- coding: utf-8 -*-
"""Métricas visibles del sistema de memoria: contexto, memoria, retrieval,
tokens, checkpoints. Alimentan `/contexto stats`, la telemetría JSONL
(`harness/telemetria.evento("memoria", ...)`) y el informe del banco.

Auditoría 2026-09-04: la telemetría contaba `n_compactaciones` pero nadie
emitía el evento; aquí cada reconstrucción emite `compactacion` con sus números.
"""
from __future__ import annotations

import time

_ULTIMA = None       # la instancia de la tarea en curso, para /contexto stats


class Estadisticas:
    def __init__(self, task_id: str = "", n_ctx: int = 0, max_activo: int = 0):
        self.task_id = task_id
        self.n_ctx = int(n_ctx or 0)
        self.max_activo = int(max_activo or 0)
        self.inicio = time.time()
        self.contexto_usado = 0
        self.tokens_historicos = 0       # todo lo que ENTRÓ al historial (acumulado)
        self.tokens_inyectados = 0       # lo que los bloques reconstruidos metieron
        self.tokens_descartados = 0      # lo que salió de la ventana en reconstrucciones
        self.reconstrucciones = 0
        self.memorias_guardadas = 0
        self.memorias_fusionadas = 0
        self.contradicciones = 0
        self.checkpoint_n = 0
        self.retrieval_candidatos = 0
        self.retrieval_seleccionados = 0
        self.retrieval_latencia_ms = 0.0
        self.retrieval_via = ""
        self.ultimas_explicaciones: dict = {}
        self.eventos: list[dict] = []
        global _ULTIMA
        _ULTIMA = self

    # ── registro ────────────────────────────────────────────────────────────
    def anotar_reconstruccion(self, antes: int, despues: int, descartados: int, inyectados: int,
                              candidatos: int, seleccionados: int, latencia_ms: float, via: str,
                              checkpoint_n: int, explicaciones: dict | None = None) -> None:
        self.reconstrucciones += 1
        self.tokens_descartados += max(0, antes - despues)
        self.tokens_inyectados += inyectados
        self.retrieval_candidatos = candidatos
        self.retrieval_seleccionados = seleccionados
        self.retrieval_latencia_ms = latencia_ms
        self.retrieval_via = via
        self.checkpoint_n = checkpoint_n or self.checkpoint_n
        self.contexto_usado = despues
        if explicaciones:
            self.ultimas_explicaciones = explicaciones
        ev = {"t": round(time.time() - self.inicio, 1), "antes": antes, "despues": despues,
              "descartados": descartados, "inyectados": inyectados, "candidatos": candidatos,
              "seleccionados": seleccionados, "via": via, "checkpoint": checkpoint_n}
        self.eventos.append(ev)
        try:
            from cognia.harness import telemetria
            telemetria.evento("compactacion", modo="reconstruccion", **ev)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("telemetria de reconstruccion no emitida: %s", exc)

    @property
    def tokens_ahorrados(self) -> int:
        return max(0, self.tokens_historicos - self.contexto_usado)

    # ── render ──────────────────────────────────────────────────────────────
    def render(self, almacen=None) -> str:
        util = (100.0 * self.contexto_usado / self.n_ctx) if self.n_ctx else 0.0
        total = "?"
        if almacen is not None:
            try:
                total = sum((almacen.contar().get("por_tipo") or {}).values())
            except Exception:
                total = "?"
        lineas = [
            "CONTEXTO",
            f"  Usado: {self.contexto_usado:,} / {self.n_ctx:,}   (objetivo activo {self.max_activo:,})".replace(",", "."),
            f"  Utilización: {util:.0f}%",
            "MEMORIA",
            f"  Memorias totales: {total}   guardadas esta tarea: {self.memorias_guardadas}   fusionadas: {self.memorias_fusionadas}   contradicciones resueltas: {self.contradicciones}",
            "RETRIEVAL",
            f"  Candidatos: {self.retrieval_candidatos}   Seleccionados: {self.retrieval_seleccionados}   vía: {self.retrieval_via or '-'}   latencia: {self.retrieval_latencia_ms:.0f} ms",
            "TOKENS",
            f"  Históricos: {self.tokens_historicos:,}   Inyectados: {self.tokens_inyectados:,}   Descartados de la ventana: {self.tokens_descartados:,}   Ahorrados: {self.tokens_ahorrados:,}".replace(",", "."),
            "CHECKPOINT",
            f"  #{self.checkpoint_n}   reconstrucciones: {self.reconstrucciones}",
        ]
        return "\n".join(lineas)

    def a_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("ultimas_explicaciones", "eventos")}
        d["tokens_ahorrados"] = self.tokens_ahorrados
        d["n_eventos"] = len(self.eventos)
        return d


def ultima() -> Estadisticas | None:
    return _ULTIMA


def explicar_memoria(id_memoria: int, explicaciones: dict | None = None) -> str:
    """Por qué entró (o no) una memoria en el último retrieval."""
    ex = (explicaciones or (_ULTIMA.ultimas_explicaciones if _ULTIMA else {}) or {}).get(id_memoria)
    if not ex:
        return f"Memoria #{id_memoria}: sin explicación registrada en el último retrieval."
    lineas = [f"Memoria #{id_memoria}: score {ex.get('score', 0):.3f}"]
    for k in ("semantic", "lexical", "task", "importance", "recency", "confidence", "graph",
              "redundancy", "contradiction", "obsolescence"):
        if k in ex:
            lineas.append(f"  {k:13s} = {float(ex[k]):.2f}")
    if ex.get("motivo"):
        lineas.append("  motivo: " + str(ex["motivo"]))
    return "\n".join(lineas)


__all__ = ["Estadisticas", "ultima", "explicar_memoria"]
