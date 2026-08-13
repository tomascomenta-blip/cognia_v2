# -*- coding: utf-8 -*-
"""Hasta DONDE llega el modo RLM de verdad: aguja en pajares de 0,4M a 32M chars.

POR QUE (2026-08-13): el smoke del RLM esta fijado en 400.000 chars (~100k
tokens) porque se escribio cuando la ventana del cerebro era 32768 — "12x mas
grande que su ventana". Hoy la ventana son 200.192 tokens, asi que ESE banco ya
cabe entero en la ventana y no demuestra lo que su nombre promete. Nadie ha
medido el modo por encima de ahi.

Este script mide la escala: mismo protocolo de aguja del smoke (token hex de 8
chars, acierto ESTRICTO textual, pajar determinista) pero barriendo tamanos
crecientes. Por cada escalon reporta acierto, segundos, tokens gastados y el
contexto EFECTIVO que el medidor dice que se vio.

La pregunta que responde: ¿el RLM sostiene el acierto cuando el pajar crece 80x,
o se degrada? Y ¿a que coste?

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\rlm_escala.py [chars...]
      (por defecto: 400k 2M 8M)
Exit: 0 si todos los escalones aciertan; 1 si alguno falla; 3 sin backend.
"""

from __future__ import annotations

import random
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEED = 20260811                  # el mismo del smoke: pajares comparables
HEALTH_TIMEOUT = 8
ESCALONES = [400_000, 2_000_000, 8_000_000]

_FRASES = [
    "El nodo {n} sincronizo su estado con el coordinador sin incidencias.",
    "La revision {n} quedo registrada en la bitacora del turno de la tarde.",
    "El operador anoto que el sensor {n} devolvio una lectura dentro de rango.",
    "Se archivo el expediente {n} tras verificar las firmas correspondientes.",
    "El lote {n} paso el control de calidad con una desviacion despreciable.",
    "La ruta {n} se recalculo por congestion en el tramo intermedio.",
]


def _generar(objetivo_chars: int, ruta: Path):
    """Escribe el pajar a disco en STREAMING y devuelve sus agujas.

    En streaming y no en memoria porque estos pajares llegan a cientos de MB:
    construir la lista de lineas y hacer join tendria el corpus DOS veces en
    RAM y moriria justo en los escalones interesantes.
    """
    random.seed(SEED)
    agujas, acum, i, idx = [], 0, 0, 0
    cortes = sorted({int(objetivo_chars * f) for f in (0.05, 0.5, 0.95)})
    nombres = ["delta", "sigma", "omega"]
    buffer, buf_len = [], 0
    with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
        while acum < objetivo_chars:
            if idx < len(cortes) and acum >= cortes[idx]:
                nombre = nombres[idx]
                token = "%08x" % random.getrandbits(32)
                linea = (f"El codigo de acceso de {nombre} es {token} "
                         f"y no debe compartirse.")
                agujas.append((nombre, token))
                idx += 1
            else:
                linea = random.choice(_FRASES).format(n=i)
                i += 1
                if i % 17 == 0:
                    linea += "\n"
            buffer.append(linea)
            buf_len += len(linea) + 1
            acum += len(linea) + 1
            if buf_len >= 8_000_000:          # volcar cada ~8 MB
                fh.write("\n".join(buffer) + "\n")
                buffer, buf_len = [], 0
        if buffer:
            fh.write("\n".join(buffer) + "\n")
    return agujas


def _salud(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    from cognia.first_run import apply_config
    apply_config()
    from cognia.agent.model_profiles import perfil_del_agente, url_del_backend

    url = url_del_backend()
    if not _salud(url):
        print(f"SIN BACKEND: {url}/health no responde.", flush=True)
        return 3

    perfil = perfil_del_agente(forzar=True)
    n_ctx = perfil.get("n_ctx") or 0
    print(f"cerebro: {perfil.get('modelo')}")
    print(f"ventana del raiz: {n_ctx:,} tokens\n")

    from cognia.agent.rlm import correr_rlm

    escalones = [int(a) for a in sys.argv[1:]] or ESCALONES
    filas, fallos = [], 0
    for chars in escalones:
        ruta = Path(tempfile.mkdtemp(prefix="rlm_esc_")) / "pajar.txt"
        t_gen = time.time()
        agujas = _generar(chars, ruta)
        reales = ruta.stat().st_size
        tok_aprox = reales // 4
        veces_ventana = (tok_aprox / n_ctx) if n_ctx else 0
        print(f"== pajar {reales:,} chars (~{tok_aprox:,} tokens, "
              f"{veces_ventana:.1f}x la ventana) generado en {time.time()-t_gen:.0f}s",
              flush=True)

        # La aguja del MEDIO: la mas dificil de encontrar por busqueda ciega.
        nombre, token = agujas[1] if len(agujas) > 1 else agujas[0]
        t0 = time.time()
        try:
            res = correr_rlm(f"cual es el codigo de acceso de {nombre}?",
                             str(ruta), url=url)
        except Exception as exc:
            print(f"   EXCEPCION: {exc}\n", flush=True)
            filas.append((chars, "EXCEPCION", time.time() - t0, 0, 0.0))
            fallos += 1
            continue
        dt = time.time() - t0
        resp = str(res.get("texto") or "")
        ok = token in resp
        med = res.get("medidor") or {}
        tokens = (med.get("tokens_in_raiz", 0) + med.get("tokens_out_raiz", 0)
                  + med.get("tokens_in_hijos", 0) + med.get("tokens_out_hijos", 0))
        cobertura = med.get("cobertura_union", 0.0)
        print(f"   [{'PASS' if ok else 'FAIL'}] esperado {token} — "
              f"{dt:.0f}s — {tokens:,} tokens — cobertura {cobertura:.4%}")
        if not ok:
            print(f"   respuesta: {resp[:200]}")
            fallos += 1
        pico = med.get("ventana_pico_raiz", 0)
        if n_ctx and pico >= n_ctx:
            print(f"   INVARIANTE ROTA: pico {pico:,} >= ventana {n_ctx:,}")
            fallos += 1
        print(flush=True)
        filas.append((chars, "PASS" if ok else "FAIL", dt, tokens, cobertura))
        try:
            ruta.unlink()
            ruta.parent.rmdir()
        except Exception:
            pass

    print("=" * 62)
    print(f"{'chars':>12} {'result':>8} {'seg':>7} {'tokens':>10} {'cobertura':>11}")
    for chars, res, dt, tokens, cob in filas:
        print(f"{chars:>12,} {res:>8} {dt:>7.0f} {tokens:>10,} {cob:>10.4%}")
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
