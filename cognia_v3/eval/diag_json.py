# -*- coding: utf-8 -*-
"""Diagnóstico ESTRUCTURA (JSON): ¿el gap del 3B es de FORMATO (no emite
JSON parseable / rompe el schema — entrenable por adapter) o de CONTENIDO
(JSON válido con valores mal — capacidad, línea muerta)?

24 tareas es+en con verificación programática:
  - no_json   : no se puede extraer/parsear JSON        -> FORMATO
  - schema    : parsea pero claves/tipos mal            -> FORMATO
  - contenido : schema OK pero valores mal              -> CAPACIDAD
  - pasa      : todo OK
Mismo patrón que diag_g5/LCD: medir el gap ANTES de construir (regla del
PLAN_MOM_GLM52 §6).

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.diag_json
"""
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (prompt, schema {clave: tipo}, checks {clave: valor esperado} | None)
TAREAS = [
    ("Devolvé SOLO un JSON (sin texto extra) con las claves nombre (string) y edad (number) para una persona llamada Ana que tiene 30 años.",
     {"nombre": str, "edad": (int, float)}, {"nombre": "ana", "edad": 30}),
    ("Return ONLY a JSON object with keys city (string) and population (number) for Paris with 2100000 people.",
     {"city": str, "population": (int, float)}, {"city": "paris", "population": 2100000}),
    ("Generá un JSON con la clave colores cuyo valor sea una lista con exactamente rojo, verde y azul (en ese orden). Solo el JSON.",
     {"colores": list}, {"colores": ["rojo", "verde", "azul"]}),
    ("Return ONLY valid JSON: an object with key items containing a list of 3 objects, each with keys id (number) and done (boolean). Use ids 1, 2, 3 and done false for all.",
     {"items": list}, None),
    ("Devolvé SOLO un JSON con las claves ancho y alto (numbers) para una pantalla de 1920 por 1080.",
     {"ancho": (int, float), "alto": (int, float)}, {"ancho": 1920, "alto": 1080}),
    ("Return ONLY a JSON object with key config, whose value is an object with keys debug (boolean, true) and retries (number, 5).",
     {"config": dict}, None),
    ("Generá SOLO un JSON con la clave dias cuyo valor sea la lista de los días del fin de semana en español, en minúsculas.",
     {"dias": list}, None),
    ("Return ONLY JSON: {\"status\": ..., \"code\": ...} where status is the string ok and code is the number 200.",
     {"status": str, "code": (int, float)}, {"status": "ok", "code": 200}),
    ("Devolvé SOLO un JSON que represente un producto: claves titulo (string 'Notebook'), precio (number 999.99) y stock (number 12).",
     {"titulo": str, "precio": (int, float), "stock": (int, float)}, {"precio": 999.99, "stock": 12}),
    ("Return ONLY a JSON array (not an object) with the numbers 1 through 5.",
     None, "array_1_5"),
    ("Generá SOLO un JSON con las claves usuario (string 'admin') y activo (boolean true). Nada de explicaciones.",
     {"usuario": str, "activo": bool}, {"usuario": "admin", "activo": True}),
    ("Return ONLY JSON with keys lat and lon (numbers) for coordinates -34.6 and -58.4.",
     {"lat": (int, float), "lon": (int, float)}, {"lat": -34.6, "lon": -58.4}),
    ("Devolvé SOLO un JSON con la clave tareas: lista de 2 objetos, cada uno con texto (string) y prioridad (number 1 o 2). Inventá los textos.",
     {"tareas": list}, None),
    ("Return ONLY a JSON object mapping the strings a, b and c to the numbers 1, 2 and 3 respectively.",
     {"a": (int, float), "b": (int, float), "c": (int, float)}, {"a": 1, "b": 2, "c": 3}),
    ("Generá SOLO un JSON con clave version (string '1.0.0') y clave dependencias (lista vacía).",
     {"version": str, "dependencias": list}, {"version": "1.0.0", "dependencias": []}),
    ("Return ONLY JSON: object with key user containing keys name (string 'Bo') and tags (list of exactly the strings x and y).",
     {"user": dict}, None),
    ("Devolvé SOLO un JSON con las claves pregunta (string) y respuesta (number) para: ¿cuánto es 7 por 8?",
     {"pregunta": str, "respuesta": (int, float)}, {"respuesta": 56}),
    ("Return ONLY a JSON object with key empty whose value is an empty object.",
     {"empty": dict}, {"empty": {}}),
    ("Generá SOLO un JSON válido con una clave ruta cuyo valor sea el string C:\\\\temp\\\\datos.txt (ojo con escapar la barra).",
     {"ruta": str}, None),
    ("Return ONLY JSON with key message whose value is the string: He said \"hello\" (quotes must be escaped correctly).",
     {"message": str}, None),
    ("Devolvé SOLO un JSON con clave nulo cuyo valor sea null (el literal JSON, no el string).",
     {"nulo": type(None)}, {"nulo": None}),
    ("Return ONLY a JSON object with keys min and max (numbers) where min is 0 and max is 100.",
     {"min": (int, float), "max": (int, float)}, {"min": 0, "max": 100}),
    ("Generá SOLO un JSON con clave matriz: lista de 2 listas, cada una con 2 números (1,2 y 3,4).",
     {"matriz": list}, {"matriz": [[1, 2], [3, 4]]}),
    ("Return ONLY JSON: {\"ok\": true} and absolutely nothing else.",
     {"ok": bool}, {"ok": True}),
]

_FENCE_RX = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def extraer_json(texto: str):
    """Primer JSON parseable: fence -> objeto/array crudo -> None."""
    t = (texto or "").strip()
    m = _FENCE_RX.search(t)
    if m:
        t = m.group(1).strip()
    for candidato in (t,):
        try:
            return json.loads(candidato), candidato == (texto or "").strip()
        except json.JSONDecodeError:
            pass
    # subcadena { ... } o [ ... ] mas larga
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1]), False
            except json.JSONDecodeError:
                pass
    return None, False


def clasificar(raw: str, schema, checks):
    obj, _limpio = extraer_json(raw)
    if obj is None:
        return "no_json"
    if checks == "array_1_5":
        return "pasa" if obj == [1, 2, 3, 4, 5] else (
            "schema" if not isinstance(obj, list) else "contenido")
    if schema:
        if not isinstance(obj, dict):
            return "schema"
        for k, tipo in schema.items():
            if k not in obj or not isinstance(obj[k], tipo):
                return "schema"
        if isinstance(checks, dict):
            for k, v in checks.items():
                got = obj.get(k)
                if isinstance(got, str) and isinstance(v, str):
                    if v.lower() not in got.lower():
                        return "contenido"
                elif got != v:
                    return "contenido"
    return "pasa"


def main():
    os.environ["LLAMA_GGUF_PATH"] = str(
        REPO / "model_shards" / "qwen-coder-3b-q4" /
        "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf")
    from node.llama_backend import LlamaBackend
    backend = LlamaBackend.try_load()
    assert backend is not None

    res = {"pasa": [], "no_json": [], "schema": [], "contenido": []}
    t0 = time.time()
    for i, (prompt, schema, checks) in enumerate(TAREAS):
        raw = (backend.generate(
            f"<|im_start|>system\nEres un asistente útil.<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            max_tokens=220, temperature=0.0, cache_prompt=False) or "").strip()
        clase = clasificar(raw, schema, checks)
        res[clase].append({"i": i, "prompt": prompt[:60], "raw": raw[:150]})
        print(f"  [{clase:9s}] {i:02d}: {raw[:70]!r}", flush=True)

    out = REPO / "cognia_v3" / "eval" / "results_diag_json.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    n = len(TAREAS)
    print(f"\n[diag-json] pasa={len(res['pasa'])}/{n}  "
          f"no_json(FORMATO)={len(res['no_json'])}  schema(FORMATO)={len(res['schema'])}  "
          f"contenido(CAPACIDAD)={len(res['contenido'])}  ({(time.time()-t0)/60:.1f} min)",
          flush=True)


if __name__ == "__main__":
    main()
