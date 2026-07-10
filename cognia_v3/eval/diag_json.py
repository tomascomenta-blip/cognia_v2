# -*- coding: utf-8 -*-
"""Diagnóstico ESTRUCTURA (JSON): ¿el gap del 3B es de FORMATO (no emite
JSON parseable / rompe el schema — entrenable por adapter) o de CONTENIDO
(JSON válido con valores mal — capacidad, línea muerta)?

72 tareas es+en (las 24 originales del hallazgo N=24 quedan INTACTAS en los
índices 0-23; ampliación 24-71 del 2026-07-10) con verificación programática:
  - no_json   : no se puede extraer/parsear JSON        -> FORMATO
  - schema    : parsea pero claves/tipos mal            -> FORMATO
  - contenido : schema OK pero valores mal              -> CAPACIDAD
  - pasa      : todo OK
Mismo patrón que diag_g5/LCD: medir el gap ANTES de construir (regla del
PLAN_MOM_GLM52 §6). La suite se congela por sha256_tareas() ANTES de medir.

Dos brazos PAREADOS sobre las mismas tareas (McNemar en el orquestador):
  brazo A (base):    .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.diag_json
  brazo B (grammar): .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.diag_json --grammar
El brazo B restringe el sampling con la GBNF generada del schema de cada
ítem (gbnf_json.esquema_a_gbnf): no_json y schema quedan imposibles POR
CONSTRUCCIÓN (salvo truncamiento por max_tokens) sin GPU ni entrenamiento.
"""
import argparse
import hashlib
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
    # ── Ampliación N=72 (2026-07-10): índices 24-71. NO tocar ni reordenar
    # los 0-23 de arriba (comparabilidad con el hallazgo N=24) NI estos: el
    # sha256_tareas() congela la suite completa. 24 es + 24 en (intercaladas),
    # cubriendo: claves en español con acentos, valores vacíos/null, escapes,
    # anidamiento, arrays, booleanos, números negativos/float. Schemas de
    # <=4 claves (tope _PERM_MAX de gbnf_json para el brazo --grammar).
    ("Devolvé SOLO un JSON con las claves título (string 'Dune') y año (number 1965).",
     {"título": str, "año": (int, float)}, {"título": "dune", "año": 1965}),
    ("Return ONLY a JSON object with keys title (string 'Alien') and year (number 1979).",
     {"title": str, "year": (int, float)}, {"title": "alien", "year": 1979}),
    ("Generá SOLO un JSON con las claves señal (string 'wifi') y potencia (number -70).",
     {"señal": str, "potencia": (int, float)}, {"señal": "wifi", "potencia": -70}),
    ("Return ONLY JSON with keys signal (string 'lte') and power (number -95).",
     {"signal": str, "power": (int, float)}, {"signal": "lte", "power": -95}),
    ("Devolvé SOLO un JSON con la clave descripción cuyo valor sea el string vacío \"\".",
     {"descripción": str}, {"descripción": ""}),
    ("Return ONLY a JSON object with key note whose value is the empty string \"\".",
     {"note": str}, {"note": ""}),
    ("Generá SOLO un JSON con las claves nombre (string 'demo') y etiquetas (lista vacía).",
     {"nombre": str, "etiquetas": list}, {"nombre": "demo", "etiquetas": []}),
    ("Return ONLY JSON with keys name (string 'demo') and labels (an empty list).",
     {"name": str, "labels": list}, {"name": "demo", "labels": []}),
    ("Devolvé SOLO un JSON con la clave extras cuyo valor sea un objeto vacío {}.",
     {"extras": dict}, {"extras": {}}),
    ("Return ONLY a JSON object with key extra whose value is an empty object {}.",
     {"extra": dict}, {"extra": {}}),
    ("Generá SOLO un JSON con las claves resultado (el literal null) y código (number -1).",
     {"resultado": type(None), "código": (int, float)}, {"resultado": None, "código": -1}),
    ("Return ONLY JSON with keys result (the literal null) and code (number -2).",
     {"result": type(None), "code": (int, float)}, {"result": None, "code": -2}),
    ("Devolvé SOLO un JSON con la clave carpeta cuyo valor sea el string D:\\\\logs\\\\app (escapá las barras invertidas).",
     {"carpeta": str}, None),
    ("Return ONLY a JSON object with key folder whose value is the string C:\\\\logs\\\\app (escape the backslashes).",
     {"folder": str}, None),
    ("Generá SOLO un JSON con la clave cita cuyo valor sea el string: dijo \"hola\" (escapá las comillas).",
     {"cita": str}, None),
    ("Return ONLY JSON with key quote whose value is the string: she said \"bye\" (escape the quotes).",
     {"quote": str}, None),
    ("Devolvé SOLO un JSON con la clave texto cuyo valor sea un string de dos líneas separadas por \\n: linea1 y linea2.",
     {"texto": str}, None),
    ("Return ONLY a JSON object with key text whose value is a two-line string separated by \\n: line1 and line2.",
     {"text": str}, None),
    ("Generá SOLO un JSON con la clave servidor: un objeto con host (string 'localhost') y puerto (number 8080).",
     {"servidor": dict}, {"servidor": {"host": "localhost", "puerto": 8080}}),
    ("Return ONLY JSON with key server: an object with host (string 'localhost') and port (number 9090).",
     {"server": dict}, {"server": {"host": "localhost", "port": 9090}}),
    ("Devolvé SOLO un JSON con la clave a cuyo valor sea un objeto con clave b cuyo valor sea un objeto con clave c igual al number 1.",
     {"a": dict}, {"a": {"b": {"c": 1}}}),
    ("Return ONLY a JSON object with key a whose value is an object with key b whose value is an object with key c equal to the number 2.",
     {"a": dict}, {"a": {"b": {"c": 2}}}),
    ("Generá SOLO un JSON con la clave puntos: lista de 2 objetos, cada uno con x (number) e y (number); usá x=1,y=2 y x=3,y=4.",
     {"puntos": list}, {"puntos": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]}),
    ("Return ONLY JSON with key points: a list of 2 objects, each with x (number) and y (number); use x=5,y=6 and x=7,y=8.",
     {"points": list}, {"points": [{"x": 5, "y": 6}, {"x": 7, "y": 8}]}),
    ("Devolvé SOLO un JSON con la clave pares: la lista de los números pares del 2 al 8 inclusive.",
     {"pares": list}, {"pares": [2, 4, 6, 8]}),
    ("Return ONLY a JSON object with key odds: the list of odd numbers from 1 to 7 inclusive.",
     {"odds": list}, {"odds": [1, 3, 5, 7]}),
    ("Generá SOLO un JSON con la clave datos: una lista con exactamente el number 1, el string \"dos\" y el literal true, en ese orden.",
     {"datos": list}, {"datos": [1, "dos", True]}),
    ("Return ONLY JSON with key data: a list containing exactly the number 2, the string \"three\" and the literal false, in that order.",
     {"data": list}, {"data": [2, "three", False]}),
    ("Devolvé SOLO un JSON con las claves visible (boolean false) y bloqueado (boolean true).",
     {"visible": bool, "bloqueado": bool}, {"visible": False, "bloqueado": True}),
    ("Return ONLY a JSON object with keys visible (boolean true) and locked (boolean false).",
     {"visible": bool, "locked": bool}, {"visible": True, "locked": False}),
    ("Generá SOLO un JSON con las claves éxito (boolean true) e intentos (number 3).",
     {"éxito": bool, "intentos": (int, float)}, {"éxito": True, "intentos": 3}),
    ("Return ONLY JSON with keys success (boolean false) and attempts (number 4).",
     {"success": bool, "attempts": (int, float)}, {"success": False, "attempts": 4}),
    ("Devolvé SOLO un JSON con las claves temperatura (number -12.5) y humedad (number 0.85).",
     {"temperatura": (int, float), "humedad": (int, float)}, {"temperatura": -12.5, "humedad": 0.85}),
    ("Return ONLY a JSON object with keys temp (number -3.25) and ratio (number 0.5).",
     {"temp": (int, float), "ratio": (int, float)}, {"temp": -3.25, "ratio": 0.5}),
    ("Generá SOLO un JSON con las claves saldo (number -1500.75) y moneda (string 'ARS').",
     {"saldo": (int, float), "moneda": str}, {"saldo": -1500.75, "moneda": "ars"}),
    ("Return ONLY JSON with keys balance (number -220.4) and currency (string 'USD').",
     {"balance": (int, float), "currency": str}, {"balance": -220.4, "currency": "usd"}),
    ("Devolvé SOLO un JSON con las claves nombre (string 'Luz'), edad (number 7) y activo (boolean true).",
     {"nombre": str, "edad": (int, float), "activo": bool}, {"nombre": "luz", "edad": 7, "activo": True}),
    ("Return ONLY a JSON object with keys name (string 'Sky'), age (number 9) and active (boolean false).",
     {"name": str, "age": (int, float), "active": bool}, {"name": "sky", "age": 9, "active": False}),
    ("Generá SOLO un JSON con las claves id (number 1), nombre (string 'test'), tags (lista vacía) y meta (objeto vacío).",
     {"id": (int, float), "nombre": str, "tags": list, "meta": dict},
     {"id": 1, "nombre": "test", "tags": [], "meta": {}}),
    ("Return ONLY JSON with keys id (number 2), name (string 'probe'), tags (empty list) and meta (empty object).",
     {"id": (int, float), "name": str, "tags": list, "meta": dict},
     {"id": 2, "name": "probe", "tags": [], "meta": {}}),
    ("Devolvé SOLO un JSON con la clave anterior cuyo valor sea null y la clave siguiente cuyo valor sea el number 2.",
     {"anterior": type(None), "siguiente": (int, float)}, {"anterior": None, "siguiente": 2}),
    ("Return ONLY a JSON object with key prev whose value is null and key next whose value is the number 3.",
     {"prev": type(None), "next": (int, float)}, {"prev": None, "next": 3}),
    ("Generá SOLO un JSON con la clave habitantes (number 47000000) para España.",
     {"habitantes": (int, float)}, {"habitantes": 47000000}),
    ("Return ONLY JSON with key population (number 39000000) for California.",
     {"population": (int, float)}, {"population": 39000000}),
    ("Devolvé SOLO un JSON con las claves errores (number 0) y avisos (number 0).",
     {"errores": (int, float), "avisos": (int, float)}, {"errores": 0, "avisos": 0}),
    ("Return ONLY a JSON object with keys errors (number 0) and warnings (number 0).",
     {"errors": (int, float), "warnings": (int, float)}, {"errors": 0, "warnings": 0}),
    ("Generá SOLO un JSON con la clave saludo cuyo valor sea el string exacto ñandú.",
     {"saludo": str}, {"saludo": "ñandú"}),
    ("Return ONLY JSON with key greeting whose value is the exact string naïve café.",
     {"greeting": str}, {"greeting": "naïve café"}),
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
                    # esperado string VACÍO: igualdad exacta ('' es substring
                    # de todo — el check por contención pasaría siempre)
                    if v == "":
                        if got != "":
                            return "contenido"
                    elif v.lower() not in got.lower():
                        return "contenido"
                elif isinstance(got, bool) != isinstance(v, bool) or got != v:
                    # bool es subclase de int en Python (True==1, False==0):
                    # sin el chequeo de booleanidad, false pasaría un check
                    # numérico 0 (y viceversa) — falso "pasa"
                    return "contenido"
    return "pasa"


def sha256_tareas(tareas=None) -> str:
    """Hash canónico de la suite (congelar ANTES de medir, regla del método).
    Serializa prompts + schemas (nombres de tipo) + checks de forma
    determinista: cambiar/reordenar CUALQUIER tarea cambia el hash."""
    def _canon(x):
        if isinstance(x, type):
            return f"<{x.__name__}>"
        if isinstance(x, tuple):
            return [_canon(v) for v in x]
        if isinstance(x, dict):
            return {k: _canon(v) for k, v in x.items()}
        return x
    blob = json.dumps([_canon(t) for t in (TAREAS if tareas is None else tareas)],
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def correr(backend, tareas, con_grammar: bool) -> dict:
    """Lazo de medición, separado de main() para poder verificar el CABLEADO
    (grammar por ítem, cache_prompt=False, temp 0) con un backend FAKE en
    tests — la medición REAL siempre entra por main()/CLI. Devuelve el dict
    de clases; cada ítem lleva su índice i (pareo McNemar entre brazos)."""
    esquema_a_gbnf = None
    if con_grammar:
        from cognia_v3.eval.gbnf_json import esquema_a_gbnf
    res = {"pasa": [], "no_json": [], "schema": [], "contenido": []}
    for i, (prompt, schema, checks) in enumerate(tareas):
        # grammar SOLO cuando el ítem tiene schema (idx 9, el array, corre
        # sin restricción en ambos brazos — fuera del alcance del GBNF)
        g = esquema_a_gbnf(schema) if (con_grammar and schema) else None
        raw = (backend.generate(
            f"<|im_start|>system\nEres un asistente útil.<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            max_tokens=220, temperature=0.0, cache_prompt=False,
            grammar=g) or "").strip()
        clase = clasificar(raw, schema, checks)
        res[clase].append({"i": i, "prompt": prompt[:60], "raw": raw[:150],
                           "grammar": g is not None})
        print(f"  [{clase:9s}] {i:02d}: {raw[:70]!r}", flush=True)
    return res


def main():
    parser = argparse.ArgumentParser(
        description="diagnóstico JSON del 3B: brazo A (base) / brazo B (--grammar)")
    parser.add_argument("--grammar", action="store_true",
                        help="brazo B: restringir el sampling con la GBNF "
                             "generada del schema de cada ítem (gbnf_json); "
                             "ítems sin schema (idx 9) corren igual que el A")
    parser.add_argument("--limit", type=int, default=0,
                        help="correr solo las primeras N tareas (smoke); 0=todas")
    args = parser.parse_args()

    os.environ["LLAMA_GGUF_PATH"] = str(
        REPO / "model_shards" / "qwen-coder-3b-q4" /
        "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf")
    from node.llama_backend import LlamaBackend
    backend = LlamaBackend.try_load()
    assert backend is not None
    if args.grammar:
        # El campo grammar SOLO lo respeta el impl llama-server: el in-process
        # (llama-cpp-python) lo IGNORA en silencio (node/llama_backend.py) y
        # el brazo B mediría el A con etiqueta B. Abortar fuerte, no medir falso.
        impl = type(backend._impl).__name__
        if impl != "_LlamaServerBackend":
            print(f"ERROR: --grammar exige el backend llama-server; el impl "
                  f"actual ({impl}) ignora el campo grammar (brazo B falso)")
            sys.exit(1)

    tareas = TAREAS[:args.limit] if args.limit else TAREAS
    sha = sha256_tareas()
    brazo = "B_grammar" if args.grammar else "A_base"
    print(f"[diag-json] N={len(tareas)} brazo={brazo} sha256(TAREAS)={sha}",
          flush=True)

    t0 = time.time()
    res = correr(backend, tareas, args.grammar)

    # _meta declara contra QUÉ suite/brazo/modelo corrió este JSON (los
    # ítems por clase llevan su índice i -> pareo McNemar entre brazos)
    res["_meta"] = {"n": len(tareas), "brazo": brazo, "sha256_tareas": sha,
                    "gguf": getattr(backend.gguf_path, "name", None),
                    "fecha": time.strftime("%Y-%m-%d %H:%M")}
    nombre = ("results_diag_json_grammar.json" if args.grammar
              else "results_diag_json.json")
    out = REPO / "cognia_v3" / "eval" / nombre
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    n = len(tareas)
    print(f"\n[diag-json] brazo={brazo} pasa={len(res['pasa'])}/{n}  "
          f"no_json(FORMATO)={len(res['no_json'])}  schema(FORMATO)={len(res['schema'])}  "
          f"contenido(CAPACIDAD)={len(res['contenido'])}  ({(time.time()-t0)/60:.1f} min)"
          f"  -> {nombre}", flush=True)


if __name__ == "__main__":
    main()
