# -*- coding: utf-8 -*-
"""
b4_lora_f0_gate.py — FASE 0 del PREREG_LORAS_20260801 (enmienda 1): gate de
ACTIVIDAD del pipeline GGUF-LoRA contra el no-op silencioso.

UN solo proceso de llama-server arrancado con
    --lora <adapter> --lora-init-without-apply --parallel 1
(sin draft: se lanza directo, no via servir_modelo.py). Tres condiciones por
el endpoint de runtime, en este orden:
    A = estado inicial (adapter cargado, NO aplicado)
    C = POST /lora-adapters scale 0.0   (debe ser = A token a token)
    B = POST /lora-adapters scale 1.0   (debe diferir de A en >=1 prompt)
`cache_prompt: false` en toda peticion (el KV bajo la escala anterior
contaminaria en silencio). Decodificacion determinista (temp 0, top_k 1).

PASS = B!=A en >=1 prompt  Y  C==A en TODOS  Y  B coherente  Y  sin errores
de carga. Rescate pre-registrado: si C!=A, se vuelcan los logprobs de la
primera divergencia; margen de argmax <1e-3 = limite del instrumento (el
gate PASA con B!=A y B!=C y C~=A), no KILL.

ADAPTACION 2026-08-09 (PREREG_LORA_QWYTHOS_20260809): 4o prompt CON tools
nativas via /v1/chat/completions — la conducta entrenada del LoRA de Qwythos
es tool-calling, y un gate de actividad que no ejercita esa via podria dar
PASS con un adapter que solo mueve prosa. Los 3 prompts /completion quedan
identicos y el protocolo S0->S1->S0 esta intacto: el prompt de tools corre
en los tres estados como uno mas. Su "texto" comparado es la serializacion
canonica de TODO lo emitido (reasoning + content + tool_calls con arguments
crudos): cualquier cambio del adapter en cualquier canal cuenta como B!=A.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "b4_loras"
URL = "http://127.0.0.1:8090"   # se puede pisar con --url (F2: 8092)

PROMPTS = [
    "If a train travels 60 km in 40 minutes, how far does it travel in 2 "
    "hours at the same speed? Think step by step and give the answer.",
    "Write a Python function that returns the n-th Fibonacci number "
    "iteratively.",
    "Describe in two sentences what a hash table is.",
]

# 4o prompt: tool-calling nativo (la conducta que el LoRA entrena). Schema
# inline y minimo — el script es standalone contra un server lanzado a mano,
# no importa cognia (mismo criterio que los 3 prompts historicos).
PROMPT_TOOLS = ("Crea el archivo notas.txt con el contenido exacto: hola "
                "mundo. Usa la herramienta.")
TOOLS_NATIVAS = [{
    "type": "function",
    "function": {
        "name": "escribir_archivo",
        "description": "Escribe contenido en un archivo del workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string",
                         "description": "Ruta relativa del archivo"},
                "contenido": {"type": "string",
                              "description": "Contenido exacto a escribir"},
            },
            "required": ["ruta", "contenido"],
        },
    },
}]


def _post(ruta: str, cuerpo: dict) -> dict:
    req = urllib.request.Request(
        f"{URL}{ruta}", data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _escala(s: float) -> None:
    _post("/lora-adapters", [{"id": 0, "scale": s}])


def _completa(prompt: str) -> dict:
    return _post("/completion", {
        "prompt": prompt, "n_predict": 128, "temperature": 0.0, "top_k": 1,
        "seed": 20260801, "cache_prompt": False, "n_probs": 5})


def _serializa_chat(r: dict) -> tuple:
    """(texto canonico, n_tool_calls, finish_reason) de /v1/chat/completions.

    POR QUE serializar TODO (reasoning + content + tool_calls crudos): el
    gate mide ACTIVIDAD; un adapter que solo cambia el pensamiento o solo
    los arguments tambien debe contar como B!=A. arguments se deja como el
    JSON crudo del server (byte a byte, sin re-serializar) para que la
    comparacion sea determinista."""
    msg = (r.get("choices") or [{}])[0].get("message") or {}
    finish = (r.get("choices") or [{}])[0].get("finish_reason") or ""
    partes = []
    if msg.get("reasoning_content"):
        partes.append("<razonamiento>" + msg["reasoning_content"])
    partes.append("<contenido>" + (msg.get("content") or ""))
    tcs = msg.get("tool_calls") or []
    for tc in tcs:
        fn = tc.get("function") or {}
        partes.append("<tool>%s(%s)" % (fn.get("name", ""),
                                        fn.get("arguments", "")))
    return "\n".join(partes), len(tcs), finish


def _completa_tools() -> dict:
    """El 4o prompt: tool-calling nativo, determinista, cache_prompt false.

    max_tokens 1024 (no 128): con un razonador el presupuesto tiene que
    cubrir el PENSAMIENTO o el corte decapita la respuesta y el gate mide
    truncado, no actividad (memoria: presupuesto-tokens-razonamiento; por
    eso finish_reason se guarda y se imprime)."""
    r = _post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": PROMPT_TOOLS}],
        "tools": TOOLS_NATIVAS, "temperature": 0.0, "top_k": 1,
        "seed": 20260801, "max_tokens": 1024, "cache_prompt": False})
    texto, n_tc, finish = _serializa_chat(r)
    return {"prompt": "[tools] " + PROMPT_TOOLS[:32], "texto": texto,
            "tokens": [], "es_tools": True, "n_tool_calls": n_tc,
            "finish": finish}


def _corre(nombre: str) -> list:
    out = []
    for p in PROMPTS:
        r = _completa(p)
        out.append({"prompt": p[:40], "texto": r.get("content", ""),
                    "tokens": [t.get("id") for t in
                               (r.get("completion_probabilities") or [])]})
        print(f"  [{nombre}] {p[:40]!r} -> {len(out[-1]['texto'])} chars")
    e = _completa_tools()
    out.append(e)
    print(f"  [{nombre}] {e['prompt']!r} -> {len(e['texto'])} chars, "
          f"{e['n_tool_calls']} tool_call(s), finish={e['finish']!r}")
    return out


def _coherente(texto: str) -> bool:
    if not texto.strip():
        return False
    palabras = texto.split()
    tri = Counter(tuple(palabras[i:i + 3]) for i in range(len(palabras) - 2))
    return not tri or tri.most_common(1)[0][1] <= 8


def _coherente_tools(entrada: dict) -> bool:
    """Coherencia del prompt de tools: ademas del anti-loro, si hubo
    tool_calls sus arguments tienen que ser JSON valido con las claves del
    schema — un adapter que emite tool_calls rotos es actividad DEGRADANTE,
    no actividad a secas, y debe reprobar."""
    if not _coherente(entrada.get("texto", "")):
        return False
    if entrada.get("finish") == "length":
        return False   # truncado: el gate no puede leer la conducta entera
    texto = entrada.get("texto", "")
    for linea in texto.splitlines():
        if linea.startswith("<tool>escribir_archivo("):
            crudo = linea[len("<tool>escribir_archivo("):-1]
            try:
                args = json.loads(crudo)
            except ValueError:
                return False
            if not isinstance(args, dict) or "ruta" not in args \
                    or "contenido" not in args:
                return False
    return True


def main():
    global URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--salida", default="f0_gate.json")
    ap.add_argument("--etiqueta", default="F0 Deepthink/qwen2.5-7b")
    args = ap.parse_args()
    URL = args.url

    # estado del adapter: debe estar cargado (id 0) y sin aplicar
    ad = json.loads(urllib.request.urlopen(
        f"{URL}/lora-adapters", timeout=10).read().decode("utf-8"))
    print(f"adapters del server: {ad}")
    if not ad:
        print("FALLA: el server no tiene adapters cargados"); sys.exit(2)

    # ENMIENDA 2: en b10066 el estado inicial ya esta a escala 1.0 aunque se
    # arranque con --lora-init-without-apply (medido: A==B byte-exacto en la
    # corrida 1). Protocolo corregido: S0 -> S1 -> S0 (ida y vuelta).
    print("\n== S0_1: escala 0.0 (base) ==")
    _escala(0.0)
    A = _corre("S0_1")
    print("\n== S1: escala 1.0 (adapter) ==")
    _escala(1.0)
    B = _corre("S1")
    print("\n== S0_2: escala 0.0 otra vez (ida y vuelta) ==")
    _escala(0.0)
    C = _corre("S0_2")

    c_igual_a = [a["texto"] == c["texto"] for a, c in zip(A, C)]
    b_difiere = [a["texto"] != b["texto"] for a, b in zip(A, B)]
    b_coherente = [_coherente_tools(b) if b.get("es_tools")
                   else _coherente(b["texto"]) for b in B]

    print(f"\nS0_2==S0_1 por prompt : {c_igual_a}")
    print(f"S1!=S0_1 por prompt   : {b_difiere}")
    print(f"S1 coherente          : {b_coherente}")

    gate = all(c_igual_a) and any(b_difiere) and all(b_coherente)
    veredicto = "PASS" if gate else "FALLA"
    if not all(c_igual_a) and any(b_difiere) and all(b_coherente):
        veredicto = "REVISAR_LOGPROBS"   # rescate pre-registrado
    print(f"\nGATE F0: {veredicto}")

    SALIDA.mkdir(exist_ok=True)
    (SALIDA / args.salida).write_text(json.dumps(
        {"prereg": "PREREG_LORAS_20260801.md (enmiendas 1-3) + 4o prompt "
                   "tools nativas (PREREG_LORA_QWYTHOS_20260809)",
         "etiqueta": args.etiqueta,
         "server": "b10066, un proceso, --lora-init-without-apply, sin draft",
         "veredicto": veredicto, "c_igual_a": c_igual_a,
         "b_difiere": b_difiere, "b_coherente": b_coherente,
         "A": A, "B": B, "C": C}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"-> {SALIDA / args.salida}")
    sys.exit(0 if veredicto == "PASS" else 1)


if __name__ == "__main__":
    main()
