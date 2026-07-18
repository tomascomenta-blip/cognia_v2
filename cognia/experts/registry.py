"""
cognia/experts/registry.py
==========================
Registro persistente de expertos (perfiles de modelo con dedicacion).

Un experto une un modelo concreto (GGUF de node/fleet.py, un modelo de
ollama, o los shards INT4 LOGOS/TECHNE/RHETOR) con una dedicacion en una
linea y un system prompt propio opcional.

Los builtin viven en codigo (BUILTIN_EXPERTS). Los custom y los overrides
de builtin (p.ej. enabled=False) se persisten en JSON:

    ~/.cognia/experts/registry.json     (override: COGNIA_EXPERTS_DIR)

Al cargar, custom pisa builtin por id (mismo patron que config.env: el
archivo del usuario gana sobre el default de codigo).

Uso:
    from cognia.experts import load_registry, render_modelos_table
    print(render_modelos_table(load_registry(), fleet_status()))
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

# Backends soportados: gguf = flota local llama.cpp (node/fleet.py),
# ollama = servidor ollama, shards = sub-modelos INT4 (shattering/).
BACKENDS = ("gguf", "ollama", "shards")

# Slug: minusculas, digitos y guiones; empieza alfanumerico.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class Expert:
    """Un experto: modelo + dedicacion + system prompt opcional."""
    id:                 str          # slug unico, ej. "cerebro-principal"
    nombre:             str          # nombre humano, ej. "Cerebro principal"
    dedicacion:         str          # 1 linea, ej. "chat general del dia a dia"
    model_key:          str          # key de node/fleet.py, nombre ollama o sub-modelo shards
    backend:            str          # "gguf" | "ollama" | "shards"
    system_prompt_file: str | None = None   # relativo a experts_dir(), ej. "<id>/system_prompt.md"
    adapter_file:       str | None = None   # reservado (adapters ELC), None por ahora
    builtin:            bool = False
    enabled:            bool = True


# Expertos de fabrica, derivados de lo que existe hoy:
# - gguf: keys de node/fleet.py (FLEET: coder-0.5b / chat-7b / coder-14b).
# - shards: sub-modelos del GlobalRouter (shattering/router.py: logos/techne/rhetor).
BUILTIN_EXPERTS: tuple[Expert, ...] = (
    Expert(
        id="cerebro-principal",
        nombre="Cerebro principal",
        dedicacion="chat general del dia a dia",
        model_key="chat-7b",
        backend="gguf",
        builtin=True,
    ),
    Expert(
        id="programador",
        nombre="Programador",
        dedicacion="codigo de calidad",
        model_key="coder-14b",
        backend="gguf",
        builtin=True,
    ),
    Expert(
        id="portero-draft",
        nombre="Portero draft",
        dedicacion="borradores rapidos para speculative decoding",
        model_key="coder-0.5b",
        backend="gguf",
        builtin=True,
    ),
    Expert(
        id="razonador-logos",
        nombre="Razonador Logos",
        dedicacion="razonamiento y conocimiento comun",
        model_key="logos",
        backend="shards",
        builtin=True,
    ),
    Expert(
        id="tecnico-techne",
        nombre="Tecnico Techne",
        dedicacion="codigo y tecnica en INT4 local",
        model_key="techne",
        backend="shards",
        builtin=True,
    ),
    Expert(
        id="comunicador-rhetor",
        nombre="Comunicador Rhetor",
        dedicacion="redaccion y estilo",
        model_key="rhetor",
        backend="shards",
        builtin=True,
    ),
)

_BUILTIN_IDS = {e.id for e in BUILTIN_EXPERTS}


# -- Paths ------------------------------------------------------------------

def experts_dir() -> Path:
    """Directorio de expertos; COGNIA_EXPERTS_DIR permite override (tests)."""
    override = os.environ.get("COGNIA_EXPERTS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".cognia" / "experts"


def registry_path() -> Path:
    """Ruta del JSON con los expertos custom y overrides de builtin."""
    return experts_dir() / "registry.json"


def system_prompt_path(expert: Expert) -> Path | None:
    """Ruta absoluta al system prompt del experto, o None si no tiene."""
    if not expert.system_prompt_file:
        return None
    return experts_dir() / expert.system_prompt_file


# -- Carga / persistencia ---------------------------------------------------

def _expert_from_dict(d: dict) -> Expert | None:
    """Construye Expert desde un dict del JSON; None si es inusable."""
    if not isinstance(d, dict) or not d.get("id"):
        return None
    return Expert(
        id=str(d["id"]),
        nombre=str(d.get("nombre", d["id"])),
        dedicacion=str(d.get("dedicacion", "")),
        model_key=str(d.get("model_key", "")),
        backend=str(d.get("backend", "gguf")),
        system_prompt_file=d.get("system_prompt_file") or None,
        adapter_file=d.get("adapter_file") or None,
        builtin=bool(d.get("builtin", False)),
        enabled=bool(d.get("enabled", True)),
    )


def _load_custom() -> list[Expert]:
    """Lee registry.json; JSON ausente o corrupto degrada a lista vacia."""
    path = registry_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        e = _expert_from_dict(d)
        if e is not None:
            out.append(e)
    return out


def load_registry() -> list[Expert]:
    """
    Lista completa de expertos: builtin + custom mergeados.
    Custom pisa builtin por id (el override conserva builtin=True).
    Orden: builtin primero (orden de BUILTIN_EXPERTS), luego custom.
    """
    merged: dict[str, Expert] = {e.id: replace(e) for e in BUILTIN_EXPERTS}
    order: list[str] = [e.id for e in BUILTIN_EXPERTS]
    for e in _load_custom():
        e.builtin = e.id in _BUILTIN_IDS  # el flag lo decide el codigo, no el JSON
        if e.id not in merged:
            order.append(e.id)
        merged[e.id] = e
    return [merged[i] for i in order]


def save_custom(experts: list[Expert]) -> None:
    """
    Persiste en registry.json solo lo que difiere del codigo: expertos
    custom y builtin modificados. Un builtin identico a su default no
    se escribe (asi los defaults de codigo pueden evolucionar).
    """
    defaults = {e.id: e for e in BUILTIN_EXPERTS}
    out = []
    for e in experts:
        d = defaults.get(e.id)
        if d is not None and asdict(e) == asdict(d):
            continue
        out.append(asdict(e))
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


# -- Operaciones ------------------------------------------------------------

def get_expert(expert_id: str) -> Expert | None:
    """Devuelve el experto por id, o None si no existe."""
    for e in load_registry():
        if e.id == expert_id:
            return e
    return None


def add_expert(expert_id: str, nombre: str, dedicacion: str, model_key: str,
               backend: str, system_prompt_file: str | None = None,
               adapter_file: str | None = None, enabled: bool = True) -> Expert:
    """
    Agrega un experto custom y lo persiste. Valida slug, backend y que el
    id no exista ya (ni builtin ni custom). Lanza ValueError si algo falla.
    """
    if not _SLUG_RE.match(expert_id or ""):
        raise ValueError(f"id invalido (usar minusculas/digitos/guiones): {expert_id!r}")
    if backend not in BACKENDS:
        raise ValueError(f"backend invalido: {backend!r} (validos: {', '.join(BACKENDS)})")
    if not model_key.strip():
        raise ValueError("model_key vacio")
    experts = load_registry()
    if any(e.id == expert_id for e in experts):
        raise ValueError(f"ya existe un experto con id: {expert_id}")
    nuevo = Expert(
        id=expert_id,
        nombre=nombre.strip() or expert_id,
        dedicacion=dedicacion.strip(),
        model_key=model_key.strip(),
        backend=backend,
        system_prompt_file=system_prompt_file,
        adapter_file=adapter_file,
        builtin=False,
        enabled=enabled,
    )
    experts.append(nuevo)
    save_custom(experts)
    return nuevo


def remove_expert(expert_id: str) -> Expert:
    """
    Quita un experto custom y persiste. Los builtin no se pueden quitar
    (solo desactivar con set_enabled). Lanza ValueError si es builtin o
    no existe. Devuelve el experto quitado.
    """
    if expert_id in _BUILTIN_IDS:
        raise ValueError(f"'{expert_id}' es de fabrica: no se quita, se desactiva "
                         f"(set_enabled('{expert_id}', False))")
    experts = load_registry()
    for e in experts:
        if e.id == expert_id:
            experts.remove(e)
            save_custom(experts)
            return e
    raise ValueError(f"experto desconocido: {expert_id}")


def set_enabled(expert_id: str, enabled: bool) -> Expert:
    """
    Activa/desactiva un experto (builtin o custom) y persiste. Para un
    builtin esto crea un override en el JSON. Lanza ValueError si no existe.
    """
    experts = load_registry()
    for e in experts:
        if e.id == expert_id:
            e.enabled = bool(enabled)
            save_custom(experts)
            return e
    raise ValueError(f"experto desconocido: {expert_id}")


def save_adapter_file(expert_id: str, adapter_dir: str) -> Expert:
    """
    Registra la ruta del adapter LoRA entrenado para un experto (modalidad 2
    del alta) y persiste. Lanza ValueError si el experto no existe.
    """
    experts = load_registry()
    for e in experts:
        if e.id == expert_id:
            e.adapter_file = str(adapter_dir)
            save_custom(experts)
            return e
    raise ValueError(f"experto desconocido: {expert_id}")


# -- Vista /modelos ---------------------------------------------------------

def _estado_modelo(expert: Expert, fleet_by_key: dict) -> str:
    """Etiqueta de estado del modelo: OK X GB / FALTA / ollama / shards."""
    if expert.backend == "gguf":
        m = fleet_by_key.get(expert.model_key)
        if m is None:
            return "gguf"
        if m.get("presente"):
            return f"OK {m.get('gb', 0):.2f} GB"
        return "FALTA"
    return expert.backend  # "ollama" | "shards": sin chequeo de disco aca


def render_modelos_table(experts: list[Expert],
                         fleet_status: list[dict] | None = None) -> str:
    """
    Vista de texto plano del comando /modelos (sin rich: el cli decide si
    lo envuelve en un panel). Builtin primero, custom despues. Por experto:
    NOMBRE en mayusculas + dedicacion, y debajo el modelo con su estado.
    fleet_status es la salida de node.fleet.fleet_status() (inyectable).
    """
    fleet_by_key = {m.get("key"): m for m in (fleet_status or [])}
    lines = ["EXPERTOS", "========", ""]

    def _bloque(grupo: list[Expert]) -> None:
        for e in grupo:
            marca = "" if e.enabled else "  (desactivado)"
            lines.append(f"{e.nombre.upper()} -- {e.dedicacion}{marca}")
            lines.append(f"  -> modelo: {e.model_key} [{_estado_modelo(e, fleet_by_key)}]")
            lines.append("")

    _bloque([e for e in experts if e.builtin])
    customs = [e for e in experts if not e.builtin]
    if customs:
        lines.append("-- Personalizados --")
        lines.append("")
        _bloque(customs)
    return "\n".join(lines).rstrip() + "\n"
