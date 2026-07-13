r"""
cognia/agent/plan_artifact.py — plan como ARTEFACTO MUTABLE (patrón OpenManus)
=============================================================================
De la investigación (AGENCIA_RESEARCH, OpenManus PlanningFlow): el plan de una
tarea multi-paso conviene tenerlo como un ARTEFACTO con estado por paso
([ ] pendiente / [→] en curso / [x] hecho), separado del historial, que el
loop consulta y ACTUALIZA — no como texto perdido entre los mensajes.

Verificación previa (regla del repo): el loop de Cognia YA tiene lo demás de
OpenManus y mejor — is_stuck (register_action: cuenta acciones idénticas y
ciclos oscilantes, avisa nombrando la acción, sube la temperatura, cierra
honesto) y terminate (la tool `responder` es el cierre explícito). Lo único
que faltaba es este plan mutable; es lo único que se agrega.

Concreto: una clase plana + persistencia JSON en el workspace del agente, así
sobrevive entre pasos y el agente lo relee. Se expone como tool `plan`.
"""
from __future__ import annotations

import json
from pathlib import Path

PENDIENTE, EN_CURSO, HECHO = " ", "→", "x"
_MARCAS = {"pendiente": PENDIENTE, "en_curso": EN_CURSO, "hecho": HECHO,
           " ": PENDIENTE, "→": EN_CURSO, "x": HECHO, "done": HECHO,
           "doing": EN_CURSO, "todo": PENDIENTE}


class Plan:
    """Lista de pasos con estado por paso. Serializable a JSON."""

    def __init__(self, objetivo: str = "", pasos: list | None = None):
        self.objetivo = objetivo
        # cada paso: {"texto": str, "estado": " "|"→"|"x"}
        self.pasos = [{"texto": p, "estado": PENDIENTE} for p in (pasos or [])]

    # ── mutación ──
    def marcar(self, idx: int, estado: str) -> bool:
        e = _MARCAS.get((estado or "").strip().lower(), None)
        if e is None or not (0 <= idx < len(self.pasos)):
            return False
        self.pasos[idx]["estado"] = e
        return True

    def avanzar(self) -> int | None:
        """Marca el paso EN_CURSO actual como hecho y el siguiente pendiente
        como en_curso. Devuelve el índice ahora en_curso, o None si no quedan."""
        for p in self.pasos:
            if p["estado"] == EN_CURSO:
                p["estado"] = HECHO
                break
        for i, p in enumerate(self.pasos):
            if p["estado"] == PENDIENTE:
                p["estado"] = EN_CURSO
                return i
        return None

    def siguiente_pendiente(self) -> int | None:
        for i, p in enumerate(self.pasos):
            if p["estado"] in (PENDIENTE, EN_CURSO):
                return i
        return None

    def completo(self) -> bool:
        return bool(self.pasos) and all(p["estado"] == HECHO for p in self.pasos)

    # ── render (para el prompt del loop) ──
    def render(self) -> str:
        if not self.pasos:
            return "PLAN: (vacío)"
        cab = f"PLAN{f' — {self.objetivo}' if self.objetivo else ''}:"
        filas = [f"  [{p['estado']}] {i+1}. {p['texto']}"
                 for i, p in enumerate(self.pasos)]
        return cab + "\n" + "\n".join(filas)

    # ── persistencia ──
    def to_dict(self) -> dict:
        return {"objetivo": self.objetivo, "pasos": self.pasos}

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        p = cls(d.get("objetivo", ""))
        p.pasos = [{"texto": s.get("texto", ""),
                    "estado": _MARCAS.get(s.get("estado", " "), PENDIENTE)}
                   for s in d.get("pasos", [])]
        return p

    def guardar(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def cargar(cls, path: str | Path) -> "Plan | None":
        path = Path(path)
        if not path.is_file():
            return None
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None


def _plan_path() -> Path:
    """Ruta del plan en el workspace del agente (sobrevive entre pasos)."""
    try:
        from cognia.agents.workers.dev_tools import AGENT_WORKSPACE_ROOT
        base = Path(AGENT_WORKSPACE_ROOT)
    except Exception:
        base = Path.home() / ".cognia"
    return base / ".plan.json"


def parse_pasos(texto: str) -> list:
    """Extrae pasos de una lista numerada (salida típica del decompose)."""
    import re
    pasos = []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        m = re.match(r"^(?:\d+[.)]\s*|[-*]\s+)(.+)$", linea)
        if m:
            pasos.append(m.group(1).strip())
    return pasos


# ── tool `plan` (ver / crear / marcar) para el loop del agente ──────────────
def register(tool_decorator) -> None:
    @tool_decorator(
        "plan",
        "plan [ver | crear <lista numerada> | marcar <n> <hecho|en_curso>] -- "
        "gestiona el plan de la tarea (artefacto con estado por paso)",
        danger=False)
    def _t_plan(args, ctx):
        path = _plan_path()
        partes = (args or "").strip().split(None, 1)
        sub = (partes[0].lower() if partes else "ver")
        resto = partes[1] if len(partes) > 1 else ""
        if sub in ("", "ver"):
            p = Plan.cargar(path)
            return ("RESULTADO plan:\n" + p.render()) if p else \
                "RESULTADO plan: (no hay plan; crealo con 'plan crear <lista>')"
        if sub == "crear":
            pasos = parse_pasos(resto)
            if not pasos:
                return "RESULTADO plan ERROR: no pude parsear pasos numerados"
            p = Plan(objetivo="", pasos=pasos)
            if p.pasos:
                p.pasos[0]["estado"] = EN_CURSO
            p.guardar(path)
            return "RESULTADO plan creado:\n" + p.render()
        if sub == "marcar":
            mp = resto.split(None, 1)
            if len(mp) < 2 or not mp[0].isdigit():
                return "RESULTADO plan ERROR: formato (marcar <n> <estado>)"
            p = Plan.cargar(path)
            if p is None:
                return "RESULTADO plan ERROR: no hay plan"
            ok = p.marcar(int(mp[0]) - 1, mp[1])
            if not ok:
                return "RESULTADO plan ERROR: paso o estado invalido"
            p.guardar(path)
            estado = "COMPLETO" if p.completo() else "en progreso"
            return f"RESULTADO plan ({estado}):\n" + p.render()
        return f"RESULTADO plan ERROR: subcomando '{sub}' desconocido (ver|crear|marcar)"
