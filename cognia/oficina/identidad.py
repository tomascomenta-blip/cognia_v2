# -*- coding: utf-8 -*-
"""
cognia/oficina/identidad.py — identidad visual de los modelos del fleet
=======================================================================
La oficina 3D pinta trabajadores por ROL (investigador/implementador), no por
QUÉ modelo del FLEET-30 los ejecuta. El mandato del dueño (2026-07-13): que
cada modelo aparezca con su NOMBRE, un COLOR de camisa propio y agrupado por
DEPARTAMENTO — una oficina global dividida, no una flota indistinta.

Este módulo es la fuente única de esa identidad visual. Es DATOS + resolución:
mapea cada `key` del fleet (fleet30.json + los 3 servers históricos) a
{nombre, depto, color, rol_visual, descripcion}. Cero dependencias pesadas;
lo consume el server de la oficina (endpoint /api/fleet) y el front (derivar).

Regla: un modelo sin identidad declarada NO rompe — cae a una identidad
derivada (nombre del key, depto "General", color gris). Así el registry puede
crecer sin tocar la UI.
"""
from __future__ import annotations

import json
from pathlib import Path

# ── Departamentos: agrupan por función cognitiva, con un color base ─────────
DEPARTAMENTOS = {
    "direccion":     {"nombre": "Dirección",     "color": "#D4AF37"},   # dorado
    "ingenieria":    {"nombre": "Ingeniería",    "color": "#2E6FDB"},   # azul
    "razonamiento":  {"nombre": "Razonamiento",  "color": "#7B4FD4"},   # violeta
    "recepcion":     {"nombre": "Recepción",     "color": "#2FB37A"},   # verde
    "datos":         {"nombre": "Datos y Memoria", "color": "#E08A2E"}, # naranja
    "general":       {"nombre": "General",       "color": "#8A8F98"},   # gris
}

# ── Identidad por key del fleet (nombre humano + depto + tinte de camisa) ───
# color = tinte propio de la camisa (variación del color del depto para que
# dos modelos del mismo depto se distingan de un vistazo).
IDENTIDADES = {
    # Dirección (el orquestador jerárquico de la oficina)
    "jefe":        {"nombre": "Dante",  "depto": "direccion",   "color": "#D4AF37",
                    "rol_visual": "mega_jefe", "descripcion": "Orquestador: descompone metas en directivas"},
    # Ingeniería (código)
    "3b":          {"nombre": "Cora",   "depto": "ingenieria",  "color": "#2E6FDB",
                    "rol_visual": "implementador", "descripcion": "Agente principal 3B — la cara de Cognia"},
    "coder15b":    {"nombre": "Fito",   "depto": "ingenieria",  "color": "#4B8AF0",
                    "rol_visual": "implementador", "descripcion": "Autocompletado FIM rápido (1.5B)"},
    "qwen35_4b":   {"nombre": "Max",    "depto": "ingenieria",  "color": "#1E4FA8",
                    "rol_visual": "implementador", "descripcion": "Código top — etapa 3 de la cascada"},
    "nextcoder7b": {"nombre": "Rex",    "depto": "ingenieria",  "color": "#3866B0",
                    "rol_visual": "implementador", "descripcion": "Reparación y edición de código (7B)"},
    "7b":          {"nombre": "Goliat", "depto": "ingenieria",  "color": "#12305F",
                    "rol_visual": "implementador", "descripcion": "Especialista pesado 7B (código duro)"},
    # Razonamiento
    "qwen3_4b":    {"nombre": "Sabio",  "depto": "razonamiento", "color": "#7B4FD4",
                    "rol_visual": "investigador", "descripcion": "Razonamiento y tool-calling (4B, 92.5% G2R)"},
    "vibethinker15b": {"nombre": "Vera", "depto": "razonamiento", "color": "#9A6FEC",
                    "rol_visual": "investigador", "descripcion": "Matemática de competencia (1.5B)"},
    # Recepción (turnos rápidos / chat)
    "portero":     {"nombre": "Nico",   "depto": "recepcion",   "color": "#2FB37A",
                    "rol_visual": "investigador", "descripcion": "Portero 0.5B — saludos y turnos triviales"},
    "lfm25_12b":   {"nombre": "Lía",    "depto": "recepcion",   "color": "#4FD69A",
                    "rol_visual": "investigador", "descripcion": "Generalista rápida (1.2B)"},
    # Datos y memoria
    "qwen3_embed": {"nombre": "Indi",   "depto": "datos",       "color": "#E08A2E",
                    "rol_visual": "investigador", "descripcion": "Embedder 0.6B — índice del conocimiento"},
}

# Los 3 servers históricos NO están en fleet30.json; se agregan al roster.
HISTORICOS = [
    {"key": "3b",      "role": "agente",  "port": 8088},
    {"key": "portero", "role": "portero", "port": 8090},
    {"key": "7b",      "role": "heavy",   "port": 8092},
]


def _manifest_path() -> Path | None:
    import os
    env = os.environ.get("COGNIA_FLEET30_MANIFEST", "").strip()
    if env and Path(env).is_file():
        return Path(env)
    home = Path.home() / ".cognia" / "models" / "fleet30.json"
    if home.is_file():
        return home
    repo = Path(__file__).resolve().parents[2] / "shattering" / "manifests" / "fleet30.json"
    return repo if repo.is_file() else None


def _titulo(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").title()


def identidad(key: str) -> dict:
    """Identidad visual de un modelo (fallback derivado si no está declarada)."""
    base = IDENTIDADES.get(key)
    if base is None:
        return {"key": key, "nombre": _titulo(key), "depto": "general",
                "depto_nombre": DEPARTAMENTOS["general"]["nombre"],
                "color": DEPARTAMENTOS["general"]["color"],
                "rol_visual": "investigador",
                "descripcion": ""}
    depto = base["depto"]
    return {"key": key, "nombre": base["nombre"], "depto": depto,
            "depto_nombre": DEPARTAMENTOS[depto]["nombre"],
            "color": base["color"], "rol_visual": base["rol_visual"],
            "descripcion": base.get("descripcion", "")}


def roster() -> list[dict]:
    """Lista de TODOS los miembros (fleet30 + históricos) con identidad visual
    + metadatos operativos (role, port, ram_gb) donde existan. Ordenada por
    departamento (según DEPARTAMENTOS) y luego por nombre."""
    miembros: dict[str, dict] = {}
    # históricos primero (para que el 3B/portero/7B siempre estén)
    for h in HISTORICOS:
        miembros[h["key"]] = dict(h)
    # fleet30.json
    path = _manifest_path()
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for m in data.get("members", []):
                k = m.get("key")
                if k:
                    miembros[k] = {"key": k, "role": m.get("role"),
                                   "port": m.get("port"),
                                   "ram_gb": m.get("ram_gb")}
        except Exception:
            pass
    out = []
    for k, op in miembros.items():
        ide = identidad(k)
        ide.update({"role": op.get("role"), "port": op.get("port"),
                    "ram_gb": op.get("ram_gb")})
        out.append(ide)
    orden_depto = list(DEPARTAMENTOS.keys())
    out.sort(key=lambda m: (orden_depto.index(m["depto"])
                            if m["depto"] in orden_depto else 99, m["nombre"]))
    return out


# Modelo REPRESENTATIVO por función de la tarea, para que la oficina muestre
# departamentos con sentido. El motor jerárquico corre vía el orquestador
# (no un modelo por tarea literal); esto es el mapeo de DISPLAY que refleja
# qué modelo encarna cada función (coherente con el ruteo real: implementador
# = 3B base, director/razonamiento = 4B, etc.).
_MODELO_POR_ROL = {
    "jefe": "jefe",              # Dante — Dirección
    "mega_jefe": "jefe",
    "director": "qwen3_4b",      # Sabio — Razonamiento (planifica)
    "investigador": "lfm25_12b",  # Lía — Recepción (busca/lee rápido)
    "implementador": "3b",       # Cora — Ingeniería (codea)
}


def modelo_por_rol(rol: str | None) -> str | None:
    """Key del modelo representativo para un rol de tarea (display de la
    oficina). None si el rol no mapea (el trabajador cae al color por rol)."""
    return _MODELO_POR_ROL.get((rol or "").strip().lower())


# Modelo RECOMENDADO por tipo de tool: qué miembro del fleet encara mejor cada
# herramienta (para los flujos "divididos por modelo"). Coherente con el ruteo
# real: código→Max, razonar/planear→Sabio, buscar/leer→Lía, ejecutar→Cora,
# memoria/KG→Indi.
_MODELO_POR_TOOL = {
    "generar_codigo": "qwen35_4b", "py_validar": "qwen35_4b",
    "crear_flujo": "qwen3_4b", "plan": "qwen3_4b", "resumir": "qwen3_4b",
    "buscar": "lfm25_12b", "listar": "lfm25_12b", "arbol": "lfm25_12b",
    "leer_archivo": "lfm25_12b", "contar_lineas": "lfm25_12b",
    "http_get": "lfm25_12b",
    "tests": "3b", "ejecutar": "3b", "escribir_archivo": "3b",
    "apendar_archivo": "3b", "copiar_archivo": "3b", "responder": "3b",
    "kg_buscar": "qwen3_embed", "kg_agregar": "qwen3_embed",
    "recordar": "qwen3_embed", "memorizar": "qwen3_embed",
}


def recomendar_modelo(tool: str | None) -> str:
    """Key del modelo que Cognia recomienda para ejecutar una tool (default
    3b = Cora). Se usa para colorear los nodos del flujo por modelo."""
    return _MODELO_POR_TOOL.get((tool or "").strip().lower(), "3b")


def departamentos() -> list[dict]:
    """Departamentos con sus miembros anidados (para la vista global por deptos)."""
    r = roster()
    out = []
    for dkey, dmeta in DEPARTAMENTOS.items():
        miembros = [m for m in r if m["depto"] == dkey]
        if not miembros:
            continue
        out.append({"key": dkey, "nombre": dmeta["nombre"],
                    "color": dmeta["color"], "miembros": miembros})
    return out


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for d in departamentos():
        print(f"\n== {d['nombre']} ({d['color']}) ==")
        for m in d["miembros"]:
            print(f"  {m['nombre']:8s} [{m['key']}] {m['color']}  "
                  f":{m.get('port')}  {m['descripcion']}")
