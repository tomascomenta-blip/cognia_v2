# -*- coding: utf-8 -*-
"""Los CUATRO ganchos con los que el loop del agente usa la memoria larga.

    ml = iniciar(task, ctx, perfil, print_fn, schemas)      # al arrancar bucle_nativo
    ml.registrar(role, texto, tool=None, ok=None, paso=n)   # tras cada mensaje que entra al historial
    ml.fin_de_paso(mensajes, est, resp, ...) -> int|None    # en lugar de resumen→truncado→emergencia
    ml.cerrar(result_text, ok)                              # al salir del bucle

Todo degrada avisando por print_fn: un fallo de la memoria nunca cuesta el
paso. Con COGNIA_MEMORIA_LARGA=0 `iniciar` devuelve None y el loop sigue como
antes (contrafactual para el banco).
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

from cognia.memoria_larga import activo
from cognia.memoria_larga import checkpoint as _cp
from cognia.memoria_larga.contexto import ContextManager
from cognia.memoria_larga.observabilidad import Estadisticas
from cognia.memoria_larga.tokens import Estimador

_LOG = logging.getLogger(__name__)
_CADA_PASOS = int(os.environ.get("COGNIA_MEMORIA_CHECKPOINT_CADA", "5") or 5)


def _task_id(task: str, ctx: dict) -> str:
    for clave in ("_ml_task_id", "_traza_task_id", "_hz_task_id"):
        v = ctx.get(clave) if isinstance(ctx, dict) else None
        if v:
            return str(v)
    try:
        from cognia.agent.estado_tarea import nuevo_task_id
        return nuevo_task_id(task)
    except Exception:
        slug = re.sub(r"[^a-z0-9]+", "-", (task or "tarea").lower())[:24].strip("-")
        return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug or 'tarea'}-{uuid.uuid4().hex[:4]}"


class MemoriaTarea:
    def __init__(self, task: str, ctx: dict, perfil: dict, print_fn, schemas=None):
        self.task = task
        self.ctx = ctx if isinstance(ctx, dict) else {}
        self.print_fn = print_fn or (lambda *a, **k: None)
        self.task_id = _task_id(task, self.ctx)
        self.ctx["_ml_task_id"] = self.task_id
        self.session_id = str(self.ctx.get("session_id") or os.environ.get("COGNIA_SESSION_ID") or uuid.uuid4().hex[:12])
        self.cwd = str(self.ctx.get("workspace") or self.ctx.get("cwd") or os.getcwd())
        self.n_ctx = int((perfil or {}).get("n_ctx") or 32768)
        self.est = Estimador()
        self.stats = Estadisticas(self.task_id, self.n_ctx)
        self.almacen = None
        self.recuperador = None
        self.paso = 0
        self.ultimo_error_id = None
        self.ficheros_abiertos: list[str] = []
        self.memorias_ids: list[int] = []
        self.decisiones: list[str] = []
        self.errores: list[str] = []
        self.checkpoint_n = 0
        self.ultimo_cp_paso = 0
        self.ultima_intencion = ""
        peso = 0
        try:
            from cognia.agent.loop import _peso_schemas
            peso = _peso_schemas(schemas) if schemas else 0
        except Exception as exc:
            _LOG.warning("memoria larga: peso de schemas no calculable (%s); 0", exc)
            peso = 0
        # Sesion EFIMERA (COGNIA_EFIMERO=1: pruebas, bancos, REPL efimero): la
        # memoria vive en RAM y no se escribe ningun checkpoint JSON. Sin esto
        # los tests que corren bucle_nativo contaminaban ~/.cognia con tareas
        # de prueba (22 checkpoints el 2026-09-04, la leccion del repo
        # "las pruebas contaminan la memoria del dueno").
        self.efimero = os.environ.get("COGNIA_EFIMERO", "").strip().lower() in ("1", "on", "true", "yes")
        try:
            from cognia.memoria_larga.almacen import Almacen
            self.almacen = Almacen(":memory:" if self.efimero else str(_cp.dir_base() / "memoria_larga.db"))
        except Exception as exc:
            self.print_fn(f"[warn_cl]memoria larga: almacén no disponible ({type(exc).__name__}: {exc}); "
                          f"sigo sin memoria persistente[/warn_cl]")
        if self.almacen is not None:
            try:
                from cognia.memoria_larga.retrieval import Recuperador
                self.recuperador = Recuperador(self.almacen)
            except Exception as exc:
                self.print_fn(f"[warn_cl]memoria larga: retrieval no disponible ({type(exc).__name__}: {exc})[/warn_cl]")
        self.cm = ContextManager(n_ctx=self.n_ctx, estimador=self.est, almacen=self.almacen,
                                 recuperador=self.recuperador, task_id=self.task_id, session_id=self.session_id,
                                 print_fn=self.print_fn, peso_schemas=peso, stats=self.stats)
        self.stats.max_activo = self.cm.max_activo
        # el objetivo entra como memoria de nivel 1
        self.registrar("user", task, paso=0)

    # ── gancho 2: extracción incremental ────────────────────────────────────
    def registrar(self, role: str, texto: str, tool: str | None = None, ok=None, paso: int | None = None) -> int:
        """Extrae memorias del mensaje y las guarda (dedup + contradicciones). Devuelve cuántas guardó."""
        if paso is not None:
            self.paso = int(paso)
        try:
            self.stats.tokens_historicos += self.est.texto(texto, "tool" if role == "tool" else "prosa")
        except Exception as exc:
            _LOG.warning("memoria larga: tokens historicos no contados (%s)", exc)
        if self.almacen is None or not texto:
            return 0
        try:
            from cognia.memoria_larga import contradicciones, dedup, extraccion
            nuevas = extraccion.extraer(role, texto, tool=tool, task_id=self.task_id, session_id=self.session_id,
                                        paso=self.paso, ok=ok)
        except Exception as exc:
            _LOG.warning("extracción degradada: %s", exc)
            return 0
        guardadas = 0
        for m in nuevas:
            try:
                dup = dedup.es_duplicada(self.almacen, m)
                if dup is not None:
                    dedup.fusionar(self.almacen, dup, m)
                    self.stats.memorias_fusionadas += 1
                    continue
                vieja = contradicciones.detectar(self.almacen, m)
                mid = self.almacen.guardar(m)
                m.id = mid
                guardadas += 1
                self.memorias_ids.append(mid)
                if vieja is not None:
                    contradicciones.resolver(self.almacen, vieja, m)
                    self.stats.contradicciones += 1
                if m.tipo == "error":
                    self.ultimo_error_id = mid
                    self.errores.append(m.resumen or m.contenido[:120])
                elif m.tipo == "solucion" and self.ultimo_error_id:
                    self.almacen.relacionar(mid, self.ultimo_error_id, "solves")
                elif m.tipo in ("decision", "restriccion"):
                    self.decisiones.append(m.resumen or m.contenido[:120])
                if m.tipo == "fichero" and m.valor:
                    if m.valor not in self.ficheros_abiertos:
                        self.ficheros_abiertos.append(m.valor)
                        self.ficheros_abiertos = self.ficheros_abiertos[-20:]
            except Exception as exc:
                _LOG.warning("no pude guardar una memoria (%s): %s", m.tipo, exc)
        self.stats.memorias_guardadas += guardadas
        return guardadas

    def registrar_respuesta(self, resp, paso: int) -> None:
        """El turno assistant: texto (memorias) e intención (para el checkpoint)."""
        try:
            from cognia.agent.loop import _intencion_de
            self.ultima_intencion = _intencion_de(resp) or self.ultima_intencion
        except Exception as exc:
            _LOG.warning("memoria larga: intencion no derivada (%s)", exc)
            self.ultima_intencion = (getattr(resp, "texto", "") or "")[:160]
        texto = getattr(resp, "texto", "") or ""
        if texto:
            self.registrar("assistant", texto, paso=paso)
        else:
            self.paso = int(paso)

    # ── checkpoint ──────────────────────────────────────────────────────────
    def checkpoint(self, motivo: str, *, mensajes_fuera: int = 0, tokens_fuera: int = 0, intencion: str = "",
                   estado_canal=None, canal_mod=None, ficheros=(), trace=(), estado: str = "en_curso") -> dict:
        next_action = intencion or self.ultima_intencion or ""
        cp = _cp.crear(task_id=self.task_id, session_id=self.session_id, cwd=self.cwd, tarea=self.task,
                       paso=self.paso, motivo=motivo, estado_canal=estado_canal, canal_mod=canal_mod,
                       ficheros=list(ficheros) or self.ficheros_abiertos, trace=trace, next_action=next_action,
                       ultima_intencion=self.ultima_intencion, memorias_ids=self.memorias_ids[-200:],
                       mensajes_fuera=mensajes_fuera, tokens_historicos=self.stats.tokens_historicos,
                       estado=estado, decisiones=self.decisiones[-8:], errores=self.errores[-4:])
        if self.efimero:
            # solo en el almacen (RAM): nada toca el disco del dueno
            try:
                n = self.almacen.checkpoint_guardar(cp) if self.almacen is not None else None
                cp["n"] = n or (self.checkpoint_n + 1)
            except Exception as exc:
                _LOG.warning("memoria larga (efimero): checkpoint en RAM no guardado (%s)", exc)
                cp["n"] = self.checkpoint_n + 1
        else:
            cp = _cp.guardar(cp, self.almacen)
        self.checkpoint_n = int(cp.get("n") or self.checkpoint_n)
        self.stats.checkpoint_n = self.checkpoint_n
        self.ultimo_cp_paso = self.paso
        return cp

    def checkpoint_periodico(self, paso: int, **kw) -> dict | None:
        if paso - self.ultimo_cp_paso >= _CADA_PASOS:
            try:
                return self.checkpoint("periodico", **kw)
            except Exception as exc:
                self.print_fn(f"[warn_cl]checkpoint periódico no escrito ({type(exc).__name__}: {exc})[/warn_cl]")
        return None

    # ── gancho 3: fin de paso ───────────────────────────────────────────────
    def fin_de_paso(self, mensajes: list, est: int, resp=None, *, forzar: bool = False, estado_canal=None,
                    canal_mod=None, trace=(), prompt_tokens_real: int | None = None) -> int | None:
        """Reconstruye el contexto si hace falta. Devuelve los TOKENS liberados (0 si no aplicó), o None si la memoria está apagada."""
        try:
            if prompt_tokens_real:
                self.est.calibrar(mensajes, prompt_tokens_real, self.cm.peso_schemas)
            # El `est` del loop es chars/4 (subestima hasta un 22 %): se toma el
            # mayor entre ese y la estimacion calibrada propia.
            est_eff = max(int(est or 0), self.cm.ocupacion(mensajes))
            self.stats.contexto_usado = est_eff
            intencion = self.ultima_intencion
            info = self.cm.reconstruir(
                mensajes, est_tokens=est_eff, forzar=forzar, intencion=intencion,
                ficheros_abiertos=self.ficheros_abiertos, estado_canal=estado_canal, canal_mod=canal_mod,
                checkpoint_fn=lambda **kw: self.checkpoint(kw.get("motivo", "reconstruccion"),
                                                           mensajes_fuera=kw.get("mensajes_fuera", 0),
                                                           tokens_fuera=kw.get("tokens_fuera", 0),
                                                           intencion=kw.get("intencion", ""),
                                                           estado_canal=estado_canal, canal_mod=canal_mod, trace=trace))
            if info is None:
                self.checkpoint_periodico(self.paso, estado_canal=estado_canal, canal_mod=canal_mod, trace=trace)
                return 0
            return max(0, int(info["tokens_antes"]) - int(info["tokens_despues"]))
        except Exception as exc:
            self.print_fn(f"[warn_cl]memoria larga: reconstrucción fallida ({type(exc).__name__}: {exc}); "
                          f"el loop usa su compactación de siempre[/warn_cl]")
            return 0

    # ── gancho 4: cierre ────────────────────────────────────────────────────
    def cerrar(self, result_text: str, ok: bool, *, estado_canal=None, canal_mod=None, trace=()) -> None:
        try:
            if result_text:
                self.registrar("assistant", result_text, paso=self.paso)
            self.checkpoint("cierre", estado_canal=estado_canal, canal_mod=canal_mod, trace=trace,
                            estado="completa" if ok else "incompleta")
        except Exception as exc:
            self.print_fn(f"[warn_cl]memoria larga: cierre sin checkpoint ({type(exc).__name__}: {exc})[/warn_cl]")
        try:
            if self.almacen is not None:
                self.almacen.cerrar()
        except Exception as exc:
            _LOG.warning("memoria larga: almacen no cerrado limpio (%s)", exc)

    def stats_render(self) -> str:
        return self.stats.render(self.almacen)


def iniciar(task: str, ctx: dict, perfil: dict, print_fn, schemas=None) -> MemoriaTarea | None:
    if not activo():
        return None
    try:
        return MemoriaTarea(task, ctx, perfil, print_fn, schemas)
    except Exception as exc:
        try:
            print_fn(f"[warn_cl]memoria larga no disponible ({type(exc).__name__}: {exc}); el loop sigue sin ella[/warn_cl]")
        except Exception:
            pass
        return None


__all__ = ["MemoriaTarea", "iniciar"]
