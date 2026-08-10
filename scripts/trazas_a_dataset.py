# -*- coding: utf-8 -*-
"""
scripts/trazas_a_dataset.py — trazas chatml selladas -> dataset JSONL de tools.

POR QUE: el LoRA de tools de Qwythos se entrena con conversaciones REALES y
VERIFICADAS del agente nativo. Este script filtra las trazas de
``~/.cognia/data/trazas/`` por SELLO DE EVIDENCIA REAL (verificar_ws /
contrato_ok / gate e2e — el ``status: 'completa'`` de estado.json NO alcanza:
caso real 202316, 'completa' con analiza.py muerto por exit 9009), deduplica en
dos niveles y emite JSONL ``{"messages", "tools", "meta"}``.

POR QUE SIN RENDER: Qwythos es familia Qwen3.5 con su propio
``chat_template.jinja`` (el mismo que llama-server aplica con ``--jinja``).
Renderizar ChatML a mano aqui entrenaria contra una plantilla DISTINTA de la
servida (asimetria de instrumento, leccion F1). El render y el masking se hacen
EN ENTRENAMIENTO con ``tokenizer.apply_chat_template`` del repo base.

Uso:
  venv312\\Scripts\\python.exe scripts\\trazas_a_dataset.py
      [--dir ~/.cognia/data/trazas]
      [--out ~/.cognia/data/datasets/qwythos_tools_v1.jsonl]
      [--max-por-plantilla 5] [--incluir-sin-sello] [--sin-reasoning]
      [--reporte b4_loras/dataset_reporte.json]

El dataset y las trazas viven en ~/.cognia/data/ y JAMAS se commitean.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")

DIR_TRAZAS_DEFAULT = Path.home() / ".cognia" / "data" / "trazas"
OUT_DEFAULT = Path.home() / ".cognia" / "data" / "datasets" / "qwythos_tools_v1.jsonl"


# ── Filtro ─────────────────────────────────────────────────────────────

def tiene_sello(calidad) -> bool:
    """Sello de EVIDENCIA REAL. 'status: completa' a secas NO cuenta (mas
    debil que la tarea: el estado se marca completo aunque la postcondicion
    nunca se haya mirado)."""
    c = calidad or {}
    return (c.get("verificar_ws") is True
            or c.get("contrato_ok") is True
            or c.get("gate") == "e2e_ok")


def _tool_calls_de(traza: dict) -> list:
    """Secuencia (nombre, arguments) de TODOS los tool calls, en orden."""
    out = []
    for m in traza.get("mensajes") or []:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            out.append((fn.get("name", ""), fn.get("arguments", "")))
    return out


def pasa_filtro(traza: dict, exigir_sello: bool = True):
    """(True, '') si la traza entrena; (False, causa) si no. Orden congelado:
    estructura -> sello -> finish/ok. Las RECUPERACIONES (tool con ERROR
    seguida de correccion) NO descartan: si el sello final esta OK, esa
    senal de autocorreccion es de las mas valiosas del dataset."""
    if traza.get("version") != 1:
        return False, "version"
    if not traza.get("mensajes"):
        return False, "sin_mensajes"
    if not _tool_calls_de(traza):
        return False, "sin_tool_calls"
    if exigir_sello and not tiene_sello(traza.get("calidad")):
        return False, "sin_sello"
    resultado = traza.get("resultado") or {}
    if resultado.get("finish") != "stop":
        # Excluye estancamiento/no-progreso/presupuesto agotado (ademas
        # visibles por los prefijos '(interrumpida'/'(presupuesto' del texto).
        return False, "finish_no_stop"
    if resultado.get("ok") is not True:
        return False, "resultado_no_ok"
    return True, ""


# ── Dedupe (dos niveles) ───────────────────────────────────────────────

def _user_inicial(traza: dict) -> str:
    return next((m.get("content") or "" for m in traza.get("mensajes") or []
                 if m.get("role") == "user"), "")


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip().lower())


def clave_exacta(traza: dict) -> str:
    """sha256 de (user inicial normalizado, secuencia (tool, args), texto
    final): dos corridas identicas no aportan dos ejemplos."""
    payload = json.dumps(
        [_normalizar(_user_inicial(traza)), _tool_calls_de(traza),
         (traza.get("resultado") or {}).get("texto", "")],
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clave_plantilla(traza: dict) -> str:
    """User folded (sin tildes, minusculas) con digitos y rutas -> '#'.
    Mitiga el 'eco del molde': cientos de trazas del mismo banco con solo
    los numeros cambiados no deben dominar el dataset."""
    texto = _normalizar(_user_inicial(traza))
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[\w.~-]*[/\\][\w./\\~-]*", "#", texto)   # rutas
    texto = re.sub(r"\d+", "#", texto)                        # digitos
    return texto


# ── Construccion ───────────────────────────────────────────────────────

def a_ejemplo(traza: dict, sin_reasoning: bool = False) -> dict:
    """Una linea del JSONL: mensajes ESTRUCTURADOS + schemas + meta.
    --sin-reasoning dropea reasoning_content (si el smoke F-2 muestra que la
    plantilla no lo consume)."""
    mensajes = []
    for m in traza.get("mensajes") or []:
        m = dict(m)
        if sin_reasoning and m.get("role") == "assistant":
            m.pop("reasoning_content", None)
        mensajes.append(m)
    calidad = traza.get("calidad") or {}
    return {
        "messages": mensajes,
        "tools": traza.get("schemas") or [],
        "meta": {"task_id": traza.get("task_id", ""),
                 "calidad": calidad,
                 "banco": calidad.get("banco", "")},
    }


def _tokens_estimados(ejemplo: dict) -> int:
    """Estimacion barata (~4 chars/token) para p50/p95 del reporte. El conteo
    REAL lo hace el trainer con el tokenizer de la base; esto solo dimensiona
    seq-len y descartes ANTES de bajar 19 GB."""
    return max(1, len(json.dumps(ejemplo.get("messages", []),
                                 ensure_ascii=False)) // 4)


def _percentil(valores: list, p: float) -> int:
    if not valores:
        return 0
    orden = sorted(valores)
    idx = min(len(orden) - 1, int(round(p * (len(orden) - 1))))
    return orden[idx]


def construir_dataset(trazas: list, *, max_por_plantilla: int = 5,
                      exigir_sello: bool = True, sin_reasoning: bool = False):
    """(ejemplos, reporte). El reporte cuenta CADA descarte por causa: un
    dataset que no explica que tiro es un dataset en el que no se puede
    confiar (el filtro es la mitad del metodo)."""
    descartes: dict = {}
    ejemplos: list = []
    vistos_exacto: set = set()
    por_plantilla: dict = {}
    histograma: dict = {}
    schema_tools: set = set()

    for traza in trazas:
        ok, causa = pasa_filtro(traza, exigir_sello=exigir_sello)
        if not ok:
            descartes[causa] = descartes.get(causa, 0) + 1
            continue
        h = clave_exacta(traza)
        if h in vistos_exacto:
            descartes["dup_exacto"] = descartes.get("dup_exacto", 0) + 1
            continue
        kp = clave_plantilla(traza)
        if por_plantilla.get(kp, 0) >= max_por_plantilla:
            descartes["dup_plantilla"] = descartes.get("dup_plantilla", 0) + 1
            continue
        vistos_exacto.add(h)
        por_plantilla[kp] = por_plantilla.get(kp, 0) + 1
        ejemplos.append(a_ejemplo(traza, sin_reasoning=sin_reasoning))
        for nombre, _args in _tool_calls_de(traza):
            histograma[nombre] = histograma.get(nombre, 0) + 1
        for sch in traza.get("schemas") or []:
            n = ((sch.get("function") or {}).get("name")
                 if isinstance(sch, dict) else None)
            if n:
                schema_tools.add(n)

    toks = [_tokens_estimados(e) for e in ejemplos]
    reporte = {
        "trazas_leidas": len(trazas),
        "descartes": descartes,
        "ejemplos": len(ejemplos),
        "tokens_p50": _percentil(toks, 0.50),
        "tokens_p95": _percentil(toks, 0.95),
        "histograma_tools": dict(sorted(histograma.items(),
                                        key=lambda kv: -kv[1])),
        # Tools OFRECIDAS en los schemas que el dataset jamas ejercita: el
        # prereg F-1 exige cobertura y esto es lo que la audita.
        "tools_sin_cobertura": sorted(schema_tools - set(histograma)),
    }
    return ejemplos, reporte


def cargar_trazas(directorio: Path) -> list:
    """Lee todos los *.json del dir; un archivo corrupto se REPORTA por
    stderr y se salta (degradacion visible, jamas silenciosa)."""
    trazas = []
    for ruta in sorted(Path(directorio).glob("*.json")):
        try:
            trazas.append(json.loads(ruta.read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"[trazas_a_dataset] AVISO: {ruta.name} ilegible: {exc}",
                  file=sys.stderr)
    return trazas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dir", default=str(DIR_TRAZAS_DEFAULT))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--max-por-plantilla", type=int, default=5)
    ap.add_argument("--incluir-sin-sello", action="store_true",
                    help="SOLO para inspeccion: sin sello no se entrena")
    ap.add_argument("--sin-reasoning", action="store_true")
    ap.add_argument("--reporte", default="")
    args = ap.parse_args(argv)

    trazas = cargar_trazas(Path(args.dir))
    ejemplos, reporte = construir_dataset(
        trazas, max_por_plantilla=args.max_por_plantilla,
        exigir_sello=not args.incluir_sin_sello,
        sin_reasoning=args.sin_reasoning)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for ej in ejemplos:
            fh.write(json.dumps(ej, ensure_ascii=False) + "\n")

    print(json.dumps(reporte, ensure_ascii=False, indent=1))
    print(f"dataset: {len(ejemplos)} ejemplos -> {out}")
    if args.reporte:
        rp = Path(args.reporte)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(reporte, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print(f"reporte -> {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
