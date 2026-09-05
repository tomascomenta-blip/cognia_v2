# -*- coding: utf-8 -*-
r"""Banco de MEMORIA DE LARGO ALCANCE: baseline (compactación actual) vs memoria larga.

Tres brazos sobre el MISMO dataset (scripts/memoria_larga/generar_dataset.py):

  baseline   Reproduce el pipeline actual del loop paso a paso sobre el historial
             sintético: offloading de tools grandes + `_compactar_por_resumen` (0.8)
             → `_recortar_mensajes` → `_recorte_de_emergencia` (0.92), con la misma
             cuenta chars/4 del loop. Al final entra la pregunta y responde el modelo
             (una llamada por pregunta). Mide: aciertos A-G, prompt_tokens reales,
             latencia, cuántas veces compactó/recortó, qué quedó del historial.
  despues    Mismo feed, pero con memoria_larga: extracción incremental + REBUILD
             cuando el contexto activo supera el umbral; ante la pregunta, un
             rebuild forzado con la pregunta como intención (la memoria es el
             context builder). Mide lo mismo + memorias/retrieval/checkpoints.
  retrieval  SIN modelo: ingesta el historial en el almacén y para cada pregunta
             mide precisión/recall del retrieval contra los mensajes sembrados,
             tasa de irrelevantes (distractores B), latencia, RAM, disco.

Uso:
  venv312\Scripts\python.exe scripts/memoria_larga/banco.py --dataset scratchpad/ml/100000 --modo baseline
  ... --modo despues | --modo retrieval [--n-ctx 65536] [--salida scratchpad/ml/resultados.jsonl]
Los brazos con modelo usan http://127.0.0.1:8080 (COGNIA_LLM_URL) y aíslan todo
en <dataset>/_<modo>/ (COGNIA_MEMORIA_DIR, COGNIA_OFFLOAD_DIR, COGNIA_HOME).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

SYSTEM = ("Sos un agente de programación. Respondé en español, de forma concreta y breve, "
          "SOLO con lo que sabés por el historial y los datos recuperados. Si no lo sabés, decilo.")
PESO_SCHEMAS = 7600      # medido con /tokenize: 73 tools del catálogo real


def _juzgar(respuesta: str, p: dict) -> dict:
    r = (respuesta or "").lower()
    esperados = [e.lower() for e in p.get("esperado", [])]
    evitar = [e.lower() for e in p.get("evitar", [])]
    ok_esp = all(e in r for e in esperados)
    ok_evi = not any(e in r for e in evitar)
    extra = True
    if p["tipo"] == "decision_actualizada":
        extra = all(v.lower() in r for v in p.get("secuencia", []))
    if p["tipo"] == "contradiccion":
        # la respuesta puede citar la anterior, pero la ACTUAL tiene que estar
        extra = p.get("actual", "").lower() in r
    return {"ok": bool(ok_esp and ok_evi and extra), "esperado": ok_esp, "evito": ok_evi, "extra": extra}


def _cargar(dataset: Path):
    mensajes = [json.loads(l) for l in open(dataset / "mensajes.jsonl", encoding="utf-8")]
    preguntas = json.loads((dataset / "preguntas.json").read_text(encoding="utf-8"))
    return mensajes, preguntas


def _a_formato_loop(msgs: list) -> list:
    """Los mensajes del dataset → turnos del loop (assistant con tool_calls + tool)."""
    out = []
    i = 0
    n = 0
    while i < len(msgs):
        m = msgs[i]
        if m["role"] == "assistant" and m.get("tool") and i + 1 < len(msgs) and msgs[i + 1]["role"] == "tool":
            t = msgs[i + 1]
            cab = t["content"].split("\n", 1)[0]
            args = {"path": cab.split(" ", 2)[-1].rstrip(":")} if m["tool"] in ("leer_archivo", "listar") else {"ruta": "tests"}
            out.append({"role": "assistant", "content": "", "_i": m["i"],
                        "tool_calls": [{"type": "function", "id": f"c{n}",
                                        "function": {"name": m["tool"], "arguments": json.dumps(args, ensure_ascii=False)}}]})
            out.append({"role": "tool", "tool_call_id": f"c{n}", "content": t["content"], "_i": t["i"],
                        "_tool": m["tool"], "_args": json.dumps(args, ensure_ascii=False), "_sembrado": t.get("sembrado")})
            n += 1
            i += 2
            continue
        out.append({"role": m["role"], "content": m["content"], "_i": m["i"], "_sembrado": m.get("sembrado")})
        i += 1
    return out


def _limpio(m: dict) -> dict:
    return {k: v for k, v in m.items() if not k.startswith("_")}


def _llamar_modelo(mensajes: list, max_tokens: int = 4096) -> dict:
    url = os.environ.get("COGNIA_LLM_URL", "http://127.0.0.1:8080").rstrip("/") + "/v1/chat/completions"
    body = {"model": "qwen3.8-27b", "messages": [_limpio(m) for m in mensajes], "max_tokens": max_tokens,
            "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.perf_counter()
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        j = json.load(r)
    msg = j["choices"][0]["message"]
    return {"texto": msg.get("content") or "", "usage": j.get("usage") or {},
            "finish": j["choices"][0].get("finish_reason"), "segundos": round(time.perf_counter() - t0, 1)}


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return 0.0


def _vram_mb() -> float:
    try:
        import subprocess
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return float(out.splitlines()[0])
    except Exception:
        return 0.0


# ── brazo BASELINE ───────────────────────────────────────────────────────────

def correr_baseline(dataset: Path, n_ctx: int, con_modelo: bool) -> dict:
    os.environ["COGNIA_MEMORIA_LARGA"] = "0"
    from cognia.agent import loop as L
    from cognia.harness import offloading
    msgs, preguntas = _cargar(dataset)
    turnos = _a_formato_loop(msgs)
    primer_user = next(m["content"] for m in msgs if m["role"] == "user")
    mensajes = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "TAREA: " + primer_user}]
    stats = {"compactaciones": 0, "recortes": 0, "emergencias": 0, "max_est": 0, "pasos": 0, "rss_max_mb": 0.0}
    salidas = []

    def print_fn(s, *a, **k):
        salidas.append(str(s))

    t0 = time.perf_counter()
    for m in turnos[1:]:
        if m["role"] == "tool":
            try:
                if offloading.activo():
                    m = dict(m)
                    m["content"] = offloading.formatear_observacion(m["content"], tool=m.get("_tool", "tool"), args=m.get("_args", ""))
            except Exception:
                pass
        mensajes.append(m)
        if m["role"] != "assistant":
            continue
        stats["pasos"] += 1
        est = L._tokens_prompt(mensajes) if False else (sum(len(str(x.get("content") or "")) + len(str(x.get("reasoning_content") or "")) for x in mensajes) // 4 + PESO_SCHEMAS)
        stats["max_est"] = max(stats["max_est"], est)
        lib = L._compactar_por_resumen(mensajes, n_ctx, est, None, print_fn)
        if lib:
            stats["compactaciones"] += 1
            est -= lib // 4
        else:
            while True:
                liberados = L._recortar_mensajes(mensajes, n_ctx, est)
                if not liberados:
                    break
                stats["recortes"] += 1
                est -= liberados // 4
        if est >= int(n_ctx * L._EMERGENCIA_FRAC):
            if L._recorte_de_emergencia(mensajes, n_ctx, print_fn):
                stats["emergencias"] += 1
        stats["rss_max_mb"] = max(stats["rss_max_mb"], _rss_mb())
    stats["segundos_feed"] = round(time.perf_counter() - t0, 1)
    stats["mensajes_en_ventana"] = len(mensajes)
    stats["chars_en_ventana"] = sum(len(str(x.get("content") or "")) for x in mensajes)
    resultados = []
    if con_modelo:
        base = [dict(x) for x in mensajes]
        for p in preguntas:
            ms = [dict(x) for x in base] + [{"role": "user", "content": p["pregunta"]}]
            try:
                r = _llamar_modelo(ms)
            except Exception as exc:
                r = {"texto": f"ERROR {exc}", "usage": {}, "finish": "error", "segundos": 0}
            j = _juzgar(r["texto"], p)
            resultados.append({"id": p["id"], "tipo": p["tipo"], "ok": j["ok"], "detalle": j,
                               "prompt_tokens": r["usage"].get("prompt_tokens"), "segundos": r["segundos"],
                               "finish": r["finish"], "respuesta": r["texto"][:400]})
            print(f"  [{p['id']}] {'OK ' if j['ok'] else 'FALLO'} prompt={r['usage'].get('prompt_tokens')} "
                  f"{r['segundos']}s :: {r['texto'][:110]!r}", flush=True)
    return {"modo": "baseline", "n_ctx": n_ctx, "stats": stats, "preguntas": resultados,
            "aciertos": sum(1 for x in resultados if x["ok"]), "total": len(resultados)}


# ── brazo DESPUES ────────────────────────────────────────────────────────────

def correr_despues(dataset: Path, n_ctx: int, con_modelo: bool) -> dict:
    os.environ["COGNIA_MEMORIA_LARGA"] = "1"
    from cognia.harness import offloading
    from cognia.memoria_larga.integracion import MemoriaTarea
    msgs, preguntas = _cargar(dataset)
    turnos = _a_formato_loop(msgs)
    primer_user = next(m["content"] for m in msgs if m["role"] == "user")
    salidas = []
    ml = MemoriaTarea(primer_user, {"cwd": str(dataset)}, {"n_ctx": n_ctx}, lambda s, *a, **k: salidas.append(str(s)), None)
    ml.cm.peso_schemas = PESO_SCHEMAS
    mensajes = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "TAREA: " + primer_user}]
    stats = {"pasos": 0, "max_est": 0, "rss_max_mb": 0.0}
    t0 = time.perf_counter()
    paso = 0
    for m in turnos[1:]:
        if m["role"] == "tool":
            ml.registrar("tool", m["content"], tool=m.get("_tool"), ok=("rc=1" not in m["content"][:80]), paso=paso)
            try:
                if offloading.activo():
                    m = dict(m)
                    m["content"] = offloading.formatear_observacion(m["content"], tool=m.get("_tool", "tool"), args=m.get("_args", ""))
            except Exception:
                pass
        elif m["role"] == "user":
            ml.registrar("user", m["content"], paso=paso)
        elif m["role"] == "assistant" and m.get("content"):
            ml.registrar("assistant", m["content"], paso=paso)
        mensajes.append(m)
        if m["role"] != "assistant":
            continue
        paso += 1
        stats["pasos"] = paso
        ml.paso = paso
        ml.ultima_intencion = (m.get("content") or "")[:160] or ml.ultima_intencion
        est = ml.cm.ocupacion(mensajes)
        stats["max_est"] = max(stats["max_est"], est)
        ml.fin_de_paso(mensajes, est, None)
        stats["rss_max_mb"] = max(stats["rss_max_mb"], _rss_mb())
    stats["segundos_feed"] = round(time.perf_counter() - t0, 1)
    stats["memoria"] = ml.stats.a_dict()
    try:
        stats["almacen"] = ml.almacen.estadisticas() if ml.almacen else {}
    except Exception as exc:
        stats["almacen"] = {"error": str(exc)}
    stats["mensajes_en_ventana"] = len(mensajes)
    resultados = []
    if con_modelo:
        base = [dict(x) for x in mensajes]
        for p in preguntas:
            ms = [dict(x) for x in base] + [{"role": "user", "content": p["pregunta"]}]
            # la pregunta gobierna el context builder: rebuild forzado con ella como intención
            t1 = time.perf_counter()
            info = ml.cm.reconstruir(ms, forzar=True, intencion=p["pregunta"], ficheros_abiertos=ml.ficheros_abiertos,
                                     checkpoint_fn=None) or {}
            ms_rebuild = round((time.perf_counter() - t1) * 1000)
            try:
                r = _llamar_modelo(ms)
            except Exception as exc:
                r = {"texto": f"ERROR {exc}", "usage": {}, "finish": "error", "segundos": 0}
            j = _juzgar(r["texto"], p)
            resultados.append({"id": p["id"], "tipo": p["tipo"], "ok": j["ok"], "detalle": j,
                               "prompt_tokens": r["usage"].get("prompt_tokens"), "segundos": r["segundos"],
                               "finish": r["finish"], "respuesta": r["texto"][:400],
                               "rebuild": {k: info.get(k) for k in ("tokens_antes", "tokens_despues", "memorias", "candidatos", "via", "latencia_ms")},
                               "rebuild_ms": ms_rebuild})
            print(f"  [{p['id']}] {'OK ' if j['ok'] else 'FALLO'} prompt={r['usage'].get('prompt_tokens')} "
                  f"mem={info.get('memorias')} via={info.get('via')} {r['segundos']}s :: {r['texto'][:100]!r}", flush=True)
    try:
        ml.cerrar("fin del banco", True)
    except Exception:
        pass
    return {"modo": "despues", "n_ctx": n_ctx, "stats": stats, "preguntas": resultados,
            "aciertos": sum(1 for x in resultados if x["ok"]), "total": len(resultados)}


# ── brazo RETRIEVAL (sin modelo) ─────────────────────────────────────────────

_ESPERADOS = {"A": ["A"], "B": ["A"], "C": ["C2"], "D": ["D1", "D2", "D3"], "E": ["E"], "F": ["F"], "G": ["G_error", "G_solucion"]}
_HISTORIAL = {"C": ["C1", "C2"]}


def correr_retrieval(dataset: Path, pesos: dict | None = None) -> dict:
    from cognia.memoria_larga import contradicciones, dedup, extraccion
    from cognia.memoria_larga.almacen import Almacen
    from cognia.memoria_larga.retrieval import Recuperador
    msgs, preguntas = _cargar(dataset)
    ruta_db = dataset / "_retrieval" / "memoria_larga.db"
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    if ruta_db.exists():
        ruta_db.unlink()
    alm = Almacen(str(ruta_db))
    task_id = "banco"
    t0 = time.perf_counter()
    n_guardadas = n_fus = n_contra = 0
    tag_de_memoria: dict[int, str | None] = {}
    lote = []
    for m in msgs:
        tool = m.get("tool") if m["role"] == "tool" else None
        for mem in extraccion.extraer(m["role"], m["content"], tool=tool, task_id=task_id, session_id="s", paso=m["i"],
                                      ok=("rc=1" not in m["content"][:80])):
            mem.referencias = list(mem.referencias) + [f"msg:{m['i']}"]
            dup = dedup.es_duplicada(alm, mem)
            if dup is not None:
                dedup.fusionar(alm, dup, mem)
                n_fus += 1
                continue
            vieja = contradicciones.detectar(alm, mem)
            mid = alm.guardar(mem)
            tag_de_memoria[mid] = m.get("sembrado")
            n_guardadas += 1
            if vieja is not None:
                contradicciones.resolver(alm, vieja, mem)
                n_contra += 1
    seg_ingesta = round(time.perf_counter() - t0, 1)
    rec = Recuperador(alm, pesos=pesos)
    filas = []
    for p in preguntas:
        q = p["pregunta"] + (" historial" if p["id"] == "D" else "")
        t1 = time.perf_counter()
        r = rec.buscar(q, task_id=task_id, limite=12, explicar=True)
        lat = round((time.perf_counter() - t1) * 1000, 1)
        sel = [m.id for m in r.memorias]
        tags_sel = [tag_de_memoria.get(i) for i in sel]
        esperados = set(_ESPERADOS[p["id"]])
        relevantes = [t for t in tags_sel if t in esperados]
        cubiertos = esperados & set(tags_sel)
        irrelevantes = sum(1 for t in tags_sel if t == "B")
        # contradicción: la superada (C1) NO debe salir en la pregunta de estado actual
        # la superada (C1) puede aparecer si la pregunta pide el porqué del cambio,
        # pero NUNCA por delante de la vigente (C2)
        superada_fuera = True
        if p["id"] == "C" and "C1" in tags_sel:
            superada_fuera = ("C2" in tags_sel) and tags_sel.index("C2") < tags_sel.index("C1")
        filas.append({"id": p["id"], "tipo": p["tipo"], "precision": round(len(relevantes) / max(1, len(sel)), 3),
                      "recall": round(len(cubiertos) / max(1, len(esperados)), 3), "seleccionados": len(sel),
                      "candidatos": r.candidatos, "irrelevantes": irrelevantes, "superada_fuera": superada_fuera,
                      "latencia_ms": lat, "via": r.via, "tags": tags_sel[:12]})
    est = {}
    try:
        est = alm.estadisticas()
    except Exception as exc:
        est = {"error": str(exc)}
    alm.cerrar()
    prec = sum(f["precision"] for f in filas) / len(filas)
    rec_ = sum(f["recall"] for f in filas) / len(filas)
    return {"modo": "retrieval", "ingesta": {"segundos": seg_ingesta, "guardadas": n_guardadas, "fusionadas": n_fus,
                                             "contradicciones": n_contra, "rss_mb": round(_rss_mb()),
                                             "db_bytes": ruta_db.stat().st_size if ruta_db.exists() else 0},
            "preguntas": filas, "precision_media": round(prec, 3), "recall_medio": round(rec_, 3),
            "hit_rate": round(sum(1 for f in filas if f["recall"] > 0) / len(filas), 3),
            "contradiccion_ok": all(f["superada_fuera"] for f in filas),
            "irrelevantes_total": sum(f["irrelevantes"] for f in filas), "almacen": est}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--modo", choices=["baseline", "despues", "retrieval"], required=True)
    ap.add_argument("--n-ctx", type=int, default=65536)
    ap.add_argument("--sin-modelo", action="store_true")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--pesos", default=None, help="JSON con pesos del reranker (solo retrieval)")
    a = ap.parse_args()
    dataset = Path(a.dataset)
    aislado = dataset / f"_{a.modo}"
    if aislado.exists() and a.modo != "retrieval":
        shutil.rmtree(aislado, ignore_errors=True)
    aislado.mkdir(parents=True, exist_ok=True)
    os.environ["COGNIA_MEMORIA_DIR"] = str(aislado)
    os.environ["COGNIA_OFFLOAD_DIR"] = str(aislado / "offload")
    os.environ["COGNIA_HOME"] = str(aislado / "home")
    os.environ.setdefault("COGNIA_OFFLOAD", "1")
    os.environ.setdefault("COGNIA_EFIMERO", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    t0 = time.perf_counter()
    vram0 = _vram_mb()
    if a.modo == "baseline":
        res = correr_baseline(dataset, a.n_ctx, not a.sin_modelo)
    elif a.modo == "despues":
        res = correr_despues(dataset, a.n_ctx, not a.sin_modelo)
    else:
        res = correr_retrieval(dataset, json.loads(a.pesos) if a.pesos else None)
    res["dataset"] = str(dataset)
    res["resumen_dataset"] = json.loads((dataset / "resumen.json").read_text(encoding="utf-8"))
    res["segundos_total"] = round(time.perf_counter() - t0, 1)
    res["rss_final_mb"] = round(_rss_mb())
    res["cpu_proceso_s"] = round(time.process_time(), 1)
    res["vram_mb"] = {"antes": vram0, "despues": _vram_mb()}
    res["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    linea = json.dumps(res, ensure_ascii=False)
    if a.salida:
        with open(a.salida, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    cab = {k: v for k, v in res.items() if k not in ("preguntas", "resumen_dataset", "stats", "almacen")}
    print(json.dumps(cab, ensure_ascii=False))
    if a.modo != "retrieval":
        print(json.dumps(res["stats"], ensure_ascii=False)[:1500])
    else:
        for f in res["preguntas"]:
            print(f"  [{f['id']}] P={f['precision']} R={f['recall']} sel={f['seleccionados']} cand={f['candidatos']} irrel={f['irrelevantes']} {f['latencia_ms']}ms via={f['via']} tags={f['tags'][:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
