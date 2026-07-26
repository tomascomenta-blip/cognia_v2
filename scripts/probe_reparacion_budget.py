"""
probe_reparacion_budget.py — ¿de que muere reparar_web con gpt-oss de cerebro?

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\probe_reparacion_budget.py [n]

CONTEXTO (2026-07-26, brazo BoN de PREREG_BON_RONDAS_20260726.md): en la
replica 1, CUATRO de cuatro reparaciones murieron con "el modelo no devolvio
una correccion valida" (generar devolvio vacio -> _call_llm cayo al 404 de
Ollama), cuando 40 minutos antes run9 habia reparado 4 de 4 con el mismo
server y el mismo presupuesto (12000). La auditoria acota: la reparacion de
calculadora tardo ~99s entre registro y DEGRADADO — a la velocidad del 20B eso
es ~el presupuesto entero, o sea razonamiento que se lo come todo (la clase de
bug numero 6 de presupuesto-tokens-razonamiento) — o el timeout de 120s de
TIMEOUT_GEN cortando por debajo (otra cara de la misma clase).

Esta sonda reproduce las CONDICIONES exactas: el index.html FALLIDO que dejo
el brazo, sus contraejemplos reales del juez, el prompt literal de
reparar_web, el mismo endpoint. Y mira finish_reason + usage ANTES de culpar
a nadie (leccion: descartar-hipotesis-reproduce-condiciones).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TAREAS = RAIZ / "scripts" / "b1_tareas.json"
PRODUCTO = (RAIZ / "cognia" / "program_creator" / "generated_programs"
            / "b2_sistema_real" / "calculadora" / "index.html")


def main(argv: list) -> int:
    n = int(argv[0]) if argv else 3
    from cognia.program_creator import juez_ejecutable
    from cognia.program_creator.generator import _SISTEMA_WEB

    tarea = next(t for t in json.loads(TAREAS.read_text(encoding="utf-8"))
                 ["tareas"] if t["id"] == "calculadora")
    codigo = PRODUCTO.read_text(encoding="utf-8")

    v = juez_ejecutable.juzgar_web(PRODUCTO, tarea["contrato"])
    contraejemplos = [f"(juez) {c.nombre}: {c.detalle}"
                      for c in v.checks if not c.ok]
    print(f"producto: {PRODUCTO.name} ({len(codigo)} chars), juez: "
          f"{'APROBADO' if v.aprobado else 'FALLIDO'}, "
          f"{len(contraejemplos)} contraejemplos", flush=True)

    lista = "\n".join(f"- {d}" for d in contraejemplos or
                      ["- (sin contraejemplos: producto aprobado; se sondea igual)"])
    prompt = (
        f"This HTML page was rendered in a real browser and these problems were "
        f"OBSERVED (not guessed):\n{lista}\n\n"
        f"Fix ONLY those problems. Keep the design and the rest of the code.\n"
        f"Remember: a rule like `.row.up span` only applies if the class 'up' "
        f"lands on the element matching `.row`, not on the inner span.\n\n"
        f"Current page:\n```html\n{codigo}\n```\n\n"
        f"Respond EXACTLY in this format:\n\n"
        f"Title: Calculadora\nDescription: d\n"
        f"HTML Code:\n```html\n<!DOCTYPE html>\n<fixed page>\n```"
    )

    # --reasoning-low: prefija la directiva Harmony al system (el fix que cerro
    # la espiral de generar_contrato). Sin flag: la config de produccion actual.
    # --template-low: chat_template_kwargs.reasoning_effort=low (la via nativa
    # de llama-server para fijar el esfuerzo Harmony REAL, no una linea en el
    # developer message). --dump: guarda el razonamiento del intento 1.
    system = _SISTEMA_WEB
    if "--reasoning-low" in argv:
        system = "Reasoning: low\n\n" + system
        print("  (con Reasoning: low en el system)", flush=True)
    payload_extra = {}
    if "--template-low" in argv:
        payload_extra["chat_template_kwargs"] = {"reasoning_effort": "low"}
        print("  (con chat_template_kwargs.reasoning_effort=low)", flush=True)

    for i in range(1, n + 1):
        t0 = time.time()
        req = urllib.request.Request(
            "http://127.0.0.1:8080/v1/chat/completions",
            data=json.dumps({
                "model": "local",
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 12000,
                **payload_extra,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            print(f"  intento {i}: EXCEPCION {type(exc).__name__}: {exc} "
                  f"({time.time()-t0:.0f}s)", flush=True)
            continue
        ch = data["choices"][0]
        msg = ch.get("message", {})
        contenido = msg.get("content") or ""
        razonamiento = msg.get("reasoning_content") or ""
        u = data.get("usage", {})
        print(f"  intento {i}: finish={ch.get('finish_reason')!r} "
              f"contenido={len(contenido)}ch razonamiento={len(razonamiento)}ch "
              f"completion_tokens={u.get('completion_tokens')} "
              f"prompt_tokens={u.get('prompt_tokens')} "
              f"({time.time()-t0:.0f}s)", flush=True)
        if "--dump" in argv and i == 1:
            destino = RAIZ / "scripts" / "probe_reparacion_razonamiento.txt"
            destino.write_text(razonamiento or contenido, encoding="utf-8")
            print(f"  razonamiento volcado a {destino.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
