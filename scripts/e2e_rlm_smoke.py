# -*- coding: utf-8 -*-
"""Smoke e2e del modo RLM — agujas hex en ~400k chars contra el backend real.

POR QUE: los tests de tests/test_rlm.py guionan el completar y jamas tocan un
modelo de verdad; este smoke es la unica pieza que prueba que el raiz REAL
(tool-calling nativo) navega un contexto ~12x mas grande que su ventana con
las 5 tools RLM y saca la aguja EXACTA. El acierto es ESTRICTO: el token hex
de 8 chars aparece textual en la respuesta — un parafraseo o un token
inventado cuentan como FAIL (la leccion del campo de acierto sin declarar:
con el criterio permisivo el banco no decide nada).

El pajar es determinista (seed 20260811): misma corrida, mismo pajar, mismas
agujas — los numeros de linea del informe son comparables entre corridas.

Requiere la flota arriba; si /health no responde sale con exit 3 y mensaje
claro (timeout corto, jamas se cuelga esperando un server muerto).

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_rlm_smoke.py
Salida: PASS/FAIL + informe del medidor por pregunta; 'E2E RLM SMOKE: N/3 OK'.
Exit: 0 si 3/3 y las invariantes del medidor pasan; 1 si no; 3 sin backend.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SEED = 20260811
OBJETIVO_CHARS = 400_000
HEALTH_TIMEOUT = 5

# Nombres fijos (no sorteados): la pregunta se arma por nombre y tiene que
# ser identica entre corridas para que un FAIL sea comparable con el anterior.
_NOMBRES = ["Amaranta", "Baltasar", "Casilda", "Demetrio", "Eulalia",
            "Fructuoso"]
# Fracciones del pajar donde va cada aguja: bordes y medio, porque un
# selector vago falla distinto en cada zona (recencia, primacia, medio).
_FRACCIONES = [0.03, 0.21, 0.42, 0.58, 0.79, 0.97]

_PALABRAS = ("sistema modelo contexto ventana memoria indice registro "
             "proceso archivo modulo bitacora medidor informe corrida "
             "verificacion presupuesto fragmento respuesta pregunta "
             "resultado servidor cliente linea trozo patron origen "
             "cobertura union limite guarda bucle turno paso herramienta "
             "prueba banco relleno parrafo").split()


def _generar_contexto():
    """(texto, [(nombre, token), ...]) determinista con seed fijo.

    Relleno de frases variadas (no una pared repetida: un pajar de una sola
    frase se comprime en la ventana y el smoke dejaria de medir busqueda).
    """
    random.seed(SEED)
    agujas = [(n, "".join(random.choice("0123456789abcdef") for _ in range(8)))
              for n in _NOMBRES]
    lineas, acum = [], 0
    while acum < OBJETIVO_CHARS:
        frase = " ".join(random.choice(_PALABRAS)
                         for _ in range(random.randint(8, 14)))
        linea = frase.capitalize() + "."
        lineas.append(linea)
        acum += len(linea) + 1
        # Lineas en blanco sueltas: parrafos, para que el pajar no sea una
        # pared uniforme que el modelo pueda ignorar en bloque.
        if random.random() < 0.2:
            lineas.append("")
            acum += 1
    # De atras hacia adelante: insertar primero las fracciones altas evita
    # que cada insert corra los indices de las agujas que faltan.
    for frac, (nombre, token) in sorted(zip(_FRACCIONES, agujas),
                                        reverse=True):
        idx = int(len(lineas) * frac)
        lineas.insert(idx, f"El codigo de acceso de {nombre} es {token}")
    return "\n".join(lineas), agujas


def _salud_backend(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health",
                                    timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    from cognia.first_run import apply_config
    apply_config()
    from cognia.agent.model_profiles import url_del_backend
    url = url_del_backend()
    if not _salud_backend(url):
        print(f"SIN BACKEND: {url}/health no responde en {HEALTH_TIMEOUT}s. "
              "Levanta la flota (scripts/servir_flota.py) y reintenta.",
              flush=True)
        sys.exit(3)

    from cognia.agent.rlm import correr_rlm

    texto, agujas = _generar_contexto()
    ruta = Path(tempfile.mkdtemp(prefix="rlm_smoke_")) / "pajar.txt"
    ruta.write_text(texto, encoding="utf-8")
    print(f"contexto sintetico: {len(texto):,} chars | {len(agujas)} agujas "
          f"| {ruta}", flush=True)

    # Tres zonas distintas del pajar (inicio/medio/final): las agujas no
    # preguntadas quedan como distractores del mismo formato.
    elegidas = [agujas[0], agujas[3], agujas[5]]
    aciertos, invariantes_rotas = 0, []
    t0 = time.time()
    for nombre, token in elegidas:
        t1 = time.time()
        res = correr_rlm(f"cual es el codigo de acceso de {nombre}?",
                         str(ruta), url=url)
        texto_resp = str(res.get("texto") or "")
        # Acierto ESTRICTO: el token hex exacto, textual, en la respuesta.
        ok = token in texto_resp
        aciertos += 1 if ok else 0
        print(f"\n[{'PASS' if ok else 'FAIL'}] {nombre} "
              f"({time.time() - t1:.0f}s) — esperado {token} — "
              f"resp: {texto_resp[:160]}", flush=True)
        print(res.get("informe") or "(sin informe)", flush=True)
        # Invariantes del medidor: si el modo "funciona" violandolas, el
        # PASS seria de un modo distinto al contratado (p.ej. contexto
        # entero colado en la ventana del raiz).
        med = res.get("medidor") or {}
        n_ctx = med.get("n_ctx") or 0
        pico = med.get("ventana_pico_raiz", 0)
        if n_ctx and pico >= n_ctx:
            invariantes_rotas.append(
                f"{nombre}: ventana pico raiz {pico} >= n_ctx {n_ctx}")
        if med.get("cobertura_union", 0.0) <= 0.0:
            invariantes_rotas.append(f"{nombre}: cobertura union en 0 "
                                     "(no se toco el contexto)")
        hijos, max_hijos = med.get("llamadas_hijo", 0), med.get("max_hijos", 0)
        if max_hijos and hijos > max_hijos:
            invariantes_rotas.append(
                f"{nombre}: {hijos} subllamadas superan el limite {max_hijos}")

    print(f"\nE2E RLM SMOKE: {aciertos}/3 OK en "
          f"{(time.time() - t0) / 60:.1f} min", flush=True)
    for inv in invariantes_rotas:
        print(f"INVARIANTE ROTA: {inv}", flush=True)
    sys.exit(0 if aciertos == 3 and not invariantes_rotas else 1)


if __name__ == "__main__":
    main()
