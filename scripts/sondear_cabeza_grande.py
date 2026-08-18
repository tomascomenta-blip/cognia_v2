"""Sondeo INDEPENDIENTE de la CABEZA que teje, con n_tasks grande, contra el :8080 vivo.

La averia medida el 2026-08-17: el prompt de la cabeza son ~400 chars de extracto
x n_secciones; con castellano real (4,21 chars/token) 144 secciones daban 15.191
de 16.384 tokens y por encima de ~151 el server devolvia HTTP 400, generate()
devolvia None y `head = ... or ""` se lo tragaba -> documento sin introduccion y
sin una linea de aviso.

Este script mide las DOS cosas contra el server real, sin correr un solo worker
(los drafts son prosa castellana sintetica del tamano real):
  A) el prompt VIEJO (extracto fijo de 400 chars) -- cuantos tokens ocupa y si el
     server lo rechaza de verdad;
  B) el camino NUEVO (_cabeza_tejida) -- a cuanto encoge el extracto, si el prompt
     entra en el presupuesto, si devuelve introduccion y si algun fallo sale por
     meta['error'] en vez de en silencio.

Uso:
  venv312/Scripts/python.exe scripts/sondear_cabeza_grande.py [--ns 144,151,160,200]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from node.llama_backend import LlamaBackend, _LlamaServerBackend
from shattering.model_constants import (
    GEN_CHAT_TEMPERATURE, GEN_CTX_GUARD_RATIO, GEN_CTX_MARGIN_TOKENS,
    GEN_HEAD_MAX_TOKENS,
)

PORT = 8080
PEDIDO = ("Escribe un manual exhaustivo en espanol sobre ingenieria de sistemas "
          "distribuidos.")

# Prosa castellana real: lo que importa es la densidad chars/token (4,21 medidos),
# no el contenido. Un draft de laboratorio en ASCII pelado mide distinto.
PARRAFO = (
    "La replicación de estado en un sistema distribuido exige acordar un orden "
    "total de operaciones entre réplicas que fallan de forma independiente; el "
    "protocolo de consenso garantiza que ninguna decisión comprometida se revierta "
    "aunque una minoría de nodos quede particionada de la red durante un intervalo "
    "arbitrariamente largo, y el registro de operaciones se compacta con instantáneas "
    "periódicas para que la recuperación de un nodo caído no dependa del histórico. "
)


def draft(i: int, chars: int = 3000) -> tuple:
    """Un draft de seccion del tamano tipico medido (~1.400 tok = ~5.900 chars).

    Solo se leen los primeros `extracto_chars` de cada uno, asi que 3.000 chars
    alcanzan para que ningun paso del encogido se quede corto de texto."""
    cuerpo = (PARRAFO * (chars // len(PARRAFO) + 2))[:chars]
    return (f"Sección {i + 1}: consenso, replicación y tolerancia a fallos", cuerpo)


def main(argv: list) -> int:
    ns = [144, 151, 160, 200]
    for i, a in enumerate(argv):
        if a == "--ns":
            ns = [int(x) for x in argv[i + 1].split(",")]

    impl = _LlamaServerBackend(Path("adoptado.gguf"), port=PORT)
    if impl._proc is not None:
        print("ABORTO: se levanto un server nuevo, no se adopto el vivo")
        return 2
    be = LlamaBackend(impl)
    ctx = be.n_ctx_efectivo()
    presupuesto = min(int(ctx * GEN_CTX_GUARD_RATIO),
                      ctx - GEN_HEAD_MAX_TOKENS - GEN_CTX_MARGIN_TOKENS)
    print(f"[ctx] n_ctx_efectivo={ctx}  presupuesto_cabeza={presupuesto} tok", flush=True)

    ok = True
    for n in ns:
        drafts = [draft(i) for i in range(n)]

        # ---- A) el prompt VIEJO: 400 chars fijos, sin medir nada -------------
        viejo = be._head_prompt(PEDIDO, drafts, 400)
        tok_viejo = be.contar_tokens(viejo)
        chars_por_tok = round(len(viejo) / max(1, tok_viejo), 2)
        cabe = tok_viejo <= presupuesto

        # ---- B) el camino NUEVO ---------------------------------------------
        t0 = time.time()
        txt, meta = be._cabeza_tejida(PEDIDO, drafts, GEN_CHAT_TEMPERATURE)
        dt = time.time() - t0

        fila = {
            "n": n,
            "viejo_tok": tok_viejo,
            "viejo_cabe_en_presupuesto": cabe,
            "viejo_cabe_en_ctx": tok_viejo <= ctx,
            "chars_por_tok": chars_por_tok,
            "nuevo_extracto_chars": meta["extracto_chars"],
            "nuevo_prompt_tok": meta["prompt_tokens"],
            "nuevo_bloques": meta["bloques"],
            "nuevo_error": meta["error"],
            "hay_introduccion": bool(txt.strip()),
            "intro_chars": len(txt.strip()),
            "s": round(dt, 1),
        }
        print("  " + json.dumps(fila, ensure_ascii=False), flush=True)
        if txt.strip():
            print(f"      intro: {txt.strip()[:160]}", flush=True)
        # CHECK: o hay introduccion, o hay un error explicito. Nunca las dos vacias.
        if not txt.strip() and not meta["error"]:
            print(f"      FALLO MUDO a n={n}: sin introduccion y sin error", flush=True)
            ok = False
        if meta["prompt_tokens"] is not None and meta["prompt_tokens"] > presupuesto:
            print(f"      FALLO: se mando un prompt de {meta['prompt_tokens']} tok "
                  f"contra un presupuesto de {presupuesto}", flush=True)
            ok = False

    # ---- C) prueba directa de que el prompt VIEJO lo RECHAZA el server -------
    # Una sola llamada, con el n mas grande sondeado: si el viejo no cabia, el
    # server tiene que contestar 400 (generate -> None). Es el contrafactual.
    n = max(ns)
    viejo = be._head_prompt(PEDIDO, [draft(i) for i in range(n)], 400)
    tok_viejo = be.contar_tokens(viejo)
    if tok_viejo > ctx:
        t0 = time.time()
        r = be.generate(viejo, max_tokens=GEN_HEAD_MAX_TOKENS,
                        temperature=GEN_CHAT_TEMPERATURE)
        print(f"[contrafactual] prompt VIEJO a n={n} ({tok_viejo} tok > ctx {ctx}): "
              f"generate -> {'None (rechazado)' if r is None else 'RESPONDIO'} "
              f"en {time.time()-t0:.1f}s", flush=True)
        if r is not None:
            print("      OJO: el server NO lo rechazo; la premisa del fix cambia",
                  flush=True)
    else:
        print(f"[contrafactual] a n={n} el prompt viejo aun cabe en el ctx "
              f"({tok_viejo} <= {ctx}): no hay 400 que reproducir", flush=True)

    print("\n[VEREDICTO] " + ("OK: ninguna cabeza fallo en silencio"
                              if ok else "HAY FALLO MUDO"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
