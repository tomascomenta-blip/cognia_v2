# -*- coding: utf-8 -*-
"""
cognia/fases/dod.py — la Definicion de Hecho (Definition of Done).

Antes de escribir codigo, el objetivo se convierte en una lista VERIFICABLE
en tres grupos: funcionales ("el jugador se mueve"), visuales ("nada se
superpone"), calidad ("sin errores de consola"). Cada requisito lleva una
verificacion que el verificador puede EJECUTAR:

  {"tipo": "tests",    "args": "tests/"}                     pytest en verde
  {"tipo": "ejecutar", "args": "python juego.py --version", "espera": "regex"}
  {"tipo": "probar",   "args": "index.html", "espera": "regex"}   la tool probar
  {"tipo": "guion",    "args": "index.html | guion=tecla derecha*3; assert window.score>0"}
  {"tipo": "app",      "args": "python juego.py | pasos=tecla derecha*3; captura", "espera": "regex"}
  {"tipo": "manual",   "args": ""}   lo juzga el modelo con evidencia (queda [ ] hasta entonces)

El planificador (fase 0) la escribe como JSON; si el JSON no llega o es
invalido, `automatica()` deriva una DoD minima del enunciado (contrato_tarea)
mas los requisitos de calidad estandar. La lista es el contrato del producto:
el juez y las fases leen de aqui, nunca de la opinion del modelo.
"""
from __future__ import annotations

import json
import re

TIPOS = ("tests", "ejecutar", "probar", "guion", "app", "manual")
GRUPOS = ("funcionales", "visuales", "calidad")
TOPE_POR_GRUPO = 40


def _item(grupo: str, n: int, texto: str, verif: dict = None) -> dict:
    v = dict(verif or {})
    tipo = str(v.get("tipo") or "manual").lower().strip()
    if tipo not in TIPOS:
        tipo = "manual"
    return {"id": "%s%d" % (grupo[0].upper(), n), "texto": str(texto).strip()[:300],
            "verif": {"tipo": tipo, "args": str(v.get("args") or "").strip()[:600],
                      "espera": str(v.get("espera") or "").strip()[:300]},
            "ok": None, "evidencia": "", "fase": str(v.get("fase") or "")}


def normalizar(cruda: dict) -> dict:
    """{funcionales:[...], visuales:[...], calidad:[...]} con items validados.
    Acepta strings sueltos (-> manual) o dicts {texto, verif|tipo|args|espera}."""
    out = {g: [] for g in GRUPOS}
    for g in GRUPOS:
        items = cruda.get(g) if isinstance(cruda, dict) else None
        if not isinstance(items, list):
            continue
        n = 0
        for it in items[:TOPE_POR_GRUPO]:
            if isinstance(it, str):
                texto, verif = it, {}
            elif isinstance(it, dict):
                texto = it.get("texto") or it.get("requisito") or it.get("nombre") or ""
                verif = it.get("verif") if isinstance(it.get("verif"), dict) else \
                    {k: it.get(k) for k in ("tipo", "args", "espera", "fase") if k in it}
            else:
                continue
            if not str(texto).strip():
                continue
            n += 1
            out[g].append(_item(g, n, texto, verif))
    return out


def parsear_json(texto: str) -> dict | None:
    """El JSON de la DoD dentro de la respuesta del modelo (bloque ```json o
    el primer {...} con las claves esperadas). None si no hay nada valido."""
    if not texto:
        return None
    candidatos = []
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S):
        candidatos.append(m.group(1))
    i = texto.find("{")
    if i >= 0:
        candidatos.append(texto[i:texto.rfind("}") + 1])
    for c in candidatos:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if isinstance(obj, dict) and any(k in obj for k in GRUPOS):
            d = normalizar(obj)
            if total(d):
                d["_meta"] = {k: obj[k] for k in ("tipo_producto", "entrypoint", "arquitectura", "ficheros") if k in obj}
                return d
    return None


def total(d: dict) -> int:
    return sum(len(d.get(g) or []) for g in GRUPOS)


def items(d: dict) -> list:
    out = []
    for g in GRUPOS:
        out.extend(d.get(g) or [])
    return out


def buscar(d: dict, item_id: str) -> dict | None:
    iid = (item_id or "").strip().upper()
    for it in items(d):
        if it["id"].upper() == iid:
            return it
    return None


def resumen(d: dict) -> dict:
    its = items(d)
    return {"total": len(its), "ok": sum(1 for i in its if i.get("ok") is True),
            "fallan": sum(1 for i in its if i.get("ok") is False),
            "sin": sum(1 for i in its if i.get("ok") is None),
            "manuales": sum(1 for i in its if (i.get("verif") or {}).get("tipo") == "manual")}


def marcar(d: dict, item_id: str, ok, evidencia: str = "") -> dict | None:
    it = buscar(d, item_id)
    if it is None:
        return None
    it["ok"] = ok
    it["evidencia"] = (evidencia or "").strip()[:400]
    return it


# ---------------------------------------------------------------------------
# DoD automatica (sin modelo): del enunciado + calidad estandar
# ---------------------------------------------------------------------------

_CALIDAD_WEB = [
    ("Abre sin errores de consola ni excepciones de JS", {"tipo": "probar", "args": "{entrypoint}",
                                                         "espera": r"sin errores de consola"}),
    ("El HTML es valido (etiquetas cerradas, recursos locales existentes)", {"tipo": "probar", "args": "{entrypoint}",
                                                                              "espera": r"formato_validar[^\n]*: OK|0 problema"}),
    ("No hay enlaces ni imagenes rotos", {"tipo": "manual"}),
    ("Responde a la entrada del usuario (teclado o clic) sin errores", {"tipo": "manual"}),
]
_CALIDAD_PY_GUI = [
    ("Sintaxis y lint limpios", {"tipo": "probar", "args": "{entrypoint}", "espera": r"sintaxis OK"}),
    ("La ventana abre y sigue viva sin tracebacks", {"tipo": "app", "args": "python {entrypoint} | pasos=espera 800; captura",
                                                     "espera": r"ventana '"}),
]
_CALIDAD_PY_CLI = [
    ("Sintaxis y lint limpios", {"tipo": "probar", "args": "{entrypoint}", "espera": r"sintaxis OK"}),
    ("Arranca sin traceback", {"tipo": "ejecutar", "args": "python {entrypoint} --help", "espera": r"^(?!.*Traceback)"}),
]
_VISUAL_GENERICO = [
    ("No hay elementos superpuestos ni cortados", {"tipo": "manual"}),
    ("Jerarquia visual clara (titulos, botones, contenido)", {"tipo": "manual"}),
    ("Estilo consistente (tipografia, colores, espaciado)", {"tipo": "manual"}),
]


def automatica(encargo: str, tipo_producto: str = "", entrypoint: str = "") -> dict:
    """DoD minima derivada del enunciado (requisitos enumerados via
    contrato_tarea.derivar) + calidad/visual estandar por tipo de producto."""
    try:
        from cognia.harness.contrato_tarea import derivar
        reqs = list(derivar(encargo or "", 25))
    except Exception:
        reqs = []
    # las lineas enumeradas del enunciado (1. / - / *) entran aunque sean
    # cortas: derivar filtra por longitud y "Hay marcador" se perdia
    for m in re.finditer(r"(?m)^\s*(?:\d+[.)]|[-*\u2022])\s+(.+?)\s*$", encargo or ""):
        t = m.group(1).strip().rstrip(".")
        if len(t) >= 4 and all(t.lower() != r.lower().rstrip(".") for r in reqs):
            reqs.append(t)
    if not reqs:
        reqs = [r.strip() for r in re.split(r"[.;\n]", encargo or "") if len(r.strip()) > 12][:12]
    if not reqs:
        reqs = [(encargo or "producto pedido").strip()[:200]]
    funcionales = [{"texto": r, "verif": {"tipo": "manual"}} for r in reqs]
    ep = entrypoint or "{entrypoint}"
    tp = (tipo_producto or "").lower()
    if tp == "web":
        calidad, visuales = _CALIDAD_WEB, _VISUAL_GENERICO
    elif tp == "python_gui":
        calidad, visuales = _CALIDAD_PY_GUI, _VISUAL_GENERICO
    elif tp in ("python_cli", "python"):
        calidad, visuales = _CALIDAD_PY_CLI, [("La salida en consola es legible y consistente", {"tipo": "manual"})]
    else:
        calidad, visuales = [("Sin errores en consola ni crashes", {"tipo": "manual"})], _VISUAL_GENERICO
    calidad = [{"texto": t, "verif": {k: (v.replace("{entrypoint}", ep) if isinstance(v, str) else v) for k, v in vf.items()}}
               for t, vf in calidad]
    visuales = [{"texto": t, "verif": vf} for t, vf in visuales]
    return normalizar({"funcionales": funcionales, "visuales": visuales, "calidad": calidad})


def plantilla_para_modelo(tipo_producto: str = "") -> str:
    """El formato exacto que se le pide al planificador."""
    return (
        '```json\n{\n  "tipo_producto": "web | python_gui | python_cli | node | otro",\n'
        '  "entrypoint": "index.html | juego.py | ...",\n'
        '  "arquitectura": "3-6 lineas: modulos/ficheros y responsabilidad de cada uno",\n'
        '  "funcionales": [\n'
        '    {"texto": "el jugador se mueve con las flechas", "tipo": "guion", '
        '"args": "index.html | vars=player.x | guion=tecla derecha*3; assert player.x>0"},\n'
        '    {"texto": "el menu permite iniciar partida", "tipo": "guion", '
        '"args": "index.html | guion=clic #jugar; esperar \\"puntos\\" 2000; assert texto contiene \\"puntos\\""},\n'
        '    {"texto": "la CLI suma dos numeros", "tipo": "ejecutar", "args": "python calc.py 2 3", "espera": "^5"},\n'
        '    {"texto": "los tests pasan", "tipo": "tests", "args": "tests/"}\n'
        '  ],\n'
        '  "visuales": [\n'
        '    {"texto": "el HUD no tapa el area de juego", "tipo": "manual"},\n'
        '    {"texto": "la pagina no desborda a 360px", "tipo": "probar", "args": "index.html", "espera": "sin errores"}\n'
        '  ],\n'
        '  "calidad": [\n'
        '    {"texto": "sin errores de consola", "tipo": "probar", "args": "index.html", "espera": "sin errores de consola"},\n'
        '    {"texto": "la ventana abre sin traceback", "tipo": "app", "args": "python juego.py | pasos=espera 800; captura", "espera": "ventana"}\n'
        '  ]\n}\n```\n'
        "Tipos de verificacion: tests (pytest en verde), ejecutar (comando, exit 0 y regex en `espera`), "
        "probar (la tool probar sobre un fichero/URL, regex en `espera`), guion (renderizar con guion y "
        "asserts: cada assert tiene que pasar), app (app_probar con pasos: sin traceback y regex en `espera`), "
        "manual (lo juzga QA con evidencia). Cada requisito con verificacion ejecutable vale mas que tres manuales."
    )
