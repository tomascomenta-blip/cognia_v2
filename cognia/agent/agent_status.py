"""
cognia/agent/agent_status.py
============================
Visibilidad del subsistema agente para un manager (autonomo o humano): un
snapshot de lo que hoy es OPACO -- si el daemon de auto-sintesis de tools esta
vivo, que ideas/wanted-tools esperan, que tools generadas hay y en que tier,
y los contadores de uso reales (builtin + generadas).

Cero dependencias nuevas: lee las mismas tablas/archivos que ya escriben
background_research (tool_ideas/wanted_tools), tool_synthesis (_manifest.json)
y tools (_tool_usage.json / _bon_telemetry.jsonl). Best-effort: cualquier
fuente ausente/corrupta se reporta como vacia, nunca levanta.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_GEN_DIR = Path(__file__).parent / "generated_tools"


def _daemon_pulse() -> dict:
    """Ultimo latido del daemon de research: mtime del log si existe. El
    daemon (scripts/cognia_research_daemon.py) no deja PID, asi que 'vivo' se
    infiere de un log reciente -- se reporta el mtime crudo y el caller decide."""
    import datetime
    candidates = [
        Path(__file__).parent.parent.parent / "research_daemon.log",
        Path(__file__).parent.parent.parent / "logs" / "research_daemon.log",
    ]
    for p in candidates:
        try:
            if p.exists():
                ts = datetime.datetime.fromtimestamp(p.stat().st_mtime)
                return {"log": str(p), "last": ts.isoformat(timespec="seconds")}
        except Exception:
            continue
    return {"log": None, "last": None}


def _manifest_tiers(db_path: str = None) -> dict:
    """Conteo de tools generadas por tier desde _manifest.json."""
    out = {"staged": 0, "verified": 0, "retired": 0, "total": 0, "names": []}
    try:
        from cognia.agent.tool_synthesis import _load_manifest
        for e in _load_manifest():
            tier = e.get("tier", "staged")
            out[tier] = out.get(tier, 0) + 1
            out["total"] += 1
            out["names"].append(f"{e.get('name')}({tier} v{e.get('version','?')})")
    except Exception:
        pass
    return out


def _tool_usage_top(n: int = 8) -> list:
    """Top-N tools por llamadas (builtin + generadas), desde _tool_usage.json."""
    try:
        from cognia.agent.tools import get_tool_usage
        usage = get_tool_usage()
    except Exception:
        usage = {}
    rows = sorted(usage.items(), key=lambda kv: kv[1].get("calls", 0), reverse=True)
    return [{"tool": k, **v} for k, v in rows[:n]]


def _bon_telemetry_tail(n: int = 5) -> list:
    """Ultimas N corridas de generar_codigo (dificultad, rank, score, secs)."""
    p = _GEN_DIR / "_bon_telemetry.jsonl"
    try:
        lines = p.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def agent_status_snapshot(db_path: str = None) -> dict:
    """Snapshot completo del subsistema agente. Best-effort por fuente."""
    from cognia.config import DB_PATH
    db = db_path or DB_PATH
    snap = {"daemon": _daemon_pulse(), "generated_tools": _manifest_tiers(),
            "tool_usage_top": _tool_usage_top(), "bon_recent": _bon_telemetry_tail()}
    # Cola de ideas y wishlist pendiente (lo que el daemon procesaria).
    try:
        from cognia.agent.background_research import (
            pending_tool_ideas, unprocessed_wanted_tools,
        )
        snap["pending_ideas"] = pending_tool_ideas(limit=10, db_path=db)
        snap["wanted_pending"] = unprocessed_wanted_tools(min_hits=1, limit=10,
                                                          db_path=db)
    except Exception:
        snap["pending_ideas"] = []
        snap["wanted_pending"] = []
    return snap


def format_agent_status(snap: dict) -> str:
    """Reporte ASCII legible del snapshot (para /agente estado)."""
    L = []
    d = snap.get("daemon", {})
    L.append("== Estado del subsistema agente ==")
    L.append(f"Daemon de auto-sintesis: " + (
        f"log {d.get('last')}" if d.get("last") else "sin log (no lanzado?)"))

    gt = snap.get("generated_tools", {})
    L.append(f"Tools generadas: {gt.get('total', 0)} "
             f"(staged {gt.get('staged', 0)}, verified {gt.get('verified', 0)}, "
             f"retired {gt.get('retired', 0)})")
    for nm in gt.get("names", [])[:8]:
        L.append(f"  - {nm}")

    ideas = snap.get("pending_ideas", [])
    L.append(f"Ideas de tool en cola: {len(ideas)}")
    for it in ideas[:5]:
        L.append(f"  - {it.get('name')}: {str(it.get('purpose',''))[:60]}")

    wanted = snap.get("wanted_pending", [])
    L.append(f"Wishlist pendiente (pedidas y no cubiertas): {len(wanted)}")
    for w in wanted[:5]:
        L.append(f"  - {w.get('name')} (hits {w.get('hits')})")

    usage = snap.get("tool_usage_top", [])
    if usage:
        L.append("Tools mas usadas:")
        for u in usage:
            L.append(f"  - {u.get('tool')}: {u.get('calls',0)} llamadas "
                     f"({u.get('ok',0)} ok / {u.get('fail',0)} fail)")

    bon = snap.get("bon_recent", [])
    if bon:
        L.append("generar_codigo reciente (dificultad -> resultado):")
        for b in bon:
            L.append(f"  - dif={b.get('difficulty')} n={b.get('n_generated')} "
                     f"rank={b.get('rank_mode')} "
                     f"tests={b.get('score')}/{b.get('total')} {b.get('secs')}s")
    return "\n".join(L)
