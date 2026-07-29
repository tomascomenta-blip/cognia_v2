"""
bon.py — best-of-N de réplicas INDEPENDIENTES con selector de señal real.

POR QUÉ EXISTE (2026-07-28, PREREG_BON_HELDOUT). Medido en el banco brutal:
4 réplicas independientes de primgen llevan el control de 17/24 a 24/24, y
un selector que solo ve un contrato held-out captura TODO el margen. La
diversidad viene de REHACER el pipeline por muestra (mockup nuevo, hints
nuevos) — NO de subir la temperatura (0.9 pierde los selectores obligatorios
del enunciado) y NO de re-generar dentro del lazo con el mismo prompt (eso
produce clones: KILL del 2026-07-26).

La pieza que falta para que esto sea el default es el SELECTOR para tareas
no vistas: la señal interna autogenerada está al nivel del azar (4 KILL,
memoria contrato-interno-al-azar), así que este modo exige un contrato
selector EXTERNO (held-out a mano, como los del banco). Sin selector no hay
selección: se degrada RUIDOSAMENTE a una sola réplica, no se elige al azar
ni con la señal muerta.

Modo env-gated (default actual intacto):
    COGNIA_BON_K        — nº de réplicas (default 1 = camino de siempre)
    COGNIA_BON_SELECTOR — ruta a un JSON con el contrato selector

Los knobs de env son para operar el modo en tareas CONOCIDAS (banco, gates);
el código de llamada también puede pasar k/contrato_selector explícitos.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

BON_K_ENV = "COGNIA_BON_K"
BON_SELECTOR_ENV = "COGNIA_BON_SELECTOR"


def k_configurado() -> int:
    """K desde el env; 1 (default) = el camino de siempre, sin BoN."""
    try:
        return max(1, int(os.environ.get(BON_K_ENV, 1)))
    except (TypeError, ValueError):
        return 1


def selector_configurado() -> Optional[dict]:
    """Contrato selector desde COGNIA_BON_SELECTOR (ruta a JSON), o None.
    Un path configurado pero ilegible es un error de operación: se avisa
    (degradación silenciosa es el modo de fallo típico de este repo)."""
    ruta = os.environ.get(BON_SELECTOR_ENV, "").strip()
    if not ruta:
        return None
    try:
        c = json.loads(Path(ruta).read_text(encoding="utf-8"))
        return c if isinstance(c, dict) and c.get("pasos") else None
    except Exception as exc:
        print(f"[bon] COGNIA_BON_SELECTOR={ruta} ilegible: {exc}", flush=True)
        return None


def construir_bon(idea: str, *, k: Optional[int] = None,
                  contrato_selector: Optional[dict] = None,
                  guardar_muestras: Optional[Path] = None,
                  verbose: bool = True, **kwargs):
    """
    Genera K réplicas independientes del lazo completo y entrega la que el
    contrato selector prefiere. Devuelve el ResultadoDiseno elegido con
    `res.bon` = metadatos del muestreo (k, elegida, tabla de muestras).

    Sin selector (o k=1) delega tal cual en construir_para_mockup: el
    default del sistema no cambia. Una réplica que crashea no mata el modo
    (cuenta como muestra sin HTML); si ninguna produce HTML se devuelve la
    última con su motivo, como haría el camino de siempre.
    """
    from .diseno_a_codigo import construir_para_mockup
    from . import juez_ejecutable

    k = k if k is not None else k_configurado()
    if contrato_selector is None:
        contrato_selector = selector_configurado()
    if k <= 1:
        return construir_para_mockup(idea, verbose=verbose, **kwargs)
    if not contrato_selector:
        print(f"[bon] K={k} pedido SIN contrato selector: la señal interna "
              f"está al nivel del azar (no se elige con ella); se corre UNA "
              f"réplica. Da un held-out via {BON_SELECTOR_ENV}.", flush=True)
        return construir_para_mockup(idea, verbose=verbose, **kwargs)

    muestras = []
    ultimo_res = None
    tmp = None
    if guardar_muestras is None:
        tmp = tempfile.TemporaryDirectory(prefix="cognia_bon_")
        guardar_muestras = Path(tmp.name)
    guardar_muestras = Path(guardar_muestras)
    try:
        for s in range(1, k + 1):
            t0 = time.time()
            fila = {"s": s}
            res = None
            try:
                # Réplica INDEPENDIENTE: pipeline entero de nuevo. El estado
                # aleatorio avanza solo entre llamadas (hints/feromona); no
                # se toca la temperatura (prior en contra, medido).
                res = construir_para_mockup(idea, verbose=verbose, **kwargs)
            except Exception as exc:
                fila["error"] = f"{type(exc).__name__}: {exc}"[:100]
            html = None
            if res is not None:
                ultimo_res = res
                try:
                    html = res.html_entregable() or res.html
                except Exception:
                    html = res.html
            if html:
                d = guardar_muestras / f"s{s}"
                d.mkdir(parents=True, exist_ok=True)
                (d / "index.html").write_text(html, encoding="utf-8")
                try:
                    v = juez_ejecutable.juzgar_web(d / "index.html",
                                                   contrato_selector)
                    fila.update(
                        aprobado_sel=bool(v.aprobado),
                        checks_ok_sel=sum(1 for c in v.checks if c.ok))
                except Exception as exc:
                    # juez caído = muestra sin ranking, no modo roto
                    fila.update(aprobado_sel=None, checks_ok_sel=-1,
                                sel_crasheo=f"{exc}"[:80])
                fila["res"] = res
            fila["segundos"] = round(time.time() - t0, 1)
            muestras.append(fila)
            if verbose:
                print(f"[bon] muestra {s}/{k}: "
                      f"{'sin HTML' if 'res' not in fila else 'sel=' + str(fila.get('aprobado_sel'))}"
                      f" ({fila['segundos']}s)", flush=True)

        con_html = [m for m in muestras if "res" in m]
        if not con_html:
            # Ninguna réplica entregó: se devuelve el último resultado vivo
            # (su motivo_corte explica) o el fracaso explícito.
            if ultimo_res is None:
                raise RuntimeError(
                    f"bon: las {k} réplicas crashearon: "
                    + "; ".join(m.get("error", "?") for m in muestras))
            elegida = None
            res = ultimo_res
        else:
            # Selector: aprobado > checks_ok > la más temprana. El mismo
            # orden que capturó el 100% del margen en PREREG_BON_HELDOUT.
            mejor = sorted(con_html,
                           key=lambda m: (not m.get("aprobado_sel"),
                                          -(m.get("checks_ok_sel") or 0),
                                          m["s"]))[0]
            elegida = mejor["s"]
            res = mejor["res"]
        res.bon = {
            "modo": "replicas_independientes", "k": k, "elegida_s": elegida,
            "muestras": [{kk: v for kk, v in m.items() if kk != "res"}
                         for m in muestras]}
        if verbose:
            print(f"[bon] elegida s{elegida} de {len(con_html)}/{k} con HTML",
                  flush=True)
        return res
    finally:
        if tmp is not None:
            tmp.cleanup()
