# -*- coding: utf-8 -*-
"""La ventana EFICAZ del cerebro: donde deja de servir, no donde deja de caber.

POR QUE (2026-08-13): la ventana fisica del server son 200.192 tokens, pero
"cabe" y "se entera" son cosas distintas. Este banco mide las dos fronteras que
importan, DENTRO de la ventana y sin RLM (prompt directo):

  RECUPERAR : una aguja literal en el pajar. Es el liston BAJO -- si falla aqui,
              la ventana no sirve para nada a esa longitud.
  RAZONAR   : DOS agujas separadas que hay que combinar (sumar dos numeros que
              estan en extremos opuestos del contexto). Es el liston que importa
              de verdad: casi todos los modelos aguantan NIAH mucho mas alla de
              donde ya no pueden RAZONAR sobre lo que leyeron.

Cada punto se prueba a tres profundidades (10%, 50%, 90%) porque la degradacion
no es uniforme: el medio del contexto es lo primero que se pierde ("lost in the
middle").

Acierto ESTRICTO: el valor exacto, textual, en la respuesta. Un parafraseo o un
numero aproximado cuentan como fallo.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\ventana_eficaz.py [longitudes...]
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEED = 20260813
URL = "http://127.0.0.1:8080"
LONGITUDES = [4_000, 16_000, 64_000, 128_000, 190_000]
PROFUNDIDADES = [0.1, 0.5, 0.9]

_FRASES = [
    "El turno {n} cerro sin incidencias reportadas por el equipo de guardia.",
    "La medicion {n} se archivo junto al resto del lote correspondiente.",
    "El informe {n} quedo pendiente de revision por el area tecnica.",
    "Se anoto que el canal {n} mantuvo su nivel dentro del margen previsto.",
    "La entrega {n} figura registrada con su comprobante correspondiente.",
]


def post(carga: dict, timeout: int = 1200) -> dict:
    req = urllib.request.Request(
        URL + "/v1/chat/completions", data=json.dumps(carga).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _relleno(n_frases: int, rnd) -> list:
    return [rnd.choice(_FRASES).format(n=i) for i in range(n_frases)]


def _pajar(tokens_objetivo: int, insertos: list, rnd) -> str:
    """Pajar con `insertos` = [(fraccion, linea)] colocados por posicion."""
    # ~4 chars por token con este texto; se ajusta midiendo despues.
    n_frases = max(10, int(tokens_objetivo * 4 / 62))
    lineas = _relleno(n_frases, rnd)
    for fraccion, linea in sorted(insertos, key=lambda x: -x[0]):
        lineas.insert(int(len(lineas) * fraccion), linea)
    return "\n".join(lineas)


def _tokens(texto: str) -> int:
    req = urllib.request.Request(
        URL + "/tokenize", data=json.dumps({"content": texto}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return len(json.loads(r.read().decode()).get("tokens", []))


def _preguntar(pajar: str, pregunta: str) -> tuple:
    """(respuesta, segundos, finish_reason). max_tokens GRANDE a proposito.

    Qwythos es un RAZONADOR: piensa en `reasoning_content` antes de emitir
    `content`. Con un presupuesto corto agota los tokens pensando y devuelve
    content VACIO -- que no es "no encontro la aguja", es "no llego a
    contestar". Esa confusion es la leccion de los 10 bugs identicos del repo,
    y aqui falsearia la ventana eficaz hacia abajo. Por eso se devuelve tambien
    el finish_reason: 'length' significa INSTRUMENTO, no modelo.
    """
    t0 = time.time()
    r = post({"messages": [
        {"role": "system", "content": "Responde SOLO con el dato pedido, sin explicar."},
        {"role": "user", "content": f"{pajar}\n\n{pregunta}"}],
        "max_tokens": 4096, "temperature": 0})
    elec = (r.get("choices") or [{}])[0]
    msg = elec.get("message") or {}
    return ((msg.get("content") or "").strip(), time.time() - t0,
            elec.get("finish_reason") or "")


def main() -> int:
    from cognia.first_run import apply_config
    apply_config()

    longitudes = [int(a) for a in sys.argv[1:]] or LONGITUDES
    rnd = random.Random(SEED)
    print(f"{'tokens':>8} {'prof':>6} {'recuperar':>10} {'razonar':>9} "
          f"{'seg_r':>7} {'seg_z':>7}")
    print("-" * 54)

    resumen = []
    for objetivo in longitudes:
        for prof in PROFUNDIDADES:
            # --- RECUPERAR: una aguja literal
            token = "%08x" % rnd.getrandbits(32)
            aguja = f"El codigo de acceso del sector norte es {token}."
            pajar = _pajar(objetivo, [(prof, aguja)], rnd)
            n_tok = _tokens(pajar)
            resp_r, seg_r, fin_r = _preguntar(
                pajar, "Cual es el codigo de acceso del sector norte?")
            ok_r = token in resp_r

            # --- RAZONAR: dos numeros en extremos opuestos, hay que sumarlos
            a, b = rnd.randint(1000, 4999), rnd.randint(1000, 4999)
            suma = a + b
            l1 = f"El contador principal marco {a} unidades ese dia."
            l2 = f"El contador auxiliar marco {b} unidades ese mismo dia."
            # uno cerca del principio, otro cerca del final: obliga a usar ambos
            pajar2 = _pajar(objetivo, [(0.08, l1), (0.92, l2)], rnd)
            resp_z, seg_z, fin_z = _preguntar(
                pajar2, "Cuanto suman las unidades del contador principal mas "
                        "las del contador auxiliar? Responde solo el numero.")
            ok_z = str(suma) in resp_z.replace(".", "").replace(",", "")

            # 'length' con content vacio = el razonador se quedo sin presupuesto:
            # es fallo del INSTRUMENTO y se marca aparte para no contarlo contra
            # la ventana del modelo.
            def _marca(ok, resp, fin):
                if ok:
                    return "PASS"
                return "sin-tok" if (fin == "length" and not resp) else "FALLO"

            m_r, m_z = _marca(ok_r, resp_r, fin_r), _marca(ok_z, resp_z, fin_z)
            print(f"{n_tok:>8,} {prof:>6.0%} {m_r:>10} {m_z:>9} "
                  f"{seg_r:>7.0f} {seg_z:>7.0f}", flush=True)
            if not ok_r:
                print(f"         recuperar esperaba {token} [{fin_r}] -> {resp_r[:80]!r}")
            if not ok_z:
                print(f"         razonar esperaba {suma} ({a}+{b}) [{fin_z}] -> {resp_z[:80]!r}")
            resumen.append((n_tok, prof, ok_r, ok_z))

    print("\n== ventana eficaz ==")
    for etiqueta, idx in (("RECUPERAR", 2), ("RAZONAR", 3)):
        por_long = {}
        for fila in resumen:
            por_long.setdefault(fila[0] // 1000, []).append(fila[idx])
        buenas = [k for k, v in sorted(por_long.items()) if all(v)]
        ultima = f"~{max(buenas):,}k tokens" if buenas else "falla ya en el punto mas corto"
        parciales = [k for k, v in sorted(por_long.items()) if any(v) and not all(v)]
        extra = f" (parcial hasta {max(parciales):,}k)" if parciales else ""
        print(f"  {etiqueta:10} 3/3 profundidades hasta {ultima}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
